import { afterEach, describe, expect, it, vi } from "vitest";
import {
  booleanSpec,
  COMPARE_FIELDS,
  DEFAULT_PREFERENCES,
  enteredBudget,
  validBudgetInput,
  resultPhones,
  catalogueStatusLabel,
  isHistoricalPrice,
  numberSpec,
  priceLabel,
  priceStatusLabel,
  releaseLabel,
  sourceLabel,
  discoveryPriceLabel,
  discoveryOverview,
  requestPreferences,
  variantRequestUrl,
  variantLabel,
  phoneWithVariant,
  rankingExplanation,
  rankingHighlights,
  phoneForPreview,
  chatPhoneIds,
  safeSource,
  toggleSaved,
} from "./helpers";
import type { Phone, Recommendations } from "./types";

const phone = {
  id: "100",
  name: "测试手机",
  price: 2999,
  origin: "zol",
} as Phone;

afterEach(() => vi.useRealTimers());

describe("需求提交", () => {
  it("预算首次留空，零和无效输入不被当成无限预算", () => {
    expect(DEFAULT_PREFERENCES.budget_max).toBeNull();
    expect(DEFAULT_PREFERENCES.min_storage).toBe(0);
    expect(enteredBudget("")).toBeNull();
    expect(enteredBudget(" ")).toBeNull();
    expect(enteredBudget("0")).toBeNaN();
    expect(enteredBudget("-200")).toBeNaN();
    expect(enteredBudget("not a budget")).toBeNaN();
    expect(validBudgetInput("")).toBe(true);
    expect(validBudgetInput("   ")).toBe(true);
    expect(validBudgetInput("0")).toBe(false);
    expect(validBudgetInput("-200")).toBe(false);
    expect(validBudgetInput("not a budget")).toBe(false);
    expect(validBudgetInput("Infinity")).toBe(false);
    expect(enteredBudget("3500")).toBe(3500);
  });
  it("保留多种用途并移除重复品牌、用途，规范预算和检索文字", () => {
    expect(
      requestPreferences({
        ...DEFAULT_PREFERENCES,
        budget_min: -10,
        brands: ["小米", "小米"],
        priorities: ["camera", "battery", "camera"],
        query: "  Ultra  ",
      }),
    ).toEqual({
      ...DEFAULT_PREFERENCES,
      budget_min: 0,
      brands: ["小米"],
      priorities: ["camera", "battery"],
      query: "Ultra",
    });
  });
  it("默认综合推荐与买新机，并保留用户明确选择的价格排序", () => {
    expect(DEFAULT_PREFERENCES.sort).toBe("recommended");
    expect(DEFAULT_PREFERENCES.purchase_mode).toBe("new");
    expect(
      requestPreferences({ ...DEFAULT_PREFERENCES, sort: "price_asc" }).sort,
    ).toBe("price_asc");
  });
  it("二手场景与历史资料独立，提交时不启用历史报价", () => {
    const submitted = requestPreferences({
      ...DEFAULT_PREFERENCES,
      purchase_mode: "used",
    });
    expect(submitted.purchase_mode).toBe("used");
    expect(submitted.include_history).toBe(false);
    expect(rankingExplanation("used")).toContain("没有二手行情或库存");
    expect(rankingExplanation("used", 4000)).toContain("85%");
    expect(rankingExplanation("new")).toContain("一年内");
  });
  it("空的最高预算保留 null 与用户设定的最低预算，不引入隐藏金额或容量", () => {
    const submitted = requestPreferences({
      ...DEFAULT_PREFERENCES,
      budget_min: 3000,
      budget_max: enteredBudget(""),
    });
    expect(submitted.budget_min).toBe(3000);
    expect(submitted.budget_max).toBeNull();
    expect(submitted.min_storage).toBe(0);
    expect(
      requestPreferences({ ...submitted, budget_max: 8000 }).budget_max,
    ).toBe(8000);
    expect(rankingExplanation("new", null)).toContain("85%");
    expect(rankingExplanation("used", null)).toContain("95%");
    expect(rankingExplanation("new", 4000)).toContain("75%");
  });
  it("型号搜索显示完整目录而不是合格购买名单，保留历史和缺价项超过60项", () => {
    const all = Array.from({ length: 67 }, (_, index) => ({
      ...phone,
      id: String(index),
      catalogue_status: index % 2 ? "history" : "unknown_price",
      price: index % 2 ? 2999 : null,
    }));
    const data = {
      phones: [phone],
      catalogue: { phones: all, total: 67, returned: 67 },
    } as Recommendations;
    expect(resultPhones(data, "iPhone")).toBe(all);
    expect(resultPhones(data, " iPhone ")).toHaveLength(67);
    expect(resultPhones(data, " ")).toEqual([phone]);
    expect(resultPhones(null, "iPhone")).toEqual([]);
    expect(catalogueStatusLabel(all[0])).toBe("报价待核实");
    expect(catalogueStatusLabel(all[1])).toBe("历史资料");
  });
  it("卡片突出时效与品牌依据，不重复已有的需求分与预算信息", () => {
    const ranked = {
      ...phone,
      ranking_reasons: [
        "需求匹配 85 分，是推荐的主要依据",
        "预算余量 20 分，依据来源参考报价",
        "一年内上市，获得时效加分",
        "主流品牌采购偏好适度加分，不代表品质或售后结论",
        "其他说明",
      ],
    };
    expect(rankingHighlights(ranked)).toEqual(
      ranked.ranking_reasons.slice(2, 4),
    );
    expect(ranked.ranking_reasons).toHaveLength(5);
    expect(
      rankingHighlights({ ...phone, ranking_reasons: ["需求匹配 60 分"] }),
    ).toEqual([]);
  });
});

