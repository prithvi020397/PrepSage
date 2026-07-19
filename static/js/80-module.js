// 80-module.js — lines 1922-2214 of original bundle. Key fns: addCaseCaption, renderQuestionContext, addMsg, startDebug, renderDebugCode, debugStep

function addCaseCaption(el, numCases) {
  if (!numCases || numCases < 1) return;
  const cap = document.createElement('div');
  cap.className = 'spec-caption';
  const word = numCases === 1 ? 'test case' : 'test cases';
  cap.innerHTML = `This example shows one sample. Your solution is verified against <b>${numCases} ${word}</b> — get them all right to pass.`;
  el.appendChild(cap);
}

function renderQuestionContext(ctx) {
  const box = document.getElementById('context-box');
  if (!ctx || (!ctx.scenario && !ctx.why_asked && !(ctx.edge_cases || []).length)) {
    box.style.display = 'none';
    box.innerHTML = '';
    return;
  }
  box.innerHTML = '';
  if (ctx.scenario) {
    const s = document.createElement('div');
    s.className = 'ctx-scenario';
    s.textContent = ctx.scenario;
    box.appendChild(s);
  }
  if (ctx.why_asked) {
    const w = document.createElement('div');
    w.className = 'ctx-why';
    w.innerHTML = `<span class="ctx-why-label">Why it's asked</span> ${ctx.why_asked}`;
    box.appendChild(w);
  }
  if (ctx.edge_cases && ctx.edge_cases.length) {
    const e = document.createElement('div');
    e.className = 'ctx-edges';
    e.innerHTML = '<span class="ctx-why-label">Watch for</span> ' +
      ctx.edge_cases.map(x => `<span class="ctx-chip">${x}</span>`).join('');
    box.appendChild(e);
  }
  box.style.display = 'block';
}

function addMsg(role, text) {
  const log = document.getElementById('chatlog');
  const d = document.createElement('div');
  d.className = 'msg ' + (role === 'system' ? 'system' : role === 'user' ? 'me' : 'tutor');

  if (role !== 'user' && role !== 'system') {
    const avatar = document.createElement('span');
    avatar.className = 'msg-avatar';
    avatar.textContent = 'L↻';
    d.appendChild(avatar);
  }

  const textSpan = document.createElement('span');
  textSpan.className = 'msg-text';
  textSpan.textContent = text;
  d.appendChild(textSpan);

  log.appendChild(d);
  log.scrollTop = log.scrollHeight;
  return d;
}

let debugSteps = [];
let debugIdx = -1;
let debugSource = [];

async function startDebug() {
  const btn = document.getElementById('debug-menu');
  btn.disabled = true;
  btn.innerHTML = '<svg class="icon" viewBox="0 0 24 24"><use href="#i-psy"/></svg>Debugging…';
  const res = await (await fetch('/api/debug', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({question_id: current.id, code: cm.getValue()})
  })).json();
  btn.disabled = false;
  btn.disabled = false;
  btn.innerHTML = '<svg class="icon" viewBox="0 0 24 24"><use href="#i-psy"/></svg>Debug (step through)';
  if (res.error) { showToast('Debug error: ' + res.error); return; }
  debugSteps = res.steps || [];
  debugSource = res.source || [];
  if (!debugSteps.length) { showToast('No steps captured — check that your function is named solve() and has code in it.'); return; }
  debugIdx = -1;
  document.getElementById('debug-panel').style.display = '';
  document.getElementById('results').innerHTML = '';
  document.getElementById('results').className = '';
  document.getElementById('run-btn').disabled = true;
  document.getElementById('submit-btn').disabled = true;
  renderDebugCode();
  debugStep(1);
}

function renderDebugCode() {
  const el = document.getElementById('debug-code');
  el.innerHTML = debugSource.map((line, i) =>
    `<div class="dl" data-line="${i + 1}"><span class="dl-num">${String(i + 1).padStart(2, ' ')}</span>${escapeHtml(line) || ' '}</div>`
  ).join('');
}

