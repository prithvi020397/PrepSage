// 120-module.js — lines 2849-3743 of original bundle. Key fns: startInterview, renderPersonaPicker, wrapUpInterview, submitSelfRating, showReferenceDesign, parseDiagramLines

function startInterview(id) {
  requestInterview({question_id: id, start: true});
}

const PERSONA_OPTIONS = [
  ['', 'Standard'],
  ['skeptical', '🧐 Skeptical'],
  ['friendly', '🙂 Friendly'],
  ['silent', '🤐 Silent'],
];

const ADVERSARIAL_PERSONA_OPTIONS = [
  ['', 'Standard'],
  ['friendly', '🙂 Friendly coach'],
  ['skeptical', '🧐 Skeptical'],
  ['bar_raiser', '🔥 Bar raiser'],
];

function renderPersonaPicker(promptText, options, onStart) {
  const placeholder = addMsg('tutor', promptText);
  const textEl = placeholder.querySelector('.msg-text');
  const row = document.createElement('div');
  row.style.cssText = 'display:flex; flex-wrap:wrap; gap:6px; margin-top:8px;';
  options.forEach(([key, text]) => {
    const btn = document.createElement('button');
    btn.className = 'btn btn-ghost';
    btn.textContent = text;
    btn.onclick = () => {
      selectedPersona = key;
      placeholder.remove();
      onStart();
    };
    row.appendChild(btn);
  });
  textEl.appendChild(row);
}

 function wrapUpInterview() {
  log("wrapUpInterview");
  clearPacingNudge();
  stopFrameworkMode();
  const panel = document.getElementById('selfrate-panel');
  if (current && current.lang === 'decomposition') {
    panel.style.display = 'none';
    document.getElementById('wrapup-btn').style.display = 'none';
    addMsg('system', 'Decomposition wrap-up requested');
    requestInterview({question_id: current.id, wrap_up: true, decomposition: true});
    resetIdleTimer();
    return;
  }
  const opts = document.getElementById('selfrate-options');
  opts.innerHTML = '';
  const taxonomy = CONCEPT_TAXONOMIES[(current && current.track) || 'data'];
  taxonomy.forEach(concept => {
    const label = document.createElement('label');
    label.style.cssText = 'display:block; font-size:12.5px; margin:3px 0; cursor:pointer;';
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.value = concept;
    cb.style.marginRight = '6px';
    label.appendChild(cb);
    label.appendChild(document.createTextNode(concept.replace(/_/g, ' ')));
    opts.appendChild(label);
  });
  panel.style.display = '';
  document.getElementById('wrapup-btn').style.display = 'none';
}

function submitSelfRating() {
  const selfRated = Array.from(document.querySelectorAll('#selfrate-options input:checked')).map(cb => cb.value);
  document.getElementById('selfrate-panel').style.display = 'none';
  addMsg('system', selfRated.length ? `Self-rated missed: ${selfRated.join(', ')}` : 'Self-rated: nothing missed');
  requestInterview({question_id: current.id, wrap_up: true, self_rated: selfRated});
  resetIdleTimer();
}

async function showReferenceDesign() {
  const btn = document.getElementById('refdesign-btn');
  btn.disabled = true;
  const placeholder = addMsg('tutor', 'thinking…');
  const textEl = placeholder.querySelector('.msg-text');
  try {
    const r = await api('/api/reference-design', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({question_id: current.id})
    });
    const res = await r.json();
    if (!r.ok || res.error) {
      placeholder.className += ' err';
      textEl.textContent = 'error: ' + (res.error || r.status);
    } else {
      textEl.textContent = '📐 Reference design:';
      const ul = document.createElement('ul');
      ul.style.cssText = 'margin:6px 0 0; padding-left:18px;';
      (res.bullets || []).forEach(b => {
        const li = document.createElement('li');
        li.textContent = b;
        ul.appendChild(li);
      });
      textEl.appendChild(ul);
      if ((res.diagram || []).length) {
        const diagBtn = document.createElement('button');
        diagBtn.className = 'btn btn-ghost';
        diagBtn.style.marginTop = '4px';
        diagBtn.textContent = '🗺 View as diagram';
        diagBtn.onclick = () => viewReferenceDiagram(res.diagram);
        textEl.appendChild(diagBtn);
      }
      btn.style.display = 'none';
    }
  } catch (e) {
    placeholder.className += ' err';
    textEl.textContent = 'error: ' + e.message;
  }
  btn.disabled = false;
}

// ponytail: reuses the box/arrow schema already fed to the LLM every turn (serializeCanvasForLLM),
// just parsed back in reverse, so renderCanvas() needs no changes to draw it.
let savedShapesBeforeDiagram = null;

