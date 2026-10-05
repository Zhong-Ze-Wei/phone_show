"""可解释的规格匹配；分数不是跑分、成像测评或续航实测。"""

import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone

MARKET_TIMEZONE = timezone(timedelta(hours=8))

PRIORITIES = [
    {"id": "daily", "label": "日常好用"},
    {"id": "gaming", "label": "游戏性能"},
    {"id": "camera", "label": "拍照配置"},
    {"id": "battery", "label": "续航快充"},
]

# 采购偏好名单，不代表品质、售后或实测表现的结论。
MAINSTREAM_BRANDS = ("苹果", "三星", "华为", "荣耀", "小米", "红米", "OPPO", "vivo", "一加", "realme", "iQOO")


@dataclass
class Preferences:
    budget_min: float = 0
    budget_max: float | None = None
    brands: list[str] = field(default_factory=list)
    os: str = "all"
    priorities: list[str] = field(default_factory=lambda: ["daily"])
    compact: bool = False
    min_storage: float = 0
    include_history: bool = False
    query: str = ""
    sort: str = "recommended"
    purchase_mode: str = "new"


def fetched_days(phone: dict, now: datetime | None = None) -> int | None:
    stamp = phone.get("fetched_at")
    if not stamp:
        return None
    fetched = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    return max(0, ((now or datetime.now(timezone.utc)) - fetched).days)


def is_current(phone: dict) -> bool:
    days = fetched_days(phone)
    return phone.get("availability") == "listed" and days is not None and days <= 30


def release_sort_key(phone: dict) -> tuple[int, int, int]:
    """只用来源实际给出的上市年/月/日；缺失分量为排序占位，不伪造日期。"""
    release = phone.get("release_date")
    precision = phone.get("release_precision")
    if release and precision in (None, "day"):
        try:
            parsed = date.fromisoformat(release)
        except ValueError:
            pass
        else:
            return parsed.year, parsed.month, parsed.day
    year = phone.get("release_year")
    month = phone.get("release_month")
    return int(year or 0), int(month or 0), 0


def market_today() -> date:
    return datetime.now(MARKET_TIMEZONE).date()


def is_released(phone: dict, today: date | None = None) -> bool:
    """明确未来日期或仅公布但未上市的产品，不参与已上市推荐。"""
    if phone.get("availability") == "announced":
        return False
    year, month, day = release_sort_key(phone)
    today = today or market_today()
    if year > today.year:
        return False
    if year == today.year and month > today.month:
        return False
    return not (year == today.year and month == today.month and day > today.day)


def release_age_days(phone: dict, today: date | None = None) -> int | None:
    """部分上市日期按可能区间最早端计算年龄，只用于评分，不补写日期。"""
    year, month, day = release_sort_key(phone)
    if not year:
        return None
    precision = phone.get("release_precision")
    earliest = date(year, 1 if precision == "year" else month or 1, day or 1)
    return ((today or market_today()) - earliest).days


def ranking_weights(preferences: Preferences) -> dict[str, float]:
    if preferences.purchase_mode == "used":
        if preferences.budget_max is None:
            return {"usage": 0.95, "value": 0.0, "recency": 0.0, "brand": 0.05}
        return {"usage": 0.85, "value": 0.1, "recency": 0.0, "brand": 0.05}
    if preferences.budget_max is None:
        return {"usage": 0.85, "value": 0.0, "recency": 0.1, "brand": 0.05}
    return {"usage": 0.75, "value": 0.1, "recency": 0.1, "brand": 0.05}


def ranking_policy(preferences: Preferences) -> dict:
    return {
        "sort": preferences.sort,
        "purchase_mode": preferences.purchase_mode,
        "weights": ranking_weights(preferences),
        "mainstream_brands": list(MAINSTREAM_BRANDS),
        "value_basis": "未设置最高预算，预算余量权重转给需求匹配" if preferences.budget_max is None else "预算余量，依据来源参考报价，不是实测性价比",
        "recency_basis": "真实上市日期；月份或年份按区间最早端保守计算，未知不加分",
        "brand_basis": "主流品牌采购偏好，不证明品质或售后",
        "used_basis": "二手机型参考沿用已核验的新机参考报价，未接入二手价格、成色或库存",
    }


