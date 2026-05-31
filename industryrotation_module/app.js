// ---- 状态 ----
const state = {
  dates: [],
  currentDate: "",
  currentLevel: "sw3",
  rows: [],
  momentumWindow: 20,
  volWindow: 20,
  crowdingWindow: 20,
  industryTree: [],
  selectedNode: null,
  klineChart: null,
};

// ---- DOM 引用 ----
const els = {
  dateSelect: document.getElementById("dateSelect"),
  levelSelect: document.getElementById("levelSelect"),
  dataDate: document.getElementById("dataDate"),
  industryCount: document.getElementById("industryCount"),
  topMomentum: document.getElementById("topMomentum"),
  topCrowding: document.getElementById("topCrowding"),
  docButton: document.getElementById("docButton"),
  docModal: document.getElementById("docModal"),
  docContent: document.getElementById("docContent"),
  closeDocModal: document.getElementById("closeDocModal"),
  sidebarTree: document.getElementById("sidebarTree"),
  sidebarSearch: document.getElementById("sidebarSearch"),
  toggleSidebar: document.getElementById("toggleSidebar"),
  hierarchySidebar: document.getElementById("hierarchySidebar"),
  hierarchyPlaceholder: document.getElementById("hierarchyPlaceholder"),
  hierarchyContent: document.getElementById("hierarchyContent"),
  hierarchyBreadcrumb: document.getElementById("hierarchyBreadcrumb"),
  hierarchyFactorBody: document.getElementById("hierarchyFactorBody"),
  klineDays: document.getElementById("klineDays"),
};

// ---- 图表实例 ----
const charts = {};

function initChart(domId) {
  const dom = document.getElementById(domId);
  if (!dom) return null;
  if (charts[domId]) charts[domId].dispose();
  const instance = echarts.init(dom);
  charts[domId] = instance;
  return instance;
}

function resizeAllCharts() {
  Object.values(charts).forEach((c) => { try { c.resize(); } catch(e) {} });
}

window.addEventListener("resize", () => {
  clearTimeout(window._resizeTimer);
  window._resizeTimer = setTimeout(resizeAllCharts, 150);
});

