// 100-module.js — lines 2357-2523 of original bundle. Key fns: showCalibration, renderCalibration, draw, askHint, askTwist, askDryRun
// ("gold") transcript's expected ranges, so they see the gap dimension by dimension.
function showCalibration(userJudge) {
  log("showCalibration");
  fetch('/api/calibration', {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({question_id: current.id})})
    .then(r => r.ok ? r.json() : Promise.reject())
    .then(data => renderCalibration(data, userJudge))
    .catch(() => alert('No calibration transcript available for this scenario yet.'));
}

function renderCalibration(data, userJudge) {
  const userDims = {};
  (userJudge.dimensions || []).forEach(d => { userDims[d.id] = d.score; });
  const allIds = Object.keys(data.dimensions);
  const gold = data.golds[0]; // default to first gold; user can switch below

  const overlay = document.createElement('div');
  overlay.style.cssText = 'position:fixed; inset:0; background:rgba(15,18,25,.55); z-index:50; display:flex; align-items:center; justify-content:center; padding:20px;';
  const panel = document.createElement('div');
  panel.style.cssText = 'background:#fff; border-radius:12px; max-width:760px; width:100%; max-height:88vh; overflow:auto; padding:18px 20px; font-size:13px; color:#111; box-shadow:0 20px 60px rgba(0,0,0,.3);';
  document.body.appendChild(overlay);
  overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };

  function draw(g) {
    const asserts = g.dimension_assertions || {};
    const rows = allIds.map(id => {
      const meta = data.dimensions[id] || {};
      const userScore = userDims[id];
      const a = asserts[id] || {};
      const lo = a.min, hi = a.max;
      let status = '', color = '#666';
      if (userScore == null) { status = 'not scored'; color = '#999'; }
      else if (lo != null && hi != null) {
        if (userScore < lo) { status = 'below gold min (' + lo + ')'; color = '#dc2626'; }
        else if (userScore > hi) { status = 'above gold max (' + hi + ')'; color = '#16a34a'; }
        else { status = 'within gold range'; color = '#16a34a'; }
      }
      const bar = (lo != null && hi != null)
        ? '<span style="display:inline-block; min-width:120px; height:8px; background:#eee; border-radius:4px; position:relative; vertical-align:middle;">'
          + '<span style="position:absolute; left:' + ((lo-1)/4*100) + '%; width:' + ((hi-lo)/4*100) + '%; background:#c4b5fd; height:100%; border-radius:4px;"></span>'
          + '<span style="position:absolute; left:' + ((userScore!=null?(userScore-1):0)/4*100) + '%; width:2px; background:' + color + '; height:14px; top:-3px;"></span></span>'
        : '';
      return '<div style="display:flex; align-items:center; gap:10px; padding:5px 0; border-bottom:1px solid #f0f0f0;">'
        + '<div style="width:42px; font-weight:700;">' + id + '</div>'
        + '<div style="flex:1;">' + (meta.name || '') + '<div style="color:' + color + '; font-size:11px;">' + (status || 'no gold target') + '</div></div>'
        + '<div style="width:60px; text-align:right; font-weight:700;">' + (userScore != null ? userScore.toFixed(1) : '-') + '/5</div>'
        + '<div style="width:130px;">' + bar + '</div></div>';
    }).join('');

    const rf = (g.red_flags_must_not_contain || []).map(f => '<span style="color:#dc2626;">must NOT contain: ' + f + '</span>').join(' · ');
    panel.innerHTML =
      '<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">'
      + '<div style="font-weight:700; font-size:16px;">🎯 Calibrate vs gold — ' + (g.band || 'gold') + '</div>'
      + '<button id="cal-close" style="border:none; background:none; font-size:18px; cursor:pointer;">✕</button></div>'
      + '<div style="color:#555; font-size:12px; margin-bottom:10px; background:#f7f5ff; border:1px solid #e9e3ff; border-radius:6px; padding:8px;">' + (g.note || '') + '</div>'
      + '<div style="display:flex; gap:6px; flex-wrap:wrap; margin-bottom:10px;">' + data.golds.map((gg, i) =>
          '<button data-i="' + i + '" class="cal-pick btn btn-ghost" style="font-size:12px; padding:4px 10px; border-radius:6px; ' + (gg === g ? 'border:2px solid #7c6cf6;' : '') + '">' + (gg.band || gg.file) + '</button>').join('') + '</div>'
      + '<div style="font-weight:600; margin-bottom:4px;">Your score vs gold target (purple band = gold range, bar = you)</div>'
      + rows
      + (rf ? '<div style="margin-top:10px; font-size:11px;">' + rf + '</div>' : '')
      + '<div style="margin-top:12px; font-size:11px; color:#777;">Gold ranges are from pre-scored reference transcripts. Use them to calibrate your read of the rubric, not as absolute pass marks.</div>';
    panel.querySelector('#cal-close').onclick = () => overlay.remove();
    panel.querySelectorAll('.cal-pick').forEach(b => b.onclick = () => draw(data.golds[+b.dataset.i]));
  }
  draw(gold);
}

