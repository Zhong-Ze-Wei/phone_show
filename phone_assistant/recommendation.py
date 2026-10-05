"""按明确条件筛选手机；用途取舍交由用户主动启动的 AI 分析。"""

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


@dataclass
class Preferences:
    budget_min: float = 0
    budget_max: float | None = None
    brands: list[str] = field(default_factory=list)
    os: str = "all"
    priorities: list[str] = field(default_factory=list)
    compact: bool = False
    min_storage: float = 0
    include_history: bool = False
    query: str = ""
    sort: str = "newest"
    purchase_mode: str = "new"

    def __post_init__(self):
        # 旧书签/API 请求保留兼容，但不恢复任何隐藏评分。
        if self.sort in ("recommended", "match"):
            self.sort = "newest"


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
    """明确未来日期或仅公布但未上市的产品，不参与默认已上市筛选。"""
    if phone.get("availability") == "announced":
        return False
    year, month, day = release_sort_key(phone)
    today = today or market_today()
    if year > today.year:
        return False
    if year == today.year and month > today.month:
        return False
    return not (year == today.year and month == today.month and day > today.day)


def _filter_sort_key(phone: dict, preferences: Preferences) -> tuple:
    price = phone.get("price")
    price_key = (price is None, price if price is not None else 0)
    if preferences.sort == "price_asc":
        return *price_key, phone["name"], phone["id"]
    if preferences.sort == "price_desc":
        return price is None, -price if price is not None else 0, phone["name"], phone["id"]
    return *(-part for part in release_sort_key(phone)), *price_key, phone["name"], phone["id"]


def _family_representative_key(phone: dict) -> tuple:
    """同族优先真实近期报价，再取最低价；未知价不当作零元。"""
    price = phone.get("price")
    current_quote = price is not None and _price_is_current(phone)
    return (not current_quote, price is None, price if price is not None else 0,
        phone.get("storage_gb") is None, phone.get("storage_gb") or 0, phone["id"])


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
    has_budget = preferences.budget_max is not None or preferences.budget_min > 0
    if has_budget and price is None:
        reasons.append(("unknown_price", "价格待核实，不能确认是否在预算内"))
    elif has_budget and not _price_is_current(phone):
        reasons.append(("stale_price", "参考报价未近期核验，不能确认当前预算"))
    elif preferences.budget_max is not None and price > preferences.budget_max:
        reasons.append(("over_budget", f"参考价 ¥{price:g}，超过当前 ¥{preferences.budget_max:g} 预算"))
    elif price is not None and price < preferences.budget_min:
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
    """近期核价资格独立于浏览资格，不借未知/历史报价证明可购买。"""
    return (_matches_identity(phone, preferences) and is_current(phone)
        and phone.get("price") is not None and _price_is_current(phone) and not _constraint_reasons(phone, preferences))


def _matches_filter(phone: dict, preferences: Preferences) -> bool:
    return (_matches_identity(phone, preferences) and (preferences.include_history or is_current(phone))
        and not _constraint_reasons(phone, preferences))


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
    return (not _matches_filter(phone, preferences), not current_quote, not trusted, price is None,
        price if price is not None else 0, -phone.get("quality_score", 0),
        phone.get("origin") != "official", phone["id"])


def _network_variant(phone: dict) -> str | None:
    """只识别明示网络版本；不把非 5G 或未知推断成 4G。"""
    explicit = re.search(r"([45])\s*G\s*版", phone["name"], re.I)
    if explicit:
        return explicit.group(1) + "G"
    if phone.get("five_g") is True:
        return "5G"
    if phone.get("five_g") is False:
        return "non5G"
    return None


def _partial_replaced(phone: dict, complete: list[dict], preferences: Preferences) -> bool:
    """当前不完整资料不能被历史配置替代，也不将已核价 SKU 的缺值补成另一个版本。"""
    if not complete:
        return False
    days = fetched_days(phone)
    if phone.get("origin") not in ("official", "zol") or days is None or days > 30:
        return True
    if phone.get("price") is not None and _price_is_current(phone):
        return False
    return any(is_current(other) and is_released(other)
        and (not _matches_filter(phone, preferences) or _matches_filter(other, preferences)) for other in complete)


