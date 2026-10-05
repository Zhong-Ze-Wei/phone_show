import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import anyio
import httpx
import pytest
from fastapi.testclient import TestClient
from openai import APIConnectionError, APIStatusError
from starlette.requests import ClientDisconnect

from phone_assistant.chat import (
    ChatStreamingResponse, build_chat_messages, prepare_chat_context, stream_chat,
)
from phone_assistant.config import Settings
from phone_assistant.recommendation import Preferences
from phone_assistant.server import create_app

SETTINGS = Settings("private-test-key")


def phone(phone_id="a", **changes):
    return {"id": phone_id, "name": f"手机{phone_id}", "brand": "荣耀", "price": 2500,
        "storage_gb": 256, "ram_gb": 12, "battery_mah": 6000, "soc": "骁龙8至尊版",
        "origin": "zol", "availability": "listed", "os_family": "Android",
        "fetched_at": datetime.now(timezone.utc).isoformat(), "release_date": "2025-10-01",
        "source_url": f"https://example.com/{phone_id}", **changes}


def storage_for(phones):
    storage = Mock()
    storage.list_phones.side_effect = lambda: list(phones)
    storage.get_phone.side_effect = lambda phone_id: next((record for record in phones if record["id"] == phone_id), None)
    return storage


def chunk(content=None, finish_reason=None):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=content), finish_reason=finish_reason)])


class FakeStream:
    def __init__(self, items):
        self.items = iter(items)
        self.closed = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        item = next(self.items, None)
        if item is None:
            raise StopAsyncIteration
        if isinstance(item, Exception):
            raise item
        return item

    async def close(self):
        self.closed += 1


def model_for(monkeypatch, items=None, stream=None, create_error=None):
    stream = stream or FakeStream(items if items is not None else [chunk("根据用途选择"), chunk("即可。", "stop")])
    completion = AsyncMock(return_value=stream, side_effect=create_error)
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=completion)), close=AsyncMock())
    factory = Mock(return_value=client)
    monkeypatch.setattr("phone_assistant.chat.create_chat_client", factory)
    return client, stream, factory


def events(response):
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    return [
        (part.splitlines()[0].removeprefix("event: "), json.loads(part.splitlines()[1].removeprefix("data: ")))
        for part in response.text.strip().split("\n\n")
    ]


def test_budgetless_chat_streams_actual_chunks_without_assuming_an_amount(monkeypatch):
    model, stream, factory = model_for(monkeypatch)
    storage = storage_for([])
    client = TestClient(create_app(storage=storage, settings=SETTINGS))
    result = events(client.post("/api/chat", json={"message": "我想先聊一下自己的需求"}))
    assert result[0] == ("context", {"phones": [], "sources": [], "mode": "no_candidates", "persona": "tech"})
    assert result[1:] == [("delta", {"content": "根据用途选择"}), ("delta", {"content": "即可。"}), ("done", {"finish_reason": "stop"})]
    kwargs = model.chat.completions.create.call_args.kwargs
    assert kwargs["stream"] is True and kwargs["max_tokens"] <= 1800
    assert kwargs["model"] == SETTINGS.model
    assert kwargs["extra_body"] == {"extra_body": {"enable_thinking": False}}
    assert '"budget_max": null' in kwargs["messages"][0]["content"]
    assert "不能把填写预算当作交流或搜索的前提" in kwargs["messages"][0]["content"]
    model.chat.completions.create.assert_awaited_once()
    model.close.assert_awaited_once()
    factory.assert_called_once_with(SETTINGS)
    assert stream.closed == 1
    storage.list_phones.assert_called_once()


def test_budgetless_selected_phone_has_facts_and_no_budget_warning(monkeypatch):
    monkeypatch.setattr("phone_assistant.chat.filter_phones", Mock(side_effect=AssertionError("无预算不能推荐")))
    context = prepare_chat_context(storage_for([phone()]), ["a"], None, "lifestyle")
    record = context["phones"][0]
    assert context["mode"] == "selected"
    assert record["recommendation_eligible"] is True and "score_applicable" not in record
    assert "score" not in record and "ranking_breakdown" not in record
    assert record["budget_warning"] is None


