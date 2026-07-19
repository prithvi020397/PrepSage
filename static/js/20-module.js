// 20-module.js — lines 36-455 of original bundle. Key fns: wrapText, newShapeId, boxAt, shapeAt, setCanvasTool, svgPoint
let shapes = []; // {id, type:'box'|'text', label, x, y, w, h} | {id, type:'arrow', fromId, toId, label}
let shapeSeq = 1;
let canvasTool = 'select';
let selectedShapeId = null;
let lastClickShapeId = null;
let lastClickTime = 0;
let arrowDraft = null; // {fromId}
let dragState = null; // {id, offsetX, offsetY} or {id, end:'fromId'|'toId'}
let lastCanvasClick = {x: 140, y: 100};
const measureCtx = document.createElement('canvas').getContext('2d');
measureCtx.font = '12px Inter, sans-serif';

function wrapText(text, maxWidth) {
  const words = String(text).split(/\s+/).filter(Boolean);
  if (!words.length) return [''];
  const lines = [];
  let line = words[0];
  for (let i = 1; i < words.length; i++) {
    const test = line + ' ' + words[i];
    if (measureCtx.measureText(test).width > maxWidth) {
      lines.push(line);
      line = words[i];
    } else {
      line = test;
    }
  }
  lines.push(line);
  return lines;
}
let narrationText = '';

function newShapeId() { return 's' + (shapeSeq++); }

function boxAt(x, y) {
  return shapes.find(s => s.type === 'box' && x >= s.x && x <= s.x + s.w && y >= s.y && y <= s.y + s.h);
}

function shapeAt(x, y, type) {
  return shapes.find(s => s.type === type && x >= s.x && x <= s.x + s.w && y >= s.y && y <= s.y + s.h);
}

function setCanvasTool(tool) {
  canvasTool = tool;
  arrowDraft = null;
  document.querySelectorAll('.tool-btn').forEach(b => b.classList.remove('active'));
  const btn = document.getElementById('tool-' + tool);
  if (btn) btn.classList.add('active');
  const svg = document.getElementById('design-canvas');
  if (svg) svg.classList.toggle('select-mode', tool === 'select');
  renderCanvas();
}

function svgPoint(evt) {
  const svg = document.getElementById('design-canvas');
  const rect = svg.getBoundingClientRect();
  return {x: evt.clientX - rect.left, y: evt.clientY - rect.top};
}

function canvasMouseDown(evt) {
  evt.preventDefault();
  const openEdit = document.querySelector('.canvas-inline-edit');
  if (openEdit) openEdit.blur();
  const pt = svgPoint(evt);
  lastCanvasClick = pt;
  const hitBox = boxAt(pt.x, pt.y);
  const hitText = shapeAt(pt.x, pt.y, 'text');

  if (canvasTool === 'box') {
    if (hitBox) return;
    const shape = {id: newShapeId(), type: 'box', label: '', x: snap(pt.x - 55), y: snap(pt.y - 25), w: 110, h: 50};
    shapes.push(shape);
    setCanvasTool('select');
    startInlineEdit(shape);
    return;
  }
  if (canvasTool === 'text') {
    if (hitText) return;
    const shape = {id: newShapeId(), type: 'text', label: '', x: snap(pt.x - 50), y: snap(pt.y - 20), w: 100, h: 40};
    shapes.push(shape);
    setCanvasTool('select');
    startInlineEdit(shape);
    return;
  }
  if (canvasTool === 'arrow') {
    const hitAnchor = hitBox || hitText;
    if (!hitAnchor) return;
    if (!arrowDraft) {
      arrowDraft = {fromId: hitAnchor.id};
      renderCanvas();
    } else if (hitAnchor.id !== arrowDraft.fromId) {
      shapes.push({id: newShapeId(), type: 'arrow', fromId: arrowDraft.fromId, toId: hitAnchor.id, label: ''});
      arrowDraft = null;
      setCanvasTool('select');
      saveCurrentState();
    }
    return;
  }
  // select tool
  const shape = hitBox || hitText;
  if (shape) {
    const now = Date.now();
    const isDoubleClick = lastClickShapeId === shape.id && now - lastClickTime < 400;
    lastClickShapeId = shape.id;
    lastClickTime = now;
    selectedShapeId = shape.id;
    if (isDoubleClick) {
      lastClickShapeId = null;
      renderCanvas();
      startInlineEdit(shape);
      return;
    }
    dragState = {id: shape.id, offsetX: pt.x - shape.x, offsetY: pt.y - shape.y};
  } else {
    lastClickShapeId = null;
    selectedShapeId = null;
  }
  renderCanvas();
}

