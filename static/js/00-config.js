// 00-config.js — lines 0-36 of original bundle. Key fns: 
// Central debug logger (Step 3.5): silent unless window.APP_BOOT.debug is true.
function log(...args) {
  if (window.APP_BOOT && window.APP_BOOT.debug) {
    console.debug("[loop]", ...args);
  }
}
// Single fetch wrapper (Step 4): identical to api() but auto-logs every
// network call when debug is on. Migrate call sites from api(...) to api(...).
async function api(path, opts) {
  const t0 = performance.now();
  const method = (opts && opts.method) || "GET";
  const res = await fetch(path, opts);
  log(method, path, res.status, Math.round(performance.now() - t0) + "ms");
  return res;
}
let cm = CodeMirror.fromTextArea(document.getElementById('editor'), {theme: 'material-darker', lineNumbers: true});
requestAnimationFrame(() => cm.refresh());
new ResizeObserver(() => cm.refresh()).observe(document.getElementById('editor-card'));

// Step 5: centralize magic globals into a single App.state source of truth.
// Old global names are kept alive via getters/setters (aliases) so every
// existing reference across modules keeps working until migrated.
window.App = window.App || {};
App.state = {
  current: null,
  clarifyMode: false,
  selectedPersona: '',
  selectedArchetype: '',
  __compareData: null, // {label, chatHTML, band, score, dimScores}
  adversarialMode: false,
  adversarialFlaws: [],
  scalingMode: false,
  incidentMode: false,
  incidentScenario: '',
  replayTurns: [],
  replayComments: [],
  mockLoop: null, // {ids: [...], stage: 0} — null when no loop is active
  savedChatHTMLBeforeReplay: null,
  savedShapesBeforeReplay: null,
  ttsEnabled: true,
  designChips: [],
  pacingTimer: null,
  lastRunSummary: '',
  __compareMode: null,
  idleTimer: null,
  stuck: false,
  nudgeSent: false,
  reinforced: false,
  pendingRecallReview: null,
  stateCache: {}, // qid -> {code, chatHTML, resultsHTML, resultsClass, lastRunSummary, stuck, nudgeSent, reinforced, shapes}
  timers: {}, // qid -> {elapsed, running}
  timerInterval: null,
};
["current","clarifyMode","selectedPersona","selectedArchetype","__compareData","adversarialMode","adversarialFlaws","scalingMode","incidentMode","incidentScenario","replayTurns","replayComments","mockLoop","savedChatHTMLBeforeReplay","savedShapesBeforeReplay","ttsEnabled","designChips","pacingTimer","lastRunSummary","__compareMode","idleTimer","stuck","nudgeSent","reinforced","pendingRecallReview","stateCache","timers","timerInterval"].forEach(function (k) {
  Object.defineProperty(window, k, {
    get: function () { return App.state[k]; },
    set: function (v) { App.state[k] = v; },
    configurable: true,
  });
});
const CONCEPT_TAXONOMIES = (window.APP_BOOT && window.APP_BOOT.concept_taxonomies) || [];

const IDLE_NUDGE_MS = 45000;

// ---- design canvas (system design questions) ----
