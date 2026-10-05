import type { Phone, Preferences, Recommendations, SortOrder } from "./types";

export const SORT_LABELS: Record<SortOrder, string> = {
  newest: "上市时间",
  price_asc: "价格由低到高",
  price_desc: "价格由高到低",
};

export const DEFAULT_PREFERENCES: Preferences = {
  budget_min: 0,
  budget_max: null,
  brands: [],
  os: "all",
  priorities: [],
  compact: false,
  min_storage: 0,
  include_history: false,
  query: "",
  sort: "newest",
  purchase_mode: "new",
};

export function enteredBudget(value: string): number | null {
  if (!value.trim()) return null;
  const budget = Number(value);
  return Number.isFinite(budget) && budget > 0 ? budget : Number.NaN;
}

export function validBudgetInput(value: string): boolean {
  const budget = enteredBudget(value);
  return budget === null || Number.isFinite(budget);
}

export function resultPhones(
  data: Recommendations | null,
  query: string,
): Phone[] {
  return query.trim() ? data?.catalogue?.phones || [] : data?.phones || [];
}

export function catalogueStatusLabel(phone: Phone): string {
  const labels: Record<string, string> = {
    history: "历史资料",
    upcoming: "待上市",
    availability_unknown: "销售状态待核实",
    unknown_price: "报价待核实",
    stale_price: "历史价 · 请核价",
    over_budget: "超出当前预算",
    under_budget: "低于预算下限",
  };
  return (
    labels[phone.catalogue_status || ""] ||
    (phone.matches_preferences === false
      ? "不符合当前筛选"
      : phone.matches_preferences === true || phone.recommendation_eligible
        ? "符合当前筛选"
        : "目录资料")
  );
}

export function phoneForPreview(
  phones: Phone[],
  selection: { id: string; context: string } | null,
  context: string,
): Phone | null {
  const selected = selection?.context === context ? selection.id : null;
  return phones.find((phone) => phone.id === selected) || phones[0] || null;
}

export interface ChatChoice {
  ids: string[];
  context: string;
  origin: "preview" | "advice";
}

export function chatPhoneIds(
  compare: Phone[],
  choice: ChatChoice | null,
  context: string,
): string[] {
  const currentChoice = choice?.context === context ? choice : null;
  if (currentChoice?.origin === "advice") return currentChoice.ids;
  if (compare.length) return compare.map((phone) => phone.id);
  return currentChoice?.ids || [];
}

export function requestPreferences(value: Preferences): Preferences {
  return {
    ...value,
    budget_min: Math.max(0, Number(value.budget_min)),
    budget_max: value.budget_max === null ? null : Number(value.budget_max),
    brands: [...new Set(value.brands)],
    priorities: [...new Set(value.priorities)],
    query: value.query.trim(),
  };
}

export function filterPreferences(value: Preferences): Preferences {
  return { ...requestPreferences(value), priorities: [], compact: false };
}

export function variantRequestUrl(
  id: string,
  preferences: Preferences,
): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(filterPreferences(preferences))) {
    if (value === null) continue;
    if (Array.isArray(value)) {
      for (const item of value) query.append(key, String(item));
    } else {
      query.set(key, String(value));
    }
  }
  return `/api/phones/${encodeURIComponent(id)}/variants?${query}`;
}

export function variantLabel(
  phone: Pick<Phone, "ram_gb" | "storage_gb" | "price"> &
    Partial<Pick<Phone, "five_g" | "name">>,
): string {
  const storage =
    phone.storage_gb === 1024
      ? "1TB"
      : phone.storage_gb === 2048
        ? "2TB"
        : `${phone.storage_gb}GB`;
  const capacity =
    phone.storage_gb === null
      ? "配置待核实"
      : phone.ram_gb === null
        ? storage
        : `${phone.ram_gb}GB + ${storage}`;
  const price =
    phone.price === null
      ? "价格待核实"
      : `¥${phone.price.toLocaleString("zh-CN", { maximumFractionDigits: 0 })}`;
  const explicitNetwork = phone.name?.match(/([45])\s*G\s*版/i)?.[1];
  const network = explicitNetwork
    ? `${explicitNetwork}G`
    : phone.five_g === true
      ? "5G"
      : phone.five_g === false
        ? /\b4G\b/i.test(phone.name || "")
          ? "4G"
          : "非5G"
        : "";
  return `${capacity}${network ? ` · ${network}` : ""} · ${price}`;
}

