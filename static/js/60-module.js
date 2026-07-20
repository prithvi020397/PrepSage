// 60-module.js — lines 1107-1658 of original bundle. Key fns: renderTakeaways, showWhatIf, submitWhatIf, resetIdleTimer, sendIdleNudge, loadList

function renderTakeaways(items) {
  const box = document.getElementById('takeaways-box');
  const list = document.getElementById('takeaways-list');
  if (!items || !items.length) { box.style.display = 'none'; return; }
  list.innerHTML = '';
  items.forEach(it => {
    const li = document.createElement('li');
    li.style.marginBottom = '6px';
    li.innerHTML = `<strong>${it.label}</strong> — ${it.text}`;
    list.appendChild(li);
  });
  box.style.display = '';
}

let whatifScenario = '';

async function showWhatIf() {
  const box = document.getElementById('whatif-box');
  const scenario = document.getElementById('whatif-scenario');
  const feedback = document.getElementById('whatif-feedback');
  const input = document.getElementById('whatif-input');
  box.style.display = 'none';
  if (!current || !current.id) return;
  try {
    const r = await api('/api/whatif', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({question_id: current.id, code: cm.getValue()})
    });
    const res = await r.json();
    if (!r.ok || res.error) return;
    whatifScenario = res.what_if;
    scenario.textContent = whatifScenario;
    feedback.innerHTML = '';
    input.value = '';
    box.style.display = '';
  } catch (e) { /* silent fail — what-if is optional */ }
}

async function submitWhatIf() {
  const input = document.getElementById('whatif-input');
  const answer = input.value.trim();
  if (!answer) return;
  const btn = document.getElementById('whatif-btn');
  const status = document.getElementById('whatif-status');
  const feedback = document.getElementById('whatif-feedback');
  btn.disabled = true;
  status.textContent = 'Grading…';
  try {
    const r = await api('/api/whatif', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({question_id: current.id, code: cm.getValue(), user_answer: answer, scenario: whatifScenario})
    });
    const res = await r.json();
    if (!r.ok || res.error) { status.textContent = 'Could not grade — discuss in chat'; btn.disabled = false; return; }
    status.textContent = '';
    feedback.innerHTML = `<div style="color:${res.ok ? 'var(--success)' : 'var(--warn)'};">${res.ok ? '✓' : '💡'} ${res.feedback}</div>`;
    input.disabled = true;
    btn.disabled = true;
    btn.textContent = 'Done';
  } catch (e) {
    status.textContent = 'Error — try again';
    btn.disabled = false;
  }
}

function resetIdleTimer() {
  clearTimeout(idleTimer);
  if (stuck && !nudgeSent) {
    idleTimer = setTimeout(sendIdleNudge, IDLE_NUDGE_MS);
  }
}

function sendIdleNudge() {
  nudgeSent = true;
  requestHint({question_id: current.id, code: cm.getValue(), actual: lastRunSummary, proactive: true});
  fabAlert('Stuck? Click me');
}

cm.on('change', resetIdleTimer);

