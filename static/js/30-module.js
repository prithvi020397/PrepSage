// 30-module.js — lines 455-890 of original bundle. Key fns: liveTargetField, toggleDrillsMenu, resetCurrentQuestion, toggleCanvasVoiceNote, dropCanvasVoiceNote, startRecording
// Live, zero-cost speech recognition via webkitSpeechRecognition — replaced with
// Deepgram-based recording + /api/transcribe for higher accuracy. Records audio on
// mic toggle, sends to server for transcription, inserts result into active field.
let micOn = false; // off by default (user clicks to record)
let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;
let recTimer = null; // interval id for the visible recording timer
let recSeconds = 0;
const REC_MAX_SECONDS = 90; // auto-stop so audio never piles up silently

function liveTargetField() {
  if (current && current.lang === 'design') return document.getElementById('chatbox');
  const narr = document.getElementById('narration-input');
  if (narr && narr.offsetParent !== null) return narr;
  if (canvasVoiceNote && current && current.lang === 'design') return 'CANVAS_NOTE';
  return document.getElementById('chatbox');
}

let canvasVoiceNote = false;
function toggleDrillsMenu() {
  const menu = document.getElementById('drills-menu');
  const btn = document.getElementById('more-drills-btn');
  const open = menu.classList.toggle('open');
  btn.classList.toggle('active', open);
}

async function resetCurrentQuestion() {
  if (!current) return;
  if (!confirm(`Reset "${current.title}"? This clears your saved code, trace, and notes for this question. Your solved status is kept.`)) return;
  const btn = document.querySelector('.dm-item.dm-danger');
  const old = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = 'Resetting…';
  try {
    const r = await api(`/api/reset-question/${current.id}`, {method: 'POST'});
    if (!r.ok) throw new Error('reset failed');
    delete stateCache[current.id];
    await loadQuestion(current.id, true);
    showToast('Question reset — fresh starter code loaded.');
  } catch (e) {
    showToast('Could not reset question.');
  } finally {
    btn.disabled = false;
    btn.innerHTML = old;
  }
}

document.addEventListener('click', (e) => {
  const wrap = document.querySelector('.more-drills-wrap');
  if (wrap && !wrap.contains(e.target)) {
    document.getElementById('drills-menu').classList.remove('open');
    document.getElementById('more-drills-btn').classList.remove('active');
  }
});

function toggleCanvasVoiceNote() {
  canvasVoiceNote = !canvasVoiceNote;
  const btn = document.getElementById('tool-mic');
  btn.classList.toggle('active', canvasVoiceNote);
  if (canvasVoiceNote && !micOn) setMicOn(true);
  showToast(canvasVoiceNote ? 'Voice note on — speak, it drops onto the canvas. Click again to stop.' : 'Voice note off.');
}

function dropCanvasVoiceNote(text) {
  if (!text) return;
  const cx = (lastCanvasClick && lastCanvasClick.x ? lastCanvasClick.x : 200) - 70;
  const cy = (lastCanvasClick && lastCanvasClick.y ? lastCanvasClick.y : 150) - 20;
  shapes.push({id: newShapeId(), type: 'text', label: text, x: cx, y: cy, w: 140, h: 40});
  renderCanvas();
  saveCurrentState();
}