def _ranking_fields(phone: dict, preferences: Preferences, usage: int) -> dict:
    price = phone.get("price")
    price_usable = price is not None and (preferences.include_history or _price_is_current(phone))
    value = max(0.0, min(100.0, 100 * (1 - price / preferences.budget_max))) if price_usable and preferences.budget_max else 0.0
    age = release_age_days(phone)
    recency = 100 if age is not None and 0 <= age <= 365 else 50 if age is not None and 365 < age <= 730 else 0
    brand = 100 if str(phone.get("brand") or "").casefold() in {name.casefold() for name in MAINSTREAM_BRANDS} else 0
    weights = ranking_weights(preferences)
    scores = {"usage": usage, "value": round(value, 2), "recency": recency, "brand": brand}
    reasons = [f"需求匹配 {usage} 分，是推荐的主要依据"]
    if preferences.budget_max is None:
        reasons.append("未设置最高预算，预算余量权重转给需求匹配")
    elif price_usable:
        reasons.append(f"预算余量 {value:.1f} 分，依据来源参考报价")
    if preferences.purchase_mode == "used":
        reasons.append("二手机型参考不因上市较新加分；未接入二手价格、成色或库存")
    elif recency == 100:
        reasons.append("上市在近一年内，适度加分")
    elif recency == 50:
        reasons.append("上市在一至两年内，少量加分")
    elif age is None:
        reasons.append("上市时间未知，不获得时效加分")
    else:
        reasons.append("上市时效不加分，仍可凭用途匹配进入推荐")
    if brand:
        reasons.append("主流品牌采购偏好适度加分，不代表品质或售后结论")
    return {
        "recommendation_score": round(sum(scores[name] * weight for name, weight in weights.items()), 2),
        "ranking_breakdown": {**scores, "weights": weights},
        "ranking_reasons": reasons,
    }


def _recommendation_sort_key(phone: dict, preferences: Preferences) -> tuple:
    price = phone.get("price")
    price_key = (price is None, price if price is not None else 0)
    if preferences.sort == "newest":
        return *(-part for part in release_sort_key(phone)), -phone["score"], *price_key, phone["id"]
    if preferences.sort == "price_asc":
        return *price_key, -phone["score"], phone["id"]
    if preferences.sort == "price_desc":
        return price is None, -price if price is not None else 0, -phone["score"], phone["id"]
    if preferences.sort == "match":
        return -phone["score"], *price_key, phone["id"]
    return -phone["recommendation_score"], -phone["score"], *price_key, phone["id"]


def _matches_identity(phone: dict, preferences: Preferences, *, discovery: bool = False) -> bool:
    if preferences.brands and phone.get("brand") not in preferences.brands:
        return False
    os_family = phone.get("os_family") or (phone.get("os") or "").split(" ")[0]
    if preferences.os != "all" and not str(os_family).casefold().startswith(preferences.os.casefold()):
        if not discovery or os_family:
            return False
    query = re.sub(r"\s+", "", preferences.query).casefold()
    text = re.sub(r"\s+", "", phone["name"] + str(phone.get("soc") or "")).casefold()
    return not query or query in text


def _price_is_current(phone: dict) -> bool:
    source = phone.get("field_sources", {}).get("price", {})
    origin = source.get("origin", phone.get("origin"))
    days = fetched_days({"fetched_at": source.get("fetched_at") if source else phone.get("fetched_at")})
    return origin != "legacy" and days is not None and days <= 30


def _constraint_reasons(phone: dict, preferences: Preferences) -> list[tuple[str, str]]:
    reasons = []
    if not is_released(phone):
        reasons.append(("upcoming", "尚未上市或上市时间在未来"))
    price = phone.get("price")
    if price is None:
        reasons.append(("unknown_price", "价格待核实，不能用于当前购买推荐" if preferences.budget_max is None else "价格待核实，不能确认是否在预算内"))
    elif not preferences.include_history and not _price_is_current(phone):
        reasons.append(("stale_price", "参考报价未近期核验，不能用于当前购买推荐"))
    elif preferences.budget_max is not None and price > preferences.budget_max:
        reasons.append(("over_budget", f"参考价 ¥{price:g}，超过当前 ¥{preferences.budget_max:g} 预算"))
    elif price < preferences.budget_min:
        reasons.append(("under_budget", f"参考价 ¥{price:g}，低于当前预算下限"))
    storage = phone.get("storage_gb")
    if preferences.min_storage and storage is None:
        reasons.append(("unknown_storage", "容量待核实，不能确认是否符合存储要求"))
    elif preferences.min_storage and storage < preferences.min_storage:
        reasons.append(("insufficient_storage", f"存储 {storage:g}GB，低于所选 {preferences.min_storage:g}GB"))
    return reasons