def test_recommended_context_preserves_hard_filters_and_full_field_provenance():
    old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    records = [phone("good", specs={"镜头": "OIS光学防抖"}, field_sources={
        "price": {"origin": "zol", "fetched_at": datetime.now(timezone.utc).isoformat(), "source_url": "https://example.com/price"},
        "battery_mah": {"origin": "official", "source_url": "https://example.com/specs"}}),
        phone("over", price=3001), phone("small", storage_gb=128),
        phone("legacy", field_sources={"price": {"origin": "legacy", "fetched_at": None}}),
        phone("staleprice", field_sources={"price": {"origin": "zol", "fetched_at": old}}),
        phone("future", availability="announced", release_date="2099-01-01"),
        phone("unknown", price=None), phone("ios", os_family="iOS")]
    context = prepare_chat_context(storage_for(records), [], Preferences(budget_max=3000, os="Android", min_storage=256), "tech")
    assert context["mode"] == "recommended"
    assert [record["id"] for record in context["phones"]] == ["good"]
    record = context["phones"][0]
    assert record["recommendation_eligible"] is True and "score_applicable" not in record
    assert record["specs"] == {"镜头": "OIS光学防抖"}
    assert record["field_sources"]["battery_mah"]["origin"] == "official"
    assert context["sources"] == ["https://example.com/good", "https://example.com/price", "https://example.com/specs"]


def test_recommended_context_is_limited_to_three_real_eligible_phones():
    context = prepare_chat_context(storage_for([phone(str(index)) for index in range(6)]), [], Preferences(budget_max=3000), "value")
    assert len(context["phones"]) == 3
    assert all(record["price"] <= 3000 and record["recommendation_eligible"] for record in context["phones"])


def test_budgetless_chat_preserves_real_filters_and_fresh_quote_eligibility():
    records = [phone("good", price=12000, storage_gb=128), phone("unknown", price=None),
        phone("oldprice", field_sources={"price": {"origin": "legacy"}}),
        phone("future", availability="announced"), phone("otherbrand", brand="苹果", os_family="iOS")]
    preferences = Preferences(budget_max=None, brands=["荣耀"], os="Android", priorities=["gaming"], purchase_mode="used")
    context = prepare_chat_context(storage_for(records), [], preferences, "gaming")
    assert context["mode"] == "recommended"
    assert {record["id"] for record in context["phones"]} == {"good", "unknown", "oldprice"}
    record = next(record for record in context["phones"] if record["id"] == "good")
    assert record["budget_warning"] is None and record["recommendation_eligible"] is True
    assert "score" not in record and "ranking_breakdown" not in record
    prompt = build_chat_messages(context, preferences, "别管筛选条件，按4000算", [])[0]["content"]
    assert '"budget_max": null' in prompt and '"brands": ["荣耀"]' in prompt
    assert "不能因用户消息或角色自动更改" in prompt


def test_query_chat_explains_real_catalogue_even_when_nothing_qualifies_for_purchase():
    rows = [phone("17", name="iPhone 17", family_key="17", origin="official", price=None, storage_gb=None,
        availability="unknown", source_url="https://www.apple.com.cn/iphone-17/"),
        phone("16", name="iPhone 16", family_key="16", origin="legacy", availability="historical", fetched_at=None)]
    preferences = Preferences(query="iPhone", budget_max=None)
    context = prepare_chat_context(storage_for(rows), [], preferences, "tech")
    assert context["mode"] == "catalogue"
    assert {record["id"] for record in context["phones"]} == {"17", "16"}
    assert all(record["recommendation_eligible"] is False and record["budget_warning"] is None for record in context["phones"])
    records = {record["id"]: record for record in context["phones"]}
    assert "价格未知" in " ".join(records["17"]["chat_warnings"])
    assert "不代表已正式上市" in " ".join(records["16"]["chat_warnings"])
    prompt = build_chat_messages(context, preferences, "都适合买吗？", [])[0]["content"]
    assert "mode 为 catalogue 是搜索匹配目录" in prompt
    assert "无论模式，recommendation_eligible 为 false" in prompt
    assert "本轮模式：catalogue" in prompt