describe("容量版本", () => {
  it("版本请求省略空的预算上限，保留预算下限和明确的零容量限制", () => {
    const url = new URL(
      variantRequestUrl("phone / 256", {
        ...DEFAULT_PREFERENCES,
        budget_min: 3000,
      }),
      "http://localhost",
    );
    expect(url.pathname).toBe("/api/phones/phone%20%2F%20256/variants");
    expect(url.searchParams.has("budget_max")).toBe(false);
    expect(url.searchParams.get("budget_min")).toBe("3000");
    expect(url.searchParams.get("min_storage")).toBe("0");
    expect(url.searchParams.get("compact")).toBe("false");
    expect(url.searchParams.get("include_history")).toBe("false");
  });

  it("版本请求保留多品牌、多用途和中文检索，规范重复项和首尾空白", () => {
    const url = new URL(
      variantRequestUrl("100", {
        ...DEFAULT_PREFERENCES,
        budget_min: 1000,
        budget_max: 8000,
        brands: ["华为", "苹果", "华为"],
        priorities: ["camera", "battery", "camera"],
        os: "HarmonyOS",
        compact: true,
        min_storage: 512,
        include_history: true,
        query: "  华为 Mate + 80  ",
        sort: "price_asc",
        purchase_mode: "used",
      }),
      "http://localhost",
    );
    expect(url.searchParams.getAll("brands")).toEqual(["华为", "苹果"]);
    expect(url.searchParams.getAll("priorities")).toEqual([
      "camera",
      "battery",
    ]);
    expect(url.searchParams.get("query")).toBe("华为 Mate + 80");
    expect(url.searchParams.get("budget_min")).toBe("1000");
    expect(url.searchParams.get("budget_max")).toBe("8000");
    expect(url.searchParams.get("os")).toBe("HarmonyOS");
    expect(url.searchParams.get("compact")).toBe("true");
    expect(url.searchParams.get("min_storage")).toBe("512");
    expect(url.searchParams.get("include_history")).toBe("true");
    expect(url.searchParams.get("sort")).toBe("price_asc");
    expect(url.searchParams.get("purchase_mode")).toBe("used");
  });

  it("版本标签对应真实容量与价格，苹果未知运行内存不显示虚假 RAM", () => {
    expect(variantLabel({ ram_gb: 12, storage_gb: 256, price: 3999 })).toBe(
      "12GB + 256GB · ¥3,999",
    );
    expect(variantLabel({ ram_gb: null, storage_gb: 256, price: 5999 })).toBe(
      "256GB · ¥5,999",
    );
    expect(variantLabel({ ram_gb: 16, storage_gb: 1024, price: null })).toBe(
      "16GB + 1TB · 价格待核实",
    );
    expect(variantLabel({ ram_gb: null, storage_gb: 2048, price: 13999 })).toBe(
      "2TB · ¥13,999",
    );
    expect(variantLabel({ ram_gb: 12, storage_gb: null, price: null })).toBe(
      "配置待核实 · 价格待核实",
    );
  });

  it("切换容量完整使用新版本，不沿用旧版本的价格、评分或购买资格", () => {
    const base = {
      ...phone,
      id: "2tb",
      storage_gb: 2048,
      price: 20499,
      score: 90,
      recommendation_score: 90,
      recommendation_eligible: true,
      matches_preferences: true,
      catalogue_status: "eligible",
      family_name: "测试手机家族",
      variant_count: 2,
      variant_summary: [],
      field_sources: { price: { origin: "legacy" } },
    };
    const selected = {
      ...phone,
      id: "256gb",
      storage_gb: 256,
      price: null,
      recommendation_eligible: false,
      matches_preferences: false,
      catalogue_status: "unknown_price",
      variant_reasons: ["配置报价待核实"],
      family_name: "版本侧的家族信息",
      variant_count: 1,
      field_sources: { storage_gb: { origin: "official" } },
    };
    const result = phoneWithVariant(
      base,
      { context: "budget-8000", phone: selected },
      "budget-8000",
    );
    expect(result).toEqual({
      ...selected,
      family_name: base.family_name,
      variant_count: selected.variant_count,
      variant_summary: base.variant_summary,
    });
    expect(result.score).toBeUndefined();
    expect(result.recommendation_score).toBeUndefined();
    expect(result.price).toBeNull();
    expect(result.recommendation_eligible).toBe(false);
    expect(result.field_sources?.price).toBeUndefined();
    expect(base.price).toBe(20499);
    expect(base.score).toBe(90);
  });

  it("预算等条件变化后沿用当前默认版本，不恢复旧条件下的容量选择", () => {
    const base = { ...phone, id: "512gb", storage_gb: 512 };
    const choice = {
      context: "budget-8000",
      phone: { ...phone, id: "2tb", storage_gb: 2048 },
    };
    expect(phoneWithVariant(base, undefined, "budget-8000")).toBe(base);
    expect(phoneWithVariant(base, choice, "budget-4000")).toBe(base);
    expect(phoneWithVariant(base, choice, "budget-8000").id).toBe("2tb");
  });

  it("原卡缺少型号展示信息时保留所选版本的家族数据", () => {
    const selected = {
      ...phone,
      id: "512gb",
      family_name: "测试型号",
      variant_count: 3,
      variant_summary: [],
    };
    const result = phoneWithVariant(
      phone,
      { context: "current", phone: selected },
      "current",
    );
    expect(result.family_name).toBe("测试型号");
    expect(result.variant_count).toBe(3);
    expect(result.variant_summary).toBe(selected.variant_summary);
  });
  it("配置切换后的最新报价与成员列表覆盖图库原有摘要", () => {
    const oldSummary = [
      {
        ...phone,
        id: "256gb",
        storage_gb: 256,
        price: 8999,
        matches_preferences: true,
        recommendation_eligible: true,
        variant_codes: [],
        variant_reasons: [],
      },
    ];
    const latestSummary = [
      { ...oldSummary[0], price: 9999 },
      { ...oldSummary[0], id: "512gb", storage_gb: 512, price: 11999 },
    ];
    const base = { ...phone, variant_count: 1, variant_summary: oldSummary };
    const selected = {
      ...phone,
      id: "512gb",
      price: 11999,
      variant_count: 2,
      variant_summary: latestSummary,
    };
    const result = phoneWithVariant(
      base,
      { context: "current", phone: selected },
      "current",
    );
    expect(result.price).toBe(11999);
    expect(result.variant_count).toBe(2);
    expect(result.variant_summary).toBe(latestSummary);
    expect(result.variant_summary?.[0].price).toBe(9999);
  });
});