function parseDiagramLines(lines) {
  const boxes = [], arrows = [];
  (lines || []).forEach(line => {
    let m = line.match(/^Box:\s*(.+?)(?:\s*\[(\w+)\])?$/);
    if (m) { boxes.push({label: m[1].trim(), layer: (m[2] || '').toLowerCase()}); return; }
    m = line.match(/^Arrow:\s*(.+?)\s*->\s*(.+?)(?:\s*\[(.+?)\])?$/);
    if (m) arrows.push({from: m[1].trim(), to: m[2].trim(), label: m[3] || ''});
  });
  const layerOrder = ['source', 'processing', 'storage', 'consumer', ''];
  const cols = {};
  layerOrder.forEach(l => cols[l] = []);
  boxes.forEach(b => (cols[b.layer] || cols['']).push(b));
  const colW = 190, boxW = 160, rowH = 80;
  const idByLabel = {};
  const out = [];
  let colIdx = 0;
  layerOrder.forEach(layer => {
    cols[layer].forEach((b, i) => {
      const id = newShapeId();
      idByLabel[b.label] = id;
      out.push({id, type: 'box', label: b.label, x: 30 + colIdx * colW, y: 30 + i * rowH, w: boxW, h: 50, layer: b.layer});
    });
    if (cols[layer].length) colIdx++;
  });
  arrows.forEach(a => {
    const fromId = idByLabel[a.from], toId = idByLabel[a.to];
    if (fromId && toId) out.push({id: newShapeId(), type: 'arrow', fromId, toId, label: a.label});
  });
  return out;
}

function viewReferenceDiagram(lines) {
  if (savedShapesBeforeDiagram === null) savedShapesBeforeDiagram = JSON.parse(JSON.stringify(shapes));
  shapes = parseDiagramLines(lines);
  selectedShapeId = null;
  document.getElementById('design-canvas-card').style.display = 'flex';
  renderCanvas();
  document.getElementById('diagram-restore-btn').style.display = '';
}

function restoreOwnDiagram() {
  if (savedShapesBeforeDiagram === null) return;
  shapes = savedShapesBeforeDiagram;
  savedShapesBeforeDiagram = null;
  selectedShapeId = null;
  renderCanvas();
  document.getElementById('diagram-restore-btn').style.display = 'none';
}

function startClarifyDrill() {
  clarifyMode = true;
  stopFrameworkMode();
  document.getElementById('design-canvas-card').style.display = 'none';
  document.getElementById('wrapup-btn').style.display = 'none';
  document.getElementById('clarify-btn').style.display = 'none';
  document.getElementById('end-drill-btn').style.display = '';
  addMsg('system', 'Clarify-only drill started');
  requestInterview({question_id: current.id, requirements_only: true, start: true});
  resetIdleTimer();
}

async function startAdversarialMode() {
  clearReqChips();
  stopFrameworkMode();
  const btn = document.getElementById('adversarial-btn');
  btn.disabled = true;
  btn.textContent = 'Loading flawed design…';
  try {
    const r = await api('/api/adversarial-design', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({question_id: current.id})
    });
    const res = await r.json();
    if (!r.ok || res.error) {
      btn.disabled = false;
      btn.textContent = '🧨 Break this design';
      addMsg('tutor', 'error: ' + (res.error || r.status));
      return;
    }
    adversarialMode = true;
    adversarialFlaws = res.flaws || [];
    shapes = parseDiagramLines(res.diagram);
    selectedShapeId = null;
    renderCanvas();
    document.getElementById('chatlog').innerHTML = '';
    document.getElementById('clarify-btn').style.display = 'none';
    document.getElementById('adversarial-btn').style.display = 'none';
    selectedPersona = '';
    renderPersonaPicker('Pick interviewer intensity for this drill:', ADVERSARIAL_PERSONA_OPTIONS, () => {
      addMsg('system', 'Adversarial drill started');
      requestInterview({question_id: current.id, start: true});
      resetIdleTimer();
    });
  } finally {
    btn.disabled = false;
    btn.textContent = '🧨 Break this design';
  }
}

async function startScalingMode() {
  clearReqChips();
  stopFrameworkMode();
  scalingMode = true;
  document.getElementById('chatlog').innerHTML = '';
  shapes = [];
  selectedShapeId = null;
  renderCanvas();
  document.getElementById('clarify-btn').style.display = 'none';
  document.getElementById('adversarial-btn').style.display = 'none';
  document.getElementById('scaling-btn').style.display = 'none';
  selectedPersona = '';
  renderPersonaPicker('Pick interviewer temperament:', PERSONA_OPTIONS, () => {
    addMsg('system', 'Scaling-pressure drill started — starting at 1K req/day');
    requestInterview({question_id: current.id, scaling: true, start: true});
    resetIdleTimer();
  });
}

