// ---- 状态 ----
const state = {
  dates: [],
  currentDate: "",
  currentLevel: "sw1",
  rows: [],
  momentumWindow: 20,
  volWindow: 20,
  crowdingWindow: 20,
  tableFilterGroup: "all",
  expandedIdx: null,
};

// ---- DOM 引用 ----
const els = {
  dateSelect: document.getElementById("dateSelect"),
  levelSelect: document.getElementById("levelSelect"),
  dataDate: document.getElementById("dataDate"),
  industryCount: document.getElementById("industryCount"),
  topMomentum: document.getElementById("topMomentum"),
  topCrowding: document.getElementById("topCrowding"),
  tableSearch: document.getElementById("tableSearch"),
  factorTableBody: document.querySelector("#factorTable tbody"),
  docButton: document.getElementById("docButton"),
  docModal: document.getElementById("docModal"),
  docContent: document.getElementById("docContent"),
  closeDocModal: document.getElementById("closeDocModal"),
};

// ---- 图表实例 ----
const charts = {};

function initChart(domId) {
  const dom = document.getElementById(domId);
  if (!dom) return null;
  const instance = echarts.init(dom);
  charts[domId] = instance;
  return instance;
}

function resizeAllCharts() {
  Object.values(charts).forEach((c) => c.resize());
}

window.addEventListener("resize", () => {
  clearTimeout(window._resizeTimer);
  window._resizeTimer = setTimeout(resizeAllCharts, 150);
});

// ---- API ----
async function fetchDates() {
  const resp = await fetch("/industryrotation/api/dates");
  return resp.json();
}

async function fetchData(date, level) {
  const resp = await fetch(`/industryrotation/api/data?date=${date}&level=${level}`);
  return resp.json();
}

// ---- 初始化 ----
async function init() {
  // 初始化所有图表
  initChart("rsMomentumChart");
  initChart("returnMomentumChart");
  initChart("closeVolChart");
  initChart("intradayVolChart");
  initChart("amountCrowdingChart");
  initChart("priceDevCrowdingChart");
  initChart("rsCrowdingChart");
  initChart("equalCrowdingChart");

  // 加载日期
  state.dates = await fetchDates();
  renderDateOptions();

  // 加载默认数据
  await loadData();

  // 事件绑定
  els.dateSelect.addEventListener("change", loadData);
  els.levelSelect.addEventListener("change", () => {
    state.currentLevel = els.levelSelect.value;
    loadData();
  });
  els.tableSearch.addEventListener("input", renderTable);

  // 表格分类筛选
  document.querySelectorAll(".filter-tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".filter-tab").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.tableFilterGroup = btn.dataset.group;
      // 折叠所有展开行并重置箭头
      document.querySelectorAll(".expand-row").forEach((r) => (r.hidden = true));
      document.querySelectorAll(".expand-arrow").forEach((a) => (a.textContent = "▶"));
      state.expandedIdx = null;
      applyTableColumnFilter();
    });
  });

  // 文档模态框
  els.docButton.addEventListener("click", openDocModal);
  els.closeDocModal.addEventListener("click", closeDocModal);
  els.docModal.addEventListener("click", (e) => {
    if (e.target === els.docModal) closeDocModal();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !els.docModal.hidden) closeDocModal();
  });

  // 动量窗口切换
  document.querySelectorAll(".momentum-tabs").forEach((group) => {
    group.addEventListener("click", (e) => {
      const btn = e.target.closest(".mom-tab");
      if (!btn) return;
      group.querySelectorAll(".mom-tab").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const window = parseInt(btn.dataset.window);

      if (group.id === "volTabs") {
        state.volWindow = window;
        renderVolatilityCharts();
      } else if (group.id === "crowdingTabs") {
        state.crowdingWindow = window;
        renderCrowdingCharts();
      } else {
        state.momentumWindow = window;
        renderMomentumCharts();
      }
    });
  });
}

function renderDateOptions() {
  els.dateSelect.innerHTML = state.dates
    .map((d) => `<option value="${d}">${d}</option>`)
    .join("");
  if (state.dates.length > 0) {
    state.currentDate = state.dates[0];
    els.dateSelect.value = state.currentDate;
  }
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
    return out;
  });

  renderSummary();
  renderMomentumCharts();
  renderVolatilityCharts();
  renderCrowdingCharts();
  renderTable();
}

