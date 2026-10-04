"""Search the project's historical phone documents without an embedding service."""

from collections import Counter
from dataclasses import dataclass
import math
from pathlib import Path
import re
import unicodedata


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAX_CHUNK_CHARACTERS = 1800

KNOWLEDGE_DIRECTORIES = (
    "docs/by_brand",
    "docs/by_category",
    "data/brands",
    "data/processed",
    "docs_archive/brand_docs",
    "docs_archive/components_docs",
    "docs_archive/knowledge_docs",
    "docs_archive/tech_docs",
    "docs_archive/rag_docs/markdown",
)

_BRAND_ALIASES = {
    "xiaomi": "小米",
    "huawei": "华为",
    "honor": "荣耀",
    "oneplus": "一加",
    "apple": "苹果",
    "samsung": "三星",
    "google": "谷歌",
    "sony": "索尼",
    "motorola": "摩托罗拉",
    "meizu": "魅族",
}
_TECHNOLOGY_ALIASES = {
    "camera": "影像",
    "cameras": "影像",
    "photography": "影像",
    "sensor": "传感器",
    "sensors": "传感器",
    "battery": "电池",
    "batteries": "电池",
    "charging": "充电",
    "performance": "性能",
    "screen": "屏幕",
    "display": "屏幕",
}
_GENERIC_TERMS = {
    "手机", "推荐", "什么", "哪个", "哪款", "一下", "怎么", "如何",
    "这个", "帮我", "请问", "介绍", "参数", "配置", "对比", "比较",
    "历史", "参考", "机型", "可以", "有什么", "各有", "偏重",
    "phone", "phones", "smartphone", "smartphones", "the", "a", "an",
    "is", "are", "of", "and", "with", "what", "which", "tell", "me",
}
_CHINESE_FILLER = re.compile("|".join(
    sorted((term for term in _GENERIC_TERMS if re.fullmatch(r"[\u4e00-\u9fff]+", term)), key=len, reverse=True)
))
_MODEL_PATTERN = re.compile(
    r"(?:小米|红米|华为|荣耀|一加|苹果|三星|谷歌|魅族|索尼|摩托罗拉|"
    r"oppo|vivo|iqoo|realme|pura|mate|magic|find|iphone|pixel|galaxy|redmi)"
    r"\s*(?:[a-z]+\s*){0,3}\d+"
    r"(?:\s*(?:ultra|pro|max|plus|mini|s)){0,2}"
)


@dataclass(frozen=True)
class DocumentChunk:
    source: str
    title: str
    content: str


@dataclass(frozen=True)
class SearchResult:
    chunk: DocumentChunk
    score: float


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    for english, chinese in (_BRAND_ALIASES | _TECHNOLOGY_ALIASES).items():
        text = re.sub(rf"\b{english}(?=\b|\d)", chinese, text)
    text = text.replace("真我", "realme")
    for synonym in ("摄像头", "摄影", "拍照", "相机"):
        text = text.replace(synonym, "影像")
    return re.sub(r"(?<=[a-z])(?=\d)|(?<=\d)(?=[a-z])", " ", text)


def _tokens(text: str) -> list[str]:
    normalized = _CHINESE_FILLER.sub(" ", _normalize(text))
    normalized = re.sub(r"[的和与呢吗]", " ", normalized)
    terms = re.findall(r"[a-z]+|\d+(?:\.\d+)?", normalized)
    for word in re.findall(r"[\u4e00-\u9fff]+", normalized):
        terms.extend(word[index:index + 2] for index in range(len(word) - 1))
    return [term for term in terms if term not in _GENERIC_TERMS]


def _compact(text: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]", "", _normalize(text))


def _model_context(title: str) -> set[str]:
    """A specific subsection supersedes model names in a shared report title."""
    for heading in reversed(title.split(" / ")):
        if _normalize(heading).startswith("vs "):
            continue
        models = {_compact(match.group()) for match in _MODEL_PATTERN.finditer(_normalize(heading))}
        if models:
            return models
    return set()


def _same_model(first: str, second: str) -> bool:
    # A subsection can omit the brand, such as "Pura 70 Ultra".
    return first == second or first.endswith(second) or second.endswith(first)


def _bounded_parts(content: str) -> list[str]:
    """Keep paragraph boundaries when possible and cap every chunk's length."""
    parts = []
    current = ""
    for paragraph in re.split(r"\n\s*\n", content.strip()):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if current and len(current) + len(paragraph) + 2 > MAX_CHUNK_CHARACTERS:
            parts.append(current)
            current = ""
        while len(paragraph) > MAX_CHUNK_CHARACTERS:
            parts.append(paragraph[:MAX_CHUNK_CHARACTERS])
            paragraph = paragraph[MAX_CHUNK_CHARACTERS:]
        if paragraph:
            current = f"{current}\n\n{paragraph}" if current else paragraph
    if current:
        parts.append(current)
    return parts


