// 40-module.js — lines 890-935 of original bundle. Key fns: requestFreshAngle, gradeCurveball
async function requestFreshAngle() {
  if (!current) { showToast('Open a question first.'); return; }
  const btn = document.getElementById('webangle-menu');
  const prev = btn.innerHTML;
  btn.innerHTML = '<svg class="icon" viewBox="0 0 24 24"><use href="#i-grid"/></svg>Fetching…';
  const placeholder = addMsg('tutor', 'pulling a real-world angle from the web…');
  const textEl = placeholder.querySelector('.msg-text');
  try {
    const r = await api('/api/fresh-angle', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({question_id: current.id})
    });
    const res = await r.json();
    if (!r.ok || !res.angle) {
      placeholder.className += ' err';
      textEl.textContent = 'No live angle available right now — using the precomputed framing instead.';
    } else {
      textEl.textContent = '🌐 Real-world angle: ' + res.angle;
    }
  } catch (e) {
    placeholder.className += ' err';
    textEl.textContent = 'Could not reach the web layer — using the precomputed framing instead.';
  } finally {
    btn.innerHTML = prev;
  }
}

async function gradeCurveball() {
  if (!curveballActive) return;
  const btn = document.getElementById('curveball-grade-btn');
  const el = document.getElementById('curveball-feedback');
  btn.disabled = true;
  el.className = 'pending';
  el.textContent = 'Grading…';
  const res = await (await api('/api/curveball-grade', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({question_id: current.id, code: cm.getValue()})
  })).json();
  btn.disabled = false;
  el.className = res.ok ? 'ok' : 'bad';
  el.textContent = (res.ok ? '✓ ' : '✗ ') + res.feedback;
}

let sqlClarifyMode = false;
let sqlClarifyAsked = 0;
