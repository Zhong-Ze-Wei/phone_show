"""Deterministic phone normalization; unknown or invalid facts stay unknown."""

from datetime import datetime, timezone
import json
import re
import unicodedata


CLEANING_VERSION = "2"
_BRANDS = {
    "xiaomi": "小米", "小米": "小米", "redmi": "红米", "红米": "红米",
    "huawei": "华为", "华为": "华为", "honor": "荣耀", "荣耀": "荣耀",
    "oppo": "OPPO", "vivo": "vivo", "iqoo": "iQOO", "oneplus": "一加", "一加": "一加",
    "realme": "realme", "真我": "realme", "apple": "苹果", "iphone": "苹果", "苹果": "苹果",
    "samsung": "三星", "三星": "三星", "motorola": "摩托罗拉", "moto": "摩托罗拉", "摩托罗拉": "摩托罗拉",
    "google": "谷歌", "谷歌": "谷歌", "sony": "索尼", "索尼": "索尼",
    "meizu": "魅族", "魅族": "魅族", "nokia": "诺基亚", "诺基亚": "诺基亚",
    "philips": "飞利浦", "飞利浦": "飞利浦", "lenovo": "联想", "联想": "联想",
    "zte": "中兴", "中兴": "中兴", "asus": "华硕", "华硕": "华硕",
    "nubia": "努比亚", "努比亚": "努比亚", "红魔": "红魔", "rog": "ROG",
    "vertu": "VERTU", "8848": "8848", "htc": "HTC", "lg": "LG",
}
_UNKNOWN = re.compile(r"^(?:暂无(?:报价|参数|信息)?|未知|不详|待定|待公布|未公布|n/?a|null|none|[-—–]+)$", re.I)


def _issue(issues: list, field: str, code: str, message: str, severity: str = "warning") -> None:
    issues.append({"field": field, "code": code, "severity": severity, "message": message})


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = unicodedata.normalize("NFKC", str(value)).strip()
    return None if not text or _UNKNOWN.fullmatch(text) else text


def normalize_brand(value: object, name: str = "") -> str | None:
    brand = _text(value)
    if brand:
        brand = re.sub(r"(?:手机|品牌)$", "", brand).strip()
        return _BRANDS.get(brand.casefold(), brand)
    for alias in sorted(_BRANDS, key=len, reverse=True):
        if name.casefold().startswith(alias):
            return _BRANDS[alias]
    return None


def family_key(name: str, brand: str | None) -> str:
    model = unicodedata.normalize("NFKC", name).casefold()
    model = re.sub(r"\([^)]*(?:\d\s*(?:gb|tb|mb)|全网通)[^)]*\)", "", model)
    model = re.sub(r"\s+\d+\s*(?:gb|tb|mb)(?:\s*[+/]\s*\d+\s*(?:gb|tb|mb))?\s*$", "", model)
    if brand == "苹果":
        model = re.sub(r"^(?:苹果\s*)?(?:apple\s*)?iphone\s*", "", model)
    else:
        for alias in sorted(_BRANDS, key=len, reverse=True):
            if _BRANDS[alias] == brand and model.startswith(alias):
                model = model[len(alias):]
                break
    return f"{(brand or 'unknown').casefold()}:{re.sub(r'\s+', '', model)}"


def _spec(specs: dict, *keys: str) -> tuple[object, str]:
    for key in keys:
        if key in specs and _text(specs[key]) is not None:
            return specs[key], key
    return None, ""


