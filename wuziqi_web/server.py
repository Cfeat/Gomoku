#!/usr/bin/env python3
"""五子棋网页版 — Flask + SocketIO + Rapfi"""
import os
import re
import threading
import subprocess
import random

from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit

# ============================================================
BOARD_SIZE = 15
ROOT_DIR    = os.path.dirname(os.path.abspath(__file__))
ENGINE_PATH = os.path.join(ROOT_DIR, "..", "engine", "pbrain-rapfi.exe")
ENGINE_DIR  = os.path.join(ROOT_DIR, "..", "engine")

DIFFICULTY = {
    "easy":   (800,  5, 1.5),
    "medium": (2000, 10, 0.8),
    "hard":   (5000, 20, 0.0),
}

app = Flask(__name__)
app.config["SECRET_KEY"] = "wzq-2024"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")


# ============================================================
class Engine:
    def __init__(self):
        self._proc  = None
        self._lock  = threading.Lock()
        self._time  = 2000
        self._depth = 10
        self._noise = 0.8
        self._info_cb    = None   # 实时信息回调 cb(depth, winrate)
        self._info_depth = 0

    def configure(self, level):
        self._time, self._depth, self._noise = DIFFICULTY[level]

    def set_info_callback(self, cb):
        self._info_cb = cb

    def start(self):
        if not os.path.exists(ENGINE_PATH):
            raise FileNotFoundError(ENGINE_PATH)
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
                raise RuntimeError("engine dead")
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

    def init(self, size=BOARD_SIZE):
        self._write(f"START {size}")
        if self._read() != "OK":
            raise RuntimeError("init fail")
        self._write(f"INFO TIMEOUT_TURN {self._time}")
        self._write(f"INFO MAX_DEPTH {self._depth}")
        self._write("INFO RULE 0")
        self._write("INFO SHOW_DETAIL 2")  # 开启实时 INFO 输出（含 WINRATE / DEPTH / EVAL）
        self._info_depth = 0

    def turn(self, x, y):
        with self._lock:
            self._proc.stdin.write(f"TURN {x},{y}\n")
            self._proc.stdin.flush()
        resp = self._read()
        if resp:
            m = re.match(r"(-?\d+)\s*,\s*(-?\d+)", resp)
            if m:
                ax, ay = int(m.group(1)), int(m.group(2))
                if self._noise > 0 and random.random() < self._noise:
                    pass  # 保持最优，扰动仅体现在深度控制
                return (ax, ay)
        return None

    def begin(self):
        self._write("BEGIN")
        resp = self._read()
        if resp:
            m = re.match(r"(-?\d+)\s*,\s*(-?\d+)", resp)
            if m:
                return (int(m.group(1)), int(m.group(2)))
        return None

    def takeback(self, n=1):
        """同步悔棋：让引擎撤销最近 n 手，保持引擎内部棋盘与本地一致。"""
        for _ in range(n):
            with self._lock:
                if not self._proc or self._proc.poll() is not None:
                    raise RuntimeError("engine dead")
                self._proc.stdin.write("TAKEBACK 0,0\n")
                self._proc.stdin.flush()
            self._read()  # 消费引擎返回的 "OK"

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


# ============================================================
class Game:
    def __init__(self):
        self.reset()

    def reset(self):
        self.grid = [[0] * BOARD_SIZE for _ in range(BOARD_SIZE)]
        self.turn = 1
        self.log  = []
        self.over = False
        self.win  = 0
        self.line = []
        self.ai_first = False
        self.busy = False

    def move(self, x, y, player=None):
        if player is None:
            player = self.turn
        if self.over:
            return False, "game over"
        if not (0 <= x < BOARD_SIZE and 0 <= y < BOARD_SIZE):
            return False, "out of bounds"
        if self.grid[y][x] != 0:
            return False, "occupied"
        self.grid[y][x] = player
        self.log.append({"x": x, "y": y, "p": player})
        self.turn = 3 - player
        w = self._check(x, y)
        if w:
            self.over = True
            self.win  = player
            self.line = [{"x": wx, "y": wy} for wx, wy in w]
        elif len(self.log) == BOARD_SIZE * BOARD_SIZE:
            self.over = True
        return True, "ok"

    def undo(self):
        if self.over or len(self.log) < 2:
            return False
        self.log.pop()  # AI 的着法
        p = self.log.pop()  # 玩家的着法
        self.grid = [[0] * BOARD_SIZE for _ in range(BOARD_SIZE)]
        for m in self.log:
            self.grid[m["y"]][m["x"]] = m["p"]
        self.turn = p["p"]  # 撤销后仍轮到玩家落子（黑棋/白棋模式均正确）
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
                if 0 <= nx < BOARD_SIZE and 0 <= ny < BOARD_SIZE and self.grid[ny][nx] == p:
                    line.append((nx, ny))
                else:
                    break
            for i in range(1, 5):
                nx, ny = x - dx * i, y - dy * i
                if 0 <= nx < BOARD_SIZE and 0 <= ny < BOARD_SIZE and self.grid[ny][nx] == p:
                    line.insert(0, (nx, ny))
                else:
                    break
            if len(line) >= 5:
                return line
        return None

    def to_dict(self):
        return {
            "grid":   self.grid,
            "turn":   self.turn,
            "log":    self.log,
            "over":   self.over,
            "win":    self.win,
            "line":   self.line,
            "aiFirst": self.ai_first,
        }


