# pawscode — end-to-end testing guide

This is a manual walkthrough for testing every button and feature in pawscode by hand. There's no automated test suite for the UI — this doc *is* the test suite. Follow it top to bottom the first time; after that, jump to whichever section you changed.

Each section says what to click, what you should see, and what "broken" looks like.

## Setup

```
cd pawscode
python3 app.py
```

Open `http://127.0.0.1:5050/` in a browser. You should see a sidebar on the left (filter box + SQL / PYTHON / SYSTEM DESIGN / TRADEOFF DRILLS groups) and an empty state in the middle.

---

## 1. SQL / Python questions (the core solve loop)

**Worked example:** pick any SQL question from the sidebar, e.g. the first one under `SQL`.

1. Click a question in the sidebar. The prompt loads on the left, a code editor appears in the middle, and the question's timer starts (top-right of the question card, counts up).
2. **Plan gate.** Before you can type code, there's a text box: *"Your approach + time complexity, before you code…"* with a **Check approach** button.
   - Type something vague like `"idk"` and click **Check approach**. It should come back rejecting it (still locked).
   - Type a real plan, e.g. `"group by user_id, count rows, O(n)"`, click **Check approach** again. It should approve — the editor unlocks (you can now type/run code).
   - *Broken if:* editor is typable before approval, or a good plan never unlocks it.
3. **Run.** Write a plausible (even wrong) solution and click **▶ Run**. This runs against a *sample* only — you'll see sample output/pass-fail, not a real grade.
4. **Submit.** Click **Submit** to run the full grade. On a pass, the question gets marked solved (checkmark/progress bar in the sidebar ticks up) and a **debrief row** appears.
5. **Debrief.** Two inputs appear: *"Actual time/space complexity…"* and *"Edge cases you'd test…"*, plus a **Debrief** button.
   - Fill both in (e.g. `O(n)` / `empty table, nulls in group key`) and click **Debrief**. You should get ✓/✗ feedback lines on both complexity and edge-case coverage.
   - *Broken if:* clicking Debrief with either field empty doesn't warn you and silently does nothing useful.