def card_record(phone: dict) -> dict:
    """列表不重复运送参数原文；GET详情与对比保留完整字段来源。"""
    compact = {key: value for key, value in phone.items() if key not in ("specs", "specs_sources", "issues", "field_sources")}
    price_source = phone.get("field_sources", {}).get("price")
    compact["field_sources"] = {"price": price_source} if price_source else {}
    return compact


def is_purchase_candidate(phone: dict, preferences: Preferences) -> bool:
    """当前购买资格与历史探索分开；空预算也不放宽核价证据。"""
    return (_matches_identity(phone, preferences) and is_current(phone)
        and _price_is_current(phone) and not _constraint_reasons(phone, preferences))


def budget_warning(phone: dict, preferences: Preferences) -> str | None:
    if preferences.budget_max is None and not preferences.budget_min:
        return None
    price = phone.get("price")
    if price is None:
        return "价格未知，无法确认预算"
    if preferences.budget_max is not None and price > preferences.budget_max:
        return "超出当前预算范围"
    if price < preferences.budget_min:
        return "低于当前预算下限"
    if not _price_is_current(phone):
        return "参考报价未近期核验，不能确认当前预算"
    return None


def _variant_source_key(phone: dict, preferences: Preferences) -> tuple:
    current_quote = phone.get("price") is not None and _price_is_current(phone) and is_current(phone) and is_released(phone)
    days = fetched_days(phone)
    trusted = phone.get("origin") in ("zol", "official") and days is not None and days <= 30
    price = phone.get("price")
    return (not is_purchase_candidate(phone, preferences), not current_quote, not trusted,
        phone.get("origin") != "official", -phone.get("quality_score", 0), price is None,
        price if price is not None else 0, phone["id"])


def family_variants(members: list[dict], preferences: Preferences) -> list[dict]:
    """按真实 RAM/容量去重；有具体容量时，未指明容量的目录记录不算配置。"""
    specific = [phone for phone in members if phone.get("storage_gb") is not None]
    if not specific:
        return [min(members, key=lambda phone: _variant_source_key(phone, preferences))]
    known_ram = {phone["storage_gb"] for phone in specific if phone.get("ram_gb") is not None}
    groups: dict[tuple, list[dict]] = {}
    for phone in specific:
        if phone.get("ram_gb") is None and phone["storage_gb"] in known_ram:
            continue
        groups.setdefault((phone.get("ram_gb"), phone["storage_gb"]), []).append(phone)
    variants = [min(records, key=lambda phone: _variant_source_key(phone, preferences)) for records in groups.values()]
    return sorted(variants, key=lambda phone: (phone["storage_gb"], phone.get("ram_gb") is None,
        phone.get("ram_gb") or 0, phone["id"]))


def family_name(members: list[dict]) -> str:
    source = min(members, key=lambda phone: (phone.get("origin") != "official", phone.get("storage_gb") is not None,
        len(phone["name"]), phone["id"]))
    name = re.sub(r"\s*\([^)]*(?:\d\s*(?:GB|TB|MB)|全网通)[^)]*\)", "", source["name"], flags=re.I).strip()
    name = re.sub(r"\s+\d+\s*(?:GB|TB|MB)(?:\s*[+/]\s*\d+\s*(?:GB|TB|MB))?\s*$", "", name, flags=re.I)
    return re.sub(r"^苹果\s*", "", name) if source.get("brand") == "苹果" else name