// ---- 摘要 ----
function renderSummary() {
  const rows = state.rows.filter((r) => !isNaN(r.rs_momentum_20));
  els.dataDate.textContent = state.currentDate;
  els.industryCount.textContent = rows.length;

  if (rows.length === 0) {
    els.topMomentum.textContent = "-";
    els.topCrowding.textContent = "-";
    return;
  }

  const topRS = rows.reduce((a, b) =>
    (a.rs_momentum_20 || -Infinity) > (b.rs_momentum_20 || -Infinity) ? a : b
  );
  els.topMomentum.textContent = topRS.stock_name || "-";

  const topCrowd = rows.reduce((a, b) =>
    (a.equal_weight_crowding_20 || -Infinity) > (b.equal_weight_crowding_20 || -Infinity) ? a : b
  );
  els.topCrowding.textContent = `${topCrowd.stock_name || "-"} (${((topCrowd.equal_weight_crowding_20 || 0) * 100).toFixed(0)}%)`;
}

// ---- 水平条形图通用渲染 ----
function renderHorizontalBar(domId, rows, valueKey, title, unit, colorFunc) {
  const chart = charts[domId];
  if (!chart) return;

  const valid = rows
    .filter((r) => !isNaN(r[valueKey]) && r.stock_name)
    .sort((a, b) => (b[valueKey] || 0) - (a[valueKey] || 0))
    .slice(0, 20);

  if (valid.length === 0) {
    chart.clear();
    return;
  }

  const names = valid.map((r) => r.stock_name).reverse();
  const values = valid.map((r) => r[valueKey]).reverse();

  const option = {
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" },
      formatter: (params) => {
        const p = params[0];
        const v = p.value;
        return `${p.name}<br/>${valueKey}: ${v != null ? v.toFixed(4) : "-"}${unit}`;
      },
    },
    grid: { left: 100, right: 40, top: 8, bottom: 8 },
    xAxis: {
      type: "value",
      axisLabel: { fontSize: 10, color: "#aaa" },
      splitLine: { lineStyle: { color: "#f0ede4" } },
    },
    yAxis: {
      type: "category",
      data: names,
      axisLabel: { fontSize: 11, color: "#444", width: 90, overflow: "truncate" },
      axisTick: { show: false },
      axisLine: { show: false },
    },
    series: [
      {
        type: "bar",
        data: values.map((v, i) => {
          const baseColor = colorFunc ? colorFunc(v, i) : "#c4a24a";
          return {
            value: v,
            itemStyle: {
              borderRadius: [0, 4, 4, 0],
              color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
                { offset: 0, color: baseColor },
                { offset: 1, color: baseColor + "cc" },
              ]),
            },
          };
        }),
        barMaxWidth: 18,
        emphasis: {
          itemStyle: {
            shadowBlur: 10,
            shadowColor: "rgba(0,0,0,0.15)",
          },
        },
        label: {
          show: true,
          position: "right",
          fontSize: 10,
          color: "#999",
          formatter: (p) => (p.value != null ? p.value.toFixed(3) : "-"),
        },
      },
    ],
  };

  chart.setOption(option, true);
}

// ---- 动量图表 ----
function renderMomentumCharts() {
  const w = state.momentumWindow;
  const rows = state.rows;

  // 热力色阶：深红(强正) → 浅红 → 白(零) → 浅绿 → 深绿(强负)
  const heatColor = (v) => {
    if (v > 0.08) return "#d03030";
    if (v > 0.04) return "#e86050";
    if (v > 0.02) return "#f09080";
    if (v > 0) return "#f5c0b8";
    if (v > -0.02) return "#c0e0c0";
    if (v > -0.04) return "#80c880";
    if (v > -0.08) return "#40a850";
    return "#208838";
  };

  renderMomentumMainChart("rsMomentumChart", rows, `rs_momentum_${w}`, "RS 动量（相对大盘）", heatColor);
  renderMomentumMainChart("returnMomentumChart", rows, `return_momentum_${w}`, "收益动量（绝对收益）", heatColor);
}

