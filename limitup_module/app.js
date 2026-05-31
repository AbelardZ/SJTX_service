const COL = {
  code: "股票代码",
  name: "股票名称",
  change: "涨跌幅",
  marketValue: "流通市值",
  turnover: "换手率",
  sealAmount: "封板资金",
  firstSeal: "首次封板时间",
  lastSeal: "最后封板时间",
  breaks: "炸板次数",
  limitStats: "涨停统计",
  chain: "连板数",
  industry1: "申万一级",
  industry2: "申万二级",
  industry3: "申万三级",
  theme: "韭研题材",
  note: "韭研解读",
};

const hiddenTableColumns = new Set([COL.note]);
const numericColumns = new Set([
  COL.change,
  COL.marketValue,
  COL.turnover,
  COL.sealAmount,
  COL.breaks,
  COL.chain,
]);
const tagColumns = new Set([COL.limitStats, COL.industry1, COL.industry2, COL.industry3, COL.theme]);
const dangerColumns = new Set([COL.change, COL.chain]);
const timeColumns = new Set([COL.firstSeal, COL.lastSeal]);
const trendColors = ["#a38b55", "#8b7a5c", "#c49a6c", "#9e8e6e", "#b8a080", "#7a8b6e", "#a09078", "#8a7a62"];

const state = {
  dates: [],
  dailyData: new Map(),
  columns: [],
  rows: [],
  filteredRows: [],
  activeFilters: {
    industry: null,
    theme: null,
  },
  trendRange: "5",
  customStart: "",
  customEnd: "",
  selectedTrendCategories: {
    industry: new Set(),
    theme: new Set(),
  },
  sortKey: "",
  sortDir: "asc",
};

const els = {
  dateSelect: document.querySelector("#dateSelect"),
  rangeButtons: document.querySelector(".range-buttons"),
  customRange: document.querySelector("#customRange"),
  trendStart: document.querySelector("#trendStart"),
  trendEnd: document.querySelector("#trendEnd"),
  totalTrendChart: document.querySelector("#totalTrendChart"),
  industryTrendChart: document.querySelector("#industryTrendChart"),
  themeTrendChart: document.querySelector("#themeTrendChart"),
  trendTotalSummary: document.querySelector("#trendTotalSummary"),
  clearFilterButton: document.querySelector("#clearFilterButton"),
  activeFilterText: document.querySelector("#activeFilterText"),
  tableHead: document.querySelector("#tableHead"),
  tableBody: document.querySelector("#tableBody"),
  status: document.querySelector("#status"),
  totalCount: document.querySelector("#totalCount"),
  visibleCount: document.querySelector("#visibleCount"),
  maxChain: document.querySelector("#maxChain"),
  industryStats: document.querySelector("#industryStats"),
  themeStats: document.querySelector("#themeStats"),
  themeDistribution: document.querySelector("#themeDistribution"),
};

function showStatus(message) {
  els.status.textContent = message;
  els.status.classList.add("show");
}

function hideStatus() {
  els.status.classList.remove("show");
}

async function fetchJson(url) {
  const response = await fetch(url);
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || "请求失败");
  }
  return payload;
}

async function init() {
  try {
    showStatus("正在加载趋势数据...");
    const { dates } = await fetchJson("/limitup/api/dates");
    if (!dates.length) {
      showStatus("未在 sumup/data 中找到 CSV 文件");
      return;
    }

    state.dates = [...dates].sort();
    setupCustomRangeDefaults();
    els.dateSelect.innerHTML = dates
      .map((date) => `<option value="${escapeHtml(date)}">${escapeHtml(date)}</option>`)
      .join("");

    // 阶段1: 先加载轻量级趋势聚合数据，快速渲染趋势图
    await loadTrendDataFromAggregatedApi();
    renderTrends();
    hideStatus();

    // 阶段2: 后台加载当日详细数据（表格+统计）
    await loadDate(dates[0]);

    // 阶段3: 后台静默预加载所有日期的完整数据（用于后续日期切换加速）
    prefetchAllDailyData(dates);
  } catch (error) {
    showStatus(error.message);
  }
}

