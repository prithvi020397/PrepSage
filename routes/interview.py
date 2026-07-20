# Phase 5 refactor — routes (verbatim from app.py).
from flask import Blueprint
from flask import jsonify, request, session, g, render_template, redirect, flash, current_app, send_file, url_for, abort

bp = Blueprint('interview', __name__)

@bp.route("/api/interview", methods=["POST"])
def interview():
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
    data = request.json or {}
    qid = data.get("question_id")
    if not qid:
        return jsonify({"error": "question_id required"}), 400
    q = QUESTIONS.get(qid)
    if not q or q["lang"] not in ("design", "decomposition"):
        return jsonify({"error": "not found"}), 404

    requirements_only = bool(data.get("requirements_only"))
    adversarial = bool(data.get("adversarial"))
    scaling = bool(data.get("scaling"))
    incident = bool(data.get("incident"))
    decomposition = bool(data.get("decomposition"))
    chat_key = data["question_id"] + (":decomposition" if decomposition else (":clarify" if requirements_only else (":adversarial" if adversarial else (":scaling" if scaling else (":incident" if incident else "")))))

    if requirements_only:
        system_prompt = f"""You are a {persona_for(q)} running a requirements-gathering drill. Stay in character.

Scenario: {q['title']}
{q['prompt']}

{REQUIREMENTS_ONLY_RULES}"""
    elif adversarial:
        flaws = data.get("flaws") or []
        flaws_block = "\n".join(f"- {f.get('concept', '')}: {f.get('note', '')}" for f in flaws if f.get("concept"))
        adversarial_persona_note = ""
        adversarial_persona_key = data.get("persona")
        if adversarial_persona_key in ADVERSARIAL_PERSONAS:
            adversarial_persona_note = f"\n\n{ADVERSARIAL_PERSONAS[adversarial_persona_key]}"
        system_prompt = f"""You are a {persona_for(q)} running an adversarial "break this design" drill.

Scenario: {q['title']}
{q['prompt']}

The design currently on the candidate's whiteboard has these deliberate flaws (never reveal this list directly — only confirm or push back as they investigate):
{flaws_block}

        {ADVERSARIAL_RULES}{adversarial_persona_note}"""
    elif scaling:
        persona_note = ""
        persona_key = data.get("persona")
        if persona_key in PERSONAS:
            persona_note = f"\n\nInterviewer persona for this session: {PERSONAS[persona_key]}"
        tier_blocks = "\n".join(f"  Tier {i+1}: {t['name']} — {t['scale']}. {t['desc']}"
                                 for i, t in enumerate(SCALING_TIERS))
        system_prompt = f"""You are a {persona_for(q)} conducting a scaling-pressure interview. Stay in character as the interviewer throughout.

Scenario: {q['title']}
{q['prompt']}

Your goal is to start at the baseline tier and escalate through each tier as the candidate's design stabilizes.

Scaling ladder (escalate in order, one tier at a time):
{tier_blocks}

Rules:
1. Start the interview at Tier 1 — let them ask clarifying questions and sketch a design for that scale.
2. Once their design for the current tier is reasonably stable (not perfect, just coherent), escalate to the next tier. Explain what breaks concretely — don't just say "scale up."
3. At each escalation, the candidate should evolve their existing design, not start over. Push them to identify what fails first and why.
4. If they jump to a solution that would work at a higher tier (e.g. partitioning at Tier 1), note that it's premature but don't force them to undo it — just escalate sooner.
5. If their design at the current tier has a real gap that would break even at that tier's scale, probe that gap before escalating. Don't let them skip a tier's constraint.
6. Never design it for them and never state the "correct" answer, even if asked directly.
7. Keep replies to 2-4 sentences, interviewer voice, no bullet lists.
        8. The candidate has a whiteboard. Before their message you'll see its current contents as boxes/arrows/notes — treat it like glancing at a real whiteboard. React to mismatches: things they said but never drew, or drew but never explained.{persona_note}"""
    elif incident:
        incident_scenario = data.get("incident_scenario") or ""
        system_prompt = f"""You are a senior engineer running an incident-response drill. Stay in character — this is production, not hypothetical.

Scenario: {q['title']}
{q['prompt']}

The current incident (this is the real failure the candidate must respond to):
{incident_scenario}

{INCIDENT_RULES}"""
    elif decomposition:
        if q.get("format_version") == 2:
            # v2 — build client prompt from persona + triggers (no scoring content)
            p = q.get("persona", {})
            triggers = q.get("triggers", [])
            # Archetype deep-merge — deep-copy then mutate p and triggers in-place
            archetype_key = data.get("archetype")
            if archetype_key and q.get("archetypes"):
                a = q["archetypes"].get(archetype_key)
                if a and "persona" in a:
                    p = json.loads(json.dumps(p))  # deep-copy before mutatation
                    for k, v in a["persona"].items():
                        if isinstance(v, dict):
                            p.setdefault(k, {}).update(v)
                        else:
                            p[k] = v
                if a and "triggers" in a:
                    triggers = json.loads(json.dumps(triggers))  # deep-copy before mutatation
                    overrides = {t["id"]: t for t in a["triggers"]}
                    for t in triggers:
                        if t["id"] in overrides:
                            t.update(overrides[t["id"]])
            # Filter judge_note out of trigger blocks that go to the client
            clean_triggers = []
            for tr in triggers:
                ct = {k: v for k, v in tr.items() if k != "judge_note"}
                clean_triggers.append(ct)
            system_prompt = f"""You are roleplaying as a client stakeholder. The candidate is an FDE assigned to your account. Stay in character as a real client — you have a problem, you need help solving it, but you don't have all the answers yourself.

Your name: {p.get('name', 'Client')}
Your role: {p.get('role', 'Stakeholder')}
Your voice: {p.get('voice', 'Professional')}

{json.dumps(p.get('hidden_facts', {}), indent=2)}
(The above is your PRIVATE internal knowledge. Never volunteer it unprompted.)

{json.dumps(clean_triggers, indent=2)}
(The above are internal notes on how to react when certain topics arise. Do NOT reveal this structure to the candidate.)

{p.get('knowledge_boundaries', '')}"""
        else:
            # v1 — use the existing rules, stripped of any scoring content
            system_prompt = f"""You are roleplaying as a client stakeholder at the company described below. The candidate is an FDE assigned to your account. Stay in character as a real client — you have a problem, you need help solving it, but you don't have all the answers yourself.

Your internal situation (this is your PRIVATE context — the candidate does NOT know this and you must NOT volunteer it):
Title: {q['title']}
What's happening: {q['prompt']}

**CRITICAL: The above "What's happening" is your private knowledge. Your opening statement MUST be vague — describe the problem in 1 sentence without mentioning specific constraints, technologies, compliance requirements, or internal teams. Anyone reading your opening should not be able to tell if this is a small startup or a Fortune 500. Let the candidate discover the details by asking good questions.**

{DECOMPOSITION_RULES}"""
    else:
        rubric_lines = "\n".join(f"- {r}" for r in baseline_rubric_for(q) + q.get("rubric", []))
        war_stories_block = "\n".join(f"- {concept}: {story}" for concept, story in war_stories_for(q).items())

        resurfacing_note = ""
        if data.get("start"):
            recurring = recurring_missed_concepts()
            if recurring:
                resurfacing_note = (
                    f"\n\nThis candidate has repeatedly missed these concepts across recent design interviews: "
                    f"{', '.join(recurring)}. If either is relevant to this question, make sure to probe it."
                )

        persona_note = ""
        persona_key = data.get("persona")
        if persona_key in PERSONAS:
            persona_note = f"\n\nInterviewer persona for this session: {PERSONAS[persona_key]}"

        resume_note = ""
        resume = PROGRESS.get("_resume")
        if resume and data.get("start"):
            domains_raw = resume.get("domains", [])[:3]
            skills_raw = resume.get("skills", [])[:4]
            domains = [d.get("name") if isinstance(d, dict) else d for d in domains_raw]
            skills = [sk.get("name") if isinstance(sk, dict) else sk for sk in skills_raw]
            if domains or skills:
                resume_note = (
                    f"\n\nCandidate's background: domains = {', '.join(domains)}; skills = {', '.join(skills)}. "
                    f"When probing, draw connections to their experience where relevant — e.g. 'Given your work with {domains[0] if domains else skills[0]}, how would you handle...'"
                )

        system_prompt = f"""You are a {persona_for(q)} conducting a system design interview. Stay in character as the interviewer throughout.

Scenario: {q['title']}
{q['prompt']}

What a strong answer eventually covers (your private rubric — NEVER read this list back to the candidate or hint that it exists):
{rubric_lines}

Concrete failure scenarios you can draw on when probing or pushing back — cite the consequence, not just the pattern name, and only bring up the ones relevant to what's missing (don't dump this list):
{war_stories_block}

Rules:
1. Don't volunteer requirements the candidate hasn't asked about yet.
2. If the candidate starts proposing a design before asking about scale, latency, data volume, existing systems, or budget, stop them and ask what they'd want to clarify first.
3. Once they've asked reasonable clarifying questions (or explicitly state assumptions and move on), let them sketch a design across all layers (sources, processing, storage, consumers, tooling) before pushing deep on any one part.
4. Only probe a layer they actually mentioned or conspicuously skipped, and ground the probe in a concrete failure mode or scale consideration specific to their choice — not a generic "what about scale?" question.
5. Push back, don't just note it and move on: if they propose streaming-only or batch-only with no reprocessing/replay story, or never mention idempotency, backfills, schema evolution, or data quality once the design is otherwise taking shape, ask one pointed question grounded in the matching failure scenario above before letting them move to the next layer.
6. Never design it for them and never state the "correct" answer, even if asked directly.
7. Keep replies to 2-4 sentences, interviewer voice, no bullet lists.
8. The candidate has a whiteboard. Before their message you'll see its current contents as boxes/arrows/notes — treat it like glancing at a real whiteboard. React to mismatches: things they said but never drew, or drew but never explained.{resurfacing_note}{persona_note}{resume_note}"""

    if data.get("wrap_up"):
        if incident:
            user_turn = ("(The incident drill is ending. Give a 3-5 sentence debrief scoring the candidate's incident "
                         "response: triage order, communication, fix choice, and one concrete thing to practice. "
                         "End with a JSON block:\n"
                         "```json\n{\"incident_score\": <1-5>, \"triage_ok\": <true/false>, "
                         "\"fix_choice_ok\": <true/false>, \"communication_ok\": <true/false>}\n```)")
        elif decomposition:
            user_turn = ("(The engagement is ending. Write a 3-5 sentence debrief from the CLIENT's perspective — "
                         "not as an interviewer grading a candidate, but as a real stakeholder reflecting on how "
                         "the FDE handled the engagement. Mention what they did well and where they fell short. "
                         "Use natural client language, not rubric language. "
                         "Do NOT include any JSON block or structured rubric — just natural prose.)")
        else:
            concept_list = ", ".join(taxonomy_for(q))
            rubric_block = (
                "Also rate each of these 6 phases 0 to max based on the transcript, "
                "and include rubric_scores in the json block:\n"
                "  phase1 (max 8): requirements & scoping — asks about scale, latency, sources, consumers, constraints; summarizes, identifies ambiguities, defines done\n"
                "  phase2 (max 10): architecture — correct ingestion/processing/storage/serving layer; clean flow, right complexity, uses existing infra, specific tools, happy path first, defends choices\n"
                "  phase3 (max 6): data modeling — schema design, partitioning, file format, schema evolution, dedup, data versioning\n"
                "  phase4 (max 8): reliability — late data, idempotency, error handling, exactly-once, backpressure, data quality, failure isolation, recovery\n"
                "  phase5 (max 6): operations — monitoring, data freshness, cost estimation, scaling, access control, deployment\n"
                "  phase6 (max 6): communication — structured walkthrough, trade-off articulation, handles pushback, asks for feedback, time management, confidence vs humility\n"
                "Be honest and score against the bar for this question, not an ideal candidate."
            )
            user_turn = ("(The candidate wants to end the interview now. Give a structured debrief in 4-6 sentences total: "
                         "which rubric points they addressed well, which were missing or shallow, and one concrete concept to "
                         "go read up on. This is the only time you may reveal rubric-style structure. Comment on the "
                         "whiteboard too if it's empty or contradicts what they said, but keep it brief — the json block "
                         "below is where the missing concepts get itemized, don't also list them at length in prose. "
                         "After your prose debrief, on a new line, append a fenced json block classifying which "
                         f"concepts from this fixed list were missing or shallow: [{concept_list}]. Use ONLY concepts "
                         "from that list, only the ones actually missing or shallow. Grade against the bar for this "
                         "question, not against the best candidate you can imagine, and weight demonstrated evidence "
                         "over confident delivery — a polished answer with no cited depth is not a strong signal. Also "
                         "include rushed_to_design: true "
                         "if the candidate proposed concrete storage/architecture choices before asking any meaningful "
                         "clarifying questions about scale, latency, or requirements, false if they clarified first. Also "
                         "include communication_score: an integer 1-5 rating how well they signposted their thinking, "
                         "checked in before committing to a direction, and paced the conversation (5 = clearly narrated "
                         "reasoning and checked in at decision points, 1 = silent info-dumping or jumping around with no "
                         "narration), plus communication_note: one short sentence citing a specific moment from this "
                         "conversation, not a vague impression — 'clearly walked through the cache invalidation trade-off "
                         "before committing' rather than 'good communication'. " + rubric_block + ". e.g.:\n"
                         "```json\n{\"missed_concepts\": [\"idempotency_dedup\", \"backfill_reprocessing\"], "
                         "\"rushed_to_design\": false, \"communication_score\": 4, \"communication_note\": "
                         "\"Narrated tradeoffs clearly but didn't check in before committing to Kafka.\", "
                         "\"rubric_scores\": {\"phase1\": 5, \"phase2\": 7, \"phase3\": 4, \"phase4\": 3, \"phase5\": 2, \"phase6\": 5}" + ("}" if not scaling else "}") + (", \"max_tier_reached\": <number>" if scaling else "") + "\n```)")
    elif data.get("end_drill"):
        user_turn = ("(The candidate wants to end the drill now. Give the short debrief described in your "
                     "instructions: which clarifying-question categories they covered, which they missed, and "
                     "whether their questions were specific enough.)")
    elif data.get("start"):
        if requirements_only:
            user_turn = ("(The drill is starting. Give a brief one-sentence opening telling the candidate this "
                         "round is clarifying questions only — no design yet.)")
        elif adversarial:
            user_turn = ("(The drill is starting and a flawed design is already on the candidate's whiteboard. "
                         "Give a brief one-sentence opening asking what worries them about it at scale.)")
        elif scaling:
            user_turn = ("(The scaling-pressure drill is starting. Open at Tier 1 — Baseline (1K req/day). "
                         "Give a brief one-sentence opening inviting the candidate to ask clarifying questions "
                         "and sketch a design for that scale. Don't restate the scenario or mention future tiers.)")
        elif incident:
            user_turn = ("(The incident-response drill is starting. Open with a brief, urgent description of "
                         "the failure scenario — what broke, what alerts fired, who's affected. "
                         "Ask the candidate how they'd start troubleshooting. 2-3 sentences, calm but urgent tone.)")
        elif decomposition:
            v2_question = q.get("format_version") == 2 and (p.get("opening_line") if archetype_key and q.get("archetypes", {}).get(archetype_key) else q.get("persona", {}).get("opening_line"))
            if v2_question:
                user_turn = f"(The engagement is starting. Roleplay as the client. Your opening line is below — say it exactly as written, then wait for the candidate to respond.)\n\n{p['opening_line']}"
            else:
                user_turn = ("(The engagement is starting. Roleplay as the client stakeholder introducing the problem. "
                             "Give ONLY 2 sentences: one describing the data situation vaguely, one stating the goal. "
                             "Do NOT mention HIPAA, EU borders, IT politics, budget, timelines, compliance, or any specific constraint. "
                             "Do NOT say 'we have challenges' or 'there are hurdles' — that implies constraints. "
                             "Just describe the raw situation: what data exists and what you want to achieve. "
                             "End with 'So — what questions do you have for me?' "
                             "Do NOT say 'the candidate' or 'the interview' — you are a client talking to an FDE.)")
        else:
            user_turn = ("(The interview is starting. Give a brief one-sentence opening inviting the candidate to "
                         "ask clarifying questions before they begin designing. Don't restate the scenario.)")
    else:
        user_turn = data.get("message") or "I'm ready to start."

    is_meta = data.get("start") or data.get("wrap_up") or data.get("end_drill")
    diagram = (data.get("diagram") or "").strip()
    if diagram and not is_meta:
        user_turn = f"[Candidate's current whiteboard]\n{diagram}\n\n[Candidate says]\n{user_turn}"

    history = CHATS.get(chat_key, [])
    if is_meta:
        # Meta instructions (start/wrap_up/end_drill) go to the LLM
        # but are NOT persisted in chat history — prevents confusion
        # between meta-prompts and actual candidate utterances.
        llm_messages = [{"role": "system", "content": system_prompt}] + history + [{"role": "user", "content": user_turn}]
    else:
        history.append({"role": "user", "content": user_turn})
        CHATS[chat_key] = history
        llm_messages = [{"role": "system", "content": system_prompt}] + history

    reply_max_tokens = 700 if (data.get("wrap_up") or data.get("end_drill")) else 400
    try:
        resp = client.chat.completions.create(
            model=MODEL, messages=llm_messages,
            max_tokens=reply_max_tokens, extra_body={"reasoning": {"enabled": False}},
        )
    except Exception as e:
        if not is_meta:
            history.pop()
            CHATS[chat_key] = history
        return jsonify({"error": str(e)}), 502
    reply = resp.choices[0].message.content
    if not reply:
        if not is_meta:
            history.pop()
            CHATS[chat_key] = history
        return jsonify({"error": "model returned an empty response — try again"}), 502

    if not is_meta:
        history.append({"role": "assistant", "content": reply})
        CHATS[chat_key] = history
        save_chats()
    elif data.get("start"):
        # Persist the opening statement so it survives page reloads
        history.append({"role": "assistant", "content": reply})
        CHATS[chat_key] = history
        save_chats()

    prose_reply = reply
    if data.get("wrap_up"):
        if incident:
            if "```json" in reply:
                prose_reply = reply.split("```json")[0].strip()
            try:
                raw_tail = reply.split("```json")[1].split("```")[0]
                incident_result = json.loads(raw_tail)
                incident_score = incident_result.get("incident_score")
                triage_ok = bool(incident_result.get("triage_ok"))
                fix_choice_ok = bool(incident_result.get("fix_choice_ok"))
                communication_ok = bool(incident_result.get("communication_ok"))
            except Exception:
                incident_score, triage_ok, fix_choice_ok, communication_ok = None, False, False, False
            log_history({"event": "incident_debrief", "qid": data["question_id"],
                         "incident_score": incident_score, "triage_ok": triage_ok,
                         "fix_choice_ok": fix_choice_ok, "communication_ok": communication_ok})
            return jsonify({"reply": prose_reply, "wrap_up": True, "incident": True,
                            "incident_score": incident_score, "triage_ok": triage_ok,
                            "fix_choice_ok": fix_choice_ok, "communication_ok": communication_ok})
        elif decomposition:
            # Separate judge call — client model never sees the rubric
            transcript_turns = history  # list of {role, content} from the session
            # Get the scenario JSON for the judge
            qid = data["question_id"]
            judge_scenario = V2_SCENARIOS.get(qid)
            if judge_scenario:
                scenario_for_judge = judge_scenario
            else:
                # v1 — construct minimal scenario JSON for judge
                scenario_for_judge = {
                    "id": qid, "title": q.get("title", ""), "prompt": q.get("prompt", ""),
                    "format_version": 1, "triggers": [], "rubric": JUDGE_RUBRIC,
                }
            judge_result = run_judge(
                scenario_for_judge, transcript_turns,
                session_id=f"{qid}@{int(time.time())}",
                scenario_id=qid,
            )
            log_history({"event": "fde_debrief", "qid": qid,
                         "judge_verdict": judge_result.get("band"),
                         "normalized_score": judge_result.get("normalized_score")})
            JUDGES[chat_key] = judge_result
            save_judges()
            return jsonify({"reply": prose_reply, "wrap_up": True,
                             "decomposition": True,
                             "judge": judge_result})
        prose_reply, missed_concepts, rushed_to_design, communication_score, communication_note, rubric_scores = split_wrap_up_reply(reply, taxonomy_for(q))
        self_rated = [c for c in (data.get("self_rated") or []) if c in taxonomy_for(q)]
        verdict = hire_verdict(missed_concepts, rushed_to_design, communication_score, rubric_scores)
        max_tier = None
        if scaling:
            try:
                raw_tail = reply.split("```json")[1].split("```")[0]
                max_tier = json.loads(raw_tail).get("max_tier_reached")
            except Exception:
                pass
        log_history({"event": "design_debrief", "qid": data["question_id"], "missed_concepts": missed_concepts,
                     "rushed_to_design": rushed_to_design, "self_rated": self_rated,
                     "communication_score": communication_score, "verdict": verdict,
                     "max_tier_reached": max_tier, "rubric_scores": rubric_scores})
        return jsonify({"reply": prose_reply, "wrap_up": True, "missed_concepts": missed_concepts,
                         "concept_taxonomy": taxonomy_for(q), "rubric": DESIGN_RUBRIC_44,
                         "rubric_scores": rubric_scores, "retro_questions": RETRO_QUESTIONS,
                         "self_rated": self_rated,
                         "rushed_to_design": rushed_to_design, "communication_score": communication_score,
                         "communication_note": communication_note, "verdict": verdict,
                         "max_tier_reached": max_tier})

    return jsonify({"reply": prose_reply, "wrap_up": bool(data.get("wrap_up"))})



