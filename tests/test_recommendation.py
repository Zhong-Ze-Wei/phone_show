from datetime import date, datetime, timedelta, timezone

import pytest

from phone_assistant.recommendation import Preferences, family_variants, phone_record, recommend


def phone(id="1", **fields):
    return {"id": id, "name": "示例手机" + id, "brand": "示例", "family_key": id, "price": 3000, "ram_gb": 12, "storage_gb": 256, "soc": "高通骁龙8 Elite", "battery_mah": 6000, "charging_w": 80, "display_inches": 6.7, "refresh_hz": 120, "weight_g": 210, "os": "Android 15", "availability": "listed", "origin": "zol", "fetched_at": datetime.now(timezone.utc).isoformat(), "specs": {"主摄": "5000万像素，支持OIS光学防抖"}, **fields}


def test_budget_is_hard_constraint_and_unknown_price_is_not_zero():
    result = recommend([phone("cheap", price=1999), phone("expensive", price=4001), phone("unknown", price=None)], Preferences(budget_max=3000))
    assert [record["id"] for record in result["phones"]] == ["cheap"]
    assert result["coverage"]["unknown_price"] == 1


def test_battery_priority_is_only_an_ai_preference():
    balanced = phone("balanced", battery_mah=4000, charging_w=30, ram_gb=16, refresh_hz=144)
    enduring = phone("enduring", battery_mah=7500, charging_w=100, ram_gb=8, refresh_hz=90, soc="高通骁龙7 Gen3")
    result = recommend([balanced, enduring], Preferences(priorities=["battery"]))
    assert result["phones"] == recommend([balanced, enduring], Preferences())["phones"]


def test_default_excludes_old_records_but_user_can_include_them():
    old = phone(fetched_at=(datetime.now(timezone.utc) - timedelta(days=31)).isoformat())
    assert recommend([old], Preferences())["total"] == 0
    assert recommend([old], Preferences(include_history=True))["total"] == 1


def test_old_model_with_recent_quote_can_be_recommended_without_recency_bonus():
    old_model = phone(release_date="2021-07-01")
    result = recommend([old_model], Preferences())
    assert result["total"] == 1
    assert recommend([old_model], Preferences(include_history=True))["total"] == 1


def test_old_release_year_does_not_exclude_a_freshly_priced_listed_model():
    old_model = phone(release_date=None, release_year=2020)
    result = recommend([old_model], Preferences())
    assert result["total"] == 1
    assert recommend([old_model], Preferences(include_history=True))["total"] == 1


def test_capacities_of_one_family_take_one_slot():
    result = recommend([phone("a", family_key="same", storage_gb=256), phone("b", family_key="same", storage_gb=512)], Preferences())
    assert result["total"] == 1
    assert result["coverage"]["matching_variants"] == 2


def test_storage_constraint_excludes_unknown_and_small_variants():
    result = recommend([phone("a", storage_gb=None), phone("b", storage_gb=128), phone("c", storage_gb=256)], Preferences(min_storage=256))
    assert [record["id"] for record in result["phones"]] == ["c"]


def test_camera_specs_do_not_generate_an_automatic_quality_judgment():
    plain = phone("plain", camera_mp=200, specs={"主摄": "2亿像素"})
    optical = phone("optical", camera_mp=50, specs={"主摄": "5000万，OIS光学防抖", "镜头": "潜望式长焦"})
    result = recommend([plain, optical], Preferences(priorities=["camera"]))
    assert result["phones"] == recommend([plain, optical], Preferences())["phones"]
    assert all("score" not in record and "metrics" not in record for record in result["phones"])


def test_old_price_source_remains_visible_after_fresh_spec_update():
    result = phone_record(phone(field_sources={"price": {"origin": "legacy"}}))
    assert any("历史" in reason for reason in result["tradeoffs"])


