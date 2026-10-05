import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { Phone, VariantSummary } from "./types";
import { dateLabel } from "./helpers";

type PriceRow = Pick<
  VariantSummary,
  | "id"
  | "ram_gb"
  | "storage_gb"
  | "price"
  | "field_sources"
  | "five_g"
  | "budget_warning"
>;

export function priceRows(phone: Phone): PriceRow[] {
  return phone.variant_summary?.length ? phone.variant_summary : [phone];
}

export function priceRange(rows: PriceRow[]): string {
  const prices = rows.flatMap((row) =>
    row.price != null && row.price > 0 ? [row.price] : [],
  );
  if (!prices.length) return "价格待核实";
  const low = Math.min(...prices),
    high = Math.max(...prices);
  const money = (value: number) => `¥${value.toLocaleString("zh-CN")}`;
  return low === high ? money(low) : `${money(low)}–${money(high)}`;
}

function capacity(row: PriceRow): string {
  const storage =
    row.storage_gb == null
      ? "容量待核实"
      : row.storage_gb >= 1024
        ? `${row.storage_gb / 1024}TB`
        : `${row.storage_gb}GB`;
  return `${row.ram_gb == null ? "" : `${row.ram_gb}GB + `}${storage}`;
}

function quoteNote(row: PriceRow): string {
  if (row.price == null) return "暂无独立报价";
  const source = row.field_sources?.price;
  if (source?.origin === "legacy") return "历史价 · 请核价";
  const stamp = source?.fetched_at;
  if (!stamp || !Number.isFinite(Date.parse(stamp))) return "报价日期未知";
  return `${dateLabel(stamp)}${Date.now() - Date.parse(stamp) > 30 * 86400000 ? " · 历史价" : " · 参考价"}`;
}

export default function PriceOverview({ phone }: { phone: Phone }) {
  const rows = priceRows(phone);
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState({ left: 0, top: 0 });
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const id = useId();
  const show = () => {
    clearTimeout(timer.current);
    setOpen(true);
  };
  const hide = () => {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setOpen(false), 120);
  };
  useEffect(() => () => clearTimeout(timer.current), []);
  useLayoutEffect(() => {
    if (!open || !trigger.current || !panel.current) return;
    const anchor = trigger.current.getBoundingClientRect(),
      popup = panel.current.getBoundingClientRect();
    setPosition({
      left: Math.max(
        12,
        Math.min(
          anchor.right - popup.width,
          window.innerWidth - popup.width - 12,
        ),
      ),
      top: Math.max(
        12,
        Math.min(anchor.bottom + 10, window.innerHeight - popup.height - 12),
      ),
    });
  }, [open, phone.id]);
  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => {
      if (
        !trigger.current?.contains(event.target as Node) &&
        !panel.current?.contains(event.target as Node)
      )
        setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    const reposition = (event: Event) => {
      if (
        !trigger.current ||
        !panel.current ||
        (event.target instanceof Node && panel.current.contains(event.target))
      )
        return;
      const anchor = trigger.current.getBoundingClientRect();
      const popup = panel.current.getBoundingClientRect();
      if (anchor.bottom < 0 || anchor.top > window.innerHeight) {
        setOpen(false);
        return;
      }
      setPosition({
        left: Math.max(
          12,
          Math.min(
            anchor.right - popup.width,
            window.innerWidth - popup.width - 12,
          ),
        ),
        top: Math.max(
          12,
          Math.min(anchor.bottom + 10, window.innerHeight - popup.height - 12),
        ),
      });
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    window.addEventListener("scroll", reposition, true);
    window.addEventListener("resize", reposition);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
      window.removeEventListener("scroll", reposition, true);
      window.removeEventListener("resize", reposition);
    };
  }, [open]);
  return (
    <>
      <button
        ref={trigger}
        className="price-overview"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        aria-label={`${phone.family_name || phone.name}，${priceRange(rows)}，查看全部配置价格`}
        onPointerEnter={(event) => {
          if (event.pointerType === "mouse") show();
        }}
        onPointerLeave={(event) => {
          if (event.pointerType === "mouse") hide();
        }}
        onFocus={show}
        onBlur={hide}
        onClick={show}
      >
        <strong>{priceRange(rows)}</strong>
        <small>{rows.length} 个配置 · 价格明细</small>
      </button>
      {open &&
        createPortal(
          <div
            ref={panel}
            id={id}
            className="price-popover"
            role="region"
            aria-label="全部配置价格"
            style={position}
            onPointerEnter={(event) => {
              if (event.pointerType === "mouse") show();
            }}
            onPointerLeave={(event) => {
              if (event.pointerType === "mouse") hide();
            }}
          >
            <header>
              <span>配置与参考价</span>
              <strong>{phone.family_name || phone.name}</strong>
            </header>
            <div className="price-rows">
              {rows.map((row) => (
                <div className="price-row" key={row.id}>
                  <span>
                    {capacity(row)}
                    {row.five_g == null ? "" : row.five_g ? " · 5G" : " · 4G"}
                  </span>
                  <strong>
                    {row.price == null
                      ? "待核实"
                      : `¥${row.price.toLocaleString("zh-CN")}`}
                  </strong>
                  <small>
                    {quoteNote(row)}
                    {row.budget_warning ? ` · ${row.budget_warning}` : ""}
                  </small>
                </div>
              ))}
            </div>
            <footer>
              展示全部已收录配置，缺价保留为空。
              {rows.some((row) => row.price == null)
                ? "区间仅包含已知报价。"
                : "报价供参考，请以购买时为准。"}
            </footer>
          </div>,
          document.body,
        )}
    </>
  );
}