def variant_record(phone: dict, preferences: Preferences) -> dict:
    """各配置独立重算匹配与警告，不借用代表版本的资格或价格。"""
    record = match_phone(phone, preferences)
    constraints = _constraint_reasons(phone, preferences)
    matches = _matches_identity(phone, preferences) and (preferences.include_history or is_current(phone)) and not constraints
    reasons = _catalogue_reasons(phone, preferences)
    reasons.extend(reason for reason in constraints if reason[0] not in {code for code, _ in reasons})
    if not _matches_identity(phone, preferences):
        reasons.append(("identity", "不符合当前品牌、系统或搜索条件，仅供配置比较"))
    return {**record, "budget_warning": budget_warning(phone, preferences), "matches_preferences": bool(matches),
        "recommendation_eligible": is_purchase_candidate(phone, preferences),
        "variant_codes": [code for code, _ in reasons], "variant_reasons": [message for _, message in reasons],
        "catalogue_codes": [code for code, _ in reasons], "catalogue_reasons": [message for _, message in reasons],
        "catalogue_status": reasons[0][0] if reasons else "current"}


def family_metadata(members: list[dict], preferences: Preferences) -> dict:
    variants = family_variants(members, preferences)
    keys = ("id", "name", "ram_gb", "storage_gb", "price", "source_url", "fetched_at", "price_source_url", "price_fetched_at",
        "budget_warning", "matches_preferences", "recommendation_eligible", "variant_codes", "variant_reasons")
    summary = []
    for phone in variants:
        record = variant_record(phone, preferences)
        summary.append({**{key: record.get(key) for key in keys}, "availability": phone.get("availability") or "unknown",
            "field_sources": {key: value for key, value in phone.get("field_sources", {}).items() if key in ("price", "ram_gb", "storage_gb")}})
    return {"family_name": family_name(members), "variant_count": len(variants), "variant_summary": summary}


def _catalogue_reasons(phone: dict, preferences: Preferences) -> list[tuple[str, str]]:
    reasons = []
    days = fetched_days(phone)
    if phone.get("origin") == "legacy" or phone.get("availability") == "historical":
        reasons.append(("history", "历史来源记录，型号、上市与现价未作本轮核验，不代表已正式上市或当前在售"))
    elif days is None or days > 30:
        reasons.append(("history", "资料较旧或采集时间未知，仅作目录浏览，购买前需重新核实"))
    if not is_released(phone):
        reasons.append(("upcoming", "尚未上市或上市时间在未来，只能查看已公布资料"))
    elif phone.get("availability") not in ("listed", "historical"):
        reasons.append(("availability_unknown", "上市或销售状态待核实，不能确认在售或库存"))
    price = phone.get("price")
    if price is None:
        reasons.append(("unknown_price", "参考报价待核实，不属于当前可核价推荐"))
    else:
        if not _price_is_current(phone):
            reasons.append(("stale_price", "历史或未近期核验的参考报价，购买前须重新核价"))
        if preferences.budget_max is not None and price > preferences.budget_max:
            reasons.append(("over_budget", f"参考价 ¥{price:g}，超过当前 ¥{preferences.budget_max:g} 预算"))
        elif price < preferences.budget_min:
            reasons.append(("under_budget", f"参考价 ¥{price:g}，低于当前预算下限"))
    return reasons


def _catalogue_variant_key(phone: dict, preferences: Preferences) -> tuple:
    if is_purchase_candidate(phone, preferences):
        return 0, *_recommendation_sort_key(phone, preferences)
    price = phone.get("price")
    if price is not None and _price_is_current(phone) and is_current(phone) and is_released(phone):
        return 1, price, -phone["score"], phone["id"]
    days = fetched_days(phone)
    recent_source = phone.get("origin") in ("official", "zol") and days is not None and days <= 30
    # 官网近期未知价优先于历史传闻报价；未知价不会当作零元最便宜。
    return 2 if recent_source else 3, not is_released(phone), price is None, price if price is not None else 0, -phone["score"], phone["id"]


def _catalogue_sort_key(phone: dict, preferences: Preferences) -> tuple:
    if preferences.sort != "recommended":
        return _recommendation_sort_key(phone, preferences)
    if phone["recommendation_eligible"]:
        return 0, *_recommendation_sort_key(phone, preferences)
    days = fetched_days(phone)
    recent_source = phone.get("origin") in ("official", "zol") and days is not None and days <= 30
    return (1, not recent_source, not is_released(phone), *(-part for part in release_sort_key(phone)),
        -phone["score"], phone["name"], phone["id"])


