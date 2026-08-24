/**
 * game.js — 五子棋网页版主逻辑（纯前端版）
 *
 * 由 Flask + Socket.IO 后端架构改造而来：
 *   - Game 类 / 连珠禁手检测：移植自 wuziqi_web/server.py
 *   - EngineClient：以 Web Worker + Rapfi WASM 替代原 Python 进程引擎，
 *     协议命令（START/TURN/BEGIN/TAKEBACK/TRACESEARCH/INFO）与桌面版完全一致
 */
'use strict';

// ============================================================
// 连珠禁手检测（黑方三三 / 四四 / 长连）— 移植自 server.py
// ============================================================
const RENJU_DIRS = [[1, 0], [0, 1], [1, 1], [1, -1]];

function _run(grid, x, y, dx, dy, p, size) {
  let r = 1;
  for (const s of [1, -1]) {
    let i = 1;
    while (x + dx * i * s >= 0 && x + dx * i * s < size &&
           y + dy * i * s >= 0 && y + dy * i * s < size &&
           grid[y + dy * i * s][x + dx * i * s] === p) {
      r += 1;
      i += 1;
    }
  }
  return r;
}

function _fivePoints(grid, x, y, dx, dy, p, size) {
  const pts = [];
  for (let d = -4; d <= 4; d++) {
    if (d === 0) continue;
    const nx = x + dx * d, ny = y + dy * d;
    if (nx >= 0 && nx < size && ny >= 0 && ny < size && grid[ny][nx] === 0) {
      grid[ny][nx] = p;
      if (_run(grid, x, y, dx, dy, p, size) >= 5) pts.push([nx, ny]);
      grid[ny][nx] = 0;
    }
  }
  return pts;
}

function _fourType(grid, x, y, dx, dy, p, size) {
  const n = _fivePoints(grid, x, y, dx, dy, p, size).length;
  return n >= 2 ? 'F4' : (n === 1 ? 'B4' : null);
}

function _threeType(grid, x, y, dx, dy, p, size) {
  let live = 0, rush = 0;
  for (let d = -4; d <= 4; d++) {
    if (d === 0) continue;
    const nx = x + dx * d, ny = y + dy * d;
    if (nx >= 0 && nx < size && ny >= 0 && ny < size && grid[ny][nx] === 0) {
      grid[ny][nx] = p;
      const ft = _fourType(grid, x, y, dx, dy, p, size);
      grid[ny][nx] = 0;
      if (ft === 'F4') live += 1;
      else if (ft === 'B4') rush += 1;
    }
  }
  if (live >= 2) return 'F3S';
  if (live === 1) return 'F3';
  if (rush >= 1) return 'B3';
  return null;
}

function renjuForbidden(grid, x, y, player, size) {
  /** 黑方在 (x,y) 落子是否构成禁手（三三/四四/长连）。白方无禁手。 */
  size = size || 15;
  if (player !== 1) return false;
  grid[y][x] = player;
  const types = [];
  for (const [dx, dy] of RENJU_DIRS) {
    const run = _run(grid, x, y, dx, dy, player, size);
    if (run >= 6) types.push('OL');
    else if (run === 5) types.push('F5');
    else types.push(_fourType(grid, x, y, dx, dy, player, size)
                 || _threeType(grid, x, y, dx, dy, player, size));
  }
  grid[y][x] = 0;
  if (types.includes('F5')) return false;
  if (types.includes('OL')) return true;
  if (types.filter(t => t === 'F4' || t === 'B4').length >= 2) return true;
  if (types.filter(t => t === 'F3' || t === 'F3S').length >= 2) return true;
  return false;
}

// ============================================================
// 游戏状态 — 移植自 server.py 的 Game 类
// ============================================================
class Game {
  constructor() {
    this.renju = false;   // 是否启用连珠禁手
    this.reset();
  }

  reset() {
    this.grid    = Array.from({ length: 15 }, () => new Array(15).fill(0));
    this.turn    = 1;
    this.log     = [];
    this.over    = false;
    this.win     = 0;
    this.line    = [];
    this.aiFirst = false;
  }

