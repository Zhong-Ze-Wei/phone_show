const $ = (selector) => document.querySelector(selector);
const shots = {
  gallery: {
    src: "./assets/gallery-desktop.png",
    title: "手机图库",
    alt: "真实桌面工作台：左侧大图手机卡片，右侧预览与对比",
  },
  advisor: {
    src: "./assets/advisor-desktop.png",
    title: "顾问展开",
    alt: "真实顾问展开界面：左侧仍可浏览，右侧支持角色切换与连续追问",
  },
  mobile: {
    src: "./assets/gallery-mobile.png",
    title: "手机端",
    alt: "真实手机端选机界面：单列大图卡片与底部操作条",
  },
};
const purposeLabels = {
  daily: "日常",
  gaming: "游戏",
  camera: "拍照",
  battery: "续航",
};
let snapshot = null;
let budget = null;
let purpose = "daily";
let compared = [];
let draggedId = null;
const DRAG_TYPE = "application/x-pick-phone-demo";

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text != null) element.textContent = text;
  return element;
}
function sourceUrl(value) {
  if (!value) return null;
  const url = new URL(value, document.baseURI);
  return ["http:", "https:"].includes(url.protocol) ? url.href : null;
}
function number(value, unit) {
  return value == null
    ? "待核实"
    : `${Number(value).toLocaleString("zh-CN")}${unit}`;
}
function price(phone) {
  return phone.price == null
    ? "报价待核实"
    : `¥${Number(phone.price).toLocaleString("zh-CN")}`;
}
function announce(text) {
  $("#demo-status").textContent = text;
}
function candidates() {
  return !snapshot ? [] : snapshot.cases[`${budget ?? "all"}:${purpose}`] || [];
}
function photo(phone) {
  const src = sourceUrl(phone.image_url);
  if (!src) return node("span", "no-source-image", "暂无来源图片");
  const image = node("img");
  image.src = src;
  image.alt = phone.name;
  image.loading = "lazy";
  image.draggable = false;
  image.addEventListener(
    "error",
    () => image.replaceWith(node("span", "no-source-image", "暂无来源图片")),
    { once: true },
  );
  return image;
}
function sourceLink(phone) {
  const href = sourceUrl(phone.source_url);
  if (!href) return node("span", "", "来源待核实");
  const link = node("a", "", "来源 ↗");
  link.href = href;
  link.target = "_blank";
  link.rel = "noreferrer";
  link.setAttribute("aria-label", `查看 ${phone.name} 的真实来源`);
  return link;
}
function updateChoices() {
  document.querySelectorAll("[data-budget]").forEach((button) => {
    const active =
      button.dataset.budget === "all"
        ? budget === null
        : Number(button.dataset.budget) === budget;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  document.querySelectorAll("[data-purpose]").forEach((button) => {
    const active = button.dataset.purpose === purpose;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
}
function renderPhones() {
  const list = $("#demo-phones");
  list.replaceChildren();
  $("#demo-results-title").textContent =
    `${budget === null ? "预算不限" : `¥${budget.toLocaleString("zh-CN")}`} · ${purposeLabels[purpose]}候选`;
  const phones = candidates();
  if (!phones.length) {
    const empty = node("div", "demo-empty");
    empty.append(
      node("h4", "", snapshot ? "本组快照没有候选" : "正在读取真实快照"),
      node("p", "", "稍后重试或查看上方真实界面。"),
    );
    list.append(empty);
  }
  phones.forEach((phone) => {
    const included = compared.some((item) => item.id === phone.id);
    const card = node("article", `demo-phone${included ? " is-compared" : ""}`);
    card.draggable = true;
    card.dataset.phoneId = phone.id;
    const picture = node("div", "demo-phone-image");
    picture.append(photo(phone));
    const body = node("div", "demo-phone-body");
    const prices = node("div", "demo-phone-price-row");
    prices.append(
      node("span", "", `${phone.brand} · 参考价`),
      node("strong", "", price(phone)),
    );
    const specs = node("div", "demo-phone-specs");
    specs.append(
      node("span", "", number(phone.display_inches, "″")),
      node("span", "", number(phone.storage_gb, "GB")),
      node("span", "", number(phone.battery_mah, "mAh")),
    );
    const actions = node("div", "demo-phone-actions");
    const compare = node("button", "", included ? "移出对比" : "+ 加入对比");
    compare.type = "button";
    compare.setAttribute(
      "aria-label",
      `${included ? "移出" : "加入"}演示对比 ${phone.name}`,
    );
    compare.addEventListener("click", () =>
      included ? removeCompare(phone.id) : addCompare(phone),
    );
    actions.append(sourceLink(phone), compare);
    body.append(prices, node("h4", "", phone.name), specs, actions);
    card.append(picture, body);
    card.addEventListener("dragstart", (event) => {
      draggedId = phone.id;
      card.classList.add("dragging");
      event.dataTransfer.setData(DRAG_TYPE, phone.id);
      event.dataTransfer.effectAllowed = "copy";
      $("#demo-ai-ball").style.pointerEvents = "none";
      announce("拖到右侧任意位置即可加入演示对比。");
    });
    card.addEventListener("dragend", () => {
      draggedId = null;
      card.classList.remove("dragging");
      $("#demo-side").classList.remove("drop-active");
      $("#demo-ai-ball").style.pointerEvents = "";
    });
    list.append(card);
  });
}
function renderCompare() {
  const list = $("#demo-compare");
  list.replaceChildren();
  $("#compare-count").textContent = `${compared.length} 部`;
  $("#show-comparison").disabled = compared.length < 2;
  $("#clear-comparison").hidden = compared.length === 0;
  if (!compared.length)
    list.append(node("p", "compare-empty", "挑几部放到一起，再看差别。"));
  compared.forEach((phone) => {
    const item = node("div", "compare-item");
    const identity = node("div");
    identity.append(
      node("strong", "", phone.name),
      node("small", "", `${price(phone)} · 参考价`),
    );
    const remove = node("button", "", "×");
    remove.setAttribute("aria-label", `从演示对比移除 ${phone.name}`);
    remove.addEventListener("click", () => removeCompare(phone.id));
    item.append(photo(phone), identity, remove);
    list.append(item);
  });
}
function addCompare(phone) {
  if (compared.some((item) => item.id === phone.id)) {
    announce("这部手机已在演示对比中。");
    return;
  }
  compared.push(phone);
  renderPhones();
  renderCompare();
  announce(`已加入 ${phone.name}，当前 ${compared.length} 部。`);
}
function removeCompare(id) {
  compared = compared.filter((phone) => phone.id !== id);
  renderPhones();
  renderCompare();
  announce(`当前对比 ${compared.length} 部。`);
}
function changeCase() {
  updateChoices();
  renderPhones();
  renderCompare();
  announce(
    `已切换到 ${budget === null ? "预算不限" : `¥${budget.toLocaleString("zh-CN")}`} / ${purposeLabels[purpose]}的真实快照，保留已选对比机型。`,
  );
}
document.querySelectorAll("[data-budget]").forEach((button) =>
  button.addEventListener("click", () => {
    budget =
      button.dataset.budget === "all" ? null : Number(button.dataset.budget);
    changeCase();
  }),
);
document.querySelectorAll("[data-purpose]").forEach((button) =>
  button.addEventListener("click", () => {
    purpose = button.dataset.purpose;
    changeCase();
  }),
);
$("#reset-demo").addEventListener("click", () => {
  budget = null;
  purpose = "daily";
  changeCase();
});
$("#clear-comparison").addEventListener("click", () => {
  compared = [];
  renderPhones();
  renderCompare();
  announce("演示对比已清空。");
});

const side = $("#demo-side");
function internalDrag(event) {
  return draggedId && event.dataTransfer.types.includes(DRAG_TYPE);
}
side.addEventListener("dragover", (event) => {
  if (!internalDrag(event)) return;
  event.preventDefault();
  event.dataTransfer.dropEffect = "copy";
  side.classList.add("drop-active");
});
side.addEventListener("dragleave", (event) => {
  if (!side.contains(event.relatedTarget)) side.classList.remove("drop-active");
});
side.addEventListener("drop", (event) => {
  event.preventDefault();
  if (
    internalDrag(event) &&
    event.dataTransfer.getData(DRAG_TYPE) === draggedId
  ) {
    const phone = candidates().find((item) => item.id === draggedId);
    if (phone) addCompare(phone);
  }
  draggedId = null;
  side.classList.remove("drop-active");
  $("#demo-ai-ball").style.pointerEvents = "";
});

$("#show-comparison").addEventListener("click", () => {
  if (compared.length < 2) return;
  const table = node("table");
  table.style.minWidth = `${100 + compared.length * 230}px`;
  table.style.width = `${100 + compared.length * 230}px`;
  const columns = node("colgroup");
  const firstColumn = node("col");
  firstColumn.style.width = "100px";
  columns.append(firstColumn);
  compared.forEach(() => {
    const column = node("col");
    column.style.width = "230px";
    columns.append(column);
  });
  table.append(columns);
  const header = node("tr");
  const label = node("th", "", "机型");
  header.append(label);
  compared.forEach((phone) => {
    const cell = node("th");
    cell.scope = "col";
    cell.append(photo(phone), node("p", "", phone.name));
    header.append(cell);
  });
  const head = node("thead");
  head.append(header);
  table.append(head);
  const body = node("tbody");
  table.append(body);
  const fields = [
    ["参考报价", price],
    ["品牌", (phone) => phone.brand],
    ["屏幕", (phone) => number(phone.display_inches, "″")],
    [
      "内存 / 存储",
      (phone) =>
        `${number(phone.ram_gb, "GB")} / ${number(phone.storage_gb, "GB")}`,
    ],
    ["电池", (phone) => number(phone.battery_mah, "mAh")],
    ["芯片", (phone) => phone.chipset || "待核实"],
    ["系统", (phone) => phone.os || "待核实"],
    ["上市日期", (phone) => phone.release_date || "待核实"],
  ];
  fields.forEach(([label, getValue]) => {
    const row = node("tr");
    const title = node("th", "", label);
    title.scope = "row";
    row.append(title);
    compared.forEach((phone) => row.append(node("td", "", getValue(phone))));
    body.append(row);
  });
  const sourceRow = node("tr");
  sourceRow.append(node("th", "", "资料来源"));
  compared.forEach((phone) => {
    const cell = node("td");
    cell.append(sourceLink(phone));
    sourceRow.append(cell);
  });
  body.append(sourceRow);
  $("#comparison-table").replaceChildren(table);
  $("#comparison-dialog").showModal();
});

document.querySelectorAll("[data-preview]").forEach((button) =>
  button.addEventListener("click", () => {
    const key = button.dataset.preview;
    const shot = shots[key];
    $("#hero-image").src = shot.src;
    $("#hero-image").alt = shot.alt;
    $(".hero-screen").dataset.shot = key;
    $(".hero-screen").classList.toggle("mobile-shot", key === "mobile");
    $(".hero-screen").setAttribute("aria-label", `放大真实${shot.title}截图`);
    $("#hero-mode-label").textContent = `真实运行界面 / ${shot.title}`;
    document.querySelectorAll("[data-preview]").forEach((item) => {
      const selected = item === button;
      item.classList.toggle("active", selected);
      item.setAttribute("aria-pressed", String(selected));
    });
  }),
);
document.querySelectorAll(".shot-trigger").forEach((button) =>
  button.addEventListener("click", () => {
    const shot = shots[button.dataset.shot];
    $("#enlarged-shot").src = shot.src;
    $("#enlarged-shot").alt = shot.alt;
    $("#image-dialog-title").textContent = `真实产品截图 / ${shot.title}`;
    $("#image-dialog").classList.toggle(
      "mobile-image",
      button.dataset.shot === "mobile",
    );
    $("#image-dialog").showModal();
  }),
);
document
  .querySelectorAll("[data-close-dialog]")
  .forEach((button) =>
    button.addEventListener("click", () =>
      $(`#${button.dataset.closeDialog}`).close(),
    ),
  );
document.querySelectorAll("dialog").forEach((dialog) =>
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) {
      const rect = dialog.getBoundingClientRect();
      if (
        event.clientX < rect.left ||
        event.clientX > rect.right ||
        event.clientY < rect.top ||
        event.clientY > rect.bottom
      )
        dialog.close();
    }
  }),
);

function openAdvisor() {
  $("#advisor-dialog").showModal();
  $("#demo-ai-ball").setAttribute("aria-expanded", "true");
  $("#demo-advisor-open").setAttribute("aria-expanded", "true");
}
$("#demo-ai-ball").addEventListener("click", openAdvisor);
$("#demo-advisor-open").addEventListener("click", openAdvisor);
$("#advisor-dialog").addEventListener("close", () => {
  $("#demo-ai-ball").setAttribute("aria-expanded", "false");
  $("#demo-advisor-open").setAttribute("aria-expanded", "false");
});
$("#play-recording").addEventListener("click", () => {
  if (!snapshot) {
    announce("快照暂不可用，无法读取已录制对话。");
    return;
  }
  const transcript = $("#recorded-chat");
  transcript.replaceChildren();
  snapshot.recorded_chat.forEach((message) => {
    const entry = node(
      "article",
      `recorded-message ${message.role === "user" ? "user-message" : "assistant-message"}`,
    );
    entry.append(
      node(
        "span",
        "",
        message.role === "user" ? "录制问题" : "录制回答 · 固定文本",
      ),
      node("p", "", message.content),
    );
    transcript.append(entry);
  });
  transcript.hidden = false;
  $("#play-recording").hidden = true;
  $("#reset-recording").hidden = false;
});
$("#reset-recording").addEventListener("click", () => {
  $("#recorded-chat").hidden = true;
  $("#play-recording").hidden = false;
  $("#reset-recording").hidden = true;
});
$("#advisor-install-link").addEventListener("click", () =>
  $("#advisor-dialog").close(),
);

$("#copy-install").addEventListener("click", async () => {
  const text = $("#install-code").textContent;
  let copied = false;
  try {
    await navigator.clipboard.writeText(text);
    copied = true;
  } catch {
    const field = node("textarea");
    field.value = text;
    field.setAttribute("aria-hidden", "true");
    field.style.cssText =
      "position:fixed;top:0;left:0;opacity:0;pointer-events:none";
    document.body.append(field);
    field.select();
    copied = document.execCommand("copy");
    field.remove();
    $("#copy-install").focus({ preventScroll: true });
  }
  $("#copy-status").textContent = copied
    ? "命令已复制，按顺序执行即可启动本地工作台。"
    : "浏览器未允许复制，请选中上方命令手动复制。";
  if (copied) $("#copy-install").textContent = "已复制 ✓";
});

if (
  "IntersectionObserver" in window &&
  !window.matchMedia("(prefers-reduced-motion: reduce)").matches
) {
  document.body.classList.add("reveal-ready");
  const observer = new IntersectionObserver(
    (entries) =>
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-visible");
          observer.unobserve(entry.target);
        }
      }),
    { threshold: 0.06 },
  );
  document
    .querySelectorAll(".reveal")
    .forEach((section) => observer.observe(section));
}

fetch("./assets/demo-data.json")
  .then((response) => {
    if (!response.ok) throw new Error("快照无法读取");
    return response.json();
  })
  .then((data) => {
    snapshot = data;
    $("#snapshot-label").textContent =
      `快照 ${data.snapshot_date} · 按真实推荐顺序`;
    renderPhones();
  })
  .catch(() => {
    announce(
      "真实候选快照暂时无法读取；上方真实截图仍可查看。请刷新或使用本地 HTTP 服务打开本页。",
    );
  });