function startRecording() {
  log("recording: start");
  navigator.mediaDevices.getUserMedia({ audio: true }).then(stream => {
    const mime = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : 'audio/webm';
    mediaRecorder = new MediaRecorder(stream, { mimeType: mime });
    audioChunks = [];
    mediaRecorder.ondataavailable = e => e.data.size && audioChunks.push(e.data);
    mediaRecorder.onstop = async () => {
      stream.getTracks().forEach(t => t.stop());
      const blob = new Blob(audioChunks, { type: mime });
      const formData = new FormData();
      formData.append('audio', blob, 'recording.webm');
      const indicator = document.getElementById('live-transcript');
      if (indicator) { indicator.textContent = '⏳ Transcribing…'; indicator.classList.remove('active'); }
      try {
        const res = await api('/api/transcribe', { method: 'POST', body: formData });
        const data = await res.json();
        if (indicator) indicator.textContent = '';
        if (data.transcript) {
          const field = liveTargetField();
          if (field === 'CANVAS_NOTE') {
            dropCanvasVoiceNote(data.transcript.trim());
          } else {
            const cur = field.value;
            field.value = (cur ? cur + ' ' : '') + data.transcript.trim();
            field.dispatchEvent(new Event('input'));
            field.focus();
          }
        } else if (data.error) {
          showToast('Transcription failed: ' + data.error);
        }
      } catch (e) {
        if (indicator) indicator.textContent = '';
        showToast('Transcription failed. Check Deepgram API key.');
      }
    };
    mediaRecorder.start();
    isRecording = true;
    recSeconds = 0;
    const indicator = document.getElementById('live-transcript');
    const tick = () => {
      recSeconds += 1;
      if (indicator) indicator.textContent = `🔴 Recording… ${recSeconds}s (click Mic to stop, auto-stops at ${REC_MAX_SECONDS}s)`;
      if (recSeconds >= REC_MAX_SECONDS) {
        showToast('Max recording length reached — transcribing now.');
        setMicOn(false);
      }
    };
    if (indicator) indicator.classList.add('active');
    tick();
    recTimer = setInterval(tick, 1000);
  }).catch(() => {
    showToast('Microphone access needed — type instead.');
    setMicOn(false);
  });
}

function stopRecording() {
  if (recTimer) { clearInterval(recTimer); recTimer = null; }
  if (mediaRecorder && mediaRecorder.state !== 'inactive') {
    mediaRecorder.stop();
    isRecording = false;
  }
}

function setMicOn(on) {
  log("mic:", on ? "on" : "off");
  micOn = on;
  const toggle = document.getElementById('mic-toggle');
  if (toggle) {
    toggle.classList.toggle('on', on);
    document.getElementById('mic-toggle-label').textContent = on ? 'Recording…' : 'Record';
  }
  if (on) {
    startRecording();
  } else {
    stopRecording();
  }
}

document.getElementById('mic-toggle').addEventListener('click', () => setMicOn(!micOn));

const LAYER_CYCLE = ['', 'source', 'processing', 'storage', 'consumer'];
function duplicateSelected() {
  const shape = shapes.find(s => s.id === selectedShapeId);
  if (!shape || shape.type === 'arrow') return;
  const clone = {...shape, id: newShapeId(), x: shape.x + 20, y: shape.y + 20};
  shapes.push(clone);
  selectedShapeId = clone.id;
  renderCanvas();
  saveCurrentState();
}
function cycleLayer() {
  const shape = shapes.find(s => s.id === selectedShapeId);
  if (!shape || shape.type !== 'box') return;
  shape.layer = LAYER_CYCLE[(LAYER_CYCLE.indexOf(shape.layer || '') + 1) % LAYER_CYCLE.length];
  renderCanvas();
  saveCurrentState();
}