6. **Post-solve extras** (buttons next to Run/Submit unlock only after you've solved the question):
   - **💡 Hint** — works any time, gives a nudge without the answer.
   - **🔁 Twist** — disabled until solved (hover shows "Solve it first"); after solving, click it for a follow-up variant question in the chat.
   - **👣 Dry run** (Python only) — disabled until solved; after solving, click it, then use **Check my trace** to self-trace your code's execution against a description the LLM gives you.
7. Reload the page and reselect the same question — your code, plan input, complexity/edge-case answers should all still be there (state is cached client-side/server-side per question).

---

## 2. Spaced repetition / dashboard basics

1. Click **Dashboard** (top right of the practice page).
2. You should see three stat cards: **Solved** (x/total, split by SQL/Python), **Due for review**, **Debriefs completed**.
3. Solve a couple more questions, revisit the dashboard — **Solved** and **Debriefs completed** should tick up, and the **Interview-readiness signals** card should start showing complexity/edge-case accuracy bars instead of the empty state.
4. **Weak areas — fails by topic**: intentionally submit a wrong answer on a question, then check this card — the topic should appear with a count.
5. Click **← back to practice** to return.

---

## 3. System Design — Mock Interview Mode

**Worked example:** click **Clickstream Event Pipeline** under `SYSTEM DESIGN`.

The interview auto-starts: the tutor opens with a question like *"What clarifying questions do you have about the clickstream pipeline requirements?"* — a chat panel on the right, and a whiteboard canvas in the middle.

### 3a. Chat
- Type a clarifying question (e.g. *"What's the expected event volume and latency requirement?"*) in the input box at the bottom and hit **➤** (or Enter). The tutor replies with concrete numbers/constraints.
- **🎤 mic button**: hold to record a voice question. (This may show a "not configured" message if no Whisper API key is set up — that's expected, not a bug, unless you've configured one.)

### 3b. Whiteboard
Toolbar across the top of the canvas: **↖ Select**, **▭ Box**, **→ Arrow**, **🗒 Note**, plus **Delete** / **Clear** on the right.

1. **Box tool** — click it, then drag on the canvas to draw a box. Type a label (a text input appears inline). Try a long label like *"Kafka topic for raw clickstream events ingestion"* — the box should wrap the text across multiple lines and grow taller to fit, not overflow.
2. **Layer tagging** — with a box selected (Select tool, click the box), press **L** repeatedly. Each press cycles the box's border color: none → teal (source) → purple (processing) → green (storage) → gold (consumer) → back to none. Hover the box to see a tooltip naming the current layer.
3. **Duplicate** — with a box selected, press **Cmd+D** (Mac) or **Ctrl+D** (Windows/Linux). A copy appears offset slightly down-right, and becomes the new selection.
4. **Arrow tool** — click it, click a source box, then click a target box. A line connects them with an arrowhead.
   - **Editable arrow labels** — double-click directly on the arrow line. An inline text box appears; type a label (e.g. *"produces to"*) and click away — the label renders centered on the line.
5. **Note tool** — click it, drag to place a sticky note. Notes wrap text the same way boxes do, and have a resize handle (bottom-right corner) you can drag to resize manually.
6. **Delete** — select any shape and press **Delete**/**Backspace**, or click the **Delete** button. It should disappear.
7. **Clear** — click **Clear**. It should ask for confirmation before wiping the whole canvas.
8. Whatever you draw is fed to the tutor automatically on your next chat message — you don't need to describe your diagram in words.

### 3c. Wrapping up (self-rating + debrief checklist)
1. Once you've had a few exchanges, click **Wrap up interview**.
2. A panel appears: *"Before you see the debrief — which of these do you think you missed or went shallow on?"* with a checkbox for each of the 9 core concepts (clarifying requirements, batch vs stream choice, partitioning/hot key skew, idempotency/dedup, backfill/reprocessing, schema evolution, replication/consistency, data quality/observability, storage format choice).
3. Check the ones you *think* you missed (this is a calibration exercise — be honest, don't peek ahead), then click **Submit self-rating & get debrief**.
4. The tutor's prose debrief appears, followed by a **checklist** of all 9 concepts, each marked:
   - ✅ covered
   - ❌ missed — blind spot (you didn't flag it, but you missed it)
   - 🟡 missed — you caught it (you flagged it, and you were right)
   - ⚠️ you flagged this but it was actually fine (you were too hard on yourself)
   - *Broken if:* the checklist doesn't show, or a concept you self-flagged never gets cross-referenced.
5. A **📐 Show reference design** button appears below the debrief — click it once to reveal a concrete reference architecture for the scenario. It should only ever appear *after* wrap-up, never during the live interview (if you see it mid-interview, that's a bug). It disappears after you use it.

### 3d. Clarify-only drill
1. Load a fresh design question. Click **🎯 Clarify-only drill** instead of starting the normal interview.
2. The whiteboard should be hidden — this mode is chat-only, practicing *only* asking clarifying questions (you shouldn't be able to propose a design).
3. Ask a few questions, then click **End drill**. You should get a short debrief on the quality/breadth of your questions rather than a design debrief.

---

## 4. Tradeoff drills

**Worked example:** click a question under `TRADEOFF DRILLS`, e.g. *"Batch ETL vs. CDC for Keeping an Analytical Store Fresh"*.

1. You'll see a scenario prompt and a single text box: *"Your choice + the tradeoff reasoning behind it…"*.
2. Type a justification (e.g. *"CDC — the 5-10 min latency requirement rules out nightly batch, and CDC avoids re-scanning the whole table"*) and click **Grade my answer**.
3. You should get pass/fail feedback against the key tradeoff points. On a pass, the question is marked solved and enters the spaced-repetition queue (check **Due for review** on the dashboard later).

---

## 5. Dashboard — system design signals

After completing at least one design interview wrap-up:

1. Go to **Dashboard**. The **System design — concepts to revisit** card should now show:
   - A line like *"Jumped into design before clarifying requirements: X% of N interviews"* — this tracks whether you designed before asking clarifying questions. Rush a design next time (propose storage/architecture immediately, skip clarifying questions) to see this percentage climb.
   - A bar per concept, ranked by how often it's been missed across your last few debriefs.
2. **Deep link**: some concept rows render as a clickable link with a `→` arrow (only concepts that have a matching tradeoff drill — not all 9 do). Click one, e.g. *"backfill reprocessing →"*.
   - *Expected:* you land back on the practice page with the matching tradeoff question auto-selected and its sidebar section auto-expanded — no manual hunting required.
   - *Broken if:* it dumps you on an empty state, or the wrong question is selected.

---

## Quick regression checklist (after any whiteboard/interview change)

- [ ] Box text wraps and auto-grows
- [ ] Note text wraps and is still manually resizable
- [ ] L cycles all 4 layer colors + tooltip updates
- [ ] Cmd/Ctrl+D duplicates the selected shape only (not arrows)
- [ ] Double-click an arrow → inline label editor → label renders
- [ ] Wrap-up → self-rate panel → debrief checklist cross-references self-ratings correctly
- [ ] Reference design button only appears post-wrap-up, disappears after one use
- [ ] Dashboard rushed-to-design % and concept deep links reflect real history.json data
