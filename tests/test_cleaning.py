import pytest

from phone_assistant.cleaning import clean_phone


def raw_phone(**changes):
    raw = {
        "id": "1", "name": "小米 15 Ultra（16GB+512GB）", "brand": "Xiaomi",
        "price": "￥6,499", "image_url": None, "source_url": "https://example.com/phone/1",
        "fetched_at": "2026-10-03T10:00:00+08:00", "availability": "listed", "origin": "zol",
        "specs": {},
    }
    raw.update(changes)
    return raw


def test_spaced_zol_main_screen_system_and_primary_camera_labels_keep_original_specs():
    specs = {"主 屏幕尺寸": "6.3英寸", "主 屏幕刷新率": "120Hz", "出厂系统内核": "iOS 27",
        "后置摄像头1 后置摄像头": "4800万像素", "前置摄像头1 前置摄像头": "1800万像素"}
    record = clean_phone(raw_phone(name="苹果iPhone 18 Pro(256GB)", brand="苹果", specs=specs))
    assert record["display_inches"] == 6.3
    assert record["refresh_hz"] == 120
    assert record["os_family"] == "iOS"
    assert record["camera_mp"] == 48
    assert record["specs"] == specs
    assert record["battery_mah"] is None and record["charging_w"] is None


def test_apple_adapter_watts_and_playback_hours_are_not_phone_charge_or_battery_capacity():
    record = clean_phone(raw_phone(name="iPhone 18 Pro", brand="苹果", origin="official", specs={
        "电源和电池": "视频播放31小时，搭配60W电源适配器约20分钟充至50%", "续航时间": "31小时", "适配器": "60W"}))
    assert record["charging_w"] is None and record["battery_mah"] is None


@pytest.mark.parametrize("price,expected", [("￥ 247.4万 [北京 4GB厂商指导价]", 2474000), ("2.5万元", 25000), ("¥2.5千", 2500)])
def test_currency_multiplier_is_not_discarded(price, expected):
    assert clean_phone(raw_phone(name="VERTU眼镜蛇", brand="VERTU", price=price))["price"] == expected


def test_explicit_main_screen_and_adaptive_refresh_are_parsed_semantically():
    specs = {"屏幕尺寸": "主:8.03英寸 副:6.53英寸", "屏幕刷新率": "120Hz(1-120)>"}
    phone = clean_phone(raw_phone(specs=specs))
    assert phone["display_inches"] == 8.03
    assert phone["refresh_hz"] == 120
    assert phone["specs"] == specs


def test_normalization_is_unit_aware_and_keeps_original_specs():
    specs = {
        "RAM容量": "16384MB", "ROM容量": "1TB", "电池容量": "6Ah", "有线充电": "120W",
        "屏幕尺寸": "6.78英寸", "屏幕刷新率": "144Hz", "重量": "0.221kg", "厚度": "0.82cm",
        "主摄像素": "5000万像素", "CPU型号": "骁龙8至尊版 更多", "操作系统": "Android 15",
        "上市日期": "2025年03月03日", "NFC": "支持", "网络类型": "5G，4G，3G", "三防功能": "IP68",
    }
    phone = clean_phone(raw_phone(specs=specs))

    assert phone["brand"] == "小米"
    assert phone["price"] == 6499
    assert phone["ram_gb"] == 16
    assert phone["storage_gb"] == 1024
    assert phone["battery_mah"] == 6000
    assert phone["charging_w"] == 120
    assert phone["display_inches"] == 6.78
    assert phone["refresh_hz"] == 144
    assert phone["weight_g"] == 221
    assert phone["thickness_mm"] == pytest.approx(8.2)
    assert phone["camera_mp"] == 50
    assert phone["soc"] == "骁龙8至尊版"
    assert phone["release_date"] == "2025-03-03"
    assert phone["nfc"] is True and phone["five_g"] is True
    assert phone["fetched_at"] == "2026-10-03T02:00:00+00:00"
    assert phone["specs"] == specs


@pytest.mark.parametrize("text,expected", [("不支持", False), ("不支持NFC", False), ("支持", True), ("暂无参数", None), (None, None)])
def test_boolean_negation_and_unknown_are_distinct(text, expected):
    assert clean_phone(raw_phone(specs={"NFC": text}))["nfc"] is expected


