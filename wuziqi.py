#!/usr/bin/env python3
"""五子棋 — 基于 Rapfi 引擎的人机对弈"""
import subprocess
import sys
import os
import threading
import re
import random
import tkinter as tk
from tkinter import messagebox, ttk

# ============================================================
# 配置
# ============================================================
BOARD_SIZE = 15
CELL_SIZE  = 38
MARGIN     = 40
STONE_R    = 16

# 支持 PyInstaller 单文件打包：_MEIPASS 是运行时解压目录
if getattr(sys, 'frozen', False):
    _BASE = sys._MEIPASS
else:
    _BASE = os.path.dirname(os.path.abspath(__file__))

ENGINE_DIR  = os.path.join(_BASE, "engine")
ENGINE_PATH = os.path.join(ENGINE_DIR, "pbrain-rapfi.exe")

# 颜色
C_BOARD   = "#DEB887"
C_LINE    = "#5D4037"
C_BLACK   = "#1A1A1A"
C_WHITE   = "#F5F5F5"
C_WIN     = "#CC3333"
C_BG      = "#2D2D2D"
C_FG      = "#E0E0E0"
C_DIM     = "#888888"
C_BTN     = "#404040"
C_BTN_FG  = "#E0E0E0"

# 难度配置: (显示名, 限时ms, 最大深度, 随机扰动范围)
DIFFICULTY = {
    "初级": (800,  5, 1.5),
    "中级": (2000, 10, 0.8),
    "高级": (5000, 20, 0.0),
}
DEFAULT_DIFFICULTY = "中级"

# ============================================================
# 连珠禁手检测（黑方三三 / 四四 / 长连）
# ============================================================
_RENJU_DIRS = ((1, 0), (0, 1), (1, 1), (1, -1))


def _run(grid, x, y, dx, dy, p, size):
    r = 1
    for s in (1, -1):
        i = 1
        while 0 <= x + dx * i * s < size and 0 <= y + dy * i * s < size \
                and grid[y + dy * i * s][x + dx * i * s] == p:
            r += 1
            i += 1
    return r


def _five_points(grid, x, y, dx, dy, p, size):
    pts = []
    for d in range(-4, 5):
        if d == 0:
            continue
        nx, ny = x + dx * d, y + dy * d
        if 0 <= nx < size and 0 <= ny < size and grid[ny][nx] == 0:
            grid[ny][nx] = p
            if _run(grid, x, y, dx, dy, p, size) >= 5:
                pts.append((nx, ny))
            grid[ny][nx] = 0
    return pts


def _four_type(grid, x, y, dx, dy, p, size):
    n = len(_five_points(grid, x, y, dx, dy, p, size))
    return "F4" if n >= 2 else ("B4" if n == 1 else None)


def _three_type(grid, x, y, dx, dy, p, size):
    live = rush = 0
    for d in range(-4, 5):
        if d == 0:
            continue
        nx, ny = x + dx * d, y + dy * d
        if 0 <= nx < size and 0 <= ny < size and grid[ny][nx] == 0:
            grid[ny][nx] = p
            ft = _four_type(grid, x, y, dx, dy, p, size)
            grid[ny][nx] = 0
            if ft == "F4":
                live += 1
            elif ft == "B4":
                rush += 1
    if live >= 2:
        return "F3S"
    if live == 1:
        return "F3"
    if rush >= 1:
        return "B3"
    return None


def renju_forbidden(grid, x, y, player, size=BOARD_SIZE):
    """判断黑方在 (x,y) 落子是否构成禁手（三三/四四/长连）。白方无禁手。"""
    if player != 1:
        return False
    grid[y][x] = player
    types = []
    for dx, dy in _RENJU_DIRS:
        run = _run(grid, x, y, dx, dy, player, size)
        if run >= 6:
            types.append("OL")
        elif run == 5:
            types.append("F5")
        else:
            types.append(_four_type(grid, x, y, dx, dy, player, size)
                         or _three_type(grid, x, y, dx, dy, player, size))
    grid[y][x] = 0
    if "F5" in types:
        return False          # 五连即胜，非禁手
    if "OL" in types:
        return True           # 长连
    if sum(1 for t in types if t in ("F4", "B4")) >= 2:
        return True           # 四四
    if sum(1 for t in types if t in ("F3", "F3S")) >= 2:
        return True           # 三三
    return False


