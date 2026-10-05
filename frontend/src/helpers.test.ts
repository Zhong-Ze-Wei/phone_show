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
  filterPreferences,
  SORT_LABELS,
  variantRequestUrl,
  variantLabel,
  phoneWithVariant,
  sortPhoneCards,
  phoneForPreview,
  chatPhoneIds,
  safeSource,
  toggleSaved,
} from "./helpers";
import type { Phone, Preferences, Recommendations } from "./types";

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
  it("默认按上市时间排序与买新机，只提供上市时间和价格排序", () => {
    expect(DEFAULT_PREFERENCES.sort).toBe("newest");
    expect(DEFAULT_PREFERENCES.priorities).toEqual([]);
    expect(DEFAULT_PREFERENCES.compact).toBe(false);
    expect(DEFAULT_PREFERENCES.purchase_mode).toBe("new");
    expect(SORT_LABELS.newest).toBe("上市时间");
    expect(Object.keys(SORT_LABELS)).toEqual([
      "newest",
      "price_asc",
      "price_desc",
    ]);
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
    expect(
      catalogueStatusLabel({ ...phone, recommendation_eligible: true }),
    ).toBe("符合当前筛选");
  });
  it("筛选状态独立于报价购买资格，未核价也可符合无预算筛选", () => {
    expect(
      catalogueStatusLabel({
        ...phone,
        price: null,
        matches_preferences: true,
        recommendation_eligible: false,
      }),
    ).toBe("符合当前筛选");
    expect(
      catalogueStatusLabel({
        ...phone,
        matches_preferences: false,
        recommendation_eligible: true,
      }),
    ).toBe("不符合当前筛选");
  });
  it("AI 用途变化不改变客观筛选请求，同时 AI 请求保留多选用途", () => {
    const preferences = {
      ...DEFAULT_PREFERENCES,
      budget_min: 3000,
      brands: ["苹果", "苹果"],
      query: "  iPhone  ",
    };
    const aiPreferences = {
      ...preferences,
      priorities: ["camera", "gaming", "camera"] as Preferences["priorities"],
      compact: true,
    };
    expect(filterPreferences(aiPreferences)).toEqual(
      filterPreferences(preferences),
    );
    expect(filterPreferences(aiPreferences)).toMatchObject({
      budget_min: 3000,
      budget_max: null,
      brands: ["苹果"],
      query: "iPhone",
      priorities: [],
      compact: false,
    });
    expect(requestPreferences(aiPreferences).priorities).toEqual([
      "camera",
      "gaming",
    ]);
    expect(aiPreferences.priorities).toEqual(["camera", "gaming", "camera"]);
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

  it("版本请求保留多品牌和中文检索，不受 AI 用途或小屏偏好影响", () => {
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
    expect(url.searchParams.getAll("priorities")).toEqual([]);
    expect(url.searchParams.get("query")).toBe("华为 Mate + 80");
    expect(url.searchParams.get("budget_min")).toBe("1000");
    expect(url.searchParams.get("budget_max")).toBe("8000");
    expect(url.searchParams.get("os")).toBe("HarmonyOS");
    expect(url.searchParams.get("compact")).toBe("false");
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

  it("同容量网络版本用已核实网络区分，未知网络不推断为4G", () => {
    const variant = { ram_gb: 8, storage_gb: 128, price: 2999 };
    expect(
      variantLabel({ ...variant, name: "测试手机（4G版）", five_g: false }),
    ).toBe("8GB + 128GB · 4G · ¥2,999");
    expect(variantLabel({ ...variant, name: "测试手机", five_g: true })).toBe(
      "8GB + 128GB · 5G · ¥2,999",
    );
    expect(variantLabel({ ...variant, name: "旧手机", five_g: false })).toBe(
      "8GB + 128GB · 非5G · ¥2,999",
    );
    expect(
      variantLabel({ ...variant, name: "网络信息待核实", five_g: null }),
    ).toBe(variantLabel(variant));
  });

  it("保留来源名称明确的网络版本，即使规范5G字段未知", () => {
    const variant = { ram_gb: 8, storage_gb: 128, price: 3699, five_g: null };
    expect(variantLabel({ ...variant, name: "华为 nova 8 Pro（4G版）" })).toBe(
      "8GB + 128GB · 4G · ¥3,699",
    );
    expect(variantLabel({ ...variant, name: "测试手机（5 G版）" })).toBe(
      "8GB + 128GB · 5G · ¥3,699",
    );
  });

  it("切换容量完整使用新版本，不沿用旧版本的价格、来源或购买资格", () => {
    const base = {
      ...phone,
      id: "2tb",
      storage_gb: 2048,
      price: 20499,
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
    expect(result.price).toBeNull();
    expect(result.recommendation_eligible).toBe(false);
    expect(result.matches_preferences).toBe(false);
    expect(result.catalogue_status).toBe("unknown_price");
    expect(result.field_sources?.price).toBeUndefined();
    expect(base.price).toBe(20499);
    expect(base.field_sources?.price.origin).toBe("legacy");
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
  it("价格排序采用当前所选配置的实际报价，保留原卡 key 和数据且未知价最后", () => {
    const original = [
      { key: "16e-128", phone: { ...phone, id: "16e-128", price: 4499 } },
      { key: "other", phone: { ...phone, id: "other", price: 4999 } },
      { key: "unknown", phone: { ...phone, id: "unknown", price: null } },
    ];
    const selected = {
      ...original[0].phone,
      id: "16e-512",
      storage_gb: 512,
      price: 7499,
    };
    const cards = original.map((card) => ({
      ...card,
      phone:
        card.key === "16e-128"
          ? phoneWithVariant(
              card.phone,
              { context: "current", phone: selected },
              "current",
            )
          : card.phone,
    }));
    const ascending = sortPhoneCards(cards, "price_asc");
    expect(ascending.map((card) => card.phone.id)).toEqual([
      "other",
      "16e-512",
      "unknown",
    ]);
    expect(ascending[1].key).toBe("16e-128");
    expect(ascending[1]).toBe(cards[0]);
    expect(
      sortPhoneCards(cards, "price_desc").map((card) => card.phone.id),
    ).toEqual(["16e-512", "other", "unknown"]);
    expect(cards.map((card) => card.key)).toEqual([
      "16e-128",
      "other",
      "unknown",
    ]);
    expect(original[0].phone.price).toBe(4499);
  });
  it("相同报价用名称和真实配置 id 确定顺序，不把未知价当零元", () => {
    const cards = [
      { key: "null", phone: { ...phone, id: "null", name: "A", price: null } },
      { key: "b", phone: { ...phone, id: "b", name: "B", price: 4999 } },
      { key: "a2", phone: { ...phone, id: "a2", name: "A", price: 4999 } },
      { key: "a1", phone: { ...phone, id: "a1", name: "A", price: 4999 } },
    ];
    for (const sort of ["price_asc", "price_desc"] as const)
      expect(sortPhoneCards(cards, sort).map((card) => card.key)).toEqual([
        "a1",
        "a2",
        "b",
        "null",
      ]);
  });
  it("上市排序仅使用真实上市日期精度，年和月缺失不借用采集日或占位日期", () => {
    const cards = [
      {
        key: "unknown",
        phone: { ...phone, release_date: null, fetched_at: "2099-01-01" },
      },
      {
        key: "year",
        phone: {
          ...phone,
          release_date: "2026-12-31",
          release_precision: "year" as const,
          release_year: 2026,
        },
      },
      {
        key: "month",
        phone: {
          ...phone,
          release_date: "2026-12-31",
          release_precision: "month" as const,
          release_year: 2026,
          release_month: 10,
        },
      },
      {
        key: "day",
        phone: {
          ...phone,
          release_date: "2026-10-15",
          release_precision: "day" as const,
          price: null,
        },
      },
      {
        key: "old",
        phone: { ...phone, release_date: "2025-12-31", price: 999 },
      },
    ];
    expect(sortPhoneCards(cards, "newest").map((card) => card.key)).toEqual([
      "day",
      "month",
      "year",
      "old",
      "unknown",
    ]);
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
