from phone_assistant.advisor import build_advice_messages
from phone_assistant.recommendation import Preferences


def test_model_receives_only_selected_phone_evidence_with_field_provenance():
    phones = [{"id": "1", "name": "选中的手机", "price": 3000, "soc": None, "field_sources": {"price": {"origin": "legacy", "fetched_at": None}}, "source_url": "https://example.com/phone", "issues": [{"message": "内部质量日志"}]}]
    messages = build_advice_messages(phones, Preferences(priorities=["battery"]), "续航如何？")
    context = messages[0]["content"]
    assert "legacy" in context and '"soc": null' in context
    assert "https://example.com/phone" in context
    assert "内部质量日志" not in context
    assert "不要编造评测跑分" in context and "资料不足" in context
    assert messages[-1]["content"] == "续航如何？"


def test_official_upcoming_model_and_starting_price_remain_distinct():
    messages = build_advice_messages([{"id": "official:apple:duo", "name": "iPhone Duo",
        "origin": "official", "availability": "announced", "price": None, "price_from": 16999,
        "new_from_source": True, "release_date": "2026-10-23"}], Preferences(), "能买吗？")

    context = messages[0]["content"]
    assert '"origin": "official"' in context
    assert '"price": null' in context
    assert "不能据起价宣称满足预算" in context
    assert "不能宣称已在售" in context


def test_used_mode_keeps_quote_evidence_distinct_from_second_hand_market():
    phones = [{"id": "1", "name": "机型参考", "brand": "苹果", "price": 3000}]
    context = build_advice_messages(phones, Preferences(purchase_mode="used"), "二手能买吗？")[0]["content"]
    assert '"purchase_mode": "used"' in context
    assert '"recommendation_score":' not in context
    assert '"ranking_breakdown":' not in context
    assert "不是二手售价" in context
    assert "成色、电池健康、保修" in context
    assert "推断品质、售后或实测优劣" in context


def test_optional_budget_explanation_keeps_all_selected_records_and_no_amount_assumption():
    import json

    phones = [{"id": str(index), "name": f"手机{index}", "price": 9999 + index} for index in range(6)]
    context = build_advice_messages(phones, Preferences(), "六款一起比较")[0]["content"]
    evidence = json.loads(context.split("候选记录：", 1)[1])
    assert [record["id"] for record in evidence] == [record["id"] for record in phones]
    assert all(record["budget_warning"] is None for record in evidence)
    assert all("score" not in record and "ranking_breakdown" not in record for record in evidence)
    assert '"budget_max": null' in context
    assert "不假定任何金额" in context


def test_sku_capacity_conflict_and_field_source_reach_model_as_explicit_evidence():
    phone = {"id": "sku", "name": "iPhone 18 Pro Max(2TB)", "storage_gb": 2048,
        "specs": {"ROM容量": "256GB"}, "issues": [
            {"code": "sku_storage_conflict", "message": "具体版本为2048GB，共享参数为256GB，待核验"},
            {"code": "internal", "message": "内部处理细节"}],
        "field_sources": {"storage_gb": {"origin": "zol", "source_url": "https://example.com/sku"}}}
    context = build_advice_messages([phone], Preferences(), "这个2TB是真的吗？")[0]["content"]
    assert "具体版本为2048GB，共享参数为256GB，待核验" in context
    assert '"storage_gb": 2048' in context and "https://example.com/sku" in context
    assert "不能拿共享规格覆盖规范容量" in context
    assert "内部处理细节" not in context
