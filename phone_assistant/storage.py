"""Transactional raw snapshots, cleaned records, and field-level provenance."""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

from phone_assistant.cleaning import CLEANING_VERSION, clean_phone
from phone_assistant.knowledge import PROJECT_ROOT
from phone_assistant.images import IMAGE_FIELDS, apply_image_override, image_quality


DEFAULT_STORAGE_PATH = PROJECT_ROOT / "data" / "phones.sqlite3"
_METADATA = {"id", "specs", "issues", "quality_score", "cleaning_version", "field_sources", "specs_sources", "_corrects_fetched_at"}
_SOURCE_FIELDS = {"origin", "availability", "fetched_at", "source_url", "price_source_url", "specs_source_url", "price_fetched_at", "specs_fetched_at", "release_source_url", "release_fetched_at", "image_source_url", "image_fetched_at", "storage_source_url", "storage_fetched_at"}
_RELEASE_FIELDS = ("release_date", "release_year", "release_month", "release_precision")
_FAMILY_SPEC_FIELDS = ("soc", "os", "os_family", "display_inches", "refresh_hz", "weight_g",
    "thickness_mm", "nfc", "five_g", "waterproof", "camera_mp")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rank(source: dict) -> tuple[int, str]:
    origin = source.get("origin")
    priority = (3 if origin == "official" else 2) if origin in {"official", "zol"} and source.get("fetched_at") else 1 if origin in {"official", "zol"} else 0
    return (priority, source.get("fetched_at") or "")


def _merge(existing: dict | None, incoming: dict) -> dict:
    if existing is None:
        existing = {"id": incoming["id"], "specs": {}, "issues": [], "field_sources": {}}
    result = dict(existing)
    provenance = dict(existing.get("field_sources", {}))
    source = {field: incoming.get(field) for field in ("origin", "source_url", "fetched_at")}
    source["source_url"] = incoming.get("source_url") or incoming.get("legacy_source")
    correction = bool(incoming.get("_corrects_fetched_at")
        and incoming.get("origin") == existing.get("origin") == "zol"
        and incoming.get("source_url") == existing.get("source_url")
        and incoming["_corrects_fetched_at"] == existing.get("fetched_at"))
    preferred = correction or _rank(incoming) >= _rank(existing)
    image_source = {**source, "source_url": incoming.get("image_source_url") or source["source_url"],
        "fetched_at": incoming.get("image_fetched_at") or source["fetched_at"]}
    old_image_source = provenance.get("image_url", existing)
    image_preferred = bool(incoming.get("image_url") and (image_quality(incoming) > image_quality(existing)
        or image_quality(incoming) == image_quality(existing) and _rank(image_source) >= _rank(old_image_source)))
    for field, value in incoming.items():
        if field in _METADATA or field in _SOURCE_FIELDS or value is None or value == "":
            continue
        if field in IMAGE_FIELDS:
            continue
        field_source = dict(source)
        if field in {"price", "price_from"}:
            field_source["source_url"] = incoming.get("price_source_url") or source["source_url"]
            field_source["fetched_at"] = incoming.get("price_fetched_at")
        elif field not in {"name", "brand", "family_key", "image_url"}:
            field_source["source_url"] = incoming.get("specs_source_url") or source["source_url"]
            field_source["fetched_at"] = incoming.get("specs_fetched_at")
        if field == "storage_gb" and incoming.get("storage_source_url"):
            field_source["source_url"] = incoming["storage_source_url"]
            field_source["fetched_at"] = incoming.get("storage_fetched_at")
        if field in {"release_date", "release_year", "release_month", "release_precision"} and incoming.get("release_source_url"):
            field_source["source_url"] = incoming["release_source_url"]
            field_source["fetched_at"] = incoming.get("release_fetched_at")
        if field in {"new_from_source", "current_source", "source_position", "discovered_at", "new_release_catalog_url"} and incoming.get("new_release_catalog_url"):
            field_source["source_url"] = incoming["new_release_catalog_url"]
            field_source["fetched_at"] = incoming.get("catalog_fetched_at")
        previous_source = provenance.get(field, existing)
        field_correction = (correction
            and previous_source.get("origin") == "zol"
            and previous_source.get("fetched_at") == incoming["_corrects_fetched_at"]
            and previous_source.get("source_url") == field_source.get("source_url"))
        if result.get(field) is None or field_correction or _rank(field_source) >= _rank(previous_source):
            result[field] = value
            provenance[field] = field_source
    for field in incoming:
        if field not in result and field != "_corrects_fetched_at":
            result[field] = None
    if preferred:
        result.update({field: incoming.get(field) for field in _SOURCE_FIELDS if field not in {"image_source_url", "image_fetched_at"}})
        result["issues"] = incoming["issues"]
        result["quality_score"] = incoming["quality_score"]
    if image_preferred:
        result.update({field: incoming.get(field) for field in IMAGE_FIELDS})
        provenance["image_url"] = image_source
    specs = dict(existing.get("specs", {}))
    specs_sources = dict(existing.get("specs_sources", {}))
    for key, value in incoming["specs"].items():
        if value is None or value == "":
            continue
        spec_source = {**source, "source_url": incoming.get("specs_source_url") or source["source_url"], "fetched_at": incoming.get("specs_fetched_at")}
        previous_source = specs_sources.get(key, existing)
        spec_correction = (correction
            and previous_source.get("origin") == "zol"
            and previous_source.get("fetched_at") == incoming["_corrects_fetched_at"]
            and previous_source.get("source_url") == spec_source.get("source_url"))
        if key not in specs or spec_correction or _rank(spec_source) >= _rank(previous_source):
            specs[key] = value
            specs_sources[key] = spec_source
    result["specs"] = specs
    result["specs_sources"] = specs_sources
    result["field_sources"] = provenance
    result["cleaning_version"] = CLEANING_VERSION
    return result