def search_catalogue(phones: list[dict], preferences: Preferences) -> dict:
    """完整型号搜索，不把旧资料、未售或缺价记录伪装成购买推荐。"""
    if not preferences.query.strip():
        return {"phones": [], "total": 0, "returned": 0}
    families: dict[str, list[dict]] = {}
    for phone in phones:
        if not _matches_identity(phone, preferences):
            continue
        storage = phone.get("storage_gb")
        if preferences.min_storage and (storage is None or storage < preferences.min_storage):
            continue
        record = match_phone(phone, preferences)
        families.setdefault(phone.get("family_key") or phone["id"], []).append(record)
    result = []
    all_members: dict[str, list[dict]] = {}
    for phone in phones:
        all_members.setdefault(phone.get("family_key") or phone["id"], []).append(phone)
    for members in families.values():
        representative = min(members, key=lambda phone: _catalogue_variant_key(phone, preferences))
        reasons = _catalogue_reasons(representative, preferences)
        representative.update(catalogue_reasons=[message for _, message in reasons],
            catalogue_codes=[code for code, _ in reasons],
            catalogue_status=reasons[0][0] if reasons else "current",
            recommendation_eligible=is_purchase_candidate(representative, preferences))
        metadata = family_metadata(all_members[representative.get("family_key") or representative["id"]], preferences)
        representative.update(metadata, catalogue_variant_count=metadata["variant_count"])
        result.append(representative)
    result.sort(key=lambda phone: _catalogue_sort_key(phone, preferences))
    return {"phones": [card_record(phone) for phone in result], "total": len(result), "returned": len(result)}


def _discovery_variant_key(phone: dict, preferences: Preferences) -> tuple:
    price = phone.get("price")
    price_known = price is not None and _price_is_current(phone)
    storage_ok = not preferences.min_storage or (phone.get("storage_gb") is not None and phone["storage_gb"] >= preferences.min_storage)
    normal_scope = preferences.include_history or is_current(phone)
    fully_matches = price_known and normal_scope and _matches_identity(phone, preferences) and not _constraint_reasons(phone, preferences)
    if fully_matches:
        return 0, *_recommendation_sort_key(phone, preferences)
    if price_known and storage_ok and is_released(phone):
        return 1, price, -phone["score"], phone["name"]
    if price_known and is_released(phone):
        return 2, price, -phone["score"], phone["name"]
    return 3, 0 if price is not None else 1, phone["name"]


def discover_new_releases(phones: list[dict], preferences: Preferences) -> dict:
    """独立发现入口；未知报价、未知容量与超预算都保留并解释。"""
    discoveries = []
    for phone in phones:
        if not phone.get("new_from_source") or phone.get("origin") not in ("official", "zol"):
            continue
        days = fetched_days(phone)
        if days is None or days > 30 or not _matches_identity(phone, preferences, discovery=True):
            continue
        record = match_phone(phone, preferences)
        reasons = _constraint_reasons(phone, preferences)
        if phone.get("availability") not in ("listed", "historical") and is_released(phone):
            reasons.insert(0, ("availability_unknown", "官网已列出，上市或销售状态待核实"))
        record["discovery_reasons"] = [message for _, message in reasons]
        record["discovery_codes"] = [code for code, _ in reasons]
        record["discovery_status"] = reasons[0][0] if reasons else "current" if preferences.budget_max is None else "within_budget"
        discoveries.append(record)
    families: dict[str, list[dict]] = {}
    for phone in discoveries:
        families.setdefault(phone.get("family_key") or phone["id"], []).append(phone)
    result = []
    all_members: dict[str, list[dict]] = {}
    for phone in phones:
        all_members.setdefault(phone.get("family_key") or phone["id"], []).append(phone)
    for members in families.values():
        representative = min(members, key=lambda phone: _discovery_variant_key(phone, preferences))
        metadata = family_metadata(all_members[representative.get("family_key") or representative["id"]], preferences)
        representative.update(metadata, discovery_variant_count=metadata["variant_count"])
        result.append(representative)
    result.sort(key=lambda phone: (not is_released(phone), *(-part for part in release_sort_key(phone)), 0 if phone.get("origin") == "official" else 1, phone["name"]))
    return {"phones": [card_record(phone) for phone in result], "total": len(result), "returned": len(result)}