function canvasMouseMove(evt) {
  if (!dragState) return;
  const pt = svgPoint(evt);
  const shape = shapes.find(s => s.id === dragState.id);
  if (!shape) return;
  if (dragState.end) {
    const hitAnchor = boxAt(pt.x, pt.y) || shapeAt(pt.x, pt.y, 'text');
    if (hitAnchor && hitAnchor.id !== shape[dragState.end === 'fromId' ? 'toId' : 'fromId']) shape[dragState.end] = hitAnchor.id;
  } else if (dragState.resize) {
    shape.w = Math.max(60, snap(pt.x - shape.x));
    shape.h = Math.max(30, snap(pt.y - shape.y));
  } else {
    shape.x = snap(pt.x - dragState.offsetX);
    shape.y = snap(pt.y - dragState.offsetY);
  }
  renderCanvas();
}

function canvasMouseUp() {
  if (dragState) saveCurrentState();
  dragState = null;
}

function startArrowHandleDrag(arrowId, end, evt) {
  evt.stopPropagation();
  selectedShapeId = arrowId;
  dragState = {id: arrowId, end};
}

function deleteSelected() {
  if (!selectedShapeId) return;
  shapes = shapes.filter(s => s.id !== selectedShapeId && s.fromId !== selectedShapeId && s.toId !== selectedShapeId);
  selectedShapeId = null;
  renderCanvas();
  saveCurrentState();
}

function showToast(message) {
  const existing = document.querySelector('.toast');
  if (existing) existing.remove();
  const t = document.createElement('div');
  t.className = 'toast';
  t.textContent = message;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 5000);
}

function showConfirm(message, onConfirm) {
  const overlay = document.createElement('div');
  overlay.className = 'confirm-overlay';
  overlay.innerHTML = '<div class="confirm-box"><div class="confirm-msg"></div><div class="confirm-actions">'
    + '<button class="btn btn-ghost" id="confirm-no">Cancel</button>'
    + '<button class="btn btn-primary" id="confirm-yes">Clear</button></div></div>';
  overlay.querySelector('.confirm-msg').textContent = message;
  overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
  overlay.querySelector('#confirm-no').onclick = () => overlay.remove();
  overlay.querySelector('#confirm-yes').onclick = () => { overlay.remove(); onConfirm(); };
  document.body.appendChild(overlay);
}

function clearCanvas() {
  if (!shapes.length) return;
  showConfirm("Clear the whole whiteboard? This can't be undone.", () => {
    shapes = [];
    selectedShapeId = null;
    renderCanvas();
    saveCurrentState();
  });
}

const GRID = 10;
function snap(v) { return Math.round(v / GRID) * GRID; }

// port-snapped edge point: pick the cardinal side facing the other shape instead of
// a raw center-to-center intersection, so arrows always leave/enter straight (no corner-clipping).
function edgePoint(box, towardX, towardY) {
  const cx = box.x + box.w / 2, cy = box.y + box.h / 2;
  const dx = towardX - cx, dy = towardY - cy;
  if (!dx && !dy) return {x: cx, y: cy};
  if (Math.abs(dx) > Math.abs(dy)) return {x: dx > 0 ? box.x + box.w : box.x, y: cy};
  return {x: cx, y: dy > 0 ? box.y + box.h : box.y};
}

