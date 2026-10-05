import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { api } from "./api";
import {
  COMPARE_FIELDS,
  dateLabel,
  isHistoricalPrice,
  discoveryPriceLabel,
  sourceLabel,
  requestPreferences,
  safeSource,
  variantLabel,
} from "./helpers";
import type {
  Meta,
  Phone,
  Preferences,
  QualityReport,
  SyncStatus,
} from "./types";

export function VariantSelector({
  phone,
  onChange,
  loading = false,
  error = "",
  disabled = false,
}: {
  phone: Phone;
  onChange: (id: string) => void;
  loading?: boolean;
  error?: string;
  disabled?: boolean;
}) {
  const variants = phone.variant_summary || [];
  if (variants.length < 2) return null;
  const warning =
    phone.budget_warning ||
    (phone.matches_preferences === false ||
    phone.recommendation_eligible === false
      ? phone.variant_reasons?.[0]
      : undefined);
  return (
    <div className="variant-picker">
      <label>
        <span>{phone.variant_count || variants.length} 个配置</span>
        <select
          className="variant-select"
          aria-label={`选择 ${phone.family_name || phone.name} 的配置`}
          value={phone.id}
          disabled={disabled || loading}
          onChange={(event) => onChange(event.target.value)}
        >
          {!variants.some((variant) => variant.id === phone.id) && (
            <option value={phone.id} disabled>
              选择容量配置
            </option>
          )}
          {variants.map((variant) => (
            <option value={variant.id} key={variant.id}>
              {variantLabel(variant)}
              {variant.matches_preferences === false
                ? " · 不符当前筛选"
                : variant.recommendation_eligible === false &&
                    variant.price != null
                  ? " · 仅资料"
                  : ""}
            </option>
          ))}
        </select>
      </label>
      {loading ? (
        <p className="variant-status" role="status">
          正在切换配置…
        </p>
      ) : error ? (
        <p className="variant-status variant-error" role="alert">
          {error}
        </p>
      ) : warning ? (
        <p className="variant-status">{warning}</p>
      ) : null}
    </div>
  );
}

export function Dialog({
  title,
  eyebrow,
  children,
  onClose,
  wide = false,
  drawer = false,
}: {
  title: string;
  eyebrow?: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
  drawer?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const dialog = ref.current!;
    dialog.showModal();
    return () => {
      dialog.close();
    };
  }, []);
  return (
    <dialog
      ref={ref}
      className={`panel-dialog ${wide ? "wide-dialog" : ""} ${drawer ? "advisor-drawer" : ""}`}
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="dialog-inner">
        <button
          className="modal-close"
          aria-label={`关闭${title}`}
          onClick={onClose}
        >
          ×
        </button>
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <h2 className="dialog-title" id={titleId}>
          {title}
        </h2>
        {children}
      </div>
    </dialog>
  );
}