def test_old_price_does_not_enter_current_budget_results_by_borrowing_fresh_spec_time():
    old_price = phone(field_sources={"price": {"origin": "zol", "fetched_at": "2020-01-01T00:00:00+00:00"}})
    unknown_time = phone("unknown", field_sources={"price": {"origin": "zol", "fetched_at": None}})
    result = recommend([old_price, unknown_time], Preferences(budget_max=5000))
    assert result["total"] == 0
    assert result["coverage"]["unknown_price"] == 2
    assert recommend([old_price], Preferences(include_history=True))["total"] == 1


def test_explicit_newest_does_not_use_fetched_date_or_product_id():
    year = datetime.now(timezone.utc).year
    old_high_score = phone("99999", release_date=f"{year - 1}-12-01", ram_gb=16, storage_gb=512, battery_mah=7500)
    new = phone("1", release_date=f"{year}-01-01", ram_gb=8, storage_gb=256, battery_mah=4000)
    unknown = phone("999999", release_date=None, ram_gb=16, storage_gb=512)
    assert [p["id"] for p in recommend([unknown, old_high_score, new], Preferences(sort="newest"))["phones"]] == ["1", "99999", "999999"]
    assert recommend([old_high_score, new], Preferences(sort="match"))["phones"][0]["id"] == "1"


def test_release_precision_preserves_unknown_day_and_month():
    from phone_assistant.recommendation import release_sort_key
    assert release_sort_key(phone(release_year=2026, release_month=3, release_precision="month")) == (2026, 3, 0)
    assert release_sort_key(phone(release_year=2026, release_precision="year")) == (2026, 0, 0)
    assert release_sort_key(phone()) == (0, 0, 0)


def test_future_release_is_not_a_published_budget_recommendation():
    future = phone(release_date=(datetime.now(timezone.utc) + timedelta(days=10)).date().isoformat(), new_from_source=True)
    result = recommend([future], Preferences())
    assert result["phones"] == []
    assert result["coverage"]["excluded"]["upcoming"] == 1
    assert result["discovery"]["phones"][0]["discovery_status"] == "upcoming"


def test_price_sorts_and_budget_remain_independent_of_recency():
    rows = [phone("old", price=1000, release_date="2025-01-01"), phone("new", price=3000, release_date="2026-01-01"), phone("too-expensive", price=8000, release_date="2026-03-01")]
    assert [p["id"] for p in recommend(rows, Preferences(budget_max=4000, sort="price_asc"))["phones"]] == ["old", "new"]
    assert [p["id"] for p in recommend(rows, Preferences(budget_max=4000, sort="price_desc"))["phones"]] == ["new", "old"]
    result = recommend(rows, Preferences(budget_max=4000))
    assert result["coverage"]["excluded"]["over_budget"] == 1
    assert result["coverage"]["budget_suggestion"] == 8000


def test_official_and_source_new_entries_are_discoverable_without_price_or_capacity():
    unknown = phone("official:brand:new", origin="official", price=None, storage_gb=None, new_from_source=True, availability="unknown")
    expensive = phone("zol:new", price=7999, new_from_source=True)
    result = recommend([unknown, expensive], Preferences(budget_max=4000, min_storage=256))
    assert result["phones"] == []
    discoveries = {p["id"]: p for p in result["discovery"]["phones"]}
    assert set(discoveries) == {unknown["id"], expensive["id"]}
    assert "价格待核实" in " ".join(discoveries[unknown["id"]]["discovery_reasons"])
    assert "容量待核实" in " ".join(discoveries[unknown["id"]]["discovery_reasons"])
    assert "超过当前" in " ".join(discoveries[expensive["id"]]["discovery_reasons"])
    assert "历史" not in " ".join(discoveries[unknown["id"]]["tradeoffs"])


def test_explicit_newest_keeps_latest_release_in_front_of_result_limit():
    year = datetime.now(timezone.utc).year
    rows = [phone(str(i), release_date=f"{year - 1}-01-01", storage_gb=512) for i in range(65)]
    rows.append(phone("new", release_date=f"{year}-01-01", storage_gb=256))
    result = recommend(rows, Preferences(sort="newest"))
    assert result["total"] == 66
    assert len(result["phones"]) == 66
    assert len(recommend(rows, Preferences(sort="newest"), limit=60)["phones"]) == 60
    assert result["phones"][0]["id"] == "new"


