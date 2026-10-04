import { useEffect, useRef, useState, type DragEvent } from "react";
import { api } from "./api";
import AdvisorChat from "./AdvisorChat";
import { ComparePanel, DetailPanel, QualityPanel, SyncPanel } from "./Panels";
import {
  dateLabel,
  DEFAULT_PREFERENCES,
  enteredBudget,
  validBudgetInput,
  resultPhones,
  catalogueStatusLabel,
  priceStatusLabel,
  releaseLabel,
  discoveryPriceLabel,
  discoveryOverview,
  sourceLabel,
  SORT_LABELS,
  numberSpec,
  readSaved,
  requestPreferences,
  rankingExplanation,
  rankingHighlights,
  phoneForPreview,
  chatPhoneIds,
  type ChatChoice,
  safeSource,
  toggleSaved,
} from "./helpers";
import type {
  Meta,
  Phone,
  Preferences,
  Recommendations,
  SyncStatus,
  SortOrder,
} from "./types";

const PURPOSES = [
  { id: "daily", title: "日常使用" },
  { id: "camera", title: "拍照" },
  { id: "gaming", title: "游戏" },
  { id: "battery", title: "续航" },
] as const;
const PHONE_DRAG_TYPE = "application/x-phone-assistant-phone";

export default function App() {
  const [preferences, setPreferences] = useState<Preferences>({
    ...DEFAULT_PREFERENCES,
  });
  const [budgetInput, setBudgetInput] = useState("");
  const budgetValid = validBudgetInput(budgetInput);
  const invalidBudgetRange =
    preferences.budget_max !== null &&
    preferences.budget_min > preferences.budget_max;
  const invalidBudget = !budgetValid || invalidBudgetRange;
  const [meta, setMeta] = useState<Meta | null>(null);
  const [data, setData] = useState<Recommendations | null>(null);
  const [resultKey, setResultKey] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState<Phone[]>(readSaved);
  const [showSaved, setShowSaved] = useState(false);
  const [reload, setReload] = useState(0);
  const [brandSearch, setBrandSearch] = useState("");
  const [details, setDetails] = useState<Phone | null>(null);
  const [compare, setCompare] = useState<Phone[]>([]);
  const [compareOpen, setCompareOpen] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const [chatChoice, setChatChoice] = useState<ChatChoice | null>(null);
  const [chatPreset, setChatPreset] = useState<{
    serial: number;
    prompt: string;
  } | null>(null);
  const [qualityOpen, setQualityOpen] = useState(false);
  const [syncOpen, setSyncOpen] = useState(false);
  const [syncStatus, setSyncStatus] = useState<SyncStatus>({ state: "idle" });
  const [storageError, setStorageError] = useState("");
  const budgetRef = useRef<HTMLInputElement>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [draggedId, setDraggedId] = useState<string | null>(null);
  const [dropActive, setDropActive] = useState(false);
  const [compareMessage, setCompareMessage] = useState("");
  const [selection, setSelection] = useState<{
    id: string;
    context: string;
  } | null>(null);
  const [isCompact, setIsCompact] = useState(
    () => window.matchMedia("(max-width: 900px)").matches,
  );
  const [previewExpanded, setPreviewExpanded] = useState(!isCompact);
  const previewRef = useRef<HTMLDivElement>(null);
  const requestKey = JSON.stringify([
    requestPreferences(preferences),
    reload,
    budgetValid,
  ]);
  const currentData = !invalidBudget && resultKey === requestKey ? data : null;

  useEffect(() => {
    const viewport = window.matchMedia("(max-width: 900px)");
    const updateViewport = () => {
      setIsCompact(viewport.matches);
      setPreviewExpanded(!viewport.matches);
    };
    viewport.addEventListener("change", updateViewport);
    return () => viewport.removeEventListener("change", updateViewport);
  }, []);

  useEffect(() => {
    api<Meta>("/api/meta")
      .then(setMeta)
      .catch((e: Error) => setError(e.message));
  }, [reload]);
  useEffect(() => {
    const controller = new AbortController();
    api<SyncStatus>("/api/sync", { signal: controller.signal })
      .then(setSyncStatus)
      .catch((e: Error) => {
        if (e.name !== "AbortError")
          setSyncStatus({ state: "failed", message: e.message });
      });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    if (syncStatus.state !== "running") return;
    const controller = new AbortController();
    const interval = setInterval(() => {
      api<SyncStatus>("/api/sync", { signal: controller.signal })
        .then((status) => {
          setSyncStatus(status);
          if (status.state === "completed") setReload((value) => value + 1);
        })
        .catch((e: Error) => {
          if (e.name !== "AbortError")
            setSyncStatus({ state: "failed", message: e.message });
        });
    }, 2500);
    return () => {
      clearInterval(interval);
      controller.abort();
    };
  }, [syncStatus.state]);
  useEffect(() => {
    setPage(1);
    if (invalidBudget) {
      setData(null);
      setLoading(false);
      setError("");
      setCompareOpen(false);
      return;
    }
    setData(null);
    setLoading(true);
    setError("");
    const controller = new AbortController();
    const timer = setTimeout(() => {
      setLoading(true);
      setError("");
      api<Recommendations>("/api/recommend", {
        method: "POST",
        body: JSON.stringify(requestPreferences(preferences)),
        signal: controller.signal,
      })
        .then((result) => {
          if (!controller.signal.aborted) {
            setData(result);
            setResultKey(requestKey);
          }
        })
        .catch((e: Error) => {
          if (!controller.signal.aborted && e.name !== "AbortError")
            setError(e.message);
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false);
        });
    }, 250);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [preferences, reload, invalidBudget, requestKey]);
  useEffect(() => {
    try {
      localStorage.setItem("pick-a-phone.saved.v1", JSON.stringify(saved));
      setStorageError("");
    } catch {
      setStorageError("浏览器未允许持久保存，当前收藏在关闭页面后可能丢失。");
    }
  }, [saved]);

  const update = (patch: Partial<Preferences>) =>
    setPreferences((prev) => ({ ...prev, ...patch }));
  function setBudget(value: string, minimum?: number) {
    setBudgetInput(value);
    update({
      budget_max: enteredBudget(value),
      ...(minimum != null ? { budget_min: minimum } : {}),
    });
  }
  const toggleBrand = (brand: string) =>
    update({
      brands: preferences.brands.includes(brand)
        ? preferences.brands.filter((value) => value !== brand)
        : [...preferences.brands, brand],
    });
  const searchMode = !showSaved && preferences.query.trim().length > 0;
  const phones = showSaved
    ? saved.map(
        (phone) =>
          currentData?.phones.find((item) => item.id === phone.id) || {
            ...phone,
            score: undefined,
            recommendation_score: undefined,
            ranking_reasons: [],
            reasons: [],
            tradeoffs: [],
          },
      )
    : resultPhones(currentData, preferences.query);
  const resultTotal = searchMode
    ? currentData?.catalogue?.total || 0
    : currentData?.total || 0;
  const brands =
    meta?.brands.filter((brand) =>
      brand.toLowerCase().includes(brandSearch.toLowerCase()),
    ) || [];
  async function startSync() {
    setQualityOpen(false);
    setSyncOpen(true);
    if (syncStatus.state === "running") return;
    setSyncStatus({
      state: "running",
      stage: "正在开始更新",
      message: "连接公开数据源，自动清洗采集结果。",
    });
    try {
      setSyncStatus(
        await api<SyncStatus>("/api/sync", {
          method: "POST",
          body: JSON.stringify({ mode: "current" }),
        }),
      );
    } catch (e) {
      setSyncStatus({
        state: "failed",
        stage: "更新未能开始",
        message: e instanceof Error ? e.message : "请求未完成，请稍后重试。",
      });
    }
  }
  function openAdvice(selected: Phone[]) {
    setDetails(null);
    setCompareOpen(false);
    setChatChoice({
      ids: selected.map((phone) => phone.id),
      context: selectionContext,
      origin: "advice",
    });
    setChatPreset((previous) => ({
      serial: (previous?.serial || 0) + 1,
      prompt:
        selected.length > 1
          ? "比较这些手机的优势和取舍，哪部更适合我？"
          : "解释这部手机的优势和取舍，是否适合我的需求？",
    }));
    setChatOpen(true);
  }
  function openDetail(phone: Phone) {
    setChatChoice({
      ids: [phone.id],
      context: selectionContext,
      origin: "preview",
    });
    setDetails(phone);
  }

  const pages = Math.max(1, Math.ceil(phones.length / pageSize));
  const currentPage = Math.min(page, pages);
  const visiblePhones = phones.slice(
    (currentPage - 1) * pageSize,
    currentPage * pageSize,
  );
  const selectionContext = `${requestKey}:${showSaved ? "saved" : "recommendations"}`;
  const selectedPhone = phoneForPreview(phones, selection, selectionContext);
  function selectPhone(phone: Phone) {
    setSelection({ id: phone.id, context: selectionContext });
    setChatChoice({
      ids: [phone.id],
      context: selectionContext,
      origin: "preview",
    });
    setPreviewExpanded(true);
    if (isCompact) {
      requestAnimationFrame(() =>
        previewRef.current?.scrollIntoView({
          block: "nearest",
          behavior: window.matchMedia("(prefers-reduced-motion: reduce)")
            .matches
            ? "auto"
            : "smooth",
        }),
      );
    }
  }
  function addCompare(phone: Phone) {
    if (compare.some((item) => item.id === phone.id)) {
      setCompareMessage(`${phone.name} 已在对比列表`);
      return;
    }
    clearAdviceTarget();
    setCompare((previous) =>
      previous.some((item) => item.id === phone.id)
        ? previous
        : [...previous, phone],
    );
    setCompareMessage(`已加入 ${phone.name}，当前 ${compare.length + 1} 部`);
  }
  function removeCompare(id: string) {
    clearAdviceTarget();
    setCompare((previous) => previous.filter((item) => item.id !== id));
    setCompareMessage("已移除对比机型");
  }
  function clearAdviceTarget() {
    setChatChoice((previous) =>
      previous?.origin === "advice" ? null : previous,
    );
  }
  function openChat() {
    clearAdviceTarget();
    setChatOpen(true);
  }
  function clearCompare() {
    clearAdviceTarget();
    setCompare([]);
    setCompareMessage("对比列表已清空");
  }
  const draggedPhone = phones.find((phone) => phone.id === draggedId);
  function isInternalPhoneDrag(event: DragEvent<HTMLElement>): boolean {
    return Boolean(
      draggedPhone && event.dataTransfer.types.includes(PHONE_DRAG_TYPE),
    );
  }
  function handleComparisonDragOver(event: DragEvent<HTMLElement>) {
    if (!isInternalPhoneDrag(event)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    setDropActive(true);
  }
  function handleComparisonDragLeave(event: DragEvent<HTMLElement>) {
    if (event.currentTarget.contains(event.relatedTarget as Node | null))
      return;
    const bounds = event.currentTarget.getBoundingClientRect();
    if (
      event.clientX >= bounds.left &&
      event.clientX < bounds.right &&
      event.clientY >= bounds.top &&
      event.clientY < bounds.bottom
    )
      return;
    setDropActive(false);
  }
  function handleComparisonDrop(event: DragEvent<HTMLElement>) {
    event.preventDefault();
    event.stopPropagation();
    if (
      isInternalPhoneDrag(event) &&
      event.dataTransfer.getData(PHONE_DRAG_TYPE) === draggedId
    ) {
      addCompare(draggedPhone!);
    }
    setDropActive(false);
    setDraggedId(null);
  }
  const chatSelectedIds = chatPhoneIds(compare, chatChoice, selectionContext);
  const chatContextKey = JSON.stringify([requestKey, chatSelectedIds]);

  const previewPanel = (
    <SelectedPhonePanel
      phone={selectedPhone}
      expanded={previewExpanded}
      onExpanded={setPreviewExpanded}
      onDetail={openDetail}
      compared={
        selectedPhone != null &&
        compare.some((phone) => phone.id === selectedPhone.id)
      }
      onCompare={(phone) =>
        compare.some((item) => item.id === phone.id)
          ? removeCompare(phone.id)
          : addCompare(phone)
      }
    />
  );

  return (
    <>
      <a className="skip-link" href="#results">
        跳到推荐结果
      </a>
      <header className="site-header">
        <a href="/" className="wordmark" aria-label="挑一部首页">
          挑一部 <span>手机选购</span>
        </a>
        <span className="system-status">
          <i className={meta ? "live-dot" : "live-dot pending"} />
          {meta ? "资料库在线" : "连接资料库"}
        </span>
        <nav aria-label="主导航">
          <button
            className={!showSaved ? "nav-item active" : "nav-item"}
            onClick={() => {
              setShowSaved(false);
              setPage(1);
            }}
          >
            手机推荐
          </button>
          <button
            className={showSaved ? "nav-item active" : "nav-item"}
            onClick={() => {
              setShowSaved(true);
              setPage(1);
            }}
          >
            收藏 <span className="nav-count">{saved.length}</span>
          </button>
          <button className="nav-item" onClick={() => setQualityOpen(true)}>
            数据质量
          </button>
          <button className="quiet-button header-refresh" onClick={startSync}>
            {syncStatus.state === "running" ? "更新进度" : "更新资料"}{" "}
            <span aria-hidden="true">↻</span>
          </button>
        </nav>
      </header>
      <div className={`workbench ${chatOpen && !isCompact ? "chat-open" : ""}`}>
        <main className="catalog-column">
          <section className="filters" aria-label="选购需求">
            <div className="search-row">
              <label className="model-search">
                <SearchIcon />
                <input
                  type="search"
                  aria-label="搜索手机型号"
                  placeholder="搜索手机品牌、型号…"
                  value={preferences.query}
                  onChange={(event) => update({ query: event.target.value })}
                />
              </label>
              <button
                className="primary-button search-button"
                onClick={() =>
                  !invalidBudget
                    ? setReload((value) => value + 1)
                    : budgetRef.current?.focus()
                }
              >
                搜索
              </button>
              <button
                className="quiet-button reset-button"
                onClick={() => {
                  setPreferences({ ...DEFAULT_PREFERENCES });
                  setBudgetInput("");
                  setShowSaved(false);
                  setPage(1);
                }}
              >
                重置
              </button>
            </div>
            <div className="filter-grid">
              <label className="filter-field budget-field">
                <span>最高预算</span>
                <div className="budget-control">
                  <span>¥</span>
                  <input
                    ref={budgetRef}
                    type="text"
                    inputMode="decimal"
                    aria-label="最高预算"
                    placeholder="留空表示预算不限"
                    aria-invalid={invalidBudget}
                    value={budgetInput}
                    onChange={(event) => setBudget(event.target.value)}
                  />
                </div>
                <small className="budget-input-note">
                  可留空，最高预算不限
                </small>
              </label>
              <label className="filter-field">
                <span>品牌</span>
                <select
                  aria-label="品牌偏好"
                  value={
                    preferences.brands.length === 1 ? preferences.brands[0] : ""
                  }
                  onChange={(event) =>
                    update({
                      brands: event.target.value ? [event.target.value] : [],
                    })
                  }
                >
                  <option value="">
                    {preferences.brands.length > 1
                      ? `已选 ${preferences.brands.length} 个品牌`
                      : "所有品牌"}
                  </option>
                  {meta?.brands.map((brand) => (
                    <option value={brand} key={brand}>
                      {brand}
                    </option>
                  ))}
                </select>
              </label>
              <label className="filter-field">
                <span>存储</span>
                <select
                  id="phone-storage"
                  aria-label="至少需要多少存储？"
                  value={preferences.min_storage}
                  onChange={(event) =>
                    update({ min_storage: Number(event.target.value) })
                  }
                >
                  <option value="0">不限容量</option>
                  <option value="128">128GB 及以上</option>
                  <option value="256">256GB 及以上</option>
                  <option value="512">512GB 及以上</option>
                  <option value="1024">1TB 及以上</option>
                </select>
              </label>
              <label className="filter-field">
                <span>购买场景</span>
                <select
                  id="purchase-mode"
                  aria-label="购买场景"
                  value={preferences.purchase_mode}
                  onChange={(event) =>
                    update({
                      purchase_mode: event.target
                        .value as Preferences["purchase_mode"],
                    })
                  }
                >
                  <option value="new">买新机</option>
                  <option value="used">考虑二手</option>
                </select>
              </label>
              <label className="filter-field sort-control">
                <span>排序方式</span>
                <select
                  aria-label="排序方式"
                  value={preferences.sort}
                  onChange={(event) =>
                    update({ sort: event.target.value as SortOrder })
                  }
                >
                  {Object.entries(SORT_LABELS).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="quick-filters">
              <span className="control-caption">主要用途</span>
              <div className="purpose-grid">
                {PURPOSES.map((purpose) => (
                  <button
                    className={
                      preferences.priorities.includes(purpose.id)
                        ? "purpose selected"
                        : "purpose"
                    }
                    aria-pressed={preferences.priorities.includes(purpose.id)}
                    key={purpose.id}
                    onClick={() =>
                      update({
                        priorities: preferences.priorities.includes(purpose.id)
                          ? preferences.priorities.filter(
                              (item) => item !== purpose.id,
                            )
                          : [...preferences.priorities, purpose.id],
                      })
                    }
                  >
                    {purpose.title}
                  </button>
                ))}
              </div>
              <details className="more-filters">
                <summary>更多条件</summary>
                <div className="more-filter-content">
                  <label className="filter-field">
                    <span>最低预算</span>
                    <input
                      type="number"
                      min="0"
                      step="100"
                      aria-label="最低预算"
                      value={preferences.budget_min}
                      onChange={(event) =>
                        update({ budget_min: Number(event.target.value) })
                      }
                    />
                  </label>
                  <label className="filter-field">
                    <span>系统</span>
                    <select
                      id="phone-os"
                      value={preferences.os}
                      onChange={(event) =>
                        update({ os: event.target.value as Preferences["os"] })
                      }
                    >
                      <option value="all">都可以</option>
                      <option value="Android">Android</option>
                      <option value="iOS">iOS</option>
                      <option value="HarmonyOS">HarmonyOS</option>
                    </select>
                  </label>
                  <div className="budget-presets">
                    {[
                      [0, 2000],
                      [2000, 3500],
                      [3500, 5000],
                      [5000, 8000],
                    ].map(([min, max]) => (
                      <button
                        key={max}
                        className={
                          preferences.budget_min === min &&
                          preferences.budget_max === max
                            ? "preset selected"
                            : "preset"
                        }
                        aria-pressed={
                          preferences.budget_min === min &&
                          preferences.budget_max === max
                        }
                        onClick={() => setBudget(String(max), min)}
                      >
                        {min === 0
                          ? "2 千以内"
                          : `${min / 1000}–${max / 1000} 千`}
                      </button>
                    ))}
                  </div>
                  <label className="check-label">
                    <input
                      type="checkbox"
                      checked={preferences.compact}
                      onChange={(event) =>
                        update({ compact: event.target.checked })
                      }
                    />
                    <span>更喜欢轻巧便携</span>
                  </label>
                  <label className="check-label">
                    <input
                      type="checkbox"
                      checked={preferences.include_history}
                      onChange={(event) =>
                        update({ include_history: event.target.checked })
                      }
                    />
                    <span>
                      也看看历史机型
                      <small>历史价格单独标记，不是二手报价</small>
                    </span>
                  </label>
                  <div className="multi-brand-filter">
                    <label className="filter-field">
                      <span>多品牌选择</span>
                      <input
                        type="search"
                        aria-label="搜索品牌"
                        placeholder="查找品牌"
                        value={brandSearch}
                        onChange={(event) => setBrandSearch(event.target.value)}
                      />
                    </label>
                    <div className="brand-list">
                      {brands.map((brand) => (
                        <button
                          className={
                            preferences.brands.includes(brand)
                              ? "brand selected"
                              : "brand"
                          }
                          aria-pressed={preferences.brands.includes(brand)}
                          onClick={() => toggleBrand(brand)}
                          key={brand}
                        >
                          {brand}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              </details>
            </div>
            {invalidBudgetRange && (
              <p className="field-error" role="alert">
                最低预算不能高于最高预算。
              </p>
            )}
            {!budgetValid && (
              <p className="field-error" role="alert">
                预算留空表示不限；填写时请输入大于 0 的数字。
              </p>
            )}
          </section>
          {isCompact && (
            <div className="mobile-selection-panel" ref={previewRef}>
              {previewPanel}
            </div>
          )}
          <section
            className="results"
            id="results"
            aria-labelledby="results-title"
            aria-busy={loading && !showSaved}
          >
            <div className="results-heading">
              <div>
                <h1 id="results-title">
                  {showSaved
                    ? "我的收藏"
                    : searchMode
                      ? "搜索结果"
                      : SORT_LABELS[preferences.sort]}
                </h1>
                <p>
                  {showSaved
                    ? `当前浏览器保存的 ${saved.length} 部手机`
                    : invalidBudget
                      ? "请修正预算后继续查看"
                      : searchMode
                        ? `匹配目录 ${resultTotal} 款 · 已加载 ${phones.length} 款 · 当前可推荐 ${currentData?.total || 0} 款`
                        : `符合条件 ${resultTotal} 款 · 已加载 ${phones.length} 款${preferences.budget_max === null ? " · 预算不限" : ""}`}
                </p>
              </div>
              <span className="loading-label" role="status">
                {loading && !showSaved ? (
                  <>
                    <span className="spinner" />
                    正在匹配
                  </>
                ) : currentData?.updated_at ? (
                  `资料更新 ${dateLabel(currentData.updated_at)}`
                ) : meta ? (
                  `${Number(meta.summary.current_records || 0).toLocaleString()} 条当前目录配置`
                ) : (
                  "正在读取资料"
                )}
              </span>
            </div>
            {!showSaved && !searchMode && (
              <details className="ranking-guide">
                <summary>推荐依据</summary>
                <p>
                  {rankingExplanation(
                    preferences.purchase_mode,
                    preferences.budget_max,
                  )}
                </p>
                <p>
                  综合推荐分比较当前选择，需求匹配分衡量规格对用途的适合程度，均不是品质测评分。
                </p>
              </details>
            )}
            {searchMode && (
              <p className="catalogue-note" role="status">
                搜索展示全部匹配目录，包含历史、待上市、报价待核实与超预算机型；目录资料不等于购买推荐。容量等显式条件仍生效，可点详细参数核对来源。
              </p>
            )}
            {!showSaved && preferences.purchase_mode === "used" && (
              <p className="purchase-mode-note" role="status">
                二手机型参考 ·
                价格仍是新机来源参考价，没有二手报价或库存。请另查实际二手价格、成色与保修。
              </p>
            )}
            {showSaved && storageError && (
              <p className="inline-error" role="status">
                {storageError}
              </p>
            )}
            {error && (
              <div className="error-panel" role="alert">
                <strong>资料暂未加载完成</strong>
                <p>{error}</p>
                <button
                  className="primary-button"
                  onClick={() => setReload((value) => value + 1)}
                >
                  重新加载
                </button>
              </div>
            )}
            {!error && invalidBudget && !showSaved ? (
              <div className="empty-state">
                <h2>请修正预算</h2>
                <p>
                  {invalidBudgetRange
                    ? "最低预算不能大于最高预算。"
                    : "预算留空表示不限；填写时请输入大于 0 的数字。"}
                </p>
              </div>
            ) : !error && phones.length === 0 ? (
              <div className="empty-state">
                <SearchIcon />
                <h2>
                  {loading
                    ? "正在匹配手机"
                    : showSaved
                      ? "还没有收藏"
                      : searchMode
                        ? "没有找到匹配的目录机型"
                        : "没有符合全部条件的机型"}
                </h2>
                <p>
                  {loading
                    ? "读取来源参数，计算需求与选购策略。"
                    : showSaved
                      ? "点击卡片上的收藏，把候选留在这里。"
                      : currentData?.discovery?.phones.length
                        ? "下方新机资料里仍有相关机型。查看被排除的原因，或调整预算与容量。"
                        : "可以调整预算、存储容量、系统或品牌条件。"}
                </p>
                {!showSaved && !loading && (
                  <button
                    className="quiet-button"
                    onClick={() =>
                      update({ min_storage: 0, brands: [], os: "all" })
                    }
                  >
                    放宽容量与品牌
                  </button>
                )}
              </div>
            ) : (
              <>
                <div className="phone-grid">
                  {visiblePhones.map((phone) => {
                    const compared = compare.some(
                      (item) => item.id === phone.id,
                    );
                    const isSaved = saved.some((item) => item.id === phone.id);
                    return (
                      <article
                        className={`phone-card gallery-card ${selectedPhone?.id === phone.id ? "is-selected" : ""} ${draggedId === phone.id ? "is-dragging" : ""}`}
                        key={phone.id}
                        draggable
                        onDragStart={(event) => {
                          event.dataTransfer.setData(PHONE_DRAG_TYPE, phone.id);
                          event.dataTransfer.setData("text/plain", phone.id);
                          event.dataTransfer.effectAllowed = "copy";
                          setDraggedId(phone.id);
                        }}
                        onDragEnd={() => {
                          setDraggedId(null);
                          setDropActive(false);
                        }}
                      >
                        <div className="card-image-wrap">
                          <button
                            className="card-image-button"
                            aria-label={`预览 ${phone.name}`}
                            aria-pressed={selectedPhone?.id === phone.id}
                            onClick={() => selectPhone(phone)}
                          >
                            <PhonePicture phone={phone} />
                            <span className="image-selection-label">
                              {selectedPhone?.id === phone.id
                                ? "正在查看"
                                : "点击查看"}
                            </span>
                          </button>
                          <button
                            className={
                              isSaved ? "save-button saved" : "save-button"
                            }
                            aria-label={`${isSaved ? "取消收藏" : "收藏"} ${phone.name}`}
                            aria-pressed={isSaved}
                            onClick={() =>
                              setSaved((previous) =>
                                toggleSaved(previous, phone),
                              )
                            }
                          >
                            <SaveIcon filled={isSaved} />
                          </button>
                        </div>
                        <div className="phone-card-content">
                          <div className="card-identity">
                            <span className="phone-brand">
                              {phone.brand}
                              <small>
                                {phone.price == null
                                  ? "配置价待核实"
                                  : priceStatusLabel(phone)}
                              </small>
                            </span>
                            <span className="phone-price">
                              {phone.price == null
                                ? "价格待核实"
                                : `¥${phone.price.toLocaleString()}`}
                            </span>
                          </div>
                          <h2>{phone.name}</h2>
                          <div className="quick-specs">
                            <span>{numberSpec(phone.display_inches, "″")}</span>
                            <span>{numberSpec(phone.storage_gb, "GB")}</span>
                            <span>{numberSpec(phone.battery_mah, "mAh")}</span>
                          </div>
                          {searchMode ? (
                            <div className="catalogue-card-status">
                              <span>{catalogueStatusLabel(phone)}</span>
                              {(phone.catalogue_reasons || [])
                                .slice(0, 2)
                                .map((reason, index) => (
                                  <p key={index}>{reason}</p>
                                ))}
                            </div>
                          ) : (
                            <div className="card-scores">
                              <span className="match-badge">
                                {phone.recommendation_score != null
                                  ? `${Math.round(phone.recommendation_score)} /100 综合推荐`
                                  : phone.score != null
                                    ? `${Math.round(phone.score)}% 需求匹配`
                                    : "已收藏"}
                              </span>
                              {phone.recommendation_score != null &&
                                phone.score != null && (
                                  <span className="usage-match-reference">
                                    匹配 {Math.round(phone.score)}%
                                  </span>
                                )}
                            </div>
                          )}
                          <div className="card-actions">
                            <button
                              className="card-detail"
                              onClick={() => openDetail(phone)}
                            >
                              详细参数
                            </button>
                            <button
                              className={
                                compared
                                  ? "compare-button selected"
                                  : "compare-button"
                              }
                              aria-label={`${compared ? "移出对比" : "加入对比"} ${phone.name}`}
                              aria-pressed={compared}
                              onClick={() =>
                                compared
                                  ? removeCompare(phone.id)
                                  : addCompare(phone)
                              }
                            >
                              {compared ? "已加入 ✓" : "+ 对比"}
                            </button>
                          </div>
                        </div>
                      </article>
                    );
                  })}
                </div>
                {phones.length > 0 && (
                  <div
                    className="pagination"
                    aria-label={searchMode ? "搜索分页" : "推荐分页"}
                  >
                    <span>
                      第 {(currentPage - 1) * pageSize + 1}–
                      {Math.min(currentPage * pageSize, phones.length)} 项 ·
                      已加载 {phones.length} 项
                      {!showSaved && resultTotal > phones.length && (
                        <small>
                          {searchMode ? "匹配目录" : "符合条件"}共 {resultTotal}{" "}
                          款，当前已加载 {phones.length} 款
                        </small>
                      )}
                    </span>
                    <div className="page-controls">
                      <button
                        aria-label="上一页"
                        disabled={currentPage === 1}
                        onClick={() => setPage((value) => value - 1)}
                      >
                        上一页
                      </button>
                      {Array.from(
                        { length: pages },
                        (_, index) => index + 1,
                      ).map((value) => (
                        <button
                          key={value}
                          className={value === currentPage ? "active" : ""}
                          aria-label={`第 ${value} 页`}
                          aria-current={
                            value === currentPage ? "page" : undefined
                          }
                          onClick={() => setPage(value)}
                        >
                          {value}
                        </button>
                      ))}
                      <button
                        aria-label="下一页"
                        disabled={currentPage === pages}
                        onClick={() => setPage((value) => value + 1)}
                      >
                        下一页
                      </button>
                      <select
                        aria-label="每页显示"
                        value={pageSize}
                        onChange={(event) => {
                          setPageSize(Number(event.target.value));
                          setPage(1);
                        }}
                      >
                        <option value="20">20 / 页</option>
                        <option value="40">40 / 页</option>
                        <option value="60">60 / 页</option>
                      </select>
                    </div>
                  </div>
                )}
              </>
            )}
            {!showSaved && !loading && currentData?.coverage.excluded && (
              <FilterCoverage
                coverage={currentData.coverage}
                onBudget={(value) => setBudget(String(Math.ceil(value)))}
              />
            )}
            {!showSaved &&
              currentData?.discovery &&
              currentData.discovery.phones.length > 0 && (
                <details
                  className="discovery-section"
                  open={phones.length === 0}
                >
                  <summary>
                    新机资料补充{" "}
                    <span>
                      {currentData.discovery.total} 款 · 含超预算与待核验配置
                    </span>
                  </summary>
                  <NewReleaseShelf
                    discovery={currentData.discovery}
                    preferences={preferences}
                    onDetail={openDetail}
                    onBudget={(value) => setBudget(String(Math.ceil(value)))}
                  />
                </details>
              )}
            {phones.length > 0 && (
              <p className="results-footnote">
                价格为来源参考报价，非成交价。未知规格不会填成零，推荐分不等同于实测品质。
              </p>
            )}
          </section>
        </main>
        <aside
          className={`comparison-rail selection-comparison-panel ${draggedPhone ? "ready-to-drop" : ""} ${dropActive ? "drop-active" : ""}`}
          aria-labelledby="compare-title"
          onDragEnter={handleComparisonDragOver}
          onDragOver={handleComparisonDragOver}
          onDragLeave={handleComparisonDragLeave}
          onDrop={handleComparisonDrop}
        >
          {draggedPhone && (
            <p className="rail-drop-notice" role="status">
              右侧任意位置松手，即可加入对比{" "}
              <span>已选 {compare.length} 部</span>
            </p>
          )}
          {!isCompact && !chatOpen && (
            <div ref={previewRef}>{previewPanel}</div>
          )}
          <div className="rail-comparison">
            <div className="comparison-heading">
              <CompareIcon />
              <div>
                <h2 id="compare-title">参数对比</h2>
                <p>拖到右侧任意位置，或点击卡片「+ 对比」</p>
              </div>
              <span>{compare.length} 部</span>
            </div>
            <div
              className={`comparison-dropzone ${dropActive ? "drop-active" : ""} ${draggedId ? "ready-to-drop" : ""}`}
              aria-label="手机对比投放区"
            >
              {compare.length === 0 ? (
                <div className="drop-placeholder">
                  <CompareIcon />
                  <strong>拖到这里开始比较</strong>
                  <span>数量不限 · 参数表横向滚动</span>
                  <small>也可用卡片按钮加入，支持键盘操作</small>
                </div>
              ) : (
                compare.map((phone) => (
                  <article className="comparison-item" key={phone.id}>
                    <PhonePicture phone={phone} compact />
                    <div>
                      <span>{phone.brand}</span>
                      <strong>{phone.name}</strong>
                      <small>
                        {phone.price == null
                          ? "价格待核实"
                          : `¥${phone.price.toLocaleString()} · ${priceStatusLabel(phone)}`}
                      </small>
                    </div>
                    <button
                      aria-label={`从对比中移除 ${phone.name}`}
                      onClick={() => removeCompare(phone.id)}
                    >
                      ×
                    </button>
                  </article>
                ))
              )}
              {compare.length > 0 && (
                <div className="drop-next">继续拖入，或从卡片加入下一部</div>
              )}
            </div>
            <div className="comparison-actions">
              <button
                className="primary-button"
                disabled={compare.length < 2 || invalidBudget}
                onClick={() => setCompareOpen(true)}
              >
                开始对比 · {compare.length} 部
              </button>
              {compare.length > 0 && (
                <button className="quiet-button" onClick={clearCompare}>
                  清空
                </button>
              )}
            </div>
            <p className="sr-only" role="status" aria-live="polite">
              {compareMessage}
            </p>
          </div>
          {!chatOpen && (
            <div className="rail-advisor">
              <div>
                <ChatIcon />
                <h3>AI 选购顾问</h3>
              </div>
              <p>
                {compare.length
                  ? `围绕已选 ${compare.length} 部，解释优势和取舍。`
                  : "聊聊你的需求，或比较当前真实候选。"}
              </p>
              <button className="quiet-button" onClick={openChat}>
                打开选购顾问 <span aria-hidden="true">↗</span>
              </button>
              <small>只有发送问题后才调用 AI，预算可以留空</small>
            </div>
          )}
          {!chatOpen && (
            <p className="rail-note">
              官网 / 中关村在线资料
              <br />
              实际价格、库存与售后请核对购买渠道。
            </p>
          )}
          <AdvisorChat
            open={chatOpen}
            compact={isCompact}
            onClose={() => setChatOpen(false)}
            preferences={
              !invalidBudget ? requestPreferences(preferences) : null
            }
            invalidPreferences={invalidBudget}
            selectedIds={chatSelectedIds}
            candidatePhones={resultPhones(currentData, preferences.query)}
            catalogueContext={preferences.query.trim().length > 0}
            contextKey={chatContextKey}
            budgetInput={budgetInput}
            onBudget={setBudget}
            preset={chatPreset}
          />
          <button
            className="ai-launcher"
            aria-label={chatOpen ? "关闭 AI 选购顾问" : "打开 AI 选购顾问"}
            aria-expanded={chatOpen}
            style={draggedId ? { pointerEvents: "none" } : undefined}
            onClick={() => (chatOpen ? setChatOpen(false) : openChat())}
            title={chatOpen ? "关闭选购顾问" : "打开选购顾问"}
          >
            {chatOpen ? <span aria-hidden="true">×</span> : <ChatIcon />}
          </button>
        </aside>
      </div>
      <footer className="site-footer">
        <span>挑一部 · 手机选购工作台</span>
        <button onClick={() => setQualityOpen(true)}>数据来源与质量 ↗</button>
        <span>参数有来源，推荐有依据。</span>
      </footer>
      <div className="mobile-compare-bar">
        <span>对比 {compare.length} 部</span>
        {compare.length > 0 && (
          <button className="quiet-button" onClick={clearCompare}>
            清空
          </button>
        )}
        <button
          className="quiet-button mobile-advisor-button"
          aria-label="打开 AI 选购顾问"
          onClick={openChat}
        >
          AI 顾问
        </button>
        {compare.length >= 2 && (
          <button
            className="primary-button"
            disabled={compare.length < 2 || invalidBudget}
            onClick={() => setCompareOpen(true)}
          >
            开始对比
          </button>
        )}
      </div>
      {syncStatus.state === "running" && !syncOpen && (
        <button className="background-sync" onClick={() => setSyncOpen(true)}>
          <span className="spinner" />
          资料更新中 · 查看进度
        </button>
      )}
      {details && (
        <DetailPanel
          initialPhone={details}
          onClose={() => setDetails(null)}
          onExplain={openAdvice}
        />
      )}
      {compareOpen && !invalidBudget && (
        <ComparePanel
          phones={compare}
          preferences={preferences}
          onClose={() => setCompareOpen(false)}
          onExplain={openAdvice}
        />
      )}
      {qualityOpen && (
        <QualityPanel
          onClose={() => setQualityOpen(false)}
          onSync={startSync}
        />
      )}
      {syncOpen && (
        <SyncPanel status={syncStatus} onClose={() => setSyncOpen(false)} />
      )}
    </>
  );
}

function SelectedPhonePanel({
  phone,
  expanded,
  onExpanded,
  onDetail,
  compared,
  onCompare,
}: {
  phone: Phone | null;
  expanded: boolean;
  onExpanded: (expanded: boolean) => void;
  onDetail: (phone: Phone) => void;
  compared: boolean;
  onCompare: (phone: Phone) => void;
}) {
  return (
    <details
      className="selected-phone-panel"
      open={expanded}
      onToggle={(event) => onExpanded(event.currentTarget.open)}
    >
      <summary>
        <span>
          <small>当前查看</small>
          <strong>{phone?.name || "选择一部手机"}</strong>
        </span>
        <span className="preview-collapse-label">
          {expanded ? "收起" : "展开"} <span aria-hidden="true">⌄</span>
        </span>
      </summary>
      {phone ? (
        <div className="selected-phone-preview" key={phone.id}>
          <PhonePicture phone={phone} preview />
          <div className="preview-identity">
            <span>{phone.brand}</span>
            <strong>
              {phone.price == null
                ? "价格待核实"
                : `¥${phone.price.toLocaleString()}`}
            </strong>
          </div>
          <p className="preview-price-note">
            {phone.price == null ? "具体配置报价未知" : priceStatusLabel(phone)}{" "}
            · {releaseLabel(phone)}
          </p>
          <dl className="preview-specs">
            <div>
              <dt>屏幕</dt>
              <dd>{numberSpec(phone.display_inches, "″")}</dd>
            </div>
            <div>
              <dt>存储</dt>
              <dd>{numberSpec(phone.storage_gb, "GB")}</dd>
            </div>
            <div>
              <dt>电池</dt>
              <dd>{numberSpec(phone.battery_mah, "mAh")}</dd>
            </div>
          </dl>
          <p className="preview-soc">{phone.soc || "处理器待核实"}</p>
          {phone.catalogue_reasons ? (
            <div className="preview-catalogue-status">
              <strong>{catalogueStatusLabel(phone)}</strong>
              {phone.catalogue_reasons.map((reason, index) => (
                <p key={index}>{reason}</p>
              ))}
              {(phone.catalogue_variant_count || 0) > 1 && (
                <p>
                  匹配 {phone.catalogue_variant_count}{" "}
                  个配置，此卡显示代表版本。
                </p>
              )}
            </div>
          ) : (
            <details className="preview-reasons">
              <summary>
                推荐依据
                {phone.recommendation_score != null && (
                  <span>{Math.round(phone.recommendation_score)} /100</span>
                )}
              </summary>
              {phone.score != null && (
                <p>需求匹配 {Math.round(phone.score)}%</p>
              )}
              <div className="ranking-reasons">
                {rankingHighlights(phone).map((reason, index) => (
                  <p key={index}>{reason}</p>
                ))}
              </div>
              <p>策略分用于比较当前候选，不是品质测评分。</p>
            </details>
          )}
          <div className="preview-actions">
            <button className="quiet-button" onClick={() => onDetail(phone)}>
              详细资料 ↗
            </button>
            <button
              className={
                compared ? "compare-button selected" : "compare-button"
              }
              aria-label={`${compared ? "移出对比" : "加入对比"} ${phone.name}（当前查看）`}
              aria-pressed={compared}
              onClick={() => onCompare(phone)}
            >
              {compared ? "已加入 ✓" : "+ 加入对比"}
            </button>
          </div>
          <p className="preview-source">
            {sourceLabel(phone)} · {dateLabel(phone.fetched_at)}
            {safeSource(phone.source_url) && (
              <a
                href={safeSource(phone.source_url)}
                target="_blank"
                rel="noreferrer"
              >
                核对来源 ↗
              </a>
            )}
          </p>
        </div>
      ) : (
        <p className="preview-empty">
          浏览或搜索手机，再点击图片查看资料。预算可以留空，选择手机与加入对比分开操作。
        </p>
      )}
    </details>
  );
}

function PhonePicture({
  phone,
  compact = false,
  preview = false,
}: {
  phone: Phone;
  compact?: boolean;
  preview?: boolean;
}) {
  const [failedURL, setFailedURL] = useState<string | undefined>();
  const imageURL = safeSource(phone.image_url);
  return (
    <div
      className={
        compact
          ? "phone-picture comparison-thumb"
          : preview
            ? "phone-picture selected-preview-image"
            : "phone-picture"
      }
    >
      {imageURL && failedURL !== imageURL ? (
        <img
          src={imageURL}
          alt={`${phone.name} 产品图片`}
          loading="lazy"
          draggable={false}
          onError={() => setFailedURL(imageURL)}
        />
      ) : (
        <span className="no-picture">暂无来源图片</span>
      )}
    </div>
  );
}

function SearchIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="m16 16 4 4" />
    </svg>
  );
}
function CompareIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <rect x="3" y="4" width="7" height="16" rx="1.5" />
      <rect x="14" y="4" width="7" height="16" rx="1.5" />
      <path d="M6 17h1m10 0h1" />
    </svg>
  );
}
function ChatIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M20 11.5a8 8 0 0 1-8 8H8l-4 2v-5a8 8 0 1 1 16-5Z" />
      <path d="M8 9h8M8 13h5" />
    </svg>
  );
}
function SaveIcon({ filled }: { filled: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24"
      aria-hidden="true"
      style={{ fill: filled ? "currentColor" : "none" }}
    >
      <path d="M6 3h12v18l-6-4-6 4Z" />
    </svg>
  );
}

