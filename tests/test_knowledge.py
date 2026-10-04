from pathlib import Path

import pytest

from phone_assistant.knowledge import (
    KnowledgeBase,
    MAX_CHUNK_CHARACTERS,
    PROJECT_ROOT,
)


@pytest.fixture
def knowledge_root(tmp_path: Path) -> Path:
    documents = {
        "docs/by_brand/xiaomi.md": (
            "# 小米手机技术报告\n\n"
            "## 小米15 Ultra\n\n徕卡影像旗舰。\n\n"
            "### 影像系统\n\n主摄采用索尼 LYT-900，支持光学防抖。\n\n"
            "### 电池与充电\n\n电池容量 5410mAh，支持 90W 有线充电。\n\n"
            "## 小米14 Ultra\n\n上一代影像旗舰，电池为 5000mAh。\n"
        ),
        "data/brands/oneplus/specs.md": (
            "# OnePlus 技术规格\n\n"
            "## OnePlus 13\n\n骁龙旗舰处理器，支持快速充电。\n\n"
            "## OnePlus 12\n\n上一代旗舰，支持无线充电。\n"
        ),
        "docs/by_category/camera.md": (
            "# 摄影技术\n\n## 传感器\n\n大尺寸传感器可以改善暗光拍照。\n"
        ),
        "docs_archive/project_docs/README.md": (
            "# 项目验收\n\n不应检索到的独特词 zzzprojectonly。\n"
        ),
        "docs_archive/rag_docs/RAG_Embedding_Strategy.md": (
            "# RAG 教程\n\n不应检索到的独特词 zzzembeddingonly。\n"
        ),
        "data/gsmarena/DATA_COLLECTION_GUIDE.md": (
            "# 收集教程\n\n不应检索到的独特词 zzzguideonly。\n"
        ),
    }
    for source, content in documents.items():
        path = tmp_path / source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("query", ["小米15 Ultra 的相机", "Xiaomi 15 Ultra camera"])
def test_specific_phone_matches_in_chinese_and_english(knowledge_root: Path, query: str):
    results = KnowledgeBase(knowledge_root).search(query)

    assert results
    assert "小米15 Ultra" in results[0].chunk.title
    assert all("小米14 Ultra" not in result.chunk.title for result in results)
    assert all(result.score > 0 for result in results)
    assert results[0].chunk.source == "docs/by_brand/xiaomi.md"


@pytest.mark.parametrize("query", ["一加13", "OnePlus13", "oneplus 13"])
def test_brand_alias_and_model_spacing(knowledge_root: Path, query: str):
    results = KnowledgeBase(knowledge_root).search(query)

    assert results
    assert "OnePlus 13" in results[0].chunk.title
    assert all("OnePlus 12" not in result.chunk.title for result in results)


def test_technical_question_uses_chinese_bigrams(knowledge_root: Path):
    results = KnowledgeBase(knowledge_root).search("暗光拍照和传感器有什么关系？")

    assert results[0].chunk.source == "docs/by_category/camera.md"


def test_headings_preserve_parent_model_context(knowledge_root: Path):
    results = KnowledgeBase(knowledge_root).search("小米15 Ultra 充电")

    assert results[0].chunk.title == "小米手机技术报告 / 小米15 Ultra / 电池与充电"
    assert "5410mAh" in results[0].chunk.content
    assert "索尼" not in results[0].chunk.content


@pytest.mark.parametrize("query", ["小米15 Ultra 相机", "Xiaomi 15 Ultra camera"])
def test_camera_synonyms_prefer_the_camera_section(knowledge_root: Path, query: str):
    results = KnowledgeBase(knowledge_root).search(query)

    assert results[0].chunk.title.endswith("影像系统")


def test_english_battery_question_uses_the_chinese_section(knowledge_root: Path):
    results = KnowledgeBase(knowledge_root).search("Xiaomi 15 Ultra battery charging")

    assert results[0].chunk.title.endswith("电池与充电")


def test_shared_report_title_does_not_override_specific_subsection(knowledge_root: Path):
    path = knowledge_root / "data/brands/oneplus/specs.md"
    path.write_text(
        "# OnePlus 12 & OnePlus 13 技术规格\n\n"
        "## 电池与充电\n\n"
        "### OnePlus 12 电池系统\n\n电池容量 5400mAh，支持无线充电。\n\n"
        "### OnePlus 13 电池系统\n\n电池容量 6000mAh，支持无线充电。\n",
        encoding="utf-8",
    )

    results = KnowledgeBase(knowledge_root).search("一加13 电池")

    assert results
    assert all(result.chunk.title.endswith("OnePlus 13 电池系统") for result in results)