@bp.route("/api/export", methods=["POST"])
def export_session():
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
    data = request.json
    qid = data.get("question_id", "")
    if not qid:
        return jsonify({"error": "question_id required"}), 400
    decomposition = bool(data.get("decomposition"))
    chat_key = qid + (":decomposition" if decomposition else "")
    turns = CHATS.get(chat_key, [])
    if not turns:
        return jsonify({"error": f"Session not found for {chat_key}"}), 404
    q = QUESTIONS.get(qid) or V2_SCENARIOS.get(qid) or {}
    judge_result = JUDGES.get(chat_key) if decomposition else None
    md = _generate_report(qid, q, turns, judge_result)
    return md, 200, {"Content-Type": "text/markdown; charset=utf-8"}



@bp.route("/api/calibration", methods=["POST"])
def calibration():
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
    data = request.json
    qid = data.get("question_id", "")
    if not qid:
        return jsonify({"error": "question_id required"}), 400
    # Fixtures are keyed by canonical scenario id. decomposition-1 is an alias for
    # decomp_hospital_readmission, so map it explicitly.
    lookup_id = "decomp_hospital_readmission" if qid == "decomposition-1" else qid
    golds = CALIBRATION_FIXTURES.get(lookup_id)
    if not golds:
        return jsonify({"error": "no calibration transcript for this scenario"}), 404
    dims = {}
    q = QUESTIONS.get(qid) or V2_SCENARIOS.get(qid) or {}
    for d in (q.get("rubric", {}).get("dimensions", []) if q else []):
        dims[d.get("id")] = {"name": d.get("name", ""), "weight": d.get("weight", 1.0)}
    return jsonify({
        "scenario_id": qid,
        "dimensions": dims,
        "golds": [
            {
                "file": g["file"],
                "note": g["note"],
                "band": g["expected"].get("band"),
                "band_tolerance": g["expected"].get("band_tolerance", []),
                "dimension_assertions": g["expected"].get("dimension_assertions", {}),
                "red_flags_must_not_contain": g["expected"].get("red_flags_must_not_contain", []),
            }
            for g in golds
        ],
    })