def test_legacy_booleans_are_not_assumed_reliable():
    phone = clean_phone(raw_phone(origin="legacy", fetched_at=None, availability="historical", specs={"是否支持NFC": "1"}))

    assert phone["nfc"] is None
    assert phone["specs"]["是否支持NFC"] == "1"
    assert any(issue["code"] == "legacy_boolean_unverified" for issue in phone["issues"])
    assert phone["fetched_at"] is None


def test_ambiguous_configuration_is_not_guessed():
    phone = clean_phone(raw_phone(price="4999/5999元", specs={"RAM容量": "12/16GB", "ROM容量": "256GB/512GB"}))

    assert phone["price"] is None
    assert phone["ram_gb"] is None
    assert phone["storage_gb"] is None
    assert sum(issue["code"] == "ambiguous_quantity" for issue in phone["issues"]) == 3


@pytest.mark.parametrize("label,expected", [("512GB", 512), (" 1TB", 1024), ("2TB", 2048)])
def test_apple_exact_sku_capacity_does_not_inherit_series_rom(label, expected):
    specs = {"ROM容量": "256GB"}
    phone = clean_phone(raw_phone(name=f"苹果iPhone 18 Pro（{label}）", brand="苹果", specs=specs))

    assert phone["storage_gb"] == expected
    assert phone["specs"] == specs
    assert any(issue["code"] == "sku_storage_conflict" for issue in phone["issues"])
    assert phone["fetched_at"] == "2026-10-03T02:00:00+00:00"


def test_generic_official_apple_capacity_list_stays_unknown():
    phone = clean_phone(raw_phone(name="iPhone 18 Pro", brand="Apple", origin="official",
        specs={"ROM容量": "256GB 512GB 1TB 2TB"}))

    assert phone["storage_gb"] is None
    assert not any(issue["code"] == "sku_storage_conflict" for issue in phone["issues"])


def test_apple_capacity_range_in_name_is_not_a_single_configuration():
    phone = clean_phone(raw_phone(name="苹果iPhone 18 Pro（256GB/512GB）", brand="苹果",
        specs={"ROM容量": "256GB/512GB"}))
    assert phone["storage_gb"] is None


@pytest.mark.parametrize("name", ["苹果iPhone 18 Pro（256GB）（512GB）",
    "苹果iPhone 18 Pro（16GB）内存版（512GB）", "苹果iPhone 18 Pro（512GB）套装"])
def test_apple_non_unique_or_non_suffix_capacity_does_not_override_specs(name):
    phone = clean_phone(raw_phone(name=name, brand="苹果", specs={"ROM容量": "1TB"}))
    assert phone["storage_gb"] == 1024
    assert not any(issue["code"] == "sku_storage_conflict" for issue in phone["issues"])


def test_typical_battery_value_has_explicit_source_label():
    phone = clean_phone(raw_phone(specs={"电池容量": "6000mAh（典型值）；5800mAh（额定值）"}))

    assert phone["battery_mah"] == 6000


def test_known_bad_values_are_quarantined_without_guessing_corrections():
    phone = clean_phone(raw_phone(specs={"机身厚度(毫米)": "861", "运行内存RAM容量(GB)": "384"}))

    assert phone["thickness_mm"] is None
    assert phone["ram_gb"] is None
    assert phone["specs"]["机身厚度(毫米)"] == "861"
    assert {issue["field"] for issue in phone["issues"] if issue["code"] == "out_of_range"} == {"thickness_mm", "ram_gb"}


def test_real_kilobyte_unit_is_converted_without_assuming_gigabytes():
    phone = clean_phone(raw_phone(specs={"RAM容量": "384KB"}))

    assert phone["ram_gb"] == pytest.approx(384 / 1048576)


def test_mass_market_high_price_is_isolated_and_luxury_price_is_preserved():
    mass_market = clean_phone(raw_phone(name="一加 Ace 5 至尊版", brand="一加", price=59999))
    luxury = clean_phone(raw_phone(name="VERTU SIGNATURE 眼镜蛇限量款", brand="VERTU", price=2473990))

    assert mass_market["price"] is None
    assert any(issue["code"] == "price_outlier" for issue in mass_market["issues"])
    assert luxury["price"] == 2473990


