// ---- 状态 ----
const state = {
  reports: new Map(),
  reportOrder: [],
  currentReport: "",
  currentLevel: "一级",
  currentIndustry: "全部",
  searchText: "",
  industryRankMetric: "持仓市值",
  stockRankMetric: "持股总市值",
  summaryRankMetric: "持仓市值",
  top300RankMetric: "持股总市值",
  top300Search: "",
  stockTableSearch: "",
};

// ---- 数据目录配置（相对于 web/ 的路径） ----
var DATA_DIR = "/fund/data";

// ---- DOM 引用 ----
const els = {
  reloadButton: document.getElementById("reloadButton"),
  reportSelect: document.getElementById("reportSelect"),
  levelSelect: document.getElementById("levelSelect"),
  industrySelect: document.getElementById("industrySelect"),
  searchInput: document.getElementById("searchInput"),
  summarySearch: document.getElementById("summarySearch"),
  summaryTable: document.getElementById("summaryTable"),
  top300Table: document.getElementById("top300Table"),
  top300Search: document.getElementById("top300Search"),
  stockTable: document.getElementById("stockTable"),
  stockTableSearch: document.getElementById("stockTableSearch"),
  industryStockTitle: document.getElementById("industryStockTitle"),
  stockTableCount: document.getElementById("stockTableCount"),
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
  Object.values(charts).forEach(function(c) { c.resize(); });
}

window.addEventListener("resize", function() {
  clearTimeout(window._resizeTimer);
  window._resizeTimer = setTimeout(resizeAllCharts, 150);
});

// ---- 工具 ----
var textMap = { "一级": "申万一级", "二级": "申万二级", "三级": "申万三级" };
var numberFormatter = new Intl.NumberFormat("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
var integerFormatter = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 0 });
var CHART_COLORS = ["#c4a24a", "#d4b860", "#9e8030", "#e8d5a0", "#b89540", "#dcc880", "#a08030", "#f0e0b0"];

// Debounced refresh for search inputs
var _refreshTimer = null;
function scheduleRefresh() {
  clearTimeout(_refreshTimer);
  _refreshTimer = setTimeout(refreshView, 200);
}

// ---- 初始化 ----
var initialized = false;
bootstrap();

function initializeUi() {
  els.reloadButton.addEventListener("click", bootstrap);
  els.reportSelect.addEventListener("change", function() {
    state.currentReport = els.reportSelect.value;
    refreshView();
  });
  els.levelSelect.addEventListener("change", function() {
    state.currentLevel = els.levelSelect.value;
    state.currentIndustry = "全部";
    refreshView();
  });
  els.industrySelect.addEventListener("change", function() {
    state.currentIndustry = els.industrySelect.value;
    refreshView();
  });
  els.searchInput.addEventListener("input", function() {
    state.searchText = els.searchInput.value.trim();
    scheduleRefresh();
  });
  els.summarySearch.addEventListener("input", function() {
    scheduleRefresh();
  });
  els.top300Search.addEventListener("input", function() {
    state.top300Search = els.top300Search.value.trim();
    scheduleRefresh();
  });
  els.stockTableSearch.addEventListener("input", function() {
    state.stockTableSearch = els.stockTableSearch.value.trim();
    scheduleRefresh();
  });

  // 行业明细排名切换
  document.querySelectorAll("#summaryRankTabs .rank-tab").forEach(function(btn) {
    btn.addEventListener("click", function() {
      document.querySelectorAll("#summaryRankTabs .rank-tab").forEach(function(b) { b.classList.remove("active"); });
      btn.classList.add("active");
      state.summaryRankMetric = btn.dataset.metric;
      refreshView();
    });
  });

  // 全市场前300排名切换
  document.querySelectorAll("#top300RankTabs .rank-tab").forEach(function(btn) {
    btn.addEventListener("click", function() {
      document.querySelectorAll("#top300RankTabs .rank-tab").forEach(function(b) { b.classList.remove("active"); });
      btn.classList.add("active");
      state.top300RankMetric = btn.dataset.metric;
      refreshView();
    });
  });

  // 行业排名切换
  document.querySelectorAll("#industryRankTabs .rank-tab").forEach(function(btn) {
    btn.addEventListener("click", function() {
      document.querySelectorAll("#industryRankTabs .rank-tab").forEach(function(b) { b.classList.remove("active"); });
      btn.classList.add("active");
      state.industryRankMetric = btn.dataset.metric;
      refreshView();
    });
  });

  // 股票排名切换
  document.querySelectorAll("#stockRankTabs .rank-tab").forEach(function(btn) {
    btn.addEventListener("click", function() {
      document.querySelectorAll("#stockRankTabs .rank-tab").forEach(function(b) { b.classList.remove("active"); });
      btn.classList.add("active");
      state.stockRankMetric = btn.dataset.metric;
      refreshView();
    });
  });
}