async function loadList() {
  let qs;
  try {
    const r = await api('/api/questions');
    qs = await r.json();
  } catch (e) {
    console.error('loadList failed:', e);
    return;
  }
  const sb = document.getElementById('sidebar-list');

  const groups = [
    {lang: 'sql', label: 'SQL'},
    {lang: 'python', label: 'Python'},
    {lang: 'design', label: 'System Design'},
    {lang: 'tradeoff', label: 'Tradeoff Drills'},
    {lang: 'decomposition', label: 'FDE Decomposition'},
  ];

  groups.forEach(({lang, label}) => {
    const items = qs.filter(q => q.lang === lang);
    if (!items.length) return;

    const header = document.createElement('div');
    // auto-expand a section if it holds any due questions — those are the priority
    const hasDue = items.some(q => q.due);
    header.className = 'q-section-header ' + (hasDue ? '' : 'collapsed ') + lang;
    header.innerHTML = `<span class="chevron">▾</span><span class="dot"></span><span>${label}</span><span class="count">${items.length}</span>`;
    header.onclick = () => { header.classList.toggle('collapsed'); applySidebarFilter(); };
    sb.appendChild(header);

    // prioritized section: due reviews + unsolved, sorted due-first, on top of the section
    const priority = items.filter(q => q.due || !q.solved)
      .sort((a, b) => (b.due - a.due) || (a.solved - b.solved));
    const rest = items.filter(q => !q.due && q.solved);

    [...priority, ...rest].forEach(q => {
      const d = document.createElement('div');
      d.className = 'q-item' + (q.solved ? ' solved' : '') + (q.due ? ' due' : '');
      d.dataset.id = q.id;

      const badge = document.createElement('span');
      badge.className = 'q-lang-badge ' + q.lang;
      badge.textContent = {sql: 'SQL', python: 'PY', design: 'SYS', tradeoff: 'T/O', decomposition: 'FDE'}[q.lang];

      const title = document.createElement('span');
      title.className = 'q-title';
      title.textContent = q.title;

      const check = document.createElement('span');
      check.className = 'q-check';
      check.textContent = '✓';

      d.appendChild(badge);
      d.appendChild(title);
      if (q.difficulty) {
        const diff = document.createElement('span');
        diff.className = 'q-diff-dot ' + q.difficulty.toLowerCase();
        diff.title = q.difficulty;
        d.appendChild(diff);
      }
      if (q.due) {
        const due = document.createElement('span');
        due.className = 'q-due-dot';
        due.title = 'due for review';
        due.textContent = '↻';
        d.appendChild(due);
      }
      d.appendChild(check);
      d.onclick = () => selectQuestion(d, q.id);
      sb.appendChild(d);
    });
  });

  // hint to browse all when everything's collapsed away
  const browseHint = document.createElement('div');
  browseHint.className = 'q-browse-hint';
  browseHint.innerHTML = 'Sections collapse as you clear them — use the filter above to browse all 201.';
  sb.appendChild(browseHint);

  updateProgress();
  applySidebarFilter();
  const deepLinkId = new URLSearchParams(location.search).get('q');
  const deepLinkQ = qs.find(q => q.id === deepLinkId);
  const deepLinkEl = deepLinkQ && document.querySelector(`.q-item[data-id="${deepLinkId}"]`);
  if (deepLinkEl) {
    const header = document.querySelector('.q-section-header.' + deepLinkQ.lang);
    if (header) { header.classList.remove('collapsed'); applySidebarFilter(); }
    document.querySelectorAll('.q-item.active').forEach(x => x.classList.remove('active'));
    deepLinkEl.classList.add('active');
    await loadQuestion(deepLinkId);
    const params = new URLSearchParams(location.search);
    if (params.get('replay') === '1') {
      adversarialMode = params.get('adversarial') === '1';
      clarifyMode = params.get('requirements_only') === '1';
      incidentMode = params.get('incident') === '1';
      startReplay();
    }
  } else if (!current) {
    renderEmptyState(qs);
  }
}

function applySidebarFilter() {
  const term = document.getElementById('q-search').value.trim().toLowerCase();
  document.querySelectorAll('.q-section-header').forEach(h => {
    const collapsed = h.classList.contains('collapsed');
    let visible = 0;
    let total = 0;
    let next = h.nextElementSibling;
    while (next && !next.classList.contains('q-section-header')) {
      // skip non-question siblings (e.g. the browse hint appended after the last section)
      const titleEl = next.querySelector('.q-title');
      if (!titleEl || !next.classList.contains('q-item')) {
        next = next.nextElementSibling;
        continue;
      }
      total++;
      const match = !term || titleEl.textContent.toLowerCase().includes(term);
      next.style.display = (match && (!collapsed || term)) ? '' : 'none';
      if (match) visible++;
      next = next.nextElementSibling;
    }
    // hide sections with no matches while filtering; always show when unfiltered
    h.style.display = (term && visible === 0) ? 'none' : '';
    // keep the section count badge in sync: per-section total when unfiltered, live matches when filtering
    const countEl = h.querySelector('.count');
    if (countEl) countEl.textContent = term ? visible : total;
  });
}

function selectQuestion(el, id) {
  document.querySelectorAll('.q-item.active').forEach(x => x.classList.remove('active'));
  el.classList.add('active');
  loadQuestion(id);
  if (current && (current.lang === 'design' || current.lang === 'decomposition') && !micOn) setMicOn(true);
}

