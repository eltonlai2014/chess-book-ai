// Static-site renderer for the per-game page.
// Single source of truth = STATE { vi, pi }. Every UI update routes through activatePly
// or selectVariation, both of which always stop any running demo first.

const SVG_NS = "http://www.w3.org/2000/svg";

const PIECE_CHAR = {
  K: "帥", A: "仕", B: "相", N: "傌", R: "俥", C: "炮", P: "兵",
  k: "將", a: "士", b: "象", n: "馬", r: "車", c: "砲", p: "卒",
};

// ---------- generic helpers ----------

function el(tag, attrs, parent) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const k in attrs) node.setAttribute(k, attrs[k]);
  if (parent) parent.appendChild(node);
  return node;
}

// Module-level flag so screenY can flip without threading a parameter through
// every call site. Set by drawBoard at the start of each redraw.
let CURRENT_REDP = true;

function screenX(col) {
  // Perspective switch is a true 180° rotation, so X also flips.
  return CURRENT_REDP ? (30 + col * 60) : (30 + (8 - col) * 60);
}
function screenY(row) {
  // Red perspective: row 0 (red back rank) at bottom of SVG, row 9 at top.
  // Black perspective: row 0 at top, row 9 at bottom.
  return CURRENT_REDP ? (30 + (9 - row) * 60) : (30 + row * 60);
}

function iccsToCoord(iccs) {
  if (!iccs || iccs.length < 4) return null;
  const a = "a".charCodeAt(0);
  return {
    from: { col: iccs.charCodeAt(0) - a, row: parseInt(iccs[1], 10) },
    to:   { col: iccs.charCodeAt(2) - a, row: parseInt(iccs[3], 10) },
  };
}

function parseFen(fen) {
  const parts = fen.split(/\s+/);
  const boardStr = parts[0];
  const side = parts[1] || "w";
  const rows = [];
  for (const rs of boardStr.split("/")) {
    const row = [];
    for (const ch of rs) {
      if (/\d/.test(ch)) {
        for (let i = 0; i < parseInt(ch, 10); i++) row.push(null);
      } else {
        row.push(ch);
      }
    }
    while (row.length < 9) row.push(null);
    rows.push(row);
  }
  const byIccsRow = [];
  for (let r = 0; r <= 9; r++) byIccsRow[r] = rows[9 - r];
  return { rows: byIccsRow, side };
}

function getEntry(fen) {
  return (window.POSITIONS && window.POSITIONS[fen]) || null;
}

// Always returns score in RED perspective (positive = red advantage). Used by chart.
function redPerspectiveScore(entry, sideToMove) {
  if (!entry) return null;
  if (entry.mate != null) {
    let s = entry.mate > 0 ? 1000 : -1000;
    if (sideToMove === "black") s = -s;
    return s;
  }
  if (entry.score == null) return null;
  return sideToMove === "black" ? -entry.score : entry.score;
}

// Build a synthetic entry that uses the deep_* fields so existing
// red-perspective and delta helpers can be reused unchanged.
function deepEntry(entry) {
  if (!entry || (entry.deep_score == null && entry.deep_mate == null)) return null;
  return { score: entry.deep_score, mate: entry.deep_mate };
}

function redPerspectiveDeepScore(fen, sideToMove) {
  return redPerspectiveScore(deepEntry(getEntry(fen)), sideToMove);
}

// Loss computed from deep eval (depth 22) instead of shallow (depth 12).
function deepDeltaCp(plies, i) {
  if (i < 0 || i >= plies.length - 1) return null;
  const p = plies[i];
  const pn = plies[i + 1];
  if (!p.fen || !pn.fen) return null;
  const r  = redPerspectiveDeepScore(p.fen,  p.side);
  const rn = redPerspectiveDeepScore(pn.fen, pn.side);
  if (r == null || rn == null) return null;
  return p.side === "red" ? r - rn : rn - r;
}

// "Loss" = how much cp the side-to-move at step i gave up by playing the book move.
// Computed as: red_persp(i) - red_persp(i+1) for red-to-move, negated for black.
// Positive = the moving side lost cp (their move was suboptimal).
function deltaCp(plies, i) {
  if (i < 0 || i >= plies.length - 1) return null;
  const p = plies[i];
  const pn = plies[i + 1];
  if (!p.fen || !pn.fen) return null;
  const r  = redPerspectiveScore(getEntry(p.fen),  p.side);
  const rn = redPerspectiveScore(getEntry(pn.fen), pn.side);
  if (r == null || rn == null) return null;
  return p.side === "red" ? r - rn : rn - r;
}