// ---- API ----
async function fetchJSON(url) {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

async function fetchDates(level) { return fetchJSON(`/industryrotation/api/dates?level=${level}`); }
async function fetchData(date, level) { return fetchJSON(`/industryrotation/api/data?date=${date}&level=${level}`); }
async function fetchTree() { return fetchJSON("/industryrotation/api/tree"); }
async function fetchKline(level, name) { return fetchJSON(`/industryrotation/api/kline?level=${level}&name=${encodeURIComponent(name)}`); }

// ---- 初始化 ----
async function init() {
  // 阶段1: 先初始化首屏必需的图表实例（动量2个 + 拥挤度主图1个）
  initChart("rsMomentumChart");
  initChart("returnMomentumChart");
  initChart("equalCrowdingChart");

  state.dates = await fetchDates(state.currentLevel);
  renderDateOptions();

  // Load industry tree for sidebar
  try { state.industryTree = await fetchTree(); } catch(e) { state.industryTree = []; }
  renderSidebarTree();

  // 阶段2: 加载数据并渲染首屏图表
  await loadData();

  // 阶段3: 延迟初始化非首屏图表（波动率、拥挤度子图），用 requestIdleCallback 或 setTimeout
  scheduleDeferredCharts();

  els.dateSelect.addEventListener("change", loadData);
  els.levelSelect.addEventListener("change", async () => { state.currentLevel = els.levelSelect.value; state.dates = await fetchDates(state.currentLevel); renderDateOptions(); loadData(); });
  els.sidebarSearch.addEventListener("input", renderSidebarTree);
  els.toggleSidebar.addEventListener("click", () => { els.hierarchySidebar.classList.toggle("collapsed"); });
  els.klineDays.addEventListener("change", () => { if (state.selectedNode) loadKline(state.selectedNode); });

  // Doc modal
  els.docButton.addEventListener("click", openDocModal);
  els.closeDocModal.addEventListener("click", closeDocModal);
  els.docModal.addEventListener("click", (e) => { if (e.target === els.docModal) closeDocModal(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !els.docModal.hidden) closeDocModal(); });

  // Momentum tabs
  document.querySelectorAll(".momentum-tabs").forEach((group) => {
    group.addEventListener("click", (e) => {
      const btn = e.target.closest(".mom-tab");
      if (!btn) return;
      group.querySelectorAll(".mom-tab").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const w = parseInt(btn.dataset.window);
      if (group.id === "volTabs") { state.volWindow = w; renderVolatilityCharts(); }
      else if (group.id === "crowdingTabs") { state.crowdingWindow = w; renderCrowdingCharts(); }
      else { state.momentumWindow = w; renderMomentumCharts(); }
    });
  });
}

function scheduleDeferredCharts() {
  // 使用 requestIdleCallback 或 setTimeout 延迟初始化非首屏图表
  const deferredInit = () => {
    // 初始化波动率图表
    initChart("closeVolChart");
    initChart("intradayVolChart");
    // 初始化拥挤度子图表
    initChart("amountCrowdingChart");
    initChart("priceDevCrowdingChart");
    initChart("rsCrowdingChart");

    // 渲染延迟的图表
    renderVolatilityCharts();
    renderCrowdingCharts();
  };

  if (window.requestIdleCallback) {
    requestIdleCallback(deferredInit, { timeout: 300 });
  } else {
    setTimeout(deferredInit, 100);
  }
}

function renderDateOptions() {
  els.dateSelect.innerHTML = state.dates.map((d) => `<option value="${d}">${d}</option>`).join("");
  if (state.dates.length > 0) { state.currentDate = state.dates[0]; els.dateSelect.value = state.currentDate; }
}

async function loadData() {
  state.currentDate = els.dateSelect.value;
  state.currentLevel = els.levelSelect.value;
  const rows = await fetchData(state.currentDate, state.currentLevel);
  state.rows = rows.map((r) => {
    const out = {};
    for (const [k, v] of Object.entries(r)) {
      const num = parseFloat(v);
      out[k] = isNaN(num) ? v : num;
    }
    // Add short name (last segment after last "-")
    if (out.stock_name) {
      const parts = out.stock_name.split("-");
      out.short_name = parts[parts.length - 1];
    }
    return out;
  });

  // 确保首屏图表实例正确
  ["rsMomentumChart", "returnMomentumChart", "equalCrowdingChart"].forEach(id => {
    const dom = document.getElementById(id);
    if (dom && charts[id]) {
      charts[id].resize();
    } else if (dom) {
      if (charts[id]) charts[id].dispose();
      charts[id] = echarts.init(dom);
    }
  });

  // 首屏渲染：摘要 + 动量 + 等权拥挤度主图
  renderSummary();
  renderMomentumCharts();
  renderCrowdingMainChartOnly();

  // 延迟图表如果已经初始化则渲染
  if (charts["closeVolChart"]) {
    renderVolatilityCharts();
    renderCrowdingCharts();
  }
}

// 仅渲染等权复合拥挤度主图（首屏用）
function renderCrowdingMainChartOnly() {
  const w = state.crowdingWindow;
  const heatColor = (v) => { if (v > 0.85) return "#e03030"; if (v > 0.7) return "#e87040"; if (v > 0.55) return "#d4a020"; if (v > 0.4) return "#8ab830"; return "#3a9d6e"; };
  renderCrowdingMainChart("equalCrowdingChart", state.rows, `equal_weight_crowding_${w}`, heatColor);
}

// ---- 摘要 ----
function renderSummary() {
  const rows = state.rows.filter((r) => !isNaN(r.rs_momentum_20));
  els.dataDate.textContent = state.currentDate;
  els.industryCount.textContent = rows.length;
  if (rows.length === 0) { els.topMomentum.textContent = "-"; els.topCrowding.textContent = "-"; return; }
  const topRS = rows.reduce((a, b) => (a.rs_momentum_20 || -Infinity) > (b.rs_momentum_20 || -Infinity) ? a : b);
  els.topMomentum.textContent = topRS.stock_name || "-";
  const topCrowd = rows.reduce((a, b) => (a.equal_weight_crowding_20 || -Infinity) > (b.equal_weight_crowding_20 || -Infinity) ? a : b);
  els.topCrowding.textContent = `${topCrowd.stock_name || "-"} (${((topCrowd.equal_weight_crowding_20 || 0) * 100).toFixed(0)}%)`;
}

// ---- 水平条形图（动态高度 + 卡片滚动） ----
function renderScrollableBar(domId, rows, valueKey, title, unit, colorFunc, maxItems) {
  const chart = charts[domId];
  if (!chart) return;
  const valid = rows.filter((r) => !isNaN(r[valueKey]) && (r.short_name || r.stock_name)).sort((a, b) => (b[valueKey] || 0) - (a[valueKey] || 0));
  if (valid.length === 0) { chart.clear(); return; }
  const limit = maxItems || valid.length;
  const sliced = valid.slice(0, limit);
  const names = sliced.map((r) => r.short_name || r.stock_name).reverse();
  const values = sliced.map((r) => r[valueKey]).reverse();
  const barH = Math.max(16, Math.min(24, Math.floor(400 / names.length)));
  const h = Math.max(300, names.length * (barH + 4) + 40);
  const dom = document.getElementById(domId);
  if (dom) dom.style.height = h + "px";

  chart.setOption({
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, formatter: (p) => `${p[0].name}<br/>${valueKey}: ${p[0].value != null ? p[0].value.toFixed(4) : "-"}${unit}` },
    grid: { left: 100, right: 50, top: 8, bottom: 8 },
    xAxis: { type: "value", axisLabel: { fontSize: 10, color: "#aaa" }, splitLine: { lineStyle: { color: "#f0ede4" } } },
    yAxis: { type: "category", data: names, axisLabel: { fontSize: 11, color: "#444", width: 90, overflow: "truncate" }, axisTick: { show: false }, axisLine: { show: false } },
    series: [{
      type: "bar", data: values.map((v) => ({ value: v, itemStyle: { borderRadius: [0, 4, 4, 0], color: colorFunc ? colorFunc(v) : "#c4a24a" } })),
      label: { show: true, position: "right", fontSize: 10, color: "#999", formatter: (p) => (p.value != null && typeof p.value === 'number') ? p.value.toFixed(3) : "-" },
    }],
  }, true);
}