async function startIncidentMode() {
  clearReqChips();
  stopFrameworkMode();
  const btn = document.getElementById('incident-btn');
  btn.disabled = true;
  btn.textContent = 'Generating failure scenario…';
  try {
    const r = await api('/api/incident-scenario', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({question_id: current.id})
    });
    const res = await r.json();
    if (!r.ok || res.error) {
      addMsg('tutor', 'error: ' + (res.error || r.status));
      btn.disabled = false;
      btn.textContent = '🔥 3am stress test';
      return;
    }
    incidentMode = true;
    incidentScenario = res.scenario || '';
    document.getElementById('chatlog').innerHTML = '';
    document.getElementById('design-canvas-card').style.display = 'none';
    document.getElementById('clarify-btn').style.display = 'none';
    document.getElementById('adversarial-btn').style.display = 'none';
    document.getElementById('incident-btn').style.display = 'none';
    document.getElementById('scaling-btn').style.display = 'none';
    document.getElementById('framework-btn').style.display = 'none';
    document.getElementById('refdesign-btn').style.display = 'none';
    document.getElementById('staffcomp-btn').style.display = 'none';
    addMsg('system', '🔥 3am stress test started — you\'ve been paged');
    requestInterview({question_id: current.id, incident: true, start: true});
    resetIdleTimer();
  } finally {
    btn.disabled = false;
    btn.textContent = '🔥 3am stress test';
  }
}

async function showStaffComparison() {
  const btn = document.getElementById('staffcomp-btn');
  btn.disabled = true;
  const placeholder = addMsg('tutor', 'thinking…');
  const textEl = placeholder.querySelector('.msg-text');
  try {
    const r = await api('/api/staff-comparison', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        question_id: current.id,
        adversarial: adversarialMode ? '1' : '0',
        scaling: scalingMode ? '1' : '0',
        incident: incidentMode ? '1' : '0'
      })
    });
    const res = await r.json();
    if (!r.ok || res.error) {
      placeholder.className += ' err';
      textEl.textContent = 'error: ' + (res.error || r.status);
    } else {
      textEl.textContent = '👤 Staff engineer comparison:';
      const comparisons = res.comparisons || [];
      if (!comparisons.length) {
        textEl.textContent = '👤 No clear deltas found — your answers were close to Staff-level on this one.';
      } else {
        const container = document.createElement('div');
        container.style.cssText = 'margin:6px 0 0; display:flex; flex-direction:column; gap:10px;';
        comparisons.forEach((c, i) => {
          const card = document.createElement('div');
          card.style.cssText = 'border:1px solid var(--border); border-radius:6px; padding:8px; background:var(--card-2);';
          card.innerHTML = `
            <div style="font-size:11px; font-weight:600; margin-bottom:4px;">${i+1}. ${c.delta}</div>
            <div style="font-size:11px; color:var(--text-dim); margin-bottom:3px;"><span style="color:#ef4444;">You said:</span> ${c.moment}</div>
            <div style="font-size:11px; color:var(--text-dim); margin-bottom:3px;"><span style="color:#22c55e;">Staff says:</span> ${c.staff_says}</div>
            <div style="font-size:10px; color:var(--text-dim); font-style:italic;">${c.why_it_matters}</div>`;
          container.appendChild(card);
        });
        textEl.appendChild(container);
      }
      btn.style.display = 'none';
    }
  } catch (e) {
    placeholder.className += ' err';
    textEl.textContent = 'error: ' + e.message;
  }
  btn.disabled = false;
}

function endClarifyDrill() {
  addMsg('system', 'Clarify-only drill ended');
  requestInterview({question_id: current.id, requirements_only: true, end_drill: true});
  clarifyMode = false;
  document.getElementById('design-canvas-card').style.display = 'flex';
  document.getElementById('wrapup-btn').style.display = '';
  document.getElementById('clarify-btn').style.display = '';
  document.getElementById('end-drill-btn').style.display = 'none';
  resetIdleTimer();
}

// ponytail: reuses parseDiagramLines (already built for reference-design + adversarial-mode)
// to redraw each snapshot — no new diagram rendering code needed.
async function startReplay() {
  const isDecomp = current && current.lang === 'decomposition';
  const r = await api(`/api/interview-history?question_id=${encodeURIComponent(current.id)}&adversarial=${adversarialMode ? '1' : '0'}&requirements_only=${clarifyMode ? '1' : '0'}&incident=${incidentMode ? '1' : '0'}&decomposition=${isDecomp ? '1' : '0'}`);
  const res = await r.json();
  replayTurns = res.turns || [];
  if (!replayTurns.length) {
    addMsg('tutor', 'Nothing to replay yet — have a few exchanges first.');
    return;
  }
  const cr = await api(`/api/replay-comments?question_id=${encodeURIComponent(current.id)}&adversarial=${adversarialMode ? '1' : '0'}&requirements_only=${clarifyMode ? '1' : '0'}&incident=${incidentMode ? '1' : '0'}&decomposition=${isDecomp ? '1' : '0'}`);
  replayComments = (await cr.json()).comments || [];
  window.speechSynthesis && window.speechSynthesis.cancel();
  clearPacingNudge();
  savedChatHTMLBeforeReplay = document.getElementById('chatlog').innerHTML;
  savedShapesBeforeReplay = JSON.parse(JSON.stringify(shapes));
  ['chatinput', 'wrapup-btn', 'clarify-btn', 'adversarial-btn', 'incident-btn', 'scaling-btn', 'framework-btn', 'refdesign-btn', 'staffcomp-btn', 'replay-btn', 'end-drill-btn'].forEach(id => {
    const el = document.getElementById(id);
    el.dataset.replayPrevDisplay = el.style.display;
    el.style.display = 'none';
  });
  const bar = document.getElementById('replay-bar');
  bar.style.display = 'flex';
  const slider = document.getElementById('replay-slider');
  slider.max = replayTurns.length - 1;
  slider.value = replayTurns.length - 1;
  scrubReplay(replayTurns.length - 1);
}