  move(x, y, player) {
    if (player === undefined) player = this.turn;
    if (this.over) return [false, 'game over'];
    if (!(x >= 0 && x < 15 && y >= 0 && y < 15)) return [false, 'out of bounds'];
    if (this.grid[y][x] !== 0) return [false, 'occupied'];
    if (this.renju && renjuForbidden(this.grid, x, y, player))
      return [false, '禁手：黑方不能下三三/四四/长连'];
    this.grid[y][x] = player;
    this.log.push({ x: x, y: y, p: player });
    this.turn = 3 - player;
    const w = this._check(x, y);
    if (w) {
      this.over = true;
      this.win  = player;
      this.line = w.map(([wx, wy]) => ({ x: wx, y: wy }));
    } else if (this.log.length === 15 * 15) {
      this.over = true;
    }
    return [true, 'ok'];
  }

  undo() {
    if (this.over || this.log.length < 2) return false;
    this.log.pop();  // AI 的着法
    const p = this.log.pop();  // 玩家的着法
    this.grid = Array.from({ length: 15 }, () => new Array(15).fill(0));
    for (const m of this.log) this.grid[m.y][m.x] = m.p;
    this.turn = p.p;  // 撤销后仍轮到玩家落子
    this.over = false;
    this.win  = 0;
    this.line = [];
    return true;
  }

  _check(x, y) {
    const p = this.grid[y][x];
    for (const [dx, dy] of [[1, 0], [0, 1], [1, 1], [1, -1]]) {
      const line = [[x, y]];
      for (let i = 1; i <= 4; i++) {
        const nx = x + dx * i, ny = y + dy * i;
        if (nx >= 0 && nx < 15 && ny >= 0 && ny < 15 && this.grid[ny][nx] === p)
          line.push([nx, ny]);
        else break;
      }
      for (let i = 1; i <= 4; i++) {
        const nx = x - dx * i, ny = y - dy * i;
        if (nx >= 0 && nx < 15 && ny >= 0 && ny < 15 && this.grid[ny][nx] === p)
          line.unshift([nx, ny]);
        else break;
      }
      if (line.length >= 5) return line;
    }
    return null;
  }
}

// ============================================================
// 引擎客户端 — 通过 Web Worker 驱动 Rapfi WASM
//
// 协议与桌面版（pbrain-rapfi.exe）完全一致：
//   START <n>          -> OK（重置棋盘）
//   INFO KEY VALUE ... （设置参数，无响应）
//   TURN x,y           -> "ax,ay"（期间输出实时 INFO DEPTH/WINRATE）
//   BEGIN              -> "x,y"
//   TAKEBACK 0,0       -> OK
//   TRACESEARCH        -> Static Eval[Black]: ... (WDL xx.xx ...)
// ============================================================
class EngineClient {
  /**
   * @param {function(number, number)} onInfo 实时搜索信息回调 cb(depth, aiWinrate)
   */
  constructor(onInfo) {
    this._onInfo    = onInfo || function () {};
    this._infoDepth = 0;
    this._queue     = [];   // FIFO 待匹配响应 [{test, resolve, reject, timer}]
    this._ready     = new Promise((resolve, reject) => {
      this._readyResolve = resolve;
      this._readyReject  = reject;
    });

    this.worker = new Worker('engine-worker.js');
    this.worker.onmessage = (e) => this._onMessage(e.data);
    this.worker.onerror   = (e) => {
      console.error('engine worker error:', e.message || e);
      if (this._readyReject) { this._readyReject(new Error(e.message || 'worker error')); }
    };

    // 引擎加载兜底超时（含 40MB 权重下载时间）
    this._loadTimer = setTimeout(() => {
      if (this._readyReject) this._readyReject(new Error('引擎加载超时'));
    }, 300000);
  }

