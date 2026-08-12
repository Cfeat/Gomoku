#!/usr/bin/env python3
"""构建单文件五子棋软件包 (PyInstaller --onefile)"""
import os, sys, shutil, subprocess

BASE   = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(BASE, "engine")
ICON   = os.path.join(BASE, "wuziqi.ico")
DIST   = os.path.join(BASE, "dist")

def clean():
    for d in ["build", "dist"]:
        p = os.path.join(BASE, d)
        if os.path.exists(p):
            shutil.rmtree(p)
    for f in os.listdir(BASE):
        if f.endswith(".spec"):
            os.remove(os.path.join(BASE, f))

def build():
    clean()

    # 收集引擎文件
    engine_files = []
    for fn in os.listdir(ENGINE):
        fp = os.path.join(ENGINE, fn)
        if os.path.isfile(fp):
            engine_files.append((fp, "engine"))

    # 构建 --add-data 参数
    add_data = []
    for src, dest in engine_files:
        add_data += ["--add-data", f"{src}{os.pathsep}{dest}"]

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "Wuziqi",
        "--onefile",
        "--windowed",
        "--icon", ICON,
        "--noconfirm",
        "--clean",
        "--distpath", DIST,
        "--workpath", os.path.join(BASE, "build"),
    ] + add_data + [os.path.join(BASE, "wuziqi.py")]

    print(f"Packing {len(engine_files)} engine files into single exe...")
    result = subprocess.run(cmd, cwd=BASE)

    if result.returncode != 0:
        print("PyInstaller failed!")
        return False

    exe = os.path.join(DIST, "Wuziqi.exe")
    size_mb = os.path.getsize(exe) / (1024 * 1024)
    print(f"\n[OK] {exe}")
    print(f"     Size: {size_mb:.1f} MB  (standalone, no dependencies)")
    return True

if __name__ == "__main__":
    success = build()
    sys.exit(0 if success else 1)
