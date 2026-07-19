// 00-config.js — lines 0-36 of original bundle. Key fns: 
// Central debug logger (Step 3.5): silent unless window.APP_BOOT.debug is true.
function log(...args) {
  if (window.APP_BOOT && window.APP_BOOT.debug) {
    console.debug("[loop]", ...args);
  }
}
let cm = CodeMirror.fromTextArea(document.getElementById('editor'), {theme: 'material-darker', lineNumbers: true});
requestAnimationFrame(() => cm.refresh());
new ResizeObserver(() => cm.refresh()).observe(document.getElementById('editor-card'));
let current = null;
let clarifyMode = false;
let selectedPersona = '';
let selectedArchetype = '';
let __compareData = null; // {label, chatHTML, band, score, dimScores}
let adversarialMode = false;
let adversarialFlaws = [];
let scalingMode = false;
let incidentMode = false;
let incidentScenario = '';
let replayTurns = [];
let replayComments = [];
let mockLoop = null; // {ids: [...], stage: 0} — null when no loop is active
let savedChatHTMLBeforeReplay = null;
let savedShapesBeforeReplay = null;
let ttsEnabled = true;
let designChips = [];
let pacingTimer = null;
let lastRunSummary = '';
let __compareMode = null;
const CONCEPT_TAXONOMIES = (window.APP_BOOT && window.APP_BOOT.concept_taxonomies) || [];

const IDLE_NUDGE_MS = 45000;
let idleTimer = null;
let stuck = false;
let nudgeSent = false;
let reinforced = false;
let pendingRecallReview = null;
let stateCache = {}; // qid -> {code, chatHTML, resultsHTML, resultsClass, lastRunSummary, stuck, nudgeSent, reinforced, shapes}
let timers = {}; // qid -> {elapsed, running}
let timerInterval = null;

// ---- design canvas (system design questions) ----