  _onMessage(msg) {
    switch (msg.type) {
      case 'ready':
        clearTimeout(this._loadTimer);
        this._readyResolve();
        break;
      case 'stdout':
        this._handleLine(msg.line);
        break;
      case 'stderr':
        if (msg.line) console.debug('[engine]', msg.line);
        break;
      case 'error':
        clearTimeout(this._loadTimer);
        if (this._readyReject) this._readyReject(new Error(msg.message));
        break;
      case 'exit':
        console.warn('engine exited with code', msg.code);
        break;
    }
  }

  _handleLine(line) {
    if (!line) return;

    // 所有 INFO 开头的行均为实时搜索信息，全部分流（对应 server.py _read 的
    // line.startswith("INFO") 分支）——否则 INFO PV/BESTLINE 等会闯入响应队列
    if (/^INFO /.test(line)) {
      let m = line.match(/^INFO DEPTH (\d+)/);
      if (m) { this._infoDepth = parseInt(m[1], 10); return; }
      m = line.match(/^INFO WINRATE ([\d.]+)/);
      if (m) this._onInfo(this._infoDepth, parseFloat(m[1]));
      return;
    }

    // raw 请求（TRACESEARCH）：响应以 MESSAGE 前缀输出，需在过滤前匹配
    // （对应 server.py evaluate() 使用不过滤的 _read_raw()）
    const headRaw = this._queue[0];
    if (headRaw && headRaw.raw && headRaw.test(line)) {
      this._queue.shift();
      clearTimeout(headRaw.timer);
      headRaw.resolve(line);
      return;
    }

    // 过滤 MESSAGE/DEBUG/ERROR 行后投递给待匹配队列
    if (/^(MESSAGE|DEBUG|ERROR)/.test(line)) return;
    const entry = this._queue.shift();
    if (entry) {
      clearTimeout(entry.timer);
      if (entry.test(line)) entry.resolve(line);
      else entry.reject(new Error('unexpected engine response: ' + line));
    }
    // 无等待者时丢弃（如启动横幅）
  }

  _request(cmd, test, timeoutMs, raw) {
    return this._ready.then(() => new Promise((resolve, reject) => {
      const entry = {
        test: test,
        resolve: resolve,
        reject: reject,
        raw: !!raw,
        timer: setTimeout(() => {
          const i = this._queue.indexOf(entry);
          if (i >= 0) this._queue.splice(i, 1);
          reject(new Error('引擎响应超时: ' + cmd));
        }, timeoutMs),
      };
      this._queue.push(entry);
      this.worker.postMessage({ cmd: cmd });
    }));
  }

  /** 等待引擎就绪（WASM 编译 + 权重加载） */
  waitReady() { return this._ready; }

  /** 初始化棋盘并应用规则/难度配置（对应 server.py Engine.init） */
  async init(renju, timeMs, maxDepth) {
    await this._request('START 15', s => s === 'OK', 15000);
    this._write('INFO TIMEOUT_TURN ' + timeMs);
    this._write('INFO MAX_DEPTH ' + maxDepth);
    this._write(renju ? 'INFO RULE 2' : 'INFO RULE 0');  // 2=连珠(禁手) 0=无禁手
    this._write('INFO SHOW_DETAIL 2');  // 开启实时 INFO 输出（含 WINRATE/DEPTH/EVAL）
    this._infoDepth = 0;
  }

  _write(cmd) { this.worker.postMessage({ cmd: cmd }); }

  /** 玩家落子，AI 应答 -> [x, y] */
  async turn(x, y, timeoutMs) {
    const resp = await this._request('TURN ' + x + ',' + y,
      s => /^-?\d+\s*,\s*-?\d+$/.test(s), timeoutMs || 20000);
    const m = resp.match(/^(-?\d+)\s*,\s*(-?\d+)$/);
    return [parseInt(m[1], 10), parseInt(m[2], 10)];
  }

  /** AI 执黑先行 -> [x, y] */
  async begin(timeoutMs) {
    const resp = await this._request('BEGIN',
      s => /^-?\d+\s*,\s*-?\d+$/.test(s), timeoutMs || 20000);
    const m = resp.match(/^(-?\d+)\s*,\s*(-?\d+)$/);
    return [parseInt(m[1], 10), parseInt(m[2], 10)];
  }

