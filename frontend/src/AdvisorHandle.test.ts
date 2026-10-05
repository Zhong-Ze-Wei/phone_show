import { describe, expect, it } from "vitest";
import { advisorWidth } from "./AdvisorHandle";

describe("顾问分栏边界", () => {
  it("拖动和缩小窗口时均给手机列表留出可操作宽度", () => {
    expect(advisorWidth(1800, 1600)).toBe(1340);
    expect(advisorWidth(1000, 760)).toBe(500);
    expect(advisorWidth(800, 601)).toBe(341);
    expect(advisorWidth(40, 1280)).toBe(320);
    expect(advisorWidth(720, 1280)).toBe(720);
  });
});