async function bootstrap() {
  initializeUiOnce();
  try {
    // 自动扫描 DATA_DIR 下所有 *_enriched.csv，配对 *_summary.csv
    var reportList = await discoverReports();
    var reports = await Promise.all(reportList.map(loadReport));
    var validReports = reports
      .filter(function(r) { return r && r.enriched.length && r.summary.length; })
      .sort(function(a, b) { return b.reportDate.localeCompare(a.reportDate) || b.stem.localeCompare(a.stem); });

    state.reports = new Map(validReports.map(function(r) { return [r.stem, r]; }));
    state.reportOrder = validReports.map(function(r) { return r.stem; });

    if (!state.reportOrder.length) { clearAll(); return; }

    state.currentReport = state.reportOrder[0];
    state.currentLevel = "一级";
    state.currentIndustry = "全部";
    state.searchText = "";

    populateControls();
    refreshView();
  } catch (error) {
    console.error(error);
    clearAll();
  }
}

// ---- 自动发现报告期：列出目录下 *_enriched.csv，推断 stem 和日期 ----
async function discoverReports() {
  // 尝试列出目录（需要服务器支持目录列表，否则回退到逐个探测常见命名）
  var list = [];
  // 常见报告期命名模式
  var patterns = [];
  var now = new Date();
  var thisYear = now.getFullYear();
  for (var y = thisYear; y >= thisYear - 3; y--) {
    for (var q = 4; q >= 1; q--) {
      patterns.push(y + "Q" + q);
    }
    for (var h = 2; h >= 1; h--) {
      patterns.push(y + "H" + h);
    }
  }

  // 并发探测所有可能的文件
  var checks = patterns.map(function(stem) {
    var enrichedFile = stem + "_enriched.csv";
    var summaryFile = stem + "_summary.csv";
    var url = new URL(DATA_DIR + "/" + enrichedFile, window.location.href);
    return fetch(url, { method: "HEAD" }).then(function(resp) {
      if (resp.ok) {
        // 从 stem 推断日期：2026Q1 → 2026-03-31, 2026H1 → 2026-06-30
        var date = stemToDate(stem);
        list.push({ stem: stem, reportDate: date, enriched: enrichedFile, summary: summaryFile });
      }
    }).catch(function() { /* 文件不存在，跳过 */ });
  });

  await Promise.all(checks);
  return list;
}

function stemToDate(stem) {
  var match = stem.match(/^(\d{4})(Q|H)(\d)$/);
  if (!match) return stem;
  var year = match[1], type = match[2], num = match[3];
  if (type === "Q") {
    var lastDay = { "1": "03-31", "2": "06-30", "3": "09-30", "4": "12-31" };
    return year + "-" + (lastDay[num] || "12-31");
  }
  if (type === "H") {
    return year + "-" + (num === "1" ? "06-30" : "12-31");
  }
  return stem;
}

function initializeUiOnce() {
  if (initialized) return;
  initializeUi();
  initialized = true;
}

// ---- 数据加载 ----
async function loadReport(entry) {
  var enrichedUrl = new URL(DATA_DIR + "/" + entry.enriched, window.location.href);
  var summaryUrl = new URL(DATA_DIR + "/" + entry.summary, window.location.href);
  var results = await Promise.all([fetchCsvText(enrichedUrl), fetchCsvText(summaryUrl)]);
  return {
    stem: cleanValue(entry.stem),
    reportDate: cleanValue(entry.reportDate),
    enriched: parseCsv(results[0]),
    summary: parseCsv(results[1]),
  };
}

