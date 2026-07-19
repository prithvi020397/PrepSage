// 50-module.js — lines 935-1107 of original bundle. Key fns: toggleSqlClarify, renderSqlClarifyGate, revealSqlClarify, closeSqlClarify, gradeTradeoff, setQuestionTitle
const SQL_CLARIFY_MIN = 2;

function toggleSqlClarify() {
  if (sqlClarifyMode) { revealSqlClarify(); return; }
  sqlClarifyMode = true;
  sqlClarifyAsked = 0;
  document.getElementById('sample').style.display = 'none';
  document.getElementById('clarify-menu').classList.add('active');
  renderSqlClarifyGate();
  addMsg('system', "Clarify-first mode — I'll ask about the schema and edge cases before coding");
}

function renderSqlClarifyGate() {
  const gate = document.getElementById('clarify-gate');
  gate.style.display = 'block';
  const remaining = Math.max(0, SQL_CLARIFY_MIN - sqlClarifyAsked);
  gate.innerHTML = `🎯 Schema hidden — ask the tutor about the table shape, nulls, ties, or edge cases first.` +
    `<div class="clarify-progress">${remaining > 0 ? `Ask ${remaining} more clarifying question${remaining === 1 ? '' : 's'} to unlock, or reveal now.` : 'Ready when you are.'}</div>` +
    `<button class="btn btn-ghost" onclick="revealSqlClarify()">Reveal schema &amp; start coding</button>`;
}

function revealSqlClarify() {
  sqlClarifyMode = false;
  if (current) renderSample(current);
  document.getElementById('clarify-gate').style.display = 'none';
  document.getElementById('clarify-menu').classList.remove('active');
}

function closeSqlClarify() {
  sqlClarifyMode = false;
  sqlClarifyAsked = 0;
  if (current) renderSample(current);
  document.getElementById('clarify-gate').style.display = 'none';
  document.getElementById('clarify-menu').classList.remove('active');
}

async function gradeTradeoff() {
  const btn = document.getElementById('tradeoff-grade-btn');
  const answer = document.getElementById('tradeoff-input').value;
  const el = document.getElementById('tradeoff-feedback');
  btn.disabled = true;
  el.className = 'pending';
  el.textContent = 'Grading…';
  const res = await (await fetch('/api/tradeoff-grade', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({question_id: current.id, answer})
  })).json();
  btn.disabled = false;
  el.className = res.ok ? 'ok' : 'bad';
  el.textContent = (res.ok ? '✓ ' : '✗ ') + res.feedback;
  if (res.ok) markSolved(current.id);
}

function setQuestionTitle(title) {
  const prefix = window.JD_CONTEXT ? window.JD_CONTEXT + ' — ' : '';
  document.getElementById('title').textContent = prefix + title;
}

async function rerollTradeoff() {
  const btn = document.getElementById('tradeoff-reroll-btn');
  btn.disabled = true;
  btn.textContent = 'Loading…';
  const res = await (await fetch('/api/tradeoff-regenerate', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({question_id: current.id})
  })).json();
  btn.disabled = false;
  btn.textContent = '🎲 New scenario';
  if (res.error) { showToast('Could not generate a new scenario: ' + res.error); return; }
  current.title = res.title;
  current.prompt = res.prompt;
  setQuestionTitle(res.title);
  document.getElementById('prompt').textContent = res.prompt;
  document.getElementById('tradeoff-input').value = '';
  document.getElementById('tradeoff-feedback').outerHTML = '<div id="tradeoff-feedback"></div>';
  resetTradeoffSpar();
}

let tradeoffSparStarted = false;

function resetTradeoffSpar() {
  tradeoffSparStarted = false;
  document.getElementById('tradeoff-spar').style.display = 'none';
  document.getElementById('tradeoff-spar-log').innerHTML = '';
}

async function startTradeoffSpar() {
  document.getElementById('tradeoff-spar').style.display = '';
  if (tradeoffSparStarted) return;
  tradeoffSparStarted = true;
  const opener = document.getElementById('tradeoff-input').value.trim() ||
    "I'll go with whichever option seems safer here — convince me otherwise.";
  await sendTradeoffSpar(opener);
}

async function sendTradeoffSpar(prefill) {
  const inputEl = document.getElementById('tradeoff-spar-input');
  const message = prefill !== undefined ? prefill : inputEl.value.trim();
  if (!message) return;
  appendSparTurn('you', message);
  inputEl.value = '';
  const res = await (await fetch('/api/tradeoff-spar', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({question_id: current.id, message})
  })).json();
  if (res.error) { appendSparTurn('tutor', 'Error: ' + res.error); return; }
  appendSparTurn('tutor', res.reply);
}

function appendSparTurn(who, text) {
  const log = document.getElementById('tradeoff-spar-log');
  const div = document.createElement('div');
  div.innerHTML = `<b>${who === 'you' ? 'You' : '🥊 Tutor'}:</b> ${escapeHtml(text)}`;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}


async function submitDebrief() {
  const complexity = document.getElementById('complexity-input').value.trim();
  const edge_cases = document.getElementById('edge-input').value.trim();
  const narrationVal = (document.getElementById('narration-input').value.trim() || narrationText).trim();
  const isSql = current.lang === 'sql';
  const btn = document.getElementById('debrief-btn');
  const fb = document.getElementById('debrief-feedback');
  if ((!isSql && !complexity) || !edge_cases) {
    fb.innerHTML = '';
    const line = document.createElement('div');
    line.className = 'line bad';
    line.textContent = isSql ? 'Fill in the edge cases field.' : 'Fill in both fields.';
    fb.appendChild(line);
    return;
  }
  btn.disabled = true;
  fb.innerHTML = '';
  const pendingLine = document.createElement('div');
  pendingLine.className = 'line pending';
  pendingLine.textContent = 'Grading…';
  fb.appendChild(pendingLine);
  const res = await (await fetch('/api/debrief', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({question_id: current.id, code: cm.getValue(), complexity, edge_cases, narration: narrationVal})
  })).json();
  btn.disabled = false;
  fb.innerHTML = '';
  if (!isSql) {
    const complexityLine = document.createElement('div');
    complexityLine.className = 'line ' + (res.complexity_ok ? 'ok' : 'bad');
    complexityLine.textContent = (res.complexity_ok ? '✓' : '✗') + ' complexity: ' + res.complexity_feedback;
    fb.appendChild(complexityLine);
  }
  const edgeLine = document.createElement('div');
  edgeLine.className = 'line ' + (res.edge_ok ? 'ok' : 'bad');
  edgeLine.textContent = (res.edge_ok ? '✓' : '✗') + ' edge cases: ' + res.edge_feedback;
  fb.appendChild(edgeLine);
  if ('narration_ok' in res) {
    const narrationLine = document.createElement('div');
    narrationLine.className = 'line ' + (res.narration_ok ? 'ok' : 'bad');
    narrationLine.textContent = (res.narration_ok ? '✓' : '✗') + ' narration: ' + res.narration_feedback;
    fb.appendChild(narrationLine);
  }
  // Phase 2: surface exactly 3 prioritized takeaways from this debrief
  fetch('/api/takeaways', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({question_id: current.id, complexity_ok: res.complexity_ok, edge_ok: res.edge_ok})
  }).then(r => r.json()).then(t => renderTakeaways(t.takeaways)).catch(() => {});
  narrationText = '';
  document.getElementById('narration-input').value = '';
  document.getElementById('narration-readout').style.display = 'none';
  // trigger what-if after debrief
  showWhatIf();
}