async function startPractice(lane) {
  log("startPractice:", lane || "default");
  const btn = document.querySelector('.cc-start');
  if (btn) { btn.disabled = true; btn.textContent = 'Picking…'; }
  try {
    const res = await (await api('/api/start' + (lane ? '?lane=' + encodeURIComponent(lane) : ''))).json();
    if (!res.id) {
      showToast(res.message || 'No questions available — pick one from the sidebar.');
      return;
    }
    const el = document.querySelector(`.q-item[data-id="${res.id}"]`);
    if (el) { selectQuestion(el, res.id); }
    else { await loadQuestion(res.id); }
    if (current && (current.lang === 'design' || current.lang === 'decomposition') && !micOn) setMicOn(true);
  } catch (e) {
    showToast('Could not start practice: ' + e.message);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '▶ Start Practice'; }
  }
}

function markSolved(id) {
  const item = document.querySelector(`.q-item[data-id="${id}"]`);
  if (item) { item.classList.add('solved'); item.classList.remove('due'); }
  updateProgress();
  if (current && current.id === id) loadConceptMapper(id);
}

function updateProgress() {
  const total = document.querySelectorAll('.q-item').length;
  const solved = document.querySelectorAll('.q-item.solved').length;
  document.getElementById('solved-count').textContent = `${solved}/${total} solved`;
  document.getElementById('solved-bar').style.width = (total ? solved / total * 100 : 0) + '%';
}

const FEATURE_FAMILIES = [
  {name: 'Solve', icon: 'i-play', tools: [
    {label: 'Run', icon: 'i-play', tip: 'Run your code against the sample case to check it before submitting.'},
    {label: 'Submit', icon: 'i-check', tip: 'Submit — graded against all hidden test cases. Passing locks in the concept.'},
    {label: 'Debug', icon: 'i-psy', tip: 'Step through your Python line-by-line and watch variables change.'},
    {label: 'Diff', icon: 'i-grid', tip: 'After a fail, see your code side-by-side with the ideal solution.'},
  ]},
  {name: 'Coach', icon: 'i-bulb', tools: [
    {label: 'Hint', icon: 'i-bulb', tip: 'Stuck? Get a nudge grounded in the concept — never the full answer.'},
    {label: 'Trace', icon: 'i-grid', tip: 'Build the solution line-by-line with a scaffolded code-translation drill.'},
    {label: 'Plan check', icon: 'i-check', tip: 'State your approach + complexity first; the tutor grades it.'},
    {label: 'Concept map', icon: 'i-chart', tip: 'See how Problem → Approach → Pattern → Skeleton → Solution connect.'},
  ]},
  {name: 'Pressure', icon: 'i-zap', tools: [
    {label: 'Curveball', icon: 'i-zap', tip: 'Mid-solve the interviewer changes the requirement — adapt your code.'},
    {label: 'Twist', icon: 'i-repeat', tip: 'Once solved, a follow-up variation on the same problem.'},
    {label: 'Dry run', icon: 'i-shoe', tip: 'Trace your own code by hand on a sample input.'},
    {label: 'Spot the bug', icon: 'i-bug', tip: 'Review someone else’s buggy code and find the flaw.'},
  ]},
  {name: 'Interview sim', icon: 'i-mask', tools: [
    {label: 'Clarify first', icon: 'i-target', tip: 'Hide the schema and ask clarifying questions before coding.'},
    {label: 'Adversarial', icon: 'i-shield', tip: 'Break your own design — find what fails at scale.'},
    {label: 'Incident', icon: 'i-fire', tip: '3am on-call: diagnose and stabilize a failing pipeline.'},
    {label: 'Scaling', icon: 'i-scale', tip: 'Pressure-test the design across 6 growth tiers.'},
  ]},
  {name: 'Mock', icon: 'i-loop', tools: [
    {label: 'Mock loop', icon: 'i-loop', tip: 'Chain a SQL/Python + design + tradeoff interview back-to-back.'},
    {label: 'Tradeoff', icon: 'i-scale', tip: 'Pick a side and defend it against the tutor.'},
    {label: 'Takeaways', icon: 'i-bulb', tip: 'After each solve, get 3 things worth remembering.'},
  ]},
];