async function fetchCsvText(url) {
  var resp = await fetch(url, { cache: "no-store" });
  if (!resp.ok) throw new Error("读取失败: " + url.pathname);
  return resp.text();
}

// ---- 控件 ----
function populateControls() {
  els.reportSelect.disabled = false;
  els.levelSelect.disabled = false;
  els.industrySelect.disabled = false;
  els.searchInput.disabled = false;

  els.reportSelect.innerHTML = state.reportOrder.map(function(s) {
    return '<option value="' + escapeHtml(s) + '">' + escapeHtml(s) + '</option>';
  }).join("");
  els.reportSelect.value = state.currentReport;
  els.levelSelect.value = state.currentLevel;
  els.searchInput.value = "";
}

// ---- 视图刷新 ----
function refreshView() {
  var report = state.reports.get(state.currentReport);
  if (!report) { clearAll(); return; }

  var levelKey = textMap[state.currentLevel];
  var summaryRows = report.summary.filter(function(r) { return r["统计表"] === state.currentLevel + "行业"; });
  var stockRows = report.enriched.map(function(r, i) { return normalizeStockRow(r, i); });
  var currentIndustry = updateIndustryOptions(summaryRows, levelKey);

  var industryRows = currentIndustry === "全部"
    ? stockRows
    : stockRows.filter(function(r) { return r[levelKey] === currentIndustry; });

  var searchedIndustryRows = filterBySearch(industryRows, state.searchText);
  var searchedOverallRows = filterBySearch(stockRows, state.searchText);

  updateSummaryCards(report, searchedIndustryRows, summaryRows);
  renderIndustryHoldingChart(summaryRows, levelKey);
  renderIndustryStockChart(searchedIndustryRows, currentIndustry);
  renderSummaryTable(summaryRows, levelKey);
  renderTop300Table(searchedOverallRows);
  renderStockTable(searchedIndustryRows);
}

// ---- 摘要卡 ----
function updateSummaryCards(report, industryRows, summaryRows) {
  els.industryStockTitle.textContent = state.currentIndustry === "全部" ? "🏆 全市场股票排行" : "🏆 " + state.currentIndustry + " · 股票排行";
  els.stockTableCount.textContent = industryRows.length + " 只";
}

// ---- 行业下拉 ----
function updateIndustryOptions(summaryRows, levelKey) {
  var list = Array.from(new Map(summaryRows.map(function(r) { return [cleanValue(r[levelKey]) || "其它", r]; })).values())
    .map(function(r) { return { name: cleanValue(r[levelKey]) || "其它", val: toNumber(r["持仓市值(万元)合计"]) }; })
    .sort(function(a, b) { return b.val - a.val || a.name.localeCompare(b.name, "zh-Hans-CN"); });

  var prev = state.currentIndustry;
  els.industrySelect.innerHTML = '<option value="全部">全部</option>' +
    list.map(function(it) { return '<option value="' + escapeHtml(it.name) + '">' + escapeHtml(it.name) + '</option>'; }).join("");

  if (prev === "全部") {
    state.currentIndustry = list.length ? list[0].name : "全部";
  } else if (list.length && !list.some(function(it) { return it.name === prev; })) {
    state.currentIndustry = list[0].name;
  }
  els.industrySelect.value = state.currentIndustry;
  return state.currentIndustry;
}

// ============ ECharts 图表 ============

