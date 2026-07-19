// 90-module.js — lines 2214-2357 of original bundle. Key fns: requestHint, requestCoach, showCoachPill, startComparison, applyComparisonMode, renderComparison

async function requestHint(body) {
  const placeholder = addMsg('tutor', 'thinking…');
  const textEl = placeholder.querySelector('.msg-text');
  try {
    const r = await api('/api/hint', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
    });
    const res = await r.json();
    if (!r.ok || res.error) {
      placeholder.className += ' err';
      textEl.textContent = 'error: ' + (res.error || r.status);
    } else {
      textEl.textContent = res.hint;
    }
  } catch (e) {
    placeholder.className += ' err';
    textEl.textContent = 'error: ' + e.message;
  }
}

async function requestCoach(body) {
  try {
    const r = await api('/api/coach', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
    });
    const res = await r.json();
    if (res.hint) showCoachPill(res.hint);
  } catch (_) {}
}

let coachPillTimer = null;

function showCoachPill(text) {
  const existing = document.getElementById('coach-pill');
  if (existing) existing.remove();
  if (coachPillTimer) clearTimeout(coachPillTimer);
  const pill = document.createElement('div');
  pill.id = 'coach-pill';
  pill.style.cssText = 'background:#fef3c7; border:1px solid #f59e0b; border-radius:8px; padding:6px 12px; margin:4px 0; font-size:12px; color:#92400e; display:flex; align-items:center; gap:6px; animation:fadeIn .3s;';
  pill.innerHTML = '<span style="font-size:14px;">💡</span> <span>' + text + '</span>';
  const input = document.getElementById('chatinput');
  if (input) input.parentNode.insertBefore(pill, input);
  coachPillTimer = setTimeout(() => { if (pill.parentNode) pill.remove(); }, 8000);
}

function startComparison(archetype) {
  const chatlog = document.getElementById('chatlog');
  const j = window.__lastJudge;
  __compareData = {
    label: current.archetypes[selectedArchetype]?.label || 'Standard',
    chatHTML: chatlog.innerHTML,
    band: j?.band || '',
    score: j?.normalized_score || 0,
    dimScores: (j?.dimensions || []).map(d => ({id: d.id, score: d.score})),
  };
  __compareMode = archetype;
  selectedArchetype = archetype;
  loadQuestion(current.id, true);
}

function applyComparisonMode() {
  if (__compareMode) {
    const html = document.getElementById('chatlog').innerHTML;
    document.getElementById('chatlog').innerHTML = '';
    const cmp = document.createElement('div');
    cmp.style.cssText = 'display:flex; gap:12px;';
    const left = document.createElement('div');
    left.style.cssText = 'flex:1; border:1px solid #e5e7eb; border-radius:8px; padding:8px; overflow:auto; max-height:70vh;';
    left.innerHTML = '<div style="font-size:11px; font-weight:600; color:#6b7280; margin-bottom:6px;">' + __compareData.label + '</div>';
    left.innerHTML += '<div style="font-size:11px; color:#374151;">' + __compareData.chatHTML + '</div>';
    const right = document.createElement('div');
    right.style.cssText = 'flex:1; border:2px solid #c4b5fd; border-radius:8px; padding:8px; overflow:auto; max-height:70vh;';
    right.innerHTML = '<div style="font-size:11px; font-weight:600; color:#6b7280; margin-bottom:6px;">' + (current.archetypes?.[__compareMode]?.label || __compareMode) + '</div>';
    right.innerHTML += '<div style="font-size:11px; color:#374151;">' + html + '</div>';
    cmp.appendChild(left);
    cmp.appendChild(right);
    document.getElementById('chatlog').appendChild(cmp);
    __compareMode = null;
  }
}

const BAND_LABELS = {strong_hire: 'Strong Hire', hire: 'Hire', borderline: 'Borderline', no_hire: 'No Hire', strong_no_hire: 'Strong No Hire'};
const BAND_COLORS = {strong_hire: '#16a34a', hire: '#ca8a04', borderline: '#ea580c', no_hire: '#dc2626', strong_no_hire: '#991b1b'};

function renderComparison() {
  const log = document.getElementById('chatlog');
  const html1 = __compareData.chatHTML;
  const html2 = window.__compareData2.chatHTML;
  const d1 = __compareData;
  const d2 = window.__compareData2;
  log.innerHTML = '';
  const wrap = document.createElement('div');
  wrap.style.cssText = 'display:flex; flex-direction:column; gap:16px;';

  // Score comparison header
  const header = document.createElement('div');
  header.style.cssText = 'display:flex; gap:16px;';
  const scoreCard = (data, color) => {
    const c = document.createElement('div');
    c.style.cssText = 'flex:1; border:2px solid ' + color + '; border-radius:8px; padding:10px;';
    c.innerHTML = '<div style="font-weight:700; font-size:14px; margin-bottom:4px;">' + data.label + '</div>'
      + '<div style="font-size:12px; color:' + (BAND_COLORS[data.band] || '#333') + '; font-weight:600;">' + (BAND_LABELS[data.band] || data.band) + ' — ' + data.score.toFixed(2) + '/5.0</div>';
    return c;
  };
  header.appendChild(scoreCard(d1, '#e5e7eb'));
  header.appendChild(scoreCard(d2, '#c4b5fd'));
  wrap.appendChild(header);

  // Dimension comparison
  if (d1.dimScores?.length && d2.dimScores?.length) {
    const dims = document.createElement('div');
    dims.style.cssText = 'display:flex; gap:16px;';
    const dimCol = (data, border) => {
      const c = document.createElement('div');
      c.style.cssText = 'flex:1; border:1px solid ' + border + '; border-radius:8px; padding:8px; font-size:12px;';
      c.innerHTML = data.dimScores.map(d => '<div style="margin:2px 0;"><strong>' + d.id + ':</strong> ' + (d.score ?? '-') + '/5</div>').join('');
      return c;
    };
    dims.appendChild(dimCol(d1, '#e5e7eb'));
    dims.appendChild(dimCol(d2, '#c4b5fd'));
    wrap.appendChild(dims);
  }

  // Transcript comparison
  const trans = document.createElement('div');
  trans.style.cssText = 'display:flex; gap:12px;';
  const pane = (html, border) => {
    const p = document.createElement('div');
    p.style.cssText = 'flex:1; border:1px solid ' + border + '; border-radius:8px; padding:8px; overflow:auto; max-height:60vh; font-size:11px;';
    p.innerHTML = html;
    return p;
  };
  trans.appendChild(pane(html1, '#e5e7eb'));
  trans.appendChild(pane(html2, '#c4b5fd'));
  wrap.appendChild(trans);

  log.appendChild(wrap);
  __compareData = null;
  window.__compareData2 = null;
}

// Calibration mode: compare the candidate's scored dimensions against a known-good