function svgEl(tag, attrs) {
  const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const k in attrs) el.setAttribute(k, attrs[k]);
  return el;
}

const LAYER_COLORS = {
  source: {stroke: '#5ee6d8', fill: 'rgba(94,230,216,0.35)'},
  processing: {stroke: '#7c6cf6', fill: 'rgba(124,108,246,0.35)'},
  storage: {stroke: '#3ddc97', fill: 'rgba(61,220,151,0.35)'},
  consumer: {stroke: '#f5c542', fill: 'rgba(245,197,66,0.35)'}
};
function layerColors(layer) { return LAYER_COLORS[layer] || {stroke: '#9299ab', fill: 'rgba(146,153,171,0.28)'}; }

let roughSvgGen = null;
function getRC(svg) { if (!roughSvgGen) roughSvgGen = rough.svg(svg); return roughSvgGen; }

// small deterministic tilt so notes read as hand-placed sticky notes, not a UI element
function noteTilt(id) { const n = parseInt(id.slice(1), 10) || 0; return (n % 2 === 0 ? 1 : -1) * 1.4; }

 function renderCanvas() {
  log("renderCanvas");
  const svg = document.getElementById('design-canvas');
  if (!svg) return;
  svg.innerHTML = '<defs>'
    + '<pattern id="dot-grid" width="' + GRID * 2 + '" height="' + GRID * 2 + '" patternUnits="userSpaceOnUse">'
    + '<circle cx="1.5" cy="1.5" r="1.5" fill="rgba(255,255,255,0.055)"></circle></pattern>'
    + ['default', 'source', 'processing', 'storage', 'consumer'].map(l => {
        const color = l === 'default' ? '#9299ab' : LAYER_COLORS[l].stroke;
        return '<marker id="arrowhead-' + l + '" markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto">'
          + '<path d="M0,0 L9,4.5 L0,9 z" fill="' + color + '"></path></marker>';
      }).join('')
    + '</defs>';
  svg.appendChild(svgEl('rect', {x: 0, y: 0, width: '100%', height: '100%', fill: 'url(#dot-grid)', 'pointer-events': 'none'}));
  const rc = getRC(svg);
  const byId = Object.fromEntries(shapes.map(s => [s.id, s]));

  if (shapes.length === 0) {
    const hint = svgEl('text', {x: '50%', y: '44%', 'text-anchor': 'middle', class: 'canvas-hint'});
    hint.textContent = 'Sketch your architecture here';
    svg.appendChild(hint);
    const sub = svgEl('text', {x: '50%', y: '44%', dy: '22', 'text-anchor': 'middle', class: 'canvas-hint canvas-hint-sub'});
    sub.textContent = 'Box for a component · Arrow to connect two · Note for assumptions — syncs to the tutor automatically';
    svg.appendChild(sub);
  }

  shapes.filter(s => s.type === 'arrow').forEach(a => {
    const from = byId[a.fromId], to = byId[a.toId];
    if (!from || !to) return;
    const p1 = edgePoint(from, to.x + to.w / 2, to.y + to.h / 2);
    const p2 = edgePoint(to, from.x + from.w / 2, from.y + from.h / 2);
    const selected = a.id === selectedShapeId;
    const color = layerColors(from.layer).stroke;
    const line = rc.line(p1.x, p1.y, p2.x, p2.y, {stroke: color, strokeWidth: selected ? 2.4 : 1.6, roughness: 1.3, bowing: 1});
    line.setAttribute('class', 'shape-arrow' + (selected ? ' selected' : ''));
    line.setAttribute('marker-end', 'url(#arrowhead-' + (from.layer || 'default') + ')');
    line.addEventListener('mousedown', (e) => {
      e.stopPropagation();
      canvasTool = 'select';
      setCanvasTool('select');
      const now = Date.now();
      const isDoubleClick = lastClickShapeId === a.id && now - lastClickTime < 400;
      lastClickShapeId = a.id;
      lastClickTime = now;
      selectedShapeId = a.id;
      renderCanvas();
      if (isDoubleClick) {
        lastClickShapeId = null;
        startArrowLabelEdit(a, (p1.x + p2.x) / 2, (p1.y + p2.y) / 2);
      }
    });
    svg.appendChild(line);
    if (a.label) {
      const t = svgEl('text', {x: (p1.x + p2.x) / 2, y: (p1.y + p2.y) / 2 - 6, style: 'fill:var(--text-faint); font-size:11px;'});
      t.textContent = a.label;
      svg.appendChild(t);
    }
    if (selected) {
      [['fromId', p1], ['toId', p2]].forEach(([end, p]) => {
        const h = svgEl('circle', {cx: p.x, cy: p.y, r: 5, class: 'arrow-handle'});
        h.addEventListener('mousedown', (e) => startArrowHandleDrag(a.id, end, e));
        svg.appendChild(h);
      });
    }
  });

  // baseline nudge: SVG has no reliable cross-browser vertical-center text alignment,
  // so bake the offset into the tspan y instead of relying on dominant-baseline.
  const TEXT_BASELINE_NUDGE = 4;

  shapes.filter(s => s.type === 'box').forEach(b => {
    const lineHeight = 15;
    const lines = wrapText(b.label || '(untitled)', b.w - 16);
    b.h = Math.max(b.h || 50, lines.length * lineHeight + 16);
    const selected = b.id === selectedShapeId;
    const colors = layerColors(b.layer);
    const rect = rc.rectangle(b.x, b.y, b.w, b.h, {
      stroke: colors.stroke, fill: colors.fill, fillStyle: 'hachure', fillWeight: 0.8, hachureGap: 5,
      roughness: 1.15, strokeWidth: selected ? 2.5 : 1.5
    });
    rect.setAttribute('class', 'shape-box' + (selected ? ' selected' : ''));
    const rectTitle = svgEl('title', {});
    rectTitle.textContent = b.layer ? `layer: ${b.layer} (press L to cycle)` : 'select and press L to tag a layer (source/processing/storage/consumer)';
    rect.appendChild(rectTitle);
    svg.appendChild(rect);
    const t = svgEl('text', {x: b.x + b.w / 2, y: b.y + b.h / 2 - (lines.length - 1) * lineHeight / 2 + TEXT_BASELINE_NUDGE, class: 'shape-label'});
    t.style.pointerEvents = 'none';
    lines.forEach((line, i) => {
      const tspan = svgEl('tspan', {x: b.x + b.w / 2, dy: i === 0 ? 0 : lineHeight});
      tspan.textContent = line;
      t.appendChild(tspan);
    });
    svg.appendChild(t);
    if (selected) {
      const handle = svgEl('rect', {x: b.x + b.w - 7, y: b.y + b.h - 7, width: 10, height: 10, class: 'resize-handle'});
      handle.addEventListener('mousedown', (e) => { e.stopPropagation(); dragState = {id: b.id, resize: true}; });
      svg.appendChild(handle);
    }
  });

  shapes.filter(s => s.type === 'text').forEach(tx => {
    const lineHeight = 15;
    const lines = wrapText(tx.label || '(empty note)', tx.w - 16);
    tx.h = Math.max(tx.h || 40, lines.length * lineHeight + 16);
    const selected = tx.id === selectedShapeId;
    const cx = tx.x + tx.w / 2, cy = tx.y + tx.h / 2;
    const g = svgEl('g', {transform: `rotate(${noteTilt(tx.id)} ${cx} ${cy})`, class: 'rough-shadow'});
    const rect = rc.rectangle(tx.x, tx.y, tx.w, tx.h, {
      stroke: '#c99a2e', fill: '#f5c542', fillStyle: 'solid', roughness: 1.6, strokeWidth: selected ? 2.5 : 1.5
    });
    rect.setAttribute('class', 'shape-note' + (selected ? ' selected' : ''));
    g.appendChild(rect);
    const t = svgEl('text', {x: cx, y: cy - (lines.length - 1) * lineHeight / 2 + TEXT_BASELINE_NUDGE, class: 'shape-label note-label'});
    t.style.pointerEvents = 'none';
    lines.forEach((line, i) => {
      const tspan = svgEl('tspan', {x: cx, dy: i === 0 ? 0 : lineHeight});
      tspan.textContent = line;
      t.appendChild(tspan);
    });
    g.appendChild(t);
    if (selected) {
      const handle = svgEl('rect', {x: tx.x + tx.w - 7, y: tx.y + tx.h - 7, width: 10, height: 10, class: 'resize-handle'});
      handle.addEventListener('mousedown', (e) => { e.stopPropagation(); dragState = {id: tx.id, resize: true}; });
      g.appendChild(handle);
    }
    svg.appendChild(g);
  });

  if (arrowDraft) {
    const from = byId[arrowDraft.fromId];
    if (from) {
      const hint = svgEl('text', {x: from.x, y: from.y - 8, style: 'fill:var(--accent); font-size:11px;'});
      hint.textContent = 'click a target box…';
      svg.appendChild(hint);
    }
  }

  const deleteBtn = document.getElementById('canvas-delete-btn');
  if (deleteBtn) deleteBtn.disabled = !selectedShapeId;

  const wrapper = document.getElementById('canvas-scroll');
  if (wrapper) {
    const contentBottom = shapes.reduce((max, s) => Math.max(max, (s.y || 0) + (s.h || 0)), 0) + 40;
    svg.style.height = contentBottom > wrapper.clientHeight ? contentBottom + 'px' : '100%';
  }
}

