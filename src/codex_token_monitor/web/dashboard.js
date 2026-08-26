const csrf = document.querySelector('meta[name="csrf-token"]').content;
const fmt = new Intl.NumberFormat('ko-KR');
const formatTokens = window.CodexTokenMonitorFormat.formatTokens;
const $ = id => document.getElementById(id);
const TREND_COLORS = ['#2563eb', '#7c3aed', '#dc2626', '#0891b2', '#c026d3', '#64748b'];
const MODEL_COLORS = {sol: '#f97316', terra: '#16a34a', luna: '#ca8a04'};
let paused = false;
let renderedEventCount = -1;
let activeGranularity = 'day';
let trendData = {buckets: [], hoverIndex: -1};
const hiddenTrendSeries = new Set();

function localIso(d) {
  const z = new Date(d.getTime() - d.getTimezoneOffset() * 60000);
  return z.toISOString().slice(0, 10);
}
function setRange(kind) {
  const now = new Date();
  let start = new Date(now), end = new Date(now);
  const range = {
    today: {months: 0, granularity: '30m'},
    '7d': {days: 6, granularity: 'day'},
    month: {months: 1, granularity: 'day'},
    quarter: {months: 3, granularity: '10d'},
    half: {months: 6, granularity: 'month'},
    year: {months: 12, granularity: 'month'},
  }[kind];
  if (range.days) start.setDate(now.getDate() - range.days);
  if (range.months) start = new Date(now.getFullYear(), now.getMonth() - range.months + 1, 1);
  activeGranularity = range.granularity;
  document.querySelectorAll('[data-range]').forEach(button => {
    const selected = button.dataset.range === kind;
    button.classList.toggle('selected', selected);
    button.setAttribute('aria-pressed', String(selected));
  });
  $('start-date').value = localIso(start);
  $('end-date').value = localIso(end);
  loadStats();
}
function clearRangeSelection() {
  activeGranularity = 'day';
  document.querySelectorAll('[data-range]').forEach(button => {
    button.classList.remove('selected');
    button.setAttribute('aria-pressed', 'false');
  });
}
async function api(path, options = {}) {
  options.headers = {...(options.headers || {}), 'X-CSRF-Token': csrf};
  const r = await fetch(path, options);
  const data = await r.json();
  if (!r.ok) throw new Error(data.error || '요청 실패');
  return data;
}

function trendSeries(trend) {
  const buckets = trend.buckets || [];
  const models = [...new Set(buckets.flatMap(bucket => Object.keys(bucket.models || {})))].sort((a, b) => a.localeCompare(b));
  const series = models.map((model, index) => ({
    name: model,
    color: Object.entries(MODEL_COLORS).find(([name]) => model.toLowerCase().includes(name))?.[1] || TREND_COLORS[index % TREND_COLORS.length],
    values: buckets.map(bucket => Number(bucket.models[model]) || 0),
  }));
  series.push({
    name: '총합',
    color: '#6b7280',
    total: true,
    values: buckets.map(bucket => Number(bucket.total_tokens) || 0),
  });
  return {buckets, series};
}

function renderTrendLegend(series) {
  const legend = $('trend-legend');
  legend.replaceChildren();
  series.forEach(item => {
    const hidden = hiddenTrendSeries.has(item.name);
    const entry = document.createElement('button');
    entry.type = 'button';
    entry.className = `trend-legend-item${item.total ? ' total' : ''}${hidden ? ' disabled' : ''}`;
    entry.setAttribute('aria-pressed', String(!hidden));
    entry.title = `${item.name} ${hidden ? '켜기' : '끄기'}`;
    const swatch = document.createElement('i');
    swatch.style.backgroundColor = item.color;
    entry.append(swatch, document.createTextNode(item.name));
    entry.onclick = () => {
      hidden ? hiddenTrendSeries.delete(item.name) : hiddenTrendSeries.add(item.name);
      renderTrend();
    };
    legend.append(entry);
  });
}