export function DetailPanel({
  initialPhone,
  onClose,
  onExplain,
  onVariant,
  variantLoading,
  variantError,
  invalidPreferences,
}: {
  initialPhone: Phone;
  onClose: () => void;
  onExplain: (phones: Phone[]) => void;
  onVariant: (id: string) => void;
  variantLoading: boolean;
  variantError: string;
  invalidPreferences: boolean;
}) {
  const [loadedPhone, setLoadedPhone] = useState(initialPhone);
  const phone = loadedPhone.id === initialPhone.id ? loadedPhone : initialPhone;
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    setLoadedPhone(initialPhone);
    setError("");
    api<{ phone: Phone }>(
      `/api/phones/${encodeURIComponent(initialPhone.id)}`,
      { signal: controller.signal },
    )
      .then((result) => {
        if (!controller.signal.aborted)
          setLoadedPhone({ ...initialPhone, ...result.phone });
      })
      .catch((e: Error) => {
        if (e.name !== "AbortError") setError(e.message);
      });
    return () => controller.abort();
  }, [initialPhone]);
  return (
    <Dialog title={phone.name} eyebrow="参数与来源" onClose={onClose}>
      <div className="detail-subtitle">
        <span>{phone.brand}</span>
        <span>{discoveryPriceLabel(phone)}</span>
        <span>
          {phone.availability === "historical" ? "历史资料" : "公开目录机型"}
        </span>
      </div>
      <VariantSelector
        phone={phone}
        loading={variantLoading}
        error={variantError}
        disabled={invalidPreferences}
        onChange={onVariant}
      />
      {phone.origin === "official" && (
        <p className="provenance-note">
          当前资料来自{sourceLabel(phone)}
          。官网目录身份不等于今天发布；日期未知时不会用采集日代替。官网起价不代表选定容量版本的价格。
        </p>
      )}
      {(phone.discovery_reasons?.length || 0) > 0 && (
        <div className="detail-discovery-reasons">
          {phone.discovery_reasons?.map((reason, index) => (
            <p key={index}>{reason}</p>
          ))}
        </div>
      )}
      {error && (
        <p className="inline-error" role="alert">
          最新资料读取失败：{error}，下方显示已加载资料。
        </p>
      )}
      {phone.score_applicable !== false && phone.score != null && (
        <div className="detail-match">
          <span>
            {Math.round(phone.score)}
            <small>% 需求匹配</small>
          </span>
          <p>
            依据预算、用途与已核实参数计算。未知参数保持未知，匹配分不是实测排名。
          </p>
        </div>
      )}
      <dl className="spec-grid">
        {COMPARE_FIELDS.map((field) => (
          <div key={field.label}>
            <dt>{field.label}</dt>
            <dd>{field.value(phone)}</dd>
          </div>
        ))}
      </dl>
      <div className="detail-reasons">
        {(phone.reasons || []).length > 0 && (
          <section>
            <h3>为什么适合</h3>
            {phone.reasons?.map((value, i) => (
              <p key={i}>✓ {value}</p>
            ))}
          </section>
        )}
        {(phone.tradeoffs || []).length > 0 && (
          <section>
            <h3>需要接受的取舍</h3>
            {phone.tradeoffs?.map((value, i) => (
              <p key={i}>{value}</p>
            ))}
          </section>
        )}
      </div>
      <p className="provenance-note">
        {phone.price == null
          ? "具体配置价格待核实，来源起价不会直接用于预算推荐。"
          : isHistoricalPrice(phone)
            ? "这条价格来自历史资料，请重新核实购买渠道报价。"
            : "这里的价格是来源参考价，实际成交价请以购买渠道为准。"}{" "}
        参数与价格分别保留来源，更新日期不会改变历史字段的标记。
      </p>
      <details className="raw-details">
        <summary>
          查看来源参数原文
          <span>{Object.keys(phone.specs || {}).length} 项</span>
        </summary>
        <dl className="raw-specs">
          {Object.entries(phone.specs || {}).map(([key, value]) => {
            const source = phone.specs_sources?.[key];
            return (
              <div key={key}>
                <dt>{key}</dt>
                <dd>
                  <span>
                    {typeof value === "object"
                      ? JSON.stringify(value)
                      : String(value)}
                  </span>
                  <small className="field-provenance">
                    {source?.origin === "legacy" ? (
                      <span className="historical-tag">历史资料</span>
                    ) : source?.fetched_at ? (
                      `核验 ${dateLabel(source.fetched_at)}`
                    ) : (
                      "逐字段日期未知"
                    )}
                    {safeSource(source?.source_url) && (
                      <a
                        href={safeSource(source?.source_url)}
                        target="_blank"
                        rel="noreferrer"
                      >
                        来源 ↗
                      </a>
                    )}
                  </small>
                </dd>
              </div>
            );
          })}
        </dl>
      </details>
      {phone.issues && phone.issues.length > 0 && (
        <details className="raw-details">
          <summary>
            资料中仍待核实的地方<span>{phone.issues.length} 项</span>
          </summary>
          <ul className="issue-list">
            {phone.issues.map((issue, i) => (
              <li key={i}>{issue.message}</li>
            ))}
          </ul>
        </details>
      )}
      <div className="dialog-actions">
        {safeSource(phone.source_url) && (
          <a
            className="source-link"
            href={safeSource(phone.source_url)}
            target="_blank"
            rel="noreferrer"
          >
            查看来源网页 ↗
          </a>
        )}
        <button
          className="primary-button"
          disabled={variantLoading}
          onClick={() => onExplain([phone])}
        >
          向顾问询问这部手机
        </button>
      </div>
    </Dialog>
  );
}