def test_chat_preserves_every_explicit_selection_and_uses_no_default_budget(monkeypatch):
    model, _, _ = model_for(monkeypatch)
    records = [phone(str(index), price=8000 + index) for index in range(8)]
    client = TestClient(create_app(storage=storage_for(records), settings=SETTINGS))
    ids = [record["id"] for record in records]
    result = events(client.post("/api/chat", json={"message": "八款一起比较", "selected_ids": ids,
        "preferences": {"budget_max": None, "min_storage": 0}}))
    context = result[0][1]
    assert context["mode"] == "selected"
    assert [record["id"] for record in context["phones"]] == ids
    assert context["sources"] == [record["source_url"] for record in records]
    assert all(record["budget_warning"] is None for record in context["phones"])
    prompt = model.chat.completions.create.call_args.kwargs["messages"][0]["content"]
    assert all(f'"id": "{phone_id}"' in prompt for phone_id in ids)


def test_storage_sku_conflict_is_visible_to_chat_without_leaking_internal_issue_list():
    record = phone(storage_gb=2048, name="iPhone 18 Pro Max(2TB)", specs={"ROM容量": "256GB"},
        issues=[{"code": "sku_storage_conflict", "message": "具体SKU为2048GB，系列ROM为256GB，待核验"},
            {"code": "internal", "message": "内部处理细节"}], field_sources={
            "storage_gb": {"origin": "zol", "source_url": "https://example.com/sku"}})
    context = prepare_chat_context(storage_for([record]), ["a"], None, "tech")
    prompt = build_chat_messages(context, None, "容量多少？", [])[0]["content"]
    assert "具体SKU为2048GB，系列ROM为256GB，待核验" in prompt
    assert '"storage_gb": 2048' in prompt and "https://example.com/sku" in prompt
    assert "内部处理细节" not in prompt


def test_selected_context_warns_about_budget_future_unknown_and_used_information():
    context = prepare_chat_context(storage_for([phone(price=5000, availability="announced", release_date="2099-01-01")]),
        ["a"], Preferences(budget_max=3000, purchase_mode="used"), "gaming")
    record = context["phones"][0]
    assert record["price"] == 5000
    assert record["budget_warning"] == "超出当前预算范围"
    assert record["recommendation_eligible"] is False
    assert "score" not in record and "ranking_breakdown" not in record
    assert "尚未上市" in " ".join(record["chat_warnings"])
    assert "不是二手售价" in " ".join(record["chat_warnings"])
    unknown = prepare_chat_context(storage_for([phone(price=None)]), ["a"], Preferences(budget_max=3000), "tech")
    assert unknown["phones"][0]["budget_warning"] == "价格未知，无法确认预算"
    assert unknown["phones"][0]["recommendation_eligible"] is False


def test_history_exploration_keeps_old_quote_warning_in_selected_context():
    context = prepare_chat_context(storage_for([phone(origin="legacy", availability="historical", fetched_at=None)]),
        ["a"], Preferences(budget_max=3000, include_history=True), "value")
    warnings = " ".join(context["phones"][0]["chat_warnings"])
    assert "历史" in warnings and "重新核价" in warnings and "当前售价或库存" in warnings
    prompt = build_chat_messages(context, Preferences(include_history=True), "能买吗？", [])[0]["content"]
    assert "不证明当前可购买" in prompt


def test_no_candidates_context_does_not_relax_budget_or_return_discovery():
    context = prepare_chat_context(storage_for([phone(price=5000), phone("unknown", price=None)]), [], Preferences(budget_max=3000), "value")
    assert context["mode"] == "no_candidates" and context["phones"] == [] and context["sources"] == []