document.addEventListener('keydown', (e) => {
  if (!(current && current.lang === 'design' && selectedShapeId
      && !['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName))) return;
  if (e.key === 'Delete' || e.key === 'Backspace') {
    e.preventDefault();
    deleteSelected();
  } else if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'd') {
    e.preventDefault();
    duplicateSelected();
  } else if (e.key.toLowerCase() === 'l' && !e.metaKey && !e.ctrlKey) {
    e.preventDefault();
    cycleLayer();
  }
});

function formatTime(s) {
  return String(Math.floor(s / 60)).padStart(2, '0') + ':' + String(s % 60).padStart(2, '0');
}

function isSolved(id) {
  const item = document.querySelector(`.q-item[data-id="${id}"]`);
  return !!(item && item.classList.contains('solved'));
}

function updateTimerDisplay() {
  if (!current) return;
  const t = timers[current.id];
  const el = document.getElementById('q-timer');
  el.textContent = formatTime(t.elapsed);
  el.className = t.running ? '' : 'stopped';
}

function startTimerFor(id) {
  clearInterval(timerInterval);
  if (!timers[id]) timers[id] = {elapsed: 0, running: true};
  if (isSolved(id)) timers[id].running = false;
  updateTimerDisplay();
  if (timers[id].running) {
    timerInterval = setInterval(() => {
      timers[id].elapsed++;
      updateTimerDisplay();
    }, 1000);
  }
}

function stopTimer(id) {
  if (timers[id]) timers[id].running = false;
  clearInterval(timerInterval);
  updateTimerDisplay();
}

function renderConceptBox(q, solved) {
  const box = document.getElementById('concept-box');
  box.style.display = 'block';
  box.className = 'concept-box ' + (solved ? 'revealed' : 'locked');
  box.innerHTML = '';
  const label = document.createElement('div');
  label.className = 'concept-label';
  label.textContent = solved ? '💡 Key idea' : '🔒 Key idea';
  const text = document.createElement('div');
  text.className = 'concept-text';
  text.textContent = solved ? q.concept : 'Solve this to reveal the underlying pattern and the common trap.';
  box.appendChild(label);
  box.appendChild(text);
}

let planApproved = false;

function saveCurrentState() {
  if (!current) return;
  stateCache[current.id] = {
    code: cm.getValue(),
    lang: current && current.lang,
    chatHTML: document.getElementById('chatlog').innerHTML,
    resultsHTML: document.getElementById('results').innerHTML,
    resultsClass: document.getElementById('results').className,
    lastRunSummary, stuck, nudgeSent, reinforced,
    plan: document.getElementById('plan-input').value,
    approved: planApproved,
    feedbackHTML: document.getElementById('plan-feedback').outerHTML,
    complexityInput: document.getElementById('complexity-input').value,
    edgeInput: document.getElementById('edge-input').value,
    debriefFeedbackHTML: document.getElementById('debrief-feedback').outerHTML,
    shapes: JSON.parse(JSON.stringify(shapes)),
    persona: selectedPersona,
    scaling: scalingMode,
    tradeoffInput: document.getElementById('tradeoff-input').value,
    tradeoffFeedbackHTML: document.getElementById('tradeoff-feedback').outerHTML,
  };
}

function onPlanInput() {
  document.getElementById('check-approach-btn').disabled = document.getElementById('plan-input').value.trim().length === 0;
}

function setEditorLocked(locked) {
  cm.setOption('readOnly', locked);
  cm.getWrapperElement().classList.toggle('locked', locked);
  document.getElementById('run-btn').disabled = locked;
  document.getElementById('submit-btn').disabled = locked;
}

function setPlanFeedback(kind, text) {
  const el = document.getElementById('plan-feedback');
  el.className = kind;
  el.textContent = text;
}

async function checkApproach() {
  const btn = document.getElementById('check-approach-btn');
  const plan = document.getElementById('plan-input').value;
  btn.disabled = true;
  setPlanFeedback('pending', 'Checking your approach…');
  const res = await (await api('/api/check-approach', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({question_id: current.id, plan})
  })).json();
  btn.disabled = false;
  setPlanFeedback(res.ok ? 'ok' : 'bad', (res.ok ? '✓ ' : '✗ ') + res.feedback);
  if (res.ok) {
    planApproved = true;
    setEditorLocked(false);
  }
}

let spotBugNote = null;

async function startSpotBug() {
  const btn = document.getElementById('spotbug-menu');
  btn.disabled = true;
  btn.innerHTML = '<svg class="icon" viewBox="0 0 24 24"><use href="#i-bug"/></svg>Loading…';
  const res = await (await api('/api/spot-bug', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({question_id: current.id})
  })).json();
  btn.disabled = false;
  btn.innerHTML = '<svg class="icon" viewBox="0 0 24 24"><use href="#i-bug"/></svg>Spot the bug';
  if (res.error) { showToast('Could not generate a code-review drill: ' + res.error); return; }
  spotBugNote = res.bug_note;
  document.getElementById('spotbug-code').textContent = res.code;
  document.getElementById('spotbug-input').value = '';
  document.getElementById('spotbug-feedback').textContent = '';
  document.getElementById('spotbug-card').style.display = 'block';
}

function closeSpotBug() {
  document.getElementById('spotbug-card').style.display = 'none';
  spotBugNote = null;
}

async function gradeSpotBug() {
  const answer = document.getElementById('spotbug-input').value.trim();
  if (!answer || !spotBugNote) return;
  const btn = document.getElementById('spotbug-grade-btn');
  const el = document.getElementById('spotbug-feedback');
  btn.disabled = true;
  el.className = 'pending';
  el.textContent = 'Grading…';
  const res = await (await api('/api/spot-bug-grade', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({question_id: current.id, bug_note: spotBugNote, answer})
  })).json();
  btn.disabled = false;
  el.className = res.ok ? 'ok' : 'bad';
  el.textContent = (res.ok ? '✓ ' : '✗ ') + res.feedback;
}

