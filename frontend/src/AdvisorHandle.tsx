import {
  useEffect,
  useRef,
  useState,
  type DragEvent,
  type PointerEvent,
} from "react";

export function advisorWidth(width: number, viewport: number): number {
  return Math.min(Math.max(320, width), Math.max(320, viewport - 260));
}

export default function AdvisorHandle({
  open,
  compact,
  width,
  onWidth,
  onToggle,
  accepting,
  receiving,
  onDragOver,
  onDragLeave,
  onDrop,
}: {
  open: boolean;
  compact: boolean;
  width: number;
  onWidth: (width: number) => void;
  onToggle: () => void;
  accepting: boolean;
  receiving: boolean;
  onDragOver: (event: DragEvent<HTMLElement>) => void;
  onDragLeave: (event: DragEvent<HTMLElement>) => void;
  onDrop: (event: DragEvent<HTMLElement>) => void;
}) {
  const [position, setPosition] = useState<{ x: number; y: number } | null>(
    null,
  );
  const [viewport, setViewport] = useState({
    width: window.innerWidth,
    height: window.innerHeight,
  });
  const [moving, setMoving] = useState(false);
  const gesture = useRef<{
    x: number;
    y: number;
    left: number;
    top: number;
    moved: boolean;
  } | null>(null);
  const suppressClick = useRef(false);
  useEffect(() => {
    const resize = () =>
      setViewport({ width: window.innerWidth, height: window.innerHeight });
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);
  const x = open
    ? viewport.width - width - 25
    : Math.min(
        Math.max(12, position?.x ?? viewport.width - 84),
        viewport.width - 62,
      );
  const y = Math.min(
    Math.max(80, position?.y ?? viewport.height * 0.54),
    viewport.height - 86,
  );

  function begin(event: PointerEvent<HTMLElement>) {
    if (event.button !== 0) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    gesture.current = {
      x: event.clientX,
      y: event.clientY,
      left: x,
      top: y,
      moved: false,
    };
    suppressClick.current = false;
  }
  function move(event: PointerEvent<HTMLElement>) {
    const start = gesture.current;
    if (!start) return;
    const dx = event.clientX - start.x,
      dy = event.clientY - start.y;
    if (!start.moved && Math.hypot(dx, dy) < 6) return;
    start.moved = true;
    suppressClick.current = true;
    setMoving(true);
    if (open)
      onWidth(advisorWidth(viewport.width - event.clientX, viewport.width));
    else
      setPosition({
        x: Math.min(Math.max(12, start.left + dx), viewport.width - 62),
        y: Math.min(Math.max(80, start.top + dy), viewport.height - 86),
      });
  }
  function finish() {
    gesture.current = null;
    setMoving(false);
  }
  if (compact) return null;
  return (
    <>
      {open && (
        <div
          className="advisor-divider"
          role="separator"
          aria-label="调整顾问宽度"
          aria-orientation="vertical"
          tabIndex={0}
          aria-valuemin={320}
          aria-valuemax={Math.max(320, viewport.width - 260)}
          aria-valuenow={Math.round(width)}
          style={{ right: width - 5 }}
          onPointerDown={begin}
          onPointerMove={move}
          onPointerUp={finish}
          onPointerCancel={finish}
          onKeyDown={(event) => {
            const next =
              event.key === "ArrowLeft"
                ? width + 40
                : event.key === "ArrowRight"
                  ? width - 40
                  : event.key === "Home"
                    ? 320
                    : event.key === "End"
                      ? viewport.width - 260
                      : null;
            if (next === null) return;
            event.preventDefault();
            onWidth(advisorWidth(next, viewport.width));
          }}
        />
      )}
      <button
        className={`ai-launcher advisor-orb ${open ? "is-open" : ""} ${accepting ? "accepting" : ""} ${receiving ? "receiving" : ""} ${moving ? "moving" : ""}`}
        aria-label={
          open
            ? "收起 AI 顾问（拖动调整宽度）"
            : "打开 AI 顾问（可拖动，也可接收手机）"
        }
        aria-expanded={open}
        title={
          open
            ? "点击收起 · 左右拖动调整宽度"
            : "点击展开顾问 · 拖动移动 · 拖入手机"
        }
        style={{ left: x, top: y }}
        onPointerDown={begin}
        onPointerMove={move}
        onPointerUp={finish}
        onPointerCancel={finish}
        onClick={() => {
          if (suppressClick.current) {
            suppressClick.current = false;
            return;
          }
          onToggle();
        }}
        onDragEnter={onDragOver}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
      >
        {open ? (
          <span aria-hidden="true">×</span>
        ) : (
          <svg className="robot-face" viewBox="0 0 32 32" aria-hidden="true">
            <path d="M16 5V2m-2 0h4M5 13H2v7h3m22-7h3v7h-3" />
            <rect x="5" y="7" width="22" height="20" rx="7" />
            <path d="M11 21h10" />
            <circle cx="11" cy="15" r="1.5" />
            <circle cx="21" cy="15" r="1.5" />
          </svg>
        )}
        {accepting && <span className="orb-drop-label">松手交给我</span>}
      </button>
    </>
  );
}
