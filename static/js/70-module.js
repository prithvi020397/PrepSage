// 70-module.js — lines 1658-1922 of original bundle. Key fns: makeTable, makeLabeled, renderSkeleton, toggleTrace, renderTraceSteps, checkTrace

function makeTable(columns, rows) {
  const table = document.createElement('table');
  table.className = 'datatable';
  if (columns && columns.length) {
    const thead = document.createElement('tr');
    columns.forEach(c => { const th = document.createElement('th'); th.textContent = c; thead.appendChild(th); });
    table.appendChild(thead);
  }
  (rows || []).forEach(r => {
    const tr = document.createElement('tr');
    r.forEach(v => { const td = document.createElement('td'); td.textContent = v === null ? 'NULL' : v; tr.appendChild(td); });
    table.appendChild(tr);
  });
  return table;
}

function makeLabeled(label, node) {
  const wrap = document.createElement('div');
  const h = document.createElement('div');
  h.className = 'tname';
  h.textContent = label;
  wrap.appendChild(h);
  wrap.appendChild(node);
  return wrap;
}

function renderSkeleton(skeletonHTML) {
  const el = document.getElementById('trace-skeleton');
  if (!el) return;
  if (!skeletonHTML) { el.style.display = 'none'; return; }
  el.style.display = 'block';
  el.innerHTML = skeletonHTML;
}

function toggleTrace() {
  const body = document.getElementById('trace-body');
  const chev = document.querySelector('#trace-toggle .trace-chevron');
  const open = body.style.display !== 'none';
  body.style.display = open ? 'none' : 'block';
  if (chev) chev.style.transform = open ? '' : 'rotate(90deg)';
}

let traceProgress = {}; // qid -> {pattern, skeleton, steps: [{q, a, status: 'open'|'correct'|'revealed', attempts, guess}]}

function renderTraceSteps(qid) {
  const box = document.getElementById('trace-box');
  const stepsEl = document.getElementById('trace-steps');
  const t = traceProgress[qid];
  if (!t || !t.steps.length) { box.style.display = 'none'; return; }
  box.style.display = 'block';
  const sub = document.getElementById('trace-toggle-sub');
  sub.textContent = t.pattern ? ` · ${t.pattern} · ${t.steps.length} steps` : ` · ${t.steps.length} steps`;
  stepsEl.innerHTML = '';
  let correctCount = 0;
  t.steps.forEach((s, i) => {
    const card = document.createElement('div');
    card.style.cssText = 'background:var(--card-2);border:1px solid var(--border-soft);border-radius:8px;padding:10px 12px;';
    const qP = document.createElement('div');
    qP.style.cssText = 'color:var(--text);font-size:13px;line-height:1.5;margin-bottom:8px;';
    qP.textContent = (i+1) + '. ' + s.q;
    card.appendChild(qP);
    if (s.status === 'correct' || s.status === 'revealed') {
      if (s.status === 'correct') correctCount++;
      const ansP = document.createElement('div');
      const isCorrect = s.status === 'correct';
      ansP.style.cssText = 'font-family:JetBrains Mono,monospace;font-size:13px;color:' + (isCorrect ? 'var(--success)' : 'var(--warn)') + ';';
      ansP.textContent = (isCorrect ? '✓ ' : '→ ') + s.a;
      card.appendChild(ansP);
    } else {
      const inp = document.createElement('input');
      inp.type = 'text';
      inp.className = 'trace-input';
      inp.dataset.index = i;
      inp.value = s.guess || '';
      inp.placeholder = 'your code…';
      inp.style.cssText = 'width:100%;background:var(--panel);border:1px solid var(--border);border-radius:6px;padding:7px 10px;font-family:JetBrains Mono,monospace;font-size:12.5px;color:var(--text);box-sizing:border-box;';
      card.appendChild(inp);
      if (s.attempts > 0) {
        const tries = document.createElement('div');
        const left = 3 - s.attempts;
        tries.style.cssText = 'font-size:11px;color:var(--error);margin-top:5px;';
        tries.textContent = 'Not quite — ' + left + ' ' + (left === 1 ? 'try' : 'tries') + ' left';
        card.appendChild(tries);
      }
    }
    stepsEl.appendChild(card);
  });
  const allDone = t.steps.every(s => s.status === 'correct' || s.status === 'revealed');
  document.getElementById('trace-check-btn').style.display = allDone ? 'none' : '';
  document.getElementById('trace-summary').textContent = correctCount + '/' + t.steps.length + ' correct' + (allDone ? ' — trace complete, now code it.' : '');
}

async function checkTrace() {
  const qid = current.id;
  const t = traceProgress[qid];
  if (!t) return;
  const answers = [];
  document.querySelectorAll('#trace-steps .trace-input').forEach(inp => {
    const i = parseInt(inp.dataset.index, 10);
    const guess = inp.value.trim();
    if (t.steps[i].status === 'open' && guess) {
      t.steps[i].guess = guess;
      answers.push({index: i, guess});
    }
  });
  if (!answers.length) return;
  const btn = document.getElementById('trace-check-btn');
  const origLabel = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Checking…';
  try {
    const res = await (await fetch('/api/trace-check', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({question_id: qid, answers})
    })).json();
    for (const r of (res.results || [])) {
      const st = t.steps[r.index];
      if (!st) continue;
      if (r.correct) {
        st.status = 'correct';
      } else {
        st.attempts += 1;
        if (st.attempts >= 3) st.status = 'revealed';
      }
    }
  } finally {
    btn.disabled = false;
    btn.textContent = origLabel;
  }
  renderTraceSteps(qid);
}