// ---- 动量图表 ----
function renderMomentumCharts() {
  const w = state.momentumWindow;
  const rows = state.rows;
  const heatColor = (v) => {
    if (v > 0.08) return "#d03030"; if (v > 0.04) return "#e86050"; if (v > 0.02) return "#f09080";
    if (v > 0) return "#f5c0b8"; if (v > -0.02) return "#c0e0c0"; if (v > -0.04) return "#80c880";
    if (v > -0.08) return "#40a850"; return "#208838";
  };
  renderMomentumMainChart("rsMomentumChart", rows, `rs_momentum_${w}`, "RS 动量", heatColor);
  renderMomentumMainChart("returnMomentumChart", rows, `return_momentum_${w}`, "收益动量", heatColor);
}

function renderMomentumMainChart(domId, rows, valueKey, title, colorFunc) {
  const chart = charts[domId];
  if (!chart) return;
  const valid = rows.filter((r) => !isNaN(r[valueKey]) && (r.short_name || r.stock_name)).sort((a, b) => (b[valueKey] || 0) - (a[valueKey] || 0));
  if (valid.length === 0) { chart.clear(); return; }
  const names = valid.map((r) => r.short_name || r.stock_name).reverse();
  const values = valid.map((r) => r[valueKey]).reverse();
  const barH = Math.max(16, Math.min(24, Math.floor(350 / names.length)));
  const h = Math.max(300, names.length * (barH + 4) + 40);
  const dom = document.getElementById(domId);
  if (dom) dom.style.height = h + "px";

  chart.setOption({
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, formatter: (p) => { const v = p[0].value; const pct = v != null ? (v * 100).toFixed(2) : "-"; return `<b>${p[0].name}</b><br/>${title}: <b>${v > 0 ? "📈" : v < 0 ? "📉" : "➖"} ${pct}%</b>`; } },
    grid: { left: 100, right: 50, top: 8, bottom: 8 },
    xAxis: { type: "value", axisLabel: { fontSize: 10, color: "#aaa", formatter: (v) => (v * 100).toFixed(0) + "%" }, splitLine: { lineStyle: { color: "#f0ede4" } } },
    yAxis: { type: "category", data: names, axisLabel: { fontSize: 11, color: "#444", width: 90, overflow: "truncate", fontWeight: "bold" }, axisTick: { show: false }, axisLine: { show: false } },
    series: [{ type: "bar", data: values.map((v) => ({ value: v, itemStyle: { borderRadius: [0, 6, 6, 0], color: colorFunc(v) } })),
      label: { show: true, position: "right", fontSize: 11, fontWeight: "bold", color: "#555", formatter: (p) => p.value != null ? (p.value * 100).toFixed(1) + "%" : "-" },
      markLine: { silent: true, symbol: "none", lineStyle: { type: "dashed", color: "#ccc", width: 1 }, data: [{ xAxis: 0, label: { formatter: "0%", fontSize: 10, color: "#999" } }] },
    }],
  }, true);
}