  /** 同步悔棋：撤销引擎内部最近 n 手 */
  async takeback(n) {
    for (let i = 0; i < n; i++)
      await this._request('TAKEBACK 0,0', s => s === 'OK', 10000);
  }

  /** 评估当前局面，返回黑方胜率 [0,1]（失败返回 null） */
  async evaluate() {
    try {
      // raw=true：Static Eval 行带 MESSAGE 前缀输出，需在过滤前匹配
      const line = await this._request('TRACESEARCH',
        s => /Static Eval\[Black\]/.test(s), 15000, true);
      const m = line.match(/Static Eval\[Black\]:.*WDL\s+([\d.]+)/);
      return m ? parseFloat(m[1]) / 100.0 : null;
    } catch (e) {
      console.warn('evaluate failed:', e.message);
      return null;
    }
  }
}

// ============================================================
// 页面控制器 — 对应原 index.html 中 socket.io 事件处理
// ============================================================
const DIFFICULTY = {
  easy:   [800, 5],
  medium: [2000, 10],
  hard:   [5000, 20],
};

const N = 15, CELL = 36, MARG = 36, R = 15;
const CW = N * CELL + MARG * 2;
const STARS = [[3,3],[3,7],[3,11],[7,3],[7,7],[7,11],[11,3],[11,7],[11,11]];

const cv  = document.getElementById('board');
const ctx = cv.getContext('2d');
cv.width = CW; cv.height = CW;

const game = new Game();          // 游戏状态（替代服务端 session）
let engine = null;                // 引擎客户端
let busy = false, hover = null;

// ---- 绘图 ----
function draw() {
  ctx.clearRect(0, 0, CW, CW);
  ctx.fillStyle = '#DEB887'; ctx.fillRect(0, 0, CW, CW);
  ctx.strokeStyle = '#5D4037'; ctx.lineWidth = 1;
  for (let i = 0; i < N; i++) {
    const x = MARG + i * CELL;
    ctx.beginPath(); ctx.moveTo(x, MARG); ctx.lineTo(x, MARG + (N-1)*CELL); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(MARG, x); ctx.lineTo(MARG + (N-1)*CELL, x); ctx.stroke();
  }
  ctx.fillStyle = '#5D4037';
  for (const [sx, sy] of STARS) {
    ctx.beginPath(); ctx.arc(MARG + sx*CELL, MARG + sy*CELL, 3, 0, Math.PI*2); ctx.fill();
  }

  for (let y = 0; y < N; y++)
    for (let x = 0; x < N; x++)
      if (game.grid[y][x]) stone(x, y, game.grid[y][x]);

  if (game.line.length) {
    ctx.strokeStyle = '#CC3333'; ctx.lineWidth = 2;
    for (const {x, y} of game.line) {
      ctx.beginPath(); ctx.arc(MARG + x*CELL, MARG + y*CELL, R+2, 0, Math.PI*2); ctx.stroke();
    }
  }

  if (game.log.length) {
    const last = game.log[game.log.length - 1];
    ctx.fillStyle = last.p === 1 ? '#F5F5F5' : '#1A1A1A';
    ctx.beginPath(); ctx.arc(MARG + last.x*CELL, MARG + last.y*CELL, 4, 0, Math.PI*2); ctx.fill();
  }

  if (hover && !game.over && !busy) {
    const [hx, hy] = hover;
    if (game.grid[hy][hx] === 0) {
      ctx.strokeStyle = '#888'; ctx.lineWidth = 2;
      ctx.setLineDash([3,3]);
      ctx.beginPath(); ctx.arc(MARG + hx*CELL, MARG + hy*CELL, R-1, 0, Math.PI*2); ctx.stroke();
      ctx.setLineDash([]);
    }
  }
}