export function ComparePanel({
  phones: selectedPhones,
  preferences,
  onClose,
  onExplain,
}: {
  phones: Phone[];
  preferences: Preferences;
  onClose: () => void;
  onExplain: (phones: Phone[]) => void;
}) {
  const [phones, setPhones] = useState<Phone[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    setPhones([]);
    api<{ phones: Phone[] }>("/api/compare", {
      method: "POST",
      body: JSON.stringify({
        ids: selectedPhones.map((phone) => phone.id),
        preferences: requestPreferences(preferences),
      }),
      signal: controller.signal,
    })
      .then((result) => {
        if (!controller.signal.aborted) {
          setPhones(result.phones);
        }
      })
      .catch((e: Error) => {
        if (e.name !== "AbortError") setError(e.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [selectedPhones, preferences, reload]);
  return (
    <Dialog
      title="手机参数对比"
      eyebrow="当前条件与最新资料"
      onClose={onClose}
      wide
    >
      <p className="dialog-description">
        按当前需求、最新资料对比 {selectedPhones.length}{" "}
        部手机。待核实的参数不会被写成 0 或“不支持”。
      </p>
      {loading && (
        <div className="advice-loading" role="status">
          <span className="spinner" />
          <p>正在用相同需求重新比较每一部手机。</p>
        </div>
      )}
      {error && (
        <div className="error-panel" role="alert">
          <p>{error}</p>
          <button
            className="primary-button"
            onClick={() => setReload((value) => value + 1)}
          >
            重新读取对比资料
          </button>
        </div>
      )}
      {!loading && !error && (
        <div
          className="comparison-scroll"
          tabIndex={0}
          role="region"
          aria-label="手机参数对比表，可横向滚动查看全部机型"
        >
          <table
            className="comparison-table"
            style={{
              minWidth: 120 + phones.length * 230,
              width: 120 + phones.length * 230,
            }}
          >
            <colgroup>
              <col style={{ width: 120 }} />
              {phones.map((phone) => (
                <col key={phone.id} style={{ width: 230 }} />
              ))}
            </colgroup>
            <thead>
              <tr>
                <th scope="col">看看这些</th>
                {phones.map((phone) => (
                  <th scope="col" key={phone.id}>
                    <span className="phone-brand">{phone.brand}</span>
                    <strong>{phone.name}</strong>
                    {phone.score != null && (
                      <span className="match-badge">
                        {Math.round(phone.score)}% 需求匹配
                      </span>
                    )}
                    {phone.budget_warning && (
                      <p className="compare-budget-warning">
                        {phone.budget_warning}
                      </p>
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {COMPARE_FIELDS.map((field) => (
                <tr key={field.label}>
                  <th scope="row">{field.label}</th>
                  {phones.map((phone) => (
                    <td
                      className={
                        field.value(phone).includes("待核实")
                          ? "unknown-cell"
                          : ""
                      }
                      key={phone.id}
                    >
                      {field.value(phone)}
                    </td>
                  ))}
                </tr>
              ))}
              <tr>
                <th scope="row">适合你的地方</th>
                {phones.map((phone) => (
                  <td key={phone.id}>
                    {(phone.reasons || []).map((value, i) => (
                      <p className="compare-reason" key={i}>
                        ✓ {value}
                      </p>
                    ))}
                  </td>
                ))}
              </tr>
              <tr>
                <th scope="row">要接受的取舍</th>
                {phones.map((phone) => (
                  <td key={phone.id}>
                    {(phone.tradeoffs || []).map((value, i) => (
                      <p className="compare-tradeoff" key={i}>
                        {value}
                      </p>
                    ))}
                  </td>
                ))}
              </tr>
              <tr>
                <th scope="row">来源</th>
                {phones.map((phone) => (
                  <td key={phone.id}>
                    {safeSource(phone.source_url) ? (
                      <a
                        href={safeSource(phone.source_url)}
                        target="_blank"
                        rel="noreferrer"
                      >
                        核对原始资料 ↗
                      </a>
                    ) : (
                      "来源链接待核实"
                    )}
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      )}
      <div className="dialog-actions">
        <p className="dialog-description">
          参数只是起点，手感、实拍与购买渠道也值得确认。
        </p>
        <button
          className="primary-button"
          disabled={loading || phones.length === 0}
          onClick={() => onExplain(phones)}
        >
          比较这些手机 · 问顾问
        </button>
      </div>
    </Dialog>
  );
}

export function AdvicePanel({
  phones,
  preferences,
  meta,
  onClose,
}: {
  phones: Phone[];
  preferences: Preferences;
  meta: Meta | null;
  onClose: () => void;
}) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [sources, setSources] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  async function explain() {
    setLoading(true);
    setError("");
    controller.current = new AbortController();
    try {
      const result = await api<{ content: string; sources: string[] }>(
        "/api/explain",
        {
          method: "POST",
          body: JSON.stringify({
            ids: phones.map((phone) => phone.id),
            preferences: requestPreferences(preferences),
            question,
          }),
          signal: controller.current.signal,
        },
      );
      setAnswer(result.content);
      setSources(result.sources);
    } catch (e) {
      if (e instanceof Error && e.name !== "AbortError") setError(e.message);
    } finally {
      if (!controller.current?.signal.aborted) setLoading(false);
    }
  }
  return (
    <Dialog title="AI 选购顾问" eyebrow="AI 选购顾问" onClose={onClose} drawer>
      <p className="dialog-description">
        根据已加载的手机资料和你的需求，解释优势、代价和适合的人。
      </p>
      <div className="advice-phones">
        {phones.map((phone) => (
          <span key={phone.id}>{phone.name}</span>
        ))}
      </div>
      <label className="question-label" htmlFor="advice-question">
        还想让我们考虑什么？<small>可以留空，直接生成选购建议</small>
      </label>
      <textarea
        id="advice-question"
        className="question-input"
        maxLength={1000}
        rows={3}
        placeholder="例如：经常拍孩子，通勤会打游戏，想再用三年。哪一部更适合？"
        value={question}
        onChange={(event) => setQuestion(event.target.value)}
      />
      <div className="advice-action">
        <span>
          {meta?.model || "DeepSeek-V4.1-Flash"}
          <small>基于来源资料，不推测未知规格</small>
        </span>
        <button
          className="primary-button"
          onClick={explain}
          disabled={loading || !meta?.api_configured}
        >
          {loading
            ? "正在整理建议…"
            : answer
              ? "重新生成建议"
              : "生成选购建议 →"}
        </button>
      </div>
      {!meta?.api_configured && (
        <p className="inline-error">
          AI 接口尚未配置，仍然可以使用筛选与参数对比。
        </p>
      )}
      {loading && (
        <div className="advice-loading" role="status">
          <span className="spinner" />
          <p>
            正在比较你的需求和这些手机的真实资料。
            <small>通常需要几秒，请稍等。</small>
          </p>
        </div>
      )}
      {error && (
        <div className="inline-error" role="alert">
          {error}
        </div>
      )}
      {answer && (
        <section className="advice-answer" aria-label="AI 选购建议">
          <p className="eyebrow">给你的选购建议</p>
          {answer.split("\n").map((line, index) => {
            const text = line.replace(/^#{1,4}\s*/, "").replace(/\*\*/g, "");
            return text.trim() ? (
              <p
                className={/^#{1,4}\s/.test(line) ? "answer-heading" : ""}
                key={index}
              >
                {text}
              </p>
            ) : (
              <div className="answer-gap" key={index} />
            );
          })}
          {sources.length > 0 && (
            <div className="advice-sources">
              <strong>本次参考</strong>
              {sources.map((source, i) =>
                safeSource(source) ? (
                  <a
                    key={i}
                    href={safeSource(source)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    来源 {i + 1} ↗
                  </a>
                ) : (
                  <span key={i}>{source}</span>
                ),
              )}
            </div>
          )}
        </section>
      )}
    </Dialog>
  );
}

const QUALITY_LABELS: Record<string, string> = {
  release_source_conflict: "上市日期来源冲突",
  legacy_snapshot: "历史采集时间未知",
  missing_price: "价格待核实",
  out_of_range: "数值异常已隔离",
  legacy_boolean_unverified: "旧支持状态待核验",
  ambiguous_quantity: "多值参数待核验",
  ambiguous_camera: "镜头口径待核验",
  unparsed_quantity: "参数未能可靠解析",
  unknown_brand: "品牌待核验",
};

export function QualityPanel({
  onClose,
  onSync,
}: {
  onClose: () => void;
  onSync: () => void;
}) {
  const [report, setReport] = useState<QualityReport | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    api<QualityReport>("/api/quality", { signal: controller.signal })
      .then(setReport)
      .catch((e: Error) => {
        if (e.name !== "AbortError") setError(e.message);
      });
    return () => controller.abort();
  }, []);
  const summary = report?.summary;
  const sync = report?.report;
  const counts = summary?.issue_counts as Record<string, number> | undefined;
  const unresolved = Array.isArray(sync?.unresolved_errors)
    ? sync.unresolved_errors.length
    : 0;
  const seriesGaps = Array.isArray(sync?.series_count_discrepancies)
    ? sync.series_count_discrepancies.length
    : 0;
  return (
    <Dialog
      title="数据质量与覆盖"
      eyebrow="数据来源与质量"
      onClose={onClose}
      wide
    >
      <p className="dialog-description">
        新采集的来源资料与历史档案分开标记。无法核实的字段保持未知，异常数值不会进入选购比较。
      </p>
      {error && (
        <p className="inline-error" role="alert">
          {error}
        </p>
      )}
      {!report && !error && (
        <p className="dialog-description" role="status">
          正在读取质量报告…
        </p>
      )}
      {summary && (
        <>
          <div className="quality-stat-grid">
            {[
              ["资料记录", summary.records],
              ["近 30 天采集", summary.fresh_records],
              ["历史档案", summary.historical_records],
              ["价格待核实", summary.missing_price],
            ].map(([label, value]) => (
              <div key={String(label)}>
                <strong>{Number(value || 0).toLocaleString()}</strong>
                <span>{String(label)}</span>
              </div>
            ))}
          </div>
          <div className="quality-overview">
            <span>
              本地资料更新：{dateLabel(String(summary.updated_at || ""))}
            </span>
            <span>来源：品牌官网 + 中关村在线公开页面 + 历史导入档案</span>
            <span>
              官方资料：{Number(summary.official_records || 0).toLocaleString()}{" "}
              条
            </span>
          </div>
        </>
      )}
      {report?.official_coverage && (
        <section className="official-coverage">
          <h3>官网目录覆盖</h3>
          <p>以下是实际成功与待补采数量，当前目录成员不等于今天发布的新机。</p>
          <div>
            {Object.entries(report.official_coverage).map(
              ([brand, coverage]) => (
                <article key={brand}>
                  <strong>
                    {(
                      {
                        vivo: "vivo",
                        oppo: "OPPO",
                        apple: "苹果",
                        huawei: "华为",
                        honor: "荣耀",
                      } as Record<string, string>
                    )[brand] || brand}
                  </strong>
                  <span>
                    发现 {coverage.discovered ?? 0} 款 · 成功{" "}
                    {coverage.collected ?? 0} 款 · 待补 {coverage.pending ?? 0}{" "}
                    款
                  </span>
                  {((coverage.pending || 0) > 0 ||
                    (coverage.errors?.length || 0) > 0) && (
                    <small>覆盖尚未完整</small>
                  )}
                  {safeSource(coverage.catalog_url) && (
                    <a
                      href={safeSource(coverage.catalog_url)}
                      target="_blank"
                      rel="noreferrer"
                    >
                      核对官网目录 ↗
                    </a>
                  )}
                </article>
              ),
            )}
          </div>
        </section>
      )}
      {sync && (
        <section className="quality-run">
          <h3>最近一次采集</h3>
          <span
            className={
              sync.status === "complete" ? "run-badge" : "run-badge partial"
            }
          >
            {sync.status === "complete" ? "覆盖校验通过" : "仍有覆盖缺口"}
          </span>
          <p>
            发现 {Number(sync.discovered || 0).toLocaleString()} 条，成功{" "}
            {Number(sync.completed || 0).toLocaleString()}{" "}
            条，未解决页面/发布问题 {Number(sync.failed || 0).toLocaleString()}{" "}
            项。
          </p>
          <p>
            部分网页或配置暂不可访问时，已有有效数据会保留。成功记录不代表源站所有机型已经收齐。
          </p>
          {(unresolved > 0 ||
            seriesGaps > 0 ||
            sync.list_count_mismatch === true) && (
            <p>
              覆盖待核验：{unresolved} 个未解决的页面或详情问题，{seriesGaps}{" "}
              处系列配置差异
              {sync.list_count_mismatch === true
                ? "；发现数量与源站宣称数量不一致"
                : ""}
              。
            </p>
          )}
          {sync.scope != null && <p>采集范围：{String(sync.scope)}</p>}
        </section>
      )}
      {counts && (
        <section className="quality-categories">
          <h3>待核验资料的分类</h3>
          <div>
            {Object.entries(counts).map(([key, count]) => (
              <p key={key}>
                <span>{QUALITY_LABELS[key] || key}</span>
                <strong>{count.toLocaleString()}</strong>
              </p>
            ))}
          </div>
        </section>
      )}
      <details className="raw-details">
        <summary>
          查看待核验示例
          <span>{report?.issue_count?.toLocaleString() || 0} 项</span>
        </summary>
        <ul className="quality-issues">
          {report?.issues?.slice(0, 40).map((issue, i) => (
            <li key={`${issue.id}-${i}`}>
              <strong>{issue.name || "未知机型"}</strong>
              <span>{issue.message}</span>
            </li>
          ))}
        </ul>
      </details>
      <div className="dialog-actions">
        <p className="dialog-description">
          更新会自动采集、清洗与校验，通常需要几分钟。
        </p>
        <button className="primary-button" onClick={onSync}>
          更新手机资料
        </button>
      </div>
    </Dialog>
  );
}

export function SyncPanel({
  status,
  onClose,
}: {
  status: SyncStatus;
  onClose: () => void;
}) {
  const total = Number(status.discovered || 0);
  const completed = Number(status.completed || 0);
  const failed = Number(status.failed || 0);
  const progress = total
    ? Math.min(100, Math.round(((completed + failed) / total) * 100))
    : 0;
  return (
    <Dialog
      title={
        status.state === "running"
          ? "正在更新手机资料"
          : status.state === "failed"
            ? "资料更新未完成"
            : "手机资料已更新"
      }
      eyebrow="资料更新"
      onClose={onClose}
    >
      <p className="dialog-description">
        {status.state === "running"
          ? "可以关掉这个窗口继续挑选，更新会在后台进行。"
          : "通过验证的资料已经保存，旧数据保留。"}
      </p>
      <div className="sync-stage" role="status">
        {status.state === "running" && <span className="spinner" />}
        <strong>{status.stage || "正在连接数据源"}</strong>
      </div>
      <div
        className="sync-progress"
        role="progressbar"
        aria-label="采集进度"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={progress}
      >
        <span style={{ width: `${progress}%` }} />
      </div>
      <div className="sync-numbers">
        <span>
          <strong>{total.toLocaleString()}</strong>发现配置
        </span>
        <span>
          <strong>{completed.toLocaleString()}</strong>有效完成
        </span>
        <span>
          <strong>{failed.toLocaleString()}</strong>待重试
        </span>
      </div>
      {status.message && <p className="sync-message">{status.message}</p>}
      <button className="primary-button" onClick={onClose}>
        {status.state === "running" ? "继续挑手机" : "看看更新后的资料"}
      </button>
    </Dialog>
  );
}
