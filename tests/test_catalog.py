from pathlib import Path

from openpyxl import Workbook
import pytest

from phone_assistant.catalog import CATALOG_SOURCE, PhoneCatalog
from phone_assistant.knowledge import PROJECT_ROOT


HEADERS = [
    "产品ID", "产品型号", "品牌", "系列", "发布年份",
    "参考价格(人民币)", "CPU型号", "是否支持NFC",
]


def write_catalog(root: Path, rows: list[list]) -> None:
    path = root / CATALOG_SOURCE
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(HEADERS)
    for row in rows:
        worksheet.append(row)
    workbook.save(path)
    workbook.close()


@pytest.fixture
def catalog_root(tmp_path: Path) -> Path:
    write_catalog(tmp_path, [
        [101, "小米 15", "小米", "15", 2024, 4499, None, 0],
        [102, "小米 15 Ultra", "小米", "15 Ultra", 2025, 6499, "骁龙8至尊版", 1],
        [103, "小米 15 Ultra", "小米", "15 Ultra", 2025, 6999, "骁龙8至尊版", 1],
        [104, "HUAWEI Pura 70 Ultra", "HUAWEI", "Pura 70 Ultra", 2024, 8199, "麒麟9010", 1],
        [105, "HUAWEI Pura 70", "HUAWEI", "Pura 70", 2024, 4649, None, 1],
        [106, "OPPO Find X8 Ultra", "OPPO", "Find X8 Ultra", 2025, 6499, None, 1],
        [107, "苹果iPhone 16 Pro（128GB）", "苹果", "iPhone 16 Pro（128GB）", 2024, 5999, "A18 Pro", 1],
        [108, "苹果iPhone 16 Pro（256GB）", "苹果", "iPhone 16 Pro（256GB）", 2024, 6999, "A18 Pro", 1],
        [109, "iPhone 16", "iPhone", "16", 2024, 4799, "A18", 1],
        [110, "一加13", "一加", "13", 2024, 4499, None, 1],
        [111, "飞利浦E180", "飞利浦", "E180", None, None, None, 0],
        [112, "SOYES H1", "SOYES", "H1", 2011, None, None, 0],
        [None] * len(HEADERS),
        [" ", "", "  ", None, None, None, None, None],
    ])
    return tmp_path


def test_records_keep_original_columns_values_and_blank_cells(catalog_root: Path):
    catalog = PhoneCatalog(catalog_root)

    assert len(catalog.records) == 12
    assert list(catalog.records[0]) == HEADERS
    assert catalog.records[0]["产品ID"] == 101
    assert catalog.records[0]["CPU型号"] is None
    assert catalog.records[0]["是否支持NFC"] == 0
    assert catalog.records[10]["参考价格(人民币)"] is None


def test_stats_and_brand_names(catalog_root: Path):
    catalog = PhoneCatalog(catalog_root)

    assert catalog.stats == {"records": 12, "brands": 8, "min_year": 2011, "max_year": 2025}
    assert catalog.brands == sorted(["小米", "HUAWEI", "OPPO", "苹果", "iPhone", "一加", "飞利浦", "SOYES"])


@pytest.mark.parametrize("brand", ["HUAWEI", "Huawei", "华为"])
def test_brand_filter_handles_chinese_and_english_aliases(catalog_root: Path, brand: str):
    records = PhoneCatalog(catalog_root).filter(brand=brand)

    assert len(records) == 2
    assert all(record["品牌"] == "HUAWEI" for record in records)


def test_keyword_filter_matches_model_and_brand_without_spaces(catalog_root: Path):
    catalog = PhoneCatalog(catalog_root)

    assert len(catalog.filter(keyword="Xiaomi15Ultra")) == 2
    assert len(catalog.filter(keyword="find x8")) == 1
    assert len(catalog.filter(keyword="华为")) == 2
    assert len(catalog.filter(brand="苹果")) == 3
    assert catalog.filter(keyword="unlistedphone") == []
    assert catalog.filter(keyword="   ") == catalog.records


def test_year_filters_are_inclusive_and_exclude_unknown_years(catalog_root: Path):
    catalog = PhoneCatalog(catalog_root)

    assert len(catalog.filter(min_year=2025, max_year=2025)) == 3
    assert len(catalog.filter(max_year=2011)) == 1
    assert all(record["发布年份"] is not None for record in catalog.filter(min_year=2011))
    assert catalog.filter(min_year=2025, max_year=2024) == []
    assert len(catalog.filter(brand="小米", min_year=2025, keyword="Ultra")) == 2


@pytest.mark.parametrize("question", [
    "小米15Ultra的相机怎么样？",
    "Xiaomi 15 Ultra camera",
    "xiaomi15ultra",
    "小 米 15 Ultra 的屏幕",
])
def test_question_matches_explicit_complete_model(catalog_root: Path, question: str):
    records = PhoneCatalog(catalog_root).find_in_question(question)

    assert len(records) == 1
    assert records[0]["产品型号"] == "小米 15 Ultra"
    assert records[0]["产品ID"] == 102


