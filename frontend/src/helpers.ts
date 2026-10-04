import type { Phone, Preferences, SortOrder } from "./types";

export const SORT_LABELS: Record<SortOrder, string> = {
  recommended: "综合推荐",
  newest: "新机优先",
  match: "需求匹配",
  price_asc: "价格由低到高",
  price_desc: "价格由高到低",
};

export const DEFAULT_PREFERENCES: Preferences = {
  budget_min: 0,
  budget_max: 0,
  brands: [],
  os: "all",
  priorities: ["daily"],
  compact: false,
  min_storage: 256,
  include_history: false,
  query: "",
  sort: "recommended",
  purchase_mode: "new",
};

export function enteredBudget(value: string): number | null {
  if (!value.trim()) return null;
  const budget = Number(value);
  return Number.isFinite(budget) && budget > 0 ? budget : null;
}

export function rankingExplanation(mode: Preferences["purchase_mode"]): string {
  return mode === "used"
    ? "二手机型参考按需求匹配 85%、预算余量 10%、主流品牌 5% 综合排序，不因机型较老扣分。当前价格仍为来源的新机参考价，没有二手行情或库存，请自行核对二手报价、成色与保修。"
    : "综合推荐按需求匹配 75%、预算余量 10%、上市时效 10%、主流品牌 5% 排序。一年内上市的机型获得更多时效加分，日期未知时不假定为新机。品牌加分是选购策略，不代表质量测评。";
}

export function rankingHighlights(phone: Phone): string[] {
  return (phone.ranking_reasons || [])
    .filter(
      (reason) =>
        !reason.startsWith("需求匹配 ") && !reason.startsWith("预算余量 "),
    )
    .slice(0, 2);
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
    budget_max: Math.max(0, Number(value.budget_max)),
    brands: [...new Set(value.brands)],
    priorities: [...new Set(value.priorities)],
    query: value.query.trim(),
  };
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