function renderFeatureCompass() {
  const wrap = document.getElementById('cc-families');
  if (!wrap) return;
  wrap.innerHTML = FEATURE_FAMILIES.map(f => `
    <div class="cc-family">
      <div class="cc-family-head">
        <span class="cc-family-ico"><svg class="icon" viewBox="0 0 24 24"><use href="#${f.icon}"/></svg></span>
        <span class="cc-family-name">${f.name}</span>
      </div>
      <div class="cc-family-tools">
        ${f.tools.map(t => `
          <div class="cc-tool">
            <span class="cc-tool-info">
              <svg class="icon" viewBox="0 0 24 24"><use href="#${t.icon}"/></svg>
              <span class="cc-tip"><b>${t.label}.</b> ${t.tip}</span>
            </span>
            <span>${t.label}</span>
          </div>`).join('')}
      </div>
    </div>`).join('');
}

function toggleCompass() {
  const compass = document.getElementById('cc-compass');
  const toggle = document.getElementById('cc-compass-toggle');
  const label = document.getElementById('cc-compass-label');
  const open = compass.classList.toggle('open');
  toggle.classList.toggle('open', open);
  label.textContent = open ? 'Hide tools' : 'See all tools';
}

function renderEmptyState(qs) {
  const total = qs.length;
  const sqlCount = qs.filter(q => q.lang === 'sql').length;
  const pyCount = qs.length - sqlCount;
  const solved = document.querySelectorAll('.q-item.solved').length;
  const due = qs.filter(q => q.due);
  const weak = document.querySelectorAll('.q-item:not(.solved)').length;
  const greeting = document.getElementById('cc-greeting');
  const now = new Date();
  const hour = now.getHours();
  const hi = hour < 12 ? 'Morning' : hour < 18 ? 'Afternoon' : 'Evening';
  greeting.textContent = `${hi} — let's get into a loop.`;
  const streakEl = document.getElementById('streak-count');
  const streak = streakEl ? streakEl.textContent : '0';
  const momentum = document.getElementById('cc-momentum');
  momentum.innerHTML = `<span class="cc-pill">🔥 ${streak}d streak</span>`
    + (due.length ? `<span class="cc-pill due">↻ ${due.length} due</span>` : '')
    + (solved ? `<span class="cc-pill">✓ ${solved}/${total} solved</span>` : '');
  const standings = document.getElementById('cc-standings');
  const rows = [
    ['Total questions', total],
    ['SQL / Python', `${sqlCount} / ${pyCount}`],
    ['Solved', `${solved} (${total ? Math.round(solved / total * 100) : 0}%)`],
    ['Still to crack', weak],
  ];
  standings.innerHTML = rows.map(([l, v]) =>
    `<div class="cc-standing"><span class="cc-standing-l">${l}</span><span class="cc-standing-v">${v}</span></div>`
  ).join('');
  const panel = document.getElementById('empty-panel');
  panel.style.display = '';
  document.getElementById('command-center').style.display = '';
  // full-width command center: hide the left panel + resizer
  document.getElementById('main-left').style.display = 'none';
  document.getElementById('sidebar-resizer').style.display = 'none';
  document.getElementById('main-right').style.borderLeft = 'none';
  // reset compass to collapsed
  document.getElementById('cc-compass').classList.remove('open');
  document.getElementById('cc-compass-toggle').classList.remove('open');
  document.getElementById('cc-compass-label').textContent = 'See all tools';
  renderFeatureCompass();
}