function renderHorizontalBarChart(domId, data, metricLabel) {
  var chart = charts[domId];
  if (!chart) {
    chart = initChart(domId);
    if (!chart) return;
  }

  if (!data.length) { chart.clear(); return; }

  var names = data.map(function(d) { return d.name; });
  var values = data.map(function(d) { return d.value; });
  var colors = values.map(function(_, i) { return CHART_COLORS[i % CHART_COLORS.length]; });

  var isPercent = metricLabel === "持仓占比";
  var isCount = metricLabel === "基金覆盖";

  // Reset container to fixed height — scrolling handled by dataZoom
  var dom = document.getElementById(domId);
  if (dom) { dom.style.height = "480px"; }

  function formatChartVal(v) {
    if (isPercent) return formatPercent(v);
    if (isCount) return formatInteger(v);
    return formatYi(v);
  }

  chart.setOption({
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" },
      backgroundColor: "rgba(26,26,26,0.95)",
      borderColor: "rgba(255,255,255,0.1)",
      textStyle: { color: "#fff", fontSize: 12 },
      formatter: function(params) {
        var p = params[0];
        var raw = data.find(function(d) { return d.name === p.name; });
        var v = raw ? raw.value : p.value;
        return '<strong>' + escapeHtml(p.name) + '</strong><br/>' + metricLabel + ': ' + formatChartVal(v);
      },
    },
    grid: { left: 150, right: 70, top: 10, bottom: 60 },
    dataZoom: [
      {
        type: "slider",
        show: names.length > 20,
        yAxisIndex: 0,
        start: 0,
        end: names.length > 20 ? Math.min(100, Math.round(2000 / names.length)) : 100,
        width: 20,
        right: 10,
        borderColor: "transparent",
        backgroundColor: "rgba(232,229,220,0.3)",
        fillerColor: "rgba(196,162,74,0.15)",
        handleStyle: { color: "#c4a24a" },
        textStyle: { color: "#999" },
      },
      {
        type: "inside",
        yAxisIndex: 0,
        zoomOnMouseWheel: false,
        moveOnMouseMove: true,
        moveOnMouseWheel: true,
      },
    ],
    xAxis: {
      type: "value",
      axisLabel: {
        color: "#999", fontSize: 11,
        formatter: function(v) { return formatChartVal(v); },
      },
      splitLine: { lineStyle: { color: "#e8e5dc", type: "dashed" } },
    },
    yAxis: {
      type: "category",
      data: names,
      axisLabel: { color: "#1a1a1a", fontSize: 12, fontWeight: 600 },
      axisLine: { show: false },
      axisTick: { show: false },
      inverse: true,
    },
    series: [{
      type: "bar",
      data: values.map(function(v, i) {
        return { value: v, itemStyle: { color: colors[i], borderRadius: [0, 4, 4, 0] } };
      }),
      barWidth: 16,
      barCategoryGap: "20%",
      label: {
        show: true, position: "right", color: "#999", fontSize: 11,
        formatter: function(p) { return formatChartVal(p.value); },
      },
    }],
  }, true);
}

function getIndustryMetricKey() {
  if (state.industryRankMetric === "基金覆盖") return "基金覆盖家数(只)合计";
  if (state.industryRankMetric === "持仓占比") return "持仓市值/总市值(%)";
  return "持仓市值(万元)合计";
}

function getStockMetricKey() {
  if (state.stockRankMetric === "基金覆盖") return "基金覆盖家数(只)";
  if (state.stockRankMetric === "持仓占比") return "持仓市值/总市值(%)";
  return "持股总市值(万元)";
}

function getSummaryMetricKey() {
  if (state.summaryRankMetric === "基金覆盖") return "基金覆盖家数(只)合计";
  if (state.summaryRankMetric === "持仓占比") return "持仓市值/总市值(%)";
  return "持仓市值(万元)合计";
}

function getTop300MetricKey() {
  if (state.top300RankMetric === "基金覆盖") return "基金覆盖家数(只)";
  if (state.top300RankMetric === "持仓占比") return "持仓市值/总市值(%)";
  return "持股总市值(万元)";
}

function renderIndustryHoldingChart(summaryRows, levelKey) {
  var metricKey = getIndustryMetricKey();
  var metricLabel = state.industryRankMetric;
  var data = summaryRows
    .map(function(r) { return { name: cleanValue(r[levelKey]) || "其它", value: toNumber(r[metricKey]) }; })
    .sort(function(a, b) { return b.value - a.value; });
  renderHorizontalBarChart("industryHoldingChart", data, metricLabel);
}