def test_card_payload_keeps_price_provenance_without_repeating_original_specs():
    source = {"origin": "zol", "fetched_at": datetime.now(timezone.utc).isoformat(), "source_url": "https://detail.zol.com.cn/phone"}
    record = phone(new_from_source=True, field_sources={"price": source, "battery_mah": source}, specs_sources={"主摄": source}, issues=[])
    result = recommend([record], Preferences())
    for item in [result["phones"][0], result["discovery"]["phones"][0]]:
        assert item["field_sources"] == {"price": source}
        assert item["soc"] == record["soc"]
        assert "specs" not in item
        assert "specs_sources" not in item
    assert "主摄" in record["specs"]


def test_china_date_boundary_does_not_hide_today_release_as_future(monkeypatch):
    import phone_assistant.recommendation as module
    from datetime import date
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 3, 16, 30, tzinfo=timezone.utc).astimezone(tz)
    monkeypatch.setattr(module, "datetime", FrozenDatetime)
    assert module.market_today() == date(2026, 10, 4)
    assert module.is_released(phone(release_date="2026-10-04")) is True
    assert module.is_released(phone(release_date="2026-10-05")) is False


def test_discovery_chooses_in_budget_sku_before_expensive_or_unknown_official_generic():
    small = phone('256', name='vivo X500(12GB+256GB)', family_key='vivo-x500', price=5499, storage_gb=256, new_from_source=True, release_date='2026-09-01')
    large = phone('1tb', name='vivo X500(12GB+1TB)', family_key='vivo-x500', price=6999, storage_gb=1024, new_from_source=True, release_date='2026-09-01')
    generic = phone('official:vivo:x500', name='vivo X500', family_key='vivo-x500', origin='official', price=None, storage_gb=None, new_from_source=True, release_date=None)
    result = recommend([generic, large, small], Preferences(budget_max=6000))
    discovery = result['discovery']['phones'][0]
    assert discovery['id'] == '256'
    assert discovery['discovery_status'] == 'within_budget'
    assert not any('超过当前' in reason for reason in discovery['discovery_reasons'])
    assert discovery['discovery_variant_count'] == 2  # 官网目录记录不算第三个容量。


def test_discovery_when_all_over_budget_chooses_lowest_price_meeting_capacity():
    rows = [phone('tiny', family_key='same', price=4500, storage_gb=128, new_from_source=True),
        phone('middle', family_key='same', price=5500, storage_gb=256, new_from_source=True),
        phone('large', family_key='same', price=6500, storage_gb=1024, new_from_source=True)]
    discovery = recommend(rows, Preferences(budget_max=4000, min_storage=256))['discovery']['phones'][0]
    assert discovery['id'] == 'middle'
    assert discovery['discovery_status'] == 'over_budget'


@pytest.mark.parametrize("mode", ["new", "used"])
def test_used_and_new_browse_preserve_price_truth_and_never_enable_history(mode):
    old = phone("old", release_date="2023-01-01")
    new = phone("new", release_date="2026-09-01")
    stale = phone("stale", price=100, field_sources={"price": {"origin": "legacy"}})
    result = recommend([old, new, stale], Preferences(purchase_mode=mode))
    records = {record["id"]: record for record in result["phones"]}
    assert set(records) == {"old", "new", "stale"}
    assert result["preferences"]["include_history"] is False
    assert records["stale"]["matches_preferences"] is True
    assert records["stale"]["recommendation_eligible"] is False
    assert "stale_price" in records["stale"]["variant_codes"]
    assert records["old"]["price"] == 3000
    assert recommend([stale], Preferences(purchase_mode=mode, budget_max=4000, include_history=True))["total"] == 0