function deltaClass(loss) {
  if (loss == null) return "";
  if (loss > 200) return "delta-blunder";
  if (loss > 100) return "delta-mistake";
  if (loss > 50) return "delta-inaccuracy";
  return "delta-neutral";
}

function fmtDelta(v) {
  if (v == null) return "";
  const sign = v > 0 ? "+" : "";
  return sign + Math.round(v);
}

// All numeric columns use red perspective unconditionally: positive = red is
// favored, negative = black is favored. The 紅方視角 checkbox now only affects
// the board orientation (not the table numbers).
function fmtScore(entry, sideToMove) {
  if (!entry) return { text: "?", cls: "" };
  if (entry.mate != null) {
    let m = entry.mate;
    if (sideToMove === "black") m = -m;
    return { text: m > 0 ? `M${m}` : `-M${-m}`, cls: m > 0 ? "score-positive" : "score-negative" };
  }
  let s = entry.score;
  if (s == null) return { text: "?", cls: "" };
  if (sideToMove === "black") s = -s;
  return {
    text: (s >= 0 ? "+" : "") + s,
    cls: s >= 0 ? "score-positive" : "score-negative",
  };
}

// Red-perspective signed delta. Positive = red gained cp between i and i+1;
// negative = red lost cp. Magnitude regardless of which side moved.
function redDelta(plies, i) {
  if (i < 0 || i >= plies.length - 1) return null;
  const p = plies[i], pn = plies[i + 1];
  if (!p.fen || !pn.fen) return null;
  const r  = redPerspectiveScore(getEntry(p.fen),  p.side);
  const rn = redPerspectiveScore(getEntry(pn.fen), pn.side);
  if (r == null || rn == null) return null;
  return rn - r;
}

function deepRedDelta(plies, i) {
  if (i < 0 || i >= plies.length - 1) return null;
  const p = plies[i], pn = plies[i + 1];
  if (!p.fen || !pn.fen) return null;
  const r  = redPerspectiveDeepScore(p.fen,  p.side);
  const rn = redPerspectiveDeepScore(pn.fen, pn.side);
  if (r == null || rn == null) return null;
  return rn - r;
}

// Color class for any red-POV signed value (used by 分, Δ, 深Δ, 雲庫 columns).
function deltaSignClass(v) {
  if (v == null) return "";
  const a = Math.abs(v);
  if (a <= 50) return "delta-neutral";
  const sign = v > 0 ? "pos" : "neg";
  const mag = a > 100 ? "strong" : "mild";
  return `delta-${sign}-${mag}`;
}

// ---------- board drawing (SVG) ----------