async function loadQuestion(id) {
  log("loadQuestion:", id);
  try {
  if (document.getElementById('replay-bar').style.display !== 'none') exitReplay();
  window.speechSynthesis && window.speechSynthesis.cancel();
  clearPacingNudge();
  clearReqChips();
  saveCurrentState();
  const q = await (await api(`/api/questions/${id}`)).json();
  current = q;
  document.getElementById('empty-panel').style.display = 'none';
  // restore layout after command center was full-width
  document.getElementById('main-left').style.display = '';
  document.getElementById('sidebar-resizer').style.display = '';
  document.getElementById('main-right').style.borderLeft = '';
  clearTimeout(idleTimer);
  const card = document.getElementById('question-card');
  card.classList.remove('fade-in');
  void card.offsetWidth;
  card.classList.add('fade-in');
  setQuestionTitle(q.title);
  document.getElementById('prompt').textContent = q.prompt;
  renderQuestionContext(q.context);
  const langBadge = document.getElementById('lang-badge');
  langBadge.className = 'badge ' + q.lang;
  langBadge.textContent = {sql: 'SQL', python: 'PYTHON', design: 'SYSTEM DESIGN', tradeoff: 'TRADEOFF', decomposition: 'FDE DECOMPOSITION'}[q.lang];

  const isDesign = q.lang === 'design';
  const isDecomposition = q.lang === 'decomposition';
  const isTradeoff = q.lang === 'tradeoff';
  const isDrill = isDesign || isDecomposition;
  document.getElementById('editor-card').style.display = (isDrill || isTradeoff) ? 'none' : '';
  document.getElementById('concept-box').style.display = (isDrill || isTradeoff) ? 'none' : '';
  if (isDrill || isTradeoff) document.getElementById('concept-mapper').style.display = 'none';
  if (isDrill || isTradeoff) document.getElementById('sample').style.display = 'none';
  document.getElementById('results').style.display = (isDrill || isTradeoff) ? 'none' : '';
  document.getElementById('design-canvas-card').style.display = isDrill ? 'flex' : 'none';
  document.getElementById('wrapup-btn').style.display = isDrill ? '' : 'none';
  document.getElementById('clarify-btn').style.display = isDesign ? '' : 'none';
  document.getElementById('adversarial-btn').style.display = isDesign ? '' : 'none';
  document.getElementById('incident-btn').style.display = isDesign ? '' : 'none';
  document.getElementById('scaling-btn').style.display = isDesign ? '' : 'none';
  document.getElementById('framework-btn').style.display = isDesign ? '' : 'none';
  document.getElementById('replay-btn').style.display = isDrill ? '' : 'none';
  document.getElementById('end-drill-btn').style.display = 'none';
  document.getElementById('selfrate-panel').style.display = 'none';
  document.getElementById('refdesign-btn').style.display = 'none';
  resetTradeoffSpar();
  document.getElementById('tradeoff-card').style.display = isTradeoff ? '' : 'none';
  document.getElementById('chatpanel').style.display = isTradeoff ? 'none' : '';
  clarifyMode = false;
  adversarialMode = false;
  adversarialFlaws = [];
  scalingMode = false;
  incidentMode = false;
  stopFrameworkMode();

  if (isTradeoff) {
    document.getElementById('trace-box').style.display = 'none';
    document.getElementById('debrief-row').style.display = 'none';
    startTimerFor(id);
    const cached = stateCache[id];
    document.getElementById('tradeoff-input').value = (cached && cached.tradeoffInput) || '';
    document.getElementById('tradeoff-feedback').outerHTML = (cached && cached.tradeoffFeedbackHTML) || '<div id="tradeoff-feedback"></div>';
    resetIdleTimer();
    return;
  }

  if (isDesign) {
    document.getElementById('trace-box').style.display = 'none';
    document.getElementById('debrief-row').style.display = 'none';
    startTimerFor(id);
    const cached = stateCache[id];
    const chatlog = document.getElementById('chatlog');
    shapes = cached && cached.shapes ? JSON.parse(JSON.stringify(cached.shapes)) : [];
    selectedShapeId = null;
    setCanvasTool('select');
    if (cached) {
      selectedPersona = cached.persona || '';
      scalingMode = !!cached.scaling;
      chatlog.innerHTML = cached.chatHTML;
    } else {
      selectedPersona = '';
      scalingMode = false;
      chatlog.innerHTML = '';
      renderPersonaPicker('Pick an interviewer temperament to start:', PERSONA_OPTIONS, () => startInterview(id));
    }
    resetIdleTimer();
    return;
  }

  document.querySelectorAll('.archetype-picker').forEach(p => p.remove());
  if (isDecomposition) {
    document.getElementById('trace-box').style.display = 'none';
    document.getElementById('debrief-row').style.display = 'none';
    startTimerFor(id);
    const cached = stateCache[id];
    if (cached) {
      document.getElementById('chatlog').innerHTML = cached.chatHTML;
    }
    selectedArchetype = '';
    // Remove any leftover archetype picker from a previous question
    document.querySelectorAll('.archetype-picker').forEach(p => p.remove());
    if (q.archetypes) {
      const archetypeNames = Object.keys(q.archetypes);
      const picker = document.createElement('div');
      picker.className = 'archetype-picker';
      picker.style.cssText = 'margin:8px 0; display:flex; gap:8px; align-items:center; flex-wrap:wrap;';
      picker.innerHTML = '<span style="font-size:13px; font-weight:600;">Stakeholder style:</span>';
      archetypeNames.forEach(key => {
        const btn = document.createElement('button');
        btn.className = 'btn btn-ghost';
        btn.textContent = q.archetypes[key].label || key;
        btn.style.cssText = 'font-size:12px; padding:4px 10px; border-radius:6px;';
        btn.onclick = () => {
          document.querySelectorAll('.archetype-btn').forEach(b => b.style.border = '');
          btn.style.border = '2px solid var(--accent)';
          selectedArchetype = key;
        };
        btn.className = 'btn btn-ghost archetype-btn';
        picker.appendChild(btn);
      });
      // Default: standard (no archetype)
      selectedArchetype = '';
      document.getElementById('debrief-row').before(picker);
      // Auto-start for comparison mode
      if (__compareMode) {
        const autoArchetype = __compareMode;
        __compareMode = null;
        selectedArchetype = autoArchetype;
        setTimeout(() => requestInterview({question_id: id, decomposition: true, start: true}), 100);
      }
    }
    resetIdleTimer();
    return;
  }

  document.getElementById('editor-lang-label').textContent = q.lang === 'sql' ? 'SQL' : 'PYTHON';
  document.getElementById('debug-menu').style.display = q.lang === 'python' ? '' : 'none';
  renderSample(q);
  renderConceptBox(q, isSolved(id));
  loadTrace(id);
  loadConceptMapper(id);
  startTimerFor(id);
  document.getElementById('twist-menu').disabled = !isSolved(id);
  const reverseBtn = document.getElementById('reverse-menu');
  reverseBtn.disabled = !isSolved(id);
  const dryrunBtn = document.getElementById('dryrun-menu');
  dryrunBtn.style.display = q.lang === 'python' ? '' : 'none';
  dryrunBtn.disabled = !isSolved(id);
  cm.setOption('mode', q.lang === 'sql' ? 'text/x-sql' : 'python');

  const cached = stateCache[id];
  const results = document.getElementById('results');
  const planInput = document.getElementById('plan-input');
  // Guard against cross-language leaks: only restore cached code if it belongs to this question's language.
  if (cached && cached.lang === q.lang) {
    cm.setValue(cached.code);
    document.getElementById('chatlog').innerHTML = cached.chatHTML;
    results.innerHTML = cached.resultsHTML;
    results.className = cached.resultsClass;
    lastRunSummary = cached.lastRunSummary;
    stuck = cached.stuck;
    nudgeSent = cached.nudgeSent;
    reinforced = cached.reinforced;
    planInput.value = cached.plan || '';
    planApproved = !!cached.approved;
    document.getElementById('plan-feedback').outerHTML = cached.feedbackHTML || '<div id="plan-feedback"></div>';
    document.getElementById('complexity-input').value = cached.complexityInput || '';
    document.getElementById('edge-input').value = cached.edgeInput || '';
    document.getElementById('debrief-feedback').outerHTML = cached.debriefFeedbackHTML || '<div id="debrief-feedback"></div>';
  } else {
    cm.setValue(q.code || q.starter_code);
    results.innerHTML = '';
    results.className = '';
    document.getElementById('chatlog').innerHTML = '';
    lastRunSummary = '';
    stuck = false;
    nudgeSent = false;
    reinforced = false;
    pendingRecallReview = null;
    const srb = document.getElementById('skip-review-btn');
    if (srb) srb.style.display = 'none';
    planInput.value = '';
    planApproved = false;
    document.getElementById('plan-feedback').outerHTML = '<div id="plan-feedback"></div>';
    document.getElementById('complexity-input').value = '';
    document.getElementById('edge-input').value = '';
    document.getElementById('narration-input').value = '';
    document.getElementById('debrief-feedback').outerHTML = '<div id="debrief-feedback"></div>';
    document.getElementById('takeaways-box').style.display = 'none';
  }
  document.getElementById('debrief-row').style.display = isSolved(id) ? 'flex' : 'none';
  document.getElementById('complexity-input').style.display = (q.lang === 'sql') ? 'none' : '';
  narrationText = '';
  canvasVoiceNote = false;
  const toolMic = document.getElementById('tool-mic');
  if (toolMic) toolMic.classList.remove('active');
  document.getElementById('narration-readout').style.display = 'none';
  closeSpotBug();
  closeSqlClarify();
  closeCurveball();
  setEditorLocked(!planApproved);
  onPlanInput();
  resetIdleTimer();
  } catch (e) { showToast('Could not open question: ' + e.message); }
}