function renderTrend() {
  const c = $('trend'), ctx = c.getContext('2d'), ratio = devicePixelRatio || 1;
  const w = c.clientWidth || 900, h = 270;
  c.width = w * ratio;
  c.height = h * ratio;
  ctx.scale(ratio, ratio);
  ctx.clearRect(0, 0, w, h);

  const {buckets, series} = trendSeries(trendData);
  renderTrendLegend(series);
  const visibleSeries = series.filter(item => !hiddenTrendSeries.has(item.name));
  const plot = {left: 48, right: w - 18, top: 12, bottom: h - 31};
  const plotWidth = Math.max(1, plot.right - plot.left);
  const plotHeight = plot.bottom - plot.top;
  const max = Math.max(1, ...visibleSeries.flatMap(item => item.values));
  const xAt = index => plot.left + plotWidth * (buckets.length === 1 ? 0.5 : index / (buckets.length - 1));
  const yAt = value => plot.bottom - plotHeight * value / max;

  ctx.font = '11px Segoe UI';
  ctx.textBaseline = 'middle';
  for (let i = 0; i < 4; i++) {
    const y = plot.top + plotHeight * i / 3;
    ctx.strokeStyle = '#d9e2ec';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(plot.left, y);
    ctx.lineTo(plot.right, y);
    ctx.stroke();
    ctx.fillStyle = '#617080';
    ctx.textAlign = 'right';
    ctx.fillText(formatTokens(Math.round(max * (3 - i) / 3)), plot.left - 7, y);
  }
  if (!buckets.length) return;

  visibleSeries.forEach(item => {
    ctx.strokeStyle = item.color;
    ctx.lineWidth = item.total ? 3.5 : 2;
    ctx.setLineDash(item.total ? [] : [5, 3]);
    ctx.beginPath();
    item.values.forEach((value, index) => {
      const x = xAt(index), y = yAt(value);
      index ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    });
    ctx.stroke();
    ctx.setLineDash([]);
  });

  ctx.fillStyle = '#5d6b7a';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'alphabetic';
  const labelStep = Math.max(1, Math.ceil(buckets.length / 8));
  buckets.forEach((bucket, index) => {
    if (index % labelStep === 0 || index === buckets.length - 1) ctx.fillText(bucket.label, xAt(index), h - 8);
  });

  if (trendData.hoverIndex >= 0 && trendData.hoverIndex < buckets.length) {
    const index = trendData.hoverIndex, x = xAt(index);
    ctx.strokeStyle = '#8a99a8';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x, plot.top);
    ctx.lineTo(x, plot.bottom);
    ctx.stroke();
    visibleSeries.forEach(item => {
      ctx.fillStyle = item.color;
      ctx.beginPath();
      ctx.arc(x, yAt(item.values[index]), item.total ? 4.5 : 3.5, 0, Math.PI * 2);
      ctx.fill();
    });
  }
}

function showTrendTooltip(index, pointerX) {
  const tooltip = $('trend-tooltip');
  const {buckets, series} = trendSeries(trendData);
  if (index < 0 || index >= buckets.length) {
    tooltip.hidden = true;
    return;
  }
  tooltip.replaceChildren();
  const title = document.createElement('strong');
  title.textContent = buckets[index].key;
  tooltip.append(title);
  [...series].filter(item => !hiddenTrendSeries.has(item.name)).reverse().forEach(item => {
    const row = document.createElement('span');
    row.className = item.total ? 'tooltip-row total' : 'tooltip-row';
    const label = document.createElement('span');
    const swatch = document.createElement('i');
    swatch.style.backgroundColor = item.color;
    label.append(swatch, document.createTextNode(item.name));
    const value = document.createElement('b');
    value.textContent = `${fmt.format(item.values[index])} 토큰`;
    row.append(label, value);
    tooltip.append(row);
  });
  tooltip.hidden = false;
  const wrapperWidth = $('trend-chart').clientWidth;
  const tooltipWidth = tooltip.offsetWidth;
  tooltip.style.left = `${Math.max(8, Math.min(pointerX + 12, wrapperWidth - tooltipWidth - 8))}px`;
  tooltip.style.top = '12px';
}

function drawTrend(trend) {
  trendData = {...trend, hoverIndex: -1};
  $('trend-tooltip').hidden = true;
  renderTrend();
}

function handleTrendPointer(event) {
  const c = $('trend'), rect = c.getBoundingClientRect();
  const buckets = trendData.buckets || [];
  if (!buckets.length) return;
  const left = 48, right = rect.width - 18;
  const relativeX = Math.max(left, Math.min(event.clientX - rect.left, right));
  const index = buckets.length === 1 ? 0 : Math.round((relativeX - left) / (right - left) * (buckets.length - 1));
  if (index !== trendData.hoverIndex) {
    trendData.hoverIndex = index;
    renderTrend();
  }
  showTrendTooltip(index, relativeX);
}

