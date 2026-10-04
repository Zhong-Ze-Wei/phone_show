"""从有机型身份的页面主图补充图片；离线回放不刷新报价或上市证据。"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, SoupStrainer


IMAGE_FIELDS = ("image_url", "image_role", "image_width", "image_height", "image_source_url", "image_fetched_at")


def image_rank(record: dict) -> int:
    """角色来自实际页面容器；旧值仅识别URL已有尺寸标记，不生成新URL。"""
    role = record.get("image_role")
    if role:
        return {"primary": 3, "catalog": 2, "thumbnail": 1}.get(role, 0)
    match = re.search(r"(?:_|/t_s)(\d+)x(\d+)", record.get("image_url") or "")
    if match:
        return 1 if int(match[1]) <= 120 else 3
    return 2 if record.get("image_url") else 0


def image_quality(record: dict) -> tuple[int, int]:
    # 同角色优先采用页面声明展示尺寸较大的图，未知尺寸不编造。
    return image_rank(record), (record.get("image_width") or 0) * (record.get("image_height") or 0)


def image_record(node, source_url: str, role: str) -> dict:
    if node is None:
        return {}
    value = next((node.get(attr) for attr in ("data-original", "data-src", ".src", "src")
                  if node.get(attr) and not node.get(attr).startswith("data:")), None)
    if not value:
        return {}
    url = urljoin(source_url, value)
    if urlparse(url).scheme not in ("http", "https"):
        return {}
    if re.search(r"logo|(?:^|[/_-])icons?(?:[/_.-]|$)|qrcode|qr-code", urlparse(url).path, re.I) or re.search(
        r"logo|二维码|官网APP|按钮|品牌标志", node.get("alt", ""), re.I
    ):
        return {}
    result = {"image_url": url, "image_role": role, "image_source_url": source_url}
    # 只保留HTML明确的尺寸属性，不把布局尺寸声称为下载图片的真实像素。
    for field in ("width", "height"):
        text = str(node.get(field) or "")
        if text.isdigit() and int(text) > 0:
            result["image_" + field] = int(text)
    return result


def zol_primary_image(soup, source_url: str) -> dict:
    match = re.search(r"(?:index|/)(\d+)(?:\.shtml|/param\.shtml)", source_url)
    if not match:
        return {}
    identifier = match.group(1)
    for node in soup.select(".big-pic img, img#big-pic, .goods-card__pic img"):
        link = node.find_parent("a", href=True)
        if not link:
            continue
        href = link["href"]
        # 主图链接必须属于当前SKU；相关机型、广告和样张列表不参与。
        if not re.search(rf"(?:index{identifier}\.shtml|_p{identifier}\.shtml)$", urlparse(href).path):
            continue
        image = image_record(node, source_url, "primary")
        if image:
            return image
    return {}


def official_primary_image(soup, source_url: str, brand: str) -> dict:
    # 调用者必须先通过官网正文机型校验。仅使用已核对的产品色图容器。
    if brand == "vivo":
        for node in soup.select(".color-image-list .color-image-item img"):
            image = image_record(node, source_url, "primary")
            if image:
                return image
    return {}


def preferred_image(current: dict, incoming: dict) -> dict:
    if incoming.get("image_url") and image_quality(incoming) >= image_quality(current):
        return {key: incoming[key] for key in IMAGE_FIELDS if key in incoming}
    return {key: current[key] for key in IMAGE_FIELDS if key in current}


def apply_image_override(phone: dict, image: dict) -> dict:
    if image_quality(image) < image_quality(phone):
        return phone
    old_source = phone.get("field_sources", {}).get("image_url", {})
    new_source = image["field_sources"]["image_url"]
    if image_quality(image) == image_quality(phone) and (new_source.get("fetched_at") or "") < (old_source.get("fetched_at") or ""):
        return phone
    return {**phone, **{field: image.get(field) for field in IMAGE_FIELDS},
        "field_sources": {**phone.get("field_sources", {}), "image_url": new_source}}


def _cache_index(raw_dir: Path) -> dict[str, tuple[Path, dict]]:
    index = {}
    metadata = list(raw_dir.glob("zol-sync-*/html/*.json")) + list(raw_dir.glob("official/*/*.json")) + list(raw_dir.glob("zol-sync-*/official/*.json"))
    for path in metadata:
        if not re.fullmatch(r"[a-f0-9]{20}", path.stem) or not path.with_suffix(".html").exists():
            continue
        source = json.loads(path.read_text(encoding="utf-8"))
        url = source.get("requested_url") or source.get("url")
        stamp = source.get("fetched_at")
        if not url or not stamp or source.get("status") != 200:
            continue
        previous = index.get(url)
        if previous is None or stamp > previous[1]["fetched_at"]:
            index[url] = (path.with_suffix(".html"), source)
    return index


def _non_image_digest(record: dict) -> str:
    unchanged = {key: value for key, value in record.items() if key not in IMAGE_FIELDS}
    unchanged["field_sources"] = {key: value for key, value in record.get("field_sources", {}).items() if key != "image_url"}
    return hashlib.sha256(json.dumps(unchanged, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def replay_cached_images(db_path: Path, raw_dir: Path, *, apply: bool = False) -> dict:
    """已保存HTTP响应优先；只发布图字段，审计保留原获取时间。"""
    from phone_assistant.cleaning import clean_phone
    from phone_assistant.official_sources import parse_specifications

    connection = sqlite3.connect(Path(db_path).resolve().as_uri() + ("?mode=rw" if apply else "?mode=ro"), uri=True)
    reader = ThreadPoolExecutor(max_workers=8)
    try:
        phones = [json.loads(row[0]) for row in connection.execute("SELECT record_json FROM phones ORDER BY id")]
        cache = _cache_index(Path(raw_dir))
        needed_urls = {url for phone in phones if phone.get("origin") in ("zol", "official")
            for url in (phone.get("source_url"), phone.get("specs_source_url")) if url}
        reads = {url: reader.submit(path.read_text, encoding="utf-8") for url, (path, _metadata) in cache.items() if url in needed_urls}
        pages, official_families, errors = {}, {}, []

        def candidate(url: str, brand: str | None = None):
            key = (url, brand)
            if key in pages:
                return pages[key]
            if brand and brand != "vivo":
                pages[key] = ({}, [])
                return pages[key]
            saved = cache.get(url)
            if not saved:
                pages[key] = ({}, [])
                return pages[key]
            path, metadata = saved
            html = reads.pop(url).result()
            if brand:
                soup = BeautifulSoup(html, "html.parser")
            else:
                # 只解析已确认的产品主图容器，避免全库回放重复构建广告和参数DOM。
                containers = re.findall(r'''<div\b[^>]*\bclass=["'][^"']*\b(?:big-pic|goods-card__pic)\b[^"']*["'][^>]*>.*?</div\s*>''', html, re.I | re.S)
                soup = BeautifulSoup("".join(containers), "html.parser", parse_only=SoupStrainer("div", class_=re.compile(
                    r"(?:^|\s)(?:big-pic|goods-card__pic)(?:\s|$)")))
            final_url = metadata.get("source_url") or metadata.get("response_url") or url
            if urlparse(final_url).path.rstrip("/") != urlparse(url).path.rstrip("/"):
                pages[key] = ({}, [])
                return pages[key]
            families = []
            if brand:
                try:
                    raws = parse_specifications(html, url, brand, fetched_at=metadata["fetched_at"])
                except ValueError as error:
                    errors.append({"source_url": url, "cache_path": str(path), "message": str(error)})
                    pages[key] = ({}, [])
                    return pages[key]
                families = [clean_phone(raw)["family_key"] for raw in raws]
                image = official_primary_image(soup, url, brand)
            else:
                title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
                title = title_match.group(1) if title_match else ""
                image = zol_primary_image(soup, url) if ("ZOL" in title or "中关村在线" in title) else {}
            if image:
                image.update(image_fetched_at=metadata["fetched_at"], origin="official" if brand else "zol", cache_path=str(path))
            pages[key] = image, families
            return pages[key]

        for phone in phones:
            if phone.get("origin") != "official":
                continue
            brand = phone.get("platform")
            url = phone.get("specs_source_url")
            if not brand or not url:
                continue
            image, families = candidate(url, brand)
            if image and phone.get("family_key") in families:
                family = phone["family_key"]
                old = official_families.get(family)
                if old is None or image["image_fetched_at"] > old["image_fetched_at"]:
                    official_families[family] = image

        prepared = []
        for phone in phones:
            if phone.get("origin") not in ("zol", "official"):
                continue
            options = []
            if phone.get("origin") == "zol":
                for url in dict.fromkeys([phone.get("source_url"), phone.get("specs_source_url")]):
                    if url:
                        image, _ = candidate(url)
                        if image:
                            options.append(image)
            if phone.get("family_key") in official_families:
                options.append(official_families[phone["family_key"]])
            if options:
                image = max(options, key=lambda item: (image_quality(item), item["origin"] == "official", item["image_fetched_at"]))
                prepared.append((phone["id"], phone.get("family_key"), image))

        changes = []
        with connection:
            if apply:
                # HTML解析已完成；短事务中重读最新记录，避免覆盖并发采集的新报价。
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("CREATE TABLE IF NOT EXISTS image_overrides (phone_id TEXT PRIMARY KEY, image_json TEXT NOT NULL)")
            for identifier, family, image in prepared:
                row = connection.execute("SELECT record_json FROM phones WHERE id=?", (identifier,)).fetchone()
                if row is None:
                    continue
                phone = json.loads(row[0])
                if phone.get("family_key") != family:
                    continue
                if image_quality(image) < image_quality(phone):
                    continue
                source = {"origin": image["origin"], "source_url": image["image_source_url"], "fetched_at": image["image_fetched_at"]}
                override = {**{field: image.get(field) for field in IMAGE_FIELDS}, "field_sources": {"image_url": source},
                    "cache_path": image["cache_path"]}
                updated = apply_image_override(phone, override)
                if updated == phone:
                    continue
                before_digest = _non_image_digest(phone)
                after_digest = _non_image_digest(updated)
                if before_digest != after_digest:
                    raise AssertionError("图片回放不能修改非图片字段")
                changes.append({"id": phone["id"], "name": phone["name"], "before": phone.get("image_url"),
                    "after": image["image_url"], "source_url": image["image_source_url"],
                    "cache_path": image["cache_path"], "captured_at": image["image_fetched_at"],
                    "image_role": image["image_role"], "html_width": image.get("image_width"),
                    "html_height": image.get("image_height"), "non_image_before_sha256": before_digest,
                    "non_image_after_sha256": after_digest})
                if apply:
                    connection.execute("UPDATE phones SET record_json=? WHERE id=?", (json.dumps(updated, ensure_ascii=False), phone["id"]))
                    connection.execute("INSERT INTO image_overrides VALUES(?,?) ON CONFLICT(phone_id) DO UPDATE SET image_json=excluded.image_json",
                        (phone["id"], json.dumps(override, ensure_ascii=False)))
        return {"applied": apply, "checked_at": datetime.now(timezone.utc).isoformat(), "patched": len(changes) if apply else 0,
            "would_patch": len(changes), "unchanged": len(phones) - len(changes), "records": len(phones),
            "network_requests": 0, "non_image_fields_unchanged": True, "changes": changes, "errors": errors}
    finally:
        reader.shutdown(wait=True)
        connection.close()


def main():
    from phone_assistant.config import PROJECT_ROOT

    parser = argparse.ArgumentParser(description="从已保存真实页面回放产品主图，不联网、不刷新价格证据")
    parser.add_argument("--apply", action="store_true", help="发布图片字段；默认仅预览")
    parser.add_argument("--report", type=Path, help="保存图片来源审计JSON")
    arguments = parser.parse_args()
    report = replay_cached_images(PROJECT_ROOT / "data/phones.sqlite3", PROJECT_ROOT / "data/raw", apply=arguments.apply)
    if arguments.report:
        arguments.report.parent.mkdir(parents=True, exist_ok=True)
        arguments.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key not in ("changes", "errors")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