function drawBoard(svg, fen, bookMove, engineMove) {
  // Latch perspective for this redraw so screenY (called many times below)
  // doesn't re-poll the checkbox each call.
  CURRENT_REDP = isRedPerspective();
  while (svg.firstChild) svg.removeChild(svg.firstChild);

  // Wood gradient + subtle grain pattern
  const defs = el("defs", {}, svg);
  const grad = el("linearGradient", { id: "wood", x1: "0", y1: "0", x2: "0", y2: "1" }, defs);
  el("stop", { offset: "0%",   "stop-color": "#cba16b" }, grad);
  el("stop", { offset: "50%",  "stop-color": "#e6c79b" }, grad);
  el("stop", { offset: "100%", "stop-color": "#cba16b" }, grad);
  const pat = el("pattern", { id: "grain", x: "0", y: "0", width: "120", height: "8", patternUnits: "userSpaceOnUse" }, defs);
  el("line", { x1: 0, y1: 4, x2: 120, y2: 4, stroke: "rgba(110,70,30,0.07)", "stroke-width": 0.6 }, pat);
  el("line", { x1: 0, y1: 7, x2: 120, y2: 7, stroke: "rgba(110,70,30,0.04)", "stroke-width": 0.4 }, pat);

  el("rect", { x: 0, y: 0, width: 540, height: 600, fill: "url(#wood)" }, svg);
  el("rect", { x: 0, y: 0, width: 540, height: 600, fill: "url(#grain)" }, svg);

  // Last-move highlight: blue rounded box at the destination square (XQStudio style)
  if (bookMove) {
    const c = iccsToCoord(bookMove);
    if (c) {
      // origin: faint blue ring
      el("rect", {
        x: screenX(c.from.col) - 26, y: screenY(c.from.row) - 26, width: 52, height: 52,
        rx: 4, ry: 4, fill: "none", stroke: "#2980b9", "stroke-width": 1.5, "stroke-opacity": 0.4,
        "stroke-dasharray": "4 3",
      }, svg);
      // destination: solid blue box
      el("rect", {
        x: screenX(c.to.col) - 28, y: screenY(c.to.row) - 28, width: 56, height: 56,
        rx: 4, ry: 4, fill: "none", stroke: "#2980b9", "stroke-width": 2.5,
      }, svg);
    }
  }
  // Engine suggestion: dashed orange ring at destination (so it doesn't fight the blue last-move box)
  if (engineMove && engineMove !== bookMove) {
    const c = iccsToCoord(engineMove);
    if (c) {
      el("circle", {
        cx: screenX(c.to.col), cy: screenY(c.to.row), r: 28,
        fill: "none", stroke: "#e67e22", "stroke-width": 2, "stroke-dasharray": "5 4",
      }, svg);
    }
  }

  // Grid lines
  for (let r = 0; r <= 9; r++) {
    el("line", { x1: 30, y1: 30 + r * 60, x2: 510, y2: 30 + r * 60, stroke: "#4a3010", "stroke-width": 1 }, svg);
  }
  for (let c = 0; c <= 8; c++) {
    if (c === 0 || c === 8) {
      el("line", { x1: 30 + c * 60, y1: 30, x2: 30 + c * 60, y2: 570, stroke: "#4a3010", "stroke-width": 1 }, svg);
    } else {
      el("line", { x1: 30 + c * 60, y1: 30,  x2: 30 + c * 60, y2: 270, stroke: "#4a3010", "stroke-width": 1 }, svg);
      el("line", { x1: 30 + c * 60, y1: 330, x2: 30 + c * 60, y2: 570, stroke: "#4a3010", "stroke-width": 1 }, svg);
    }
  }
  el("rect", { x: 30, y: 30, width: 480, height: 540, fill: "none", stroke: "#4a3010", "stroke-width": 3 }, svg);

  // Palace diagonals
  const palace = [
    [screenX(3), screenY(2), screenX(5), screenY(0)],
    [screenX(5), screenY(2), screenX(3), screenY(0)],
    [screenX(3), screenY(9), screenX(5), screenY(7)],
    [screenX(5), screenY(9), screenX(3), screenY(7)],
  ];
  for (const [x1, y1, x2, y2] of palace) {
    el("line", { x1, y1, x2, y2, stroke: "#4a3010", "stroke-width": 1 }, svg);
  }

  // River text
  const river = el("text", { x: 270, y: 308, "text-anchor": "middle", "font-size": 24, fill: "#5a3a1a", "font-family": "serif", "letter-spacing": 38, "font-style": "italic" }, svg);
  river.textContent = "楚河      漢界";

  // Coordinate labels above (col 1..9 from red's left perspective = ICCS col a..i)
  for (let c = 0; c <= 8; c++) {
    const x = screenX(c);
    const labelTop = el("text", { x, y: 18, "text-anchor": "middle", "font-size": 11, fill: "#5a3a1a", "font-family": "serif" }, svg);
    labelTop.textContent = c + 1;
    const labelBot = el("text", { x, y: 590, "text-anchor": "middle", "font-size": 11, fill: "#5a3a1a", "font-family": "serif" }, svg);
    labelBot.textContent = c + 1;
  }

  // Pieces (traditional style: red = cream disk with red border + red text; black = dark disk + white text)
  const parsed = fen ? parseFen(fen) : null;
  if (parsed) {
    for (let r = 0; r <= 9; r++) {
      for (let c = 0; c <= 8; c++) {
        const p = parsed.rows[r][c];
        if (!p) continue;
        const isRed = p === p.toUpperCase();
        const cx = screenX(c), cy = screenY(r);
        // Drop shadow
        el("circle", { cx: cx + 1.5, cy: cy + 1.5, r: 26, fill: "rgba(0,0,0,0.22)" }, svg);
        // Outer disk
        el("circle", {
          cx, cy, r: 26,
          fill: isRed ? "#fff5db" : "#222",
          stroke: isRed ? "#8b1a0e" : "#000",
          "stroke-width": 1.5,
        }, svg);
        // Inner ring
        el("circle", {
          cx, cy, r: 22,
          fill: "none",
          stroke: isRed ? "#c0392b" : "#888",
          "stroke-width": 1,
        }, svg);
        // Character
        const t = el("text", {
          x: cx, y: cy + 10, "text-anchor": "middle",
          "font-size": 28, "font-family": "serif", "font-weight": "bold",
          fill: isRed ? "#c0392b" : "#f5f5f5",
        }, svg);
        t.textContent = PIECE_CHAR[p] || p;
      }
    }
  }
}