function renderMomentumMainChart(domId, rows, valueKey, title, colorFunc) {
  const chart = charts[domId];
  if (!chart) return;

  const valid = rows
    .filter((r) => !isNaN(r[valueKey]) && r.stock_name)
    .sort((a, b) => (b[valueKey] || 0) - (a[valueKey] || 0))
    .slice(0, 20);

  if (valid.length === 0) { chart.clear(); return; }

  const names = valid.map((r) => r.stock_name).reverse();
  const values = valid.map((r) => r[valueKey]).reverse();

  const option = {
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" },
      formatter: (params) => {
        const p = params[0];
        const v = p.value;
        const pct = v != null ? (v * 100).toFixed(2) : "-";
        const arrow = v > 0 ? "📈" : v < 0 ? "📉" : "➖";
        return `<b>${p.name}</b><br/>${title}: <b>${arrow} ${pct}%</b>`;
      },
    },
    grid: { left: 100, right: 50, top: 8, bottom: 8 },
    xAxis: {
      type: "value",
      axisLabel: { fontSize: 10, color: "#aaa", formatter: (v) => (v * 100).toFixed(0) + "%" },
      splitLine: { lineStyle: { color: "#f0ede4" } },
    },
    yAxis: {
      type: "category",
      data: names,
      axisLabel: { fontSize: 11, color: "#444", width: 90, overflow: "truncate", fontWeight: "bold" },
      axisTick: { show: false },
      axisLine: { show: false },
    },
    series: [
      {
        type: "bar",
        data: values.map((v) => ({
          value: v,
          itemStyle: {
            borderRadius: [0, 6, 6, 0],
            color: colorFunc(v),
          },
        })),
        barMaxWidth: 22,
        emphasis: {
          itemStyle: { shadowBlur: 10, shadowColor: "rgba(0,0,0,0.15)" },
        },
        label: {
          show: true,
          position: "right",
          fontSize: 11,
          fontWeight: "bold",
          color: "#555",
          formatter: (p) => (p.value != null ? (p.value * 100).toFixed(1) + "%" : "-"),
        },
        markLine: {
          silent: true,
          symbol: "none",
          lineStyle: { type: "dashed", color: "#ccc", width: 1 },
          data: [{ xAxis: 0, label: { formatter: "0%", fontSize: 10, color: "#999" } }],
        },
      },
    ],
  };

  chart.setOption(option, true);
}

// ---- 波动率图表 ----
function renderVolatilityCharts() {
  const w = state.volWindow;
  const rows = state.rows;

  const volColor = (v) => {
    if (v > 0.5) return "#c44a4a";
    if (v > 0.3) return "#c4a24a";
    return "#4a9d6e";
  };

  renderHorizontalBar("closeVolChart", rows, `close_vol_${w}`, "收盘波动率", "", volColor);
  renderHorizontalBar("intradayVolChart", rows, `intraday_vol_${w}`, "日内波动率", "", volColor);
}

// ---- 拥挤度图表 ----
function renderCrowdingCharts() {
  const w = state.crowdingWindow;
  const rows = state.rows;

  // 热力色阶：红(>0.8) → 橙(>0.6) → 金(>0.4) → 绿(<0.4)
  const heatColor = (v) => {
    if (v > 0.85) return "#e03030";
    if (v > 0.7) return "#e87040";
    if (v > 0.55) return "#d4a020";
    if (v > 0.4) return "#8ab830";
    return "#3a9d6e";
  };

  renderCrowdingMainChart("equalCrowdingChart", rows, `equal_weight_crowding_${w}`, heatColor);
  renderHorizontalBar("amountCrowdingChart", rows, `amount_share_crowding_${w}`, "成交额占比拥挤度", "", heatColor);
  renderHorizontalBar("priceDevCrowdingChart", rows, `price_deviation_crowding_${w}`, "乖离率拥挤度", "", heatColor);
  renderHorizontalBar("rsCrowdingChart", rows, `rs_crowding_${w}`, "RS拥挤度", "", heatColor);
}

