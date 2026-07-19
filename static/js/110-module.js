// 110-module.js — lines 2523-2849 of original bundle. Key fns: skipToReview, renderDebriefChecklist, renderCommunicationScore, renderRubricBreakdown, renderVerdict, requestInterview

function skipToReview() {
  if (!pendingRecallReview) return;
  const pr = pendingRecallReview;
  pendingRecallReview = null;
  document.getElementById('skip-review-btn').style.display = 'none';
  loadReview(pr.qid, pr.code, '');
}

function renderDebriefChecklist(textEl, missed, taxonomy, selfRated) {
  const wrap = document.createElement('div');
  wrap.className = 'debrief-checklist';
  taxonomy.forEach(concept => {
    const wasMissed = missed.includes(concept);
    const selfFlagged = selfRated.includes(concept);
    let icon, note;
    if (wasMissed && selfFlagged) { icon = '🟡'; note = 'missed — you caught it'; }
    else if (wasMissed && !selfFlagged) { icon = '❌'; note = 'missed — blind spot'; }
    else if (!wasMissed && selfFlagged) { icon = '⚠️'; note = 'you flagged this but it was actually fine'; }
    else { icon = '✅'; note = 'covered'; }
    const row = document.createElement('div');
    row.className = 'checklist-row';
    row.textContent = `${icon} ${concept.replace(/_/g, ' ')} — ${note}`;
    wrap.appendChild(row);
  });
  textEl.appendChild(wrap);
}

function renderCommunicationScore(textEl, score, note) {
  if (!score) return;
  const row = document.createElement('div');
  row.className = 'checklist-row';
  row.style.marginTop = '6px';
  row.textContent = `🗣 Pacing & communication: ${score}/5 — ${note}`;
  textEl.appendChild(row);
}

const VERDICT_ICONS = {'Strong Hire': '🟢', 'Hire': '🟡', 'No Hire': '🔴'};
const RUBRIC_PHASE_COLORS = ['#3b82f6', '#8b5cf6', '#06b6d4', '#f97316', '#10b981', '#ec4899'];

function renderRubricBreakdown(textEl, rubric, scores, verdict, retroQuestions) {
  const wrap = document.createElement('div');
  wrap.className = 'rubric-breakdown';
  const phaseMaxes = rubric.phases.map(p => p.max);
  let totalScore = 0, totalMax = 0;
  rubric.phases.forEach((phase, i) => {
    const score = scores[`phase${i+1}`];
    if (score === undefined) return;
    totalScore += score;
    totalMax += phase.max;
    const pct = Math.round(100 * score / phase.max);
    const color = RUBRIC_PHASE_COLORS[i % RUBRIC_PHASE_COLORS.length];
    const phaseDiv = document.createElement('div');
    phaseDiv.className = 'rubric-phase';
    phaseDiv.innerHTML = `
      <div class="rubric-phase-header">
        <span>${phase.name}</span>
        <span>${score}/${phase.max} (${pct}%)</span>
      </div>
      <div class="rubric-bar-bg"><div class="rubric-bar-fill" style="width:${pct}%;background:${color};"></div></div>
      <div class="rubric-phase-items" style="display:none;">
        ${phase.items.map(item => {
          let dotClass = 'na';
          const itemPct = score / phase.max;
          if (itemPct >= 0.8) dotClass = 'done';
          else if (itemPct >= 0.4) dotClass = 'partial';
          else dotClass = 'missed';
          return `<div class="rubric-phase-item"><span class="item-dot ${dotClass}"></span>${item.desc}</div>`;
        }).join('')}
      </div>`;
    phaseDiv.querySelector('.rubric-phase-header').onclick = () => {
      const items = phaseDiv.querySelector('.rubric-phase-items');
      items.style.display = items.style.display === 'none' ? '' : 'none';
    };
    wrap.appendChild(phaseDiv);
  });
  const totalPct = totalMax > 0 ? Math.round(100 * totalScore / totalMax) : 0;
  const totalDiv = document.createElement('div');
  totalDiv.className = 'rubric-total';
  totalDiv.textContent = `Total: ${totalScore}/${totalMax} (${totalPct}%)`;
  wrap.appendChild(totalDiv);
  const verdictIcon = VERDICT_ICONS[verdict] || '';
  const verdictDiv = document.createElement('div');
  verdictDiv.className = 'rubric-verdict';
  verdictDiv.textContent = `${verdictIcon} ${verdict}`;
  wrap.appendChild(verdictDiv);
  if (retroQuestions && retroQuestions.length) {
    const retroDiv = document.createElement('div');
    retroDiv.className = 'rubric-retro';
    retroDiv.innerHTML = '<h4>Post-interview retro</h4>';
    retroQuestions.forEach((r, i) => {
      const row = document.createElement('div');
      row.className = 'rubric-retro-item';
      row.textContent = `${i+1}. ${r.q} — ${r.why}`;
      retroDiv.appendChild(row);
    });
    wrap.appendChild(retroDiv);
  }
  textEl.appendChild(wrap);
}