function askHint() {
  addMsg('system', 'Hint requested');
  requestHint({question_id: current.id, code: cm.getValue(), actual: lastRunSummary, use_web: useWebAngle});
  nudgeSent = true;
  resetIdleTimer();
}

function askTwist() {
  addMsg('system', 'Asked for a twist');
  requestHint({question_id: current.id, code: cm.getValue(), actual: lastRunSummary, twist: true});
  resetIdleTimer();
}

function askDryRun() {
  addMsg('system', 'Asked for a dry run');
  requestHint({question_id: current.id, code: cm.getValue(), actual: lastRunSummary, dry_run: true});
  resetIdleTimer();
}

async function loadReview(qid, code, recallAnswer) {
  const placeholder = addMsg('tutor', 'reviewing your solution…');
  const textEl = placeholder.querySelector('.msg-text');
  try {
    const r = await fetch('/api/review', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({question_id: qid, code, recall_answer: recallAnswer || ''})
    });
    const res = await r.json();
    if (!r.ok || res.error) {
      placeholder.className += ' err';
      textEl.textContent = 'error: ' + (res.error || r.status);
    } else {
      textEl.innerHTML = renderReviewCards(res.review_sections || {});
    }
  } catch (e) {
    placeholder.className += ' err';
    textEl.textContent = 'error: ' + e.message;
  }
}

const REVIEW_CARD_META = {
  recall: {icon: '🧠', title: 'Your recall', className: 'recall-card'},
  readability: {icon: '✍️', title: 'Readability', className: ''},
  edge_cases: {icon: '⚠️', title: 'Edge cases', className: ''},
  followup: {icon: '🔁', title: 'Follow-up twist', className: ''},
  alternate: {icon: '🔀', title: 'Alternate approach', className: ''},
};

function renderReviewCards(sections) {
  const order = ['recall', 'readability', 'edge_cases', 'followup', 'alternate'];
  const cards = order
    .filter(k => sections[k] && String(sections[k]).trim())
    .map(k => {
      const m = REVIEW_CARD_META[k];
      return `<div class="review-card ${m.className}">
        <div class="review-card-title">${m.icon} ${m.title}</div>
        <div class="review-card-body">${escapeHtml(sections[k])}</div>
      </div>`;
    });
  if (!cards.length) return '🔍 (nothing notable to review)';
  return `<div class="review-cards">${cards.join('')}</div>`;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}

function sendMessage() {
  log("sendMessage");
  const box = document.getElementById('chatbox');
  const text = box.value.trim();
  if (!text) return;
  box.value = '';
  addMsg('user', text);
  if (current.lang === 'design') {
    requestInterview({question_id: current.id, message: text, requirements_only: clarifyMode});
    armPacingNudge();
  } else if (current.lang === 'decomposition') {
    requestInterview({question_id: current.id, message: text});
    // Fire co-pilot in parallel — no extra LLM cost, just pattern matching
    setTimeout(() => requestCoach({question_id: current.id, message: text, turn: document.querySelectorAll('.msg-user').length}), 100);
  } else {
    requestHint({question_id: current.id, code: cm.getValue(), actual: lastRunSummary, message: text});
    if (sqlClarifyMode) {
      sqlClarifyAsked++;
      renderSqlClarifyGate();
    }
  }
  // Option C: the candidate just answered the recall question — now give the
  // tailored review that references what they said, then clear the pending flag.
  if (pendingRecallReview) {
    const pr = pendingRecallReview;
    pendingRecallReview = null;
    document.getElementById('skip-review-btn').style.display = 'none';
    loadReview(pr.qid, pr.code, text);
  }
  nudgeSent = true;
  resetIdleTimer();
}
