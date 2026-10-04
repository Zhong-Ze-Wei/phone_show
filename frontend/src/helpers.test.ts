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
