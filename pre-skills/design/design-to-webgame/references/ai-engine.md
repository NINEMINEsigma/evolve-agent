# Game AI Engine Design

Designing AI opponents for turn-based strategy / board games. Based on chess engine patterns, applicable to any perfect-information game.

## 1. Board Representation: 0x88 Layout

```js
const PAWN = 1, KNIGHT = 2, BISHOP = 3, ROOK = 4, QUEEN = 5, KING = 6;
const WHITE = 8, BLACK = 16;
const TYPE = 7, COLOR = 24;

const board = new Int8Array(128);  // a8=0, b8=1... h1=119
// Boundary check: (sq & 0x88) === 0 means on board
```

**Advantages over 8×8 array**:
- Single bitwise boundary check instead of range comparisons
- No special handling for off-board squares during move generation
- `sq + 16` always moves one rank; `sq + 1` always moves one file

## 2. Move Generation

Two-phase generation for efficiency:

```js
function generateMoves(pos, { legal = true, capturesOnly = false } = {}) {
  // Phase 1: pseudo-legal (all possible moves, including those that leave king in check)
  const pseudo = [];
  // ... generate all moves into pseudo ...

  if (!legal) return pseudo;

  // Phase 2: filter by making each move and checking if king is attacked
  const out = [];
  for (const move of pseudo) {
    const undo = makeMove(pos, move);
    if (!isAttacked(pos, pos.kings[us >> 3], them)) out.push(move);
    unmakeMove(pos, move, undo);
  }
  return out;
}
```

## 3. makeMove / unmakeMove

**In-place modification** with undo record. Never clone the board.

```js
function makeMove(pos, move) {
  const undo = { castling: pos.castling, ep: pos.ep, half: pos.half, full: pos.full, captured: 0, capturedSq: -1 };
  // ... apply move to board ...
  // ... update castling rights, en passant, halfmove clock ...
  pos.turn = them;
  return undo;
}

function unmakeMove(pos, move, undo) {
  // ... restore board from undo record ...
}
```

## 4. Search: Negamax + Alpha-Beta + PVS + LMR

```js
function negamax(pos, depth, alpha, beta, ply, ctx) {
  if (ctx.nodes > ctx.budget || Date.now() > ctx.deadline) { ctx.aborted = true; return alpha; }
  ctx.nodes++;

  const checked = inCheck(pos);
  if (checked) depth++;           // extend search when in check
  if (depth <= 0) return quiesce(pos, alpha, beta, ctx);

  const moves = generateMoves(pos);
  if (!moves.length) return checked ? -MATE + ply : 0;

  orderMoves(moves, ctx.killers, ctx.history, ply);

  for (let i = 0; i < moves.length; i++) {
    const move = moves[i];
    const undo = makeMove(pos, move);
    let score;
    if (i === 0) {
      score = -negamax(pos, depth - 1, -beta, -alpha, ply + 1, ctx);
    } else {
      // Late Move Reduction
      const reduce = depth >= 3 && i >= 4 && !(move.flags & (CAPTURE | PROMO)) && !checked ? 1 : 0;
      score = -negamax(pos, depth - 1 - reduce, -alpha - 1, -alpha, ply + 1, ctx);
      if (score > alpha && score < beta) {
        score = -negamax(pos, depth - 1, -beta, -alpha, ply + 1, ctx);
      }
    }
    unmakeMove(pos, move, undo);
    if (ctx.aborted) return alpha;
    if (score > alpha) {
      alpha = score;
      if (ply === 0) ctx.rootMove = move;
      if (score >= beta) {
        // Killer heuristic + history heuristic
        if (!(move.flags & (CAPTURE | PROMO))) {
          ctx.killers[ply] = [move.from, move.to];
          ctx.history[move.from * 128 + move.to] = (ctx.history[move.from * 128 + move.to] | 0) + depth * depth;
        }
        return beta;
      }
    }
  }
  return alpha;
}
```

## 5. Static Search (Quiescence)

Search only capture moves when depth reaches zero, to avoid horizon effect:

```js
function quiesce(pos, alpha, beta, ctx) {
  ctx.nodes++;
  const stand = evaluate(pos);
  if (stand >= beta) return beta;
  if (stand > alpha) alpha = stand;

  const moves = generateMoves(pos, { capturesOnly: true });
  moves.sort((a, b) => (VALUE[typeOf(b.captured)] || 0) - (VALUE[typeOf(a.captured)] || 0));
  for (const move of moves) {
    const undo = makeMove(pos, move);
    const score = -quiesce(pos, -beta, -alpha, ctx);
    unmakeMove(pos, move, undo);
    if (score >= beta) return beta;
    if (score > alpha) alpha = score;
  }
  return alpha;
}
```

## 6. Evaluation Function

```js
function evaluate(pos) {
  let mg = 0, eg = 0, phase = 0;
  for (let sq = 0; sq <= 119; sq++) {
    if (!onBoard(sq)) { sq += 7; continue; }
    const p = pos.board[sq];
    if (!p) continue;
    const kind = typeOf(p), color = colorOf(p), sign = color === WHITE ? 1 : -1;
    const i = index64(sq, color);  // PST index
    phase += PHASE_WEIGHT[kind];
    mg += sign * (VALUE[kind] + PST_MG[kind][i] * 2);
    eg += sign * (VALUE[kind] + PST_EG[kind][i] * 2);
  }
  const p = Math.min(phase, TOTAL_PHASE) / TOTAL_PHASE;
  return mg * p + eg * (1 - p);  // tapered eval
}
```

## 7. Difficulty Control

```js
const LEVELS = {
  novice: { depth: 2, ms: 220, blunder: 0.34, spread: 90 },
  club:   { depth: 4, ms: 700, blunder: 0.12, spread: 45 },
  expert: { depth: 6, ms: 1600, blunder: 0.03, spread: 18 },
  master: { depth: 8, ms: 3200, blunder: 0, spread: 0 }
};
```

- `depth`: max iterative deepening depth
- `ms`: time limit per move
- `blunder`: probability of not playing the best move
- `spread`: max centipawn loss for "suboptimal but reasonable" moves

## 8. Web Worker

Run search off the main thread to prevent UI freezing:

```js
// main.js
const worker = new Worker(new URL('../chess/worker.js', import.meta.url), { type: 'module' });
let requestId = 0;

function askAI(pos, level) {
  requestId++;
  worker.postMessage({ type: 'search', id: requestId, fen: toFen(pos), level });
}

worker.onmessage = ({ data }) => {
  if (data.id !== requestId || data.type !== 'result') return;
  const move = findMove(state.pos, parseSquare(data.from), parseSquare(data.to));
  if (move) playMove(move);
};

// worker.js
self.onmessage = ({ data }) => {
  if (data.type !== 'search') return;
  const pos = fromFen(data.fen);
  const result = search(pos, { level: data.level });
  self.postMessage({ type: 'result', ...serialize(result) });
};
```

## 9. Thinking Pace (Humanization)

Prevent AI from playing instantly:

```js
const PACE = {
  novice: [450, 550],
  club:   [900, 1000],
  expert: [1250, 1400],
  master: [1600, 2000]
};

const [floor, spread] = PACE[level];
const owed = floor + Math.random() * spread - (performance.now() - askedAt);
if (owed > 0) setTimeout(play, owed);
else play();
```