function debugStep(dir) {
  const newIdx = Math.max(0, Math.min(debugSteps.length - 1, debugIdx + dir));
  if (newIdx === debugIdx) return;
  debugIdx = newIdx;
  const step = debugSteps[debugIdx];
  const total = debugSteps.length;
  document.getElementById('debug-counter').textContent = `Step ${debugIdx + 1} / ${total}`;
  document.getElementById('debug-prev').disabled = debugIdx === 0;
  document.getElementById('debug-next').disabled = debugIdx >= total - 1;
  document.getElementById('debug-run-all').disabled = debugIdx >= total - 1;

  document.querySelectorAll('#debug-code .dl').forEach(el => el.classList.remove('active'));
  const lineEl = document.querySelector(`#debug-code .dl[data-line="${step.line}"]`);
  if (lineEl) lineEl.classList.add('active');

  const varsEl = document.getElementById('debug-vars-table');
  const locals = step.locals || {};
  const keys = Object.keys(locals);
  if (!keys.length) {
    varsEl.innerHTML = '<div class="dv-empty">(no local variables yet)</div>';
  } else {
    varsEl.innerHTML = keys.map(k =>
      `<div class="dv-row"><span class="dv-name">${escapeHtml(k)}</span><span class="dv-val">= ${escapeHtml(locals[k])}</span></div>`
    ).join('');
  }
}

function debugRunAll() {
  debugIdx = debugSteps.length - 1;
  const step = debugSteps[debugIdx];
  document.getElementById('debug-counter').textContent = `Step ${debugIdx + 1} / ${debugSteps.length}`;
  document.getElementById('debug-prev').disabled = false;
  document.getElementById('debug-next').disabled = true;
  document.getElementById('debug-run-all').disabled = true;
  document.querySelectorAll('#debug-code .dl').forEach(el => el.classList.remove('active'));
  const lineEl = document.querySelector(`#debug-code .dl[data-line="${step.line}"]`);
  if (lineEl) lineEl.classList.add('active');
  const varsEl = document.getElementById('debug-vars-table');
  const last = debugSteps[debugIdx];
  const locals = last.locals || {};
  const keys = Object.keys(locals);
  varsEl.innerHTML = keys.length
    ? keys.map(k => `<div class="dv-row"><span class="dv-name">${escapeHtml(k)}</span><span class="dv-val">= ${escapeHtml(locals[k])}</span></div>`).join('')
    : '<div class="dv-empty">(no local variables)</div>';
}

function closeDebug() {
  document.getElementById('debug-panel').style.display = 'none';
  document.getElementById('run-btn').disabled = false;
  document.getElementById('submit-btn').disabled = false;
  debugSteps = [];
  debugIdx = -1;
}

async function showDiff(qid) {
  const overlay = document.getElementById('diff-overlay');
  overlay.style.display = '';
  document.getElementById('diff-user-lines').textContent = 'Loading…';
  document.getElementById('diff-solution-lines').textContent = 'Loading…';
  document.getElementById('diff-context-bar').textContent = '';
  const res = await (await fetch('/api/diff', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body:JSON.stringify({question_id: qid, code: cm.getValue()})
  })).json();
  if (res.error) { document.getElementById('diff-user-lines').textContent = 'Error: ' + res.error; return; }
  const diff = res.diff || [];
  let userHtml = '', solHtml = '', contextBar = null;
  diff.forEach((entry, i) => {
    const num = i + 1;
    const uMod = entry.context ? ' diff-remove' : '';
    const sMod = entry.context ? ' diff-add' : '';
    userHtml += `<div class="diff-line${uMod}"><span class="diff-line-num">${num}</span><span class="diff-line-code">${escapeHtml(entry.user)}</span></div>`;
    solHtml += `<div class="diff-line${sMod}"><span class="diff-line-num">${num}</span><span class="diff-line-code">${escapeHtml(entry.solution)}</span></div>`;
    if (entry.context) {
      if (!contextBar) contextBar = '';
      contextBar += `<div class="diff-context-msg">💡 ${escapeHtml(entry.context)}</div>`;
    }
  });
  document.getElementById('diff-user-lines').innerHTML = userHtml;
  document.getElementById('diff-solution-lines').innerHTML = solHtml;
  document.getElementById('diff-context-bar').innerHTML = contextBar || '<span style="color:var(--text-faint);">No significant differences found.</span>';
}

function closeDiff() {
  document.getElementById('diff-overlay').style.display = 'none';
}