function createInlineEditInput(midX, midY, initialValue, onCommit) {
  const card = document.getElementById('design-canvas-card');
  const svg = document.getElementById('design-canvas');
  const existing = card.querySelector('.canvas-inline-edit');
  if (existing) existing.remove();
  const input = document.createElement('input');
  input.className = 'canvas-inline-edit';
  input.value = initialValue || '';
  const cardRect = card.getBoundingClientRect();
  const svgRect = svg.getBoundingClientRect();
  const offsetX = svgRect.left - cardRect.left;
  const offsetY = svgRect.top - cardRect.top;
  input.style.left = (offsetX + midX - 50) + 'px';
  input.style.top = (offsetY + midY - 10) + 'px';
  input.style.width = '100px';
  const commit = () => {
    onCommit(input.value.trim());
    input.remove();
    renderCanvas();
    saveCurrentState();
  };
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') input.blur(); });
  input.addEventListener('blur', commit);
  card.appendChild(input);
  input.focus();
  input.select();
}

function startInlineEdit(shape) {
  createInlineEditInput(shape.x + shape.w / 2, shape.y + shape.h / 2, shape.label, (val) => { shape.label = val; });
}

function startArrowLabelEdit(arrow, midX, midY) {
  createInlineEditInput(midX, midY, arrow.label, (val) => { arrow.label = val; });
}

function serializeCanvasForLLM() {
  if (!shapes.length) return '';
  const byId = Object.fromEntries(shapes.map(s => [s.id, s]));
  const lines = [];
  shapes.filter(s => s.type === 'box').forEach(b => lines.push(`Box: ${b.label || '(unlabeled)'}${b.layer ? ` [${b.layer}]` : ''}`));
  shapes.filter(s => s.type === 'arrow').forEach(a => {
    const from = byId[a.fromId], to = byId[a.toId];
    if (!from || !to) return;
    lines.push(`Arrow: ${from.label || '(unlabeled)'} -> ${to.label || '(unlabeled)'}${a.label ? ` [${a.label}]` : ''}`);
  });
  shapes.filter(s => s.type === 'text').forEach(t => lines.push(`Note: ${t.label}`));
  return lines.join('\n');
}

// --- Phase: Mic-on by default (Option B) ---