function stone(x, y, p) {
  const cx = MARG + x*CELL, cy = MARG + y*CELL;
  ctx.fillStyle = '#777';
  ctx.beginPath(); ctx.arc(cx+1, cy+1, R, 0, Math.PI*2); ctx.fill();
  const g = ctx.createRadialGradient(cx-5, cy-5, 2, cx, cy, R);
  if (p === 1) { g.addColorStop(0, '#555'); g.addColorStop(1, '#111'); }
  else         { g.addColorStop(0, '#fff'); g.addColorStop(1, '#bbb'); }
  ctx.fillStyle = g;
  ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI*2); ctx.fill();
  ctx.strokeStyle = p === 1 ? '#333' : '#BBB'; ctx.lineWidth = 1;
  ctx.stroke();
}

// ---- 交互 ----
cv.addEventListener('click', e => {
  if (!engine || game.over || busy) return;
  const [x, y] = pixel(e); if (x == null) return;
  playMove(x, y);
});

cv.addEventListener('mousemove', e => {
  if (!engine || game.over || busy) return;
  const [x, y] = pixel(e);
  if (x == null) { if (hover) { hover = null; draw(); } return; }
  if (!hover || hover[0] !== x || hover[1] !== y) { hover = [x, y]; draw(); }
});

cv.addEventListener('mouseleave', () => { if (hover) { hover = null; draw(); } });

function pixel(e) {
  const r = cv.getBoundingClientRect();
  const sx = CW / r.width, sy = CW / r.height;
  const px = (e.clientX - r.left) * sx, py = (e.clientY - r.top) * sy;
  const x = Math.round((px - MARG) / CELL), y = Math.round((py - MARG) / CELL);
  if (x < 0 || x >= N || y < 0 || y >= N) return [null, null];
  const cx = MARG + x*CELL, cy = MARG + y*CELL;
  if (Math.abs(px - cx) > CELL/2 || Math.abs(py - cy) > CELL/2) return [null, null];
  return [x, y];
}

// ---- 对弈流程 ----
async function playMove(x, y) {
  busy = true; hover = null; setStatus('...'); enable(false); resetWinrate();
  const [ok, msg] = game.move(x, y);
  if (!ok) { busy = false; setStatus(msg); enable(true); return; }
  draw();

  try {
    if (!game.over) {
      const level = document.getElementById('level').value;
      const timeoutMs = DIFFICULTY[level][0] * 4 + 5000;  // 限时 + 兜底余量
      const [ax, ay] = await engine.turn(x, y, timeoutMs);
      const [ok2, msg2] = game.move(ax, ay);
      if (!ok2) { setStatus('AI 着法异常: ' + msg2); return; }
    }
  } catch (err) {
    console.error(err);
    setStatus('AI 未响应');
    return;
  } finally {
    busy = false;
  }
  updateStatus();
  draw();
}

async function newGame() {
  if (!engine) return;
  const lvl = document.getElementById('level').value;
  const renju = document.getElementById('renjuCheck').checked;
  hover = null; game.aiFirst = false; resetWinrate();
  busy = true; setStatus('新游戏'); enable(false);

  try {
    await engine.init(renju, DIFFICULTY[lvl][0], DIFFICULTY[lvl][1]);
    game.renju = renju;
    game.reset();
  } catch (err) {
    console.error(err);
    setStatus('引擎未响应');
  } finally {
    busy = false;
  }
  updateStatus();
  draw();
}

async function undo() {
  if (!engine) return;
  resetWinrate();
  if (!game.undo()) { setStatus('无法悔棋'); return; }
  busy = true; enable(false);
  try {
    // 同步引擎内部棋盘：撤销引擎最后两手，并重新评估当前局面
    await engine.takeback(2);
    const blackWr = await engine.evaluate();
    if (blackWr !== null) {
      const aiWr = game.aiFirst ? blackWr : (1.0 - blackWr);
      setWinrate(aiWr);
    }
  } catch (err) {
    console.error(err);
    setStatus('悔棋同步失败');
  } finally {
    busy = false;
    draw(); updateStatus();  // 无论成败，恢复按钮与状态显示
  }
}