function renderIndustryStockChart(stockRows, industryName) {
  var metricKey = getStockMetricKey();
  var metricLabel = state.stockRankMetric;
  var data = [].concat(stockRows)
    .sort(function(a, b) { return toNumber(b[metricKey]) - toNumber(a[metricKey]); })
    .slice(0, 50)
    .map(function(r) { return { name: r["股票简称"] + " (" + r["股票代码"] + ")", value: toNumber(r[metricKey]) }; });
  renderHorizontalBarChart("industryStockChart", data, metricLabel);
}

// ============ 表格 ============

// Fast DOM builder — builds all rows as a single HTML string, then inserts once
function buildTableBody(rows, rowFn) {
  var tbody = document.createElement("tbody");
  var html = "";
  for (var i = 0; i < rows.length; i++) {
    html += "<tr>" + rowFn(rows[i], i) + "</tr>";
  }
  tbody.innerHTML = html;
  return tbody;
}

function renderSummaryTable(rows, industryKey) {
  var table = els.summaryTable;
  var searchText = els.summarySearch.value.trim().toLowerCase();
  var filtered = searchText
    ? rows.filter(function(r) { return (cleanValue(r[industryKey]) || "").toLowerCase().indexOf(searchText) !== -1; })
    : rows;

  // Sort by selected metric
  var metricKey = getSummaryMetricKey();
  filtered = [].concat(filtered).sort(function(a, b) { return toNumber(b[metricKey]) - toNumber(a[metricKey]); });

  var thead = table.querySelector("thead");
  var tbody = table.querySelector("tbody");

  if (!filtered.length) {
    thead.innerHTML = "";
    tbody.innerHTML = '<tr><td class="empty-state">暂无匹配数据</td></tr>';
    return;
  }

  var headers = ["排名", industryKey, "股票数", "基金覆盖(只)", "持仓市值(亿)", "总市值(亿)", "持仓占比(%)", "覆盖排名", "市值排名", "比例排名"];
  thead.innerHTML = "<tr>" + headers.map(function(h) { return "<th>" + h + "</th>"; }).join("") + "</tr>";

  var frag = buildTableBody(filtered, function(r, i) {
    return "<td>" + (i + 1) + "</td>" +
      "<td>" + escapeHtml(cleanValue(r[industryKey])) + "</td>" +
      "<td>" + formatInteger(r["股票数"]) + "</td>" +
      "<td>" + formatInteger(r["基金覆盖家数(只)合计"]) + "</td>" +
      "<td>" + formatYi(r["持仓市值(万元)合计"]) + "</td>" +
      "<td>" + formatYi(r["总市值(万元)合计"]) + "</td>" +
      "<td>" + formatPercent(r["持仓市值/总市值(%)"]) + "</td>" +
      "<td>" + formatInteger(r["基金覆盖家数排名"]) + "</td>" +
      "<td>" + formatInteger(r["持仓市值排名"]) + "</td>" +
      "<td>" + formatInteger(r["比例排名"]) + "</td>";
  });
  tbody.parentNode.replaceChild(frag, tbody);
}