def family_variants(members: list[dict], preferences: Preferences) -> list[dict]:
    """按真实 RAM/容量及明确网络版本去重，保留当前待核验资料的独立身份。"""
    specific = [phone for phone in members if phone.get("storage_gb") is not None]
    if not specific:
        return [min(members, key=lambda phone: _variant_source_key(phone, preferences))]
    groups: dict[tuple, list[dict]] = {}
    for phone in members:
        network = _network_variant(phone)
        if phone.get("storage_gb") is None:
            complete = [other for other in specific if _network_variant(other) == network]
            if _partial_replaced(phone, complete, preferences):
                continue
        elif phone.get("ram_gb") is None:
            complete = [other for other in specific if other.get("ram_gb") is not None
                and other["storage_gb"] == phone["storage_gb"] and _network_variant(other) == network]
            if _partial_replaced(phone, complete, preferences):
                continue
        groups.setdefault((phone.get("ram_gb"), phone.get("storage_gb"), network), []).append(phone)
    variants = [min(records, key=lambda phone: _variant_source_key(phone, preferences)) for records in groups.values()]
    return sorted(variants, key=lambda phone: (phone.get("storage_gb") is None, phone.get("storage_gb") or 0,
        phone.get("ram_gb") is None, phone.get("ram_gb") or 0, _network_variant(phone) or "", phone["id"]))


def family_name(members: list[dict]) -> str:
    source = min(members, key=lambda phone: (phone.get("origin") != "official", phone.get("storage_gb") is not None,
        len(phone["name"]), phone["id"]))
    name = re.sub(r"\s*\([^)]*(?:\d\s*(?:GB|TB|MB)|全网通)[^)]*\)", "", source["name"], flags=re.I).strip()
    name = re.sub(r"\s+\d+\s*(?:GB|TB|MB)(?:\s*[+/]\s*\d+\s*(?:GB|TB|MB))?\s*$", "", name, flags=re.I)
    return re.sub(r"^苹果\s*", "", name) if source.get("brand") == "苹果" else name


def variant_record(phone: dict, preferences: Preferences) -> dict:
    """各配置独立判断硬条件与警告，不借用代表版本的资格或价格。"""
    record = phone_record(phone)
    constraints = _constraint_reasons(phone, preferences)
    matches = _matches_filter(phone, preferences)
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
    keys = ("id", "name", "ram_gb", "storage_gb", "five_g", "price", "source_url", "fetched_at", "price_source_url", "price_fetched_at",
        "budget_warning", "matches_preferences", "recommendation_eligible", "variant_codes", "variant_reasons")
    summary = []
    for phone in variants:
        record = variant_record(phone, preferences)
        summary.append({**{key: record.get(key) for key in keys}, "availability": phone.get("availability") or "unknown",
            "field_sources": {key: value for key, value in phone.get("field_sources", {}).items() if key in ("price", "ram_gb", "storage_gb")}})
    return {"family_name": family_name(members), "variant_count": len(variants), "variant_summary": summary}


def _family_groups(phones: list[dict]) -> dict[str, list[dict]]:
    families: dict[str, list[dict]] = {}
    for phone in phones:
        families.setdefault(phone.get("family_key") or phone["id"], []).append(phone)
    return families


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
        message = "价格待核实，不能确认是否在预算内" if preferences.budget_max is not None or preferences.budget_min else "参考报价待核实，可浏览资料，不能证明当前购买价格"
        reasons.append(("unknown_price", message))
    else:
        if not _price_is_current(phone):
            reasons.append(("stale_price", "历史或未近期核验的参考报价，购买前须重新核价"))
        if preferences.budget_max is not None and price > preferences.budget_max:
            reasons.append(("over_budget", f"参考价 ¥{price:g}，超过当前 ¥{preferences.budget_max:g} 预算"))
        elif price < preferences.budget_min:
            reasons.append(("under_budget", f"参考价 ¥{price:g}，低于当前预算下限"))
    return reasons


def _catalogue_variant_key(phone: dict, preferences: Preferences) -> tuple:
    matches = (preferences.include_history or is_current(phone)) and not _constraint_reasons(phone, preferences)
    if matches:
        return 0, *_family_representative_key(phone)
    price = phone.get("price")
    if price is not None and _price_is_current(phone) and is_current(phone) and is_released(phone):
        return 1, price, phone["id"]
    days = fetched_days(phone)
    recent_source = phone.get("origin") in ("official", "zol") and days is not None and days <= 30
    # 官网近期未知价优先于历史传闻报价；未知价不会当作零元最便宜。
    return 2 if recent_source else 3, not is_released(phone), *_family_representative_key(phone)