@bp.route("/api/transcribe", methods=["POST"])
def transcribe_audio():
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
    if not DEEPGRAM_API_KEY:
        return jsonify({"error": "Deepgram API key not configured"}), 500
    if "audio" not in request.files:
        return jsonify({"error": "No audio file provided"}), 400
    audio_file = request.files["audio"]
    audio_bytes = audio_file.read()
    if not audio_bytes:
        return jsonify({"error": "Empty audio"}), 400
    try:
        resp = requests.post(
            "https://api.deepgram.com/v1/listen",
            headers={
                "Authorization": f"Token {DEEPGRAM_API_KEY}",
                "Content-Type": audio_file.content_type or "audio/webm",
            },
            params={"model": "nova-2", "punctuate": "true", "language": "en"},
            data=audio_bytes,
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()
        transcript = (
            result.get("results", {})
            .get("channels", [{}])[0]
            .get("alternatives", [{}])[0]
            .get("transcript", "")
        )
        return jsonify({"transcript": transcript})
    except Exception as e:
        log.exception("transcribe_audio: unhandled exception")
        return jsonify({"error": f"Transcription failed: {str(e)}"}), 500



@bp.route("/api/tts", methods=["POST"])
def text_to_speech():
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
    if not DEEPGRAM_API_KEY:
        return jsonify({"error": "Deepgram API key not configured"}), 500
    data = request.json
    text = (data or {}).get("text", "").strip()
    if not text:
        return jsonify({"error": "text required"}), 400
    try:
        resp = requests.post(
            "https://api.deepgram.com/v1/speak",
            headers={
                "Authorization": f"Token {DEEPGRAM_API_KEY}",
                "Content-Type": "application/json",
            },
            params={"model": "aura-orion-en"},
            json={"text": text},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.content, 200, {"Content-Type": "audio/mpeg"}
    except Exception as e:
        log.exception("text_to_speech: unhandled exception")
        return jsonify({"error": f"TTS failed: {str(e)}"}), 500



@bp.route("/api/coach", methods=["POST"])
def coach():
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
    data = request.json
    msg = (data.get("message") or "").strip()
    turn = int(data.get("turn", 1))
    if not msg or turn < 1:
        return jsonify({"hint": None})

    hints = []

    # T1: Jumping to solution too early
    if turn <= 3 and SOLUTION_WORDS.search(msg):
        hints.append("You're proposing a solution. Step back — what clarifying questions do you still have about the problem?")

    # T2: Missing constraints
    if turn >= 3 and not CONSTRAINT_WORDS.search(msg):
        hints.append("Have you asked about constraints yet? Budget, timeline, compliance, and stakeholder concerns all shape the approach.")

    # T3: Oversimplifying
    if OVERSIMPLIFY_WORDS.search(msg):
        hints.append("That sounds like an oversimplification. What assumptions are you making and what could go wrong?")

    # T4: No risk/fallback awareness by turn 5+
    if turn >= 5 and not RISK_WORDS.search(msg):
        hints.append("You haven't mentioned what happens if the first approach fails. Consider a fallback or contingency plan.")

    if hints:
        return jsonify({"hint": hints[0]})

    return jsonify({"hint": None})





@bp.route("/api/interview-history")
def interview_history():
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
    """Replays a design interview's chat turns paired with the whiteboard state as it stood at
    each turn — reuses CHATS as-is (the diagram is already embedded in each user turn's stored
    content), no separate snapshot storage needed."""
    qid = request.args.get("question_id", "")
    adversarial = request.args.get("adversarial") == "1"
    requirements_only = request.args.get("requirements_only") == "1"
    scaling = request.args.get("scaling") == "1"
    incident = request.args.get("incident") == "1"
    decomposition = request.args.get("decomposition") == "1"
    chat_key = qid + (":clarify" if requirements_only else (":adversarial" if adversarial else (":scaling" if scaling else (":incident" if incident else (":decomposition" if decomposition else "")))))

    turns = []
    diagram = ""
    for msg in CHATS.get(chat_key, []):
        content = msg["content"]
        if msg["role"] == "user":
            m = WHITEBOARD_WRAP_RE.match(content)
            if m:
                diagram, text = m.group(1), m.group(2)
            else:
                text = content
        else:
            text = split_wrap_up_reply(content)[0] if "```json" in content else content
        turns.append({"role": msg["role"], "text": text, "diagram": diagram})
    return jsonify({"turns": turns})



@bp.route("/api/replay-comments")
def replay_comments():
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
    """Comments anchored to a turn index in a shared replay link — same chat_key as
    interview-history, so no separate lookup/auth needed to find the right thread."""
    chat_key = _replay_chat_key(request.args)
    return jsonify({"comments": REPLAY_COMMENTS.get(chat_key, [])})



@bp.route("/api/replay-comment", methods=["POST"])
def replay_comment():
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
    data = request.json
    chat_key = _replay_chat_key(data)
    text = (data.get("text") or "").strip()
    author = (data.get("author") or "").strip() or "anonymous"
    turn_idx = data.get("turn_idx")
    if not text or not isinstance(turn_idx, int):
        return jsonify({"error": "text and turn_idx required"}), 400
    comment = {"turn_idx": turn_idx, "author": author, "text": text, "ts": datetime.now().isoformat()}
    REPLAY_COMMENTS.setdefault(chat_key, []).append(comment)
    save_replay_comments()
    return jsonify({"comment": comment})



@bp.route("/api/postmortem", methods=["POST"])
def postmortem():
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
    """Log a question from a REAL interview (not this app), classify it against the same taxonomy
    used for practice questions, and fold it into HISTORY so it counts toward weak-areas/mastery
    tracking exactly like a practice miss would."""
    data = request.json
    question = (data.get("question") or "").strip()
    qtype = data.get("qtype")
    ok = bool(data.get("ok"))
    if not question or qtype not in ("sql", "python", "design"):
        return jsonify({"error": "question and qtype (sql/python/design) required"}), 400

    if qtype == "design":
        vocab = CONCEPT_TAXONOMY
        label_field = "concept"
    else:
        vocab = sorted(set(topic for _, topic in TOPIC_KEYWORDS))
        label_field = "topic"

    prompt = f"""Classify this real interview question into exactly ONE label from the list below — pick the
closest match even if imperfect, never invent a new label.

Labels: {", ".join(vocab)}

Question: "{question}"

Respond ONLY strict JSON, no markdown fences, no commentary:
{{"label": "one label from the list, verbatim"}}"""

    label = vocab[0]
    try:
        resp = client.chat.completions.create(
            model=MODEL, messages=[{"role": "user", "content": prompt}],
            max_tokens=50, temperature=0, extra_body={"reasoning": {"enabled": False}},
        )
        raw = chat_content(resp)
        raw = raw[raw.index("{"):raw.rindex("}") + 1]
        candidate = json.loads(raw).get("label", "")
        if candidate in vocab:
            label = candidate
    except Exception:
        pass  # falls back to vocab[0] — still logs the postmortem, just under a rough label

    entry = {"event": "postmortem", "question": question, "qtype": qtype, "ok": ok, label_field: label}
    log_history(entry)
    return jsonify({label_field: label})



@bp.route("/api/reference-design", methods=["POST"])
def reference_design():
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
    """Post-hoc only — called after wrap-up, never during the live interview."""
    data = request.json
    q = QUESTIONS.get(data["question_id"])
    if not q or q["lang"] != "design":
        return jsonify({"error": "not found"}), 404

    coverage = ("pipeline shape (batch/stream/hybrid), key storage choices, and how it handles idempotency, "
                "backfills, schema evolution, and data quality" if q.get("track") != "ai" else
                "retrieval/context strategy, model and serving choices, and how it handles grounding/hallucination, "
                "evals, cost/latency, and production monitoring")
    prompt = f"""You are a {persona_for(q)}. The candidate just finished a mock interview and its debrief for the scenario below and asked to see a reference design to compare against — this is now a learning aid, not part of the live interview, so you may reveal a concrete answer.

Scenario: {q['title']}
{q['prompt']}

Give a concise reference design covering: {coverage}.

Also express the same design as a simple box-and-arrow diagram using this exact schema (one line per shape):
Box: <short component label> [<layer>]
Arrow: <from label> -> <to label>
where <layer> is one of: source, processing, storage, consumer. Reuse the exact same labels between boxes and arrows. Keep it to 5-9 boxes.

Respond ONLY strict JSON, no markdown fences, no commentary:
{{"bullets": ["one design point per bullet, 6-9 bullets total, no leading dash"], "diagram": ["Box: ... [layer]", "Arrow: A -> B", ...]}}"""

    try:
        resp = client.chat.completions.create(
            model=MODEL, messages=[{"role": "user", "content": prompt}],
            max_tokens=600, temperature=0, extra_body={"reasoning": {"enabled": False}},
        )
        raw = chat_content(resp)
        raw = raw[raw.index("{"):raw.rindex("}") + 1]
        result = json.loads(raw)
        return jsonify({"bullets": result.get("bullets", []), "diagram": result.get("diagram", [])})
    except Exception as e:
        log.exception("reference_design: unhandled exception")
        return jsonify({"error": str(e)}), 502



@bp.route("/api/adversarial-design", methods=["POST"])
def adversarial_design():
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
    """Generates a flawed reference design + its flaw list to seed the whiteboard before an
    adversarial 'break this design' drill starts. The flaw list never reaches the client verbatim
    as text — the frontend only uses it to prime /api/interview's system prompt server-side."""
    data = request.json
    q = QUESTIONS.get(data["question_id"])
    if not q or q["lang"] != "design":
        return jsonify({"error": "not found"}), 404

    concept_list = ", ".join(taxonomy_for(q))
    prompt = f"""You are a {persona_for(q)} preparing an adversarial "break this design" drill for the scenario below.

Scenario: {q['title']}
{q['prompt']}

Design a plausible-looking but flawed architecture for this scenario — something a mediocre candidate might propose, with 2-4 deliberate weaknesses a strong candidate should be able to spot. Each flaw must map to one of these concepts: [{concept_list}].

Express the design as a simple box-and-arrow diagram using this exact schema (one line per shape):
Box: <short component label> [<layer>]
Arrow: <from label> -> <to label>
where <layer> is one of: source, processing, storage, consumer. Reuse the exact same labels between boxes and arrows. Keep it to 5-9 boxes.

Respond ONLY strict JSON, no markdown fences, no commentary:
{{"diagram": ["Box: ... [layer]", "Arrow: A -> B", ...], "flaws": [{{"concept": "one of the fixed concepts above", "note": "one sentence describing the specific weakness in this design"}}]}}"""

    try:
        resp = client.chat.completions.create(
            model=MODEL, messages=[{"role": "user", "content": prompt}],
            max_tokens=600, temperature=0, extra_body={"reasoning": {"enabled": False}},
        )
        raw = chat_content(resp)
        raw = raw[raw.index("{"):raw.rindex("}") + 1]
        result = json.loads(raw)
        flaws = [f for f in result.get("flaws", []) if f.get("concept") in taxonomy_for(q)]
        return jsonify({"diagram": result.get("diagram", []), "flaws": flaws})
    except Exception as e:
        log.exception("adversarial_design: unhandled exception")
        return jsonify({"error": str(e)}), 502



@bp.route("/api/incident-scenario", methods=["POST"])
def incident_scenario():
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
    """Generates a vivid failure scenario for the 3am stress-test drill, grounded in
    the design question's scenario."""
    data = request.json
    q = QUESTIONS.get(data["question_id"])
    if not q or q["lang"] != "design":
        return jsonify({"error": "not found"}), 404

    prompt = f"""You are a senior SRE running an incident-response drill for the scenario below.

Scenario: {q['title']}
{q['prompt']}

Generate a vivid, specific production failure scenario that could realistically happen in this system. Include:
- Which pipeline stage broke and what the symptoms are (specific alerts, error messages, dashboard readings)
- Customer impact scope (what fraction of users affected, what's visibly wrong)
- Time pressure (what time it is, how long before business impact escalates)
- One misleading clue that might send the candidate down the wrong path initially

The scenario should require the candidate to triage, diagnose, stabilize, and fix — not just re-architect.

Respond ONLY strict JSON, no markdown fences:
{{"scenario": "2-4 sentences describing the incident vividly",
  "misleading_clue": "one sentence describing a plausible red herring",
  "key_actions": ["3-4 things a strong responder would do in order"]}}"""
    try:
        resp = client.chat.completions.create(
            model=MODEL, messages=[{"role": "user", "content": prompt}],
            max_tokens=500, temperature=0.3, extra_body={"reasoning": {"enabled": False}},
        )
        raw = chat_content(resp)
        raw = raw[raw.index("{"):raw.rindex("}") + 1]
        result = json.loads(raw)
        return jsonify({"scenario": result.get("scenario", ""),
                        "misleading_clue": result.get("misleading_clue", ""),
                        "key_actions": result.get("key_actions", [])})
    except Exception as e:
        log.exception("incident_scenario: unhandled exception")
        return jsonify({"error": str(e)}), 502



@bp.route("/api/staff-comparison", methods=["POST"])
def staff_comparison():
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
    """After a design interview, generates a side-by-side 'what you said vs what a Staff
    engineer would have said' comparison at key decision points."""
    data = request.json
    q = QUESTIONS.get(data["question_id"])
    if not q or q["lang"] != "design":
        return jsonify({"error": "not found"}), 404

    adversarial = bool(data.get("adversarial"))
    scaling = bool(data.get("scaling"))
    incident = bool(data.get("incident"))
    chat_key = data["question_id"] + (":adversarial" if adversarial else (":scaling" if scaling else (":incident" if incident else "")))
    turns = CHATS.get(chat_key, [])
    if len(turns) < 3:
        return jsonify({"error": "not enough conversation to compare — have a few more exchanges first"}), 400

    transcript = "\n".join(
        f"({'Interviewer' if t['role'] == 'assistant' else 'Candidate'}): {t['content']}"
        for t in turns[-20:]  # last 20 turns max
    )
    prompt = f"""You are a Staff+ Data Engineer reviewing a mock interview transcript. Identify 3-5 key decision points where the candidate's answer differed from what a Staff-level engineer would say.

For each decision point:
- "moment": what the candidate actually said (quote or paraphrase)
- "staff_says": what a Staff engineer would say instead
- "delta": the specific gap (knowledge, depth, awareness, framing)
- "why_it_matters": one sentence on the real-world consequence of this gap

Scenario: {q['title']}
{q['prompt']}

Transcript:
{transcript}

Respond ONLY strict JSON, no markdown fences:
{{"comparisons": [{{"moment": "...", "staff_says": "...", "delta": "...", "why_it_matters": "..."}}]}}"""
    try:
        resp = client.chat.completions.create(
            model=MODEL, messages=[{"role": "user", "content": prompt}],
            max_tokens=800, temperature=0, extra_body={"reasoning": {"enabled": False}},
        )
        raw = chat_content(resp)
        raw = raw[raw.index("{"):raw.rindex("}") + 1]
        result = json.loads(raw)
        return jsonify({"comparisons": result.get("comparisons", [])})
    except Exception as e:
        log.exception("staff_comparison: unhandled exception")
        return jsonify({"error": str(e)}), 502


# qid -> {title, prompt, key_points} — session-only re-rolled tradeoff scenarios targeting the
# same concept_tag, so practicing a weak concept isn't capped at the 5 fixed bank scenarios.
# Falls back to the static bank entry whenever a question hasn't been re-rolled.

@bp.route("/api/tradeoff-regenerate", methods=["POST"])
def tradeoff_regenerate():
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
    data = request.json
    q = QUESTIONS.get(data["question_id"])
    if not q or q["lang"] != "tradeoff":
        return jsonify({"error": "not found"}), 404

    resume = PROGRESS.get("_resume")
    resume_hint = ""
    if resume:
        skills_raw = resume.get("skills", [])[:5]
        domains_raw = resume.get("domains", [])[:3]
        skills = [sk.get("name") if isinstance(sk, dict) else sk for sk in skills_raw]
        domains = [dm.get("name") if isinstance(dm, dict) else dm for dm in domains_raw]
        if skills or domains:
            resume_hint = f"\nThe candidate's background: skills = {', '.join(skills)}; domains = {', '.join(domains)}. Ground the scenario in their domain when possible."

    prompt = f"""You are writing a forced-choice system-design tradeoff drill for interview practice, targeting the
same underlying concept as the example below, but with a different concrete scenario (different domain,
numbers, and framing) so it can't be memorized.

Concept: {q['concept_tag'].replace('_', ' ')}
Existing example (for concept reference only — don't reuse its scenario): {q['title']} — {q['prompt']}
{resume_hint}
Respond ONLY strict JSON, no markdown fences, no commentary:
{{"title": "short scenario title, under 8 words", "prompt": "2-4 sentences posing a forced choice between two concrete options for a new scenario", "key_points": ["3-4 bullets, private grading key, what a strong justification must touch on"]}}"""

    try:
        resp = client.chat.completions.create(
            model=MODEL, messages=[{"role": "user", "content": prompt}],
            max_tokens=400, temperature=0.6, extra_body={"reasoning": {"enabled": False}},
        )
        raw = chat_content(resp)
        raw = raw[raw.index("{"):raw.rindex("}") + 1]
        result = json.loads(raw)
        title, new_prompt, key_points = result.get("title", ""), result.get("prompt", ""), result.get("key_points", [])
        if not (title and new_prompt and key_points):
            raise ValueError("incomplete regeneration")
        TRADEOFF_ROLLS[q["id"]] = {"title": title, "prompt": new_prompt, "key_points": key_points}
        return jsonify({"title": title, "prompt": new_prompt})
    except Exception as e:
        log.exception("tradeoff_regenerate: unhandled exception")
        return jsonify({"error": str(e)}), 502



@bp.route("/api/tradeoff-grade", methods=["POST"])
def tradeoff_grade():
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
    data = request.json
    q = QUESTIONS.get(data["question_id"])
    if not q or q["lang"] != "tradeoff":
        return jsonify({"error": "not found"}), 404
    answer = (data.get("answer") or "").strip()
    if not answer:
        return jsonify({"ok": False, "feedback": "Write your choice and reasoning first."})

    roll = TRADEOFF_ROLLS.get(q["id"])
    title = roll["title"] if roll else q["title"]
    scenario_prompt = roll["prompt"] if roll else q["prompt"]
    points = roll["key_points"] if roll else q.get("key_points", [])
    key_points = "\n".join(f"- {k}" for k in points)
    prompt = f"""You are a terse senior data engineering interviewer grading a candidate's tradeoff justification in a forced-choice drill.

Scenario: {title}
{scenario_prompt}

What a strong justification touches on (private grading key — NEVER reveal this to the candidate):
{key_points}

Candidate's answer: "{answer}"

Judge whether their choice is defensible and their reasoning actually engages with the real tradeoff driving it — they don't need to hit every point above, but the core tradeoff should be present, not just the pattern name.

Respond with ONLY strict JSON, no markdown fences, no commentary:
{{"ok": true or false, "feedback": "2-3 sentences: what they got right, what's missing or wrong. Never reveal the grading key verbatim."}}"""

    try:
        resp = client.chat.completions.create(
            model=MODEL, messages=[{"role": "user", "content": prompt}],
            max_tokens=250, temperature=0, extra_body={"reasoning": {"enabled": False}},
        )
        raw = chat_content(resp)
        raw = raw[raw.index("{"):raw.rindex("}") + 1]
        result = json.loads(raw)
        ok = bool(result.get("ok"))
        feedback = result.get("feedback", "")
    except Exception:
        return jsonify({"ok": True, "feedback": "(couldn't auto-grade — proceeding anyway)"})

    if ok:
        schedule_review(q["id"], ATTEMPTS.get(q["id"], 0))
    else:
        ATTEMPTS[q["id"]] = ATTEMPTS.get(q["id"], 0) + 1
    log_history({"event": "tradeoff", "qid": q["id"], "concept": q.get("concept_tag", ""), "ok": ok})
    return jsonify({"ok": ok, "feedback": feedback})



@bp.route("/api/tradeoff-spar", methods=["POST"])
def tradeoff_spar():
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
    """Back-and-forth debate on a tradeoff drill — reuses the CHATS persistence pattern with a
    ':spar' chat_key, same as the design chat's ':clarify'/':adversarial' suffixes."""
    data = request.json
    q = QUESTIONS.get(data.get("question_id", ""))
    if not q or q["lang"] != "tradeoff":
        return jsonify({"error": "not found"}), 404
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"error": "say something first"}), 400

    roll = TRADEOFF_ROLLS.get(q["id"])
    title = roll["title"] if roll else q["title"]
    scenario_prompt = roll["prompt"] if roll else q["prompt"]

    system_prompt = f"""You are a sharp system-design interviewer sparring live with a candidate on a forced-choice tradeoff.

Scenario: {title}
{scenario_prompt}

Rules:
- Always argue AGAINST whatever position the candidate is currently defending — never simply agree.
- If their latest argument is weak, hand-wavy, or ignores a real cost, press on that specific gap.
- If their latest argument is genuinely strong and engages the real tradeoff, explicitly concede that point, then pivot: start arguing the OTHER side yourself (steelman the position they just abandoned), so they now have to defend it in turn.
- Stay concrete and scenario-specific, never generic. 2-4 sentences, no preamble."""

    chat_key = q["id"] + ":spar"
    history = CHATS.setdefault(chat_key, [])
    history.append({"role": "user", "content": message})
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "system", "content": system_prompt}] + history,
            max_tokens=250,
            extra_body={"reasoning": {"enabled": False}},
        )
        reply = resp.choices[0].message.content
        if not reply:
            raise ValueError("model returned an empty response")
    except Exception as e:
        history.pop()
        return jsonify({"error": str(e)}), 502
    history.append({"role": "assistant", "content": reply})
    save_chats()
    return jsonify({"reply": reply})