function renderCrowdingMainChart(domId, rows, valueKey, colorFunc) {
  const chart = charts[domId];
  if (!chart) return;

  const valid = rows
    .filter((r) => !isNaN(r[valueKey]) && r.stock_name)
    .sort((a, b) => (b[valueKey] || 0) - (a[valueKey] || 0))
    .slice(0, 20);

  if (valid.length === 0) { chart.clear(); return; }

  const names = valid.map((r) => r.stock_name).reverse();
  const values = valid.map((r) => r[valueKey]).reverse();

  const option = {
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" },
      formatter: (params) => {
        const p = params[0];
        const v = p.value;
        const pct = v != null ? (v * 100).toFixed(0) : "-";
        let level = "🟢 低";
        if (v > 0.8) level = "🔴 过热";
        else if (v > 0.6) level = "🟠 偏高";
        else if (v > 0.4) level = "🟡 中等";
        return `<b>${p.name}</b><br/>等权复合拥挤度: <b>${pct}%</b><br/>风险等级: ${level}`;
      },
    },
    grid: { left: 100, right: 50, top: 8, bottom: 8 },
    xAxis: {
      type: "value",
      min: 0,
      max: 1,
      axisLabel: { fontSize: 10, color: "#aaa", formatter: (v) => (v * 100).toFixed(0) + "%" },
      splitLine: { lineStyle: { color: "#f0ede4" } },
    },
    yAxis: {
      type: "category",
      data: names,
      axisLabel: { fontSize: 11, color: "#444", width: 90, overflow: "truncate", fontWeight: "bold" },
      axisTick: { show: false },
      axisLine: { show: false },
    },
    visualMap: {
      show: false,
      min: 0,
      max: 1,
      inRange: { color: ["#3a9d6e", "#8ab830", "#d4a020", "#e87040", "#e03030"] },
    },
    series: [
      {
        type: "bar",
        data: values.map((v) => ({
          value: v,
          itemStyle: {
            borderRadius: [0, 6, 6, 0],
            color: colorFunc(v),
          },
        })),
        barMaxWidth: 22,
        emphasis: {
          itemStyle: { shadowBlur: 12, shadowColor: "rgba(224,48,48,0.3)" },
        },
        label: {
          show: true,
          position: "right",
          fontSize: 11,
          fontWeight: "bold",
          color: "#555",
          formatter: (p) => (p.value != null ? (p.value * 100).toFixed(0) + "%" : "-"),
        },
        markLine: {
          silent: true,
          symbol: "none",
          lineStyle: { type: "dashed", color: "#e03030", width: 1.5 },
          data: [{ xAxis: 0.8, label: { formatter: "过热 80%", fontSize: 10, color: "#e03030" } }],
        },
      },
    ],
  };

  chart.setOption(option, true);
}

// ---- 表格 ----
function applyTableColumnFilter() {
  const group = state.tableFilterGroup;
  const table = document.getElementById("factorTable");
  // 先全部显示
  table.querySelectorAll(".col-momentum, .col-volatility, .col-crowding").forEach((el) => {
    el.classList.remove("hidden");
  });
  if (group === "all") return;
  const hideMap = {
    momentum: ".col-volatility, .col-crowding",
    volatility: ".col-momentum, .col-crowding",
    crowding: ".col-momentum, .col-volatility",
  };
  table.querySelectorAll(hideMap[group] || "").forEach((el) => el.classList.add("hidden"));
}