async function loadTrendDataFromAggregatedApi() {
  try {
    const trendData = await fetchJson("/limitup/api/trend");
    // 将聚合数据转换为 dailyData Map 格式，兼容现有 renderTrends 逻辑
    state.dailyData.clear();
    trendData.dates.forEach((date) => {
      // 从聚合数据重建每行的简要数据（仅包含趋势图需要的字段）
      const rows = [];
      // 为每个行业创建虚拟行
      const industrySeries = trendData.industry || {};
      const themeSeries = trendData.theme || {};

      // 用 total 系列来填充 dailyData
      const totalForDate = (trendData.total || []).find((d) => d.date === date);
      const count = totalForDate ? totalForDate.value : 0;

      // 构建轻量行数据：每只股票一行，但只包含趋势图需要的列
      // 实际上 renderTrends 只需要 COL.industry1 和 COL.theme
      // 我们从聚合数据重建
      const industryEntries = Object.entries(industrySeries);
      const themeEntries = Object.entries(themeSeries);

      // 为每个行业-日期组合创建行
      for (const [industry, series] of industryEntries) {
        const point = series.find((d) => d.date === date);
        if (point && point.value > 0) {
          for (let i = 0; i < point.value; i++) {
            rows.push({ [COL.industry1]: industry, [COL.theme]: "" });
          }
        }
      }
      // 为每个题材-日期组合创建行（补充题材信息）
      let rowIdx = 0;
      for (const [theme, series] of themeEntries) {
        const point = series.find((d) => d.date === date);
        if (point && point.value > 0) {
          for (let i = 0; i < point.value; i++) {
            if (rowIdx < rows.length) {
              rows[rowIdx][COL.theme] = rows[rowIdx][COL.theme]
                ? rows[rowIdx][COL.theme] + "+" + theme
                : theme;
            } else {
              rows.push({ [COL.industry1]: "", [COL.theme]: theme });
            }
            rowIdx++;
          }
        }
      }

      state.dailyData.set(date, rows);
    });
  } catch (e) {
    // 如果聚合接口失败，回退到旧方式
    console.warn("趋势聚合接口失败，回退到全量加载:", e);
    await loadTrendDataFallback(state.dates);
  }
}

async function loadTrendDataFallback(dates) {
  const payloads = await Promise.all(
    dates.map((date) => fetchJson(`/limitup/api/data?date=${encodeURIComponent(date)}`)),
  );
  payloads.forEach((payload) => {
    state.dailyData.set(payload.date, payload.rows || []);
  });
}

async function prefetchAllDailyData(dates) {
  // 后台静默预加载所有日期的完整数据，加速后续日期切换
  for (const date of dates) {
    if (state.dailyData.has(date) && state.dailyData.get(date).length > 0) {
      // 检查是否已有完整数据（通过检查是否有 COL.code 列）
      const rows = state.dailyData.get(date);
      if (rows.length > 0 && rows[0][COL.code] !== undefined) continue;
    }
    try {
      const payload = await fetchJson(`/limitup/api/data?date=${encodeURIComponent(date)}`);
      state.dailyData.set(payload.date, payload.rows || []);
    } catch (e) {
      // 静默失败
    }
  }
}

// 保留旧函数名兼容（但不再在 init 中调用）
async function loadTrendData(dates) {
  await loadTrendDataFromAggregatedApi();
}

function setupCustomRangeDefaults() {
  const dates = state.dates;
  if (!dates.length) return;
  const end = dates.at(-1);
  const start = dates[Math.max(0, dates.length - 5)];
  state.customStart = start;
  state.customEnd = end;
  els.trendStart.min = dates[0];
  els.trendStart.max = end;
  els.trendEnd.min = dates[0];
  els.trendEnd.max = end;
  els.trendStart.value = start;
  els.trendEnd.value = end;
}

