from datetime import datetime, timedelta, timezone
import json
from hashlib import sha256
import sqlite3

from openpyxl import Workbook
import pytest

from phone_assistant.catalog import CATALOG_SOURCE
from phone_assistant.cleaning import CLEANING_VERSION
from phone_assistant.import_legacy import import_legacy
import phone_assistant.storage as storage_module
from phone_assistant.storage import Storage


def raw_phone(**changes):
    raw = {
        "id": "1", "name": "小米 15", "brand": "小米", "price": 4499,
        "source_url": "https://example.com/1", "fetched_at": datetime.now(timezone.utc).isoformat(),
        "availability": "listed", "origin": "zol", "specs": {"RAM容量": "12GB", "ROM容量": "256GB"},
    }
    raw.update(changes)
    return raw


@pytest.fixture
def storage(tmp_path):
    return Storage(tmp_path / "phones.sqlite3")


def test_official_family_common_specs_apply_to_list_and_detail_without_crossing_sku_facts(storage):
    storage.upsert_raw(raw_phone(id="sku", name="苹果iPhone 18 Pro(2TB)", brand="苹果", price=20499,
        specs={"ROM容量": "2TB", "操作系统": "iOS 26", "RAM容量": "12GB", "电池容量": "4000mAh", "有线充电": "25W"}))
    before = storage.get_phone("sku")
    captured = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    storage.upsert_raw(raw_phone(id="official", name="iPhone 18 Pro", brand="苹果", origin="official", price=None,
        fetched_at=captured, specs={"CPU型号": "A20 Pro", "操作系统": "iOS 27", "屏幕尺寸": "6.3英寸",
            "屏幕刷新率": "120Hz", "ROM容量": "256GB", "RAM容量": "8GB", "电池容量": "5000mAh", "有线充电": "60W"}))
    detail = storage.get_phone("sku")
    listed = next(phone for phone in storage.list_phones() if phone["id"] == "sku")
    assert listed == detail
    assert detail["soc"] == "A20 Pro" and detail["display_inches"] == 6.3 and detail["refresh_hz"] == 120
    assert detail["os"] == "iOS 27"
    assert detail["reported_family_specs"]["os"] == "iOS 26"
    os_conflict = next(conflict for conflict in detail["source_conflicts"] if conflict["field"] == "os")
    assert os_conflict["reported_source"] == before["field_sources"]["os"]
    assert os_conflict["fetched_at"] == captured
    assert detail["field_sources"]["soc"]["origin"] == "official"
    assert detail["field_sources"]["soc"]["fetched_at"] == captured
    for field in ("price", "ram_gb", "storage_gb", "battery_mah", "charging_w", "fetched_at", "price_fetched_at"):
        assert detail[field] == before[field]
    assert detail["field_sources"]["price"] == before["field_sources"]["price"]
    assert detail["specs"]["操作系统"] == "iOS 26"
    storage.reclean()
    assert storage.get_phone("sku")["soc"] == "A20 Pro"
    assert storage.summary()["snapshots"] == 2


def test_family_shared_specs_do_not_cross_pro_and_pro_max_or_refresh_quote_time(storage):
    storage.upsert_raw(raw_phone(id="sku", name="苹果iPhone 18 Pro Max(512GB)", brand="苹果", specs={"ROM容量": "512GB"}))
    storage.upsert_raw(raw_phone(id="official", name="iPhone 18 Pro", brand="苹果", origin="official", price=None,
        specs={"CPU型号": "A20 Pro", "屏幕尺寸": "6.3英寸"}))
    assert storage.get_phone("sku")["display_inches"] is None
    assert storage.get_phone("sku")["soc"] is None


def test_equal_time_official_family_sources_resolve_deterministically_for_list_and_detail(storage):
    stamp = "2026-10-03T09:00:00+00:00"
    for phone_id, soc in [("official-a", "A19 Pro"), ("official-z", "A20 Pro")]:
        storage.upsert_raw(raw_phone(id=phone_id, name="iPhone 18 Pro", brand="苹果", origin="official", price=None,
            fetched_at=stamp, specs={"CPU型号": soc}))
    listed = {phone["id"]: phone for phone in storage.list_phones()}
    for phone_id in listed:
        assert storage.get_phone(phone_id) == listed[phone_id]
        assert listed[phone_id]["soc"] == "A20 Pro"