describe("新品来源与日期", () => {
  it("图库预览默认当前首台，显式选择不依赖旧对象，条件变更清除旧选择", () => {
    const entries = [
      { ...phone, id: "one" },
      { ...phone, id: "two" },
    ];
    expect(phoneForPreview(entries, null, "budget-5000")).toBe(entries[0]);
    expect(
      phoneForPreview(
        entries,
        { id: "two", context: "budget-5000" },
        "budget-5000",
      ),
    ).toBe(entries[1]);
    expect(
      phoneForPreview(
        entries,
        { id: "two", context: "budget-5000" },
        "budget-2000",
      ),
    ).toBe(entries[0]);
    expect(
      phoneForPreview([], { id: "two", context: "budget-5000" }, "budget-2000"),
    ).toBeNull();
    const refreshed = [{ ...entries[1], price: 1999 }];
    expect(
      phoneForPreview(
        refreshed,
        { id: "two", context: "budget-5000" },
        "budget-5000",
      )?.price,
    ).toBe(1999);
  });
  it("品牌概览保留五个重点品牌，再补最新的其他品牌，避免同品牌占满首屏", () => {
    const entries = [
      ["h1", "华为"],
      ["h2", "华为"],
      ["r1", "红米"],
      ["v1", "vivo"],
      ["o1", "OPPO"],
      ["g1", "荣耀"],
      ["a1", "苹果"],
      ["s1", "三星"],
    ].map(([id, brand]) => ({ ...phone, id, brand }));
    expect(discoveryOverview(entries).map((item) => item.id)).toEqual([
      "v1",
      "o1",
      "h1",
      "g1",
      "a1",
      "r1",
    ]);
    expect(
      discoveryOverview(entries.filter((item) => item.brand === "华为")).map(
        (item) => item.id,
      ),
    ).toEqual(["h1", "h2"]);
    expect(entries.map((item) => item.id)).toEqual([
      "h1",
      "h2",
      "r1",
      "v1",
      "o1",
      "g1",
      "a1",
      "s1",
    ]);
  });
  it("日期精度没有日或月时不会虚构一个日期，采集时间不代表上市时间", () => {
    expect(
      releaseLabel({
        ...phone,
        release_year: 2026,
        release_month: 9,
        release_precision: "month",
      }),
    ).toBe("2026年9月");
    expect(
      releaseLabel({ ...phone, release_year: 2026, release_precision: "year" }),
    ).toBe("2026年（月份待核实）");
    expect(releaseLabel({ ...phone, fetched_at: "2026-10-04T00:00:00Z" })).toBe(
      "上市日期待核实",
    );
  });
  it("官方起价与具体配置报价分开，官方资料不标历史", () => {
    const official = {
      ...phone,
      brand: "vivo",
      origin: "official" as const,
      price: null,
      price_from: 4999,
    };
    expect(sourceLabel(official)).toBe("vivo官网");
    expect(discoveryPriceLabel(official)).toContain("¥4,999 起");
    expect(discoveryPriceLabel(official)).toContain("具体配置价待核实");
    expect(priceLabel(official)).toBe("价格待核实");
    expect(isHistoricalPrice(official)).toBe(false);
  });
});