let reverseState = null;

async function startReverse() {
  const btn = document.getElementById('reverse-menu');
  btn.disabled = true;
  btn.innerHTML = '<svg class="icon" viewBox="0 0 24 24"><use href="#i-mask"/></svg>Loading…';
  const res = await (await api('/api/reverse', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body:JSON.stringify({question_id: current.id})
  })).json();
  btn.disabled = false;
  btn.innerHTML = '<svg class="icon" viewBox="0 0 24 24"><use href="#i-mask"/></svg>Be the interviewer';
  if (res.error) { showToast('Could not start reverse interview: ' + res.error); return; }
  reverseState = {qid: current.id};
  const panel = document.getElementById('reversal-panel');
  panel.style.display = 'block';
  document.getElementById('reversal-code').textContent = res.code;
  document.getElementById('reversal-input').value = '';
  document.getElementById('reversal-chat').innerHTML = '';
  renderBugs(res.bugs || []);
  addRevChat('candidate', res.reply);
}

function closeReverse() {
  document.getElementById('reversal-panel').style.display = 'none';
  reverseState = null;
}

function renderBugs(bugs) {
  const el = document.getElementById('reversal-bugs');
  el.innerHTML = '<div style="font-weight:600; color:var(--text-dim); margin-bottom:4px; font-size:11px;">🐞 Bugs to find</div>';
  bugs.forEach((b, i) => {
    const d = document.createElement('div');
    d.className = 'rev-bug-item' + (b.found ? ' found' : '');
    d.innerHTML = `<span class="rev-bug-icon">${b.found ? '✅' : '⬜'}</span><span>${b.found ? 'Found:' : 'Hidden:'} ${b.note}</span>`;
    el.appendChild(d);
  });
}

function addRevChat(who, text) {
  const el = document.getElementById('reversal-chat');
  const d = document.createElement('div');
  d.className = 'rev-chat-bubble ' + who;
  d.textContent = text;
  el.appendChild(d);
  el.scrollTop = el.scrollHeight;
}

async function sendReverse() {
  const input = document.getElementById('reversal-input');
  const text = input.value.trim();
  if (!text || !reverseState) return;
  input.value = '';
  addRevChat('user', text);
  const res = await (await api('/api/reverse', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body:JSON.stringify({question_id: reverseState.qid, message: text})
  })).json();
  if (res.error) { addRevChat('candidate', 'Error: ' + res.error); return; }
  addRevChat('candidate', res.reply);
  renderBugs(res.bugs || []);
}

let curveballActive = false;
let useWebAngle = false;  // HYBRID: when on, hints & curveballs request a Firecrawl-grounded real-world angle

async function startCurveball() {
  const btn = document.getElementById('curveball-menu');
  btn.disabled = true;
  btn.innerHTML = '<svg class="icon" viewBox="0 0 24 24"><use href="#i-zap"/></svg>Loading…';
  const res = await (await api('/api/curveball', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({question_id: current.id, use_web: useWebAngle})
  })).json();
  btn.disabled = false;
  btn.innerHTML = '<svg class="icon" viewBox="0 0 24 24"><use href="#i-zap"/></svg>Curveball';
  if (res.error) { showToast('Could not generate a curveball: ' + res.error); return; }
  curveballActive = true;
  document.getElementById('curveball-twist').textContent = '🌀 Interviewer: ' + res.twist;
  document.getElementById('curveball-feedback').textContent = '';
  document.getElementById('curveball-card').style.display = 'block';
  addMsg('system', 'Interviewer changed the requirements mid-solve');
}

function closeCurveball() {
  document.getElementById('curveball-card').style.display = 'none';
  curveballActive = false;
}

function toggleWebAngle() {
  useWebAngle = !useWebAngle;
  const label = document.getElementById('webtoggle-label');
  if (label) label.textContent = useWebAngle ? 'On' : 'Off';
  showToast(useWebAngle
    ? 'Web angle ON — hints & curveballs will pull a real-world framing (falls back silently if offline).'
    : 'Web angle OFF — using the precomputed bank.');
}

