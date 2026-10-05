from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from phone_assistant.advisor import build_advice_messages
from phone_assistant.chat import build_chat_messages, prepare_chat_context
from phone_assistant.config import Settings
from phone_assistant.recommendation import Preferences, family_variants, recommend
from phone_assistant.server import create_app


SCORE_FIELDS = {"score", "recommendation_score", "ranking_breakdown", "ranking_reasons", "metrics", "ranking_policy", "score_applicable"}


def phone(id="one", **fields):
    return {"id": id, "family_key": id, "name": "手机 " + id, "brand": "示例", "origin": "zol",
        "availability": "listed", "fetched_at": datetime.now(timezone.utc).isoformat(), "release_date": "2026-01-01",
        "price": 3000, "storage_gb": 256, "ram_gb": 12, "specs": {}, **fields}


def storage_for(rows):
    storage = Mock()
    storage.list_phones.return_value = rows
    storage.get_phone.side_effect = lambda id: next((row for row in rows if row["id"] == id), None)
    return storage


def assert_no_scores(value):
    if isinstance(value, dict):
        assert not SCORE_FIELDS.intersection(value)
        for child in value.values():
            assert_no_scores(child)
    elif isinstance(value, list):
        for child in value:
            assert_no_scores(child)


def test_filter_route_alias_returns_all_matching_families_without_scores():
    rows = [phone(str(index)) for index in range(72)]
    client = TestClient(create_app(storage_for(rows), Settings("test-key")))
    filtered = client.post("/api/filter", json={}).json()
    assert filtered == client.post("/api/recommend", json={}).json()
    assert filtered["preferences"]["sort"] == "newest"
    assert filtered["total"] == len(filtered["phones"]) == filtered["coverage"]["returned"] == 72
    assert_no_scores(filtered)


@pytest.mark.parametrize("sort", ["recommended", "match"])
def test_legacy_sort_alias_is_plain_newest(sort):
    rows = [phone("old", release_date="2025-01-01", brand="苹果", battery_mah=9000),
        phone("new", release_date="2026-02-01", brand="示例", battery_mah=3500)]
    result = recommend(rows, Preferences(sort=sort, priorities=["battery"], compact=True))
    assert result["preferences"]["sort"] == "newest"
    assert [row["id"] for row in result["phones"]] == ["new", "old"]
    assert_no_scores(result)


@pytest.mark.parametrize("sort", ["newest", "price_asc", "price_desc"])
def test_usage_brand_and_compact_never_change_filter_order(sort):
    rows = [phone("a", price=2500, brand="示例", weight_g=240, battery_mah=3500),
        phone("b", price=2500, brand="苹果", weight_g=160, battery_mah=8000)]
    basic = recommend(rows, Preferences(sort=sort))
    analysis = recommend(rows, Preferences(sort=sort, priorities=["battery", "gaming"], compact=True))
    assert basic["phones"] == analysis["phones"]
    assert [row["id"] for row in basic["phones"]] == ["a", "b"]


def test_unbounded_browsing_keeps_unknown_and_stale_prices_without_purchase_proof():
    rows = [phone("unknown", price=None), phone("stale", field_sources={"price": {
        "origin": "zol", "fetched_at": "2020-01-01T00:00:00Z"}})]
    result = recommend(rows, Preferences())
    assert result["total"] == 2
    by_id = {row["id"]: row for row in result["phones"]}
    assert all(row["matches_preferences"] and not row["recommendation_eligible"] for row in by_id.values())
    assert "unknown_price" in by_id["unknown"]["variant_codes"]
    assert "stale_price" in by_id["stale"]["variant_codes"]
    assert recommend(rows, Preferences(budget_max=5000))["total"] == 0
    assert recommend(rows, Preferences(budget_min=1))["total"] == 0


@pytest.mark.parametrize("sort", ["newest", "price_asc", "price_desc"])
def test_family_representative_is_lowest_matching_real_quote_for_every_sort(sort):
    rows = [phone("generic", family_key="same", storage_gb=None, price=None),
        phone("small", family_key="same", storage_gb=128, price=2000),
        phone("medium", family_key="same", storage_gb=256, price=3000),
        phone("large", family_key="same", storage_gb=512, price=4000)]
    result = recommend(rows, Preferences(sort=sort, min_storage=256))
    assert result["phones"][0]["id"] == "medium"
    assert result["phones"][0]["variant_count"] == 3
    assert [row["storage_gb"] for row in result["phones"][0]["variant_summary"]] == [128, 256, 512]