function renderTable() {
  const search = els.tableSearch.value.toLowerCase();
  const rows = state.rows.filter((r) => {
    if (!search) return true;
    return (r.stock_name || "").toLowerCase().includes(search);
  });

  const fmtNum = (v, decimals = 4) => {
    if (v == null || isNaN(v)) return "-";
    return v.toFixed(decimals);
  };

  const momClass = (v) => (v > 0 ? "cell-positive" : v < 0 ? "cell-negative" : "cell-neutral");
  const crowdClass = (v) => {
    if (v > 0.8) return "crowding-high";
    if (v > 0.6) return "crowding-mid";
    return "crowding-low";
  };

  state.expandedIdx = null;

  els.factorTableBody.innerHTML = rows
    .map(
      (r, idx) => `
    <tr class="stock-row" data-idx="${idx}">
      <td class="col-name" style="font-weight:700;cursor:pointer"><span class="expand-arrow">▶</span> ${r.stock_name || "-"}</td>
      <td class="col-momentum ${momClass(r.rs_momentum_1)}">${fmtNum(r.rs_momentum_1)}</td>
      <td class="col-momentum ${momClass(r.rs_momentum_5)}">${fmtNum(r.rs_momentum_5)}</td>
      <td class="col-momentum ${momClass(r.rs_momentum_20)}">${fmtNum(r.rs_momentum_20)}</td>
      <td class="col-momentum ${momClass(r.rs_momentum_60)}">${fmtNum(r.rs_momentum_60)}</td>
      <td class="col-momentum ${momClass(r.return_momentum_1)}">${fmtNum(r.return_momentum_1)}</td>
      <td class="col-momentum ${momClass(r.return_momentum_5)}">${fmtNum(r.return_momentum_5)}</td>
      <td class="col-momentum ${momClass(r.return_momentum_20)}">${fmtNum(r.return_momentum_20)}</td>
      <td class="col-momentum ${momClass(r.return_momentum_60)}">${fmtNum(r.return_momentum_60)}</td>
      <td class="col-volatility">${fmtNum(r.close_vol_20)}</td>
      <td class="col-volatility">${fmtNum(r.close_vol_60)}</td>
      <td class="col-volatility">${fmtNum(r.close_vol_120)}</td>
      <td class="col-volatility">${fmtNum(r.close_vol_250)}</td>
      <td class="col-volatility">${fmtNum(r.intraday_vol_20)}</td>
      <td class="col-volatility">${fmtNum(r.intraday_vol_60)}</td>
      <td class="col-volatility">${fmtNum(r.intraday_vol_120)}</td>
      <td class="col-volatility">${fmtNum(r.intraday_vol_250)}</td>
      <td class="col-crowding ${crowdClass(r.amount_share_crowding_20)}">${fmtNum(r.amount_share_crowding_20)}</td>
      <td class="col-crowding ${crowdClass(r.amount_share_crowding_60)}">${fmtNum(r.amount_share_crowding_60)}</td>
      <td class="col-crowding ${crowdClass(r.amount_share_crowding_250)}">${fmtNum(r.amount_share_crowding_250)}</td>
      <td class="col-crowding ${crowdClass(r.price_deviation_crowding_20)}">${fmtNum(r.price_deviation_crowding_20)}</td>
      <td class="col-crowding ${crowdClass(r.price_deviation_crowding_60)}">${fmtNum(r.price_deviation_crowding_60)}</td>
      <td class="col-crowding ${crowdClass(r.price_deviation_crowding_250)}">${fmtNum(r.price_deviation_crowding_250)}</td>
      <td class="col-crowding ${crowdClass(r.rs_crowding_20)}">${fmtNum(r.rs_crowding_20)}</td>
      <td class="col-crowding ${crowdClass(r.rs_crowding_60)}">${fmtNum(r.rs_crowding_60)}</td>
      <td class="col-crowding ${crowdClass(r.rs_crowding_250)}">${fmtNum(r.rs_crowding_250)}</td>
      <td class="col-crowding ${crowdClass(r.equal_weight_crowding_20)}">${fmtNum(r.equal_weight_crowding_20)}</td>
      <td class="col-crowding ${crowdClass(r.equal_weight_crowding_60)}">${fmtNum(r.equal_weight_crowding_60)}</td>
      <td class="col-crowding ${crowdClass(r.equal_weight_crowding_250)}">${fmtNum(r.equal_weight_crowding_250)}</td>
    </tr>
    <tr class="expand-row" data-idx="${idx}" hidden>
      <td colspan="29">
        <div class="expand-panel" id="expandPanel${idx}"></div>
      </td>
    </tr>`
    )
    .join("");

  applyTableColumnFilter();

  // 绑定点击
  els.factorTableBody.querySelectorAll(".stock-row").forEach((row) => {
    row.addEventListener("click", () => {
      const idx = parseInt(row.dataset.idx);
      toggleExpand(idx);
    });
  });
}