def _with_official_release(phones: list[dict]) -> list[dict]:
    """同型号的官网上市证据优先；保留来源原文，不跨配置合并价格。"""
    official = {}
    precision = {"day": 3, "month": 2, "year": 1}
    for phone in phones:
        if phone.get("origin") != "official" or not phone.get("release_year"):
            continue
        family = phone["family_key"]
        previous = official.get(family)
        rank = (precision.get(phone.get("release_precision"), 0), phone.get("release_fetched_at") or phone.get("fetched_at") or "")
        old_rank = (precision.get(previous.get("release_precision"), 0), previous.get("release_fetched_at") or previous.get("fetched_at") or "") if previous else (-1, "")
        if rank > old_rank:
            official[family] = phone
    today = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    result = []
    for phone in phones:
        source = official.get(phone["family_key"])
        if not source:
            result.append(phone)
            continue
        reported = {field: phone.get(field) for field in _RELEASE_FIELDS}
        differs = any(source.get(field) is not None and source[field] != phone.get(field) for field in _RELEASE_FIELDS[:3])
        if differs:
            record = {**phone, **{field: source.get(field) for field in _RELEASE_FIELDS}}
            record["reported_release"] = reported
            record["release_source_url"] = source.get("release_source_url") or source.get("specs_source_url") or source.get("source_url")
            record["release_fetched_at"] = source.get("release_fetched_at") or source.get("specs_fetched_at")
            record["field_sources"] = dict(phone.get("field_sources", {}))
            for field in _RELEASE_FIELDS:
                record["field_sources"][field] = source.get("field_sources", {}).get(field) or {
                    "origin": "official", "source_url": record["release_source_url"], "fetched_at": record["release_fetched_at"],
                }
            conflict = any(reported[field] is not None and source.get(field) is not None and reported[field] != source[field] for field in _RELEASE_FIELDS[:3])
            if conflict:
                record["source_conflicts"] = [{"field": "release_date", "reported": reported,
                    "official": {field: source.get(field) for field in _RELEASE_FIELDS}, "source_url": record["release_source_url"]}]
                record["issues"] = [*phone["issues"], {"field": "release_date", "code": "release_source_conflict",
                    "severity": "warning", "message": "来源上市日期与官网不一致；规范显示采用官网日期精度，原始日期和参数保留。"}]
        else:
            record = dict(phone)
        if source.get("release_date") and source["release_date"] > today:
            record["availability"] = "announced"
        result.append(record)
    return result


def _family_spec_agrees(phone: dict, field: str, previous: object, official: object) -> bool:
    if previous == official:
        return True
    if phone.get("brand") == "苹果" and field in ("soc", "os"):
        pattern = r"\bA\d{1,2}(?:\s*Pro)?" if field == "soc" else r"\biOS\s*\d+(?:\.\d+)*"
        reported = re.search(pattern, str(previous), re.I)
        published = re.search(pattern, str(official), re.I)
        if reported and published:
            return re.sub(r"\s+", "", reported.group()).casefold() == re.sub(r"\s+", "", published.group()).casefold()
    return False


