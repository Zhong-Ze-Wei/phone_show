import { describe, expect, it } from "vitest";
import { priceRange, priceRows } from "./PriceOverview";
import type { Phone, VariantSummary } from "./types";
const row = (id: string, price: number | null) =>
  ({ id, price }) as VariantSummary;
describe("全部配置的报价概览", () => {
  it("保留全部配置，范围涵盖超预算的已知报价，缺价不伪装成最低价", () => {
    const variants = [
      row("low", 4999),
      row("high", 8999),
      row("unknown", null),
    ];
    const rows = priceRows({ variant_summary: variants } as Phone);
    expect(rows).toHaveLength(3);
    expect(priceRange(rows)).toBe("¥4,999–¥8,999");
  });
  it("相同报价只显示一个金额，全部缺价明确标记", () => {
    expect(priceRange([row("a", 4999), row("b", 4999)])).toBe("¥4,999");
    expect(priceRange([row("a", null), row("b", null)])).toBe("价格待核实");
  });
  it("单配置仍然展示自身报价", () => {
    expect(priceRange(priceRows({ id: "a", price: 5999 } as Phone))).toBe(
      "¥5,999",
    );
  });
});