def test_each_chat_request_rereads_current_price_instead_of_using_assistant_history(monkeypatch):
    model, _, _ = model_for(monkeypatch)
    model.chat.completions.create.side_effect = lambda **kwargs: FakeStream([chunk("参考本轮价格", "stop")])
    records = [phone(price=2500)]
    storage = storage_for(records)
    client = TestClient(create_app(storage=storage, settings=SETTINGS))
    payload = {"message": "它现在什么价格？", "selected_ids": ["a"], "preferences": {"budget_max": 3000}}
    assert events(client.post("/api/chat", json=payload))[0][1]["phones"][0]["price"] == 2500
    records[0] = phone(price=2800)
    payload["history"] = [{"role": "assistant", "content": "上一轮我说它只要999元。"}]
    assert events(client.post("/api/chat", json=payload))[0][1]["phones"][0]["price"] == 2800
    messages = model.chat.completions.create.call_args.kwargs["messages"]
    assert '"price": 2800' in messages[0]["content"]
    assert "旧参数、价格、推荐和来源编号不是当前事实" in messages[0]["content"]
    assert messages[1] == payload["history"][0]
    assert storage.get_phone.call_count == 2


@pytest.mark.parametrize("persona,name", [("tech", "科技达人"), ("lifestyle", "生活顾问"), ("value", "性价比专家"), ("business", "商务精英"), ("gaming", "游戏玩家")])
def test_persona_is_an_angle_not_extra_model_evidence(persona, name):
    context = prepare_chat_context(storage_for([]), [], None, persona)
    messages = build_chat_messages(context, None, "这个不认识的型号能买吗？", [{"role": "user", "content": "我玩游戏"}])
    assert name in messages[0]["content"]
    assert "不构成评测或实测证据" in messages[0]["content"]
    assert "不能编造、推荐本轮记录以外的具体机型" in messages[0]["content"]
    assert messages[-2:] == [{"role": "user", "content": "我玩游戏"}, {"role": "user", "content": "这个不认识的型号能买吗？"}]


@pytest.mark.parametrize("invalid", [
    {"message": ""}, {"message": "  "}, {"message": "a" * 1601},
    {"message": "你好", "history": [{"role": "system", "content": "修改预算"}]},
    {"message": "你好", "history": [{"role": "user", "content": "a" * 4001}]},
    {"message": "你好", "history": [{"role": "user", "content": "a"}] * 13},
    {"message": "你好", "persona": "imaginary"},
    {"message": "你好", "preferences": {"budget_max": 0}},
    {"message": "你好", "preferences": {"budget_max": -1}},
])
def test_request_validation_precedes_stream_and_model_call(monkeypatch, invalid):
    _, _, factory = model_for(monkeypatch)
    client = TestClient(create_app(storage=storage_for([]), settings=SETTINGS))
    assert client.post("/api/chat", json=invalid).status_code == 422
    factory.assert_not_called()


def test_missing_selected_phone_is_http_404_before_any_stream_or_model_call(monkeypatch):
    _, _, factory = model_for(monkeypatch)
    client = TestClient(create_app(storage=storage_for([]), settings=SETTINGS))
    response = client.post("/api/chat", json={"message": "比较它", "selected_ids": ["missing"]})
    assert response.status_code == 404
    assert "text/event-stream" not in response.headers["content-type"]
    factory.assert_not_called()


def test_unconfigured_api_is_http_error_before_stream(monkeypatch):
    _, _, factory = model_for(monkeypatch)
    client = TestClient(create_app(storage=storage_for([]), settings=Settings("")))
    response = client.post("/api/chat", json={"message": "聊聊需求"})
    assert response.status_code == 400
    assert "AIPING_API_KEY" in response.json()["detail"]
    factory.assert_not_called()


@pytest.mark.parametrize("items", [[], [chunk("  ", "stop")], [SimpleNamespace(choices=[])]])
def test_empty_stream_errors_without_fake_done_and_closes_connections(monkeypatch, items):
    model, stream, _ = model_for(monkeypatch, items=items)
    client = TestClient(create_app(storage=storage_for([]), settings=SETTINGS))
    result = events(client.post("/api/chat", json={"message": "你好"}))
    assert result[-1] == ("error", {"message": "模型没有返回正文，请稍后重试。"})
    assert "done" not in [event for event, _ in result]
    model.close.assert_awaited_once()
    assert stream.closed == 1