async function loadDate(tradeDate) {
  try {
    showStatus("正在加载 CSV...");
    const payload = await fetchJson(`/limitup/api/data?date=${encodeURIComponent(tradeDate)}`);
    state.columns = payload.columns;
    state.rows = payload.rows;
    state.activeFilters = { industry: null, theme: null };
    state.sortKey = "";
    state.sortDir = "asc";
    applyView();
    hideStatus();
  } catch (error) {
    showStatus(error.message);
  }
}

function applyView() {
  let rows = state.rows.filter(rowMatchesFilters);

  if (state.sortKey) {
    rows = [...rows].sort((a, b) => compareRows(a, b, state.sortKey, state.sortDir));
  }

  state.filteredRows = rows;
  renderTable();
  renderMetrics();
  renderThemeDistribution();
  renderActiveFilter();
}

function renderTrends() {
  const dates = selectedTrendDates();
  const daily = dates.map((date) => ({
    date,
    rows: state.dailyData.get(date) || [],
  }));

  const totalSeries = daily.map((item) => ({
    date: item.date,
    value: item.rows.length,
  }));

  const totals = totalSeries.map((item) => item.value);
  const latest = totals.at(-1) ?? 0;
  const peak = totals.length ? Math.max(...totals) : 0;
  els.trendTotalSummary.textContent = dates.length ? `${latest} / 峰值 ${peak}` : "-";

  renderTotalTrend(totalSeries);
  renderCategoryTrend(els.industryTrendChart, daily, COL.industry1, splitSingleValue, "industry");
  renderCategoryTrend(els.themeTrendChart, daily, COL.theme, splitThemes, "theme");
}

function selectedTrendDates() {
  const dates = state.dates;
  if (!dates.length) return [];

  if (state.trendRange === "custom") {
    const start = state.customStart || dates[0];
    const end = state.customEnd || dates.at(-1);
    return dates.filter((date) => date >= start && date <= end);
  }

  const count = Number(state.trendRange);
  return dates.slice(Math.max(0, dates.length - count));
}