function toggleExpand(idx) {
  // "全部"模式下不展开
  if (state.tableFilterGroup === "all") return;

  const expandRow = els.factorTableBody.querySelector(`.expand-row[data-idx="${idx}"]`);
  const stockRow = els.factorTableBody.querySelector(`.stock-row[data-idx="${idx}"]`);
  if (!expandRow || !stockRow) return;

  const arrow = stockRow.querySelector(".expand-arrow");

  // 折叠之前展开的行（包括箭头）
  if (state.expandedIdx !== null) {
    const prevExpand = els.factorTableBody.querySelector(`.expand-row[data-idx="${state.expandedIdx}"]`);
    const prevStock = els.factorTableBody.querySelector(`.stock-row[data-idx="${state.expandedIdx}"]`);
    const prevArrow = prevStock?.querySelector(".expand-arrow");
    if (prevExpand) prevExpand.hidden = true;
    if (prevArrow) prevArrow.textContent = "▶";
  }

  // 如果点击的是已展开的行 → 折叠
  if (state.expandedIdx === idx) {
    expandRow.hidden = true;
    if (arrow) arrow.textContent = "▶";
    state.expandedIdx = null;
    return;
  }

  // 展开当前
  expandRow.hidden = false;
  if (arrow) arrow.textContent = "▼";
  state.expandedIdx = idx;

  // 获取该行数据
  const search = els.tableSearch.value.toLowerCase();
  const rows = state.rows.filter((r) => {
    if (!search) return true;
    return (r.stock_name || "").toLowerCase().includes(search);
  });
  const row = rows[idx];
  if (!row) return;

  // 根据筛选类型渲染对应图表
  const panel = document.getElementById(`expandPanel${idx}`);
  if (!panel || panel.dataset.rendered === state.tableFilterGroup) return;
  panel.dataset.rendered = state.tableFilterGroup;

  const group = state.tableFilterGroup;
  if (group === "momentum") {
    panel.innerHTML = `
      <div class="expand-panel-head">🔍 <strong>${row.stock_name}</strong> — 动量详情</div>
      <div class="expand-charts">
        <div class="expand-chart-box"><div class="expand-chart-title">RS 动量多窗口</div><div id="expRSMom${idx}" class="expand-chart"></div></div>
        <div class="expand-chart-box"><div class="expand-chart-title">收益动量多窗口</div><div id="expRetMom${idx}" class="expand-chart"></div></div>
      </div>`;
    setTimeout(() => {
      renderBarChart(`expRSMom${idx}`, row, "rs_momentum", "RS 动量", ["1", "5", "20", "60"]);
      renderBarChart(`expRetMom${idx}`, row, "return_momentum", "收益动量", ["1", "5", "20", "60"]);
    }, 50);
  } else if (group === "volatility") {
    panel.innerHTML = `
      <div class="expand-panel-head">🔍 <strong>${row.stock_name}</strong> — 波动率详情</div>
      <div class="expand-charts">
        <div class="expand-chart-box"><div class="expand-chart-title">收盘波动率多窗口</div><div id="expCloseVol${idx}" class="expand-chart"></div></div>
        <div class="expand-chart-box"><div class="expand-chart-title">日内波动率多窗口</div><div id="expIntraVol${idx}" class="expand-chart"></div></div>
      </div>`;
    setTimeout(() => {
      renderLineChart(`expCloseVol${idx}`, row, "close_vol", "收盘波动率", ["20", "60", "120", "250"]);
      renderLineChart(`expIntraVol${idx}`, row, "intraday_vol", "日内波动率", ["20", "60", "120", "250"]);
    }, 50);
  } else if (group === "crowding") {
    panel.innerHTML = `
      <div class="expand-panel-head">🔍 <strong>${row.stock_name}</strong> — 拥挤度详情</div>
      <div class="expand-charts">
        <div class="expand-chart-box">
          <div class="expand-chart-title">四维拥挤度热力对比</div>
          <div id="expCrowdHeat${idx}" class="expand-chart"></div>
        </div>
      </div>`;
    setTimeout(() => {
      renderCrowdHeatChart(`expCrowdHeat${idx}`, row);
    }, 50);
  }
}