def _quantity(value: object, field: str, units: dict, default_unit: str | None,
              bounds: tuple[float, float], issues: list) -> float | None:
    text = _text(value)
    if text is None:
        return None
    text = re.sub(r"(?<=\d),(?=\d{3}(?:\D|$))", "", text)
    unit_pattern = "|".join(re.escape(unit) for unit in sorted(units, key=len, reverse=True))
    matches = list(re.finditer(rf"([-+]?\d+(?:\.\d+)?)\s*({unit_pattern})", text, re.I))
    values = [float(match.group(1)) * units[match.group(2).casefold()] for match in matches]
    if field in {"price", "price_from"} and not values:
        values = [float(number) * {"万": 10000, "千": 1000, "": 1}[multiplier]
            for number, multiplier in re.findall(r"(?:[¥￥]|人民币|rmb|cny)\s*(\d+(?:\.\d+)?)\s*(万|千)?", text, re.I)]
    abbreviated_range = re.search(r"(\d+(?:\.\d+)?)\s*[/~至-]\s*(\d+(?:\.\d+)?)", text)
    if abbreviated_range and abbreviated_range.group(1) != abbreviated_range.group(2):
        _issue(issues, field, "ambiguous_quantity", f"存在范围/多个配置，未选取其中一个：{text}")
        return None
    if not values and default_unit and re.fullmatch(r"[-+]?\d+(?:\.\d+)?", text):
        values = [float(text) * units[default_unit]]
    if not values:
        _issue(issues, field, "unparsed_quantity", f"缺少可核实的数字/单位：{text}")
        return None
    unique = set(values)
    if len(unique) > 1:
        typical = [values[index] for index, match in enumerate(matches) if "典型" in text[match.end():match.end() + 12]]
        if len(typical) == 1:
            unique = set(typical)
        else:
            _issue(issues, field, "ambiguous_quantity", f"多个不同数值，未猜测配置：{text}")
            return None
    number = unique.pop()
    if not bounds[0] <= number <= bounds[1]:
        _issue(issues, field, "out_of_range", f"数值 {number:g} 超出核验范围 {bounds}；原文：{text}", "error")
        return None
    return number


def _boolean(value: object, feature: str | None = None) -> bool | None:
    text = _text(value)
    if text is None:
        return None
    negative = r"不支持|不具备|没有|未配备|无此|不带"
    denied = re.search(rf"(?:{negative})\s*(?:{feature})", text, re.I) if feature else re.search(negative, text, re.I)
    if denied or text.casefold() in {"不支持", "否", "无", "0", "false", "no"}:
        return False
    if text.casefold() in {"是", "1", "true", "yes"}:
        return True
    if feature and re.search(feature, text, re.I):
        return True
    if feature is None and re.search(r"支持|具备|内置", text):
        return True
    return None


def _release(value: object, issues: list) -> tuple[str | None, int | None]:
    text = _text(value)
    if text is None:
        return None, None
    match = re.search(r"(20\d{2})(?:年|[-/.])(\d{1,2})(?:月|[-/.])(\d{1,2})", text)
    if match:
        try:
            date = datetime(*map(int, match.groups())).date()
        except ValueError:
            _issue(issues, "release_date", "invalid_date", f"无效发布日期：{text}")
            return None, int(match.group(1))
        return date.isoformat(), date.year
    year = re.search(r"(?<!\d)(20\d{2})(?!\d)", text)
    return None, int(year.group(1)) if year else None


def _fetched_at(value: object, issues: list) -> str | None:
    text = _text(value)
    if text is None:
        return None
    try:
        timestamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        _issue(issues, "fetched_at", "invalid_timestamp", f"无效抓取时间：{text}")
        return None
    if timestamp.tzinfo is None:
        _issue(issues, "fetched_at", "missing_timezone", "抓取时间缺少时区，未猜测UTC。")
        return None
    return timestamp.astimezone(timezone.utc).isoformat()


def _release_month(value: object) -> int | None:
    text = _text(value)
    match = re.search(r"20\d{2}(?:年|[-/.])(\d{1,2})(?:月|[-/.]|$)", text or "")
    month = int(match.group(1)) if match else None
    return month if month is not None and 1 <= month <= 12 else None


def _camera(specs: dict, issues: list) -> float | None:
    value, key = _spec(specs, "主摄像素", "后置主摄像素", "摄像头系统详情", "像素", "摄像头像素")
    text = _text(value)
    if text is None:
        return None
    if key == "摄像头系统详情" and text.startswith("["):
        try:
            cameras = json.loads(text)
        except json.JSONDecodeError:
            _issue(issues, "camera_mp", "invalid_camera_json", "旧摄像头JSON无法解析。")
            return None
        if not isinstance(cameras, list) or any(not isinstance(camera, dict) for camera in cameras):
            _issue(issues, "camera_mp", "invalid_camera_json", "旧摄像头JSON应为对象列表。")
            return None
        rear = [camera for camera in cameras if camera.get("type") == "后置"]
        primary = next((camera for camera in rear if "主摄" in camera.get("tags", [])), rear[0] if rear else None)
        text = primary.get("pixels") if primary else None
    elif key in {"像素", "摄像头像素"}:
        rear = re.search(r"后置(?:主摄|摄像头)1?\s*[:：]\s*([\d.]+\s*(?:万像素|万|mp|百万像素|像素))", text, re.I)
        if not rear:
            _issue(issues, "camera_mp", "ambiguous_camera", "未找到可区分的后置主摄/首个后置像素。")
            return None
        text = rear.group(1)
    return _quantity(text, "camera_mp", {"万像素": 0.01, "万": 0.01, "mp": 1, "百万像素": 1, "像素": 0.000001}, None, (0.01, 1000), issues)