def test_apple_soc_brand_prefix_and_same_ios_description_are_not_false_spec_conflicts(storage):
    storage.upsert_raw(raw_phone(id="sku", name="苹果iPhone 18 Pro(256GB)", brand="苹果",
        specs={"CPU型号": "苹果 A20 Pro", "操作系统": "iOS 27"}))
    storage.upsert_raw(raw_phone(id="official", name="iPhone 18 Pro", brand="苹果", origin="official", price=None,
        specs={"CPU型号": "A20 Pro", "操作系统": "iOS 27 iOS移动操作系统介绍"}))
    phone = storage.get_phone("sku")
    assert phone["soc"] == "A20 Pro"
    assert phone["reported_family_specs"]["soc"] == "苹果 A20 Pro"
    assert "source_conflicts" not in phone


def test_upsert_retains_snapshot_and_cleaned_record(storage):
    phone = storage.upsert_raw(raw_phone())

    assert phone["price"] == 4499
    assert storage.get_phone("1")["ram_gb"] == 12
    assert len(storage.list_phones()) == 1
    assert storage.get_phone("missing") is None
    assert storage.summary()["snapshots"] == 1
    assert storage.summary()["fresh_records"] == 1


def test_price_and_specification_times_follow_their_actual_responses(storage):
    phone = storage.upsert_raw(raw_phone(fetched_at="2026-10-03T02:00:00+00:00",
        price_source_url="https://example.com/list", price_fetched_at="2026-09-01T00:00:00+00:00",
        specs_source_url="https://example.com/param", specs_fetched_at="2026-10-03T02:00:00+00:00"))
    assert phone["field_sources"]["price"]["fetched_at"] == "2026-09-01T00:00:00+00:00"
    assert phone["field_sources"]["ram_gb"]["fetched_at"] == "2026-10-03T02:00:00+00:00"
    assert phone["specs_sources"]["RAM容量"]["fetched_at"] == "2026-10-03T02:00:00+00:00"


def test_unknown_price_capture_time_is_not_borrowed_from_parameter_page(storage):
    phone = storage.upsert_raw(raw_phone(price_source_url="https://example.com/list"))
    assert phone["field_sources"]["price"]["fetched_at"] is None
    assert phone["field_sources"]["ram_gb"]["fetched_at"] is not None


def test_apple_sku_capacity_keeps_its_identity_source_through_reclean(storage):
    stamp = "2026-10-03T17:25:10+00:00"
    raw = raw_phone(name="苹果iPhone 18 Pro（2TB）", brand="苹果",
        source_url="https://detail.zol.com.cn/cell_phone/index2177482.shtml",
        fetched_at=stamp, specs_fetched_at=stamp,
        specs_source_url="https://detail.zol.com.cn/series/57/544/param_10929893_0_1.html",
        specs={"ROM容量": "256GB"})
    storage.upsert_raw(raw)
    storage.reclean()
    phone = storage.get_phone("1")

    assert phone["storage_gb"] == 2048
    assert phone["field_sources"]["storage_gb"] == {
        "origin": "zol", "source_url": raw["source_url"], "fetched_at": stamp}
    assert phone["specs_sources"]["ROM容量"]["source_url"] == raw["specs_source_url"]
    assert phone["specs"]["ROM容量"] == "256GB"
    assert phone["field_sources"]["price"]["fetched_at"] == stamp


def test_official_evidence_survives_later_directory_estimates_and_reclean(storage):
    storage.upsert_raw(raw_phone(origin="official", price=None, price_from=5499,
        fetched_at="2026-10-03T01:00:00+00:00", specs={"电池容量": "8000mAh", "上市日期": "2026年09月"},
        release_source_url="https://www.vivo.com.cn/brand/news/1",
        release_fetched_at="2026-10-03T00:00:00+00:00"))
    storage.upsert_raw(raw_phone(fetched_at="2026-10-03T02:00:00+00:00",
        specs={"电池容量": "7500mAh", "上市日期": "2026年08月"}))
    storage.reclean()
    phone = storage.get_phone("1")

    assert phone["origin"] == "official"
    assert phone["price"] == 4499
    assert phone["price_from"] == 5499
    assert phone["battery_mah"] == 8000
    assert phone["release_month"] == 9
    assert phone["release_date"] is None
    assert phone["field_sources"]["price"]["origin"] == "zol"
    assert phone["field_sources"]["release_month"]["source_url"] == "https://www.vivo.com.cn/brand/news/1"
    assert storage.summary()["fresh_records"] == 1
    assert storage.summary()["official_records"] == 1