function scrubReplay(idx) {
  idx = Number(idx);
  document.getElementById('replay-turn-label').textContent = `${idx + 1} / ${replayTurns.length}`;
  const log = document.getElementById('chatlog');
  log.innerHTML = '';
  for (let i = 0; i <= idx; i++) addMsg(replayTurns[i].role === 'user' ? 'user' : 'tutor', replayTurns[i].text);
  log.scrollTop = log.scrollHeight;
  shapes = parseDiagramLines((replayTurns[idx].diagram || '').split('\n'));
  selectedShapeId = null;
  renderCanvas();
  renderReplayComments(idx);
}

function escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

async function startMockLoop() {
  if (!(await requireAuth())) return;
  try {
    const r = await api('/api/mock-loop/start');
    if (!r.ok) {
      showToast('Failed to start mock loop. Please try again.');
      return;
    }
    const res = await r.json();
    if (!res.ids || !res.ids.length) { showToast('Not enough questions across categories to start a mock interview.'); return; }
    mockLoop = {ids: res.ids, stage: 0};
    document.getElementById('mock-loop-bar').style.display = 'flex';
    updateMockLoopLabel();
    loadQuestion(mockLoop.ids[0]);
  } catch (e) {
    log('startMockLoop error:', e);
    showToast('Error starting mock loop: ' + (e.message || 'unknown error'));
  }
}

function updateMockLoopLabel() {
  document.getElementById('mock-loop-label').textContent = `🔁 Mock interview — stage ${mockLoop.stage + 1} / ${mockLoop.ids.length}`;
  document.getElementById('mock-loop-next').textContent = mockLoop.stage === mockLoop.ids.length - 1 ? 'Finish →' : 'Next stage →';
}

function mockLoopNext() {
  if (!mockLoop) return;
  if (mockLoop.stage < mockLoop.ids.length - 1) {
    mockLoop.stage++;
    updateMockLoopLabel();
    loadQuestion(mockLoop.ids[mockLoop.stage]);
  } else {
    finishMockLoop();
  }
}

function exitMockLoop() {
  document.getElementById('mock-loop-bar').style.display = 'none';
  mockLoop = null;
}

async function finishMockLoop() {
  const ids = mockLoop.ids;
  document.getElementById('mock-loop-bar').style.display = 'none';
  mockLoop = null;
  try {
    const r = await api('/api/mock-loop/report?ids=' + ids.join(','));
    if (!r.ok) {
      showToast('Failed to load mock report. Your progress has been saved.');
      return;
    }
    const res = await r.json();
    renderMockReport(res.report || []);
  } catch (e) {
    log('finishMockLoop error:', e);
    showToast('Error loading report: ' + (e.message || 'unknown error'));
  }
}

function renderMockReport(report) {
  const rows = report.map(r => {
    const ev = r.last_event;
    let detail = 'No attempt logged for this stage.';
    if (ev) {
      if (ev.event === 'submit') detail = ev.passed ? '✓ passed' : '✗ not passing yet';
      else if (ev.event === 'tradeoff') detail = ev.ok ? '✓ solid tradeoff call' : '✗ missed key points';
      else if (ev.event === 'design_debrief') {
        const missed = ev.missed_concepts || [];
        detail = missed.length
          ? `${missed.length} concept(s) to revisit: ${missed.map(c => c.replace(/_/g, ' ')).join(', ')}`
          : '✓ covered the key concepts';
      }
    }
    return `<div style="padding:8px 0; border-bottom:1px solid var(--border-soft);">
      <div style="font-weight:600; font-size:13px;">${escapeHtml(r.title)} <span style="color:var(--text-faint); font-weight:400;">(${escapeHtml(r.lang)})</span></div>
      <div style="font-size:12.5px; color:var(--text-dim); margin-top:2px;">${escapeHtml(detail)}</div>
    </div>`;
  }).join('');
  const overlay = document.createElement('div');
  overlay.className = 'confirm-overlay';
  overlay.innerHTML = `<div class="confirm-box" style="max-width:420px;">
    <div class="confirm-msg" style="font-weight:600;">🔁 Mock interview report</div>
    <div>${rows || '<div style="color:var(--text-faint); font-size:13px;">No stages to report.</div>'}</div>
    <div class="confirm-actions" style="margin-top:14px;"><button class="btn btn-primary" id="mock-report-close">Close</button></div>
  </div>`;
  overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
  overlay.querySelector('#mock-report-close').onclick = () => overlay.remove();
  document.body.appendChild(overlay);
}