export interface VariantSelection {
  context: string;
  phone: Phone;
}

export function phoneWithVariant(
  base: Phone,
  choice: VariantSelection | undefined,
  context: string,
): Phone {
  if (!choice || choice.context !== context) return base;
  return {
    ...choice.phone,
    family_name: base.family_name ?? choice.phone.family_name,
    variant_count: choice.phone.variant_count ?? base.variant_count,
    variant_summary: choice.phone.variant_summary ?? base.variant_summary,
  };
}

function releaseSortValue(phone: Phone): number {
  const release = phone.release_date;
  if (
    release &&
    (!phone.release_precision || phone.release_precision === "day")
  ) {
    const stamp = Date.parse(`${release}T00:00:00Z`);
    if (
      Number.isFinite(stamp) &&
      new Date(stamp).toISOString().slice(0, 10) === release
    )
      return Number(release.replaceAll("-", ""));
  }
  return (phone.release_year || 0) * 10000 + (phone.release_month || 0) * 100;
}

export function sortPhoneCards(
  cards: { key: string; phone: Phone }[],
  sort: SortOrder,
): { key: string; phone: Phone }[] {
  return [...cards].sort((left, right) => {
    const a = left.phone;
    const b = right.phone;
    if (sort === "newest") {
      const released = releaseSortValue(b) - releaseSortValue(a);
      if (released) return released;
    }
    const price =
      a.price == null
        ? b.price == null
          ? 0
          : 1
        : b.price == null
          ? -1
          : (a.price - b.price) * (sort === "price_desc" ? -1 : 1);
    return (
      price || a.name.localeCompare(b.name, "zh-CN") || a.id.localeCompare(b.id)
    );
  });
}

export function toggleSaved(phones: Phone[], phone: Phone): Phone[] {
  const unique = phones.filter(
    (item, index, all) =>
      all.findIndex((other) => other.id === item.id) === index,
  );
  return unique.some((item) => item.id === phone.id)
    ? unique.filter((item) => item.id !== phone.id)
    : [...unique, phone];
}

export function numberSpec(
  value: number | null | undefined,
  unit: string,
): string {
  return value == null ? "待核实" : `${value.toLocaleString("zh-CN")}${unit}`;
}

export function booleanSpec(value: boolean | null | undefined): string {
  return value == null ? "待核实" : value ? "支持" : "不支持";
}

export function dateLabel(value: string | null | undefined): string {
  if (!value) return "日期待核实";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "日期待核实"
    : date.toLocaleDateString("zh-CN", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
      });
}

export function releaseLabel(phone: Phone): string {
  if (
    phone.release_date &&
    (!phone.release_precision || phone.release_precision === "day")
  )
    return dateLabel(phone.release_date);
  if (phone.release_year && phone.release_month)
    return `${phone.release_year}年${phone.release_month}月`;
  if (phone.release_year) return `${phone.release_year}年（月份待核实）`;
  return "上市日期待核实";
}

export function sourceLabel(phone: Phone): string {
  return phone.origin === "official"
    ? `${phone.brand}官网`
    : phone.origin === "zol"
      ? "中关村在线"
      : "历史导入";
}

export function discoveryPriceLabel(phone: Phone): string {
  if (phone.price != null) return priceLabel(phone);
  if (phone.price_from != null)
    return `¥${phone.price_from.toLocaleString()} 起 · ${phone.origin === "official" ? "官网起价" : "来源起价"}，具体配置价待核实`;
  return "配置价格待核实";
}