def test_official_family_corrects_conflicting_year_without_inventing_a_day(storage):
    storage.upsert_raw(raw_phone(id="zol-1", name="vivo X500(12GB/256GB)", brand="vivo", price=5499,
        specs={"上市日期": "2025-09-21", "ROM容量": "256GB"}))
    storage.upsert_raw(raw_phone(id="official-1", name="vivo X500(12GB+256GB)", brand="vivo", origin="official", price=5999,
        specs={"上市日期": "2026年09月", "ROM容量": "256GB"}))
    phone = storage.get_phone("zol-1")

    assert phone["release_year"] == 2026
    assert phone["release_month"] == 9
    assert phone["release_date"] is None
    assert phone["release_precision"] == "month"
    assert phone["price"] == 5499
    assert phone["reported_release"]["release_date"] == "2025-09-21"
    assert phone["specs"]["上市日期"] == "2025-09-21"
    assert any(issue["code"] == "release_source_conflict" for issue in phone["issues"])
    assert phone["field_sources"]["release_year"]["origin"] == "official"
    with storage._connection() as connection:
        stored = json.loads(connection.execute("SELECT record_json FROM phones WHERE id='zol-1'").fetchone()[0])
    assert stored["release_date"] == "2025-09-21"
    storage.reclean()
    assert storage.get_phone("zol-1")["release_date"] is None
    assert storage.summary()["snapshots"] == 2


def test_official_month_agrees_with_a_more_precise_directory_date(storage):
    storage.upsert_raw(raw_phone(id="zol-1", name="vivo X500", brand="vivo", specs={"上市日期": "2026-09-21"}))
    storage.upsert_raw(raw_phone(id="official-1", name="vivo X500", brand="vivo", origin="official", specs={"上市日期": "2026年09月"}))

    phone = storage.get_phone("zol-1")
    assert phone["release_date"] == "2026-09-21"
    assert phone["release_precision"] == "day"
    assert "source_conflicts" not in phone


def test_official_future_launch_prevents_directory_variants_from_being_recommended(storage):
    from phone_assistant.recommendation import Preferences, recommend

    today = datetime.now(timezone(timedelta(hours=8))).date()
    directory_date = (today + timedelta(days=12)).isoformat()
    official_date = (today + timedelta(days=19)).isoformat()
    storage.upsert_raw(raw_phone(id="zol-1", name="苹果iPhone Duo(256GB)", brand="苹果", price=9999,
        specs={"上市日期": directory_date, "ROM容量": "256GB"}))
    storage.upsert_raw(raw_phone(id="official-1", name="iPhone Duo", brand="苹果", origin="official", price=None,
        availability="unknown", new_from_source=True, specs={"上市日期": official_date}))

    phone = storage.get_phone("zol-1")
    assert phone["release_date"] == official_date
    assert phone["availability"] == "announced"
    assert phone["price"] == 9999
    assert recommend(storage.list_phones(), Preferences(budget_max=20000))["total"] == 0


def test_explicit_timestamp_correction_is_replayable_and_does_not_beat_future_capture(storage):
    incorrect = "2026-10-03T02:00:00+00:00"
    actual = "2026-09-01T00:00:00+00:00"
    storage.upsert_raw(raw_phone(fetched_at=incorrect))
    corrected = raw_phone(fetched_at=actual, price_fetched_at=actual, specs_fetched_at=actual, _corrects_fetched_at=incorrect)
    phone = storage.upsert_raw(corrected)
    assert phone["fetched_at"] == actual
    assert phone["field_sources"]["price"]["fetched_at"] == actual
    storage.reclean()
    assert storage.get_phone("1")["fetched_at"] == actual
    storage.upsert_raw(raw_phone(price=3000, fetched_at="2026-10-03T03:00:00+00:00"))
    storage.upsert_raw(corrected)
    storage.reclean()
    assert storage.get_phone("1")["price"] == 3000
    assert storage.summary()["snapshots"] == 4