function renderTop300Table(rows) {
  var table = els.top300Table;
  
  // Apply search filter
  var searchText = state.top300Search.toLowerCase();
  var filtered = searchText
    ? rows.filter(function(r) {
        return [r["股票代码"], r["股票简称"], r["申万一级"], r["申万二级"], r["申万三级"]].join(" ").toLowerCase().indexOf(searchText) !== -1;
      })
    : rows;

  var thead = table.querySelector("thead");
  var tbody = table.querySelector("tbody");

  if (!filtered.length) {
    thead.innerHTML = "";
    tbody.innerHTML = '<tr><td class="empty-state">暂无匹配结果</td></tr>';
    return;
  }

  var headers = ["排名", "股票代码", "股票简称", "申万一级", "申万二级", "申万三级", "基金覆盖(只)", "持仓市值(亿)", "总市值(亿)", "持仓占比(%)"];
  
  var metricKey = getTop300MetricKey();
  var sorted = [].concat(filtered).sort(function(a, b) { 
    return toNumber(b[metricKey]) - toNumber(a[metricKey]); 
  });

  thead.innerHTML = "<tr>" + headers.map(function(h) { return "<th>" + h + "</th>"; }).join("") + "</tr>";

  // Lazy render: first 200 rows, rest on demand
  var BATCH = 200;
  var visible = sorted.slice(0, BATCH);
  var remaining = sorted.slice(BATCH);

  var frag = buildTableBody(visible, function(r, i) {
    return "<td>" + (i + 1) + "</td>" +
      "<td>" + escapeHtml(r["股票代码"]) + "</td>" +
      "<td>" + escapeHtml(r["股票简称"]) + "</td>" +
      "<td>" + escapeHtml(r["申万一级"]) + "</td>" +
      "<td>" + escapeHtml(r["申万二级"]) + "</td>" +
      "<td>" + escapeHtml(r["申万三级"]) + "</td>" +
      "<td>" + formatInteger(r["基金覆盖家数(只)"]) + "</td>" +
      "<td>" + formatYi(r["持股总市值(万元)"]) + "</td>" +
      "<td>" + formatYi(r["总市值(万元)"]) + "</td>" +
      "<td>" + formatPercent(r["持仓市值/总市值(%)"]) + "</td>";
  });

  if (remaining.length) {
    var loadRow = document.createElement("tr");
    loadRow.innerHTML = '<td colspan="10" style="text-align:center;padding:16px;cursor:pointer;color:var(--accent);font-weight:600;" id="top300LoadMore">📋 加载更多（剩余 ' + remaining.length + ' 条）</td>';
    frag.appendChild(loadRow);
  }

  tbody.parentNode.replaceChild(frag, tbody);

  // Bind click to load remaining
  if (remaining.length) {
    var btn = document.getElementById("top300LoadMore");
    if (btn) {
      btn.addEventListener("click", function() {
        var moreFrag = buildTableBody(remaining, function(r, i) {
          return "<td>" + (BATCH + i + 1) + "</td>" +
            "<td>" + escapeHtml(r["股票代码"]) + "</td>" +
            "<td>" + escapeHtml(r["股票简称"]) + "</td>" +
            "<td>" + escapeHtml(r["申万一级"]) + "</td>" +
            "<td>" + escapeHtml(r["申万二级"]) + "</td>" +
            "<td>" + escapeHtml(r["申万三级"]) + "</td>" +
            "<td>" + formatInteger(r["基金覆盖家数(只)"]) + "</td>" +
            "<td>" + formatYi(r["持股总市值(万元)"]) + "</td>" +
            "<td>" + formatYi(r["总市值(万元)"]) + "</td>" +
            "<td>" + formatPercent(r["持仓市值/总市值(%)"]) + "</td>";
        });
        btn.parentNode.parentNode.replaceChild(moreFrag, btn.parentNode);
      }, { once: true });
    }
  }
}

function renderStockTable(rows) {
  var table = els.stockTable;
  
  // Apply search filter
  var searchText = state.stockTableSearch.toLowerCase();
  var filtered = searchText
    ? rows.filter(function(r) {
        return [r["股票代码"], r["股票简称"], r["申万一级"], r["申万二级"], r["申万三级"]].join(" ").toLowerCase().indexOf(searchText) !== -1;
      })
    : rows;

  var thead = table.querySelector("thead");
  var tbody = table.querySelector("tbody");

  if (!filtered.length) {
    thead.innerHTML = "";
    tbody.innerHTML = '<tr><td class="empty-state">暂无匹配结果</td></tr>';
    return;
  }

  var headers = ["排名", "股票代码", "股票简称", "申万一级", "申万二级", "申万三级", "基金覆盖(只)", "持仓市值(亿)", "总市值(亿)", "持仓占比(%)"];
  var metricKey = getStockMetricKey();
  var sorted = [].concat(filtered).sort(function(a, b) { return toNumber(b[metricKey]) - toNumber(a[metricKey]); });

  thead.innerHTML = "<tr>" + headers.map(function(h) { return "<th>" + h + "</th>"; }).join("") + "</tr>";

  var frag = buildTableBody(sorted, function(r, i) {
    return "<td>" + (i + 1) + "</td>" +
      "<td>" + escapeHtml(r["股票代码"]) + "</td>" +
      "<td>" + escapeHtml(r["股票简称"]) + "</td>" +
      "<td>" + escapeHtml(r["申万一级"]) + "</td>" +
      "<td>" + escapeHtml(r["申万二级"]) + "</td>" +
      "<td>" + escapeHtml(r["申万三级"]) + "</td>" +
      "<td>" + formatInteger(r["基金覆盖家数(只)"]) + "</td>" +
      "<td>" + formatYi(r["持股总市值(万元)"]) + "</td>" +
      "<td>" + formatYi(r["总市值(万元)"]) + "</td>" +
      "<td>" + formatPercent(r["持仓市值/总市值(%)"]) + "</td>";
  });
  tbody.parentNode.replaceChild(frag, tbody);
}