// ---------- score chart ----------

const CHART_W = 540, CHART_H = 140;
const CHART_PAD_L = 28, CHART_PAD_R = 8, CHART_PAD_T = 10, CHART_PAD_B = 16;
const CHART_RANGE = 500; // cp clamp range; M scores rendered as +/-1000 then clamped

function drawChart(svg, plies, activePly) {
  while (svg.firstChild) svg.removeChild(svg.firstChild);
  const innerW = CHART_W - CHART_PAD_L - CHART_PAD_R;
  const innerH = CHART_H - CHART_PAD_T - CHART_PAD_B;
  const cy0 = CHART_PAD_T + innerH / 2;

  el("rect", { x: 0, y: 0, width: CHART_W, height: CHART_H, fill: "#faf3df" }, svg);

  const yOf = (s) => cy0 - (s / CHART_RANGE) * (innerH / 2);
  const xOf = (i) => {
    if (plies.length <= 1) return CHART_PAD_L + innerW / 2;
    return CHART_PAD_L + (i / (plies.length - 1)) * innerW;
  };

  // Grid lines + labels
  [-500, -250, 0, 250, 500].forEach((s) => {
    const y = yOf(s);
    el("line", {
      x1: CHART_PAD_L, y1: y, x2: CHART_W - CHART_PAD_R, y2: y,
      stroke: s === 0 ? "#888" : "#e8d8a8",
      "stroke-width": 1,
      "stroke-dasharray": s === 0 ? "0" : "3 3",
    }, svg);
    const t = el("text", { x: 2, y: y + 3, "font-size": 9, fill: "#888" }, svg);
    t.textContent = s;
  });

  // Collect data points (red perspective so the line is a continuous trend)
  const data = [];
  for (let i = 0; i < plies.length; i++) {
    const p = plies[i];
    if (!p.fen) continue;
    const e = getEntry(p.fen);
    if (!e) continue;
    const s = redPerspectiveScore(e, p.side);
    if (s == null) continue;
    const clamped = Math.max(-CHART_RANGE, Math.min(CHART_RANGE, s));
    data.push({ i, s, clamped, side: p.side });
  }
  if (!data.length) return;

  let d = "";
  data.forEach((pt, idx) => {
    d += (idx === 0 ? "M" : "L") + xOf(pt.i).toFixed(1) + " " + yOf(pt.clamped).toFixed(1);
  });
  el("path", { d, fill: "none", stroke: "#3498db", "stroke-width": 1.5 }, svg);

  // Points (clickable). Big-loss steps get a red halo; active step gets an orange ring.
  data.forEach((pt) => {
    const x = xOf(pt.i), y = yOf(pt.clamped);
    const loss = deltaCp(plies, pt.i);
    if (loss != null && loss > 100) {
      el("circle", {
        cx: x, cy: y, r: 5,
        fill: "none",
        stroke: loss > 200 ? "#c0392b" : "#d68910",
        "stroke-width": 2,
      }, svg);
    }
    if (pt.i === activePly) {
      el("circle", { cx: x, cy: y, r: 8, fill: "none", stroke: "#f39c12", "stroke-width": 2 }, svg);
    }
    const c = el("circle", {
      cx: x, cy: y, r: 3,
      fill: pt.side === "red" ? "#c0392b" : "#1a1a1a",
      "data-ply": pt.i,
      style: "cursor:pointer",
    }, svg);
    const lossText = loss != null ? ` (失分 ${fmtDelta(loss)})` : "";
    const title = el("title", {}, c);
    title.textContent = `第 ${pt.i + 1} 步 · ${pt.s >= 0 ? "+" : ""}${pt.s}${lossText}`;
  });
}