function renderBarChart(domId, row, prefix, title, windows) {
  const dom = document.getElementById(domId);
  if (!dom) return;
  const chart = echarts.init(dom);
  const data = windows.map((w) => row[`${prefix}_${w}`] || 0);
  chart.setOption({
    tooltip: { trigger: "axis", formatter: (p) => `${p[0].name}<br/>${title}: ${(p[0].value * 100).toFixed(2)}%` },
    grid: { left: 55, right: 20, top: 15, bottom: 25 },
    xAxis: { type: "category", data: windows.map((w) => `${w}日`), axisLabel: { fontSize: 10 } },
    yAxis: { type: "value", axisLabel: { fontSize: 10, formatter: (v) => (v * 100).toFixed(0) + "%" }, splitLine: { lineStyle: { color: "#f0ede4" } } },
    series: [{
      type: "bar", barMaxWidth: 36,
      data: data.map((v) => ({
        value: v,
        itemStyle: {
          borderRadius: [4, 4, 0, 0],
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: v > 0 ? "#c44a4a" : "#4a9d6e" },
            { offset: 1, color: v > 0 ? "#f0c0c0" : "#b0e0c0" },
          ]),
        },
      })),
      label: { show: true, position: "top", fontSize: 10, formatter: (p) => (p.value * 100).toFixed(1) + "%" },
    }],
  });
}

function renderLineChart(domId, row, prefix, title, windows) {
  const dom = document.getElementById(domId);
  if (!dom) return;
  const chart = echarts.init(dom);
  const data = windows.map((w) => row[`${prefix}_${w}`] || 0);
  chart.setOption({
    tooltip: { trigger: "axis" },
    grid: { left: 55, right: 20, top: 15, bottom: 25 },
    xAxis: { type: "category", data: windows.map((w) => `${w}日`), axisLabel: { fontSize: 10 } },
    yAxis: { type: "value", axisLabel: { fontSize: 10 }, splitLine: { lineStyle: { color: "#f0ede4" } } },
    series: [{
      type: "line", data, smooth: true, symbol: "circle", symbolSize: 10,
      lineStyle: { width: 3, color: "#c4a24a" }, itemStyle: { color: "#c4a24a" },
      areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: "rgba(196,162,74,0.25)" }, { offset: 1, color: "rgba(196,162,74,0.02)" }]) },
      label: { show: true, fontSize: 10, formatter: (p) => p.value.toFixed(3) },
    }],
  });
}