function renderTotalTrend(series) {
  if (!series.length) {
    els.totalTrendChart.innerHTML = `<div class="empty-chart">暂无趋势数据</div>`;
    return;
  }

  const width = 900;
  const height = 210;
  const pad = { top: 22, right: 22, bottom: 38, left: 38 };
  const chartWidth = width - pad.left - pad.right;
  const chartHeight = height - pad.top - pad.bottom;
  const maxValue = Math.max(1, ...series.map((item) => item.value));
  const xFor = (index) =>
    pad.left + (series.length === 1 ? chartWidth / 2 : (index / (series.length - 1)) * chartWidth);
  const yFor = (value) => pad.top + chartHeight - (value / maxValue) * chartHeight;
  const points = series.map((item, index) => ({ x: xFor(index), y: yFor(item.value), ...item }));
  const linePath = smoothPath(points);
  const areaPath = `${linePath} L ${points.at(-1).x} ${pad.top + chartHeight} L ${points[0].x} ${pad.top + chartHeight} Z`;

  const labels = points
    .map((point) => `<text class="trend-label" x="${point.x}" y="${height - 12}" text-anchor="middle">${formatDateLabel(point.date)}</text>`)
    .join("");

  const dots = points
    .map(
      (point) => `
        <circle class="trend-dot" cx="${point.x}" cy="${point.y}" r="5" fill="#b8872b"></circle>
      `,
    )
    .join("");
  const hoverZones = renderHoverZones(points, height, pad, (point) => `${point.date}\n总涨停: ${point.value}`);

  els.totalTrendChart.innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="总涨停数量趋势">
      ${renderGridLines(width, height, pad)}
      <line class="trend-axis" x1="${pad.left}" y1="${pad.top + chartHeight}" x2="${width - pad.right}" y2="${pad.top + chartHeight}"></line>
      <path d="${areaPath}" fill="rgba(216, 173, 79, 0.18)"></path>
      <path d="${linePath}" fill="none" stroke="#b8872b" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"></path>
      ${dots}
      ${hoverZones}
      ${labels}
    </svg>
  `;
}

function renderCategoryTrend(container, daily, column, splitter, kind) {
  if (!daily.length) {
    container.innerHTML = `<div class="empty-chart">暂无趋势数据</div>`;
    return;
  }

  const totals = new Map();
  daily.forEach((item) => {
    item.rows.forEach((row) => {
      splitter(row[column] || "").forEach((value) => {
        totals.set(value, (totals.get(value) || 0) + 1);
      });
    });
  });

  const categories = [...totals.entries()].sort(
    (a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "zh-Hans-CN"),
  );

  if (!categories.length) {
    container.innerHTML = `<div class="empty-chart">暂无分类数据</div>`;
    return;
  }

  const selected = state.selectedTrendCategories[kind];
  const shownCategories = selected.size
    ? categories.map(([value]) => value).filter((value) => selected.has(value))
    : categories.slice(0, 5).map(([value]) => value);

  const series = shownCategories.map((category) => ({
    category,
    values: daily.map((item) => ({
      date: item.date,
      value: item.rows.reduce((count, row) => {
        return count + (splitter(row[column] || "").includes(category) ? 1 : 0);
      }, 0),
    })),
  }));

  const maxValue = Math.max(1, ...series.flatMap((item) => item.values.map((point) => point.value)));
  const width = 900;
  const height = 260;
  const pad = { top: 24, right: 24, bottom: 42, left: 38 };
  const chartWidth = width - pad.left - pad.right;
  const chartHeight = height - pad.top - pad.bottom;
  const xFor = (index) =>
    pad.left + (daily.length === 1 ? chartWidth / 2 : (index / (daily.length - 1)) * chartWidth);
  const yFor = (value) => pad.top + chartHeight - (value / maxValue) * chartHeight;

  const lines = series
    .map((item, seriesIndex) => {
      const color = trendColors[seriesIndex % trendColors.length];
      const points = item.values.map((point, index) => ({
        x: xFor(index),
        y: yFor(point.value),
        value: point.value,
        date: point.date,
      }));
      const path = smoothPath(points);
      const circles = item.values
        .map((point, index) => {
          const x = xFor(index);
          const y = yFor(point.value);
          return `
            <circle class="trend-dot" cx="${x}" cy="${y}" r="5" fill="${color}"></circle>
          `;
        })
        .join("");
      return `<path d="${path}" fill="none" stroke="${color}" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"></path>${circles}`;
    })
    .join("");
  const hoverZones = renderHoverZones(
    daily.map((item, index) => ({ date: item.date, x: xFor(index), y: pad.top })),
    height,
    pad,
    (point, index) => {
      const lines = series.map((item) => `${item.category}: ${item.values[index]?.value ?? 0}`);
      return `${point.date}\n${lines.join("\n")}`;
    },
  );

  const labels = daily
    .map((item, index) => {
      const x = xFor(index);
      return `<text class="trend-label" x="${x}" y="${height - 10}" text-anchor="middle">${formatDateLabel(item.date)}</text>`;
    })
    .join("");

  const legend = series
    .map((item, index) => {
      const color = trendColors[index % trendColors.length];
      return `<span class="legend-item"><i class="legend-dot" style="background:${color}"></i>${escapeHtml(item.category)}</span>`;
    })
    .join("");
  const picker = renderTrendPicker(kind, categories);

  container.innerHTML = `
    ${picker}
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="分类涨停趋势">
      ${renderGridLines(width, height, pad)}
      <line class="trend-axis" x1="${pad.left}" y1="${pad.top + chartHeight}" x2="${width - pad.right}" y2="${pad.top + chartHeight}"></line>
      ${lines}
      ${hoverZones}
      ${labels}
    </svg>
    <div class="trend-legend">${legend}</div>
  `;
}