def _level(value: float | None, low: float, high: float) -> float | None:
    if value is None:
        return None
    return max(0.0, min(1.0, (value - low) / (high - low)))


def _average(values: list[float | None]) -> float | None:
    available = [value for value in values if value is not None]
    return sum(available) / len(available) if available else None


def _soc_level(soc: str | None) -> float | None:
    """只区分已知芯片系列档位，未知芯片不外推性能。"""
    if not soc:
        return None
    text = soc.lower().replace(" ", "")
    if re.search(r"(骁龙|snapdragon)8.*(至尊|elite)|(天玑|dimensity)9\d{3}|a(?:1[89]|2\d)(?:pro)?(?:$|[^0-9])", text):
        return 1.0
    if re.search(r"(骁龙|snapdragon)8|(天玑|dimensity)8\d{3}|a1[567]", text):
        return 0.8
    if re.search(r"(骁龙|snapdragon)7|(天玑|dimensity)[67]\d{3}", text):
        return 0.55
    if re.search(r"(骁龙|snapdragon)[46]|(天玑|dimensity)[6789]\d{2}", text):
        return 0.3
    return None


def match_phone(phone: dict, preferences: Preferences) -> dict:
    spec_sources = phone.get("specs_sources", {})
    camera_fields = " ".join(str(value) for key, value in phone.get("specs", {}).items()
        if any(word in key for word in ("摄", "镜头", "防抖", "传感器"))
        and not (phone.get("origin") in ("zol", "official") and spec_sources.get(key, {}).get("origin") == "legacy"))
    camera_known = bool(camera_fields)
    # 字段原文包含明确否定时不视为具备此配置。
    ois = bool(re.search(r"OIS|光学防抖", camera_fields, re.I)) and not bool(re.search(r"(?:不支持|无|不具备).{0,8}(?:OIS|光学防抖)", camera_fields, re.I))
    telephoto = bool(re.search(r"潜望|长焦", camera_fields)) and not bool(re.search(r"(?:无|不支持).{0,4}(?:潜望|长焦)", camera_fields))
    camera = (0.35 + 0.3 * ois + 0.35 * telephoto) if camera_known else None
    battery = _average([_level(phone.get("battery_mah"), 3500, 7500), _level(phone.get("charging_w"), 15, 100)])
    gaming = _average([_soc_level(phone.get("soc")), _level(phone.get("ram_gb"), 4, 16), _level(phone.get("refresh_hz"), 60, 144)])
    daily = _average([_level(phone.get("storage_gb"), 64, 512), _level(phone.get("ram_gb"), 4, 12), _level(phone.get("battery_mah"), 3500, 6500)])
    metrics = {"daily": daily, "gaming": gaming, "camera": camera, "battery": battery}
    weights = {name: 1.0 for name in metrics}
    for name in preferences.priorities:
        weights[name] = 3.0
    observed = [(value, weights[name]) for name, value in metrics.items() if value is not None]
    score = sum(value * weight for value, weight in observed) / sum(weight for _, weight in observed) if observed else 0.0
    coverage = len(observed) / len(metrics)
    score *= 0.75 + 0.25 * coverage
    reasons, tradeoffs = [], []
    if phone.get("battery_mah"):
        reasons.append(f"{phone['battery_mah']:g}mAh 电池" + (f"，{phone['charging_w']:g}W 充电" if phone.get("charging_w") else ""))
    if phone.get("soc"):
        reasons.append(f"{phone['soc']}" + (f" · {phone['ram_gb']:g}GB 内存" if phone.get("ram_gb") else ""))
    if "camera" in preferences.priorities:
        if telephoto or ois:
            reasons.insert(0, "影像配置：" + "、".join(label for flag, label in ((telephoto, "长焦镜头"), (ois, "光学防抖")) if flag))
        tradeoffs.append("影像按镜头配置匹配，成片效果仍需实测")
    if "gaming" in preferences.priorities:
        if _soc_level(phone.get("soc")) is None:
            tradeoffs.append("芯片性能档位待核实")
        tradeoffs.append("持续帧率、散热与功耗没有实测数据")
    if "battery" in preferences.priorities:
        tradeoffs.append("电池与功率为标称规格，续航时长没有实测")
    if preferences.compact:
        compact = _average([1 - _level(phone.get("display_inches"), 6.1, 6.9) if phone.get("display_inches") is not None else None, 1 - _level(phone.get("weight_g"), 165, 235) if phone.get("weight_g") is not None else None])
        if compact is not None:
            score = 0.7 * score + 0.3 * compact
        if phone.get("weight_g"):
            reasons.insert(0, f"约 {phone['weight_g']:g}g" + (f" · {phone['display_inches']:g} 英寸" if phone.get("display_inches") else ""))
    price_origin = phone.get("field_sources", {}).get("price", {}).get("origin", phone.get("origin"))
    price_time = phone.get("field_sources", {}).get("price", {}).get("fetched_at", phone.get("fetched_at"))
    price_days = fetched_days({"fetched_at": price_time})
    if price_origin == "legacy":
        tradeoffs.append("价格来自历史导出，购买前需核价")
    elif price_days is None:
        tradeoffs.append("参考价采集时间未知，购买前需核价")
    elif price_days > 30:
        tradeoffs.append("参考价超过 30 天，购买前需核价")
    elif phone.get("price"):
        tradeoffs.append("价格为来源站参考报价，实际渠道价可能不同")
    if not is_current(phone):
        if phone.get("availability") in ("unknown", "announced") and phone.get("origin") != "legacy":
            tradeoffs.append("上市或销售状态待核实")
        else:
            tradeoffs.append("历史或超过 30 天的记录")
    missing = [label for name, label in (("soc", "芯片"), ("battery_mah", "电池"), ("charging_w", "快充")) if phone.get(name) is None]
    if missing:
        tradeoffs.append("待补充：" + "、".join(missing))
    usage_score = round(score * 100)
    return {**phone, "score": usage_score, **_ranking_fields(phone, preferences, usage_score), "reasons": reasons[:3], "tradeoffs": tradeoffs[:4], "metrics": {key: round(value * 100) if value is not None else None for key, value in metrics.items()}}