def test_comparison_preserves_both_phone_models(knowledge_root: Path):
    results = KnowledgeBase(knowledge_root).search("小米15 Ultra 和一加13 相机对比", limit=2)

    assert len(results) == 2
    assert any("小米15 Ultra" in result.chunk.title for result in results)
    assert any("OnePlus 13" in result.chunk.title for result in results)
    assert results[0].score >= results[1].score


def test_only_fixed_phone_knowledge_directories_are_loaded(knowledge_root: Path):
    knowledge = KnowledgeBase(knowledge_root)

    assert knowledge.stats == {"documents": 3, "chunks": 7}
    assert knowledge.search("zzzprojectonly") == []
    assert knowledge.search("zzzembeddingonly") == []
    assert knowledge.search("zzzguideonly") == []


@pytest.mark.parametrize("query", ["", "   ", "qwertynonexistentzz", "手机推荐", "小米99 Ultra"])
def test_no_useful_match_returns_empty(knowledge_root: Path, query: str):
    assert KnowledgeBase(knowledge_root).search(query) == []


def test_result_limit_and_score_order(knowledge_root: Path):
    knowledge = KnowledgeBase(knowledge_root)
    results = knowledge.search("影像充电旗舰", limit=2)

    assert len(results) == 2
    assert results[0].score >= results[1].score
    assert knowledge.search("充电", limit=0) == []
    assert knowledge.search("充电", limit=-1) == []


def test_large_sections_are_bounded_and_keep_their_heading(tmp_path: Path):
    path = tmp_path / "docs/by_brand/long.md"
    path.parent.mkdir(parents=True)
    text = "长焦技术" * 1500
    path.write_text(f"# 手机影像\n\n## 长焦\n\n{text}\n", encoding="utf-8")

    knowledge = KnowledgeBase(tmp_path)
    results = knowledge.search("长焦", limit=20)

    assert len(results) == 4
    assert all(len(result.chunk.content) <= MAX_CHUNK_CHARACTERS for result in results)
    assert all(result.chunk.title == "手机影像 / 长焦" for result in results)
    assert sum(len(result.chunk.content) for result in results) == len(text)


def test_markdown_headings_inside_code_blocks_are_content(tmp_path: Path):
    path = tmp_path / "docs/by_category/example.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "# 示例技术\n\n## 正常章节\n\n```python\n# codeheading\n```\n正文内容\n",
        encoding="utf-8",
    )

    results = KnowledgeBase(tmp_path).search("codeheading")

    assert results[0].chunk.title == "示例技术 / 正常章节"
    assert "# codeheading" in results[0].chunk.content


def test_empty_knowledge_directory(tmp_path: Path):
    knowledge = KnowledgeBase(tmp_path)

    assert knowledge.stats == {"documents": 0, "chunks": 0}
    assert knowledge.search("小米") == []


def test_historical_corpus_loads_and_retrieves_real_model():
    knowledge = KnowledgeBase(PROJECT_ROOT)

    assert knowledge.stats["documents"] == 62
    assert knowledge.stats["chunks"] > knowledge.stats["documents"]
    results = knowledge.search("OPPO Find X8 Ultra 双潜望长焦")
    assert results
    assert "Find X8 Ultra" in results[0].chunk.title
    assert all("project_docs" not in result.chunk.source for result in results)


def test_historical_comparison_has_each_models_own_document():
    results = KnowledgeBase(PROJECT_ROOT).search(
        "小米 15 Ultra 和华为 Pura 70 Ultra，拍照各有什么取舍？"
    )

    assert sum("小米15 Ultra" in result.chunk.title and "vs 华为" not in result.chunk.title for result in results) >= 2
    assert any("华为Pura70 Ultra" in result.chunk.title or "华为Pura 70 Ultra" in result.chunk.title for result in results)


def test_historical_budget_query_prefers_advice_over_reference_lists():
    results = KnowledgeBase(PROJECT_ROOT).search(
        "预算 5000 元，偏重拍照和续航，有什么历史机型可以参考？"
    )

    assert len(results) == 6
    assert all(
        not any(label in result.chunk.title.rsplit(" / ", 1)[-1] for label in ("参考文献", "信息来源", "数据来源"))
        for result in results
    )
    assert any("预算" in result.chunk.title or "购买" in result.chunk.title for result in results)
    assert all("网络连接" not in result.chunk.title for result in results)