function renderTrendPicker(kind, categories) {
  const selected = state.selectedTrendCategories[kind];
  const chips = categories
    .slice(0, 18)
    .map(([value, count]) => {
      const active = selected.has(value);
      return `
        <button class="trend-picker-chip${active ? " active" : ""}" type="button" data-trend-kind="${kind}" data-trend-category="${escapeHtml(value)}">
          <span>${escapeHtml(value)}</span>
          <strong>${count}</strong>
        </button>
      `;
    })
    .join("");
  const hint = selected.size ? `已选 ${selected.size} 项` : "默认 Top 5";
  return `
    <div class="trend-picker">
      <div class="trend-picker-head">
        <span>${hint}</span>
        <button type="button" data-trend-clear="${kind}">恢复默认</button>
      </div>
      <div class="trend-picker-chips">${chips}</div>
    </div>
  `;
}

function renderGridLines(width, height, pad) {
  const chartHeight = height - pad.top - pad.bottom;
  return [0, 0.5, 1]
    .map((ratio) => {
      const y = pad.top + chartHeight * ratio;
      return `<line class="trend-gridline" x1="${pad.left}" y1="${y}" x2="${width - pad.right}" y2="${y}"></line>`;
    })
    .join("");
}

function renderHoverZones(points, height, pad, tooltipFor) {
  if (!points.length) return "";
  return points
    .map((point, index) => {
      const prevX = index === 0 ? pad.left : (points[index - 1].x + point.x) / 2;
      const nextX = index === points.length - 1 ? 900 - pad.right : (point.x + points[index + 1].x) / 2;
      const x = Math.min(prevX, nextX);
      const width = Math.max(20, Math.abs(nextX - prevX));
      return `
        <rect class="trend-hover-zone" x="${x}" y="${pad.top}" width="${width}" height="${height - pad.top - pad.bottom}" data-tooltip="${escapeHtml(tooltipFor(point, index))}"></rect>
        <line class="trend-guide" x1="${point.x}" y1="${pad.top}" x2="${point.x}" y2="${height - pad.bottom}"></line>
      `;
    })
    .join("");
}

function smoothPath(points) {
  if (!points.length) return "";
  if (points.length === 1) return `M ${points[0].x} ${points[0].y}`;

  let path = `M ${points[0].x} ${points[0].y}`;
  for (let index = 0; index < points.length - 1; index += 1) {
    const current = points[index];
    const next = points[index + 1];
    const midX = (current.x + next.x) / 2;
    path += ` C ${midX} ${current.y}, ${midX} ${next.y}, ${next.x} ${next.y}`;
  }
  return path;
}

function formatDateLabel(date) {
  return date.slice(5);
}

function rowMatchesFilters(row) {
  if (state.activeFilters.industry) {
    if ((row[COL.industry1] || "").trim() !== state.activeFilters.industry) return false;
  }

  if (state.activeFilters.theme) {
    if (!splitThemes(row[COL.theme] || "").includes(state.activeFilters.theme)) return false;
  }

  return true;
}

function compareRows(a, b, key, direction) {
  const multiplier = direction === "asc" ? 1 : -1;
  const left = a[key] || "";
  const right = b[key] || "";

  if (numericColumns.has(key)) {
    const leftNumber = Number(left);
    const rightNumber = Number(right);
    if (Number.isFinite(leftNumber) && Number.isFinite(rightNumber)) {
      return (leftNumber - rightNumber) * multiplier;
    }
  }

  return String(left).localeCompare(String(right), "zh-Hans-CN", { numeric: true }) * multiplier;
}

function visibleColumns() {
  return state.columns.filter((column) => !hiddenTableColumns.has(column));
}

function renderTable() {
  const columns = visibleColumns();
  els.tableHead.innerHTML = `
    <tr>
      ${columns
        .map((column) => {
          const active = state.sortKey === column;
          const arrow = active ? (state.sortDir === "asc" ? " ↑" : " ↓") : "";
          return `<th><button type="button" data-sort="${escapeHtml(column)}">${escapeHtml(column)}${arrow}</button></th>`;
        })
        .join("")}
    </tr>
  `;

  if (!state.filteredRows.length) {
    els.tableBody.innerHTML = `<tr><td colspan="${columns.length || 1}">没有符合条件的记录</td></tr>`;
    return;
  }

  els.tableBody.innerHTML = state.filteredRows.map((row) => renderRow(row, columns)).join("");
}

