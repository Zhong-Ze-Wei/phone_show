"""中关村在线公开手机页面采集；校验页面，不绕过验证。"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .images import image_record, zol_primary_image

BASE_URL = "https://detail.zol.com.cn"
LIST_URL = BASE_URL + "/cell_phone_index/subcate57_list_1.html"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def cached_metadata(directory: Path, url: str) -> dict:
    """读取保存响应的来源与时间；缺失元数据不能推断为今天获取。"""
    key = hashlib.sha256(url.encode()).hexdigest()[:20]
    path = Path(directory) / f"{key}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


class PageValidationError(ValueError):
    """页面不是预期公开产品页面，例如验证页或结构已改变。"""


@dataclass
class ListingPage:
    phones: list[dict]
    page_urls: list[str]
    total: int | None
    layout: str
    sort_urls: list[str] = field(default_factory=list)
    variant_urls: list[str] = field(default_factory=list)


@dataclass
class DiscoveryPage:
    phones: list[dict]
    brands: dict[str, str]
    directory_url: str | None
    module_found: bool
    main_count: int


def _soup(html: str, *, brand_directory: bool = False) -> BeautifulSoup:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    refresh = soup.find("meta", attrs={"http-equiv": re.compile("refresh", re.I)})
    if refresh and "checking" in refresh.get("content", ""):
        raise PageValidationError("源站返回访问验证页，停止此URL；需要正常浏览器验证后恢复")
    if len(html) < 500 or not title or re.search(
        r"访问验证|访问异常|验证码|Access Denied|Bad Gateway|Forbidden|验证中心|人机验证", title, re.I
    ):
        raise PageValidationError(f"非有效产品页面：{title or '缺少标题/响应过短'}")
    if "中关村在线" not in title and "ZOL" not in title and not (brand_directory and "手机品牌大全" in title):
        raise PageValidationError(f"页面来源标识不符合预期：{title}")
    return soup


def _image(node, base_url: str) -> str | None:
    image = node.select_one("img")
    if image is None:
        return None
    for attr in ("data-original", "data-src", ".src", "src"):
        value = image.get(attr)
        if value and not value.startswith("data:"):
            return urljoin(base_url, value)
    return None


def _reference_price(node) -> str | None:
    price = node.select_one(".price-normal, .price-stop, .price-type")
    if price is None:
        price = node.select_one(".price-box .price, .price-row .price, td.cell-2 .price")
    return (price.get_text(" ", strip=True) or None) if price else None


def _product_id(href: str) -> str | None:
    match = re.search(r"(?:index|/)(\d+)(?:\.shtml|/param\.shtml)", href)
    return match.group(1) if match else None


def _pagination(soup: BeautifulSoup, page_url: str, *, series: bool = False) -> list[str]:
    current_path = urlparse(page_url).path
    if series:
        match = re.search(r"/series/57/(\d+)_", current_path)
        pattern = rf"/series/57/{match.group(1)}_\d+\.html" if match else r"(?!)"
    else:
        pattern = r"/cell_phone_index/subcate57(?:_[a-zA-Z0-9]+)+_\d+\.html"
    urls = {page_url}
    for link in soup.select(".pagebar a[href], .page-box a[href], .pagination a[href], .page a[href]"):
        url = urljoin(page_url, link["href"])
        if re.fullmatch(pattern, urlparse(url).path):
            urls.add(url)
    active = soup.select_one(".small-page-active")
    if active and not series:
        match = re.search(r"/\s*(\d+)", active.get_text())
        if match:
            count = int(match.group(1))
            if count > 500:
                raise PageValidationError("列表页数异常，拒绝无边界抓取")
            template_path = next(
                (urlparse(url).path for url in sorted(urls) if url != page_url), current_path
            )
            for page in range(1, count + 1):
                if re.search(r"_\d+\.html$", template_path):
                    urls.add(urljoin(page_url, re.sub(r"_\d+\.html$", f"_{page}.html", template_path)))
    return sorted(urls)


def parse_listing(html: str, page_url: str = LIST_URL) -> ListingPage:
    soup = _soup(html)
    nodes = soup.select("div.list-item[data-follow-id]")
    layout = "list"
    if not nodes:
        nodes = soup.select(".pic-mode-box li[data-follow-id], .list-box li[data-follow-id]")
        layout = "grid"
    if not nodes:
        raise PageValidationError("列表页面没有可识别的手机条目，不能当作正常空页")
    phones = []
    for node in nodes:
        link = node.select_one("h3 a[href]")
        identifier = node.get("data-follow-id", "").removeprefix("p")
        if link is None or not identifier.isdigit():
            raise PageValidationError("列表条目缺少产品名称或有效产品ID")
        name = " ".join(link.find_all(string=True, recursive=False)).strip()
        if not name:
            name = link.get_text(" ", strip=True)
        param = node.select_one('a[href*="/param.shtml"]')
        specs = {}
        for item in node.select("ul.param li"):
            label = item.select_one("span")
            value = item.get("title")
            if label and value:
                key = label.get_text(strip=True).rstrip("：:")
                if key:
                    specs[key] = value.strip()
        price = _reference_price(node)
        phones.append({
            "id": identifier, "name": name, "brand": None,
            "price": price, "image_url": _image(node, page_url),
            "image_role": "thumbnail", "image_source_url": page_url,
            "source_url": urljoin(page_url, link["href"]),
            "price_source_url": page_url,
            "param_url": urljoin(page_url, param["href"]) if param else None,
            "availability": "historical" if price and "停产" in price else "listed",
            "specs": specs, "origin": "zol",
        })
    total_tag = soup.select_one(".total")
    total_match = re.search(r"([\d,]+)\s*款", total_tag.get_text()) if total_tag else None
    total = int(total_match.group(1).replace(",", "")) if total_match else None
    sort_urls = []
    for link in soup.find_all("a", href=True):
        if link.get_text(strip=True) == "时间":
            url = urljoin(page_url, link["href"])
            if urlparse(url).hostname == "detail.zol.com.cn" and "/cell_phone_index/" in url:
                sort_urls.append(url)
    return ListingPage(phones, _pagination(soup, page_url), total, layout, sort_urls)


def _brand_name(text: str) -> str:
    text = re.sub(r"手机$", "", text.strip()).strip()
    translated = re.search(r"[（(]([^()（）]+)[）)]", text)
    return translated.group(1) if translated else text


def parse_brand_directory(html: str, page_url: str) -> dict[str, str]:
    soup = _soup(html, brand_directory=True)
    brands = {}
    for link in soup.select(".manu.normal a[href]"):
        url = urljoin(page_url, link["href"])
        if urlparse(url).hostname == "detail.zol.com.cn" and re.fullmatch(r"/cell_phone_index/subcate57_\d+_list_1\.html", urlparse(url).path):
            name = _brand_name(link.get_text(" ", strip=True))
            if name:
                brands[name] = url
    if not brands:
        raise PageValidationError("品牌目录没有可验证的普通品牌页面链接")
    return brands


def parse_discovery(html: str, page_url: str = LIST_URL) -> DiscoveryPage:
    """独立读取标题明确的手机新品模块，避免把热门/推广列表当作新品。"""
    soup = _soup(html)
    brands = {}
    directory = None
    for section in soup.select(".section"):
        heading = section.select_one(".section-header h3")
        if heading is None or heading.get_text(strip=True) != "手机品牌报价大全":
            continue
        for link in section.select("a[href]"):
            url = urljoin(page_url, link["href"])
            if urlparse(url).hostname != "detail.zol.com.cn":
                continue
            if urlparse(url).path == "/category/57.html":
                directory = url
            elif re.fullmatch(r"/cell_phone_index/subcate57_\d+_list_1\.html", urlparse(url).path):
                name = _brand_name(link.get_text(" ", strip=True))
                if name:
                    brands[name] = url
    phones = {}
    found = False
    for module in soup.select(".module"):
        heading = module.select_one(".module-header h3")
        if heading is None or not re.fullmatch(r".*手机新品", heading.get_text(strip=True)):
            continue
        found = True
        brand = heading.get_text(strip=True).removesuffix("手机新品") or None
        for position, node in enumerate(module.select("ul.rank-list > li"), 1):
            link = node.select_one('a[title][href*="/cell_phone/index"]')
            if link is None:
                raise PageValidationError("新品模块条目缺少真实产品链接或完整名称")
            url = urljoin(page_url, link["href"])
            identifier = _product_id(url)
            if identifier is None or urlparse(url).hostname != "detail.zol.com.cn":
                raise PageValidationError("新品模块条目产品身份无效")
            price = node.select_one(".price")
            phones[identifier] = {
                "id": identifier, "name": link["title"], "brand": brand,
                "price": price.get_text("", strip=True) or None if price else None,
                "price_source_url": page_url, "image_url": _image(node, page_url),
                "image_role": "thumbnail", "image_source_url": page_url,
                "source_url": url, "param_url": None, "specs": {}, "origin": "zol",
                "availability": "unknown", "new_from_source": True,
                "new_release_catalog_url": page_url, "source_position": position,
                "current_source": "zol_new_release_module",
            }
    main_count = len(soup.select("div.list-item[data-follow-id], .pic-mode-box li[data-follow-id], .list-box li[data-follow-id]"))
    return DiscoveryPage(list(phones.values()), brands, directory, found, main_count)


def parse_product(html: str, product_url: str) -> dict:
    soup = _soup(html)
    if soup.select_one('.product-nav, .product-model, .product-price, #product_series_link, .goods-card') is None:
        # 产品首页布局常有独立的参数链接和明确产品标题。
        if soup.select_one('a[href*="/param.shtml"]') is None:
            raise PageValidationError("产品首页缺少产品导航或参数链接")
    identifier = _product_id(product_url)
    param = next((a for a in soup.select('a[href*="/param.shtml"]') if _product_id(a["href"]) == identifier), None)
    series = soup.select_one("#product_series_link[href]")
    return {
        "param_url": urljoin(product_url, param["href"]) if param else None,
        "series_url": urljoin(product_url, series["href"]) if series else None,
        "price": _reference_price(soup),
        **zol_primary_image(soup, product_url),
    }


def parse_series(html: str, series_url: str) -> ListingPage:
    soup = _soup(html)
    rows = soup.select("tr.model__item")
    if not rows:
        raise PageValidationError("系列页没有可识别的型号行")
    phones = []
    for row in rows:  # 包含所有 model_page_N，不能只读第一页CSS类。
        link = row.select_one('td.cell-7 a[href*="index"]')
        param = row.select_one('a[href*="/param.shtml"]')
        if link is None:
            raise PageValidationError("系列型号行缺少产品链接")
        identifier = _product_id(link["href"])
        if identifier is None:
            raise PageValidationError("系列型号行没有有效产品ID")
        compare = row.select_one("a[data-compare]")
        image_url = None
        if compare:
            parts = compare["data-compare"].split(",")
            if len(parts) > 3:
                image_url = urljoin(series_url, parts[3])
        row_image = image_record(row.select_one(".cell-1 img"), series_url, "catalog")
        row_text = row.get_text(" ", strip=True)
        availability = "historical" if "停产" in row_text else "listed" if "在售" in row_text else "unknown"
        phones.append({
            "id": identifier, "name": link.get("title") or link.get_text(" ", strip=True),
            "brand": None, "price": _reference_price(row), "image_url": image_url, "image_role": "thumbnail",
            "image_source_url": series_url,
            **row_image,
            "source_url": urljoin(series_url, link["href"]), "price_source_url": series_url,
            "param_url": urljoin(series_url, param["href"]) if param else None,
            "series_url": series_url, "availability": availability, "specs": {}, "origin": "zol",
        })
    text = soup.get_text(" ", strip=True)
    count = re.search(r"共有\s*(\d+)\s*款产品", text)
    variants = [urljoin(series_url, a["href"]) for a in soup.select('a.total[href*="/param_"]')]
    return ListingPage(phones, _pagination(soup, series_url, series=True), int(count.group(1)) if count else None, "series", variant_urls=variants)


def parse_series_parameters(html: str, page_url: str) -> ListingPage:
    """公开系列参数对比表按真实型号列采集，不从相关产品或导航猜型号。"""
    soup = _soup(html)
    tables = [t for t in soup.select("table.series_param_detail") if t.select_one("td.pro_name")]
    if not tables:
        raise PageValidationError("系列参数页缺少带型号列的对比表")
    table = max(tables, key=lambda node: len(node.select("tr")))
    model_row = table.select_one("tr:has(td.pro_name)")
    columns = model_row.find_all("td", recursive=False)
    phones = []
    brand = None
    for link in soup.select('.breadcrumb a[href], .location a[href], .bread-crumb a[href]'):
        if re.search(r"subcate57_\d+_list_\d+\.html", link["href"]):
            brand = re.sub(r"手机$", "", link.get_text(strip=True))
    for cell in columns:
        link = cell.select_one('a[href*="cell_phone/index"]')
        identifier = _product_id(link["href"]) if link else None
        if identifier is None:
            raise PageValidationError("系列参数表型号列缺少有效产品身份")
        phones.append({"id": identifier, "name": link.get_text(" ", strip=True), "brand": brand,
            "price": None, "price_source_url": page_url, "image_url": None,
            "source_url": urljoin(page_url, link["href"]), "specs_source_url": page_url,
            "availability": "unknown", "specs": {}, "origin": "zol"})
    if len({raw["id"] for raw in phones}) != len(phones):
        raise PageValidationError("系列参数表重复型号列，无法确定参数对应关系")
    for row in table.select("tr"):
        label = row.find("th", recursive=False)
        cells = row.find_all("td", recursive=False)
        if not cells or row is model_row:
            continue
        key = label.get_text(" ", strip=True) if label else None
        if not key:
            continue  # 源站偶有空标签行，无法赋予真实参数名称。
        if len(cells) != len(phones) or any(int(cell.get("colspan", 1)) != 1 for cell in cells):
            raise PageValidationError("系列参数行与型号列宽不一致，拒绝错位发布")
        for raw, cell in zip(phones, cells):
            for edit in cell.select(".edit-param"):
                edit.decompose()
            value = cell.get_text(" ", strip=True)
            if key == "图片":
                raw.update(image_record(cell.select_one("img"), page_url, "thumbnail"))
            elif key == "价格/商家":
                price = cell.select_one(".price_td .price")
                raw["price"] = price.get_text("", strip=True) or None if price else None
                raw["availability"] = "historical" if "停产" in value else "listed" if "在售" in value else "unknown"
                published = cell.select_one(".date")
                if published:
                    raw["specs"]["参考价更新日期"] = published.get_text(strip=True)
            elif value:
                raw["specs"][key] = value
    if any(len(raw["specs"]) < 5 for raw in phones):
        raise PageValidationError("系列参数表有型号不足五项有效参数")
    match = re.search(r"/param_(\d+)_", page_url)
    page_urls = {page_url}
    if match:
        for link in soup.select(".pagebar a[href], .page-box a[href], .pagination a[href]"):
            url = urljoin(page_url, link["href"])
            if re.search(rf"/param_{match.group(1)}_\d+_\d+\.html$", urlparse(url).path):
                page_urls.add(url)
    return ListingPage(phones, sorted(page_urls), None, "comparison")


def parse_parameters(html: str, param_url: str) -> dict:
    soup = _soup(html)
    container = soup.select_one(".detailed-parameters")
    if container is None:
        raise PageValidationError("参数页缺少详细参数容器")
    specs = {}
    for row in container.select("tr"):
        label, value = row.find("th"), row.find("td")
        if label is None or value is None or "hd" in value.get("class", []):
            continue
        for edit in value.select(".edit-param"):
            edit.decompose()
        key, text = label.get_text(" ", strip=True), value.get_text(" ", strip=True)
        if key and text:
            specs[key] = text
    if len(specs) < 5:
        raise PageValidationError(f"有效参数过少：仅 {len(specs)} 项，拒绝发布不完整详情")
    card = soup.select_one(".goods-card__title a")
    identifier = _product_id(param_url)
    if card and _product_id(card.get("href", "")) != identifier:
        raise PageValidationError("参数页面产品ID与请求不符")
    brand = None
    for link in soup.select(".breadcrumb a[href], .location a[href], .bread-crumb a[href]"):
        if re.search(r"subcate57_\d+_list_\d+\.html", link["href"]):
            brand = re.sub(r"手机$", "", link.get_text(strip=True))
    return {"specs": specs, "brand": brand, "name": card.get_text(" ", strip=True) if card else None,
        **zol_primary_image(soup, param_url)}


class ZolCrawler:
    """单源限速、有限重试与原始响应保存。"""

    def __init__(self, directory: Path, *, delay: float = 0.9, client: httpx.Client | None = None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.delay = max(0.8, delay)
        self.client = client or httpx.Client(timeout=30, follow_redirects=True, headers=HEADERS)
        self._owns_client = client is None
        self._last_request = 0.0
        self.requests = 0
        self.cache_hits = 0

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def metadata(self, url: str) -> dict:
        return cached_metadata(self.directory, url)

    def fetch(self, url: str, *, refresh: bool = False) -> str:
        if urlparse(url).hostname != "detail.zol.com.cn":
            raise PageValidationError("仅采集约定的 ZOL 公开源站")
        key = hashlib.sha256(url.encode()).hexdigest()[:20]
        path = self.directory / f"{key}.html"
        if path.exists() and not refresh:
            self.cache_hits += 1
            return path.read_text(encoding="utf-8")
        for attempt in range(3):
            time.sleep(max(0.0, self.delay - (time.monotonic() - self._last_request)))
            self._last_request = time.monotonic()
            self.requests += 1
            try:
                response = self.client.get(url)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                if attempt == 2 or status is not None and status not in {429, 500, 502, 503, 504}:
                    raise
                time.sleep(1.8 * (2 ** attempt))
                continue
            charset = response.charset_encoding or "gb18030"
            html = response.content.decode(charset, errors="replace")
            path.write_text(html, encoding="utf-8")
            (self.directory / f"{key}.json").write_text(json.dumps({
                "url": url, "response_url": str(response.url), "status": response.status_code,
                "fetched_at": utc_now(), "bytes": len(response.content), "encoding": charset,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            return html
        raise RuntimeError("重试流程未产生响应")