def test_all_selected_and_automatic_ai_evidence_are_factual_without_scores():
    rows = [phone(str(index), new_from_source=True) for index in range(7)] + [phone("unknown", price=None)]
    storage = storage_for(rows)
    preferences = Preferences(priorities=["gaming"], compact=True)
    selected = prepare_chat_context(storage, [row["id"] for row in rows], preferences, "gaming")
    assert len(selected["phones"]) == 8
    automatic = prepare_chat_context(storage, [], preferences, "tech")
    assert len(automatic["phones"]) == 3
    for context in (selected, automatic):
        assert_no_scores(context)
        prompt = build_chat_messages(context, preferences, "怎么选？", [])[0]["content"]
        assert "权重" not in prompt and "recommendation_score" not in prompt
    advisor = build_advice_messages(rows, preferences, "怎么选？")[0]["content"]
    assert "recommendation_score" not in advisor and "ranking_breakdown" not in advisor
    client = TestClient(create_app(storage, Settings("test-key")))
    for response in (client.post("/api/compare", json={"ids": [row["id"] for row in rows]}),
            client.get("/api/phones/unknown/variants")):
        assert response.status_code == 200
        assert_no_scores(response.json())


def test_every_family_card_uses_the_same_real_configuration_collection_as_its_menu():
    rows = [phone("zol", name="手机(12GB/256GB)", family_key="same", price=3000, quality_score=100,
            new_from_source=True, five_g=True, source_url="https://example.com/zol"),
        phone("official", name="手机(12GB+256GB)", family_key="same", price=4000, quality_score=72,
            origin="official", new_from_source=True, five_g=True, source_url="https://example.com/official")]
    result = recommend(rows, Preferences(query="手机", budget_max=5000))
    for card in (result["phones"][0], result["catalogue"]["phones"][0], result["discovery"]["phones"][0]):
        assert card["id"] == "zol"
        assert card["variant_count"] == 1
        assert card["id"] in {option["id"] for option in card["variant_summary"]}
        option = card["variant_summary"][0]
        assert option["price"] == 3000 and option["source_url"] == "https://example.com/zol"
        assert option["five_g"] is True


@pytest.mark.parametrize("storage,ram", [(None, None), (256, None)])
def test_current_unknown_configuration_is_not_replaced_by_historical_capacity_or_ram(storage, ram):
    rows = [phone("current", name="手机 Current", family_key="same", origin="official", storage_gb=storage,
            ram_gb=ram, price=None, new_from_source=True, source_url="https://example.com/current"),
        phone("history", name="手机(12GB/256GB)", family_key="same", storage_gb=256, ram_gb=12,
            origin="legacy", availability="historical", price=3000, fetched_at=None,
            source_url="https://example.com/history")]
    result = recommend(rows, Preferences(query="手机"))
    for card in (result["phones"][0], result["catalogue"]["phones"][0], result["discovery"]["phones"][0]):
        assert card["id"] == "current"
        options = {option["id"]: option for option in card["variant_summary"]}
        assert set(options) == {"current", "history"}
        assert options["current"]["storage_gb"] == storage and options["current"]["ram_gb"] is None
        assert options["current"]["price"] is None and options["history"]["price"] == 3000
        assert options["current"]["matches_preferences"] is True
        assert options["history"]["matches_preferences"] is False
    assert recommend(rows, Preferences(budget_max=5000))["phones"] == []


def test_same_ram_capacity_with_explicit_4g_and_5g_are_distinct_real_versions():
    rows = [phone("4g", name="华为nova 8 Pro(8GB/128GB/全网通/4G版)", family_key="same",
            ram_gb=8, storage_gb=128, price=3699, five_g=None, source_url="https://example.com/4g"),
        phone("5g", name="华为nova 8 Pro(8GB/128GB/全网通/5G版)", family_key="same",
            ram_gb=8, storage_gb=128, price=3999, five_g=True, source_url="https://example.com/5g")]
    result = recommend(rows, Preferences(budget_max=5000))
    card = result["phones"][0]
    assert card["id"] == "4g" and card["variant_count"] == 2
    assert {option["id"] for option in card["variant_summary"]} == {"4g", "5g"}
    by_id = {option["id"]: option for option in card["variant_summary"]}
    assert by_id["4g"]["five_g"] is None and by_id["5g"]["five_g"] is True
    assert by_id["4g"]["price"] == 3699 and by_id["5g"]["price"] == 3999
    assert [record["id"] for record in family_variants(rows, Preferences())] == ["4g", "5g"]


def test_current_concrete_versions_still_replace_an_unpriced_generic_directory_entry():
    rows = [phone(str(capacity), family_key="same", storage_gb=capacity, ram_gb=None,
            price=3000 + capacity, five_g=True) for capacity in (256, 512, 1024, 2048)]
    rows += [phone("generic", family_key="same", storage_gb=None, ram_gb=None, price=None,
        origin="official", availability="unknown", five_g=True)]
    result = recommend(rows, Preferences())
    assert result["phones"][0]["variant_count"] == 4
    assert "generic" not in {option["id"] for option in result["phones"][0]["variant_summary"]}