// ---- 波动率图表 ----
function renderVolatilityCharts() {
  const w = state.volWindow;
  const volColor = (v) => { if (v > 0.5) return "#c44a4a"; if (v > 0.3) return "#c4a24a"; return "#4a9d6e"; };
  renderScrollableBar("closeVolChart", state.rows, `close_vol_${w}`, "收盘波动率", "", volColor, 0);
  renderScrollableBar("intradayVolChart", state.rows, `intraday_vol_${w}`, "日内波动率", "", volColor, 0);
}

// ---- 拥挤度图表 ----
function renderCrowdingCharts() {
  const w = state.crowdingWindow;
  const heatColor = (v) => { if (v > 0.85) return "#e03030"; if (v > 0.7) return "#e87040"; if (v > 0.55) return "#d4a020"; if (v > 0.4) return "#8ab830"; return "#3a9d6e"; };
  renderCrowdingMainChart("equalCrowdingChart", state.rows, `equal_weight_crowding_${w}`, heatColor);
  renderScrollableBar("amountCrowdingChart", state.rows, `amount_share_crowding_${w}`, "成交额占比拥挤度", "", heatColor, 0);
  renderScrollableBar("priceDevCrowdingChart", state.rows, `price_deviation_crowding_${w}`, "乖离率拥挤度", "", heatColor, 0);
  renderScrollableBar("rsCrowdingChart", state.rows, `rs_crowding_${w}`, "RS拥挤度", "", heatColor, 0);
}

function renderCrowdingMainChart(domId, rows, valueKey, colorFunc) {
  const chart = charts[domId];
  if (!chart) return;
  const valid = rows.filter((r) => !isNaN(r[valueKey]) && (r.short_name || r.stock_name)).sort((a, b) => (b[valueKey] || 0) - (a[valueKey] || 0));
  if (valid.length === 0) { chart.clear(); return; }
  const names = valid.map((r) => r.short_name || r.stock_name).reverse();
  const values = valid.map((r) => r[valueKey]).reverse();
  const barH = Math.max(16, Math.min(24, Math.floor(350 / names.length)));
  const h = Math.max(300, names.length * (barH + 4) + 40);
  const dom = document.getElementById(domId);
  if (dom) dom.style.height = h + "px";

  chart.setOption({
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, formatter: (p) => { const v = p[0].value; const pct = v != null ? (v * 100).toFixed(0) : "-"; let level = "🟢 低"; if (v > 0.8) level = "🔴 过热"; else if (v > 0.6) level = "🟠 偏高"; else if (v > 0.4) level = "🟡 中等"; return `<b>${p[0].name}</b><br/>等权复合拥挤度: <b>${pct}%</b><br/>风险等级: ${level}`; } },
    grid: { left: 100, right: 50, top: 8, bottom: 8 },
    xAxis: { type: "value", min: 0, max: 1, axisLabel: { fontSize: 10, color: "#aaa", formatter: (v) => (v * 100).toFixed(0) + "%" }, splitLine: { lineStyle: { color: "#f0ede4" } } },
    yAxis: { type: "category", data: names, axisLabel: { fontSize: 11, color: "#444", width: 90, overflow: "truncate", fontWeight: "bold" }, axisTick: { show: false }, axisLine: { show: false } },
    series: [{ type: "bar", data: values.map((v) => ({ value: v, itemStyle: { borderRadius: [0, 6, 6, 0], color: colorFunc(v) } })),
      label: { show: true, position: "right", fontSize: 11, fontWeight: "bold", color: "#555", formatter: (p) => p.value != null ? (p.value * 100).toFixed(0) + "%" : "-" },
      markLine: { silent: true, symbol: "none", lineStyle: { type: "dashed", color: "#e03030", width: 1.5 }, data: [{ xAxis: 0.8, label: { formatter: "过热 80%", fontSize: 10, color: "#e03030" } }] },
    }],
  }, true);
}

