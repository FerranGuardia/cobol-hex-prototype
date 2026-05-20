"""HTML/CSS/JS for the observatory dashboard.

Editorial layout — single column, Claude warm palette. Latest run is the
front page; older runs collapse to a compact one-line list; issues only
appear when the conveyor actually blocked. No T1/T2/F-codes / run-id
hashes in headline language.

Polls /api/state every 2.5s and re-renders.
"""
from __future__ import annotations

INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pipeline Observatory · COBOL → Hex Java</title>
<style>
  :root {
    --bg:        #FAFAF7;
    --bg-sub:    #F2EFE6;
    --rule:      #D6D2C5;
    --text:      #1B1B1A;
    --text-soft: #6B6862;
    --text-faint:#9B968A;
    --accent:    #C15F3C;
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
    max-width: 880px;
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

  /* Featured (latest or in-flight) — the front page */
  .feature {
    padding: 8px 0 24px;
  }
  .feature .when {
    font-family: var(--mono);
    font-size: 12px;
    color: var(--text-soft);
    text-transform: uppercase;
    letter-spacing: 0.1em;
    margin-bottom: 8px;
  }
  .feature .lede {
    font-family: var(--serif);
    font-size: 26px;
    line-height: 1.25;
    font-weight: 600;
    color: var(--text);
    margin: 0 0 6px;
  }
  .feature .lede .slice { font-weight: 700; }
  .feature .lede.shipped  .verdict { color: var(--ok); }
  .feature .lede.blocked  .verdict { color: var(--error); }
  .feature .lede.running  .verdict { color: var(--accent); }
  .feature .lede.legacy   .verdict { color: var(--text-faint); font-style: italic; }
  .feature .subhead {
    font-family: var(--serif);
    font-style: italic;
    font-size: 16px;
    color: var(--text-soft);
    margin-bottom: 18px;
  }

  /* Gate trail */
  .gates {
    list-style: none;
    padding: 0;
    margin: 0;
    font-family: var(--mono);
    font-size: 13px;
  }
  .gates li {
    display: grid;
    grid-template-columns: 28px 1fr auto;
    gap: 12px;
    padding: 4px 0;
    align-items: baseline;
  }
  .gates .mark { text-align: center; }
  .gates .mark.done    { color: var(--ok); }
  .gates .mark.running { color: var(--accent); font-weight: bold; }
  .gates .mark.pending { color: var(--text-faint); }
  .gates .mark.fail    { color: var(--error); font-weight: bold; }
  .gates .label { color: var(--text); }
  .gates .detail { color: var(--text-soft); }
  .gates li.pending { color: var(--text-faint); }
  .gates li.pending .label { color: var(--text-faint); }
  .gates li.fail .label { color: var(--error); }

  /* Compact history list */
  .history {
    list-style: none;
    padding: 0;
    margin: 0;
    font-size: 14px;
  }
  .history li {
    display: grid;
    grid-template-columns: 72px 110px 1fr auto;
    gap: 18px;
    padding: 9px 0;
    border-bottom: 1px solid var(--rule);
    align-items: baseline;
  }
  .history li:last-child { border-bottom: none; }
  .history .time {
    font-family: var(--mono);
    font-size: 12px;
    color: var(--text-soft);
  }
  .history .slice {
    font-family: var(--serif);
    font-weight: 700;
    color: var(--text);
  }
  .history .verdict {
    font-family: var(--serif);
    color: var(--text-soft);
    font-style: italic;
  }
  .history .verdict.shipped { color: var(--ok); font-style: normal; }
  .history .verdict.blocked { color: var(--error); font-style: normal; }
  .history .verdict.running { color: var(--accent); font-style: normal; }
  .history .verdict.legacy  { color: var(--text-faint); font-style: italic; }
  .history .runid {
    font-family: var(--mono);
    font-size: 11px;
    color: var(--text-faint);
    text-align: right;
  }

  /* Issues — only shown when real */
  .issues { list-style: none; padding: 0; margin: 8px 0 0; }
  .issues li {
    padding: 12px 0;
    border-bottom: 1px dashed var(--rule);
  }
  .issues li:last-child { border-bottom: none; }
  .issues .where {
    font-family: var(--mono);
    font-size: 11px;
    color: var(--text-soft);
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-bottom: 4px;
  }
  .issues .msg {
    font-family: var(--serif);
    font-size: 15px;
    color: var(--text);
  }

  /* Empty state */
  .empty {
    font-family: var(--serif);
    font-style: italic;
    color: var(--text-faint);
    padding: 12px 0;
  }

  /* Footer */
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
  .footer a {
    color: var(--text-soft);
    text-decoration: none;
    border-bottom: 1px dotted var(--rule);
  }
  .footer a:hover { color: var(--accent); }
</style>
</head>
<body>
<div class="page">
  <header class="masthead">
    <div>
      <div class="title">Pipeline Observatory</div>
      <div class="subtitle">COBOL → Hexagonal Java</div>
    </div>
    <div class="clock" id="clock">—</div>
  </header>

  <section id="feature-section">
    <h2>Latest run</h2>
    <div id="feature"></div>
  </section>

  <section id="issues-section" hidden>
    <h2>Open issues</h2>
    <ul class="issues" id="issues"></ul>
  </section>

  <section id="history-section">
    <h2>Recent runs</h2>
    <ul class="history" id="history"></ul>
  </section>

  <div class="footer">
    <div id="root-path">—</div>
    <div>polling every 2.5s · <a href="/api/state" target="_blank">/api/state</a></div>
  </div>
</div>

<script>
const STATUS_GLYPH = { done: '✓', running: '◐', pending: '·', fail: '✗' };

const GATE_LABEL_HUMAN = {
  'code-arrived': 'Code arrived',
  'compile':       'Compiled',
  'drift':         'Followed the architecture',
  'run':           'Ran against the fixture',
  'oracle-diff':   'Matched the expected output',
};

const VERDICT_PHRASES = {
  shipped: 'shipped',
  blocked: 'blocked',
  running: 'working…',
  legacy:  'older — no record',
  smoke:   'smoke build',
};

const VERDICT_LEDE = {
  shipped: 'shipped',
  blocked: 'blocked',
  running: 'in flight',
  legacy:  'an older run (no conveyor record)',
  smoke:   'a smoke build',
};

const VERDICT_CLASS = {
  shipped: 'shipped',
  blocked: 'blocked',
  running: 'running',
  legacy:  'legacy',
  smoke:   'legacy',
};

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
  return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
}