def search_catalogue(phones: list[dict], preferences: Preferences) -> dict:
    """完整型号搜索，不把旧资料、未售或缺价记录伪装成购买推荐。"""
    if not preferences.query.strip():
        return {"phones": [], "total": 0, "returned": 0}
    result = []
    all_members = _family_groups(phones)
    for raw_members in all_members.values():
        members = [phone_record(phone) for phone in family_variants(raw_members, preferences)
            if _matches_identity(phone, preferences) and (not preferences.min_storage or
                phone.get("storage_gb") is not None and phone["storage_gb"] >= preferences.min_storage)]
        if not members:
            continue
        representative = min(members, key=lambda phone: _catalogue_variant_key(phone, preferences))
        reasons = _catalogue_reasons(representative, preferences)
        representative.update(matches_preferences=(preferences.include_history or is_current(representative)) and not _constraint_reasons(representative, preferences),
            budget_warning=budget_warning(representative, preferences), catalogue_reasons=[message for _, message in reasons],
            catalogue_codes=[code for code, _ in reasons],
            catalogue_status=reasons[0][0] if reasons else "current",
            recommendation_eligible=is_purchase_candidate(representative, preferences))
        metadata = family_metadata(all_members[representative.get("family_key") or representative["id"]], preferences)
        representative.update(metadata, catalogue_variant_count=metadata["variant_count"])
        result.append(representative)
    result.sort(key=lambda phone: _filter_sort_key(phone, preferences))
    return {"phones": [card_record(phone) for phone in result], "total": len(result), "returned": len(result)}


def _discovery_variant_key(phone: dict, preferences: Preferences) -> tuple:
    price = phone.get("price")
    price_known = price is not None and _price_is_current(phone)
    storage_ok = not preferences.min_storage or (phone.get("storage_gb") is not None and phone["storage_gb"] >= preferences.min_storage)
    normal_scope = preferences.include_history or is_current(phone)
    fully_matches = normal_scope and _matches_identity(phone, preferences) and not _constraint_reasons(phone, preferences)
    if fully_matches:
        return 0, *_family_representative_key(phone)
    if price_known and storage_ok and is_released(phone):
        return 1, price, phone["name"]
    if price_known and is_released(phone):
        return 2, price, phone["name"]
    return 3, 0 if price is not None else 1, phone["name"]


def discover_new_releases(phones: list[dict], preferences: Preferences) -> dict:
    """独立发现入口；未知报价、未知容量与超预算都保留并解释。"""
    all_members = _family_groups(phones)
    discovered_families = set()
    for phone in phones:
        days = fetched_days(phone)
        if (phone.get("new_from_source") and phone.get("origin") in ("official", "zol")
                and days is not None and days <= 30 and _matches_identity(phone, preferences, discovery=True)):
            discovered_families.add(phone.get("family_key") or phone["id"])
    variants = [phone for key in discovered_families for phone in family_variants(all_members[key], preferences)]
    discoveries = []
    for phone in variants:
        if phone.get("origin") not in ("official", "zol"):
            continue
        days = fetched_days(phone)
        if days is None or days > 30 or not _matches_identity(phone, preferences, discovery=True):
            continue
        record = phone_record(phone)
        reasons = _catalogue_reasons(phone, preferences)
        reasons.extend(reason for reason in _constraint_reasons(phone, preferences) if reason[0] not in {code for code, _ in reasons})
        record["matches_preferences"] = _matches_identity(phone, preferences) and (preferences.include_history or is_current(phone)) and not _constraint_reasons(phone, preferences)
        record["recommendation_eligible"] = is_purchase_candidate(phone, preferences)
        record["budget_warning"] = budget_warning(phone, preferences)
        record["discovery_reasons"] = [message for _, message in reasons]
        record["discovery_codes"] = [code for code, _ in reasons]
        record["discovery_status"] = reasons[0][0] if reasons else "current" if preferences.budget_max is None else "within_budget"
        discoveries.append(record)
    families: dict[str, list[dict]] = {}
    for phone in discoveries:
        families.setdefault(phone.get("family_key") or phone["id"], []).append(phone)
    result = []
    for members in families.values():
        representative = min(members, key=lambda phone: _discovery_variant_key(phone, preferences))
        metadata = family_metadata(all_members[representative.get("family_key") or representative["id"]], preferences)
        representative.update(metadata, discovery_variant_count=metadata["variant_count"])
        result.append(representative)
    result.sort(key=lambda phone: (not is_released(phone), *(-part for part in release_sort_key(phone)), 0 if phone.get("origin") == "official" else 1, phone["name"]))
    return {"phones": [card_record(phone) for phone in result], "total": len(result), "returned": len(result)}