// ---- 侧边栏行业树 ----
function renderSidebarTree() {
  const search = (els.sidebarSearch.value || "").toLowerCase();
  els.sidebarTree.innerHTML = "";

  function matchNode(node) {
    if (!search) return true;
    if (node.name.toLowerCase().includes(search)) return true;
    if (node.children) return node.children.some(matchNode);
    return false;
  }

  state.industryTree.filter(matchNode).forEach((l1) => {
    const l1Div = document.createElement("div");
    l1Div.className = "stree-node";
    const l1Head = document.createElement("div");
    l1Head.className = "stree-head stree-l1";
    l1Head.innerHTML = `<span class="stree-arrow">▶</span> ${l1.name}`;
    l1Head.addEventListener("click", () => {
      l1Div.classList.toggle("open");
      selectTreeNode({ level: "sw1", name: l1.name, children: l1.children });
    });
    l1Div.appendChild(l1Head);

    const l1Body = document.createElement("div");
    l1Body.className = "stree-body";
    (l1.children || []).forEach((l2) => {
      const l2Div = document.createElement("div");
      l2Div.className = "stree-node";
      const l2Head = document.createElement("div");
      l2Head.className = "stree-head stree-l2";
      l2Head.innerHTML = `<span class="stree-arrow">▶</span> ${l2.name}`;
      l2Head.addEventListener("click", (e) => {
        e.stopPropagation();
        l2Div.classList.toggle("open");
        selectTreeNode({ level: "sw2", name: l2.name, parent: l1.name, children: l2.children });
      });
      l2Div.appendChild(l2Head);

      const l2Body = document.createElement("div");
      l2Body.className = "stree-body";
      (l2.children || []).forEach((l3) => {
        const l3Item = document.createElement("div");
        l3Item.className = "stree-head stree-l3";
        l3Item.textContent = l3.name;
        l3Item.addEventListener("click", (e) => {
          e.stopPropagation();
          selectTreeNode({ level: "sw3", name: l3.name, parent: l2.name, grandparent: l1.name });
        });
        l2Body.appendChild(l3Item);
      });
      l2Div.appendChild(l2Body);
      l1Body.appendChild(l2Div);
    });
    l1Div.appendChild(l1Body);
    els.sidebarTree.appendChild(l1Div);
  });
}

// ---- 选中行业节点 ----
async function selectTreeNode(node) {
  state.selectedNode = node;

  // Keep current level - don't auto-switch
  // The matching logic below handles cross-level lookups

  els.hierarchyPlaceholder.style.display = "none";
  els.hierarchyContent.style.display = "block";

  // Breadcrumb
  let bc = "";
  const levelLabel = { sw1: "申万一级行业", sw2: "申万二级行业", sw3: "申万三级行业" };
  if (node.grandparent) bc = `${node.grandparent} / ${node.parent} / ${node.name}`;
  else if (node.parent) bc = `${node.parent} / ${node.name}`;
  else bc = node.name;
  els.hierarchyBreadcrumb.textContent = `📍 ${bc}（${levelLabel[node.level] || node.level}）`;

  // Collect rows: self + children
  const matchName = (row, name) => {
    if (!row || !row.stock_name) return false;
    const sn = row.stock_name;
    if (sn === name) return true;
    if (sn.endsWith("-" + name)) return true;
    if (sn.startsWith(name + "-")) return true;
    return false;
  };

  const selfRow = state.rows.find((r) => matchName(r, node.name));
  const allRows = [];
  if (selfRow) allRows.push(selfRow);

  const childRows = [];
  if (node.children && node.children.length > 0) {
    // Load child-level data for visualization
    const childLevel = node.level === "sw1" ? "sw2" : "sw3";
    try {
      // Get the latest available date for the child level
      const childDates = await fetchDates(childLevel);
      const childDate = childDates.length > 0 ? childDates[0] : state.currentDate;
      const childData = await fetchData(childDate, childLevel);
      node.children.forEach((child) => {
        const matchChild = (row, name) => {
          if (!row || !row.stock_name) return false;
          const sn = row.stock_name;
          if (sn === name) return true;
          if (sn.endsWith("-" + name)) return true;
          if (sn.startsWith(name + "-")) return true;
          return false;
        };
        const childRow = childData.find((r) => matchChild(r, child.name));
        if (childRow) childRows.push(childRow);
      });
    } catch (e) { /* ignore */ }
  }

  renderHierarchyTable(allRows);
  renderChildrenCharts(node, childRows);
  await loadKline(node);
}