function fmtWhen(epoch) {
  if (!epoch) return '—';
  const d = new Date(epoch * 1000);
  return d.toLocaleString('en-GB', {
    weekday: 'long', day: '2-digit', month: 'long',
    hour: '2-digit', minute: '2-digit',
  });
}

function fmtClock() {
  const d = new Date();
  return d.toLocaleString('en-GB', {
    weekday: 'short', day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  });
}

function el(tag, attrs = {}, ...children) {
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

function verdictWord(run) {
  if (run.is_live) return 'running';
  return run.overall_status;
}

function renderFeature(run) {
  const verdict = verdictWord(run);
  const cls = VERDICT_CLASS[verdict] || 'legacy';
  const ledeWord = VERDICT_LEDE[verdict] || verdict;

  const lede = el('h1', { class: 'lede ' + cls });
  lede.appendChild(el('span', { class: 'slice' }, run.slice || 'unknown'));
  lede.appendChild(document.createTextNode(' is '));
  lede.appendChild(el('span', { class: 'verdict' }, ledeWord));
  lede.appendChild(document.createTextNode('.'));

  const when = el('div', { class: 'when' }, fmtWhen(run.last_mtime));
  const subhead = el('div', { class: 'subhead' }, run.summary_line || '');

  const gateList = el('ul', { class: 'gates' });
  // Pull just the conveyor gates from the phases array (id starts with "G:").
  const conveyorPhases = (run.phases || []).filter(p => p.id && p.id.startsWith('G:') && p.id !== 'G:attempts');
  for (const p of conveyorPhases) {
    const mark = el('span', { class: 'mark ' + p.status }, STATUS_GLYPH[p.status] || '·');
    const humanLabel = GATE_LABEL_HUMAN[p.id.replace('G:', '')] || p.label;
    const label = el('span', { class: 'label' }, humanLabel);
    const detail = el('span', { class: 'detail' }, p.detail || '');
    gateList.appendChild(el('li', { class: p.status }, mark, label, detail));
  }

  const container = el('div', { class: 'feature' }, when, lede, subhead, gateList);
  return container;
}

function renderHistoryRow(run) {
  const time = el('span', { class: 'time' }, fmtTimeOfDay(run.last_mtime));
  const slice = el('span', { class: 'slice' }, run.slice || '—');
  const verdict = verdictWord(run);
  const cls = VERDICT_CLASS[verdict] || 'legacy';
  const phrase = VERDICT_PHRASES[verdict] || verdict;
  const verdictEl = el('span', { class: 'verdict ' + cls }, phrase);
  const runid = el('span', { class: 'runid' }, (run.run_id || '').slice(0, 17));
  return el('li', {}, time, slice, verdictEl, runid);
}

function renderIssues(issues) {
  const section = document.getElementById('issues-section');
  const list = document.getElementById('issues');
  list.innerHTML = '';
  if (!issues.length) {
    section.hidden = true;
    return;
  }
  section.hidden = false;
  for (const i of issues) {
    const where = el('div', { class: 'where' },
      `${i.slice || ''} · ${(i.run_id || '').slice(0, 17)}`);
    const msg = el('div', { class: 'msg' }, i.message);
    list.appendChild(el('li', {}, where, msg));
  }
}

async function refresh() {
  try {
    const r = await fetch('/api/state', { cache: 'no-store' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const state = await r.json();

    document.getElementById('root-path').textContent = state.artifacts_root;
    document.getElementById('clock').textContent = fmtClock();

    // Featured: server picks priority (live > shipped/blocked > legacy > smoke).
    const featured = state.featured;
    const featureEl = document.getElementById('feature');
    featureEl.innerHTML = '';
    if (featured) {
      featureEl.appendChild(renderFeature(featured));
    } else {
      featureEl.appendChild(el('div', { class: 'empty' }, 'No runs yet.'));
    }

    // Recent: server already excluded the featured run.
    const historyEl = document.getElementById('history');
    historyEl.innerHTML = '';
    const recent = state.recent || [];
    if (recent.length === 0) {
      historyEl.appendChild(el('div', { class: 'empty' }, 'No older runs.'));
    } else {
      for (const run of recent.slice(0, 12)) {
        historyEl.appendChild(renderHistoryRow(run));
      }
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