function renderVerdict(textEl, verdict) {
  if (!verdict) return;
  const row = document.createElement('div');
  row.className = 'checklist-row';
  row.style.cssText = 'margin-top:6px; font-weight:600;';
  row.textContent = `${VERDICT_ICONS[verdict] || ''} Read: ${verdict}`;
  textEl.appendChild(row);
}

async function requestInterview(body) {
  const placeholder = addMsg('tutor', 'thinking…');
  const textEl = placeholder.querySelector('.msg-text');
  try {
    const r = await fetch('/api/interview', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({...body, diagram: clarifyMode ? '' : serializeCanvasForLLM(), persona: selectedPersona,
                             archetype: selectedArchetype || undefined,
                             adversarial: adversarialMode, flaws: adversarialFlaws, scaling: scalingMode || undefined,
                             incident: incidentMode, incident_scenario: incidentScenario || undefined,
                             decomposition: current && current.lang === 'decomposition' || undefined})
    });
    const res = await r.json();
    if (!r.ok || res.error) {
      placeholder.className += ' err';
      textEl.textContent = 'error: ' + (res.error || r.status);
    } else {
      textEl.textContent = res.reply;
      if (res.wrap_up && res.incident) {
        const incidentEl = document.createElement('div');
        incidentEl.className = 'debrief-checklist';
        incidentEl.innerHTML = `
          <div class="checklist-row">🔥 Incident score: ${res.incident_score || '?'}/5</div>
          <div class="checklist-row">${res.triage_ok ? '✅' : '❌'} Triage: ${res.triage_ok ? 'checked blast radius / logs first' : 'did not triage properly'}</div>
          <div class="checklist-row">${res.fix_choice_ok ? '✅' : '❌'} Fix: ${res.fix_choice_ok ? 'chose right fix (stabilize, not rebuild)' : 'fix choice was off'}</div>
          <div class="checklist-row">${res.communication_ok ? '✅' : '❌'} Communication: ${res.communication_ok ? 'kept stakeholders informed' : 'did not communicate effectively'}</div>`;
        textEl.appendChild(incidentEl);
      }
      if (res.wrap_up && res.decomposition) {
        const j = res.judge;
        window.__lastJudge = j;
        if (j) {
          // Red flags
          if (j.red_flags && j.red_flags.length) {
            j.red_flags.forEach(f => {
              const el = document.createElement('div');
              el.style.cssText = 'background:#fef2f2; border:1px solid #fca5a5; border-radius:6px; padding:8px 10px; margin-bottom:8px; color:#991b1b; font-size:13px; font-weight:600;';
              const label = f.flag === 'rushed_to_solution' ? 'Rushed to solution' : f.flag;
              el.textContent = '🚩 ' + label + (f.detail ? ': ' + f.detail : '');
              textEl.appendChild(el);
            });
          }
          // Band
          const BAND_LABELS = {strong_hire: 'Strong Hire', hire: 'Hire', borderline: 'Borderline', no_hire: 'No Hire', strong_no_hire: 'Strong No Hire'};
          const BAND_COLORS = {strong_hire: '#16a34a', hire: '#ca8a04', borderline: '#ea580c', no_hire: '#dc2626', strong_no_hire: '#991b1b'};
          if (j.band) {
            const bandEl = document.createElement('div');
            bandEl.className = 'checklist-row';
            bandEl.style.cssText = 'margin-top:6px; font-weight:700; font-size:15px; color:' + (BAND_COLORS[j.band] || '#333') + ';';
            let capNote = j.band_capped_by_disqualifier ? ' (capped by disqualifier)' : '';
            bandEl.textContent = (BAND_LABELS[j.band] || j.band) + capNote + ' — ' + (j.normalized_score ? j.normalized_score.toFixed(2) : '?') + '/5.0';
            textEl.appendChild(bandEl);
            if (j.low_coverage) {
              const wEl = document.createElement('div');
              wEl.style.cssText = 'color:#888; font-size:12px; margin-top:2px;';
              wEl.textContent = '⚠ Low coverage — fewer than 5 dimensions were scorable. Score is advisory.';
              textEl.appendChild(wEl);
            }
          }
          // Dimensions
          if (j.dimensions && j.dimensions.length) {
            const dimWrap = document.createElement('div');
            dimWrap.className = 'debrief-checklist';
            dimWrap.innerHTML = '<div style="font-weight:600; margin-bottom:4px;">Judge Rubric</div>';
            j.dimensions.forEach(d => {
              const sc = d.score != null ? d.score + '/5' : 'N/A';
              const wt = ' (×' + d.weight + ')';
              const rt = d.response_type ? ' [' + d.response_type + ']' : '';
              const bg = d.opportunity_present ? '' : 'background:#f5f5f5;';
              const row = document.createElement('div');
              row.className = 'checklist-row';
              row.style.cssText = bg + 'margin:2px 0;';
              row.innerHTML = '<span><strong>' + d.id + '</strong> ' + d.name + wt + ': ' + sc + rt + '</span>';
              // Evidence toggle
              if (d.evidence && d.evidence.length) {
                const evBtn = document.createElement('span');
                evBtn.style.cssText = 'color:#666; cursor:pointer; font-size:11px; margin-left:6px;';
                evBtn.textContent = '📋';
                evBtn.onclick = () => {
                  const evDiv = row.querySelector('.ev-detail');
                  if (evDiv) { evDiv.style.display = evDiv.style.display === 'none' ? '' : 'none'; return; }
                  const ed = document.createElement('div');
                  ed.className = 'ev-detail';
                  ed.style.cssText = 'font-size:11px; color:#555; margin:4px 0 0 12px; padding:4px 8px; background:#f9f9f9; border-radius:4px;';
                  ed.innerHTML = d.evidence.map(e => '<div style="margin:2px 0"><em>[t' + e.turn + ' ' + e.type + ']</em> "' + e.quote + '"</div>').join('');
                  row.appendChild(ed);
                };
                row.appendChild(evBtn);
              }
              dimWrap.appendChild(row);
            });
            textEl.appendChild(dimWrap);
          }
          // Coaching
          if (j.coaching) {
            const coachWrap = document.createElement('div');
            coachWrap.style.cssText = 'margin-top:10px; padding:8px 10px; background:#f0f7ff; border:1px solid #bfdbfe; border-radius:6px;';
            coachWrap.innerHTML = '<div style="font-weight:600; margin-bottom:4px;">📝 Coaching</div>';
            if (j.coaching.summary) {
              const sum = document.createElement('div');
              sum.style.cssText = 'font-size:13px; margin-bottom:6px;';
              sum.textContent = j.coaching.summary;
              coachWrap.appendChild(sum);
            }
            if (j.coaching.per_dimension && j.coaching.per_dimension.length) {
              j.coaching.per_dimension.forEach(pd => {
                const row = document.createElement('div');
                row.style.cssText = 'font-size:12px; margin:2px 0;';
                row.innerHTML = '<strong>' + pd.dimension_id + ':</strong> ' + pd.note;
                coachWrap.appendChild(row);
              });
            }
            if (j.coaching.strongest_moment) {
              const s = document.createElement('div');
              s.style.cssText = 'font-size:12px; margin-top:4px; color:#166534;';
              s.innerHTML = '⭐ <strong>Strongest:</strong> turn ' + j.coaching.strongest_moment.turn + ' — ' + j.coaching.strongest_moment.note;
              coachWrap.appendChild(s);
            }
            if (j.coaching.costliest_moment) {
              const c = document.createElement('div');
              c.style.cssText = 'font-size:12px; margin-top:2px; color:#991b1b;';
              c.innerHTML = '💸 <strong>Costliest:</strong> turn ' + j.coaching.costliest_moment.turn + ' — ' + j.coaching.costliest_moment.note;
              coachWrap.appendChild(c);
            }
            textEl.appendChild(coachWrap);
          }
        }
        // Compare with another archetype
        if (current.archetypes && !__compareMode) {
          const otherKeys = Object.keys(current.archetypes).filter(k => k !== selectedArchetype);
          if (otherKeys.length) {
            const cmpWrap = document.createElement('div');
            cmpWrap.style.cssText = 'margin-top:10px; padding:8px 10px; background:#f5f3ff; border:1px solid #c4b5fd; border-radius:6px;';
            cmpWrap.innerHTML = '<div style="font-size:12px; font-weight:600; margin-bottom:4px;">🔄 Compare with a different persona:</div>';
            otherKeys.forEach(key => {
              const btn = document.createElement('button');
              btn.className = 'btn btn-ghost';
              btn.textContent = current.archetypes[key].label || key;
              btn.style.cssText = 'font-size:12px; padding:4px 10px; border-radius:6px; margin:2px 4px;';
              btn.onclick = () => startComparison(key);
              cmpWrap.appendChild(btn);
            });
            textEl.appendChild(cmpWrap);
          }
        }
      }
      if (res.wrap_up && res.concept_taxonomy && !res.decomposition) {
        renderDebriefChecklist(textEl, res.missed_concepts || [], res.concept_taxonomy, res.self_rated || []);
        renderCommunicationScore(textEl, res.communication_score, res.communication_note);
        renderVerdict(textEl, res.verdict);
        if (res.rubric && res.rubric_scores) {
          renderRubricBreakdown(textEl, res.rubric, res.rubric_scores, res.verdict, res.retro_questions);
        }
        if (res.max_tier_reached) {
          const tierRow = document.createElement('div');
          tierRow.className = 'checklist-row';
          tierRow.style.cssText = 'margin-top:6px;';
          tierRow.textContent = `↗ Scaling tier reached: ${res.max_tier_reached}/6`;
          textEl.appendChild(tierRow);
        }
        document.getElementById('refdesign-btn').style.display = '';
        document.getElementById('staffcomp-btn').style.display = '';
        fetch('/api/takeaways', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({question_id: current.id, missed_concepts: res.missed_concepts || [], rubric_scores: res.rubric_scores || {}})
        }).then(r => r.json()).then(t => renderTakeaways(t.takeaways)).catch(() => {});
      }
      // Download report button for any wrap_up
      if (res.wrap_up) {
        const dlBtn = document.createElement('button');
        dlBtn.className = 'btn btn-ghost';
        dlBtn.textContent = '📥 Download Report';
        dlBtn.style.cssText = 'font-size:13px; margin-top:10px; padding:6px 14px; border-radius:6px;';
        dlBtn.onclick = () => {
          const body = {question_id: current.id};
          if (res.decomposition) body.decomposition = true;
          fetch('/api/export', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)})
            .then(r => r.ok ? r.text() : Promise.reject())
            .then(md => {
              const blob = new Blob([md], {type: 'text/markdown'});
              const url = URL.createObjectURL(blob);
              const a = document.createElement('a'); a.href = url; a.download = (current.id || 'report') + '.md'; a.click();
              URL.revokeObjectURL(url);
            }).catch(() => alert('Export failed — session may have expired.'));
        };
        textEl.appendChild(dlBtn);
        // Calibrate vs gold — only for decomposition sessions with a judge result
        if (res.decomposition && res.judge && res.judge.dimensions) {
          const calBtn = document.createElement('button');
          calBtn.className = 'btn btn-ghost';
          calBtn.textContent = '🎯 Calibrate vs gold';
          calBtn.style.cssText = 'font-size:13px; margin-top:10px; margin-left:6px; padding:6px 14px; border-radius:6px;';
          calBtn.onclick = () => showCalibration(res.judge);
          textEl.appendChild(calBtn);
        }
      }
      // Comparison mode: show side-by-side after second session wrap-up
      if (res.wrap_up && res.decomposition && __compareData) {
        window.__compareData2 = {
          label: current.archetypes?.[selectedArchetype]?.label || selectedArchetype || 'Standard',
          chatHTML: document.getElementById('chatlog').innerHTML,
          band: res.judge?.band || '',
          score: res.judge?.normalized_score || 0,
          dimScores: (res.judge?.dimensions || []).map(d => ({id: d.id, score: d.score})),
        };
        setTimeout(renderComparison, 100);
      }
      speakTutor(res.reply);
      extractChips(res.reply);
      if (res.wrap_up) clearPacingNudge(); else armPacingNudge();
    }
  } catch (e) {
    placeholder.className += ' err';
    textEl.textContent = 'error: ' + e.message;
  }
}