def _with_official_family_specs(phones: list[dict]) -> list[dict]:
    """同一型号采用有溯源的官网通用参数；SKU价格、容量和功率不共享。"""
    official: dict[str, dict] = {}
    for phone in phones:
        if phone.get("origin") != "official":
            continue
        for field in _FAMILY_SPEC_FIELDS:
            value = phone.get(field)
            if value is None or value == "":
                continue
            source = phone.get("field_sources", {}).get(field) or {
                "origin": "official", "source_url": phone.get("specs_source_url") or phone.get("source_url"),
                "fetched_at": phone.get("specs_fetched_at") or phone.get("fetched_at"),
            }
            if source.get("origin") != "official" or not source.get("fetched_at"):
                continue
            fields = official.setdefault(phone["family_key"], {})
            previous = fields.get(field)
            if previous is None or (_rank(source), phone["id"]) > (_rank(previous[1]), previous[2]):
                fields[field] = (value, source, phone["id"])
    result = []
    for phone in phones:
        record = dict(phone)
        provenance = dict(phone.get("field_sources", {}))
        reported = dict(phone.get("reported_family_specs", {}))
        conflicts = list(phone.get("source_conflicts", []))
        issues = list(phone.get("issues", []))
        for field, (value, source, source_id) in official.get(phone["family_key"], {}).items():
            previous = phone.get(field)
            if previous is not None and previous != value:
                reported[field] = previous
            if previous is not None and not _family_spec_agrees(phone, field, previous, value):
                conflicts.append({"field": field, "reported": {field: previous}, "official": {field: value},
                    "reported_source": dict(phone.get("field_sources", {}).get(field, {})),
                    "source_url": source.get("source_url"), "fetched_at": source.get("fetched_at")})
                issues.append({"field": field, "code": "family_spec_source_conflict", "severity": "warning",
                    "message": f"同型号官网与该配置来源的 {field} 参数不一致；规范显示采用官网证据，原参数与来源保留。"})
            record[field] = value
            provenance[field] = {**source, "shared_from_id": source_id} if source_id != phone["id"] else dict(source)
        record["field_sources"] = provenance
        record["issues"] = issues
        if reported:
            record["reported_family_specs"] = reported
        if conflicts:
            record["source_conflicts"] = conflicts
        result.append(record)
    return result