async function loadTrace(qid) {
  if (traceProgress[qid]) { renderTraceSteps(qid); return; }
  document.getElementById('trace-box').style.display = 'none';
  const res = await (await fetch('/api/trace', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body:JSON.stringify({question_id: qid, code: cm.getValue()})
  })).json();
  traceProgress[qid] = {
    pattern: res.pattern || '',
    skeleton: res.skeleton || '',
    steps: (res.trace || []).map(s => ({q: s.q, a: s.a, status: 'open', attempts: 0, guess: ''}))
  };
  renderTraceSteps(qid);
}

async function loadConceptMapper(qid) {
  const el = document.getElementById('concept-mapper');
  const res = await (await fetch('/api/concept-map', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body:JSON.stringify({question_id: qid})
  })).json();
  if (res.error) { el.style.display = 'none'; return; }
  el.style.display = 'block';
  const nodesEl = document.getElementById('concept-mapper-nodes');
  const detailEl = document.getElementById('concept-mapper-detail');
  const solved = isSolved(qid);
  const activeCount = solved ? 5 : 3;
  const visible = res.nodes.slice(0, activeCount);
  nodesEl.innerHTML = visible.map((n, i) => {
    const arrow = i < visible.length - 1 ? '<span class="cm-arrow">→</span>' : '';
    return `<span class="cm-node active" data-idx="${i}">${n}</span>${arrow}`;
  }).join('');
  nodesEl.querySelectorAll('.cm-node').forEach(el => {
    el.addEventListener('click', () => {
      const idx = parseInt(el.dataset.idx, 10);
      const prev = detailEl.dataset.activeIdx;
      if (prev === String(idx)) { detailEl.style.display = 'none'; detailEl.dataset.activeIdx = ''; return; }
      detailEl.dataset.activeIdx = idx;
      const d = res.details[res.nodes[idx]];
      if (!d) { detailEl.style.display = 'none'; return; }
      detailEl.innerHTML = '';
      const items = [
        {label: 'Why', text: d.why},
        {label: 'What if', text: d.what_if},
        {label: 'Intuition', text: d.intuition},
      ];
      items.forEach(item => {
        if (!item.text) return;
        const row = document.createElement('div');
        row.className = 'cm-detail-item';
        row.innerHTML = `<span class="cm-detail-label">${item.label}:</span> <span class="cm-detail-text">${item.text}</span>`;
        detailEl.appendChild(row);
      });
      detailEl.style.display = 'block';
    });
  });
}

function renderSample(q) {
  const el = document.getElementById('sample');
  el.innerHTML = '';
  if (q.lang === 'sql' && q.sample_tables) {
    el.style.display = 'block';
    // Section: Schema & sample input
    const schemaSec = document.createElement('div');
    schemaSec.className = 'spec-section';
    schemaSec.innerHTML = '<div class="spec-section-title">Schema &amp; sample input</div>';
    const tablesWrap = document.createElement('div');
    tablesWrap.className = 'spec-tables';
    for (const [name, t] of Object.entries(q.sample_tables)) {
      const block = document.createElement('div');
      block.className = 'spec-table-block';
      const tname = document.createElement('div');
      tname.className = 'spec-tname';
      tname.textContent = name;
      block.appendChild(tname);
      block.appendChild(makeTable(t.columns, t.rows));
      tablesWrap.appendChild(block);
    }
    schemaSec.appendChild(tablesWrap);
    el.appendChild(schemaSec);
    // Section: Example result
    if (q.sample_output) {
      const exSec = document.createElement('div');
      exSec.className = 'spec-section';
      exSec.innerHTML = '<div class="spec-section-title">Example result</div>';
      const card = document.createElement('div');
      card.className = 'example-card';
      const row = document.createElement('div');
      row.className = 'example-row';
      const out = document.createElement('div');
      out.className = 'example-cell';
      out.innerHTML = '<div class="example-label">returns</div>';
      out.appendChild(makeTable(q.sample_output.columns, q.sample_output.rows));
      row.appendChild(out);
      card.appendChild(row);
      exSec.appendChild(card);
      el.appendChild(exSec);
    }
    addCaseCaption(el, q.num_cases);
  } else if (q.sample_call) {
    el.style.display = 'block';
    const exSec = document.createElement('div');
    exSec.className = 'spec-section';
    exSec.innerHTML = '<div class="spec-section-title">Example</div>';
    const card = document.createElement('div');
    card.className = 'example-card';
    const row = document.createElement('div');
    row.className = 'example-row';
    const inCell = document.createElement('div');
    inCell.className = 'example-cell';
    inCell.innerHTML = '<div class="example-label">call</div>';
    const callCode = document.createElement('code');
    callCode.textContent = q.sample_call;
    inCell.appendChild(callCode);
    const outCell = document.createElement('div');
    outCell.className = 'example-cell';
    outCell.innerHTML = '<div class="example-label">returns</div>';
    const outCode = document.createElement('code');
    outCode.textContent = (q.sample_output || '').trim();
    outCell.appendChild(outCode);
    row.appendChild(inCell);
    row.appendChild(outCell);
    card.appendChild(row);
    exSec.appendChild(card);
    el.appendChild(exSec);
    addCaseCaption(el, q.num_cases);
  } else {
    el.style.display = 'none';
  }
}