function renderReplayComments(idx) {
  document.getElementById('replay-comments').style.display = '';
  const list = document.getElementById('replay-comments-list');
  const here = replayComments.filter(c => c.turn_idx === idx);
  list.innerHTML = here.length
    ? here.map(c => `<div><b>${escapeHtml(c.author)}</b> <span style="color:var(--text-faint);">on turn ${idx + 1}:</span> ${escapeHtml(c.text)}</div>`).join('')
    : '<div style="color:var(--text-faint);">No comments on this turn yet.</div>';
}

async function postReplayComment() {
  const textEl = document.getElementById('replay-comment-text');
  const text = textEl.value.trim();
  if (!text) return;
  const author = document.getElementById('replay-comment-author').value.trim();
  const idx = Number(document.getElementById('replay-slider').value);
  const res = await (await api('/api/replay-comment', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      question_id: current.id, adversarial: adversarialMode ? '1' : '0', requirements_only: clarifyMode ? '1' : '0', incident: incidentMode ? '1' : '0',
      turn_idx: idx, author, text
    })
  })).json();
  if (res.error) { showToast('Could not post comment: ' + res.error); return; }
  replayComments.push(res.comment);
  textEl.value = '';
  renderReplayComments(idx);
}

function exitReplay() {
  document.getElementById('replay-bar').style.display = 'none';
  document.getElementById('replay-comments').style.display = 'none';
  ['chatinput', 'wrapup-btn', 'clarify-btn', 'adversarial-btn', 'incident-btn', 'scaling-btn', 'framework-btn', 'refdesign-btn', 'staffcomp-btn', 'replay-btn', 'end-drill-btn'].forEach(id => {
    const el = document.getElementById(id);
    el.style.display = el.dataset.replayPrevDisplay || '';
  });
  if (savedChatHTMLBeforeReplay !== null) document.getElementById('chatlog').innerHTML = savedChatHTMLBeforeReplay;
  if (savedShapesBeforeReplay !== null) shapes = savedShapesBeforeReplay;
  savedChatHTMLBeforeReplay = null;
  savedShapesBeforeReplay = null;
  selectedShapeId = null;
  renderCanvas();
  if (document.getElementById('wrapup-btn').style.display !== 'none') armPacingNudge();
}

function copyReplayLink() {
  const params = new URLSearchParams({
    q: current.id,
    replay: '1',
    adversarial: adversarialMode ? '1' : '0',
    requirements_only: clarifyMode ? '1' : '0',
    incident: incidentMode ? '1' : '0',
  });
  const url = `${location.origin}${location.pathname}?${params.toString()}`;
  navigator.clipboard.writeText(url).then(
    () => showToast('Replay link copied — anyone with it can watch this session.'),
    () => showToast('Could not copy link: ' + url)
  );
}

function isDesignQuestion() {
  return !!current && current.lang === 'design';
}

// ponytail: ambient TTS so the candidate doesn't have to glance off the whiteboard to read replies
let _ttsAudio = null;