def test_timestamp_correction_does_not_roll_back_independently_newer_price(storage):
    target = "2026-10-03T02:00:00+00:00"
    latest_price = "2026-10-03T04:00:00+00:00"
    storage.upsert_raw(raw_phone(price=1000, fetched_at=target))
    storage.upsert_raw(raw_phone(price=2000, fetched_at="2026-10-03T01:00:00+00:00", price_fetched_at=latest_price))
    storage.upsert_raw(raw_phone(price=1000, fetched_at="2026-10-03T00:00:00+00:00", _corrects_fetched_at=target))
    assert storage.get_phone("1")["price"] == 2000
    assert storage.get_phone("1")["field_sources"]["price"]["fetched_at"] == latest_price
    storage.reclean()
    assert storage.get_phone("1")["price"] == 2000


def test_historical_import_does_not_override_fresh_fields(storage):
    storage.upsert_raw(raw_phone(price=4999, specs={"RAM容量": "16GB"}))
    phone = storage.upsert_raw(raw_phone(price=1999, origin="legacy", availability="historical", fetched_at=None, specs={"RAM容量": "8GB"}))

    assert phone["price"] == 4999
    assert phone["ram_gb"] == 16
    assert phone["origin"] == "zol"
    assert phone["availability"] == "listed"
    assert phone["specs"]["RAM容量"] == "16GB"
    assert storage.summary()["snapshots"] == 2


def test_missing_fresh_field_preserves_previous_value_and_its_source(storage):
    storage.upsert_raw(raw_phone(price=4499, origin="legacy", availability="historical", fetched_at=None,
                                 source_url=None, legacy_source="phones.xlsx#row=2"))
    phone = storage.upsert_raw(raw_phone(price=None, specs={"RAM容量": "16GB"}))

    assert phone["price"] == 4499
    assert phone["ram_gb"] == 16
    assert phone["field_sources"]["price"] == {"origin": "legacy", "source_url": "phones.xlsx#row=2", "fetched_at": None}
    assert phone["field_sources"]["ram_gb"]["origin"] == "zol"
    assert phone["field_sources"]["price"]["fetched_at"] != phone["fetched_at"]


def test_each_original_specification_keeps_its_own_source(storage):
    storage.upsert_raw(raw_phone(origin="legacy", fetched_at=None, availability="historical", source_url=None,
                                 legacy_source="phones.xlsx#row=2", specs={"旧字段": "旧内容", "RAM容量": "8GB"}))
    phone = storage.upsert_raw(raw_phone(specs_source_url="https://example.com/specs", specs={"旧字段": None, "RAM容量": "16GB"}))

    assert phone["specs"]["旧字段"] == "旧内容"
    assert phone["specs_sources"]["旧字段"] == {"origin": "legacy", "source_url": "phones.xlsx#row=2", "fetched_at": None}
    assert phone["specs_sources"]["RAM容量"]["origin"] == "zol"
    assert phone["specs_sources"]["RAM容量"]["source_url"] == "https://example.com/specs"


def test_newer_capture_wins_and_older_capture_only_fills_unknown(storage):
    storage.upsert_raw(raw_phone(price=4999, fetched_at="2026-10-03T00:00:00+00:00", specs={"RAM容量": "16GB"}))
    phone = storage.upsert_raw(raw_phone(price=3999, fetched_at="2026-10-02T00:00:00+00:00",
                                        specs={"RAM容量": "12GB", "电池容量": "6000mAh"}))

    assert phone["price"] == 4999
    assert phone["ram_gb"] == 16
    assert phone["battery_mah"] == 6000
    assert phone["field_sources"]["battery_mah"]["fetched_at"] == "2026-10-02T00:00:00+00:00"


def test_reference_price_and_specification_sources_are_distinct(storage):
    phone = storage.upsert_raw(raw_phone(price_source_url="https://example.com/list",
                                         specs_source_url="https://example.com/specs"))

    assert phone["field_sources"]["price"]["source_url"].endswith("/list")
    assert phone["field_sources"]["ram_gb"]["source_url"].endswith("/specs")


