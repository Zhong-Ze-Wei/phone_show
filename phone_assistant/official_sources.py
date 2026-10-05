"""Discover phones from public Chinese manufacturer pages and retain their evidence.

This supplements ZOL rather than pretending that a manufacturer's starting price
is a particular storage variant's current retail price.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import time
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
import httpx

from .config import PROJECT_ROOT
from .images import image_record, official_primary_image

CATALOGS = {
    "vivo": "https://www.vivo.com.cn/",
    "oppo": "https://www.oppo.com/cn/smartphones/",
    "apple": "https://www.apple.com.cn/iphone/",
    "huawei": "https://consumer.huawei.com/cn/phones/",
    "honor": "https://www.honor.com/cn/phones/",
}
BRAND_NAMES = {"vivo": "vivo", "oppo": "OPPO", "apple": "苹果", "huawei": "华为", "honor": "荣耀"}
_HOSTS = {
    "vivo": {"www.vivo.com", "www.vivo.com.cn"},
    "oppo": {"www.oppo.com"}, "apple": {"www.apple.com.cn"},
    "huawei": {"consumer.huawei.com"}, "honor": {"www.honor.com"},
}
_PATHS = {
    "vivo": r"/vivo/(?:x\d|xfold\d|s\d|y\d|iqoo\d)[a-z0-9-]*/?",
    "oppo": r"/cn/smartphones/series-[a-z0-9-]+/[a-z0-9-]+/?",
    "apple": r"/iphone-(?:\d[a-z0-9-]*|duo|air|se)(?:/specs)?/?",
    "huawei": r"/cn/phones/(?:mate|pura|pocket|nova|enjoy|changxiang)[a-z0-9-]*/?",
    "honor": r"/cn/phones/honor-[a-z0-9-]+/?",
}


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_cn() -> str:
    return datetime.now(timezone(timedelta(hours=8))).date().isoformat()


def _model_slug(url: str, brand: str) -> str:
    parts = urlsplit(url).path.strip("/").split("/")
    if brand == "vivo":
        return parts[2] if len(parts) > 2 and parts[1] == "param" else parts[1] if len(parts) > 1 else ""
    if parts[-1] in {"spec", "specs"}:
        parts.pop()
    return parts[-1]


def _specification_links(soup, landing_url: str, brand: str) -> list[str]:
    model_slug = _model_slug(landing_url, brand)
    links = []
    for node in soup.select("a[href]"):
        if not re.search(r"/(?:specs?|param)/", node["href"]):
            continue
        url = _url(node["href"], landing_url)
        if urlsplit(url).hostname in _HOSTS[brand] and _model_slug(url, brand) == model_slug:
            links.append(url)
    return list(dict.fromkeys(links))


def _text(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip() if node else ""


def _url(value: str, base: str) -> str:
    parsed = urlsplit(urljoin(base, value))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _is_phone(url: str, brand: str) -> bool:
    parsed = urlsplit(url)
    return parsed.hostname in _HOSTS[brand] and bool(re.fullmatch(_PATHS[brand], parsed.path, re.I))


def _has_new_marker(node) -> bool:
    """A nearby badge/latest section is evidence; a CSS 'new-button' is not."""
    for parent in [node, *list(node.parents)[:4]]:
        if parent.get("data-series") == "latest":
            return True
        if parent.get("data-is-new") in {"true", "1"}:
            return True
    # Keep the badge local. Inspecting a parent UL would mark every old sibling
    # as new when only the first product has a badge.
    for badge in node.select(".badge-new, .new_product, .prd-new, .new-tag"):
        expiry = badge.get("data-off-time")
        if expiry and expiry.isdigit() and int(expiry) < datetime.now(timezone.utc).timestamp() * 1000:
            continue
        if re.fullmatch(r"新款|新品|NEW|New", _text(badge)):
            return True
    return False


def _nearby_card(node):
    for parent in [node, *list(node.parents)[:5]]:
        if parent.name == "li" or any("card" in name or "pdl-item" == name for name in parent.get("class", [])):
            return parent
    return node


def discover_models(html: str, catalog_url: str, brand: str) -> list[dict]:
    """Only follow actual product links; never generate guessed model URLs."""
    soup = BeautifulSoup(html, "html.parser")
    discovered: dict[str, dict] = {}

    def add(url: str, name: str = "", new: bool = False, image: str | None = None, price_from=None):
        url = _url(url, catalog_url)
        if not _is_phone(url, brand):
            return
        # Apple's current catalogue can link directly to an older phone's
        # specifications instead of a product landing page. Keep that real URL
        # and combine both link forms when the same model has both.
        key = _model_slug(url, brand) if brand == "apple" else url
        specs_url = url if brand == "apple" and urlsplit(url).path.rstrip("/").endswith("/specs") else None
        if key in discovered:
            discovered[key]["new_from_source"] |= new
            if not discovered[key].get("image_url") and image:
                discovered[key]["image_url"] = image
            if specs_url:
                discovered[key]["specs_url"] = specs_url
            return
        discovered[key] = {"url": url, "name": name, "new_from_source": new,
                           "source_position": len(discovered), "image_url": image, "price_from": price_from}
        if specs_url:
            discovered[key]["specs_url"] = specs_url

    for node in soup.select("a[href]"):
        url = _url(node["href"], catalog_url)
        if not _is_phone(url, brand):
            continue
        card = _nearby_card(node)
        image = card.select_one("img")
        name = node.get("tm-product_name") or node.get("data-analytics-title") or _text(card.select_one(".product_name_text"))
        name = name or (image.get("alt", "") if image else "") or _text(node)
        price_node = card.select_one(".prd-price, .price, [data-price]")
        price_match = re.search(r"(?:RMB|¥|￥)\s*([\d,]+)|([\d,]+)\s*元\s*起", _text(price_node))
        add(url, name, _has_new_marker(node),
            image_record(image, catalog_url, "catalog").get("image_url"),
            (price_match.group(1) or price_match.group(2)).replace(",", "") if price_match else None)

    if brand == "vivo":
        # Nuxt's public SSR payload uses array-index references (devalue format).
        # Reading the documented page payload avoids private/signed shop APIs.
        for script in soup.select('script[type="application/json"]'):
            if not script.string:
                continue
            payload = json.loads(script.string)
            if not isinstance(payload, list):
                continue
            for obj in payload:
                if not isinstance(obj, dict) or "pcUrl" not in obj:
                    continue
                def value(key):
                    index = obj.get(key)
                    return payload[index] if isinstance(index, int) and 0 <= index < len(payload) else index
                url = value("pcUrl")
                if isinstance(url, str):
                    title = value("mainTitle") or ""
                    banner = value("bannerName") or ""
                    add(url, title if isinstance(title, str) else "", bool(re.search(r"新品|发布|首发", str(banner))), value("pcImg"))
    return list(discovered.values())


def _put(specs: dict, key: str, value: str) -> None:
    if key and value:
        if key not in specs:
            specs[key] = value
        elif value not in specs[key]:
            specs[key] += "\n" + value


def _parse_vivo(soup) -> tuple[str, list[dict]]:
    specs = {}
    for section in soup.select(".parameter-item"):
        heading = _text(section.select_one(".parameter-title"))
        for row in section.select(".attr-item"):
            key = _text(row.select_one(".attr-item-name")) or heading
            _put(specs, key, _text(row.select_one(".attr-item-text")))
    title = _text(soup.title).split(" 专业")[0].split(" - ")[0]
    # Product titles may include marketing copy, e.g. S60's '4K原生感Live'.
    # The public SSR primary-product object has its own explicit name/code.
    # This is stronger identity evidence than stripping arbitrary title suffixes.
    primary_products = []
    for script in soup.select('script[type="application/json"]'):
        if not script.string:
            continue
        payload = json.loads(script.string)
        if not isinstance(payload, list):
            continue
        for obj in payload:
            if isinstance(obj, dict) and {"name", "code", "seoTitle"}.issubset(obj):
                name, code = payload[obj["name"]], payload[obj["code"]]
                if _model_identity(name, "vivo") != _model_identity(code, "vivo"):
                    raise ValueError("官网主产品名称与标识不一致")
                primary_products.append(name.strip())
    if primary_products:
        if len(set(primary_products)) != 1:
            raise ValueError("官网规格页出现多个主产品身份")
        title = primary_products[0]
        if not re.match(r"(?:vivo|iqoo)", title, re.I):
            title = "vivo " + title
    prices = specs.get("建议零售价", "")
    variants = []
    pattern = r"((?:vivo|iQOO)\s*[^：:（）]+)[（(]([^）)]+)[）)]\s*[：:]\s*([\d,.]+)\s*元"
    for match in re.finditer(pattern, prices):
        name, capacity, price = match.groups()
        variant_specs = dict(specs)
        pair = re.fullmatch(r"(\d+GB)\s*\+\s*(\d+(?:GB|TB))", capacity, re.I)
        if pair:
            variant_specs["运行内存RAM容量(GB)"] = pair.group(1)
            variant_specs["机身存储ROM容量(GB)"] = pair.group(2)
        variants.append({"name": name.strip() + "(" + capacity + ")", "price": price.replace(",", ""),
                         "price_kind": "official_msrp", "specs": variant_specs})
    return title, variants or [{"name": title, "specs": specs}]


def _parse_oppo(soup) -> tuple[str, list[dict]]:
    specs = {}
    for row in soup.select(".item-right-list"):
        key_node = row.select_one(".key > span") or row.select_one(".key")
        key = _text(key_node)
        # Both camera and video sections use the bare label '后置'. Preserve
        # their parent labels so codec text cannot become a camera specification.
        section = row.find_parent(class_="param-detail-item")
        parent_key = _text(section.select_one(".item-left-heading > span")) if section else ""
        if key in {"后置", "前置", "尺寸", "类型"}:
            key = parent_key + "/" + key
        _put(specs, key, _text(row.select_one(".value")))
    name = _text(soup.select_one("h2.detail-name span")) or _text(soup.select_one("h1"))
    if name and not name.startswith("OPPO"):
        name = "OPPO " + name
    return name, [{"name": name, "specs": specs}]


def _parse_honor(soup) -> tuple[str, list[dict]]:
    specs = {}
    for row in soup.select(".products-spec-component-list-item-right-item-list-item"):
        heading = row.select_one("h3")
        values = [BeautifulSoup(node["data-value"], "html.parser").get_text(" ", strip=True)
                  for node in row.select("[data-value]")]
        _put(specs, _text(heading), "\n".join(values))
    name = _text(soup.select_one("h1")) or re.split(r"参数配置|规格| - |\|", _text(soup.title))[0].strip()
    return name, [{"name": name, "specs": specs}]


def _parse_huawei(soup) -> tuple[str, list[dict]]:
    specs = {}
    for section in soup.select(".large-accordion__item"):
        heading = _text(section.select_one(".large-accordion__title"))
        for row in section.select(".large-accordion__wrap, .large-accordion__inner"):
            if row.select_one(".large-accordion__wrap"):
                continue
            label = _text(row.select_one(".large-accordion-subtitle"))
            values = [_text(node) for node in row.select("p") if "large-accordion-subtext" not in node.get("class", [])]
            # Prefix dimensions/type labels with the parent section to avoid
            # confusing a display size with a body dimension or a camera size.
            key = heading + "/" + label if label else heading
            _put(specs, key, "\n".join(values))
    name = _text(soup.select_one(".specs-banner-cnt .large-accordion-title")) or _text(soup.select_one("h1")).replace("规格参数", "").strip()
    name = name.replace("HUAWEI", "华为").strip()
    return name, [{"name": name, "specs": specs}]


def _parse_apple(soup) -> tuple[str, list[dict]]:
    names = list(dict.fromkeys(_text(node) for node in soup.select(".techspecs-columnheader") if "iPhone" in _text(node)))
    if not names:
        name = re.split(r" - |技术规格", _text(soup.title))[0].strip()
        names = [name]
    variants = [{"name": name, "specs": {}} for name in names]
    models = {_model_identity(variant["name"], "apple"): variant for variant in variants}
    key, continuation_rows = "", 0
    for row in soup.select(".techspecs-row"):
        header = row.select_one(":scope > .techspecs-rowheader")
        if header:
            # Apple puts common parameters in a following headerless row and
            # explicitly spans the previous label across those rows.
            for note in header.select("sup"):
                note.decompose()
            key = _text(header)
            continuation_rows = int(header.get("aria-rowspan", "1")) - 1
        elif continuation_rows:
            continuation_rows -= 1
        else:
            continue
        columns = row.select(":scope > .techspecs-column")
        for index, column in enumerate(columns):
            named_models = {_model_identity(_text(heading), "apple") for heading in column.select(".techspecs-small-heading")
                            if "iPhone" in _text(heading)}
            if named_models:
                if not named_models.issubset(models):
                    raise ValueError("Apple规格列包含未确认的机型名称")
                targets = [models[name] for name in named_models]
            elif len(columns) == 1 or int(column.get("aria-colspan", "1")) >= len(variants):
                targets = variants
            else:
                targets = variants[index:index + 1]
            for heading in column.select(".techspecs-small-heading"):
                heading.decompose()
            for variant in targets:
                _put(variant["specs"], key, _text(column))
    for variant in variants:
        _apple_canonical_specs(variant["specs"])
    return names[0], variants


def _apple_canonical_specs(specs: dict) -> None:
    """Expose only measurements and features explicitly labelled by Apple."""
    network = next((value for key, value in specs.items() if re.sub(r"\s+", "", key) == "蜂窝网络和无线连接"), "")
    if network:
        specs.setdefault("网络类型", network)
        nfc = re.search(r"(?:不支持|支持)[^。；;\n]{0,30}NFC(?![a-z0-9])", network, re.I)
        if nfc:
            specs.setdefault("NFC", nfc.group(0))
    refresh = re.search(r"刷新率[^\d。；;]{0,24}(\d+(?:\.\d+)?\s*Hz)", specs.get("显示屏", ""), re.I)
    if refresh:
        specs.setdefault("屏幕刷新率", refresh.group(1))
    camera = re.search(r"(\d+(?:\.\d+)?\s*(?:万像素|百万像素|MP))[^\d。；;，,]{0,16}主摄", specs.get("摄像头", ""), re.I)
    if camera:
        specs.setdefault("主摄像素", camera.group(1))
    chip = re.match(r"(A\d+(?:\s+(?:Pro|Bionic))?)\s*芯片(?:\s|$)", specs.get("芯片", ""), re.I)
    if chip:
        specs.setdefault("芯片型号", chip.group(1))


_PARSERS = {"vivo": _parse_vivo, "oppo": _parse_oppo, "honor": _parse_honor,
            "huawei": _parse_huawei, "apple": _parse_apple}
_ALIASES = {
    "上市时间": "上市日期", "尺寸（英寸）": "屏幕尺寸", "后置摄像头像素": "摄像头像素",
    "后置摄像头": "摄像头像素", "运行内存（RAM）": "运行内存RAM容量(GB)",
    "机身存储（ROM）": "机身存储ROM容量(GB)", "尺寸与重量/厚度": "机身厚度(毫米)",
    "尺寸与重量/重量": "机身重量(克)", "厚": "机身厚度(毫米)",
    "屏幕/尺寸": "屏幕尺寸", "屏幕/大小": "屏幕尺寸", "显示/尺寸": "屏幕尺寸", "电池": "电池容量",
    "拍摄/后置": "摄像头像素", "相机/后置": "摄像头像素",
    "摄像头/后置": "摄像头像素", "网络频段": "网络类型",
    "有线快充": "有线充电", "充电规格": "有线充电", "充电": "有线充电",
    "充电/有线充电": "有线充电", "快速充电": "有线充电", "移动平台": "芯片型号",
    "芯片": "芯片型号", "容量": "机身存储ROM容量(GB)", "防尘抗水": "防水防尘",
    "防溅、抗水、防尘": "防水防尘", "摄像头": "摄像头像素",
    "存储/运行内存（RAM）": "运行内存RAM容量(GB)",
    "存储/机身内存（ROM）": "机身存储ROM容量(GB)",
    "网络制式": "网络类型", "蜂窝网络和无线连接": "网络类型", "操作系统": "操作系统",
}


def _model_identity(name: str, brand: str) -> str:
    """Compare explicit model names, allowing only evidenced naming aliases."""
    name = re.sub(r"[（(]\d+\s*(?:GB|TB)[^）)]*[）)]$", "", name, flags=re.I)
    identity = re.sub(r"[\s\W_]+", "", name.casefold())
    prefixes = {"vivo": ("vivo",), "oppo": ("oppo",), "apple": ("apple", "苹果"),
                "huawei": ("huawei", "华为"), "honor": ("honor", "荣耀")}
    for prefix in prefixes[brand]:
        if identity.startswith(prefix):
            identity = identity[len(prefix):]
            break
    if brand == "huawei":
        identity = identity.replace("非凡大师", "ultimatedesign")
    elif brand == "honor":
        identity = identity.replace("超能版", "superpower").replace("元气版", "genki")
        identity = re.sub(r"^(\d+)超级版$", r"\1", identity)
        identity = re.sub(r"(molly)\d+周年限定版$", r"\1", identity)
    elif brand == "vivo":
        identity = re.sub(r"^(s\d+)元气版$", r"\1e", identity)
    return identity


def _validate_model_identity(page_name: str, variants: list[dict], soup, source_url: str, brand: str) -> None:
    expected = _model_identity(_model_slug(source_url, brand), brand)
    names = {_model_identity(variant["name"], brand) for variant in variants}
    allowed = {expected}
    if brand == "apple":
        # Apple can put Pro/Pro Max or the base/Plus model on one specification
        # page. Only explicit same-page columns authorize the companion model.
        companion = (expected + "max" if re.fullmatch(r"iphone\d+pro", expected)
                     else expected + "plus" if re.fullmatch(r"iphone\d+", expected) else None)
        columns = {_model_identity(_text(node), brand) for node in soup.select(".techspecs-columnheader")}
        if companion and {expected, companion}.issubset(columns):
            allowed.add(companion)
    if _model_identity(page_name, brand) != expected or expected not in names or not names.issubset(allowed):
        raise ValueError("官网正文机型与请求不一致，未发布记录：" + source_url + "；正文：" + ", ".join(variant["name"] for variant in variants))


def parse_specifications(html: str, source_url: str, brand: str, *, fetched_at: str,
                         catalog_url: str | None = None, model: dict | None = None) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    page_name, variants = _PARSERS[brand](soup)
    if any(not variant["specs"] or not variant["name"] for variant in variants):
        raise ValueError("官网规格结构未识别，未发布空记录：" + source_url)
    _validate_model_identity(page_name, variants, soup, source_url, brand)
    model = model or {}
    primary = official_primary_image(soup, source_url, brand)
    raws = []
    for variant in variants:
        specs = variant["specs"]
        for original, canonical in _ALIASES.items():
            if original in specs and canonical not in specs:
                specs[canonical] = specs[original]
        if brand == "apple":
            dimensions = specs.get("尺寸与重量", "")
            thickness = re.search(r"厚度\s*[：:]\s*(\d+(?:\.\d+)?\s*毫米)", dimensions)
            weight = re.search(r"重量\s*[：:]\s*(\d+(?:\.\d+)?\s*克)", dimensions)
            screen = re.search(r"\d+(?:\.\d+)?\s*英寸", specs.get("显示屏", ""))
            for key, match in [("机身厚度(毫米)", thickness), ("机身重量(克)", weight), ("屏幕尺寸", screen)]:
                if match:
                    specs[key] = match.group(1) if match.lastindex else match.group(0)
        slug = urlsplit(source_url).path.strip("/").replace("/", ":")
        capacity = re.search(r"[（(]([^）)]+)[）)]$", variant["name"])
        suffix = ":" + capacity.group(1).lower().replace("+", "-") if capacity else ""
        if brand == "apple":
            suffix = ":" + re.sub(r"\W+", "-", variant["name"].lower()).strip("-")
        raws.append({
            "id": "official:" + brand + ":" + slug + suffix,
            "name": variant["name"], "brand": "iQOO" if brand == "vivo" and re.match(r"iqoo\s*\d", variant["name"], re.I) else BRAND_NAMES[brand],
            "origin": "official", "platform": brand,
            "price": variant.get("price"), "price_kind": variant.get("price_kind"),
            "price_from": model.get("price_from"), "image_url": model.get("image_url"),
            "image_role": "catalog" if model.get("image_url") else None,
            "image_source_url": catalog_url if model.get("image_url") else None,
            "image_fetched_at": model.get("catalog_fetched_at") if model.get("image_url") else None,
            **primary,
            "source_url": model.get("url") or source_url, "specs_source_url": source_url,
            "price_source_url": source_url if variant.get("price") is not None else catalog_url if model.get("price_from") is not None else None,
            "fetched_at": fetched_at, "specs_fetched_at": fetched_at,
            "price_fetched_at": fetched_at if variant.get("price") is not None else model.get("catalog_fetched_at") if model.get("price_from") is not None else None,
            "availability": "unknown", "specs": specs, "current_source": True,
            "new_from_source": model.get("new_from_source") is True,
            "new_release_catalog_url": catalog_url, "source_position": model.get("source_position"),
            "discovered_at": model.get("catalog_fetched_at") or fetched_at,
            "catalog_fetched_at": model.get("catalog_fetched_at"),
            "release_source_url": source_url if "上市日期" in specs else None,
            "release_fetched_at": fetched_at if "上市日期" in specs else None,
        })
        if primary:
            raws[-1]["image_fetched_at"] = fetched_at
    return raws


class _PublicPages:
    def __init__(self, timeout: float, delay: float, cache_dir: Path):
        self.client = httpx.Client(timeout=timeout, follow_redirects=True,
                                  headers={"User-Agent": "Mozilla/5.0 (compatible; PhoneCatalog/1.0)"})
        self.delay, self.cache_dir = delay, cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.last_request = 0.0
        self.pages = {}

    def get(self, url: str) -> tuple[str, str]:
        if url in self.pages:
            return self.pages[url]
        wait = self.delay - (time.monotonic() - self.last_request)
        if wait > 0:
            time.sleep(wait)
        response = self.client.get(url)
        self.last_request = time.monotonic()
        response.raise_for_status()
        if urlsplit(str(response.url)).hostname not in set().union(*_HOSTS.values()):
            raise ValueError("官网请求跳转到非品牌域名：" + url)
        if re.search(r"/(?:specs?|param)/", url) and urlsplit(str(response.url)).path.rstrip("/") != urlsplit(url).path.rstrip("/"):
            raise ValueError("规格页跳转到其他产品路径：" + url)
        fetched_at = _utc()
        response.encoding = "utf-8"
        html = response.text
        if any(marker in html for marker in ("请完成安全验证", "访问验证", "验证码验证")):
            raise ValueError("官网返回访问验证页：" + url)
        digest = sha256(url.encode()).hexdigest()[:20]
        (self.cache_dir / (digest + ".html")).write_text(html, encoding="utf-8")
        (self.cache_dir / (digest + ".json")).write_text(json.dumps({"requested_url": url, "source_url": str(response.url),
                                                                  "fetched_at": fetched_at, "status": response.status_code}, ensure_ascii=False), encoding="utf-8")
        self.pages[url] = html, fetched_at
        return html, fetched_at


def sync_official(storage=None, *, brands=None, timeout: float = 20, delay: float = 0.6,
                  progress=None, cache_dir: Path | None = None, max_per_brand: int | None = 12,
                  offset_per_brand: dict[str, int] | None = None) -> dict:
    """Discover and collect normal public pages; caller may atomically publish raws.

    ``storage=None`` only collects. Caps and failures remain visible in coverage;
    a successful request never implies complete coverage of a brand.
    """
    selected = list(CATALOGS) if brands is None else [str(brand).lower() for brand in brands]
    unknown = set(selected) - CATALOGS.keys()
    if unknown:
        raise ValueError("不支持的官方来源：" + ", ".join(sorted(unknown)))
    cache_dir = Path(cache_dir) if cache_dir else PROJECT_ROOT / "data" / "raw" / "official" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    pages = _PublicPages(timeout, delay, cache_dir)
    report = {"raws": [], "discovered": 0, "imported": 0, "errors": [], "coverage": {}, "fetched_at": _utc()}
    try:
        for brand in selected:
            catalog = CATALOGS[brand]
            coverage = {"catalog_url": catalog, "discovered": 0, "collected": 0, "records": 0, "pending": 0, "errors": []}
            report["coverage"][brand] = coverage
            if progress:
                progress({"phase": "official_discovery", "brand": brand, "url": catalog})
            try:
                html, catalog_time = pages.get(catalog)
                models = discover_models(html, catalog, brand)
                if not models:
                    raise ValueError("官网目录未发现手机链接，需检查页面结构：" + catalog)
                models.sort(key=lambda model: (not model["new_from_source"], model["source_position"]))
                for model in models:
                    model["catalog_fetched_at"] = catalog_time
                    model["catalog_url"] = catalog
                known = {model["url"] for model in models}
                index = (offset_per_brand or {}).get(brand, 0)
                if index < 0:
                    raise ValueError("官网目录偏移量不能小于0")
                processed = 0
                while index < len(models) and (max_per_brand is None or processed < max_per_brand):
                    model = models[index]
                    index += 1
                    processed += 1
                    if progress:
                        progress({"phase": "official_specs", "brand": brand, "url": model["url"], "index": index})
                    try:
                        landing, landing_time = pages.get(model["url"])
                        soup = BeautifulSoup(landing, "html.parser")
                        if brand == "vivo":
                            for peer in discover_models(landing, model["url"], brand):
                                if peer["url"] not in known:
                                    known.add(peer["url"])
                                    peer["new_from_source"] = False
                                    peer["source_position"] = len(models)
                                    peer["catalog_fetched_at"] = landing_time
                                    peer["catalog_url"] = model["url"]
                                    models.append(peer)
                        specs_url = model.get("specs_url")
                        if not specs_url:
                            links = _specification_links(soup, model["url"], brand)
                            if not links:
                                raise ValueError("产品页没有公开规格链接：" + model["url"])
                            specs_url = links[0]
                        specs_html, specs_time = pages.get(specs_url)
                        raws = parse_specifications(specs_html, specs_url, brand, fetched_at=specs_time,
                                                    catalog_url=model["catalog_url"], model=model)
                        # The link alone proves current catalogue membership; a
                        # launch/preorder link does not prove that sales began.
                        sale_text = _text(soup.select_one("main") or soup)
                        for raw in raws:
                            future = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日.{0,12}(?:发售|开售)", sale_text)
                            partial_launch = re.search(r"\d{1,2}\s*月\s*\d{1,2}\s*日.{0,12}(?:发售|开售)", sale_text)
                            if future:
                                date_text = "-".join([future.group(1), future.group(2).zfill(2), future.group(3).zfill(2)])
                                raw["specs"]["上市日期"] = date_text
                                raw["release_source_url"], raw["release_fetched_at"] = model["url"], landing_time
                                raw["availability"] = "unknown" if date_text > _today_cn() else "listed"
                            elif partial_launch:
                                # Do not invent a year from the current clock or
                                # footer. The incomplete launch text stays raw.
                                raw["specs"]["官网发售信息"] = partial_launch.group(0)
                            elif raw["specs"].get("上市日期") or "立即购买" in sale_text or "购买" in sale_text:
                                raw["availability"] = "listed"
                        report["raws"].extend(raws)
                        model["record_ids"] = [raw["id"] for raw in raws]
                        model["specs_url"] = specs_url
                        coverage["collected"] += 1
                        coverage["records"] += len(raws)
                    except (httpx.HTTPError, ValueError) as exc:
                        error = {"brand": brand, "url": model["url"], "message": str(exc)}
                        report["errors"].append(error)
                        coverage["errors"].append(error)
                coverage["discovered"], coverage["pending"] = len(models), max(0, len(models) - index)
                coverage["next_offset"] = index if coverage["pending"] else None
                coverage["models"] = [{key: model.get(key) for key in ("url", "name", "new_from_source", "source_position", "record_ids", "specs_url")}
                                      for model in models]
                report["discovered"] += len(models)
            except (httpx.HTTPError, ValueError) as exc:
                error = {"brand": brand, "url": catalog, "message": str(exc)}
                report["errors"].append(error)
                coverage["errors"].append(error)
    finally:
        pages.client.close()
    # Stable namespaced IDs leave ZOL variants and the recovered source intact.
    report["raws"] = list({raw["id"]: raw for raw in report["raws"]}.values())
    report["models_discovered"] = report["discovered"]
    report["records_discovered"] = len(report["raws"])
    if storage is not None and report["raws"]:
        storage.import_many(report["raws"])
        report["imported"] = len(report["raws"])
    (cache_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