def recommend(phones: list[dict], preferences: Preferences, limit: int = 60) -> dict:
    candidates = []
    excluded: dict[str, set] = {name: set() for name in ("history", "upcoming", "unknown_price", "stale_price", "over_budget", "under_budget", "unknown_storage", "insufficient_storage")}
    over_budget_prices = []
    current = sum(is_current(phone) for phone in phones)
    for phone in phones:
        if not _matches_identity(phone, preferences):
            continue
        family = phone.get("family_key") or phone["id"]
        if not is_released(phone):
            excluded["upcoming"].add(family)
            continue
        if not preferences.include_history and not is_current(phone):
            excluded["history"].add(family)
            continue
        reasons = _constraint_reasons(phone, preferences)
        if reasons:
            for code, _ in reasons:
                excluded[code].add(family)
            if {code for code, _ in reasons} == {"over_budget"}:
                over_budget_prices.append((family, phone["price"]))
            continue
        candidates.append(match_phone(phone, preferences))
    candidates.sort(key=lambda phone: _recommendation_sort_key(phone, preferences))
    # 相同系列只占一个推荐位置，按所选排序保留预算内最合适的容量版本。
    families = {}
    for phone in candidates:
        families.setdefault(phone.get("family_key") or phone["id"], phone)
    results = list(families.values())
    all_members: dict[str, list[dict]] = {}
    for phone in phones:
        all_members.setdefault(phone.get("family_key") or phone["id"], []).append(phone)
    for phone in results[:limit]:
        phone.update(family_metadata(all_members[phone.get("family_key") or phone["id"]], preferences))
    matching_families = set(families)
    counts = {key: len(value - matching_families) for key, value in excluded.items()}
    return {"phones": [card_record(phone) for phone in results[:limit]], "total": len(results), "coverage": {"records": len(phones), "current_records": current, "unknown_price": len((excluded["unknown_price"] | excluded["stale_price"]) - matching_families), "excluded": counts, "budget_suggestion": min((price for family, price in over_budget_prices if family not in matching_families), default=None), "matching_variants": len(candidates), "returned": min(limit, len(results))}, "catalogue": search_catalogue(phones, preferences), "discovery": discover_new_releases(phones, preferences), "updated_at": max((phone.get("fetched_at") or "" for phone in phones), default="") or None, "preferences": asdict(preferences), "ranking_policy": ranking_policy(preferences)}