@bp.route("/api/start")
def smart_start():
    import app as _app  # lazy: entire app namespace (request-time)
    globals().update({k: v for k, v in vars(_app).items() if not k.startswith('__')})
    """Phase 1: one-tap entry. Picks the single most useful question to do right now:
    a due review > a weak-area unsolved > resume-matched unsolved > otherwise the next unsolved one.
    Accepts ?lane=focused|weak|mock to bias the pick (the practice command-center lanes)."""
    lane = (request.args.get("lane") or "").strip().lower()

    # the default "focused rep" path: due review first, then weak-area, then next unsolved
    due = [qid for qid, q in QUESTIONS.items() if is_due(qid) and not is_solved(qid)]
    if not lane or lane == "focused":
        if due:
            return jsonify({"id": due[0], "reason": "due_review"})

    # weak-area bias: use recent miss topics to pick an unsolved question in a weak topic
    weak = set(recurring_missed_topics())
    unsolved = [(qid, q) for qid, q in QUESTIONS.items() if not is_solved(qid)]
    weak_hits = [(qid, q) for qid, q in unsolved if topic_for(q) in weak and q["lang"] in ("sql", "python")]
    if lane == "weak":
        if weak_hits:
            return jsonify({"id": weak_hits[0][0], "reason": "weak_area"})
        if due:
            return jsonify({"id": due[0], "reason": "due_review"})

    if (not lane or lane == "focused") and weak_hits:
        return jsonify({"id": weak_hits[0][0], "reason": "weak_area"})

    # resume-skill bias: if resume uploaded, prefer questions matching claimed skills/domains
    resume = PROGRESS.get("_resume")
    if resume:
        claimed = [s.lower() for s in resume.get("skills", []) + resume.get("domains", [])]
        if claimed:
            def _matches_resume(q):
                text = (q.get("title", "") + " " + q.get("prompt", "") + " " + q.get("concept", "")).lower()
                return any(c in text for c in claimed if len(c) > 2)
            resume_hits = [(qid, q) for qid, q in unsolved if _matches_resume(q) and q["lang"] in ("sql", "python")]
            if resume_hits:
                return jsonify({"id": random.choice(resume_hits)[0], "reason": "resume_match"})

    pool = [qid for qid, q in unsolved if q["lang"] in ("sql", "python")]
    if pool:
        return jsonify({"id": random.choice(pool), "reason": "next_unsolved"})
    design_unsolved = [qid for qid, q in QUESTIONS.items() if not is_solved(qid)]
    if design_unsolved:
        return jsonify({"id": random.choice(design_unsolved), "reason": "any"})
    return jsonify({"id": None, "reason": "none", "message": "All questions solved — pick any to review."})