function renderRow(row, columns) {
  const note = row[COL.note] || "";

  return `
    <tr class="stock-row">
      ${columns.map((column) => renderCell(column, row[column] || "")).join("")}
    </tr>
    <tr class="note-row">
      <td colspan="${columns.length}">
        <details class="stock-note">
          <summary><span>韭研解读</span></summary>
          <div>${note ? escapeHtml(note) : "暂无解读"}</div>
        </details>
      </td>
    </tr>
  `;
}

function renderCell(column, value) {
  const displayValue = formatCell(column, value);
  const text = escapeHtml(displayValue);
  const classes = [];

  if (numericColumns.has(column)) classes.push("numeric");
  if (dangerColumns.has(column)) classes.push("danger");
  if (column === COL.code) classes.push("stock-code");

  if (tagColumns.has(column) && value) {
    return `<td><span class="tag">${text}</span></td>`;
  }

  return `<td class="${classes.join(" ")}">${text}</td>`;
}

function formatCell(column, value) {
  if (!value) return "";
  if (column === COL.change || column === COL.turnover) return formatPercent(value);
  if (column === COL.sealAmount) return formatHundredMillion(value);
  if (column === COL.marketValue) return formatMoney(value);
  if (timeColumns.has(column)) return formatTime(value);
  return value;
}

function formatPercent(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return value;
  return `${number.toFixed(2)}%`;
}

function formatMoney(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return value;
  const abs = Math.abs(number);
  if (abs >= 100000000) return `${(number / 100000000).toFixed(2)}亿`;
  if (abs >= 10000) return `${(number / 10000).toFixed(2)}万`;
  return `${number.toFixed(2)}元`;
}

function formatHundredMillion(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return value;
  return `${(number / 100000000).toFixed(2)}亿`;
}

function formatTime(value) {
  const digits = String(value).replace(/\D/g, "").padStart(6, "0");
  if (digits.length < 6) return value;
  return `${digits.slice(0, 2)}:${digits.slice(2, 4)}:${digits.slice(4, 6)}`;
}

function renderMetrics() {
  els.totalCount.textContent = state.rows.length;
  els.visibleCount.textContent = state.filteredRows.length;
  els.maxChain.textContent = maxNumber(state.filteredRows, COL.chain) || "-";
  renderStatGroup(els.industryStats, "industry", valueCounts(state.rows, COL.industry1));
  renderStatGroup(els.themeStats, "theme", themeCounts(state.rows));
}

function renderThemeDistribution() {
  const distributions = buildThemeDistributions(state.filteredRows);
  if (!distributions.length) {
    els.themeDistribution.innerHTML = `<div class="empty-distribution">暂无可视化数据</div>`;
    return;
  }

  els.themeDistribution.innerHTML = distributions
    .map(
      (item) => `
        <article class="distribution-card">
          <div class="distribution-title">
            <strong>${escapeHtml(item.theme)}</strong>
            <span>${item.total} 只</span>
          </div>
          ${renderDistributionBlock("申万一级", item.industry)}
          ${renderDistributionBlock("流通市值", item.marketValue)}
        </article>
      `,
    )
    .join("");
}

function buildThemeDistributions(rows) {
  const themeMap = new Map();

  rows.forEach((row) => {
    const themes = splitThemes(row[COL.theme] || "");
    themes.forEach((theme) => {
      if (!themeMap.has(theme)) {
        themeMap.set(theme, {
          theme,
          total: 0,
          industry: new Map(),
          marketValue: new Map(),
        });
      }

      const item = themeMap.get(theme);
      item.total += 1;
      incrementMap(item.industry, (row[COL.industry1] || "未分类").trim() || "未分类");
      incrementMap(item.marketValue, marketValueBucket(row[COL.marketValue]));
    });
  });

  return [...themeMap.values()]
    .map((item) => ({
      ...item,
      industry: sortedDistribution(item.industry),
      marketValue: sortedDistribution(item.marketValue, marketBucketOrder),
    }))
    .sort((a, b) => b.total - a.total || a.theme.localeCompare(b.theme, "zh-Hans-CN"));
}