// ---- 子行业指标可视化 ----
function renderChildrenCharts(node, childRows) {
  const section = document.getElementById("childrenChartsSection");
  const grid = document.getElementById("childrenChartsGrid");
  if (!childRows.length || !node.children) {
    section.style.display = "none";
    return;
  }
  section.style.display = "block";
  grid.innerHTML = "";

  // RS动量对比
  const rsBox = createChildChartBox("RS动量(20日) 对比", "children-rs-momentum");
  grid.appendChild(rsBox);
  renderChildBarChart("children-rs-momentum", childRows, "rs_momentum_20", "RS动量(20日)", (v) => v > 0 ? "#d44" : "#3a8");

  // 收益动量对比
  const retBox = createChildChartBox("收益动量(20日) 对比", "children-ret-momentum");
  grid.appendChild(retBox);
  renderChildBarChart("children-ret-momentum", childRows, "return_momentum_20", "收益动量(20日)", (v) => v > 0 ? "#d44" : "#3a8");

  // 收盘波动率对比
  const volBox = createChildChartBox("收盘波动率(20日) 对比", "children-close-vol");
  grid.appendChild(volBox);
  renderChildBarChart("children-close-vol", childRows, "close_vol_20", "收盘波动率(20日)", (v) => v > 0.4 ? "#c44" : "#4a9");

  // 等权复合拥挤度对比
  const crowdBox = createChildChartBox("等权复合拥挤度(20日) 对比", "children-crowding");
  grid.appendChild(crowdBox);
  renderChildBarChart("children-crowding", childRows, "equal_weight_crowding_20", "拥挤度(20日)", (v) => v > 0.8 ? "#e03030" : v > 0.6 ? "#e87040" : "#3a9d6e");
}

function createChildChartBox(title, domId) {
  const box = document.createElement("div");
  box.className = "child-chart-box";
  box.innerHTML = `<div class="child-chart-title">${title}</div><div id="${domId}" class="child-chart"></div>`;
  return box;
}

function renderChildBarChart(domId, rows, valueKey, title, colorFunc) {
  const dom = document.getElementById(domId);
  if (!dom) return;
  // Dispose old instance if exists
  const old = echarts.getInstanceByDom(dom);
  if (old) old.dispose();
  const chart = echarts.init(dom);

  const valid = rows.filter((r) => !isNaN(r[valueKey]) && (r.short_name || r.stock_name)).sort((a, b) => (b[valueKey] || 0) - (a[valueKey] || 0));
  if (!valid.length) { chart.clear(); return; }
  const shortName = (name) => { const parts = (name || "").split("-"); return parts[parts.length - 1] || name; };
  const names = valid.map((r) => shortName(r.stock_name)).reverse();
  const values = valid.map((r) => r[valueKey]).reverse();
  const barH = Math.max(18, Math.min(28, Math.floor(280 / names.length)));
  const h = Math.max(180, names.length * (barH + 6) + 40);
  dom.style.height = h + "px";

  chart.setOption({
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    grid: { left: 80, right: 50, top: 8, bottom: 8 },
    xAxis: { type: "value", axisLabel: { fontSize: 10, color: "#aaa" }, splitLine: { lineStyle: { color: "#f0ede4" } } },
    yAxis: { type: "category", data: names, axisLabel: { fontSize: 11, color: "#444", width: 70, overflow: "truncate" }, axisTick: { show: false }, axisLine: { show: false } },
    series: [{
      type: "bar", data: values.map((v) => ({ value: v, itemStyle: { borderRadius: [0, 4, 4, 0], color: colorFunc(v) } })),
      barMaxWidth: barH, label: { show: true, position: "right", fontSize: 10, color: "#999", formatter: (p) => (p.value != null && typeof p.value === 'number') ? p.value.toFixed(3) : "-" },
    }],
  });
}