function renderCrowdHeatChart(domId, row) {
  const dom = document.getElementById(domId);
  if (!dom) return;
  const chart = echarts.init(dom);

  const windows = ["20", "60", "250"];
  const indicators = [
    { name: "成交额占比", key: "amount_share_crowding" },
    { name: "乖离率", key: "price_deviation_crowding" },
    { name: "RS", key: "rs_crowding" },
    { name: "等权复合", key: "equal_weight_crowding" },
  ];

  // 构建热力矩阵：行=指标，列=窗口
  const heatData = [];
  const xLabels = windows.map((w) => `${w}日`);
  const yLabels = indicators.map((d) => d.name);

  indicators.forEach((ind, yi) => {
    windows.forEach((w, xi) => {
      heatData.push([xi, yi, row[`${ind.key}_${w}`] || 0]);
    });
  });

  const option = {
    tooltip: {
      formatter: (p) => {
        const v = p.data[2];
        const pct = (v * 100).toFixed(0);
        let level = "🟢 低";
        if (v > 0.8) level = "🔴 过热";
        else if (v > 0.6) level = "🟠 偏高";
        else if (v > 0.4) level = "🟡 中等";
        return `<b>${yLabels[p.data[1]]}</b> · ${xLabels[p.data[0]]}<br/>拥挤度: <b>${pct}%</b> ${level}`;
      },
    },
    grid: { left: 90, right: 30, top: 10, bottom: 30 },
    xAxis: {
      type: "category",
      data: xLabels,
      position: "top",
      axisLabel: { fontSize: 11, fontWeight: "bold", color: "#555" },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    yAxis: {
      type: "category",
      data: yLabels,
      axisLabel: { fontSize: 12, fontWeight: "bold", color: "#333" },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    visualMap: {
      min: 0,
      max: 1,
      calculable: true,
      orient: "horizontal",
      left: "center",
      bottom: 0,
      inRange: { color: ["#e8f5e9", "#c8e6c9", "#fff9c4", "#ffe0b2", "#ffcdd2", "#ef9a9a", "#e57373"] },
      text: ["过热", "冷静"],
      textStyle: { fontSize: 10 },
    },
    series: [{
      type: "heatmap",
      data: heatData,
      label: {
        show: true,
        fontSize: 13,
        fontWeight: "bold",
        formatter: (p) => (p.data[2] * 100).toFixed(0) + "%",
      },
      emphasis: {
        itemStyle: { shadowBlur: 10, shadowColor: "rgba(0,0,0,0.2)" },
      },
      itemStyle: { borderRadius: 4, borderWidth: 2, borderColor: "#fff" },
    }],
  };
  chart.setOption(option);
}

// ---- 文档模态框 ----
const DOC_MARKDOWN = `# 行业轮动板块模型

行业分类标准：**申万行业分类（一级、二级）**

---

## 技术面因子

### A. 动量

> 下述 \`i\` 值取 **1、5、20、60**

#### 1. RS 动量
使用 RS 在时间序列上的变化率衡量**剔除大盘影响后**的板块轮动强度。

$$
RS\\text{变化率} = \\frac{P_t / M_t}{P_{t-i} / M_{t-i}} - 1
$$

- \\(P_t\\)：本期板块收盘价
- \\(M_t\\)：本期中证全指收盘价

#### 2. 简单收益率动量
使用直接收益率衡量板块轮动强度。

$$
i\\text{期收益率} = \\frac{P_t}{P_{t-i}} - 1
$$

---

### B. 波动率

> 下述 \`i\` 值取 **20、60、120、250**

#### 1. 年化历史收盘价波动率

$$
\\sigma_{close} = \\text{Std}(\\ln\\frac{P_t}{P_{t-1}})_{i\\text{期}} \\times \\sqrt{252}
$$

#### 2. 年化历史日内波动率

$$
\\sigma_{intraday} = \\text{Std}(\\ln\\frac{H_t}{L_t})_{i\\text{期}} \\times \\sqrt{252}
$$

- \\(H_t\\)：日内最高价
- \\(L_t\\)：日内最低价

---

### C. 拥挤度

> 下述 \`i\` 值取 **20、60、250**，所有拥挤度均为过去 \`i\` 期内的**分位数（0~1）**

#### 1. 成交额占比拥挤度

$$
\\text{板块成交额} / \\text{市场成交额}\\ \\text{在过去 } i \\text{ 期内的分位数}
$$

#### 2. 价格乖离率拥挤度

$$
(\\frac{P_t}{MA_{20}} - 1)\\ \\text{在过去 } i \\text{ 期内的分位数}
$$

#### 3. RS 拥挤度

$$
(\\frac{P_t}{M_t})\\ \\text{在过去 } i \\text{ 期内的分位数}
$$

#### 4. 等权复合拥挤度 ⚠️

$$
\\frac{1}{3} \\times [\\ \\text{成交额占比拥挤度} + \\text{价格乖离率拥挤度} + \\text{RS 拥挤度}\\ ]
$$

> **注意**：等权复合拥挤度越接近 1.0，表示该板块越"拥挤"，回调风险越大。
`;

function openDocModal() {
  if (!els.docContent.innerHTML) {
    els.docContent.innerHTML = marked.parse(DOC_MARKDOWN);
    renderMathInElement(els.docContent, {
      delimiters: [
        { left: "$$", right: "$$", display: true },
        { left: "$", right: "$", display: false },
      ],
      throwOnError: false,
    });
  }
  els.docModal.hidden = false;
  document.body.style.overflow = "hidden";
}

function closeDocModal() {
  els.docModal.hidden = true;
  document.body.style.overflow = "";
}

// ---- 启动 ----
init();