# ============================================================
engine   = Engine()
engine.configure("medium")
engine_lock = threading.Lock()  # 引擎为全局单例，串行化所有读写，避免多会话交叉污染
sessions = {}


def _session():
    from flask import session as fs
    sid = fs.get("sid")
    if sid and sid in sessions:
        return sessions[sid]
    return None


@app.route("/")
def index():
    return render_template("index.html")

@app.route("/sw.js")
def service_worker():
    from flask import send_from_directory
    return send_from_directory("static", "sw.js", mimetype="application/javascript")


@socketio.on("connect")
def on_connect():
    from flask import session as fs
    sid = fs.get("sid")
    if not sid:
        sid = request.sid
        fs["sid"] = sid
    g = Game()
    sessions[sid] = g
    with engine_lock:
        if not getattr(engine, "_proc", None) or engine._proc.poll() is not None:
            engine.start()
        engine.init()
    emit("state", g.to_dict())


@socketio.on("disconnect")
def on_disconnect():
    from flask import session as fs
    sid = fs.get("sid")
    if sid and sid in sessions:
        del sessions[sid]


@socketio.on("play")
def on_play(data):
    g = _session()
    if not g or g.over or g.busy:
        return
    x, y = data["x"], data["y"]
    ok, msg = g.move(x, y)
    if not ok:
        emit("error", {"msg": msg})
        return

    g.busy = True
    try:
        emit("state", g.to_dict())  # 立即反馈玩家落子
        if g.over:
            return

        with engine_lock:
            sid = request.sid

            def _cb(depth, wr):
                emit("winrate", {"winrate": wr, "depth": depth}, to=sid)

            engine.set_info_callback(_cb)
            try:
                ai = engine.turn(x, y)
            finally:
                engine.set_info_callback(None)
        if not ai:
            emit("error", {"msg": "AI 未响应"})
            return
        ax, ay = ai
        ok, msg = g.move(ax, ay)
        if not ok:
            emit("error", {"msg": f"AI 着法异常: {msg}"})
            return
    finally:
        g.busy = False
    emit("state", g.to_dict())


@socketio.on("ai_first")
def on_ai_first():
    g = _session()
    if not g or g.busy:
        return
    g.reset()
    g.ai_first = True

    with engine_lock:
        engine.stop()
        engine.start()
        engine.init()
        sid = request.sid

        def _cb(depth, wr):
            emit("winrate", {"winrate": wr, "depth": depth}, to=sid)

        engine.set_info_callback(_cb)
        try:
            m = engine.begin()
        finally:
            engine.set_info_callback(None)
    if not m:
        emit("error", {"msg": "AI 未响应"})
        return
    g.move(m[0], m[1])
    emit("state", g.to_dict())


@socketio.on("new_game")
def on_new_game(data=None):
    g = _session()
    if not g or g.busy:
        return
    lvl = data.get("level", "medium") if data else "medium"
    engine.configure(lvl)
    g.reset()
    with engine_lock:
        try:
            engine.stop()
        except Exception:
            pass
        engine.start()
        engine.init()
    emit("state", g.to_dict())


@socketio.on("undo")
def on_undo():
    g = _session()
    if not g or g.busy:
        return
    if g.undo():
        # 同步引擎内部棋盘：撤销引擎最后两手，并重新评估当前局面
        black_wr = None
        with engine_lock:
            try:
                engine.takeback(2)
                black_wr = engine.evaluate()
            except Exception:
                pass
        emit("state", g.to_dict())
        if black_wr is not None:
            ai_wr = black_wr if g.ai_first else (1.0 - black_wr)
            emit("winrate", {"winrate": ai_wr, "depth": None})
    else:
        emit("error", {"msg": "无法悔棋"})


@socketio.on("set_level")
def on_set_level(data):
    lvl = data.get("level", "medium")
    if lvl in DIFFICULTY:
        engine.configure(lvl)


def main():
    import webbrowser
    host, port = "127.0.0.1", 5000
    print(f"\n  五子棋网页版  http://{host}:{port}\n")
    webbrowser.open(f"http://{host}:{port}")
    socketio.run(app, host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