function renderHierarchyTable(rows) {
  const fmt = (v, d = 4) => (v == null || isNaN(v)) ? "-" : v.toFixed(d);
  const momClass = (v) => v > 0 ? "cell-positive" : v < 0 ? "cell-negative" : "cell-neutral";
  const crowdClass = (v) => { if (v > 0.8) return "crowding-high"; if (v > 0.6) return "crowding-mid"; return "crowding-low"; };
  // Show only the last segment of stock_name for display
  const shortName = (name) => { const parts = (name || "").split("-"); return parts[parts.length - 1] || name; };

  els.hierarchyFactorBody.innerHTML = rows.map((r) => `
    <tr>
      <td style="font-weight:700;">${shortName(r.stock_name || "-")}</td>
      <td class="${momClass(r.rs_momentum_1)}">${fmt(r.rs_momentum_1)}</td>
      <td class="${momClass(r.rs_momentum_5)}">${fmt(r.rs_momentum_5)}</td>
      <td class="${momClass(r.rs_momentum_20)}">${fmt(r.rs_momentum_20)}</td>
      <td class="${momClass(r.rs_momentum_60)}">${fmt(r.rs_momentum_60)}</td>
      <td class="${momClass(r.return_momentum_1)}">${fmt(r.return_momentum_1)}</td>
      <td class="${momClass(r.return_momentum_5)}">${fmt(r.return_momentum_5)}</td>
      <td class="${momClass(r.return_momentum_20)}">${fmt(r.return_momentum_20)}</td>
      <td class="${momClass(r.return_momentum_60)}">${fmt(r.return_momentum_60)}</td>
      <td>${fmt(r.close_vol_20)}</td><td>${fmt(r.close_vol_60)}</td><td>${fmt(r.close_vol_120)}</td><td>${fmt(r.close_vol_250)}</td>
      <td>${fmt(r.intraday_vol_20)}</td><td>${fmt(r.intraday_vol_60)}</td><td>${fmt(r.intraday_vol_120)}</td><td>${fmt(r.intraday_vol_250)}</td>
      <td class="${crowdClass(r.amount_share_crowding_20)}">${fmt(r.amount_share_crowding_20)}</td>
      <td class="${crowdClass(r.amount_share_crowding_60)}">${fmt(r.amount_share_crowding_60)}</td>
      <td class="${crowdClass(r.amount_share_crowding_250)}">${fmt(r.amount_share_crowding_250)}</td>
      <td class="${crowdClass(r.price_deviation_crowding_20)}">${fmt(r.price_deviation_crowding_20)}</td>
      <td class="${crowdClass(r.price_deviation_crowding_60)}">${fmt(r.price_deviation_crowding_60)}</td>
      <td class="${crowdClass(r.price_deviation_crowding_250)}">${fmt(r.price_deviation_crowding_250)}</td>
      <td class="${crowdClass(r.rs_crowding_20)}">${fmt(r.rs_crowding_20)}</td>
      <td class="${crowdClass(r.rs_crowding_60)}">${fmt(r.rs_crowding_60)}</td>
      <td class="${crowdClass(r.rs_crowding_250)}">${fmt(r.rs_crowding_250)}</td>
      <td class="${crowdClass(r.equal_weight_crowding_20)}">${fmt(r.equal_weight_crowding_20)}</td>
      <td class="${crowdClass(r.equal_weight_crowding_60)}">${fmt(r.equal_weight_crowding_60)}</td>
      <td class="${crowdClass(r.equal_weight_crowding_250)}">${fmt(r.equal_weight_crowding_250)}</td>
    </tr>`).join("");
}

// ---- K线图 ----
async function loadKline(node) {
  const level = node.level;
  // Build full name for kline matching
  let name = node.name;
  if (node.grandparent) name = `${node.grandparent}-${node.parent}-${node.name}`;
  else if (node.parent) name = `${node.parent}-${node.name}`;
  const days = parseInt(els.klineDays.value) || 120;

  // Show loading state
  const dom = document.getElementById("klineChart");
  if (dom) dom.innerHTML = '<div style="padding:20px;text-align:center;color:#999;">加载K线数据...</div>';

  try {
    const data = await fetchKline(level, name);
    if (!data || data.length === 0) {
      renderEmptyKline();
      return;
    }
    const sliced = data.slice(-days);
    renderKlineChart(sliced, name);
  } catch (e) {
    renderEmptyKline();
  }
}