class Storage:
    def __init__(self, path: Path = DEFAULT_STORAGE_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS import_batches (
                    batch_id TEXT PRIMARY KEY, imported_at TEXT NOT NULL, cleaning_version TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS raw_snapshots (
                    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_id TEXT NOT NULL, phone_id TEXT NOT NULL, origin TEXT NOT NULL,
                    fetched_at TEXT, stored_at TEXT NOT NULL, raw_json TEXT NOT NULL,
                    FOREIGN KEY(batch_id) REFERENCES import_batches(batch_id)
                );
                CREATE INDEX IF NOT EXISTS snapshots_phone ON raw_snapshots(phone_id);
                CREATE TABLE IF NOT EXISTS image_overrides (phone_id TEXT PRIMARY KEY, image_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS phones (
                    id TEXT PRIMARY KEY, record_json TEXT NOT NULL, updated_at TEXT NOT NULL,
                    cleaning_version TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS quality_issues (
                    issue_id INTEGER PRIMARY KEY AUTOINCREMENT, snapshot_id INTEGER NOT NULL,
                    phone_id TEXT NOT NULL, cleaning_version TEXT NOT NULL,
                    field TEXT NOT NULL, code TEXT NOT NULL, severity TEXT NOT NULL, message TEXT NOT NULL,
                    UNIQUE(snapshot_id, cleaning_version, field, code, message),
                    FOREIGN KEY(snapshot_id) REFERENCES raw_snapshots(snapshot_id)
                );
            """)

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _write_phone(self, connection, raw: dict, snapshot_id: int) -> dict:
        incoming = clean_phone(raw)
        row = connection.execute("SELECT record_json FROM phones WHERE id=?", (incoming["id"],)).fetchone()
        phone = _merge(json.loads(row[0]) if row else None, incoming)
        override = connection.execute("SELECT image_json FROM image_overrides WHERE phone_id=?", (incoming["id"],)).fetchone()
        if override:
            phone = apply_image_override(phone, json.loads(override[0]))
        connection.execute(
            "INSERT INTO phones(id,record_json,updated_at,cleaning_version) VALUES(?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET record_json=excluded.record_json, updated_at=excluded.updated_at, cleaning_version=excluded.cleaning_version",
            (phone["id"], json.dumps(phone, ensure_ascii=False), _now(), CLEANING_VERSION),
        )
        connection.executemany(
            "INSERT OR IGNORE INTO quality_issues(snapshot_id,phone_id,cleaning_version,field,code,severity,message) VALUES(?,?,?,?,?,?,?)",
            [(snapshot_id, phone["id"], CLEANING_VERSION, issue["field"], issue["code"], issue["severity"], issue["message"]) for issue in incoming["issues"]],
        )
        return phone

    def upsert_raw(self, raw: dict) -> dict:
        with self._connection() as connection:
            batch = uuid4().hex
            connection.execute("INSERT INTO import_batches VALUES(?,?,?)", (batch, _now(), CLEANING_VERSION))
            cursor = connection.execute(
                "INSERT INTO raw_snapshots(batch_id,phone_id,origin,fetched_at,stored_at,raw_json) VALUES(?,?,?,?,?,?)",
                (batch, str(raw.get("id", "")), raw.get("origin", "zol"), raw.get("fetched_at"), _now(), json.dumps(raw, ensure_ascii=False)),
            )
            return self._write_phone(connection, raw, cursor.lastrowid)

    def import_many(self, raws) -> dict:
        count = 0
        with self._connection() as connection:
            batch = uuid4().hex
            connection.execute("INSERT INTO import_batches VALUES(?,?,?)", (batch, _now(), CLEANING_VERSION))
            for raw in raws:
                cursor = connection.execute(
                    "INSERT INTO raw_snapshots(batch_id,phone_id,origin,fetched_at,stored_at,raw_json) VALUES(?,?,?,?,?,?)",
                    (batch, str(raw.get("id", "")), raw.get("origin", "zol"), raw.get("fetched_at"), _now(), json.dumps(raw, ensure_ascii=False)),
                )
                self._write_phone(connection, raw, cursor.lastrowid)
                count += 1
        return {"imported": count, "batch_id": batch, **self.summary()}

    def list_phones(self) -> list[dict]:
        with self._connection() as connection:
            phones = [json.loads(row[0]) for row in connection.execute("SELECT record_json FROM phones ORDER BY id")]
        return _with_official_family_specs(_with_official_release(phones))

    def get_phone(self, id: str) -> dict | None:
        with self._connection() as connection:
            row = connection.execute("SELECT record_json FROM phones WHERE id=?", (str(id),)).fetchone()
            if not row:
                return None
            phone = json.loads(row[0])
            official = [json.loads(item[0]) for item in connection.execute(
                "SELECT record_json FROM phones WHERE json_extract(record_json,'$.origin')='official' "
                "AND json_extract(record_json,'$.family_key')=? AND id<>?", (phone["family_key"], str(id))) ]
        return _with_official_family_specs(_with_official_release([phone, *official]))[0]

    def summary(self) -> dict:
        phones = self.list_phones()
        recent = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        codes = {}
        for phone in phones:
            for issue in phone["issues"]:
                codes[issue["code"]] = codes.get(issue["code"], 0) + 1
        with self._connection() as connection:
            snapshots = connection.execute("SELECT COUNT(*) FROM raw_snapshots").fetchone()[0]
            updated = connection.execute("SELECT MAX(updated_at) FROM phones").fetchone()[0]
        return {
            "records": len(phones), "families": len({phone["family_key"] for phone in phones}),
            "current_records": sum(phone["availability"] == "listed" for phone in phones),
            "fresh_records": sum(phone["origin"] in {"zol", "official"} and (phone["fetched_at"] or "") >= recent for phone in phones),
            "official_records": sum(phone["origin"] == "official" for phone in phones),
            "historical_records": sum(phone["availability"] == "historical" for phone in phones),
            "brands": len({phone["brand"] for phone in phones if phone["brand"]}),
            "missing_price": sum(phone["price"] is None for phone in phones),
            "issues": sum(len(phone["issues"]) for phone in phones), "issue_counts": codes,
            "average_quality": round(sum(phone["quality_score"] for phone in phones) / len(phones), 1) if phones else 0,
            "snapshots": snapshots, "updated_at": updated, "cleaning_version": CLEANING_VERSION,
        }

    def reclean(self) -> dict:
        with self._connection() as connection:
            snapshots = connection.execute("SELECT snapshot_id,raw_json FROM raw_snapshots ORDER BY snapshot_id").fetchall()
            connection.execute("DELETE FROM phones")
            connection.execute("DELETE FROM quality_issues WHERE cleaning_version=?", (CLEANING_VERSION,))
            for snapshot_id, payload in snapshots:
                self._write_phone(connection, json.loads(payload), snapshot_id)
        return {"recleaned": len(snapshots), **self.summary()}