@pytest.mark.parametrize("sort", ["newest", "price_desc", "price_asc", "recommended", "match"])
def test_discovery_qualified_family_always_uses_lowest_matching_quote(sort):
    base = phone("base", family_key="same", price=1000, storage_gb=256, new_from_source=True)
    larger = phone("large", family_key="same", price=3999, storage_gb=512, new_from_source=True)
    result = recommend([base, larger], Preferences(budget_max=4000, sort=sort))
    assert result["phones"][0]["id"] == result["discovery"]["phones"][0]["id"] == "base"


def test_default_storage_is_unrestricted_and_only_explicit_capacity_filters():
    rows = [phone("unknown", storage_gb=None), phone("small", storage_gb=128), phone("large", storage_gb=256)]
    assert {record["id"] for record in recommend(rows, Preferences())["phones"]} == {"unknown", "small", "large"}
    assert [record["id"] for record in recommend(rows, Preferences(min_storage=256))["phones"]] == ["large"]


def test_family_cards_expose_deduplicated_real_versions_and_explain_filtered_out_capacities():
    rows = [phone(str(storage), name=f"苹果iPhone 18 Pro({storage}GB)", brand="苹果", family_key="苹果:18pro",
        storage_gb=storage, ram_gb=None, price=20499 if storage == 2048 else None, new_from_source=True)
        for storage in (256, 512, 1024, 2048)]
    rows += [phone("generic", name="iPhone 18 Pro", origin="official", brand="苹果", family_key="苹果:18pro",
        storage_gb=None, ram_gb=None, price=None, new_from_source=True)]
    result = recommend(rows, Preferences(query="iPhone18", min_storage=512))
    for card in (result["phones"][0], result["catalogue"]["phones"][0], result["discovery"]["phones"][0]):
        assert card["family_name"] == "iPhone 18 Pro"
        assert card["variant_count"] == len(card["variant_summary"]) == 4
        assert {variant["storage_gb"] for variant in card["variant_summary"]} == {256, 512, 1024, 2048}
        assert all("specs" not in variant for variant in card["variant_summary"])
        small = next(variant for variant in card["variant_summary"] if variant["id"] == "256")
        assert small["matches_preferences"] is False and "insufficient_storage" in small["variant_codes"]
    assert result["catalogue"]["phones"][0]["catalogue_variant_count"] == 4


def test_variants_deduplicate_sources_but_keep_distinct_ram_and_choose_matching_quote():
    rows = [phone("over", name="机型(8GB+256GB)", family_key="same", ram_gb=8, storage_gb=256, price=5000),
        phone("good", name="机型(8GB+256GB)", family_key="same", ram_gb=8, storage_gb=256, price=2999),
        phone("other-ram", name="机型(12GB+256GB)", family_key="same", ram_gb=12, storage_gb=256, price=3999),
        phone("partial", name="机型", family_key="same", ram_gb=None, storage_gb=256, price=None),
        phone("generic", name="机型", family_key="same", origin="official", storage_gb=None, price=None)]
    variants = family_variants(rows, Preferences(budget_max=3000))
    assert [(record["id"], record["ram_gb"], record["storage_gb"]) for record in variants] == [("good", 8, 256), ("other-ram", 12, 256)]


def test_family_without_concrete_capacity_keeps_one_generic_and_never_invents_configuration():
    rows = [phone("old", name="iPhone Example", family_key="same", origin="legacy", storage_gb=None, ram_gb=None, price=4000),
        phone("official", name="iPhone Example", family_key="same", origin="official", storage_gb=None, ram_gb=None, price=None)]
    variants = family_variants(rows, Preferences())
    assert len(variants) == 1 and variants[0]["id"] == "official"
    assert variants[0]["storage_gb"] is None and variants[0]["price"] is None


