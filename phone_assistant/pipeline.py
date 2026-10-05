"""可恢复的 ZOL 同步：只发布经过页面校验的详情，保留失败队列。"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path

import httpx
from filelock import FileLock, Timeout

from .config import PROJECT_ROOT
from .images import IMAGE_FIELDS, preferred_image
from .crawler import (
    LIST_URL, PageValidationError, ZolCrawler, cached_metadata, parse_listing, parse_parameters,
    parse_product, parse_series, parse_series_parameters, parse_discovery, parse_brand_directory, utc_now,
)

NEW_METADATA = ("new_from_source", "new_release_catalog_url", "current_source", "source_position", "catalog_fetched_at", "discovered_at")


def _has_price(raw: dict) -> bool:
    from .cleaning import clean_phone
    return clean_phone(raw)["price"] is not None


def repair_catalog_prices(storage=None, *, data_dir: Path | None = None) -> int:
    """仅追加已采同SKU确定报价，保留原报价来源/时间，不请求页面。"""
    directory = Path(data_dir) if data_dir is not None else PROJECT_ROOT / "data"
    with FileLock(directory / "reports" / "sync.lock", timeout=0):
        report = json.loads((directory / "reports" / "latest_sync.json").read_text(encoding="utf-8"))
        run_dir = Path(report["run_dir"])
        checkpoint = json.loads((run_dir / "checkpoint.json").read_text(encoding="utf-8"))
        if storage is None:
            from .storage import Storage
            storage = Storage()
        changed = 0
        for identifier, raw in checkpoint["completed_records"].items():
            candidate = checkpoint["catalog"][identifier]
            if not _has_price(raw) and _has_price(candidate):
                raw.update({key: candidate.get(key) for key in ("price", "price_source_url", "price_fetched_at")})
                storage.upsert_raw(raw)
                with (run_dir / "phones.jsonl").open("a", encoding="utf-8") as output:
                    output.write(json.dumps(raw, ensure_ascii=False) + "\n")
                changed += 1
        report["catalog_prices_repaired"] = report.get("catalog_prices_repaired", 0) + changed
        _save(run_dir / "checkpoint.json", checkpoint)
        _save(run_dir / "report.json", report)
        _save(directory / "reports" / "latest_sync.json", report)
        return changed


def _collect_official(storage, progress, cache_dir):
    from .official_sources import sync_official
    result = sync_official(storage=None, progress=progress, cache_dir=cache_dir)
    result["records_discovered"] = len(result["raws"])
    result["pending"] = sum(info["pending"] for info in result["coverage"].values())
    if result["raws"]:
        imported = storage.import_many(result["raws"])
        result["imported"] = imported["imported"]
    return result


def merge_official_report(report_path: Path, *, data_dir: Path | None = None, import_records: bool = False, storage=None) -> dict:
    """离线合入真实官方采集；默认报告中的原始记录已发布，不重复采集或写库。"""
    directory = Path(data_dir) if data_dir is not None else PROJECT_ROOT / "data"
    latest = directory / "reports" / "latest_sync.json"
    with FileLock(directory / "reports" / "sync.lock", timeout=0):
        result = json.loads(latest.read_text(encoding="utf-8"))
        run_dir = Path(result["run_dir"])
        checkpoint = json.loads((run_dir / "checkpoint.json").read_text(encoding="utf-8"))
        official = json.loads(Path(report_path).read_text(encoding="utf-8"))
        raws = official.pop("raws")
        official["records_discovered"] = len(raws)
        official["pending"] = sum(info["pending"] for info in official["coverage"].values())
        if import_records:
            if storage is None:
                from .storage import Storage
                storage = Storage()
            official["imported"] = storage.import_many(raws)["imported"]
        previous = checkpoint.get("official", {})
        result["discovered"] += official["records_discovered"] - previous.get("records_discovered", 0)
        for key in ("completed", "imported"):
            result[key] += official["imported"] - previous.get("imported", 0)
        checkpoint["official"] = official
        checkpoint["official_done"] = True
        checkpoint["official_report_path"] = str(Path(report_path).resolve())
        official_errors = [{"stage": "official", **error} for error in official.get("errors", [])]
        result.update({"official_models_discovered": official.get("models_discovered", official["discovered"]),
            "official_discovered": official["discovered"], "official_records_discovered": len(raws),
            "official_imported": official["imported"], "official_pending": official["pending"],
            "official_coverage": official["coverage"],
            "errors": checkpoint["errors"] + official_errors,
            "unresolved_errors": checkpoint["errors"] + official_errors,
            "failed": len(checkpoint["errors"]) + len(official_errors)})
        result["variants_discovered"] = len(set(checkpoint["catalog"]) - set(checkpoint["listed_ids"]) - set(checkpoint.get("new_ids", [])))
        from .cleaning import clean_phone
        zol_families = {}
        for raw in checkpoint["completed_records"].values():
            if raw.get("new_from_source"):
                phone = clean_phone(raw)
                zol_families.setdefault(phone["brand"], set()).add(phone["family_key"])
        official_families = {}
        for raw in raws:
            phone = clean_phone(raw)
            official_families.setdefault(phone["brand"], set()).add(phone["family_key"])
        result["cross_source_gaps"] = {brand: {
            "official_families": sorted(families),
            "official_families_not_in_zol_batch": sorted(families - zol_families.get(brand, set())),
            "zol_families_not_in_official_batch": sorted(zol_families.get(brand, set()) - families),
            "scope": "仅比较本批实际采集目录；缺失不代表另一来源或市场不存在该机型",
        } for brand, families in official_families.items()}
        if official["pending"] or official_errors or result["failed"]:
            result["status"] = "partial"
        _save(run_dir / "checkpoint.json", checkpoint)
        _save(run_dir / "report.json", result)
        _save(latest, result)
        _save(directory / "reports" / "latest_official.json", official)
        return result


def _save(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _series_discrepancies(series: dict) -> list[dict]:
    groups = {}
    for url, info in series.items():
        match = re.search(r"(?:/series/57/|/param_)(\d+)_", url)
        identifier = match.group(1) if match else url
        group = groups.setdefault(identifier, {"urls": [], "ids": set(), "totals": set()})
        group["urls"].append(url)
        group["ids"].update(info["ids"])
        if info["advertised_members"] is not None:
            group["totals"].add(info["advertised_members"])
    return [
        {"url": info["urls"][0], "page_urls": info["urls"],
         "visible_members": len(info["ids"]), "advertised_members": sorted(info["totals"])}
        for info in groups.values()
        if info["totals"] and (len(info["totals"]) > 1 or len(info["ids"]) != next(iter(info["totals"])))
    ]


def _resolve_alternative_layouts(checkpoint: dict) -> None:
    def page_key(url):
        return re.sub(r"(_\d+)_([12])(_0_\d+\.html$)", r"\1_layout\3", url)

    covered = {page_key(url) for url in checkpoint["list_pages"]}
    unresolved = []
    for error in checkpoint["errors"]:
        if error["stage"] == "list" and page_key(error["url"]) in covered:
            checkpoint["resolved_errors"].append({
                **error, "resolution": "同筛选和页码的另一正常公开布局已采集；整体数量仍单独核对",
            })
        else:
            unresolved.append(error)
    checkpoint["errors"] = unresolved


def _correct_provenance(raw: dict, metadata) -> dict:
    corrected = dict(raw)
    specs_url = raw.get("specs_source_url") or raw.get("param_url")
    corrected["fetched_at"] = raw["specs_fetched_at"] if "specs_fetched_at" in raw else (
        metadata(specs_url).get("fetched_at") if specs_url else None
    )
    corrected["specs_fetched_at"] = corrected["fetched_at"]
    price_url = raw.get("price_source_url")
    corrected["price_fetched_at"] = raw["price_fetched_at"] if "price_fetched_at" in raw else (
        metadata(price_url).get("fetched_at") if price_url else None
    )
    if raw.get("price") and "停产" in str(raw["price"]):
        corrected["availability"] = "historical"
    return corrected


def repair_cached_provenance(storage=None, *, data_dir: Path | None = None) -> dict:
    """只读已保存HTML/元数据，追加纠正快照并重发布；本函数不请求源站。"""
    directory = Path(data_dir) if data_dir is not None else PROJECT_ROOT / "data"
    reports = directory / "reports"
    lock = FileLock(reports / "sync.lock", timeout=0)
    try:
        with lock:
            latest = reports / "latest_sync.json"
            report = json.loads(latest.read_text(encoding="utf-8"))
            run_dir = Path(report["run_dir"])
            checkpoint = json.loads((run_dir / "checkpoint.json").read_text(encoding="utf-8"))
            html_dir = run_dir / "html"

            def metadata(url):
                return cached_metadata(html_dir, url)

            def html(url):
                key = hashlib.sha256(url.encode()).hexdigest()[:20]
                return (html_dir / f"{key}.html").read_text(encoding="utf-8")

            stopped = set()
            for url in checkpoint["list_pages"]:
                stopped.update(raw["id"] for raw in parse_listing(html(url), url).phones if raw["availability"] == "historical")
            for url in checkpoint["series"]:
                parser = parse_series_parameters if "/param_" in url else parse_series
                stopped.update(raw["id"] for raw in parser(html(url), url).phones if raw["availability"] == "historical")
            if storage is None:
                from .storage import Storage
                storage = Storage()
            repaired = 0
            for identifier, raw in checkpoint["completed_records"].items():
                corrected = _correct_provenance(raw, metadata)
                specs_url = raw.get("specs_source_url") or raw.get("param_url")
                if specs_url and metadata(specs_url):
                    if "/param_" in specs_url:
                        corrected["specs"] = next(phone["specs"] for phone in parse_series_parameters(html(specs_url), specs_url).phones if phone["id"] == identifier)
                    else:
                        corrected["specs"] = parse_parameters(html(specs_url), specs_url)["specs"]
                if identifier in stopped:
                    corrected["availability"] = "historical"
                if corrected != raw:
                    corrected["_corrects_fetched_at"] = raw.get("fetched_at")
                    storage.upsert_raw(corrected)
                    checkpoint["completed_records"][identifier] = corrected
                    with (run_dir / "phones.jsonl").open("a", encoding="utf-8") as output:
                        output.write(json.dumps(corrected, ensure_ascii=False) + "\n")
                    repaired += 1
            for identifier, raw in checkpoint["catalog"].items():
                raw["price_fetched_at"] = metadata(raw["price_source_url"]).get("fetched_at") if raw.get("price_source_url") else None
                if identifier in stopped or raw.get("price") and "停产" in str(raw["price"]):
                    raw["availability"] = "historical"
            discrepancies = _series_discrepancies(checkpoint["series"])
            _resolve_alternative_layouts(checkpoint)
            report["failed"] = len(checkpoint["errors"])
            report["errors"] = checkpoint["errors"]
            report["unresolved_errors"] = checkpoint["errors"]
            report["warnings"] = checkpoint["resolved_errors"]
            report["series_count_discrepancies"] = discrepancies
            if discrepancies:
                report["status"] = "partial"
            report["provenance_repaired"] = report.get("provenance_repaired", 0) + repaired
            report["provenance_repaired_at"] = utc_now()
            report["missing_response_metadata"] = sum(raw["fetched_at"] is None for raw in checkpoint["completed_records"].values())
            _save(run_dir / "checkpoint.json", checkpoint)
            _save(run_dir / "report.json", report)
            _save(latest, report)
            return report
    except Timeout as exc:
        raise RuntimeError("已有手机数据同步任务运行中，不能同时纠正缓存来源。") from exc


def run_sync(
    storage=None, progress=None, *, resume: bool = True, force: bool = False,
    delay: float = 0.9, limit: int | None = None, list_url: str = LIST_URL,
    data_dir: Path | None = None, seed_urls: list[str] | None = None, variants_only: bool = False,
    latest_only: bool = False, include_official: bool = True,
) -> dict:
    """刷新完整公开列表和同系列版本；force 创建新批次，resume 接续未完成批次。"""
    directory = Path(data_dir) if data_dir is not None else PROJECT_ROOT / "data"
    (directory / "reports").mkdir(parents=True, exist_ok=True)
    lock = FileLock(directory / "reports" / "sync.lock", timeout=0)
    try:
        with lock:
            return _run_sync(
                storage, progress, resume=resume, force=force, delay=delay,
                limit=limit, list_url=list_url, data_dir=directory, seed_urls=seed_urls,
                variants_only=variants_only,
                latest_only=latest_only, include_official=include_official,
            )
    except Timeout as exc:
        raise RuntimeError("已有手机数据同步任务运行中，请查看其进度后再试。") from exc


def _run_sync(
    storage=None, progress=None, *, resume: bool = True, force: bool = False,
    delay: float = 0.9, limit: int | None = None, list_url: str = LIST_URL,
    data_dir: Path | None = None, seed_urls: list[str] | None = None, variants_only: bool = False,
    latest_only: bool = False, include_official: bool = True,
) -> dict:
    data_dir = Path(data_dir) if data_dir is not None else PROJECT_ROOT / "data"
    reports_dir = data_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    latest = reports_dir / "latest_sync.json"
    previous = json.loads(latest.read_text(encoding="utf-8")) if latest.exists() else None
    if variants_only and (not previous or force):
        raise ValueError("仅补系列版本需要已有同步批次，不能与force同时使用")
    checkpoint = None
    if resume and not force and previous and (previous.get("status") != "complete" or variants_only):
        candidate = Path(previous["run_dir"]) / "checkpoint.json"
        if candidate.exists():
            checkpoint = json.loads(candidate.read_text(encoding="utf-8"))
    if checkpoint is None:
        started = utc_now()
        run_id = started.replace(":", "").replace(".", "").replace("+", "-")
        run_dir = data_dir / "raw" / f"zol-sync-{run_id}"
        checkpoint = {
            "run_id": run_id, "started_at": started, "run_dir": str(run_dir.resolve()),
            "list_url": list_url, "list_pages": {}, "catalog": {}, "listed_ids": [],
            "index_done": [], "series_done": [], "covered_ids": [], "series": {},
            "completed_records": {}, "published_ids": [], "errors": [],
        }
    else:
        checkpoint["list_url"] = list_url
    checkpoint.setdefault("resolved_errors", [])
    checkpoint.setdefault("failure_history", list(checkpoint["errors"]))
    checkpoint.setdefault("brand_pages", {})
    checkpoint.setdefault("brand_coverage", {})
    checkpoint.setdefault("new_ids", [])
    checkpoint.setdefault("discovery_pages", {})
    checkpoint.setdefault("official", {})
    run_dir = Path(checkpoint["run_dir"])
    run_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = run_dir / "checkpoint.json"
    crawler = ZolCrawler(run_dir / "html", delay=delay)
    catalog = checkpoint["catalog"]
    listed_ids = set(checkpoint["listed_ids"])
    completed = checkpoint["completed_records"]
    if storage is None:
        from .storage import Storage
        storage = Storage()
    for identifier, raw in list(completed.items()):
        corrected = _correct_provenance(raw, crawler.metadata)
        if corrected != raw:
            corrected["_corrects_fetched_at"] = raw.get("fetched_at")
            completed[identifier] = corrected
            if identifier in checkpoint["published_ids"]:
                checkpoint["published_ids"].remove(identifier)

    def report(status: str = "running", message: str = "") -> dict:
        totals = [page["total"] for page in checkpoint["list_pages"].values() if page["total"] is not None]
        official = checkpoint["official"]
        official_errors = [{"stage": "official", **error} for error in official.get("errors", [])]
        coverage = {}
        for brand, info in checkpoint["brand_coverage"].items():
            ids = info["new_ids"]
            coverage[brand] = {**info, "new_discovered": len(ids), "new_completed": len(set(ids) & set(completed)),
                "unresolved_ids": sorted(set(ids) - set(completed)),
                "coverage_scope": "源站明确新品模块可见条目及其系列版本；不代表品牌全部已上市手机"}
        return {
            "status": status, "run_id": checkpoint["run_id"],
            "started_at": checkpoint["started_at"], "finished_at": utc_now() if status != "running" else None,
            "run_dir": checkpoint["run_dir"], "list_url": list_url,
            "listed_total": totals[0] if totals else None,
            "list_pages_completed": len(checkpoint["list_pages"]),
            "listed_discovered": len(listed_ids), "variants_discovered": len(set(catalog) - listed_ids - set(checkpoint["new_ids"])),
            "discovered": len(catalog) + official.get("records_discovered", 0), "completed": len(completed) + official.get("imported", 0),
            "failed": len(checkpoint["errors"]) + len(official_errors), "errors": checkpoint["errors"] + official_errors,
            "unresolved_errors": checkpoint["errors"] + official_errors,
            "failed_attempts": len(checkpoint["failure_history"]),
            "warnings": checkpoint["resolved_errors"],
            "series": checkpoint["series"], "requests": crawler.requests,
            "cache_hits": crawler.cache_hits, "imported": len(checkpoint["published_ids"]) + official.get("imported", 0),
            "series_comparison_pages": sum(info.get("layout") == "comparison" for info in checkpoint["series"].values()),
            "variants_only": variants_only,
            "latest_only": latest_only, "brand_coverage": coverage, "official_coverage": official.get("coverage", {}),
            "official_discovered": official.get("discovered", 0), "official_imported": official.get("imported", 0),
            "official_models_discovered": official.get("discovered", 0), "official_records_discovered": official.get("records_discovered", 0),
            "official_pending": official.get("pending", 0),
            "new_from_source_discovered": len(checkpoint["new_ids"]),
            "new_from_source_completed": len(set(checkpoint["new_ids"]) & set(completed)),
            "message": message, "scope": "官方公开目录及ZOL独立新品模块；全量列表范围与新品来源覆盖分别核对，库存未知不等于确认在售",
        }

    def emit(stage: str, message: str) -> None:
        checkpoint["listed_ids"] = sorted(listed_ids)
        _save(checkpoint_path, checkpoint)
        snapshot = report(message=message)
        _save(latest, snapshot)
        if progress:
            progress({**snapshot, "stage": stage})

    def fail(stage: str, url: str, exc: Exception, identifier: str | None = None) -> None:
        checkpoint["errors"] = [error for error in checkpoint["errors"] if (error["stage"], error["url"]) != (stage, url)]
        error = {
            "stage": stage, "url": url, "id": identifier, "reason": str(exc),
            "error_type": type(exc).__name__, "at": utc_now(),
        }
        checkpoint["errors"].append(error)
        checkpoint["failure_history"].append(error)
        emit(stage, f"失败，已保留队列：{url} — {exc}")

    def clear_error(stage: str, url: str) -> None:
        checkpoint["resolved_errors"].extend(
            {**error, "resolution": "后续请求/发布成功"} for error in checkpoint["errors"]
            if error["stage"] == stage and error["url"] == url
        )
        checkpoint["errors"] = [error for error in checkpoint["errors"] if (error["stage"], error["url"]) != (stage, url)]

    def fetch(url: str, stage: str) -> str:
        retry = not variants_only and any(error["stage"] == stage and error["url"] == url for error in checkpoint["errors"])
        return crawler.fetch(url, refresh=retry)

    def response_time(url: str | None) -> str | None:
        return crawler.metadata(url).get("fetched_at") if url else None

    def merge(raw: dict) -> None:
        identifier = raw["id"]
        if identifier not in catalog:
            catalog[identifier] = raw
            return
        existing = catalog[identifier]
        image = preferred_image(existing, raw)
        if raw.get("price") is not None and existing.get("price") is None:
            for key in ("price", "price_source_url", "price_fetched_at"):
                existing[key] = raw.get(key)
        for key, value in raw.items():
            if key in IMAGE_FIELDS:
                continue
            if key == "specs":
                existing[key] = {**existing.get(key, {}), **value}
            elif value is not None and key not in {"availability", "price", "price_source_url", "price_fetched_at"}:
                existing[key] = value
            elif key == "availability":
                if value == "historical" or existing.get("availability") != "historical" and value == "listed":
                    existing[key] = value
        for key in IMAGE_FIELDS:
            existing.pop(key, None)
        existing.update(image)
        if existing.get("price") and "停产" in str(existing["price"]):
            existing["availability"] = "historical"

    def collect_series(first_url: str, context: dict | None = None) -> None:
        queue = [first_url]
        seen = set()
        while queue:
            url = queue.pop(0)
            if url in seen:
                continue
            seen.add(url)
            if url in checkpoint["series_done"]:
                queue.extend(checkpoint["series"].get(url, {}).get("page_urls", []))
                continue
            try:
                parser = parse_series_parameters if "/param_" in url else parse_series
                page = parser(fetch(url, "series"), url)
            except (httpx.HTTPError, PageValidationError) as exc:
                fail("series", url, exc)
                continue
            for raw in page.phones:
                if context and context.get("new_from_source"):
                    raw.update({key: context.get(key) for key in NEW_METADATA if key != "source_position"})
                    raw["source_position"] = context.get("source_position") if raw["id"] == context["id"] else None
                    raw["discovery_basis"] = "series_variant"
                    raw["derived_from_id"] = context["id"]
                raw["price_fetched_at"] = response_time(url)
                raw["image_fetched_at"] = response_time(url)
                merge(raw)
                if page.layout == "comparison" and raw["id"] not in completed:
                    record = {**raw, **{key: catalog[raw["id"]].get(key) for key in NEW_METADATA}, "fetched_at": response_time(url), "specs_fetched_at": response_time(url)}
                    if not _has_price(record) and _has_price(catalog[raw["id"]]):
                        record.update({key: catalog[raw["id"]].get(key) for key in ("price", "price_source_url", "price_fetched_at")})
                    completed[raw["id"]] = record
                    with (run_dir / "phones.jsonl").open("a", encoding="utf-8") as output:
                        output.write(json.dumps(record, ensure_ascii=False) + "\n")
            checkpoint["covered_ids"] = sorted(set(checkpoint["covered_ids"]) | {raw["id"] for raw in page.phones})
            checkpoint["series_done"].append(url)
            checkpoint["series"][url] = {
                "visible_members": len(page.phones), "advertised_members": page.total,
                "ids": [raw["id"] for raw in page.phones], "page_urls": page.page_urls + page.variant_urls,
                "layout": page.layout,
            }
            queue.extend(page.page_urls + page.variant_urls)
            clear_error("series", url)
            emit("series", f"系列页已解析 {len(page.phones)} 个版本：{url}")

    def discover_page(url: str, brand: str | None = None) -> dict:
        page = parse_discovery(fetch(url, "discovery"), url)
        ids = []
        for raw in page.phones:
            raw["brand"] = raw.get("brand") or brand
            raw["catalog_fetched_at"] = response_time(url)
            raw["discovered_at"] = response_time(url)
            raw["price_fetched_at"] = response_time(url)
            raw["image_fetched_at"] = response_time(url)
            merge(raw)
            ids.append(raw["id"])
        checkpoint["new_ids"] = sorted(set(checkpoint["new_ids"]) | set(ids))
        checkpoint["discovery_pages"][url] = {"ids": ids, "main_count": page.main_count, "module_found": page.module_found}
        if brand:
            checkpoint["brand_coverage"][brand] = {"source_url": url, "new_release_catalog_url": url,
                "catalog_fetched_at": response_time(url), "main_discovered": page.main_count,
                "module_found": page.module_found, "new_ids": ids}
        emit("discovery", f"{brand or '手机'}独立新品模块发现 {len(ids)} 条；热门主列表 {page.main_count} 条另计")
        return {"brands": page.brands, "directory_url": page.directory_url}

    def publish_completed() -> None:
        published = set(checkpoint["published_ids"])
        for identifier, raw in completed.items():
            metadata = {key: catalog[identifier].get(key) for key in NEW_METADATA if catalog[identifier].get(key) is not None}
            changed = any(raw.get(key) != value for key, value in metadata.items())
            raw.update(metadata)
            if not _has_price(raw) and _has_price(catalog[identifier]):
                raw.update({key: catalog[identifier].get(key) for key in ("price", "price_source_url", "price_fetched_at")})
                changed = True
            if catalog[identifier].get("availability") == "historical" and raw.get("availability") != "historical":
                raw["availability"] = "historical"
                changed = True
            if identifier in published and not changed:
                continue
            try:
                storage.upsert_raw(raw)
            except (ValueError, RuntimeError, sqlite3.Error) as exc:
                fail("publish", raw["source_url"], exc, identifier)
                continue
            if identifier not in published:
                published.add(identifier)
                checkpoint["published_ids"].append(identifier)
            clear_error("publish", raw["source_url"])
            emit("publish", f"已清洗并发布：{raw['name']}")

    try:
        if include_official and not variants_only and not checkpoint.get("official_done"):
            checkpoint["official"] = _collect_official(storage, lambda value: emit("official", value.get("message", "采集官方新品目录")), run_dir / "official")
            checkpoint["official"].pop("raws", None)
            checkpoint["official_done"] = True
            emit("official", "官方目录已采集并发布；各品牌来源覆盖独立保留")
        if not variants_only:
            try:
                found = discover_page(list_url)
                checkpoint["brand_pages"].update(found["brands"])
                if found["directory_url"]:
                    checkpoint["brand_pages"].update(parse_brand_directory(fetch(found["directory_url"], "discovery"), found["directory_url"]))
            except (httpx.HTTPError, PageValidationError) as exc:
                fail("discovery", list_url, exc)
            priority = {brand: index for index, brand in enumerate(["vivo", "华为", "荣耀", "OPPO", "苹果"])}
            for brand, url in sorted(checkpoint["brand_pages"].items(), key=lambda item: (priority.get(item[0], 5), item[0])):
                try:
                    discover_page(url, brand)
                    clear_error("discovery", url)
                except (httpx.HTTPError, PageValidationError) as exc:
                    checkpoint["brand_coverage"][brand] = {"source_url": url, "new_release_catalog_url": url,
                        "catalog_fetched_at": response_time(url), "main_discovered": 0, "module_found": False, "new_ids": []}
                    fail("discovery", url, exc)
        emit("list", "开始/恢复完整公开列表同步")
        page_queue = [] if variants_only or latest_only else [list_url, *(seed_urls or [])]
        visited = set()
        while page_queue:
            url = page_queue.pop(0)
            if url in visited:
                continue
            visited.add(url)
            if url in checkpoint["list_pages"]:
                saved_page = checkpoint["list_pages"][url]
                try:
                    parsed_saved = parse_listing(crawler.fetch(url), url)
                    saved_page["sort_urls"] = parsed_saved.sort_urls
                    saved_page["page_urls"] = parsed_saved.page_urls
                except (httpx.HTTPError, PageValidationError) as exc:
                    fail("list", url, exc)
                    continue
                page_queue.extend(saved_page["page_urls"] + saved_page["sort_urls"])
                continue
            try:
                page = parse_listing(fetch(url, "list"), url)
                signature = sorted({raw["id"] for raw in page.phones})
                page_number = re.search(r"_(\d+)\.html$", url).group(1)
                if any(
                    signature == item["ids"] and re.search(r"_(\d+)\.html$", old_url).group(1) != page_number
                    for old_url, item in checkpoint["list_pages"].items()
                ):
                    raise PageValidationError("分页返回与已采页面完全相同的产品集合")
            except (httpx.HTTPError, PageValidationError) as exc:
                fail("list", url, exc)
                continue
            for raw in page.phones:
                raw["price_fetched_at"] = response_time(url)
                merge(raw)
                listed_ids.add(raw["id"])
            checkpoint["list_pages"][url] = {
                "ids": signature, "count": len(page.phones), "total": page.total,
                "layout": page.layout, "page_urls": page.page_urls,
                "sort_urls": page.sort_urls,
            }
            page_queue.extend(page.page_urls + page.sort_urls)
            clear_error("list", url)
            emit("list", f"已解析列表页 {len(page.phones)} 条：{url}")

        for error in list(checkpoint["errors"]):
            if error["stage"] == "series" and not variants_only:
                collect_series(error["url"])

        for discrepancy in _series_discrepancies(checkpoint["series"]):
            url = discrepancy["url"]
            if "/param_" in url:
                continue
            page = parse_series(crawler.fetch(url), url)
            checkpoint["series"][url]["page_urls"] = page.page_urls + page.variant_urls
            for variant_url in page.variant_urls:
                collect_series(variant_url)

        brand_priority = {brand: index for index, brand in enumerate(["vivo", "华为", "荣耀", "OPPO", "苹果"])}
        base_ids = [] if variants_only else sorted(set(checkpoint["new_ids"]) | listed_ids, key=lambda identifier: (
            0 if catalog[identifier].get("new_from_source") else 1,
            brand_priority.get(catalog[identifier].get("brand"), 5),
            catalog[identifier].get("source_position") or 99, identifier,
        ))
        if limit is not None:
            base_ids = base_ids[:limit]
        for identifier in base_ids:
            raw = catalog[identifier]
            if identifier in completed and latest_only:
                continue
            if identifier in checkpoint["index_done"] or identifier in checkpoint["covered_ids"] and raw.get("param_url"):
                continue
            url = raw["source_url"]
            try:
                product = parse_product(fetch(url, "index"), url)
            except (httpx.HTTPError, PageValidationError) as exc:
                fail("index", url, exc, identifier)
                continue
            if product["param_url"]:
                raw["param_url"] = product["param_url"]
            if product.get("image_url"):
                raw.update(preferred_image(raw, {**product, "image_fetched_at": response_time(url)}))
            if product["price"] is not None:
                raw["price"] = product["price"]
                raw["price_source_url"] = url
                raw["price_fetched_at"] = response_time(url)
                if "停产" in str(product["price"]):
                    raw["availability"] = "historical"
            checkpoint["index_done"].append(identifier)
            clear_error("index", url)
            if product["series_url"]:
                collect_series(product["series_url"], raw)
                publish_completed()
            emit("index", f"产品首页完成：{raw['name']}")

        detail_ids = sorted(catalog)
        if limit is not None:
            detail_ids = base_ids
        for identifier in detail_ids:
            if identifier in completed:
                # 系列表只覆盖参数时，仍读取这个 SKU 自己的公开参考价。
                # 补报价不改变已采参数、上市信息及它们的核验时间。
                if not _has_price(completed[identifier]) and identifier not in checkpoint["index_done"]:
                    raw = catalog[identifier]
                    url = raw["source_url"]
                    try:
                        product = parse_product(fetch(url, "quote"), url)
                    except (httpx.HTTPError, PageValidationError) as exc:
                        fail("quote", url, exc, identifier)
                        continue
                    checkpoint["index_done"].append(identifier)
                    clear_error("quote", url)
                    clear_error("index", url)
                    if product["price"] is not None:
                        raw.update(price=product["price"], price_source_url=url,
                                   price_fetched_at=response_time(url))
                        if "停产" in str(product["price"]):
                            raw["availability"] = "historical"
                        emit("quote", f"已读取独立配置报价：{raw['name']}")
                continue
            raw = catalog[identifier]
            url = raw.get("param_url")
            if not url:
                try:
                    product = parse_product(fetch(raw["source_url"], "index"), raw["source_url"])
                except (httpx.HTTPError, PageValidationError) as exc:
                    fail("index", raw["source_url"], exc, identifier)
                    continue
                url = product["param_url"]
                if product.get("image_url"):
                    raw.update(preferred_image(raw, {**product, "image_fetched_at": response_time(raw["source_url"])}))
                if url:
                    raw["param_url"] = url
                    clear_error("index", raw["source_url"])
                if product["price"] is not None:
                    raw["price"] = product["price"]
                    raw["price_source_url"] = raw["source_url"]
                    raw["price_fetched_at"] = response_time(raw["source_url"])
                    if "停产" in str(product["price"]):
                        raw["availability"] = "historical"
            if not url:
                fail("detail", raw["source_url"], PageValidationError("未发现真实参数链接，不构造猜测URL"), identifier)
                continue
            try:
                details = parse_parameters(fetch(url, "detail"), url)
            except (httpx.HTTPError, PageValidationError) as exc:
                fail("detail", url, exc, identifier)
                continue
            record = {
                **raw, "specs": details["specs"],
                **preferred_image(raw, {**details, "image_fetched_at": response_time(url)}),
                "brand": details["brand"] or raw.get("brand"),
                "name": details["name"] or raw["name"],
                "specs_source_url": url, "fetched_at": response_time(url),
                "specs_fetched_at": response_time(url),
                "price_fetched_at": response_time(raw.get("price_source_url")),
            }
            completed[identifier] = record
            clear_error("detail", url)
            clear_error("detail", raw["source_url"])
            with (run_dir / "phones.jsonl").open("a", encoding="utf-8") as output:
                output.write(json.dumps(record, ensure_ascii=False) + "\n")
            emit("detail", f"有效详情 {len(record['specs'])} 项：{record['name']}")
            if raw.get("new_from_source"):
                publish_completed()

        publish_completed()

        totals = {page["total"] for page in checkpoint["list_pages"].values() if page["total"] is not None}
        mismatch = len(totals) > 1 or totals and len(listed_ids) != next(iter(totals))
        _resolve_alternative_layouts(checkpoint)
        if totals and not mismatch:
            unresolved = []
            for error in checkpoint["errors"]:
                if error["stage"] == "list":
                    checkpoint["resolved_errors"].append({
                        **error, "resolution": "另一正常公开布局已完整覆盖源站声明的全部独立产品",
                    })
                else:
                    unresolved.append(error)
            checkpoint["errors"] = unresolved
        series_discrepancies = _series_discrepancies(checkpoint["series"])
        new_coverage_gap = any(not info["module_found"] or not info["new_ids"] or set(info["new_ids"]) - set(completed) for info in checkpoint["brand_coverage"].values())
        status = "partial" if checkpoint["errors"] or checkpoint["official"].get("errors") or checkpoint["official"].get("pending") or mismatch or series_discrepancies or new_coverage_gap or limit is not None else "complete"
        result = report(status, "同步结束；缺失数据与失败原因已保留，不把失败标为成功")
        result["list_totals_observed"] = sorted(totals)
        result["list_count_mismatch"] = bool(mismatch)
        result["limited_run"] = limit is not None
        result["latest_coverage_gap"] = bool(new_coverage_gap)
        result["list_pages"] = checkpoint["list_pages"]
        result["failure_history"] = checkpoint["failure_history"]
        result["series_count_discrepancies"] = series_discrepancies
        _save(checkpoint_path, checkpoint)
        _save(run_dir / "report.json", result)
        _save(latest, result)
        if progress:
            progress({**result, "stage": "finished"})
        return result
    finally:
        crawler.close()