// ---------- state ----------

const STATE = { vi: 0, pi: -1, GAME: null, demoTimer: null };
let SVG_BOARD, SVG_CHART, STEP_INFO, ANNOTE_BOX, NAV_STATUS, DEMO_BTN, REDP_BOX, SELECT;

function isRedPerspective() { return REDP_BOX.checked; }

function stopDemo() {
  if (STATE.demoTimer) {
    clearTimeout(STATE.demoTimer);
    STATE.demoTimer = null;
  }
  setDemoMode(false);
}

function setDemoMode(active) {
  document.querySelectorAll(".control-bar .nav-first, .control-bar .nav-prev, .control-bar .nav-next, .control-bar .nav-last, #variation-select").forEach((b) => {
    b.disabled = active;
  });
  if (active) {
    DEMO_BTN.textContent = "■ 停止演示";
    DEMO_BTN.classList.add("stop");
  } else {
    DEMO_BTN.textContent = "▶ 演示推演";
    DEMO_BTN.classList.remove("stop");
  }
}

function updateNavStatus() {
  const total = STATE.GAME.variations[STATE.vi].length;
  const cur = STATE.pi >= 0 ? STATE.pi + 1 : 0;
  NAV_STATUS.textContent = `第 ${cur} / ${total} 步`;
}

function updateStepInfo(ply, entry) {
  if (!ply) {
    STEP_INFO.innerHTML = '<span class="placeholder">點選表格任一步，或變例選單切換變例</span>';
    return;
  }
  if (!entry) {
    STEP_INFO.innerHTML = `<span class="item"><span class="label">書譜</span> ${ply.chinese} <code>${ply.iccs}</code></span><span class="placeholder">此局面未經分析</span>`;
    return;
  }
  const sc = fmtScore(entry, ply.side);
  const bestCn = entry.best_chinese || entry.best_iccs || "?";
  const same = entry.best_iccs === ply.iccs;
  const sideLabel = ply.side === "red" ? "紅" : "黑";
  const d = redDelta(STATE.GAME.variations[STATE.vi], STATE.pi);
  const lossSpan = d == null
    ? ''
    : `<span class="item"><span class="label">Δ</span> <span class="${deltaSignClass(d)}">${fmtDelta(d)}</span></span>`;
  STEP_INFO.innerHTML = `
    <span class="item"><span class="label">${sideLabel}方走子</span></span>
    <span class="item"><span class="label">書譜</span> ${ply.chinese} <code>${ply.iccs}</code></span>
    <span class="item"><span class="label">引擎</span> ${bestCn} <code>${entry.best_iccs || "?"}</code></span>
    <span class="item"><span class="label">分</span> <span class="${sc.cls}">${sc.text}</span></span>
    ${lossSpan}
    <span class="item ${same ? "" : "diff-tag"}">${same ? "相同" : "不同"}</span>
  `;
}