def clean_phone(raw: dict) -> dict:
    if raw.get("id") is None or not str(raw["id"]).strip():
        raise ValueError("手机原始记录必须有非空 id。")
    issues = []
    specs = dict(raw.get("specs") or {})
    name = _text(raw.get("name")) or ""
    brand = normalize_brand(raw.get("brand"), name)
    origin = raw.get("origin", "zol")
    fetched_at = _fetched_at(raw.get("fetched_at"), issues)
    if not brand:
        _issue(issues, "brand", "unknown_brand", "无法从来源明确品牌。", "info")
    if origin == "legacy":
        _issue(issues, "fetched_at", "legacy_snapshot", "历史Excel没有逐条抓取时间；旧价格未经实时核验。", "info")
    price = _quantity(raw.get("price"), "price", {"万元": 10000, "千元": 1000, "元": 1, "人民币": 1, "rmb": 1, "cny": 1}, "元", (0.01, 5000000), issues)
    if price is None:
        _issue(issues, "price", "missing_price", "参考价未知，未用电商报价或模型猜测补齐。", "info")
    elif brand not in {"VERTU", "8848"} and price > 30000:
        _issue(issues, "price", "price_outlier", f"大众品牌参考价 {price:g} 元超过30000核验阈值；暂隔离待回源核验。", "error")
        price = None
    output = {
        "id": str(raw["id"]).strip(), "name": name, "brand": brand,
        "family_key": family_key(name, brand), "price": price,
        "image_url": _text(raw.get("image_url")), "source_url": _text(raw.get("source_url")),
        "image_role": _text(raw.get("image_role")),
        "image_width": raw.get("image_width"), "image_height": raw.get("image_height"),
        "image_source_url": _text(raw.get("image_source_url")),
        "image_fetched_at": _fetched_at(raw.get("image_fetched_at"), issues),
        "price_source_url": _text(raw.get("price_source_url")),
        "specs_source_url": _text(raw.get("specs_source_url")),
        "fetched_at": fetched_at, "availability": raw.get("availability", "unknown"),
        "specs_fetched_at": _fetched_at(raw.get("specs_fetched_at"), issues) if "specs_fetched_at" in raw else fetched_at,
        "price_fetched_at": _fetched_at(raw.get("price_fetched_at"), issues) if "price_fetched_at" in raw else (None if raw.get("price_source_url") else fetched_at),
        "_corrects_fetched_at": raw.get("_corrects_fetched_at"),
        "origin": origin, "specs": specs, "cleaning_version": CLEANING_VERSION,
        "legacy_source": raw.get("legacy_source"),
        "platform": _text(raw.get("platform")),
        "current_source": raw.get("current_source") is True,
        "source_position": raw.get("source_position"),
        "discovered_at": _fetched_at(raw.get("discovered_at"), issues),
        "catalog_fetched_at": _fetched_at(raw.get("catalog_fetched_at"), issues),
        "new_from_source": raw.get("new_from_source") is True,
        "new_release_catalog_url": _text(raw.get("new_release_catalog_url")),
        "release_source_url": _text(raw.get("release_source_url")),
        "release_fetched_at": _fetched_at(raw.get("release_fetched_at"), issues),
        "price_kind": _text(raw.get("price_kind")),
        "price_from": _quantity(raw.get("price_from"), "price_from", {"万元": 10000, "万": 10000, "元": 1}, "元", (0.01, 5_000_000), issues),
    }
    fields = {
        "ram_gb": (("运行内存RAM容量(GB)", "RAM容量"), {"tb": 1024, "gb": 1, "mb": 1 / 1024, "kb": 1 / 1048576}, "gb", (0.000001, 64)),
        "storage_gb": (("机身存储ROM容量(GB)", "ROM容量", "存储容量"), {"tb": 1024, "gb": 1, "mb": 1 / 1024, "kb": 1 / 1048576}, "gb", (0.000001, 8192)),
        "battery_mah": (("电池容量(mAh)", "电池容量"), {"mah": 1, "ah": 1000}, "mah", (100, 50000)),
        "charging_w": (("有线充电功率(W)", "有线充电"), {"w": 1, "瓦": 1}, "w", (0.1, 500)),
        "display_inches": (("主屏幕尺寸(英寸)", "屏幕尺寸"), {"英寸": 1, "inch": 1, "inches": 1, '"': 1}, "英寸", (0.5, 15)),
        "refresh_hz": (("主屏幕刷新率(Hz)", "屏幕刷新率", "刷新率"), {"hz": 1, "赫兹": 1}, "hz", (1, 360)),
        "weight_g": (("机身重量(克)", "重量"), {"kg": 1000, "g": 1, "克": 1}, "g", (10, 1500)),
        "thickness_mm": (("机身厚度(毫米)", "厚度"), {"mm": 1, "毫米": 1, "cm": 10, "厘米": 10}, "mm", (1, 50)),
    }
    for field, (keys, units, default, bounds) in fields.items():
        value, key = _spec(specs, *keys)
        text = _text(value) or ""
        if field == "display_inches":
            main = re.search(r"(?:主(?:屏)?|内屏)\s*[:：]\s*(\d+(?:\.\d+)?\s*英寸)", text)
            if main:
                value = main.group(1)
        if field == "refresh_hz":
            maximum = re.match(r"\s*(\d+(?:\.\d+)?\s*Hz)", text, re.I)
            adaptive = re.fullmatch(r"\s*\d+(?:\.\d+)?\s*[-~–至]\s*(\d+(?:\.\d+)?)\s*Hz\s*", text, re.I)
            if maximum and re.search(r"\([^)]*\d+\s*[-~–至]\s*\d+[^)]*\)", text):
                value = maximum.group(1)
            elif adaptive:
                value = adaptive.group(1) + "Hz"
        output[field] = _quantity(value, field, units, default if "(" in key else None, bounds, issues)
    output["camera_mp"] = _camera(specs, issues)
    soc, _ = _spec(specs, "CPU型号", "处理器", "芯片型号")
    output["soc"] = re.split(r"更多|手机性能排行|查看", _text(soc))[0].strip() if _text(soc) else None
    operating_system, _ = _spec(specs, "操作系统名称", "操作系统")
    output["os"] = _text(operating_system)
    os_text = output["os"] or ""
    output["os_family"] = (
        "HarmonyOS" if re.search(r"harmony|鸿蒙", os_text, re.I)
        else "Android" if re.search(r"android|安卓", os_text, re.I)
        else "iOS" if re.search(r"\bios\b", os_text, re.I)
        else "other" if os_text else None
    )
    release, _ = _spec(specs, "完整发布日期", "上市日期", "国内发布时间", "国外发布时间", "发布年份")
    output["release_date"], output["release_year"] = _release(release, issues)
    output["release_month"] = _release_month(release)
    output["release_precision"] = "day" if output["release_date"] else "month" if output["release_month"] else "year" if output["release_year"] else None
    nfc, _ = _spec(specs, "NFC", "是否支持NFC")
    if origin == "legacy" and _text(nfc) in {"0", "1", "False", "True"}:
        output["nfc"] = None
        _issue(issues, "nfc", "legacy_boolean_unverified", "旧布尔清洗合并了未知/否定，保留原值待原文核验。")
    else:
        output["nfc"] = _boolean(nfc)
    network, _ = _spec(specs, "网络类型支持", "网络类型", "5G")
    output["five_g"] = _boolean(network, r"5\s*g")
    waterproof, _ = _spec(specs, "三防功能(防水等级)", "三防功能", "防水防尘", "防水等级")
    output["waterproof"] = _text(waterproof)
    quality_fields = ("name", "brand", "price", "ram_gb", "storage_gb", "soc", "battery_mah", "charging_w", "camera_mp", "display_inches", "refresh_hz", "weight_g", "thickness_mm", "release_date", "os", "nfc", "five_g", "source_url")
    completeness = 100 * sum(output[field] is not None and output[field] != "" for field in quality_fields) / len(quality_fields)
    output["quality_score"] = max(0, round(completeness - 4 * sum(issue["severity"] == "error" for issue in issues), 1))
    output["issues"] = issues
    return output