def test_question_handles_english_brand_and_specific_family_alias(catalog_root: Path):
    catalog = PhoneCatalog(catalog_root)

    assert catalog.find_in_question("HuaweiPura70Ultra拍照")[0]["产品ID"] == 104
    assert catalog.find_in_question("Pura 70 Ultra 拍照")[0]["产品ID"] == 104
    assert catalog.find_in_question("Find X8 Ultra camera")[0]["产品ID"] == 106
    assert catalog.find_in_question("OnePlus13电池")[0]["产品ID"] == 110


def test_prefix_model_is_not_selected_instead_of_ultra(catalog_root: Path):
    catalog = PhoneCatalog(catalog_root)

    assert [record["产品ID"] for record in catalog.find_in_question("小米15Ultra和华为Pura70Ultra")] == [102, 104]
    assert catalog.find_in_question("小米15UltraMax怎么样") == []
    assert catalog.find_in_question("OPPO Find X8 Ultra2") == []


def test_two_explicit_models_follow_question_order(catalog_root: Path):
    catalog = PhoneCatalog(catalog_root)

    assert [record["产品ID"] for record in catalog.find_in_question("华为Pura70Ultra对比小米15Ultra")] == [104, 102]
    assert [record["产品ID"] for record in catalog.find_in_question("小米15和小米15Ultra")] == [101, 102]
    assert [record["产品ID"] for record in catalog.find_in_question("华为Pura70Ultra对比小米15Ultra", limit=1)] == [104]


def test_capacity_suffix_can_be_omitted_or_named(catalog_root: Path):
    catalog = PhoneCatalog(catalog_root)

    assert catalog.find_in_question("iPhone 16 Pro camera")[0]["产品ID"] == 107
    assert catalog.find_in_question("iPhone 16 Pro 256GB camera")[0]["产品ID"] == 108
    assert catalog.find_in_question("苹果iPhone16Pro（256GB）的性能")[0]["产品ID"] == 108


def test_repeated_model_mentions_do_not_repeat_records(catalog_root: Path):
    records = PhoneCatalog(catalog_root).find_in_question("小米15Ultra，Xiaomi15Ultra的充电怎么样")

    assert len(records) == 1


@pytest.mark.parametrize("question", ["IMX7传感器性能如何？", "索尼IMX9主摄如何？", "Android9S版本有什么不同？"])
def test_embedded_component_or_system_name_does_not_match_phone(tmp_path: Path, question: str):
    write_catalog(tmp_path, [
        [1, "X7", None, "X7", 2020, None, None, None],
        [2, "X9", None, "X9", 2020, None, None, None],
        [3, "9S", None, "9S", 2020, None, None, None],
    ])
    catalog = PhoneCatalog(tmp_path)

    assert catalog.find_in_question(question) == []
    assert catalog.find_in_question("X7拍照如何？")[0]["产品ID"] == 1


def test_model_boundary_allows_chinese_adjacent_text_and_iphone_compound(catalog_root: Path):
    catalog = PhoneCatalog(catalog_root)

    assert catalog.find_in_question("看看小米15Ultra的影像")[0]["产品ID"] == 102
    assert catalog.find_in_question("Compare iPhone16Pro camera")[0]["产品ID"] == 107


@pytest.mark.parametrize("question", ["", "   ", "推荐小米手机", "Huawei拍照怎么样", "预算5000元", "2025年哪些型号值得买", "13的价格"])
def test_question_without_explicit_model_returns_no_rows(catalog_root: Path, question: str):
    assert PhoneCatalog(catalog_root).find_in_question(question) == []


def test_zero_or_negative_question_limit(catalog_root: Path):
    catalog = PhoneCatalog(catalog_root)

    assert catalog.find_in_question("小米15Ultra", limit=0) == []
    assert catalog.find_in_question("小米15Ultra", limit=-1) == []


def test_missing_workbook_has_clear_error(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="缺少手机数据表"):
        PhoneCatalog(tmp_path)


def test_empty_workbook_and_unknown_year(tmp_path: Path):
    write_catalog(tmp_path, [])
    catalog = PhoneCatalog(tmp_path)

    assert catalog.stats == {"records": 0, "brands": 0, "min_year": None, "max_year": None}
    assert catalog.brands == []
    assert catalog.filter() == []
    assert catalog.find_in_question("小米15Ultra") == []


def test_recovered_workbook_has_all_original_fields_and_known_range():
    catalog = PhoneCatalog(PROJECT_ROOT)

    assert catalog.stats == {"records": 4018, "brands": 94, "min_year": 2011, "max_year": 2025}
    assert all(len(record) == 60 for record in catalog.records)
    records = catalog.find_in_question("小米15Ultra和华为Pura70Ultra拍照取舍")
    assert [record["产品型号"] for record in records] == ["小米 15 Ultra", "HUAWEI Pura 70 Ultra"]
    assert records[0]["发布年份"] == 2025