def phone_record(phone: dict) -> dict:
    """附上事实和来源局限，不生成用途、品牌或价格评分。"""
    reasons, tradeoffs = [], []
    if phone.get("battery_mah"):
        reasons.append(f"{phone['battery_mah']:g}mAh 电池" + (f"，{phone['charging_w']:g}W 充电" if phone.get("charging_w") else ""))
    if phone.get("soc"):
        reasons.append(f"{phone['soc']}" + (f" · {phone['ram_gb']:g}GB 内存" if phone.get("ram_gb") else ""))
    price_origin = phone.get("field_sources", {}).get("price", {}).get("origin", phone.get("origin"))
    price_time = phone.get("field_sources", {}).get("price", {}).get("fetched_at", phone.get("fetched_at"))
    price_days = fetched_days({"fetched_at": price_time})
    if phone.get("price") is None:
        tradeoffs.append("参考报价待核实")
    elif price_origin == "legacy":
        tradeoffs.append("价格来自历史导出，购买前需核价")
    elif price_days is None:
        tradeoffs.append("参考价采集时间未知，购买前需核价")
    elif price_days > 30:
        tradeoffs.append("参考价超过 30 天，购买前需核价")
    else:
        tradeoffs.append("价格为来源站参考报价，实际渠道价可能不同")
    if not is_current(phone):
        if phone.get("availability") in ("unknown", "announced") and phone.get("origin") != "legacy":
            tradeoffs.append("上市或销售状态待核实")
        else:
            tradeoffs.append("历史或超过 30 天的记录")
    missing = [label for name, label in (("soc", "芯片"), ("battery_mah", "电池"), ("charging_w", "快充")) if phone.get(name) is None]
    if missing:
        tradeoffs.append("待补充：" + "、".join(missing))
    return {**phone, "reasons": reasons, "tradeoffs": tradeoffs}


def filter_phones(phones: list[dict], preferences: Preferences, limit: int | None = None) -> dict:
    """返回全部符合明确条件的型号；limit 只用于显式缩小 AI 上下文。"""
    candidates = []
    excluded: dict[str, set] = {name: set() for name in ("history", "upcoming", "unknown_price", "stale_price", "over_budget", "under_budget", "unknown_storage", "insufficient_storage")}
    over_budget_prices = []
    current = sum(is_current(phone) for phone in phones)
    all_members = _family_groups(phones)
    variants = [phone for members in all_members.values() for phone in family_variants(members, preferences)]
    for phone in variants:
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
        candidates.append(variant_record(phone, preferences))
    candidates.sort(key=_family_representative_key)
    # 同型号只占一张卡，先选最低符合条件的报价配置，再按用户选的顺序排型号。
    families = {}
    for phone in candidates:
        families.setdefault(phone.get("family_key") or phone["id"], phone)
    results = sorted(families.values(), key=lambda phone: _filter_sort_key(phone, preferences))
    shown = results if limit is None else results[:limit]
    for phone in shown:
        phone.update(family_metadata(all_members[phone.get("family_key") or phone["id"]], preferences))
    matching_families = set(families)
    counts = {key: len(value - matching_families) for key, value in excluded.items()}
    return {"phones": [card_record(phone) for phone in shown], "total": len(results), "coverage": {"records": len(phones), "current_records": current, "unknown_price": len((excluded["unknown_price"] | excluded["stale_price"]) - matching_families), "excluded": counts, "budget_suggestion": min((price for family, price in over_budget_prices if family not in matching_families), default=None), "matching_variants": len(candidates), "returned": len(shown)}, "catalogue": search_catalogue(phones, preferences), "discovery": discover_new_releases(phones, preferences), "updated_at": max((phone.get("fetched_at") or "" for phone in phones), default="") or None, "preferences": asdict(preferences)}


def recommend(phones: list[dict], preferences: Preferences, limit: int | None = None) -> dict:
    """旧 Python/CLI 入口的兼容别名，与筛选接口完全一致。"""
    return filter_phones(phones, preferences, limit)