def test_catalogue_search_is_complete_beyond_result_limit_and_marks_purchase_restrictions():
    rows = [phone(str(index), name=f"iPhone Catalogue {index}", origin="legacy", availability="historical", fetched_at=None)
        for index in range(65)]
    rows += [phone("official", name="iPhone 17", origin="official", price=None, storage_gb=None, new_from_source=False, availability="unknown"),
        phone("pending", name="iPhone Future", release_date="2099-01-01", availability="announced"),
        phone("over", name="iPhone Premium", price=7000), phone("eligible", name="iPhone Current", price=3000)]
    result = recommend(rows, Preferences(query="iPhone", budget_max=4000), limit=1)
    assert len(result["phones"]) == result["total"] == 1
    assert result["catalogue"]["total"] == result["catalogue"]["returned"] == 69
    records = {record["id"]: record for record in result["catalogue"]["phones"]}
    assert records["official"]["catalogue_codes"] == ["availability_unknown", "unknown_price"]
    assert "upcoming" in records["pending"]["catalogue_codes"]
    assert "over_budget" in records["over"]["catalogue_codes"]
    assert records["0"]["catalogue_codes"] == ["history", "stale_price"]
    assert "不代表已正式上市" in " ".join(records["0"]["catalogue_reasons"])
    assert records["eligible"]["recommendation_eligible"] is True
    assert all(not record["recommendation_eligible"] for phone_id, record in records.items() if phone_id != "eligible")


def test_catalogue_does_not_ignore_identity_or_an_explicit_capacity_requirement():
    rows = [phone("unknown", name="iPhone 17", brand="苹果", os="iOS", storage_gb=None, price=None),
        phone("small", name="iPhone 16", brand="苹果", os="iOS", storage_gb=128, origin="legacy", availability="historical"),
        phone("large", name="iPhone 16 Pro", brand="苹果", os="iOS", storage_gb=512, origin="legacy", availability="historical"),
        phone("android", name="iPhone 模拟器手机", brand="其他", os="Android", storage_gb=512)]
    preferences = Preferences(query=" iPhone ", brands=["苹果"], os="iOS")
    assert {record["id"] for record in recommend(rows, preferences)["catalogue"]["phones"]} == {"unknown", "small", "large"}
    preferences.min_storage = 256
    assert [record["id"] for record in recommend(rows, preferences)["catalogue"]["phones"]] == ["large"]


def test_catalogue_family_prefers_eligible_variant_and_current_official_facts_over_old_rumors():
    rows = [phone("base", name="iPhone Current(128GB)", family_key="current", storage_gb=128, price=2999),
        phone("large", name="iPhone Current(512GB)", family_key="current", storage_gb=512, price=5999),
        phone("rumor", name="iPhone 17 预测", family_key="17", origin="legacy", availability="historical", price=100),
        phone("official", name="iPhone 17", family_key="17", origin="official", availability="unknown", price=None, storage_gb=None)]
    result = recommend(rows, Preferences(query="iPhone", budget_max=4000))["catalogue"]
    assert result["total"] == 2
    assert [record["id"] for record in result["phones"]] == ["base", "official"]
    counts = {record["family_key"]: record["catalogue_variant_count"] for record in result["phones"]}
    assert counts == {"current": 2, "17": 2}  # 未核验的历史配置不替代近期官网的待核验目录身份。
    rows[:2] = [phone("base", name="iPhone Current(256GB)", family_key="current", storage_gb=256, price=5000),
        phone("large", name="iPhone Current(512GB)", family_key="current", storage_gb=512, price=6000)]
    records = recommend(rows, Preferences(query="iPhone", budget_max=4000))["catalogue"]["phones"]
    assert next(record for record in records if record["family_key"] == "current")["id"] == "base"


@pytest.mark.parametrize("sort,expected", [("price_asc", ["low", "high", "unknown"]),
    ("price_desc", ["high", "low", "unknown"])])
def test_catalogue_explicit_price_sort_never_treats_unknown_as_zero(sort, expected):
    rows = [phone("unknown", name="iPhone Unknown", price=None), phone("high", name="iPhone High", price=7000),
        phone("low", name="iPhone Low", price=3000)]
    result = recommend(rows, Preferences(query="iPhone", sort=sort))["catalogue"]
    assert [record["id"] for record in result["phones"]] == expected