// ============ 数据工具 ============

function normalizeStockRow(row, index) {
  return {
    __id: cleanValue(row["股票代码"]) + "_" + index,
    "股票代码": cleanValue(row["股票代码"]),
    "股票简称": cleanValue(row["股票简称"]),
    "申万一级": cleanValue(row["申万一级"]),
    "申万二级": cleanValue(row["申万二级"]),
    "申万三级": cleanValue(row["申万三级"]),
    "基金覆盖家数(只)": toNumber(row["基金覆盖家数(只)"]),
    "持股总市值(万元)": toNumber(row["持股总市值(万元)"]),
    "总市值(万元)": toNumber(row["总市值(万元)"]),
    "持仓市值/总市值(%)": toNumber(row["持仓市值/总市值(%)"]),
  };
}

function filterBySearch(rows, text) {
  if (!text) return rows;
  var kw = text.toLowerCase();
  return rows.filter(function(r) {
    return [r["股票代码"], r["股票简称"], r["申万一级"], r["申万二级"], r["申万三级"]].join(" ").toLowerCase().indexOf(kw) !== -1;
  });
}

// ============ CSV 解析 ============

function parseCsv(text) {
  var normalized = text.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  var rows = [];
  var cur = "", row = [], inQ = false;
  for (var i = 0; i < normalized.length; i++) {
    var ch = normalized[i], nx = normalized[i + 1];
    if (inQ) {
      if (ch === '"') { if (nx === '"') { cur += '"'; i++; } else inQ = false; }
      else cur += ch;
      continue;
    }
    if (ch === '"') { inQ = true; continue; }
    if (ch === ",") { row.push(cur); cur = ""; continue; }
    if (ch === "\n") { row.push(cur); rows.push(row); row = []; cur = ""; continue; }
    cur += ch;
  }
  row.push(cur);
  if (row.length > 1 || row[0].trim() !== "") rows.push(row);
  if (!rows.length) return [];
  var headers = rows.shift().map(function(h) { return h.trim(); });
  return rows.filter(function(rv) { return rv.some(function(c) { return c.trim() !== ""; }); }).map(function(rv) {
    var e = {};
    headers.forEach(function(h, i) { e[h] = (rv[i] || "").trim(); });
    return e;
  });
}

// ============ 基础工具 ============

function cleanValue(v) {
  if (v === null || v === undefined) return "";
  var t = String(v).trim();
  return (!t || t.toLowerCase() === "nan" || t === "undefined") ? "" : t;
}

function toNumber(v) {
  if (v === null || v === undefined || v === "") return 0;
  var n = Number(String(v).replace(/,/g, ""));
  return isFinite(n) ? n : 0;
}

function formatInteger(v) { return integerFormatter.format(toNumber(v)); }
function formatMoney(v) { return numberFormatter.format(toNumber(v)); }
function formatYi(v) { return numberFormatter.format(toNumber(v) / 10000); }
function formatPercent(v) { return numberFormatter.format(toNumber(v)) + "%"; }

function escapeHtml(v) {
  return String(v).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function clearAll() {
  els.industrySelect.innerHTML = '<option value="全部">全部</option>';
  els.summaryTable.querySelector("thead").innerHTML = "";
  els.summaryTable.querySelector("tbody").innerHTML = '<tr><td class="empty-state">加载中…</td></tr>';
  els.stockTable.querySelector("thead").innerHTML = "";
  els.stockTable.querySelector("tbody").innerHTML = '<tr><td class="empty-state">加载中…</td></tr>';
  Object.values(charts).forEach(function(c) { c.clear(); });
}