function speakTutor(text) {
  if (!ttsEnabled || !text) return;
  if (_ttsAudio) { _ttsAudio.pause(); _ttsAudio = null; }
  const clean = text.replace(/[*_`#]/g, '').replace(/```[\s\S]*?```/g, '');
  api('/api/tts', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({text: clean})
  })
    .then(r => { if (!r.ok) throw Error(); return r.blob(); })
    .then(blob => {
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      _ttsAudio = audio;
      audio.onended = () => { URL.revokeObjectURL(url); _ttsAudio = null; };
      audio.play().catch(() => {});
    })
    .catch(() => {});
}

function toggleTTS() {
  ttsEnabled = !ttsEnabled;
  document.getElementById('tts-toggle-btn').textContent = ttsEnabled ? '🔊' : '🔇';
  if (!ttsEnabled) window.speechSynthesis && window.speechSynthesis.cancel();
}

function toggleChatCollapse() {
  const panel = document.getElementById('chatpanel');
  const btn = document.getElementById('chat-collapse-btn');
  if (panel.classList.contains('collapsed')) {
    panel.classList.remove('collapsed');
    panel.style.width = panel.dataset.prevWidth || '360px';
    btn.textContent = '»';
    btn.title = 'Collapse chat, focus canvas';
  } else {
    panel.dataset.prevWidth = panel.style.width || '360px';
    panel.classList.add('collapsed');
    btn.textContent = '«';
    btn.title = 'Expand chat';
  }
}

// ponytail: naive "sentences with a number in them" heuristic, not an LLM call —
// upgrade to a classified extraction if it starts missing real constraints.
function extractChips(text) {
  const sentences = text.match(/[^.?!]*\d[^.?!]*[.?!]/g) || [];
  const strip = document.getElementById('req-chips');
  sentences.forEach(s => {
    const clean = s.trim();
    if (!clean || designChips.some(c => c.toLowerCase() === clean.toLowerCase())) return;
    designChips.push(clean);
    if (designChips.length > 10) designChips.shift();
    const chip = document.createElement('div');
    chip.className = 'req-chip';
    chip.textContent = clean;
    chip.title = clean;
    strip.appendChild(chip);
    while (strip.children.length > 10) strip.removeChild(strip.firstChild);
  });
}

function clearReqChips() {
  designChips = [];
  document.getElementById('req-chips').innerHTML = '';
}

function armPacingNudge() {
  clearTimeout(pacingTimer);
  document.getElementById('pacing-hud').style.display = 'none';
  if (!isDesignQuestion() || clarifyMode) return;
  pacingTimer = setTimeout(() => {
    document.getElementById('pacing-hud').textContent = '🕑 Quiet for a bit — try narrating your thinking out loud.';
    document.getElementById('pacing-hud').style.display = '';
  }, 45000);
}

function clearPacingNudge() {
  clearTimeout(pacingTimer);
  document.getElementById('pacing-hud').style.display = 'none';
}

// ponytail: coach-only checkpoints, not an enforced timer — nudges phase transitions via
// system messages, never blocks input or force-submits anything.
const FRAMEWORK_PHASES = [
  ['Requirements', 5 * 60], ['Scale estimate', 5 * 60], ['High-level design', 15 * 60],
  ['Deep dive', 15 * 60], ['Wrap-up', 5 * 60],
];
let frameworkMode = false;
let frameworkPhaseIdx = 0;
let frameworkPhaseEndsAt = 0;
let frameworkTicker = null;

function toggleFrameworkMode() {
  if (frameworkMode) { stopFrameworkMode(); return; }
  frameworkMode = true;
  frameworkPhaseIdx = 0;
  frameworkPhaseEndsAt = Date.now() + FRAMEWORK_PHASES[0][1] * 1000;
  document.getElementById('framework-btn').textContent = '⏱ Framework mode (on)';
  addMsg('system', `Framework mode on — ${FRAMEWORK_PHASES.map(p => p[0]).join(' → ')}`);
  frameworkTicker = setInterval(frameworkTick, 1000);
  frameworkTick();
}

function stopFrameworkMode() {
  frameworkMode = false;
  clearInterval(frameworkTicker);
  frameworkTicker = null;
  document.getElementById('framework-hud').style.display = 'none';
  const btn = document.getElementById('framework-btn');
  if (btn) btn.textContent = '⏱ Framework mode';
}

function frameworkTick() {
  const remaining = Math.round((frameworkPhaseEndsAt - Date.now()) / 1000);
  if (remaining <= 0) {
    frameworkPhaseIdx++;
    if (frameworkPhaseIdx >= FRAMEWORK_PHASES.length) {
      addMsg('system', "⏱ Time's up — wrap up when ready");
      stopFrameworkMode();
      return;
    }
    addMsg('system', `⏱ ${FRAMEWORK_PHASES[frameworkPhaseIdx - 1][0]} done — move to ${FRAMEWORK_PHASES[frameworkPhaseIdx][0]}`);
    frameworkPhaseEndsAt = Date.now() + FRAMEWORK_PHASES[frameworkPhaseIdx][1] * 1000;
  }
  const [name] = FRAMEWORK_PHASES[frameworkPhaseIdx];
  const mm = String(Math.floor(Math.max(0, remaining) / 60)).padStart(2, '0');
  const ss = String(Math.max(0, remaining) % 60).padStart(2, '0');
  const hud = document.getElementById('framework-hud');
  hud.textContent = `⏱ ${name} — ${mm}:${ss}`;
  hud.style.display = '';
}

const tutorFab = document.createElement('div');
tutorFab.id = 'tutor-fab';
tutorFab.title = 'Ask the tutor';
tutorFab.innerHTML = '<svg class="fab-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="4" y1="12" x2="18" y2="12"></line><polyline points="12 6 18 12 12 18"></polyline></svg><span id="fab-badge"></span>';
document.body.appendChild(tutorFab);

const fabBubble = document.createElement('div');
fabBubble.id = 'fab-bubble';
document.body.appendChild(fabBubble);

function positionFab() {
  const panelLeft = document.getElementById('chatpanel').getBoundingClientRect().left;
  tutorFab.style.right = (window.innerWidth - panelLeft + 12) + 'px';
}
positionFab();
window.addEventListener('resize', positionFab);

function fabSay(text, ms) {
  fabBubble.textContent = text;
  const r = tutorFab.getBoundingClientRect();
  fabBubble.style.left = Math.max(8, r.left - 80) + 'px';
  fabBubble.style.top = Math.max(8, r.top - 38) + 'px';
  fabBubble.classList.add('show');
  clearTimeout(fabSay._t);
  fabSay._t = setTimeout(() => fabBubble.classList.remove('show'), ms || 2200);
}

function fabAlert(text) {
  tutorFab.classList.add('alert');
  fabSay(text, 5000);
}

tutorFab.addEventListener('click', () => {
  tutorFab.classList.remove('alert');
  if (!current) { fabSay('Pick a question first!', 2000); return; }
  fabSay('One sec — let me look…', 1400);
  askHint();
});

const resizer = document.getElementById('resizer');
const chatpanel = document.getElementById('chatpanel');
let resizing = false;

resizer.addEventListener('mousedown', () => {
  resizing = true;
  resizer.classList.add('dragging');
  document.body.style.userSelect = 'none';
  document.body.style.cursor = 'col-resize';
});

window.addEventListener('mousemove', (e) => {
  if (!resizing) return;
  const newWidth = window.innerWidth - e.clientX;
  chatpanel.style.width = Math.min(640, Math.max(240, newWidth)) + 'px';
  positionFab();
});

window.addEventListener('mouseup', () => {
  if (!resizing) return;
  resizing = false;
  resizer.classList.remove('dragging');
  document.body.style.userSelect = '';
  document.body.style.cursor = '';
});

const sidebarResizer = document.getElementById('sidebar-resizer');
const sidebar = document.getElementById('sidebar');
let sidebarResizing = false;

sidebarResizer.addEventListener('mousedown', () => {
  sidebarResizing = true;
  sidebarResizer.classList.add('dragging');
  document.body.style.userSelect = 'none';
  document.body.style.cursor = 'col-resize';
});

window.addEventListener('mousemove', (e) => {
  if (!sidebarResizing) return;
  const newWidth = e.clientX - sidebar.getBoundingClientRect().left;
  sidebar.style.width = Math.min(420, Math.max(160, newWidth)) + 'px';
});

window.addEventListener('mouseup', () => {
  if (!sidebarResizing) return;
  sidebarResizing = false;
  sidebarResizer.classList.remove('dragging');
  document.body.style.userSelect = '';
  document.body.style.cursor = '';
});

loadList();
loadDeadline();
refreshStreak();
refreshProgress();

function refreshStreak() {
  api('/api/streak').then(r => r.json()).then(s => {
    document.getElementById('streak-count').textContent = s.streak || 0;
  }).catch(() => {});
}

function refreshProgress() {
  api('/api/progress').then(r => r.json()).then(p => {
    document.getElementById('readiness-percent').textContent = p.overall_readiness || 0;
    const masteredCount = (p.concept_mastery || []).filter(c => c.percentage >= 60).length;
    document.getElementById('concepts-count').textContent = masteredCount + '/' + (p.concept_mastery ? p.concept_mastery.length : 0);
    if (p.total_solved > 0) {
      document.getElementById('progress-panel').style.display = 'block';
    }
  }).catch(() => {});
}

document.getElementById('q-search').addEventListener('input', applySidebarFilter);

/* ── auth overlay logic ── */
let authMode = 'login'; // 'login' | 'signup'
const authOverlay = document.getElementById('auth-overlay');
const authTitle = document.getElementById('auth-title');
const authError = document.getElementById('auth-error');
const authSubmitBtn = document.getElementById('auth-submit');
const authToggleText = document.getElementById('auth-toggle-text');
const authToggleLink = document.getElementById('auth-toggle-link');
const authEmail = document.getElementById('auth-email');
const authPassword = document.getElementById('auth-password');

function authToggle() {
  authMode = authMode === 'login' ? 'signup' : 'login';
  authError.classList.remove('show');
  if (authMode === 'signup') {
    authTitle.textContent = 'Create account';
    authSubmitBtn.textContent = 'Sign up';
    authToggleText.textContent = 'Have an account?';
    authToggleLink.textContent = 'Log in';
  } else {
    authTitle.textContent = 'Welcome back';
    authSubmitBtn.textContent = 'Log in';
    authToggleText.textContent = 'No account?';
    authToggleLink.textContent = 'Sign up';
  }
  authEmail.focus();
}

function authShowError(msg) {
  authError.textContent = msg;
  authError.classList.add('show');
}

async function authSubmit() {
  const email = authEmail.value.trim();
  const password = authPassword.value;
  if (!email || !password) { authShowError('Email and password required.'); return; }
  authSubmitBtn.disabled = true;
  authError.classList.remove('show');
  try {
    const endpoint = authMode === 'signup' ? '/api/signup' : '/api/login';
    const r = await api(endpoint, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({email, password}),
    });
    const data = await r.json();
    if (r.status === 404) {
      authShowError('Sign-up is not enabled yet.');
      return;
    }
    if (!r.ok || data.error) {
      authShowError(data.error || 'Something went wrong.');
      return;
    }
    if (data.access_token) {
      localStorage.setItem('loop_token', data.access_token);
    }
    hideAuthOverlay();
  } catch (e) {
    authShowError('Network error — try again.');
  } finally {
    authSubmitBtn.disabled = false;
  }
}

async function testLogin(fresh) {
  authSubmitBtn.disabled = true;
  authError.classList.remove('show');
  try {
    const r = await api('/api/test-login' + (fresh ? '?fresh=1' : ''), {method: 'POST'});
    const data = await r.json();
    if (!r.ok || data.error) { authShowError(data.error || 'Test login failed.'); authSubmitBtn.disabled = false; return; }
    if (data.access_token) localStorage.setItem('loop_token', data.access_token);
    hideAuthOverlay();
    // Reload so checkAuth re-runs and the session is reflected (banner hides,
    // /api/me shows the test user instead of staying anonymous).
    setTimeout(() => location.reload(), 500);
  } catch (e) { authShowError('Network error — try again.'); authSubmitBtn.disabled = false; }
}

// Enter key submits
document.getElementById('auth-password').addEventListener('keydown', e => { if (e.key === 'Enter') authSubmit(); });
document.getElementById('auth-email').addEventListener('keydown', e => { if (e.key === 'Enter') document.getElementById('auth-password').focus(); });

// Overlay is hidden by default (CSS). Only SHOW it when auth is genuinely required —
// this prevents the login screen from flashing on every page load.
function showAuthBanner() {
  const b = document.getElementById('auth-banner');
  if (b) b.classList.add('show');
}
// Gate a persist-bound action: return true if caller may proceed (valid session).
async function requireAuth(reason) {
  const token = localStorage.getItem('loop_token');
  if (token) {
    try {
      const r = await api('/api/me', { headers: { 'Authorization': 'Bearer ' + token } });
      const data = await r.json();
      if (data.user_id) return true;
    } catch (e) {}
  }
  showAuthOverlay(reason);
  return false;
}
// Intercept a start/persist navigation: proceed only with a session.
async function gateStart(e) {
  if (await requireAuth()) return true;
  e.preventDefault();
  return false;
}
function showAuthOverlay(reason) {
  const r = document.getElementById('auth-reason');
  if (r) { if (reason) { r.textContent = reason; r.style.display = ''; } else { r.style.display = 'none'; } }
  authOverlay.classList.remove('hidden');
  authOverlay.classList.add('show');
  authOverlay.style.display = 'flex';
  authEmail.focus();
}

function hideAuthOverlay() {
  authOverlay.classList.remove('show');
  authOverlay.classList.add('hidden');
  authOverlay.style.display = 'none';
}

(async function checkAuth() {
  try {
    const r = await api('/api/me');
    const data = await r.json();
    if (data.mode === 'legacy') return; // legacy: never show overlay
  } catch { /* Supabase unreachable — fall through to token check */ }

  const token = localStorage.getItem('loop_token');
  if (!token) { showAuthBanner(); return; }
  try {
    const r2 = await api('/api/me', { headers: {'Authorization': 'Bearer ' + token} });
    const data2 = await r2.json();
    if (data2.user_id) {
      // valid session — keep overlay hidden
    } else {
      localStorage.removeItem('loop_token');
      showAuthOverlay();
    }
  } catch { showAuthOverlay(); }
})();

async function loadDeadline() {
  const r = await api('/api/deadline');
  const d = await r.json();
  renderDeadlineWidget(d.deadline);
}

function renderDeadlineWidget(deadline) {
  const el = document.getElementById('deadline-widget');
  el.dataset.deadline = deadline || '';
  if (!deadline) { el.textContent = '🗓 Set interview date'; return; }
  const days = Math.ceil((new Date(deadline + 'T00:00:00') - new Date()) / 86400000);
  el.textContent = days > 0 ? `🗓 Interview in ${days}d — reviews compressed` : '🗓 Interview date passed';
}

async function setInterviewDeadline() {
  if (!(await requireAuth('Sign up free to save your interview date.'))) return;
  const input = prompt('Interview date (YYYY-MM-DD), blank to clear:', document.getElementById('deadline-widget').dataset.deadline || '');
  if (input === null) return;
  const r = await api('/api/deadline', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({deadline: input.trim()})});
  const d = await r.json();
  renderDeadlineWidget(d.deadline);
}