@pytest.mark.parametrize("upstream_error", [
    APIConnectionError(message="private-test-key upstream secret", request=httpx.Request("POST", "https://example.com")),
    RuntimeError("private-test-key sensitive upstream body"),
])
def test_midstream_failure_keeps_partial_delta_then_safe_error_and_no_done(monkeypatch, upstream_error):
    model, stream, _ = model_for(monkeypatch, items=[chunk("已收到的部分"), upstream_error])
    client = TestClient(create_app(storage=storage_for([]), settings=SETTINGS))
    response = client.post("/api/chat", json={"message": "你好"})
    result = events(response)
    assert result[1] == ("delta", {"content": "已收到的部分"})
    assert result[-1][0] == "error" and "done" not in [event for event, _ in result]
    assert "private-test-key" not in response.text and "sensitive" not in response.text
    model.close.assert_awaited_once()
    assert stream.closed == 1


def test_upstream_creation_failure_returns_safe_error_and_closes_client(monkeypatch):
    error = APIStatusError("private-test-key", response=httpx.Response(401, request=httpx.Request("POST", "https://example.com")), body={"secret": "private-test-key"})
    model, stream, _ = model_for(monkeypatch, create_error=error)
    client = TestClient(create_app(storage=storage_for([]), settings=SETTINGS))
    result = events(client.post("/api/chat", json={"message": "你好"}))
    assert result[-1][0] == "error" and "鉴权失败" in result[-1][1]["message"]
    assert "done" not in [event for event, _ in result]
    model.close.assert_awaited_once()
    assert stream.closed == 0


def test_eof_without_finish_marker_is_an_interruption_not_success(monkeypatch):
    model_for(monkeypatch, items=[chunk("回答到一半")])
    client = TestClient(create_app(storage=storage_for([]), settings=SETTINGS))
    result = events(client.post("/api/chat", json={"message": "你好"}))
    assert result[-1] == ("error", {"message": "AI 回答中断，请稍后重试。"})


def test_closing_suspended_generator_closes_stream_and_client(monkeypatch):
    model, stream, _ = model_for(monkeypatch)

    async def run():
        generator = stream_chat({"phones": [], "sources": [], "mode": "no_candidates", "persona": "tech"}, None, "你好", [], SETTINGS)
        assert "event: context" in await anext(generator)
        assert "event: delta" in await anext(generator)
        await generator.aclose()

    anyio.run(run)
    assert stream.closed == 1
    model.close.assert_awaited_once()


def test_disconnect_while_waiting_for_next_token_closes_stream_and_client(monkeypatch):
    class BlockingStream(FakeStream):
        async def __anext__(self):
            self.started.set()
            await anyio.sleep_forever()

    stream = BlockingStream([])
    model, _, _ = model_for(monkeypatch, stream=stream)

    async def run():
        stream.started = anyio.Event()

        async def consume():
            async for _ in stream_chat({"phones": [], "sources": [], "mode": "no_candidates", "persona": "tech"}, None, "你好", [], SETTINGS):
                pass

        async with anyio.create_task_group() as tasks:
            tasks.start_soon(consume)
            await stream.started.wait()
            tasks.cancel_scope.cancel()

    anyio.run(run)
    assert stream.closed == 1
    model.close.assert_awaited_once()


def test_asgi_send_disconnect_closes_generator_suspended_after_delta(monkeypatch):
    model, stream, _ = model_for(monkeypatch)

    async def run():
        generator = stream_chat({"phones": [], "sources": [], "mode": "no_candidates", "persona": "tech"}, None, "你好", [], SETTINGS)
        response = ChatStreamingResponse(generator, media_type="text/event-stream")

        async def send(message):
            if message.get("body", b"").startswith(b"event: delta"):
                raise OSError("browser disconnected")

        async def receive():
            await anyio.sleep_forever()

        with pytest.raises(ClientDisconnect):
            await response({"type": "http", "method": "POST", "asgi": {"spec_version": "2.4"}}, receive, send)

    anyio.run(run)
    assert stream.closed == 1
    model.close.assert_awaited_once()