async function loadStats() {
  const start = $('start-date').value, end = $('end-date').value;
  if (!start || !end) return;
  const d = await api(`/api/stats?start=${start}&end=${end}&granularity=${activeGranularity}`);
  $('m-total').textContent = formatTokens(d.overall.total_tokens);
  $('m-input').textContent = formatTokens(d.overall.input_tokens);
  $('m-output').textContent = formatTokens(d.overall.output_tokens);
  $('m-cache').textContent = formatTokens(d.overall.cached_input_tokens);
  $('m-reasoning').textContent = formatTokens(d.overall.reasoning_output_tokens);
  $('usage-body').innerHTML = d.rows.map(r => `<tr><td>${r.date}</td><td>${escapeHtml(r.model)}</td><td>${formatTokens(r.input_tokens)}</td><td>${formatTokens(r.output_tokens)}</td><td>${formatTokens(r.cached_input_tokens)}</td><td>${formatTokens(r.reasoning_output_tokens)}</td><td>${formatTokens(r.total_tokens)}</td></tr>`).join('');
  $('row-count').textContent = `${d.rows.length}개 행`;
  $('model-totals').innerHTML = Object.entries(d.by_model).sort((a, b) => b[1].total_tokens - a[1].total_tokens).map(([m, v]) => `<div class="model-row"><span>${escapeHtml(m)}</span><span>${formatTokens(v.total_tokens)}</span></div>`).join('') || '<span>기록 없음</span>';
  $('csv-link').href = `/api/csv?start=${start}&end=${end}`;
  drawTrend(d.trend);
}
function escapeHtml(v) { const e = document.createElement('span'); e.textContent = v; return e.innerHTML; }
async function loadStatus() {
  const s = await api('/api/status');
  paused = s.paused;
  $('watch-state').textContent = s.state;
  $('pause-toggle').textContent = paused ? '감시 재개' : '감시 일시중지';
  const progress = s.backfill_total ? `${s.backfill_current} / ${s.backfill_total}` : (s.backfill_complete ? '완료' : '대기');
  $('sync-details').innerHTML = `<dt>마지막 동기화</dt><dd>${s.last_sync_utc ? new Date(s.last_sync_utc).toLocaleString('ko-KR') : '없음'}</dd><dt>백필 진행</dt><dd>${progress}</dd><dt>처리 이벤트</dt><dd>${fmt.format(s.processed_events)}</dd><dt>이번 실행 신규/중복</dt><dd>${fmt.format(s.inserted_events_session)} / ${fmt.format(s.duplicate_events_session)}</dd><dt>건너뜀</dt><dd>${fmt.format(s.skipped_events_session)}</dd><dt>로그 경로</dt><dd>${s.roots.map(r => `${escapeHtml(r.path)} · ${r.available ? '읽기 가능' : '없음/접근 불가'}`).join('<br>')}</dd>`;
  $('diagnostics').innerHTML = s.diagnostics.map(d => `<div class="diag-row"><span>${escapeHtml(d.label)} <small>(${escapeHtml(d.code)})</small></span><b>${fmt.format(d.count)}</b></div>`).join('') || '진단 항목 없음';
  const shouldRefreshStats=s.processed_events!==renderedEventCount;
  if(shouldRefreshStats)await loadStats();
  renderedEventCount = s.processed_events;
}
async function post(path, payload = {}) { return api(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)}); }
async function loadSettings() {
  const s = await api('/api/settings');
  $('scan-interval').value = s.scan_interval_seconds ?? 15;
  $('autostart').checked = !!s.autostart_enabled;
}

document.querySelectorAll('[data-range]').forEach(b => b.onclick = () => setRange(b.dataset.range));
$('start-date').addEventListener('input', clearRangeSelection);
$('end-date').addEventListener('input', clearRangeSelection);
$('apply-range').onclick = loadStats;
$('rescan').onclick = async () => { await post('/api/rescan'); await loadStatus(); };
$('pause-toggle').onclick = async () => { await post(paused ? '/api/resume' : '/api/pause'); await loadStatus(); };
$('reset-diagnostics').onclick = async () => { await post('/api/diagnostics/reset'); await loadStatus(); };
$('settings-form').onsubmit = async e => {
  e.preventDefault();
  try {
    await post('/api/settings', {scan_interval_seconds: Number($('scan-interval').value), autostart_enabled: $('autostart').checked});
    $('settings-result').textContent = '저장됨';
    await loadStatus();
  } catch (err) { $('settings-result').textContent = err.message; }
};
$('trend').addEventListener('pointermove', handleTrendPointer);
$('trend').addEventListener('pointerleave', () => {
  trendData.hoverIndex = -1;
  $('trend-tooltip').hidden = true;
  renderTrend();
});
setRange('7d');
loadSettings();
loadStatus();
setInterval(loadStatus, 3000);
addEventListener('resize', renderTrend);
if (new URLSearchParams(location.search).get('settings') === '1') setTimeout(() => $('settings').scrollIntoView({behavior: 'smooth'}), 300);
