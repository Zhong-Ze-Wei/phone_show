"""遗留查询脚本的配置迁移与可选依赖边界。"""

import builtins
import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

from get_data import get_data as enhanced
from get_data import simple_get_data as simple
from phone_assistant import config
from phone_assistant.config import Settings

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("filename", ["get_data.py", "simple_get_data.py"])
def test_import_does_not_load_settings_or_optional_crawler(monkeypatch, filename):
    def unexpected_call(*args, **kwargs):
        raise AssertionError("导入不应读取凭据或创建客户端")

    monkeypatch.setattr(Settings, "from_env", unexpected_call)
    monkeypatch.setattr(config, "create_client", unexpected_call)
    original_import = builtins.__import__

    def without_crawler(name, *args, **kwargs):
        if name == "agno" or name.startswith("agno."):
            raise AssertionError("基础环境导入不应加载 Agno")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_crawler)
    spec = importlib.util.spec_from_file_location(
        "legacy_import_check", PROJECT_ROOT / "get_data" / filename
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)


def test_legacy_sources_do_not_embed_api_credentials():
    credential = re.compile(r"\b(?:sk-[A-Za-z0-9]{20,}|QC-[A-Za-z0-9-]{20,})")
    for filename in ("get_data.py", "simple_get_data.py"):
        source = (PROJECT_ROOT / "get_data" / filename).read_text(encoding="utf-8-sig")
        assert credential.search(source) is None
        assert "api.siliconflow.cn" not in source


def test_simple_query_uses_configured_model_and_marks_unverified(monkeypatch):
    settings = Settings(api_key="test-api-key", model="test-flash-model")
    client = MagicMock()
    client.__enter__.return_value = client
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="待核实参考"))]
    )
    factory = Mock(return_value=client)
    monkeypatch.setattr(simple, "create_client", factory)

    assert simple.query_earnings("AAPL", settings=settings) == "待核实参考"

    factory.assert_called_once_with(settings)
    request = client.chat.completions.create.call_args.kwargs
    assert request["model"] == "test-flash-model"
    assert request["extra_body"] == {"extra_body": {"enable_thinking": False}}
    assert "没有实时搜索" in request["messages"][0]["content"]
    assert "不要编造日期或来源链接" in request["messages"][0]["content"]
    assert "AAPL" in request["messages"][1]["content"]
    client.__exit__.assert_called_once()


def test_simple_query_reports_empty_model_response(monkeypatch):
    client = MagicMock()
    client.__enter__.return_value = client
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=None))]
    )
    monkeypatch.setattr(simple, "create_client", Mock(return_value=client))

    with pytest.raises(RuntimeError, match="没有返回文本"):
        simple.query_api("AAPL", settings=Settings(api_key="test-api-key"))


def test_enhanced_factory_passes_provider_configuration(monkeypatch):
    constructors = {}
    for name, symbol in (
        ("agno.agent", "Agent"),
        ("agno.models.openai.like", "OpenAILike"),
        ("agno.team", "Team"),
        ("agno.tools.crawl4ai", "Crawl4aiTools"),
        ("agno.tools.duckduckgo", "DuckDuckGoTools"),
    ):
        module = ModuleType(name)
        constructors[symbol] = Mock()
        setattr(module, symbol, constructors[symbol])
        monkeypatch.setitem(sys.modules, name, module)
    settings = Settings(
        api_key="test-api-key",
        base_url="https://example.test/api/v1",
        model="test-flash-model",
        timeout=15,
    )

    team = enhanced.create_earnings_team(settings)

    constructors["OpenAILike"].assert_called_once_with(
        id=settings.model,
        api_key=settings.api_key,
        base_url=settings.base_url,
        timeout=settings.timeout,
        max_retries=0,
        extra_body={"extra_body": {"enable_thinking": False}},
    )
    assert team is constructors["Team"].return_value
    assert len(constructors["Team"].call_args.kwargs["members"]) == 2


def test_enhanced_query_returns_result_instead_of_completion_status(monkeypatch):
    team = Mock()
    team.run.return_value = SimpleNamespace(content="季度 | 日期 | 来源")
    factory = Mock(return_value=team)
    monkeypatch.setattr(enhanced, "create_earnings_team", factory)
    settings = Settings(api_key="test-api-key")

    assert enhanced.query_earnings("AAPL", settings=settings) == "季度 | 日期 | 来源"

    factory.assert_called_once_with(settings)
    assert "AAPL" in team.run.call_args.args[0]
    assert team.run.call_args.kwargs == {"stream": False}