# ============================================================
# 引擎通信
# ============================================================
class Engine:
    def __init__(self):
        self._proc  = None
        self._lock  = threading.Lock()
        self._depth = 10
        self._time  = 2000
        self._noise = 0.8
        self._info_cb    = None   # 实时信息回调 cb(depth, winrate)，在搜索线程中调用
        self._info_depth = 0

    def configure(self, difficulty):
        self._time, self._depth, self._noise = DIFFICULTY[difficulty]

    def set_info_callback(self, cb):
        """设置实时信息回调：cb(depth:int, winrate:float)。winrate 为引擎侧胜率 [0,1]。"""
        self._info_cb = cb

    def start(self):
        if not os.path.exists(ENGINE_PATH):
            raise FileNotFoundError(f"引擎文件缺失: {ENGINE_PATH}")
        self._proc = subprocess.Popen(
            [ENGINE_PATH],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, cwd=ENGINE_DIR, bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        def _drain():
            try:
                while self._proc and self._proc.poll() is None:
                    self._proc.stderr.readline()
            except Exception:
                pass
        threading.Thread(target=_drain, daemon=True).start()

    def _write(self, cmd):
        with self._lock:
            if not self._proc or self._proc.poll() is not None:
                raise RuntimeError("引擎未运行")
            self._proc.stdin.write(cmd + "\n")
            self._proc.stdin.flush()

    def _read(self):
        while True:
            if not self._proc or self._proc.poll() is not None:
                return None
            line = self._proc.stdout.readline()
            if not line:
                return None
            line = line.strip()
            if not line:
                continue
            if line.startswith("INFO"):
                self._handle_info(line)
                continue
            if line.startswith(("MESSAGE", "DEBUG", "ERROR")):
                continue
            return line

    def _handle_info(self, line):
        """解析引擎实时 INFO 行（INFO DEPTH / INFO WINRATE ...），驱动胜率回调。"""
        try:
            _, key, val = line.split(None, 2)
        except ValueError:
            return
        if key == "DEPTH":
            try:
                self._info_depth = int(val)
            except ValueError:
                pass
        elif key == "WINRATE":
            try:
                wr = float(val)
            except ValueError:
                return
            if self._info_cb:
                self._info_cb(self._info_depth, wr)

    def _read_raw(self):
        """读取一行原始输出（不过滤 MESSAGE/INFO 等）。"""
        if not self._proc or self._proc.poll() is not None:
            return None
        line = self._proc.stdout.readline()
        if not line:
            return None
        return line.strip()

    def evaluate(self):
        """评估当前局面，返回黑方胜率 [0,1]（失败返回 None）。发送 TRACESEARCH 并解析。"""
        with self._lock:
            if not self._proc or self._proc.poll() is not None:
                return None
            self._proc.stdin.write("TRACESEARCH\n")
            self._proc.stdin.flush()
        for _ in range(200):
            line = self._read_raw()
            if line is None:
                return None
            m = re.search(r"Static Eval\[Black\]:.*WDL\s+([\d.]+)", line)
            if m:
                return float(m.group(1)) / 100.0
        return None

    def init_game(self, size=BOARD_SIZE, renju=False):
        self._write(f"START {size}")
        if self._read() != "OK":
            raise RuntimeError("引擎初始化失败")
        self._write(f"INFO TIMEOUT_TURN {self._time}")
        self._write(f"INFO MAX_DEPTH {self._depth}")
        self._write("INFO RULE 2" if renju else "INFO RULE 0")  # 2=连珠(禁手) 0=无禁手
        self._write("INFO SHOW_DETAIL 2")  # 开启实时 INFO 输出（含 WINRATE / DEPTH / EVAL）
        self._info_depth = 0

    def turn(self, x, y):
        with self._lock:
            self._proc.stdin.write(f"TURN {x},{y}\n")
            self._proc.stdin.flush()
        resp = self._read()
        if not resp:
            return None
        m = re.match(r"(-?\d+)\s*,\s*(-?\d+)", resp)
        if not m:
            return None
        ax, ay = int(m.group(1)), int(m.group(2))
        # 低难度下加轻微扰动：跳过最优解走次优
        if self._noise > 0 and random.random() < self._noise:
            alt = self._read_alt_move()
            if alt:
                return alt
        return (ax, ay)

    def takeback(self, n=1):
        """同步悔棋：让引擎撤销最近 n 手，保持引擎内部棋盘与本地一致。"""
        for _ in range(n):
            with self._lock:
                if not self._proc or self._proc.poll() is not None:
                    raise RuntimeError("引擎未运行")
                self._proc.stdin.write("TAKEBACK 0,0\n")
                self._proc.stdin.flush()
            self._read()  # 消费引擎返回的 "OK"

    def _read_alt_move(self):
        """尝试从 engine 的 bestline 中取第2步作为备选，模拟不完美落子。"""
        return None  # 保持用最优解，扰动不在坐标层做

    def begin(self):
        self._write("BEGIN")
        resp = self._read()
        if resp:
            m = re.match(r"(-?\d+)\s*,\s*(-?\d+)", resp)
            if m:
                return (int(m.group(1)), int(m.group(2)))
        return None

    def stop(self):
        if self._proc and self._proc.poll() is None:
            try:
                self._write("END")
            except Exception:
                pass
            try:
                self._proc.terminate()
                self._proc.wait(timeout=3)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None

    @property
    def alive(self):
        return self._proc is not None and self._proc.poll() is None


# ============================================================
# 棋盘逻辑
# ============================================================
class Board:
    def __init__(self, size=BOARD_SIZE):
        self.size = size
        self.renju = False      # 是否启用连珠禁手
        self.reset()

    def reset(self):
        self.grid  = [[0] * self.size for _ in range(self.size)]
        self.turn  = 1          # 1=黑 2=白
        self.log   = []         # [(x,y,player), ...]
        self.last  = None
        self.over  = False
        self.win   = 0
        self.line  = []

    def move(self, x, y, player=None):
        if player is None:
            player = self.turn
        if self.over:
            return False
        if not (0 <= x < self.size and 0 <= y < self.size):
            return False
        if self.grid[y][x] != 0:
            return False
        if self.renju and renju_forbidden(self.grid, x, y, player):
            return False
        self.grid[y][x] = player
        self.log.append((x, y, player))
        self.last = (x, y)
        self.turn = 3 - player
        w = self._check(x, y)
        if w:
            self.over = True
            self.win  = player
            self.line = w
        elif len(self.log) == self.size * self.size:
            self.over = True
            self.win  = 0
        return True

    def undo(self):
        """悔一步（撤销最近一手及 AI 的应手）"""
        if self.over or len(self.log) < 2:
            return False
        # 如果最近一手是 AI（偶数手），也撤销
        self.log.pop()  # AI 的着法
        _, _, player = self.log.pop()  # 玩家的着法
        self.grid = [[0] * self.size for _ in range(self.size)]
        for x, y, p in self.log:
            self.grid[y][x] = p
        self.last = self.log[-1] if self.log else None
        self.turn = player  # 撤销后仍轮到玩家落子（黑棋/白棋模式均正确）
        self.over = False
        self.win  = 0
        self.line = []
        return True

    def _check(self, x, y):
        p = self.grid[y][x]
        for dx, dy in ((1, 0), (0, 1), (1, 1), (1, -1)):
            line = [(x, y)]
            for i in range(1, 5):
                nx, ny = x + dx * i, y + dy * i
                if 0 <= nx < self.size and 0 <= ny < self.size and self.grid[ny][nx] == p:
                    line.append((nx, ny))
                else:
                    break
            for i in range(1, 5):
                nx, ny = x - dx * i, y - dy * i
                if 0 <= nx < self.size and 0 <= ny < self.size and self.grid[ny][nx] == p:
                    line.insert(0, (nx, ny))
                else:
                    break
            if len(line) >= 5:
                return line
        return None


# ============================================================
# 界面
# ============================================================
class App:
    def __init__(self, root):
        self.root = root
        self.root.title("五子棋")
        self.root.resizable(False, False)
        self.root.configure(bg=C_BG)

        self.board  = Board()
        self.engine = Engine()
        self.engine.configure(DEFAULT_DIFFICULTY)

        self.busy     = False
        self.hover    = None
        self.ai_first = False
        self.human_c  = 1
        self.ai_c     = 2
        self.gid      = 0
        self.diff     = DEFAULT_DIFFICULTY
        self.renju    = False   # 是否启用连珠禁手

        self._winrate   = None   # 当前 AI 胜率 [0,1]；None 表示暂无数据
        self._win_depth = None   # 对应的搜索深度

        self._build()
        self.engine.set_info_callback(self._on_engine_info)
        self._launch()
        self.root.protocol("WM_DELETE_WINDOW", self._shutdown)

    # ---------- UI 构建 ----------
    def _build(self):
        frame = tk.Frame(self.root, bg=C_BG)
        frame.pack(padx=10, pady=10)

        # 顶部
        top = tk.Frame(frame, bg=C_BG)
        top.pack(fill=tk.X, pady=(0, 6))

        tk.Label(top, text="五子棋", font=("Microsoft YaHei", 18, "bold"),
                 fg=C_FG, bg=C_BG).pack(side=tk.LEFT)

        ctrls = tk.Frame(top, bg=C_BG)
        ctrls.pack(side=tk.RIGHT)

        tk.Label(ctrls, text="难度", font=("Microsoft YaHei", 9),
                 fg=C_DIM, bg=C_BG).pack(side=tk.LEFT, padx=(0, 4))

        self._diff_var = tk.StringVar(value=DEFAULT_DIFFICULTY)
        cb = ttk.Combobox(ctrls, textvariable=self._diff_var,
                          values=list(DIFFICULTY.keys()), state="readonly",
                          width=5, font=("Microsoft YaHei", 9))
        cb.pack(side=tk.LEFT, padx=(0, 12))
        cb.bind("<<ComboboxSelected>>", self._on_diff_change)

        self._renju_var = tk.BooleanVar(value=False)
        tk.Checkbutton(ctrls, text="禁手", variable=self._renju_var,
                       font=("Microsoft YaHei", 9), bg=C_BG, fg=C_FG,
                       activebackground=C_BG, activeforeground=C_FG,
                       selectcolor=C_BG, highlightthickness=0,
                       command=self._on_renju_toggle).pack(side=tk.LEFT, padx=(0, 12))

        for text, cmd in [("新游戏", self._new_game), ("悔棋", self._undo), ("AI 先手", self._ai_first)]:
            b = tk.Button(ctrls, text=text, font=("Microsoft YaHei", 9),
                          bg=C_BTN, fg=C_BTN_FG, relief=tk.FLAT,
                          padx=10, pady=4, activebackground="#555",
                          activeforeground=C_FG, command=cmd)
            b.pack(side=tk.LEFT, padx=3)
            setattr(self, f"btn_{text.replace(' ', '_')}", b)

        # 棋盘
        cw = BOARD_SIZE * CELL_SIZE + MARGIN * 2
        ch = BOARD_SIZE * CELL_SIZE + MARGIN * 2
        self.canvas = tk.Canvas(frame, width=cw, height=ch,
                                bg=C_BOARD, highlightthickness=0)
        self.canvas.pack()

        # 实时胜率条
        self._win_canvas = tk.Canvas(frame, width=cw, height=40,
                                     bg=C_BG, highlightthickness=0)
        self._win_canvas.pack(fill=tk.X, pady=(6, 0))

        # 状态
        sf = tk.Frame(frame, bg=C_BG)
        sf.pack(fill=tk.X, pady=(6, 0))
        self._status = tk.Label(sf, text="启动中...", font=("Microsoft YaHei", 10),
                                fg=C_FG, bg=C_BG)
        self._status.pack(side=tk.LEFT)
        self._count_lbl = tk.Label(sf, text="", font=("Microsoft YaHei", 8),
                                   fg=C_DIM, bg=C_BG)
        self._count_lbl.pack(side=tk.RIGHT)

        # 事件
        self.canvas.bind("<Button-1>",     self._click)
        self.canvas.bind("<Motion>",       self._move)
        self.canvas.bind("<Leave>",        self._leave)

        self._redraw()
        self._redraw_winrate()

    # ---------- 引擎生命周期 ----------
    def _launch(self):
        def _start():
            try:
                self.engine.start()
                self.root.after(0, self._on_ready)
            except Exception as e:
                self.root.after(0, lambda: self._fail(str(e)))
        threading.Thread(target=_start, daemon=True).start()

    def _on_ready(self):
        try:
            self.engine.init_game(renju=self.renju)
        except Exception as e:
            self._fail(str(e))
            return
        if self.ai_first:
            self._ai_go_first()
        else:
            self._set_status("黑棋先行，点击落子")
            self._enable(True)

    def _fail(self, msg):
        self._set_status(f"引擎异常: {msg}")
        self._enable(True)

    # ---------- 绘图 ----------
    def _redraw(self):
        c = self.canvas
        c.delete("board", "stone", "last", "win", "hover")
        # 背景
        c.create_rectangle(0, 0,
                           BOARD_SIZE * CELL_SIZE + MARGIN * 2,
                           BOARD_SIZE * CELL_SIZE + MARGIN * 2,
                           fill=C_BOARD, outline="", tags="board")
        # 网格
        for i in range(BOARD_SIZE):
            x = MARGIN + i * CELL_SIZE
            c.create_line(x, MARGIN, x, MARGIN + (BOARD_SIZE - 1) * CELL_SIZE,
                          fill=C_LINE, width=1, tags="board")
            c.create_line(MARGIN, x, MARGIN + (BOARD_SIZE - 1) * CELL_SIZE, x,
                          fill=C_LINE, width=1, tags="board")
        # 星位
        for sx, sy in [(3,3),(3,7),(3,11),(7,3),(7,7),(7,11),(11,3),(11,7),(11,11)]:
            cx, cy = MARGIN + sx * CELL_SIZE, MARGIN + sy * CELL_SIZE
            c.create_oval(cx - 3, cy - 3, cx + 3, cy + 3,
                          fill=C_LINE, outline="", tags="board")
        # 棋子
        for y in range(self.board.size):
            for x in range(self.board.size):
                if self.board.grid[y][x]:
                    self._stone(x, y, self.board.grid[y][x])
        # 胜利连线
        if self.board.line:
            for wx, wy in self.board.line:
                cx, cy = MARGIN + wx * CELL_SIZE, MARGIN + wy * CELL_SIZE
                c.create_oval(cx - STONE_R - 2, cy - STONE_R - 2,
                              cx + STONE_R + 2, cy + STONE_R + 2,
                              outline=C_WIN, width=2, tags="win")
        # 最后落子标记
        if self.board.last:
            lx, ly = self.board.last
            cx, cy = MARGIN + lx * CELL_SIZE, MARGIN + ly * CELL_SIZE
            dot = C_WHITE if self.board.grid[ly][lx] == 1 else C_BLACK
            c.create_oval(cx - 4, cy - 4, cx + 4, cy + 4,
                          fill=dot, outline="", tags="last")
        # 悬停预览
        if self.hover and self.hover[0] is not None \
                and not self.board.over and not self.busy:
            hx, hy = self.hover
            if 0 <= hx < self.board.size and 0 <= hy < self.board.size \
                    and self.board.grid[hy][hx] == 0:
                cx, cy = MARGIN + hx * CELL_SIZE, MARGIN + hy * CELL_SIZE
                c.create_oval(cx - STONE_R + 1, cy - STONE_R + 1,
                              cx + STONE_R - 1, cy + STONE_R - 1,
                              fill="", outline=C_DIM, dash=(3, 3),
                              width=2, tags="hover")

    def _stone(self, x, y, player):
        cx, cy = MARGIN + x * CELL_SIZE, MARGIN + y * CELL_SIZE
        c = self.canvas
        # 阴影
        c.create_oval(cx - STONE_R + 1, cy - STONE_R + 1,
                      cx + STONE_R + 1, cy + STONE_R + 1,
                      fill="#777", outline="", tags="stone")
        # 棋子
        base = C_BLACK if player == 1 else C_WHITE
        outline = "#333" if player == 1 else "#BBB"
        c.create_oval(cx - STONE_R, cy - STONE_R,
                      cx + STONE_R, cy + STONE_R,
                      fill=base, outline=outline, width=1, tags="stone")
        # 光泽
        hl_r = STONE_R // 3
        c.create_oval(cx - hl_r, cy - hl_r,
                      cx + hl_r, cy + hl_r,
                      fill="", outline="#888" if player == 1 else "#FFF",
                      width=1, tags="stone")

    # ---------- 实时胜率 ----------
    def _on_engine_info(self, depth, winrate):
        """引擎搜索线程回调，切回主线程刷新胜率显示。"""
        gid = self.gid
        self.root.after(0, lambda: self._update_winrate(winrate, depth, gid))

    def _update_winrate(self, winrate, depth, gid):
        if gid != self.gid:
            return
        self._winrate   = max(0.0, min(1.0, float(winrate)))
        self._win_depth = depth
        self._redraw_winrate()

    def _reset_winrate(self):
        self._winrate   = None
        self._win_depth = None
        self._redraw_winrate()

    def _redraw_winrate(self):
        """围棋记谱式胜率条：黑优势从中间向左延伸、白优势从中间向右延伸，
        并在括号中标注 AI / 玩家对应的执子颜色。"""
        c = self._win_canvas
        c.delete("all")
        w = int(c["width"])
        h = int(c["height"])
        bar_y0, bar_y1 = 21, h - 3
        cx = w / 2.0
        half = w / 2.0

        black_is_ai = self.ai_c == 1
        black_tag = "AI" if black_is_ai else "玩家"
        white_tag = "玩家" if black_is_ai else "AI"

        if self._winrate is None:
            black_pct = white_pct = "—"
            black_adv = white_adv = 0.0
        else:
            ai_wr = max(0.0, min(1.0, float(self._winrate)))
            black_wr = ai_wr if black_is_ai else 1.0 - ai_wr
            white_wr = 1.0 - black_wr
            black_pct = f"{black_wr * 100:.1f}%"
            white_pct = f"{white_wr * 100:.1f}%"
            # 优势量：胜率 0.5 → 0，1.0 → 1（此时另一方为 0）
            black_adv = max(0.0, min(1.0, 2.0 * black_wr - 1.0))
            white_adv = max(0.0, min(1.0, 2.0 * white_wr - 1.0))

        # 顶部角色 + 胜率标签
        c.create_text(4, 11, anchor="w", text=f"黑（{black_tag}） {black_pct}",
                      fill=C_FG, font=("Microsoft YaHei", 10, "bold"))
        c.create_text(w - 4, 11, anchor="e", text=f"白（{white_tag}） {white_pct}",
                      fill=C_FG, font=("Microsoft YaHei", 10, "bold"))

        # 中性底色 + 细边框
        c.create_rectangle(0, bar_y0, w, bar_y1, fill="#4A4A4A", outline="#666666")
        # 黑优势从中间向左延伸，白优势从中间向右延伸
        black_px = int(round(black_adv * half))
        white_px = int(round(white_adv * half))
        if black_px > 0:
            c.create_rectangle(int(cx) - black_px, bar_y0, int(cx), bar_y1,
                               fill=C_BLACK, outline="")
        if white_px > 0:
            c.create_rectangle(int(cx), bar_y0, int(cx) + white_px, bar_y1,
                               fill=C_WHITE, outline="")
        # 中线（均势点）
        c.create_line(cx, bar_y0, cx, bar_y1, fill="#CC3333", width=2)

    # ---------- 交互 ----------
    def _click(self, e):
        if self.board.over or self.busy:
            return
        if not self.engine.alive:
            return
        x, y = self._at(e.x, e.y)
        if x is None:
            return
        if self.board.renju and self.board.grid[y][x] == 0 \
                and renju_forbidden(self.board.grid, x, y, self.board.turn):
            self._set_status("禁手：此处为黑方禁手点（三三/四四/长连），不能落子")
            return
        if not self.board.move(x, y):
            return
        self._redraw()
        self.hover = None
        if self.board.over:
            self._end()
            return
        self._reset_winrate()
        self._ask_ai(x, y)

    def _move(self, e):
        if self.board.over or self.busy:
            return
        x, y = self._at(e.x, e.y)
        if x is None:
            if self.hover is not None:
                self.hover = None
                self._redraw()
            return
        if self.hover != (x, y):
            self.hover = (x, y)
            self._redraw()

    def _leave(self, e):
        if self.hover is not None:
            self.hover = None
            self._redraw()

    def _at(self, px, py):
        x = round((px - MARGIN) / CELL_SIZE)
        y = round((py - MARGIN) / CELL_SIZE)
        if 0 <= x < BOARD_SIZE and 0 <= y < BOARD_SIZE:
            cx, cy = MARGIN + x * CELL_SIZE, MARGIN + y * CELL_SIZE
            if abs(px - cx) <= CELL_SIZE / 2 and abs(py - cy) <= CELL_SIZE / 2:
                return (x, y)
        return (None, None)

    # ---------- AI 回合 ----------
    def _ask_ai(self, hx, hy):
        self.busy = True
        self._set_status("思考中...")
        self._enable(False)
        gid = self.gid

        def _work():
            try:
                m = self.engine.turn(hx, hy)
                self.root.after(0, lambda: self._ai_done(m, gid))
            except Exception as e:
                self.root.after(0, lambda: self._ai_err(str(e), gid))

        threading.Thread(target=_work, daemon=True).start()

    def _ai_done(self, move, gid):
        if gid != self.gid:
            return
        self.busy = False
        if not move:
            self._set_status("AI 未响应，请重试")
            self._enable(True)
            return
        ax, ay = move
        if not (0 <= ax < BOARD_SIZE and 0 <= ay < BOARD_SIZE):
            self._set_status("AI 出界")
            self._enable(True)
            return
        if not self.board.move(ax, ay):
            self._set_status("AI 着法无效")
            self._enable(True)
            return
        self._redraw()
        self.hover = None
        if self.board.over:
            self._end()
        else:
            piece = "白棋" if self.ai_first else "黑棋"
            self._set_status(f"轮到你了（{piece}）")
            self._enable(True)

    def _ai_err(self, msg, gid):
        if gid != self.gid:
            return
        self.busy = False
        self._set_status(f"异常: {msg}")
        self._enable(True)

    def _ai_first(self):
        if self.busy:
            return
        self._new_game(ai_first=True)

    def _ai_go_first(self):
        self.busy = True
        self._set_status("AI 先行，思考中...")
        self._enable(False)
        gid = self.gid

        def _work():
            try:
                m = self.engine.begin()
                self.root.after(0, lambda: self._ai_first_done(m, gid))
            except Exception as e:
                self.root.after(0, lambda: self._ai_err(str(e), gid))

        threading.Thread(target=_work, daemon=True).start()

    def _ai_first_done(self, move, gid):
        if gid != self.gid:
            return
        self.busy = False
        if not move:
            self._set_status("AI 未响应")
            self._enable(True)
            return
        ax, ay = move
        if not (0 <= ax < BOARD_SIZE and 0 <= ay < BOARD_SIZE):
            self._set_status("AI 出界")
            self._enable(True)
            return
        if not self.board.move(ax, ay):
            self._set_status("AI 着法无效")
            self._enable(True)
            return
        self._redraw()
        if self.board.over:
            self._end()
        else:
            self._set_status("轮到你了（白棋）")
            self._enable(True)

    # ---------- 控制 ----------
    def _new_game(self, ai_first=False):
        if self.board.log and not messagebox.askyesno("新游戏", "放弃当前对局？"):
            return
        self.board.reset()
        self.board.renju = self.renju   # 应用禁手设置
        self.busy     = False
        self.hover    = None
        self.ai_first = ai_first
        self.human_c  = 2 if ai_first else 1
        self.ai_c     = 1 if ai_first else 2
        self.gid     += 1

        if self.engine.alive:
            try:
                self.engine.stop()
            except Exception:
                pass
        self._launch()
        self._redraw()
        self._reset_winrate()
        self._count_lbl.config(text="")
        self._set_status("启动中...")
        self._enable(False)

    def _undo(self):
        if self.busy or self.board.over or len(self.board.log) < 2:
            return
        self.board.undo()
        # 同步引擎内部棋盘：撤销引擎最后两手，避免引擎状态与本地棋盘脱节
        black_wr = None
        if self.engine.alive:
            try:
                self.engine.takeback(2)
            except Exception:
                pass
            # 悔棋后重新评估当前局面，让胜率条继续显示
            try:
                black_wr = self.engine.evaluate()
            except Exception:
                black_wr = None

        if black_wr is not None:
            # evaluate 返回黑方胜率，换算为引擎（AI 侧）胜率
            self._winrate   = black_wr if self.ai_c == 1 else (1.0 - black_wr)
            self._win_depth = None
        else:
            self._winrate   = None
            self._win_depth = None

        self._redraw()
        self._redraw_winrate()
        self.hover = None
        self._set_status("已悔棋，轮到你了")
        self._enable(True)

    def _end(self):
        self._enable(True)
        w = self.board.win
        if w == self.human_c:
            s = "你赢了"
            self._winrate, self._win_depth = 0.0, None
        elif w == self.ai_c:
            s = "AI 获胜"
            self._winrate, self._win_depth = 1.0, None
        else:
            s = "平局"
            self._winrate, self._win_depth = 0.5, None
        self._set_status(f"{s}  —  共 {len(self.board.log)} 手")
        self._count_lbl.config(text="")
        self._redraw_winrate()

    def _on_diff_change(self, e=None):
        self.diff = self._diff_var.get()
        self.engine.configure(self.diff)

    def _on_renju_toggle(self):
        self.renju = self._renju_var.get()
        self._set_status("已启用禁手（连珠规则），将在新对局生效" if self.renju
                         else "已关闭禁手，将在新对局生效")

    # ---------- 辅助 ----------
    def _set_status(self, text):
        self._status.config(text=text)

    def _enable(self, on):
        s = tk.NORMAL if on else tk.DISABLED
        self.btn_新游戏.config(state=s)
        self.btn_悔棋.config(state=s)
        self.btn_AI_先手.config(state=s)

    def _shutdown(self):
        if self.engine.alive:
            self.engine.stop()
        self.root.destroy()


# ============================================================
# 入口
# ============================================================
def main():
    root = tk.Tk()
    cw = BOARD_SIZE * CELL_SIZE + MARGIN * 2
    ch = BOARD_SIZE * CELL_SIZE + MARGIN * 2
    ww, wh = cw + 20, ch + 150
    x = (root.winfo_screenwidth()  - ww) // 2
    y = (root.winfo_screenheight() - wh) // 2
    root.geometry(f"{ww}x{wh}+{x}+{y}")
    App(root)
    root.mainloop()

if __name__ == "__main__":
    main()
