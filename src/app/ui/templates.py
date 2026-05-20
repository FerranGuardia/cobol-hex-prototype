"""HTML/CSS/JS for the observatory dashboard. One page, no build step.

Editorial layout — single column, Claude warm palette, serif headlines,
sans body, lots of whitespace. The page polls /api/state every 2.5s and
re-renders.
"""
from __future__ import annotations

INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pipeline Observatory · COBOL hex prototype</title>
<style>
  :root {
    --bg:        #FAFAF7;
    --bg-sub:   #F2EFE6;
    --rule:      #D6D2C5;
    --text:      #1B1B1A;
    --text-soft: #6B6862;
    --text-faint:#9B968A;
    --accent:    #C15F3C;   /* warm coral — Claude print, not startup neon */
    --ok:        #5B7553;
    --warn:      #B07A3E;
    --error:     #A04A3E;
    --serif: 'Charter','Iowan Old Style','Georgia','Times New Roman',serif;
    --sans:  -apple-system,BlinkMacSystemFont,'Inter','Helvetica Neue',Arial,sans-serif;
    --mono:  'SF Mono','Menlo','Consolas',monospace;
  }
  * { box-sizing: border-box; }
  html, body { background: var(--bg); color: var(--text); }
  body {
    margin: 0;
    font-family: var(--sans);
    font-size: 15px;
    line-height: 1.55;
    -webkit-font-smoothing: antialiased;
  }
  .page {
    max-width: 960px;
    margin: 0 auto;
    padding: 56px 40px 96px;
  }
  /* Masthead */
  header.masthead {
    border-bottom: 1px solid var(--rule);
    padding-bottom: 18px;
    margin-bottom: 36px;
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 24px;
  }
  .masthead .title {
    font-family: var(--serif);
    font-size: 28px;
    font-weight: 600;
    letter-spacing: -0.01em;
    color: var(--text);
  }
  .masthead .subtitle {
    font-family: var(--sans);
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.14em;
    color: var(--text-soft);
  }
  .masthead .clock {
    font-family: var(--mono);
    font-size: 13px;
    color: var(--text-soft);
  }
  /* Section headers — small caps above a rule */
  section { margin-bottom: 48px; }
  section h2 {
    font-family: var(--sans);
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.18em;
    font-weight: 600;
    color: var(--text-soft);
    margin: 0 0 14px;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--rule);
  }
  /* Run entry */
  .run {
    padding: 18px 0;
    border-bottom: 1px solid var(--rule);
  }
  .run:last-child { border-bottom: none; }
  .run-head {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 24px;
    margin-bottom: 4px;
  }
  .run-title {
    font-family: var(--serif);
    font-size: 19px;
    font-weight: 600;
    color: var(--text);
  }
  .run-title .slice {
    font-weight: 700;
  }
  .run-title .label {
    font-weight: 400;
    color: var(--text-soft);
    margin-left: 8px;
  }
  .run-meta {
    font-family: var(--mono);
    font-size: 12px;
    color: var(--text-soft);
    white-space: nowrap;
  }
  .status-dot {
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    margin-right: 6px;
    vertical-align: middle;
  }
  .status-running { background: var(--accent); animation: pulse 1.6s ease-in-out infinite; }
  .status-ok      { background: var(--ok); }
  .status-issues  { background: var(--warn); }
  .status-blocked { background: var(--error); }
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50%      { opacity: 0.35; }
  }
  .run-summary {
    font-family: var(--serif);
    font-style: italic;
    font-size: 14px;
    color: var(--text-soft);
    margin-bottom: 14px;
  }
  /* Phase grid */
  .phases {
    list-style: none;
    margin: 10px 0 4px;
    padding: 0;
    font-family: var(--mono);
    font-size: 13px;
  }
  .phases li {
    display: grid;
    grid-template-columns: 28px 140px 1fr 100px;
    gap: 12px;
    padding: 3px 0;
    color: var(--text);
  }
  .phases li.pending  { color: var(--text-faint); }
  .phases li.running  { color: var(--text); }
  .phases li.done     { color: var(--text); }
  .ph-mark { text-align: center; }
  .ph-mark.done    { color: var(--ok); }
  .ph-mark.running { color: var(--accent); font-weight: bold; }
  .ph-mark.pending { color: var(--text-faint); }
  .ph-label  { color: inherit; }
  .ph-detail { color: var(--text-soft); }
  .ph-time   { color: var(--text-soft); text-align: right; }
  .pending .ph-detail, .pending .ph-time { color: var(--text-faint); }

  /* Issues block */
  .issues {
    list-style: none;
    margin: 8px 0 0;
    padding: 0;
  }
  .issues li {
    padding: 10px 0;
    border-bottom: 1px dashed var(--rule);
    font-size: 14px;
  }
  .issues li:last-child { border-bottom: none; }
  .issue-head {
    display: flex;
    gap: 12px;
    align-items: baseline;
  }
  .issue-tag {
    font-family: var(--mono);
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    padding: 2px 6px;
    border-radius: 2px;
    background: var(--bg-sub);
    color: var(--text);
  }
  .issue-tag.error  { background: #F1DBD3; color: var(--error); }
  .issue-tag.warn   { background: #EFE2C7; color: var(--warn); }
  .issue-tag.info   { background: #DDE5DA; color: var(--ok); }
  .issue-meta {
    font-family: var(--mono);
    font-size: 11px;
    color: var(--text-soft);
  }
  .issue-msg {
    font-family: var(--serif);
    margin-top: 2px;
    color: var(--text);
  }

  /* Empty states */
  .empty {
    font-family: var(--serif);
    font-style: italic;
    color: var(--text-faint);
    padding: 14px 0;
  }

  /* History footer */
  .footer {
    margin-top: 64px;
    padding-top: 14px;
    border-top: 1px solid var(--rule);
    font-family: var(--mono);
    font-size: 11px;
    color: var(--text-faint);
    display: flex;
    justify-content: space-between;
  }
  .footer a { color: var(--text-soft); text-decoration: none; border-bottom: 1px dotted var(--rule); }
  .footer a:hover { color: var(--accent); }

  /* Drilldown link on each run */
  .run-head a {
    color: var(--text-soft);
    text-decoration: none;
    font-family: var(--mono);
    font-size: 11px;
    border-bottom: 1px dotted var(--rule);
  }
  .run-head a:hover { color: var(--accent); }
</style>
</head>
<body>
<div class="page">
  <header class="masthead">
    <div>
      <div class="title">Pipeline Observatory</div>
      <div class="subtitle">COBOL → Hexagonal Java · Iria-aware F3</div>
    </div>
    <div class="clock" id="clock">—</div>
  </header>

  <section id="live-section">
    <h2>In flight</h2>
    <div id="live"></div>
  </section>

  <section id="issues-section">
    <h2>Issues surfaced</h2>
    <ul class="issues" id="issues"></ul>
  </section>

  <section id="recent-section">
    <h2>Recent runs</h2>
    <div id="recent"></div>
  </section>

  <div class="footer">
    <div id="root-path">—</div>
    <div>polling every 2.5s · <a href="/api/state" target="_blank">/api/state</a></div>
  </div>
</div>

<script>
const STATUS_GLYPH = { done: '✓', running: '◐', pending: '·' };
const STATUS_LABEL = { ok: 'all pass', running: 'running', issues: 'issues', blocked: 'blocked' };

function fmtDuration(seconds) {
  if (seconds == null || isNaN(seconds)) return '—';
  seconds = Math.max(0, Math.round(seconds));
  if (seconds < 60) return seconds + 's';
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  if (m < 60) return s ? `${m}m${s}s` : `${m}m`;
  const h = Math.floor(m / 60);
  return `${h}h${m % 60}m`;
}

function fmtTimeOfDay(epoch) {
  if (!epoch) return '—';
  const d = new Date(epoch * 1000);
  return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function fmtClock() {
  const d = new Date();
  return d.toLocaleString('en-GB', {
    weekday: 'short', day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  });
}

function el(tag, attrs={}, ...children) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') e.className = v;
    else if (k === 'html') e.innerHTML = v;
    else e.setAttribute(k, v);
  }
  for (const c of children) {
    if (c == null) continue;
    e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
  }
  return e;
}

function renderPhase(p, runStartedAt) {
  const mark = el('span', { class: 'ph-mark ' + p.status }, STATUS_GLYPH[p.status] || '·');
  const label = el('span', { class: 'ph-label' }, p.label);
  const detail = el('span', { class: 'ph-detail' }, p.detail || '');
  let timeText = '';
  if (p.mtime && runStartedAt) {
    const dt = p.mtime - runStartedAt;
    timeText = fmtDuration(dt);
  }
  const time = el('span', { class: 'ph-time' }, timeText);
  return el('li', { class: p.status }, mark, label, detail, time);
}

function renderRun(run) {
  const dot = el('span', { class: 'status-dot status-' + run.overall_status });
  const sliceSpan = el('span', { class: 'slice' }, run.slice || run.run_id);
  const labelSpan = el('span', { class: 'label' },
    run.kind === 'smoke' ? '· smoke' : `· ${run.run_id}`);
  const titleDiv = el('div', { class: 'run-title' }, dot, sliceSpan, labelSpan);

  const metaParts = [];
  if (run.is_live) {
    metaParts.push(`${fmtDuration(run.elapsed_seconds)} elapsed`);
    if (run.estimated_remaining_seconds != null) {
      metaParts.push(`est. ${fmtDuration(run.estimated_remaining_seconds)} left`);
    }
  } else {
    metaParts.push(fmtTimeOfDay(run.last_mtime));
    metaParts.push(fmtDuration(run.elapsed_seconds));
  }
  const metaDiv = el('div', { class: 'run-meta' }, metaParts.join(' · '));

  const head = el('div', { class: 'run-head' }, titleDiv, metaDiv);
  const summary = el('div', { class: 'run-summary' }, run.summary_line);

  const phaseList = el('ul', { class: 'phases' });
  for (const ph of run.phases) {
    phaseList.appendChild(renderPhase(ph, run.started_at));
  }

  const container = el('div', { class: 'run' }, head, summary, phaseList);
  return container;
}

function renderIssues(issues) {
  const list = document.getElementById('issues');
  list.innerHTML = '';
  if (!issues.length) {
    list.appendChild(el('div', { class: 'empty' }, 'No open issues across recent runs.'));
    return;
  }
  for (const i of issues) {
    const tag = el('span', { class: 'issue-tag ' + (i.severity || 'info') }, i.tag);
    const meta = el('span', { class: 'issue-meta' },
      `${i.slice || ''} · ${i.run_id}`);
    const head = el('div', { class: 'issue-head' }, tag, meta);
    const msg = el('div', { class: 'issue-msg' }, i.message);
    list.appendChild(el('li', {}, head, msg));
  }
}

async function refresh() {
  try {
    const r = await fetch('/api/state', { cache: 'no-store' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const state = await r.json();

    document.getElementById('root-path').textContent = state.artifacts_root;
    document.getElementById('clock').textContent = fmtClock();

    const liveEl = document.getElementById('live');
    liveEl.innerHTML = '';
    if (!state.live.length) {
      liveEl.appendChild(el('div', { class: 'empty' }, 'No runs in flight.'));
    } else {
      for (const run of state.live) liveEl.appendChild(renderRun(run));
    }

    const recentEl = document.getElementById('recent');
    recentEl.innerHTML = '';
    if (!state.recent.length) {
      recentEl.appendChild(el('div', { class: 'empty' }, 'No recent runs yet.'));
    } else {
      for (const run of state.recent) recentEl.appendChild(renderRun(run));
    }

    renderIssues(state.open_issues);
  } catch (e) {
    console.warn('refresh failed:', e);
  }
}

refresh();
setInterval(refresh, 2500);
setInterval(() => { document.getElementById('clock').textContent = fmtClock(); }, 1000);
</script>
</body>
</html>
"""