async function aiFirst() {
  if (!engine) return;
  const renju = document.getElementById('renjuCheck').checked;
  hover = null; resetWinrate();
  busy = true; setStatus('AI 先手'); enable(false);

  try {
    await engine.init(renju, DIFFICULTY[document.getElementById('level').value][0],
                      DIFFICULTY[document.getElementById('level').value][1]);
    game.reset();
    game.aiFirst = true;
    game.renju = renju;
    const m = await engine.begin();
    game.move(m[0], m[1]);
  } catch (err) {
    console.error(err);
    setStatus('AI 未响应');
  } finally {
    busy = false;
  }
  updateStatus();
  draw();
}

// ---- UI ----
function setWinrate(aiWr) {
  const wr = Math.max(0, Math.min(1, aiWr));
  const blackWr = game.aiFirst ? wr : (1 - wr);
  const whiteWr = 1 - blackWr;
  // 优势量：0.5 → 0，1.0 → 1，从中间向两侧延伸
  const blackAdv = Math.max(0, Math.min(1, 2 * blackWr - 1));
  const whiteAdv = Math.max(0, Math.min(1, 2 * whiteWr - 1));
  document.getElementById('blackSeg').style.width = (blackAdv * 100) + '%';
  document.getElementById('whiteSeg').style.width = (whiteAdv * 100) + '%';
  const bTag = game.aiFirst ? 'AI' : '玩家';
  const wTag = game.aiFirst ? '玩家' : 'AI';
  document.getElementById('blackLabel').textContent = `黑（${bTag}）${(blackWr * 100).toFixed(1)}%`;
  document.getElementById('whiteLabel').textContent = `白（${wTag}）${(whiteWr * 100).toFixed(1)}%`;
}

function resetWinrate() {
  document.getElementById('blackSeg').style.width = '0%';
  document.getElementById('whiteSeg').style.width = '0%';
  const bTag = game.aiFirst ? 'AI' : '玩家';
  const wTag = game.aiFirst ? '玩家' : 'AI';
  document.getElementById('blackLabel').textContent = `黑（${bTag}）—`;
  document.getElementById('whiteLabel').textContent = `白（${wTag}）—`;
}

function setStatus(t) { document.getElementById('status').textContent = t; }

function updateStatus() {
  document.getElementById('count').textContent =
    game.log.length ? `共 ${game.log.length} 手` : '';
  if (game.over) {
    if (game.win === 0) setStatus('平局');
    else if ((game.aiFirst && game.win === 1) || (!game.aiFirst && game.win === 2)) setStatus('AI 获胜');
    else setStatus('你赢了');
    // 终局胜率：AI 胜 → 1，玩家胜 → 0，平局 → 0.5
    const aiWin = (game.aiFirst && game.win === 1) || (!game.aiFirst && game.win === 2);
    setWinrate(game.win === 0 ? 0.5 : (aiWin ? 1 : 0));
  } else if (busy) {
    setStatus('思考中...');
  } else {
    setStatus(game.aiFirst ? '轮到你了（白棋）' : '轮到你了（黑棋）');
  }
  enable(!busy);
}

function enable(on) {
  ['btnNew','btnUndo','btnAI'].forEach(id => document.getElementById(id).disabled = !on);
}

// ---- 启动：初始化 WASM 引擎 ----
(async function boot() {
  draw();
  if (typeof WebAssembly !== 'object') {
    setStatus('浏览器不支持 WebAssembly');
    return;
  }
  try {
    engine = new EngineClient((depth, wr) => { setWinrate(wr); });
    setStatus('正在加载引擎（首次约 40MB，请稍候）...');
    await engine.waitReady();
    await engine.init(false, DIFFICULTY.medium[0], DIFFICULTY.medium[1]);
    setStatus('已就绪');
    enable(true);
  } catch (err) {
    console.error(err);
    engine = null;
    setStatus('引擎加载失败：' + err.message);
    alert('Rapfi 引擎加载失败：' + err.message +
          '\n\n请确认使用较新版本的 Chrome / Edge / Firefox 浏览器。');
  }
})();