function renderDistributionBlock(title, distribution) {
  const total = distribution.reduce((sum, item) => sum + item.count, 0);
  const maxCount = Math.max(...distribution.map((d) => d.count), 1);
  const bars = distribution
    .map((item, index) => {
      const widthPct = (item.count / maxCount) * 100;
      return `
        <div class="distribution-bar-row">
          <span class="distribution-bar-label" title="${escapeHtml(item.label)}">${escapeHtml(item.label)}</span>
          <div class="distribution-bar-track">
            <div class="distribution-bar-fill" style="width:${widthPct}%; background:${distributionColor(index)}"></div>
          </div>
          <span class="distribution-bar-value">${item.count}</span>
        </div>
      `;
    })
    .join("");

  return `
    <div class="distribution-block">
      <div class="distribution-label">${title}</div>
      <div class="distribution-bars">${bars}</div>
    </div>
  `;
}

function incrementMap(map, key) {
  map.set(key, (map.get(key) || 0) + 1);
}

function sortedDistribution(map, order = null) {
  const items = [...map.entries()].map(([label, count]) => ({ label, count }));
  if (!order) {
    return items.sort((a, b) => b.count - a.count || a.label.localeCompare(b.label, "zh-Hans-CN"));
  }
  return items.sort((a, b) => order.indexOf(a.label) - order.indexOf(b.label));
}

const marketBucketOrder = ["50亿以下", "50-100亿", "100-300亿", "300-1000亿", "1000亿以上", "未知"];

function marketValueBucket(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "未知";
  const yi = number / 100000000;
  if (yi < 50) return "50亿以下";
  if (yi < 100) return "50-100亿";
  if (yi < 300) return "100-300亿";
  if (yi < 1000) return "300-1000亿";
  return "1000亿以上";
}

function distributionColor(index) {
  return trendColors[index % trendColors.length];
}

function renderStatGroup(container, kind, stats) {
  if (!stats.length) {
    container.innerHTML = `<span class="empty-theme">暂无统计</span>`;
    return;
  }

  container.innerHTML = stats
    .slice(0, 18)
    .map(([value, count]) => {
      const active = state.activeFilters[kind] === value;
      return `
        <button class="stat-chip${active ? " active" : ""}" type="button" data-filter-kind="${kind}" data-filter-value="${escapeHtml(value)}">
          <span>${escapeHtml(value)}</span>
          <strong>${count}</strong>
        </button>
      `;
    })
    .join("");
}

function renderActiveFilter() {
  const parts = [];
  if (state.activeFilters.industry) parts.push(`申万一级: ${state.activeFilters.industry}`);
  if (state.activeFilters.theme) parts.push(`韭研题材: ${state.activeFilters.theme}`);

  if (!parts.length) {
    els.activeFilterText.textContent = "全部";
    els.clearFilterButton.hidden = true;
    return;
  }

  els.activeFilterText.textContent = parts.join(" + ");
  els.clearFilterButton.hidden = false;
}

function maxNumber(rows, column) {
  const values = rows.map((row) => Number(row[column])).filter(Number.isFinite);
  return values.length ? Math.max(...values) : "";
}

function valueCounts(rows, column) {
  const counts = new Map();
  for (const row of rows) {
    const value = (row[column] || "").trim();
    if (value) counts.set(value, (counts.get(value) || 0) + 1);
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "zh-Hans-CN"));
}

function themeCounts(rows) {
  const counts = new Map();
  for (const row of rows) {
    for (const theme of splitThemes(row[COL.theme] || "")) {
      counts.set(theme, (counts.get(theme) || 0) + 1);
    }
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "zh-Hans-CN"));
}