function annotateTable(vi) {
  // Fill engine columns + annote indicator in the now-visible variation's table.
  // ALL numeric columns use red-POV signed cp (positive = red favored).
  const plies = STATE.GAME.variations[vi];
  document.querySelectorAll(`.plies-wrap[data-var="${vi}"] tbody tr[data-fen]`).forEach((tr) => {
    const pi = parseInt(tr.dataset.ply, 10);
    const ply = plies[pi];

    // Annote indicator: XQStudio-style "*" marker + 💬 tooltip on the book cell.
    const bookCell = tr.querySelector(".book-cn");
    if (ply.annote) {
      if (!bookCell.querySelector(".annote-marker")) {
        const star = document.createElement("span");
        star.className = "annote-marker";
        star.title = ply.annote;
        star.textContent = " *";
        bookCell.appendChild(star);
      }
      tr.classList.add("has-annote");
    }

    const entry = getEntry(tr.dataset.fen);
    if (!entry) return;
    const bestCn = entry.best_chinese || entry.best_iccs || "?";
    tr.querySelector(".eng-best").innerHTML = `${bestCn} <code class="tiny">${entry.best_iccs || ""}</code>`;
    const sc = fmtScore(entry, ply.side);
    const scCell = tr.querySelector(".score");
    scCell.textContent = sc.text;
    scCell.className = "score " + sc.cls;

    const dShallow = redDelta(plies, pi);
    const dCell = tr.querySelector(".delta");
    dCell.textContent = fmtDelta(dShallow);
    dCell.className = "delta " + deltaSignClass(dShallow);

    // Deep-eval overlay (depth-22). Plies 1..15 hidden — opening theory comparison
    // is misframed (avoiding every engine-preferred move = different opening).
    const SKIP_OPENING = 15;
    const dDeep = deepRedDelta(plies, pi);
    const pastOpening = pi >= SKIP_OPENING;
    const ddCell = tr.querySelector(".deep-delta");
    if (ddCell) {
      if (!pastOpening || dDeep == null) {
        ddCell.textContent = "";
        ddCell.className = "deep-delta";
      } else {
        ddCell.textContent = fmtDelta(dDeep);
        ddCell.className = "deep-delta " + deltaSignClass(dDeep);
      }
    }

    // Trap detection still uses mover-POV magnitude (positive = mover lost cp):
    // a red ply is trapped when red lost lots; a black ply when black lost lots.
    // In red-POV signed terms: red lost = dDeep << 0 on red row, black lost = dDeep >> 0 on black row.
    const moverDeep = ply.side === "red" ? -dDeep : dDeep;
    const moverShallow = ply.side === "red" ? -dShallow : dShallow;
    const shallowOk = moverShallow != null && moverShallow < 50;
    const deepBad   = moverDeep != null && moverDeep > 100;
    tr.classList.toggle("ply-trap", shallowOk && deepBad && pastOpening);

    // chessdb cloud-database overlay — score in red POV (chessdb returns mover-POV,
    // so flip for black plies). Hover shows full book vs cloud-best comparison.
    const cdbCell = tr.querySelector(".cdb");
    if (cdbCell) {
      const cdbMoves = entry.cdb_moves;
      if (!cdbMoves || cdbMoves.length === 0) {
        cdbCell.textContent = "";
        cdbCell.className = "cdb";
        cdbCell.removeAttribute("title");
      } else {
        const flipSign = ply.side === "black" ? -1 : 1;
        const bookEntry = cdbMoves.find((m) => m.iccs === ply.iccs);
        const best = cdbMoves[0];
        const matchesBest = best.iccs === ply.iccs;
        const fmtScoreLocal = (s) => s == null ? "?" : (s >= 0 ? "+" : "") + s;
        const fmtWr = (w) => w == null ? "?" : Math.round(w) + "%";
        const bestCn = entry.cdb_best_chinese || best.iccs;
        const bestRedScore = best.score == null ? null : best.score * flipSign;
        if (bookEntry && bookEntry.score != null) {
          const sRed = bookEntry.score * flipSign;
          cdbCell.textContent = fmtScoreLocal(sRed);
          cdbCell.className = "cdb " + deltaSignClass(sRed);
          cdbCell.title = matchesBest
            ? `雲庫推薦同步：${bestCn} ${fmtScoreLocal(bestRedScore)} (勝率 ${fmtWr(best.winrate)})`
            : `書譜：${ply.iccs} ${fmtScoreLocal(sRed)} (勝率 ${fmtWr(bookEntry.winrate)})\n雲庫最佳：${bestCn} ${fmtScoreLocal(bestRedScore)} (勝率 ${fmtWr(best.winrate)})\n差距：${(best.score - bookEntry.score) * flipSign} cp（紅方視角）`;
        } else {
          cdbCell.textContent = "—";
          cdbCell.className = "cdb cdb-missing";
          cdbCell.title = `書譜步雲庫無資料\n雲庫最佳：${bestCn} ${fmtScoreLocal(bestRedScore)} (勝率 ${fmtWr(best.winrate)})`;
        }
      }
    }

    const same = entry.best_iccs === ply.iccs;
    tr.querySelector(".same").textContent = same ? "同" : "異";
    tr.classList.toggle("diff", !same);
  });
}

