from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from phone_assistant.assistant import PhoneAssistant, build_messages
from phone_assistant.config import Settings
from phone_assistant.knowledge import DocumentChunk, SearchResult


def test_uses_retrieved_evidence_and_configured_model():
    chunk = DocumentChunk("docs/phone.md", "手机 / 主摄", "历史资料：1 英寸传感器。")
    knowledge = Mock()
    knowledge.search.return_value = [SearchResult(chunk, 1.0)]
    client = Mock()
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="根据资料 [1]。"), finish_reason="stop")]
    )
    assistant = PhoneAssistant(knowledge, Settings("test-key"), client)
    answer = assistant.ask("主摄怎么样？")
    request = client.chat.completions.create.call_args.kwargs
    assert request["model"] == "DeepSeek-V4.1-Flash"
    assert "docs/phone.md" in request["messages"][0]["content"]
    assert "2024–2025" in request["messages"][0]["content"]
    assert request["messages"][-1]["content"] == "主摄怎么样？"
    assert answer.sources[0].chunk is chunk
    assert answer.content == "根据资料 [1]。"


def test_no_matches_does_not_call_api():
    knowledge = Mock()
    knowledge.search.return_value = []
    client = Mock()
    answer = PhoneAssistant(knowledge, Settings(""), client).ask("没有对应资料的问题")
    assert answer.sources == []
    client.chat.completions.create.assert_not_called()


def test_original_catalog_can_supply_evidence_without_markdown_match():
    knowledge = Mock()
    knowledge.search.return_value = []
    catalog = Mock()
    catalog.find_in_question.return_value = [{"产品型号": "示例手机 12", "品牌": "示例品牌", "发布年份": 2021, "电池": None}]
    client = Mock()
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="原始记录是 2021 年 [1]。"), finish_reason="stop")]
    )
    answer = PhoneAssistant(knowledge, Settings("test-key"), client, catalog).ask("示例手机 12 什么年份？")
    assert answer.sources[0].chunk.source.endswith(".xlsx")
    request = client.chat.completions.create.call_args.kwargs
    assert "2021" in request["messages"][0]["content"]
    assert "电池：None" not in request["messages"][0]["content"]


def test_followup_retrieval_preserves_user_context():
    knowledge = Mock()
    knowledge.search.return_value = []
    PhoneAssistant(knowledge, Settings("")).ask("续航呢？", [
        {"role": "user", "content": "小米 15 Ultra 的影像怎么样？"},
        {"role": "assistant", "content": "历史参数参考。", "sources": []},
    ])
    query = knowledge.search.call_args.args[0]
    assert "小米 15 Ultra" in query and "续航" in query


def test_history_drops_ui_fields_and_is_bounded():
    history = [{"role": "user", "content": str(i), "sources": []} for i in range(20)]
    messages = build_messages("问题", [], history)
    assert len(messages) == 10
    assert "sources" not in messages[1]


def test_blank_question_is_rejected():
    with pytest.raises(ValueError, match="请输入"):
        PhoneAssistant(Mock(), Settings("")).ask("   ")