def _document_chunks(source: str, text: str) -> list[DocumentChunk]:
    headings: list[tuple[int, str]] = []
    content: list[str] = []
    chunks = []
    fence = ""

    def flush() -> None:
        title = " / ".join(heading for _, heading in headings) or Path(source).stem
        for part in _bounded_parts("\n".join(content)):
            chunks.append(DocumentChunk(source=source, title=title, content=part))
        content.clear()

    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(("```", "~~~")):
            marker = stripped[:3]
            if not fence:
                fence = marker
            elif marker == fence:
                fence = ""
            content.append(line)
            continue
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line) if not fence else None
        if heading:
            flush()
            level = len(heading.group(1))
            while headings and headings[-1][0] >= level:
                headings.pop()
            headings.append((level, heading.group(2)))
        else:
            content.append(line)
    flush()
    return chunks


class KnowledgeBase:
    def __init__(self, root: Path = PROJECT_ROOT):
        self.root = Path(root)
        documents = sorted(
            path
            for directory in KNOWLEDGE_DIRECTORIES
            for path in (self.root / directory).rglob("*.md")
        )
        self._document_count = len(documents)
        self._chunks = [
            chunk
            for path in documents
            for chunk in _document_chunks(
                path.relative_to(self.root).as_posix(), path.read_text(encoding="utf-8")
            )
        ]
        self._body_terms = [Counter(_tokens(chunk.content)) for chunk in self._chunks]
        self._title_terms = [set(_tokens(chunk.title)) for chunk in self._chunks]
        self._section_terms = [
            set(_tokens(chunk.title.rsplit(" / ", 1)[-1])) for chunk in self._chunks
        ]
        frequencies = Counter(
            term
            for body, title in zip(self._body_terms, self._title_terms)
            for term in set(body) | title
        )
        count = len(self._chunks)
        self._idf = {
            term: math.log(1 + (count - frequency + 0.5) / (frequency + 0.5))
            for term, frequency in frequencies.items()
        }
        self._average_length = (
            sum(max(1, sum(terms.values())) for terms in self._body_terms) / count if count else 1
        )
        self._compact_bodies = [_compact(chunk.content) for chunk in self._chunks]
        self._model_contexts = [_model_context(chunk.title) for chunk in self._chunks]

    @property
    def stats(self) -> dict[str, int]:
        return {"documents": self._document_count, "chunks": len(self._chunks)}

    def search(self, query: str, limit: int = 6) -> list[SearchResult]:
        if limit <= 0:
            return []
        query_terms = set(_tokens(query)) & self._idf.keys()
        if not query_terms:
            return []
        model_matches = list(_MODEL_PATTERN.finditer(_normalize(query)))
        models = list(dict.fromkeys(_compact(match.group()) for match in model_matches))
        model_terms = set(_tokens(" ".join(match.group() for match in model_matches)))
        has_topic = bool(query_terms - model_terms)
        query_weight = sum(self._idf[term] for term in query_terms)
        results = []
        ownership = {}
        for index, chunk in enumerate(self._chunks):
            body, title = self._body_terms[index], self._title_terms[index]
            matches = query_terms & (body.keys() | title)
            if not matches:
                continue
            context = self._model_contexts[index]
            owned_models = {
                model for model in models if any(_same_model(model, owner) for owner in context)
            }
            title_models = len(owned_models)
            body_models = sum(model in self._compact_bodies[index] for model in models)
            if models and context and not title_models:
                continue
            if models and not (title_models or body_models):
                continue
            length = sum(body.values())
            score = sum(
                self._idf[term] * (0.5 if has_topic and term in model_terms else 1) * (
                    body[term] / (body[term] + 0.8 + 0.6 * length / self._average_length)
                    + (0.5 if term in title else 0)
                    + (
                        2.5
                        if term in self._section_terms[index]
                        and (not has_topic or term not in model_terms)
                        else 0
                    )
                )
                for term in matches
            )
            coverage = sum(self._idf[term] for term in matches) / query_weight
            score *= 0.5 + 0.5 * coverage
            score += title_models * 6 + max(0, body_models - title_models) * 3
            section = chunk.title.rsplit(" / ", 1)[-1]
            if re.search(r"参考(?:文献|资料|来源)|(?:数据|信息|资料)来源|sources|references", section):
                score *= 0.15
            results.append(SearchResult(chunk=chunk, score=score))
            ownership[chunk] = owned_models
        results.sort(key=lambda result: result.score, reverse=True)
        if len(models) < 2:
            return results[:limit]
        selected = []
        per_model = min(2, max(1, limit // len(models)))
        for model in models:
            candidates = [result for result in results if model in ownership[result.chunk]]
            for candidate in candidates[:per_model]:
                if candidate not in selected:
                    selected.append(candidate)
                if len(selected) == limit:
                    break
            if len(selected) == limit:
                break
        for result in results:
            if len(selected) == limit:
                break
            if result not in selected:
                selected.append(result)
        selected.sort(key=lambda result: result.score, reverse=True)
        return selected