describe("收藏与比较", () => {
  it("比较和明确咨询保留五部完整机型，不再限三部", () => {
    const phones = Array.from({ length: 5 }, (_, index) => ({
      ...phone,
      id: String(index),
    }));
    expect(chatPhoneIds(phones, null, "current")).toEqual([
      "0",
      "1",
      "2",
      "3",
      "4",
    ]);
    expect(
      chatPhoneIds(
        [],
        {
          ids: phones.map((item) => item.id),
          context: "current",
          origin: "advice",
        },
        "current",
      ),
    ).toEqual(["0", "1", "2", "3", "4"]);
  });
  it("详情明确咨询 B 时不会被已有对比 A 覆盖，对比面板咨询使用明确目标", () => {
    expect(
      chatPhoneIds(
        [phone],
        { ids: ["200"], context: "current", origin: "advice" },
        "current",
      ),
    ).toEqual(["200"]);
    expect(
      chatPhoneIds(
        [phone],
        { ids: ["100", "200"], context: "current", origin: "advice" },
        "current",
      ),
    ).toEqual(["100", "200"]);
  });
  it("普通预览与开球仍优先当前对比，条件变化或清除咨询目标后不沿用旧机型", () => {
    expect(
      chatPhoneIds(
        [phone],
        { ids: ["200"], context: "current", origin: "preview" },
        "current",
      ),
    ).toEqual(["100"]);
    expect(
      chatPhoneIds(
        [],
        { ids: ["200"], context: "current", origin: "preview" },
        "current",
      ),
    ).toEqual(["200"]);
    expect(
      chatPhoneIds(
        [phone],
        { ids: ["200"], context: "old", origin: "advice" },
        "current",
      ),
    ).toEqual(["100"]);
    expect(
      chatPhoneIds(
        [],
        { ids: ["200"], context: "old", origin: "advice" },
        "current",
      ),
    ).toEqual([]);
    expect(chatPhoneIds([{ ...phone, id: "300" }], null, "current")).toEqual([
      "300",
    ]);
    expect(chatPhoneIds([], null, "current")).toEqual([]);
  });
  it("同一配置只能收藏一次，再次点击取消收藏", () => {
    expect(
      toggleSaved([phone, phone], { ...phone, id: "200" }).map((p) => p.id),
    ).toEqual(["100", "200"]);
    expect(toggleSaved([phone], phone)).toEqual([]);
  });
  it("未知参数不被显示成零值或不支持", () => {
    expect(numberSpec(null, "GB")).toBe("待核实");
    expect(booleanSpec(null)).toBe("待核实");
    expect(booleanSpec(false)).toBe("不支持");
    expect(COMPARE_FIELDS.find((f) => f.label === "NFC")?.value(phone)).toBe(
      "待核实",
    );
  });
  it("保留价格自身的来源，即使整条记录刚刚刷新", () => {
    const mixed = {
      ...phone,
      fetched_at: "2026-10-03",
      field_sources: { price: { origin: "legacy" } },
    };
    expect(isHistoricalPrice(mixed)).toBe(true);
    expect(priceLabel(mixed)).toBe("¥2,999 · 历史价");
    expect(priceLabel({ ...phone, price: null })).toBe("价格待核实");
  });
  it("旧来源报价和未知报价日期不会随着参数刷新变成新报价", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-03T08:00:00Z"));
    expect(
      priceStatusLabel({
        ...phone,
        fetched_at: "2026-10-03T08:00:00Z",
        field_sources: {
          price: { origin: "zol", fetched_at: "2026-08-01T00:00:00Z" },
        },
      }),
    ).toBe("历史价");
    expect(
      priceStatusLabel({
        ...phone,
        field_sources: {
          price: { origin: "zol", fetched_at: "2026-10-02T00:00:00Z" },
        },
      }),
    ).toBe("参考价");
    expect(
      priceStatusLabel({
        ...phone,
        field_sources: { price: { origin: "zol", fetched_at: null } },
      }),
    ).toBe("日期未知");
  });
  it("来源链接拒绝脚本和非网页协议", () => {
    expect(safeSource("javascript:alert(1)")).toBeUndefined();
    expect(safeSource("file:///private")).toBeUndefined();
    expect(safeSource("https://detail.zol.com.cn/100/param.shtml")).toBe(
      "https://detail.zol.com.cn/100/param.shtml",
    );
  });
});