def test_family_groups_capacity_variants_without_merging_pro_or_plus():
    base = clean_phone(raw_phone(name="小米 15 Ultra（12GB+256GB）"))
    variant = clean_phone(raw_phone(name="Xiaomi 15 Ultra（16GB/512GB）"))
    pro = clean_phone(raw_phone(name="小米 15 Pro（16GB/512GB）"))
    plus = clean_phone(raw_phone(name="小米 15 Ultra+"))

    assert base["family_key"] == variant["family_key"]
    assert base["family_key"] != pro["family_key"]
    assert base["family_key"] != plus["family_key"]


def test_partial_release_date_keeps_year_without_inventing_day():
    phone = clean_phone(raw_phone(specs={"上市日期": "2025年10月"}))

    assert phone["release_year"] == 2025
    assert phone["release_date"] is None
    assert phone["release_month"] == 10
    assert phone["release_precision"] == "month"


def test_official_starting_price_does_not_become_a_configuration_price():
    phone = clean_phone(raw_phone(origin="official", price=None, price_from="￥5499",
        new_from_source=True, new_release_catalog_url="https://www.vivo.com.cn/",
        specs={"上市日期": "2026年09月21日", "ROM容量": "256GB/512GB"}))

    assert phone["price"] is None
    assert phone["price_from"] == 5499
    assert phone["storage_gb"] is None
    assert phone["release_date"] == "2026-09-21"
    assert phone["release_month"] == 9
    assert phone["release_precision"] == "day"
    assert phone["new_release_catalog_url"] == "https://www.vivo.com.cn/"
    assert phone["new_from_source"] is True


def test_release_year_alone_does_not_invent_a_month():
    phone = clean_phone(raw_phone(specs={"上市日期": "2026年"}))

    assert phone["release_year"] == 2026
    assert phone["release_month"] is None
    assert phone["release_date"] is None
    assert phone["release_precision"] == "year"


def test_camera_selects_labeled_rear_main_camera_and_converts_pixels():
    phone = clean_phone(raw_phone(specs={
        "摄像头系统详情": '[{"type":"前置","pixels":"3200万像素"},{"type":"后置","pixels":"20000万像素","tags":["长焦"]},{"type":"后置","pixels":"5000万像素","tags":["主摄"]}]'
    }))

    assert phone["camera_mp"] == 50


def test_unpriced_record_does_not_use_ecommerce_quote_as_reference_price():
    phone = clean_phone(raw_phone(price="暂无报价", specs={"电商报价": "￥3999"}))

    assert phone["price"] is None
    assert phone["specs"]["电商报价"] == "￥3999"


def test_unknown_specs_remain_null_without_default_features():
    phone = clean_phone(raw_phone(specs={}))

    assert all(phone[field] is None for field in ("ram_gb", "battery_mah", "nfc", "five_g", "waterproof"))


def test_network_negation_is_scoped_to_5g_instead_of_other_protocols():
    assert clean_phone(raw_phone(specs={"网络类型": "5G，4G，不支持CDMA"}))["five_g"] is True
    assert clean_phone(raw_phone(specs={"网络类型": "不支持5G，支持4G"}))["five_g"] is False


@pytest.mark.parametrize("text,family", [("安卓 15", "Android"), ("HarmonyOS NEXT", "HarmonyOS"), ("鸿蒙 5", "HarmonyOS"), ("iOS 19", "iOS"), ("某自有系统", "other")])
def test_os_family_preserves_the_original_display_text(text, family):
    phone = clean_phone(raw_phone(specs={"操作系统": text}))

    assert phone["os"] == text
    assert phone["os_family"] == family


def test_invalid_camera_json_structure_is_a_quality_issue():
    phone = clean_phone(raw_phone(specs={"摄像头系统详情": '["50MP"]'}))

    assert phone["camera_mp"] is None
    assert any(issue["code"] == "invalid_camera_json" for issue in phone["issues"])


def test_invalid_timestamp_and_missing_id_are_explicit():
    assert clean_phone(raw_phone(fetched_at="2026-10-03T10:00:00"))["fetched_at"] is None
    with pytest.raises(ValueError, match="非空 id"):
        clean_phone(raw_phone(id=None))