function renderAnnote(ply) {
  if (!ANNOTE_BOX) return;
  ANNOTE_BOX.innerHTML = '';
  if (!ply) {
    const ph = document.createElement("div");
    ph.className = "annote-placeholder";
    ph.textContent = "（點選任一步顯示註解）";
    ANNOTE_BOX.appendChild(ph);
    return;
  }
  const head = document.createElement("div");
  head.className = "annote-head";
  head.textContent = "💬 棋譜註解";
  ANNOTE_BOX.appendChild(head);
  if (!ply.annote) {
    const ph = document.createElement("div");
    ph.className = "annote-placeholder";
    ph.textContent = "（此步無註解）";
    ANNOTE_BOX.appendChild(ph);
    return;
  }
  const body = document.createElement("div");
  body.className = "annote-body";
  body.textContent = ply.annote;
  ANNOTE_BOX.appendChild(body);
}

function scrollRowIntoView(tr) {
  const wrap = tr.closest(".plies-wrap");
  if (!wrap) return;
  const wrapH = wrap.clientHeight;
  const trTop = tr.offsetTop;
  const trH = tr.offsetHeight;
  const top = wrap.scrollTop;
  if (trTop < top || trTop + trH > top + wrapH) {
    wrap.scrollTop = trTop - wrapH / 2 + trH / 2;
  }
}

function selectVariation(vi) {
  stopDemo();
  STATE.vi = vi;
  STATE.pi = -1;
  document.querySelectorAll(".plies-wrap").forEach((w) => {
    const isCurrent = parseInt(w.dataset.var, 10) === vi;
    w.style.display = isCurrent ? "" : "none";
    if (isCurrent) w.scrollTop = 0;
  });
  SELECT.value = String(vi);
  annotateTable(vi);
  drawBoard(SVG_BOARD, STATE.GAME.init_fen, null, null);
  drawChart(SVG_CHART, STATE.GAME.variations[vi], -1);
  updateNavStatus();
  updateStepInfo(null, null);
  renderAnnote(null);
  document.querySelectorAll("table.plies tr.active").forEach((r) => r.classList.remove("active"));
}

function activatePly(pi) {
  stopDemo();
  const vi = STATE.vi;
  const plies = STATE.GAME.variations[vi];
  if (pi < 0 || pi >= plies.length) return;
  STATE.pi = pi;
  const tr = document.querySelector(`.plies-wrap[data-var="${vi}"] tr[data-ply="${pi}"]`);
  document.querySelectorAll("table.plies tr.active").forEach((r) => r.classList.remove("active"));
  if (tr) {
    tr.classList.add("active");
    scrollRowIntoView(tr);
  }
  const ply = plies[pi];
  const entry = getEntry(ply.fen);  // engine eval keyed on fen-before
  // Show the position AFTER the move was played (XQStudio convention).
  // Blue boxes mark the from/to of the move that was just played.
  const fenToDraw = ply.fen_after || ply.fen;
  drawBoard(SVG_BOARD, fenToDraw, ply.iccs, entry ? entry.best_iccs : null);
  drawChart(SVG_CHART, plies, pi);
  updateStepInfo(ply, entry);
  renderAnnote(ply);
  updateNavStatus();
}

// ---------- demo ----------

function startDemo() {
  if (STATE.pi < 0) return;
  const ply = STATE.GAME.variations[STATE.vi][STATE.pi];
  const entry = getEntry(ply.fen);
  if (!entry || !entry.pv_detail || !entry.pv_detail.length) return;
  setDemoMode(true);

  const pv = entry.pv_detail;
  let idx = 0;

  const step = () => {
    if (idx >= pv.length) {
      // Finished — leave board on last frame, restore controls
      setDemoMode(false);
      STATE.demoTimer = null;
      STEP_INFO.innerHTML = `
        <span class="item demo-tag">演示結束</span>
        <span class="item">已播放 ${pv.length} 步</span>
        <span class="item"><span class="label">起始</span> ${ply.chinese} <code>${ply.iccs}</code></span>
      `;
      return;
    }
    const s = pv[idx];
    drawBoard(SVG_BOARD, s.fen_after, s.iccs, null);
    STEP_INFO.innerHTML = `
      <span class="item demo-tag">▶ 演示 ${idx + 1} / ${pv.length}</span>
      <span class="item"><span class="label">本步</span> ${s.chinese} <code>${s.iccs}</code></span>
      <span class="item"><span class="label">起始</span> ${ply.chinese} <code>${ply.iccs}</code></span>
    `;
    idx += 1;
    STATE.demoTimer = setTimeout(step, 1200);
  };
  step();
}

// ---------- init ----------