function renderEmptyKline() {
  const dom = document.getElementById("klineChart");
  if (state.klineChart) { state.klineChart.dispose(); state.klineChart = null; }
  if (dom) dom.innerHTML = '<div style="padding:40px;text-align:center;color:#999;">暂无K线数据</div>';
}

function renderKlineChart(rawData, name) {
  const dom = document.getElementById("klineChart");
  if (state.klineChart) { state.klineChart.dispose(); state.klineChart = null; }
  if (!dom) return;
  state.klineChart = echarts.init(dom);

  const dates = rawData.map((d) => d.date);
  const ohlc = rawData.map((d) => [d.open, d.close, d.low, d.high]);
  const volumes = rawData.map((d) => [d.volume || 0, d.open > d.close ? 1 : 0]);

  state.klineChart.setOption({
    tooltip: { trigger: "axis", axisPointer: { type: "cross" } },
    grid: [
      { left: "8%", right: "2%", top: "5%", height: "60%" },
      { left: "8%", right: "2%", top: "72%", height: "20%" },
    ],
    xAxis: [
      { type: "category", data: dates, gridIndex: 0, axisLabel: { fontSize: 10 }, axisLine: { onZero: false } },
      { type: "category", data: dates, gridIndex: 1, axisLabel: { show: false }, axisLine: { onZero: false } },
    ],
    yAxis: [
      { type: "value", gridIndex: 0, scale: true, splitLine: { lineStyle: { color: "#f0ede4" } } },
      { type: "value", gridIndex: 1, scale: true, axisLabel: { show: false }, splitLine: { show: false } },
    ],
    series: [
      {
        type: "candlestick", name: name, data: ohlc, xAxisIndex: 0, yAxisIndex: 0,
        itemStyle: { color: "#d44", color0: "#3a8", borderColor: "#d44", borderColor0: "#3a8" },
      },
      {
        type: "bar", name: "成交量", data: volumes.map((v) => v[0]), xAxisIndex: 1, yAxisIndex: 1,
        itemStyle: { color: (p) => volumes[p.dataIndex][1] ? "#d44" : "#3a8" },
      },
    ],
  });
}

// ---- 文档模态框 ----
const DOC_MARKDOWN = `# 行业轮动板块模型

行业分类标准：**申万行业分类（一级、二级、三级）**

---

## 技术面因子

### A. 动量

> 下述 i 值取 **1、5、20、60**

#### 1. RS 动量
使用 RS 在时间序列上的变化率衡量**剔除大盘影响后**的板块轮动强度。

$$RS\\text{变化率} = \\frac{P_t / M_t}{P_{t-i} / M_{t-i}} - 1$$

#### 2. 收益动量
板块自身价格的变化率。

$$收益动量 = \\frac{P_t}{P_{t-i}} - 1$$

### B. 波动率

> 下述 i 值取 **20、60、120、250**

#### 1. 收盘价波动率（年化）
$$\\sigma_{close} = \\text{std}(r_{close}) \\times \\sqrt{252}$$

#### 2. 日内波动率（年化）
$$\\sigma_{intraday} = \\text{std}(r_{intraday}) \\times \\sqrt{252}$$

### C. 拥挤度

> 下述 i 值取 **20、60、250**

#### 1. 成交额占比拥挤度
板块成交额占全市场成交额比例的历史分位数。

#### 2. 乖离率拥挤度
板块价格偏离均线程度的历史分位数。

#### 3. RS 拥挤度
板块 RS 值的历史分位数。

#### 4. 等权复合拥挤度
上述三个拥挤度的等权平均值。
`;

async function openDocModal() {
  els.docModal.hidden = false;
  els.docContent.innerHTML = marked.parse(DOC_MARKDOWN);
  setTimeout(() => { if (window.renderMathInElement) renderMathInElement(els.docContent); }, 100);
}

function closeDocModal() { els.docModal.hidden = true; }

// ---- 启动 ----
init();