function NewReleaseShelf({
  discovery,
  preferences,
  onDetail,
  onBudget,
}: {
  discovery: NonNullable<Recommendations["discovery"]>;
  preferences: Preferences;
  onDetail: (phone: Phone) => void;
  onBudget: (value: number) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const visible = expanded
    ? discovery.phones
    : discoveryOverview(discovery.phones);
  return (
    <section className="new-release-shelf" aria-labelledby="new-release-title">
      <div className="new-release-heading">
        <div>
          <p className="discovery-kicker">来自官网与新品入口</p>
          <h3 id="new-release-title">
            新机发现<span>{discovery.total} 款</span>
          </h3>
        </div>
        <span className="discovery-independent">独立于预算推荐</span>
      </div>
      <p className="discovery-intro">
        先看品牌概览，展开全部按来源上市时间排列。价格未核实、容量未知或超预算也能看见；目录身份不代表已上市，来源没有日期时保持未知。
      </p>
      <div className="discovery-grid">
        {visible.map((phone) => (
          <article className="discovery-card" key={phone.id}>
            <p className="discovery-source">
              {phone.origin === "official" ? "官网当前目录" : "源站新品入口"}
              <span>
                {phone.discovery_status === "upcoming"
                  ? "待上市"
                  : phone.discovery_status === "within_budget"
                    ? "预算内有资料"
                    : "条件待核验"}
              </span>
            </p>
            <h4>{phone.name}</h4>
            <p className="discovery-date">
              来源上市时间 · {releaseLabel(phone)}
            </p>
            <p className="discovery-price">{discoveryPriceLabel(phone)}</p>
            <p className="discovery-capacity">
              存储 {numberSpec(phone.storage_gb, "GB")}
              <span>处理器 {phone.soc || "待核实"}</span>
            </p>
            <div className="discovery-reasons">
              {(phone.discovery_reasons || []).map((reason, index) => (
                <p key={index}>{reason}</p>
              ))}
            </div>
            <div className="discovery-actions">
              <button onClick={() => onDetail(phone)}>查看资料 ↗</button>
              {phone.price != null &&
                preferences.budget_max !== null &&
                phone.price > preferences.budget_max &&
                phone.discovery_codes?.includes("over_budget") &&
                !phone.discovery_codes.includes("upcoming") && (
                  <button onClick={() => onBudget(phone.price!)}>
                    预算放宽至 ¥{Math.ceil(phone.price).toLocaleString()}
                  </button>
                )}
            </div>
            <p className="discovery-foot">
              {sourceLabel(phone)}
              <span>
                {safeSource(phone.source_url) && (
                  <a
                    href={safeSource(phone.source_url)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    核对官网/来源 ↗
                  </a>
                )}
              </span>
            </p>
          </article>
        ))}
      </div>
      {discovery.phones.length > 6 && (
        <button
          className="show-discoveries"
          onClick={() => setExpanded((value) => !value)}
        >
          {expanded
            ? "收起发现列表 ↑"
            : `查看全部 ${discovery.total} 款目录机型 ↓`}
        </button>
      )}
    </section>
  );
}

function FilterCoverage({
  coverage,
  onBudget,
}: {
  coverage: Recommendations["coverage"];
  onBudget: (value: number) => void;
}) {
  const excluded = coverage.excluded || {};
  const messages = [
    excluded.over_budget ? `${excluded.over_budget} 款超过预算` : "",
    excluded.under_budget ? `${excluded.under_budget} 款低于预算下限` : "",
    coverage.unknown_price ? `${coverage.unknown_price} 款配置价格待核实` : "",
    (excluded.unknown_storage || 0) + (excluded.insufficient_storage || 0) > 0
      ? `${(excluded.unknown_storage || 0) + (excluded.insufficient_storage || 0)} 款容量未知或不符合要求`
      : "",
    excluded.upcoming ? `${excluded.upcoming} 款尚未上市/含未来日期` : "",
  ].filter(Boolean);
  if (messages.length === 0) return null;
  return (
    <div className="filter-coverage" role="status">
      <p>
        <strong>有机型被条件排除了</strong>
        <span>{messages.join("；")}。它们不会自动进入预算推荐。</span>
      </p>
      {(excluded.over_budget || 0) > 0 &&
        coverage.budget_suggestion != null && (
          <button onClick={() => onBudget(coverage.budget_suggestion!)}>
            预算放宽至 ¥{Math.ceil(coverage.budget_suggestion).toLocaleString()}{" "}
            ↗
          </button>
        )}
    </div>
  );
}