export function isHistoricalPrice(phone: Phone): boolean {
  const source = phone.field_sources?.price;
  const collectedAt = source?.fetched_at
    ? new Date(source.fetched_at).getTime()
    : Number.NaN;
  return (
    source?.origin === "legacy" ||
    (!source && phone.origin === "legacy") ||
    (Number.isFinite(collectedAt) &&
      Date.now() - collectedAt > 30 * 24 * 60 * 60 * 1000)
  );
}

export function priceStatusLabel(phone: Phone): string {
  if (isHistoricalPrice(phone)) return "历史价";
  const date = phone.field_sources?.price?.fetched_at;
  return date && Number.isFinite(new Date(date).getTime())
    ? "参考价"
    : "日期未知";
}

export function priceLabel(phone: Phone): string {
  if (phone.price == null) return "价格待核实";
  const value = `¥${phone.price.toLocaleString("zh-CN", { maximumFractionDigits: 0 })}`;
  return `${value} · ${priceStatusLabel(phone)}`;
}

export function discoveryOverview(phones: Phone[], limit = 6): Phone[] {
  const selected: Phone[] = [];
  const brands = new Set<string>();
  for (const brand of ["vivo", "OPPO", "华为", "荣耀", "苹果"]) {
    const phone = phones.find(
      (item) => item.brand.toLowerCase() === brand.toLowerCase(),
    );
    if (phone) {
      selected.push(phone);
      brands.add(phone.brand);
    }
    if (selected.length === limit) return selected;
  }
  for (const phone of phones) {
    if (!brands.has(phone.brand)) {
      selected.push(phone);
      brands.add(phone.brand);
    }
    if (selected.length === limit) return selected;
  }
  for (const phone of phones) {
    if (!selected.some((item) => item.id === phone.id)) selected.push(phone);
    if (selected.length === limit) break;
  }
  return selected;
}

export const COMPARE_FIELDS: {
  label: string;
  value: (phone: Phone) => string;
}[] = [
  { label: "价格", value: priceLabel },
  {
    label: "价格采集时间",
    value: (p) => dateLabel(p.field_sources?.price?.fetched_at),
  },
  {
    label: "内存 / 存储",
    value: (p) =>
      `${numberSpec(p.ram_gb, "GB")} / ${numberSpec(p.storage_gb, "GB")}`,
  },
  { label: "处理器", value: (p) => p.soc || "待核实" },
  { label: "电池", value: (p) => numberSpec(p.battery_mah, "mAh") },
  { label: "有线充电", value: (p) => numberSpec(p.charging_w, "W") },
  { label: "主摄像素", value: (p) => numberSpec(p.camera_mp, "MP") },
  {
    label: "屏幕",
    value: (p) =>
      `${numberSpec(p.display_inches, "英寸")} / ${numberSpec(p.refresh_hz, "Hz")}`,
  },
  { label: "重量", value: (p) => numberSpec(p.weight_g, "g") },
  { label: "厚度", value: (p) => numberSpec(p.thickness_mm, "mm") },
  { label: "系统", value: (p) => p.os || "待核实" },
  { label: "NFC", value: (p) => booleanSpec(p.nfc) },
  { label: "5G", value: (p) => booleanSpec(p.five_g) },
  { label: "防护", value: (p) => p.waterproof || "待核实" },
  { label: "来源上市时间", value: releaseLabel },
  { label: "采集时间", value: (p) => dateLabel(p.fetched_at) },
];

export function safeSource(url: string | null | undefined): string | undefined {
  if (!url) return undefined;
  try {
    const parsed = new URL(url);
    return ["https:", "http:"].includes(parsed.protocol)
      ? parsed.href
      : undefined;
  } catch {
    return undefined;
  }
}

export function readSaved(): Phone[] {
  try {
    const value = localStorage.getItem("pick-a-phone.saved.v1");
    if (!value) return [];
    const items: unknown = JSON.parse(value);
    if (!Array.isArray(items)) return [];
    return items.filter(
      (item): item is Phone =>
        typeof item === "object" &&
        item !== null &&
        typeof item.id === "string" &&
        typeof item.name === "string",
    );
  } catch {
    return [];
  }
}