function initGamePage(GAME) {
  STATE.GAME = GAME;
  SVG_BOARD = document.getElementById("board");
  SVG_CHART = document.getElementById("chart");
  STEP_INFO = document.getElementById("stepInfo");
  ANNOTE_BOX = document.getElementById("annoteBox");
  NAV_STATUS = document.getElementById("navStatus");
  DEMO_BTN = document.getElementById("demoBtn");
  REDP_BOX = document.getElementById("redPerspective");
  SELECT = document.getElementById("variation-select");

  // Annotate every table once (the hidden ones too, so future variation switches don't need redoing).
  // We do this lazily per-variation in selectVariation; but for the initial visible one, do it now.
  for (let vi = 0; vi < GAME.variations.length; vi++) annotateTable(vi);

  SELECT.addEventListener("change", () => selectVariation(parseInt(SELECT.value, 10)));

  document.querySelectorAll(".nav-first").forEach((b) => b.addEventListener("click", () => {
    activatePly(0);
  }));
  document.querySelectorAll(".nav-prev").forEach((b) => b.addEventListener("click", () => {
    activatePly(Math.max(0, (STATE.pi < 0 ? 0 : STATE.pi - 1)));
  }));
  document.querySelectorAll(".nav-next").forEach((b) => b.addEventListener("click", () => {
    const total = STATE.GAME.variations[STATE.vi].length;
    activatePly(Math.min(total - 1, STATE.pi + 1));
  }));
  document.querySelectorAll(".nav-last").forEach((b) => b.addEventListener("click", () => {
    const total = STATE.GAME.variations[STATE.vi].length;
    activatePly(total - 1);
  }));

  DEMO_BTN.addEventListener("click", () => {
    if (STATE.demoTimer) {
      stopDemo();
      // restore current ply view
      if (STATE.pi >= 0) activatePly(STATE.pi);
    } else {
      startDemo();
    }
  });

  // Row clicks (all variations — only visible ones reachable, but bind all)
  document.querySelectorAll(".plies-wrap").forEach((wrap) => {
    const vi = parseInt(wrap.dataset.var, 10);
    wrap.querySelectorAll("tbody tr[data-ply]").forEach((tr) => {
      tr.addEventListener("click", () => {
        if (vi !== STATE.vi) selectVariation(vi);
        activatePly(parseInt(tr.dataset.ply, 10));
      });
    });
  });

  // Chart click anywhere → jump to nearest ply (not just on the small data dots)
  SVG_CHART.style.cursor = "pointer";
  SVG_CHART.addEventListener("click", (ev) => {
    if (!STATE.GAME) return;
    const plies = STATE.GAME.variations[STATE.vi];
    if (!plies || plies.length === 0) return;
    const rect = SVG_CHART.getBoundingClientRect();
    const xPx = ev.clientX - rect.left;
    const xSvg = xPx * (CHART_W / rect.width);
    const innerW = CHART_W - CHART_PAD_L - CHART_PAD_R;
    let pi;
    if (plies.length <= 1) {
      pi = 0;
    } else {
      pi = Math.round(((xSvg - CHART_PAD_L) / innerW) * (plies.length - 1));
    }
    pi = Math.max(0, Math.min(plies.length - 1, pi));
    activatePly(pi);
  });

  document.addEventListener("keydown", (e) => {
    if (STATE.demoTimer) return; // ignore during demo
    if (STATE.pi < 0 && e.key !== "ArrowRight") return;
    const total = STATE.GAME.variations[STATE.vi].length;
    if (e.key === "ArrowLeft") {
      e.preventDefault();
      activatePly(Math.max(0, STATE.pi - 1));
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      activatePly(Math.min(total - 1, STATE.pi + 1));
    }
  });

  REDP_BOX.addEventListener("change", () => {
    // Checkbox only flips the board orientation. All numeric columns are
    // permanently in red-POV; they don't change when this toggles.
    if (STATE.pi >= 0) {
      const ply = STATE.GAME.variations[STATE.vi][STATE.pi];
      const entry = getEntry(ply.fen);
      drawBoard(SVG_BOARD, ply.fen_after || ply.fen, ply.iccs, entry ? entry.best_iccs : null);
    } else {
      drawBoard(SVG_BOARD, STATE.GAME.init_fen, null, null);
    }
  });

  // Initial render: variation 0, no ply selected
  selectVariation(0);
}

window.initGamePage = initGamePage;