function splitSingleValue(value) {
  const text = String(value).trim();
  return text ? [text] : [];
}

function splitThemes(value) {
  return String(value)
    .split(/[+、，,；;｜|/]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function handleStatClick(event) {
  const button = event.target.closest("[data-filter-kind]");
  if (!button) return;
  const nextFilter = {
    kind: button.dataset.filterKind,
    value: button.dataset.filterValue,
  };

  if (state.activeFilters[nextFilter.kind] === nextFilter.value) {
    state.activeFilters[nextFilter.kind] = null;
  } else {
    state.activeFilters[nextFilter.kind] = nextFilter.value;
  }
  applyView();
}

function handleRangeClick(event) {
  const button = event.target.closest("[data-range]");
  if (!button) return;

  state.trendRange = button.dataset.range;
  document.querySelectorAll("[data-range]").forEach((item) => {
    item.classList.toggle("active", item.dataset.range === state.trendRange);
  });
  els.customRange.hidden = state.trendRange !== "custom";
  renderTrends();
}

function handleCustomRangeChange() {
  state.customStart = els.trendStart.value || state.customStart;
  state.customEnd = els.trendEnd.value || state.customEnd;
  if (state.customStart > state.customEnd) {
    const oldStart = state.customStart;
    state.customStart = state.customEnd;
    state.customEnd = oldStart;
    els.trendStart.value = state.customStart;
    els.trendEnd.value = state.customEnd;
  }
  renderTrends();
}

function handleTrendCategoryClick(event) {
  const clearButton = event.target.closest("[data-trend-clear]");
  if (clearButton) {
    state.selectedTrendCategories[clearButton.dataset.trendClear].clear();
    renderTrends();
    return;
  }

  const button = event.target.closest("[data-trend-category]");
  if (!button) return;
  const kind = button.dataset.trendKind;
  const category = button.dataset.trendCategory;
  const selected = state.selectedTrendCategories[kind];
  if (selected.has(category)) {
    selected.delete(category);
  } else {
    selected.add(category);
  }
  renderTrends();
}

function tooltipEl() {
  let tooltip = document.querySelector(".chart-tooltip");
  if (!tooltip) {
    tooltip = document.createElement("div");
    tooltip.className = "chart-tooltip";
    document.body.appendChild(tooltip);
  }
  return tooltip;
}

function handleTrendPointerMove(event) {
  const target = event.target.closest("[data-tooltip]");
  const tooltip = tooltipEl();
  if (!target) {
    tooltip.classList.remove("show");
    return;
  }

  tooltip.textContent = target.dataset.tooltip;
  tooltip.style.left = `${event.clientX + 12}px`;
  tooltip.style.top = `${event.clientY + 12}px`;
  tooltip.classList.add("show");
}

function hideTrendTooltip() {
  tooltipEl().classList.remove("show");
}

els.dateSelect.addEventListener("change", (event) => loadDate(event.target.value));
els.rangeButtons.addEventListener("click", handleRangeClick);
els.trendStart.addEventListener("change", handleCustomRangeChange);
els.trendEnd.addEventListener("change", handleCustomRangeChange);
els.industryTrendChart.addEventListener("click", handleTrendCategoryClick);
els.themeTrendChart.addEventListener("click", handleTrendCategoryClick);
document.addEventListener("pointermove", handleTrendPointerMove);
document.addEventListener("pointerleave", hideTrendTooltip);
els.industryStats.addEventListener("click", handleStatClick);
els.themeStats.addEventListener("click", handleStatClick);

els.clearFilterButton.addEventListener("click", () => {
  state.activeFilters = { industry: null, theme: null };
  applyView();
});

els.tableHead.addEventListener("click", (event) => {
  const column = event.target.dataset.sort;
  if (!column) return;
  if (state.sortKey === column) {
    state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
  } else {
    state.sortKey = column;
    state.sortDir = numericColumns.has(column) ? "desc" : "asc";
  }
  applyView();
});

init();