def test_failed_batch_rolls_back_snapshots_records_and_issues(storage):
    storage.upsert_raw(raw_phone(id="existing"))
    before = storage.summary()
    with pytest.raises(ValueError, match="非空 id"):
        storage.import_many([raw_phone(id="new"), raw_phone(id=None)])

    assert storage.get_phone("new") is None
    assert storage.summary()["records"] == before["records"]
    assert storage.summary()["snapshots"] == before["snapshots"]


def test_reclean_replays_snapshots_without_losing_provenance_or_appending_snapshots(storage):
    storage.upsert_raw(raw_phone(origin="legacy", fetched_at=None, availability="historical", price=1999))
    storage.upsert_raw(raw_phone(price=4999))
    before = storage.get_phone("1")
    report = storage.reclean()

    assert report["recleaned"] == 2
    assert report["snapshots"] == 2
    assert storage.get_phone("1") == before
    with sqlite3.connect(storage.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM quality_issues").fetchone()[0] == 1


def test_same_version_reclean_removes_obsolete_parser_issues_and_preserves_other_versions(storage, monkeypatch):
    current_clean = storage_module.clean_phone

    def old_currency_parser(raw):
        phone = current_clean(raw)
        phone["price"] = None
        phone["issues"] = [{"field": "price", "code": "unparsed_quantity", "severity": "warning", "message": "旧规则无法识别￥前缀"}]
        return phone

    monkeypatch.setattr(storage_module, "clean_phone", old_currency_parser)
    storage.upsert_raw(raw_phone(price="￥4499"))
    assert storage.get_phone("1")["price"] is None
    monkeypatch.setattr(storage_module, "clean_phone", current_clean)
    with sqlite3.connect(storage.path) as connection:
        connection.execute(
            "INSERT INTO quality_issues(snapshot_id,phone_id,cleaning_version,field,code,severity,message) VALUES(1,'1','older-version','price','old_audit','info','另一个版本的审计')"
        )

    storage.reclean()

    assert storage.get_phone("1")["price"] == 4499
    with sqlite3.connect(storage.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM quality_issues WHERE cleaning_version=?", (CLEANING_VERSION,)).fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM quality_issues WHERE cleaning_version='older-version'").fetchone()[0] == 1


def test_quality_issues_are_available_in_summary_and_raw_values_remain(storage):
    storage.upsert_raw(raw_phone(price=59999, specs={"机身厚度(毫米)": "861"}))
    report = storage.summary()

    assert report["issue_counts"]["price_outlier"] == 1
    assert report["issue_counts"]["out_of_range"] == 1
    with sqlite3.connect(storage.path) as connection:
        raw = connection.execute("SELECT raw_json FROM raw_snapshots").fetchone()[0]
        assert "59999" in raw and "861" in raw


def test_empty_summary_is_stable(storage):
    report = storage.summary()

    assert report["records"] == report["snapshots"] == report["current_records"] == 0
    assert report["missing_price"] == report["issues"] == 0
    assert report["cleaning_version"]


def test_legacy_import_keeps_workbook_unchanged_and_preserves_missing_facts(storage, tmp_path):
    path = tmp_path / CATALOG_SOURCE
    path.parent.mkdir(parents=True)
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(["产品ID", "产品型号", "品牌", "参考价格(人民币)", "运行内存RAM容量(GB)", "是否支持NFC", "CPU型号"])
    worksheet.append([123, "小米 12", "小米", 1999, 8, 0, None])
    workbook.save(path)
    workbook.close()
    original_hash = sha256(path.read_bytes()).hexdigest()

    report = import_legacy(storage, root=tmp_path)
    phone = storage.get_phone("123")

    assert report["imported"] == 1
    assert phone["availability"] == "historical"
    assert phone["fetched_at"] is None
    assert phone["ram_gb"] == 8
    assert phone["nfc"] is None
    assert phone["field_sources"]["ram_gb"]["source_url"].endswith("#row=2")
    assert sha256(path.read_bytes()).hexdigest() == original_hash
    with sqlite3.connect(storage.path) as connection:
        raw = connection.execute("SELECT raw_json FROM raw_snapshots").fetchone()[0]
        assert '"CPU型号": null' in raw