async function runSample() {
  const res = await (await fetch('/api/run', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({question_id: current.id, code: cm.getValue()})
  })).json();
  const el = document.getElementById('results');
  el.innerHTML = '';
  el.className = (res.passed ? 'pass' : 'fail') + ' sample';

  const header = document.createElement('div');
  header.className = 'result-banner';
  const icon = document.createElement('span');
  icon.className = 'result-icon';
  icon.textContent = res.passed ? '✓' : '✕';
  const label = document.createElement('span');
  label.textContent = res.passed
    ? 'Sample matches'
    : 'Sample doesn’t match' + (res.error ? ` — error: ${res.error}` : '');
  header.appendChild(icon);
  header.appendChild(label);
  el.appendChild(header);

  const body = document.createElement('div');
  body.className = 'result-body';
  if (current.lang === 'sql') {
    body.appendChild(makeLabeled(res.passed ? 'output' : 'actual', makeTable(res.actual_columns, res.actual)));
    if (!res.passed && !res.error) body.appendChild(makeLabeled('expected', makeTable(res.expected_columns, res.expected)));
  } else {
    const actualPre = document.createElement('pre'); actualPre.textContent = res.actual;
    body.appendChild(makeLabeled(res.passed ? 'output' : 'your output', actualPre));
    if (!res.passed && !res.error) {
      const expectedPre = document.createElement('pre'); expectedPre.textContent = res.expected;
      body.appendChild(makeLabeled('expected output', expectedPre));
    }
  }
  el.appendChild(body);
}

async function submitCode() {
  const res = await (await fetch('/api/submit', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({question_id: current.id, code: cm.getValue()})
  })).json();
  const el = document.getElementById('results');
  el.innerHTML = '';
  el.className = res.passed ? 'pass' : 'fail';

  const header = document.createElement('div');
  header.className = 'result-banner';
  const icon = document.createElement('span');
  icon.className = 'result-icon';
  icon.textContent = res.passed ? '✓' : '✕';
  const label = document.createElement('span');
  label.textContent = res.passed
    ? `PASS — ${res.total_cases}/${res.total_cases} cases`
    : `FAIL on case ${res.case}/${res.total_cases}` + (res.error ? ` — error: ${res.error}` : '');
  header.appendChild(icon);
  header.appendChild(label);
  el.appendChild(header);

  const body = document.createElement('div');
  body.className = 'result-body';
  if (res.passed) {
    if (current.lang === 'sql') {
      body.appendChild(makeLabeled('output', makeTable(res.actual_columns, res.actual)));
    } else {
      const outPre = document.createElement('pre'); outPre.textContent = res.actual;
      body.appendChild(makeLabeled('output', outPre));
    }
    markSolved(current.id);
    stopTimer(current.id);
    renderConceptBox(current, true);
    document.getElementById('twist-menu').disabled = false;
    if (current.lang === 'python') document.getElementById('dryrun-menu').disabled = false;
    document.getElementById('debrief-row').style.display = 'flex';
  } else if (!res.error) {
    if (current.lang === 'sql') {
      body.appendChild(makeLabeled('actual', makeTable(res.actual_columns, res.actual)));
      body.appendChild(makeLabeled('expected', makeTable(res.expected_columns, res.expected)));
    } else {
      const actualPre = document.createElement('pre'); actualPre.textContent = res.actual;
      const expectedPre = document.createElement('pre'); expectedPre.textContent = res.expected;
      body.appendChild(makeLabeled('your output', actualPre));
      body.appendChild(makeLabeled('expected output', expectedPre));
    }
    const diffBtn = document.createElement('button');
    diffBtn.className = 'btn btn-ghost';
    diffBtn.textContent = '📊 Show diff';
    diffBtn.onclick = () => showDiff(current.id);
    diffBtn.style.marginTop = '8px';
    body.appendChild(diffBtn);
  }
  if (body.childNodes.length) el.appendChild(body);

  lastRunSummary = el.textContent;
  stuck = !res.passed;
  nudgeSent = false;
  if (res.passed && !reinforced) {
    reinforced = true;
    requestHint({question_id: current.id, code: cm.getValue(), actual: lastRunSummary, reinforce: true});
    // Option C: hold the review until the candidate answers the recall question,
    // then tailor it to what they said. Don't fire it unprompted.
    pendingRecallReview = {qid: current.id, code: cm.getValue()};
    document.getElementById('skip-review-btn').style.display = '';
  }
  resetIdleTimer();
}
