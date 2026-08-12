#!/usr/bin/env python3
"""Build APK using aapt2 + system zip (not Python zipfile)."""
import os, sys, shutil, subprocess, glob

BASE     = os.path.dirname(os.path.abspath(__file__))
DEP      = os.path.join(BASE, "..", "dependency")
SDK      = os.path.join(DEP, "android-sdk")
BUILD    = os.path.join(SDK, "build-tools", "34.0.0")
PLATFORM = os.path.join(SDK, "platforms", "android-34")
AAPT2    = os.path.join(BUILD, "aapt2.exe")
D8       = os.path.join(BUILD, "d8.bat")
APKSIGN  = os.path.join(BUILD, "apksigner.bat")
ZIPALIGN = os.path.join(BUILD, "zipalign.exe")
ANDROID_JAR = os.path.join(PLATFORM, "android.jar")

MANIFEST = os.path.join(BASE, "app", "src", "main", "AndroidManifest.xml")
JAVA_SRC = os.path.join(BASE, "app", "src", "main", "java")
RES_DIR  = os.path.join(BASE, "app", "src", "main", "res")
ASSETS   = os.path.join(BASE, "app", "src", "main", "assets")
JNI      = os.path.join(BASE, "app", "src", "main", "jniLibs")
OUT      = os.path.join(BASE, "build")
OUT_APK  = os.path.join(BASE, "Wuziqi.apk")

ZIP = "zip"  # system zip command

ENGINE_DIR = os.path.join(BASE, "..", "engine")
WEIGHT_EXTS = (".bin", ".lz4", ".toml")

def sync_assets_from_engine():
    """Copy weight/config files from ../engine into assets (avoid duplicating in git)."""
    os.makedirs(ASSETS, exist_ok=True)
    if not os.path.isdir(ENGINE_DIR):
        raise FileNotFoundError(f"engine dir missing: {ENGINE_DIR}")
    copied = 0
    for fn in os.listdir(ENGINE_DIR):
        if not fn.endswith(WEIGHT_EXTS):
            continue
        if fn.endswith(".exe"):
            continue
        src = os.path.join(ENGINE_DIR, fn)
        dst = os.path.join(ASSETS, fn)
        if not os.path.isfile(src):
            continue
        if (not os.path.exists(dst)
                or os.path.getsize(dst) != os.path.getsize(src)
                or os.path.getmtime(dst) < os.path.getmtime(src)):
            shutil.copy2(src, dst)
            copied += 1
    # Keep UI entry
    index = os.path.join(ASSETS, "index.html")
    if not os.path.isfile(index):
        raise FileNotFoundError(f"missing UI: {index}")
    print(f"  synced assets from engine/ ({copied} file(s) copied)")

def run(cmd):
    print(f"  {' '.join(cmd[:4])}...")
    subprocess.run(cmd, check=True)

def shell(cmd):
    print(f"  {cmd[:60]}...")
    subprocess.run(cmd, shell=True, check=True)

def build():
    print("[0/7] sync assets from engine/...")
    sync_assets_from_engine()

    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT, exist_ok=True)

    # 1. Compile resources
    print("[1/7] aapt2 compile...")
    flat = os.path.join(OUT, "flat")
    os.makedirs(flat, exist_ok=True)
    for f in glob.glob(os.path.join(RES_DIR, "**", "*.xml"), recursive=True):
        run([AAPT2, "compile", "-o", flat, f])

    # 2. Link base APK with assets
    print("[2/7] aapt2 link...")
    base_apk = os.path.join(OUT, "base.apk")
    cmd = [AAPT2, "link", "-o", base_apk, "-I", ANDROID_JAR,
           "--manifest", MANIFEST, "-A", ASSETS,
           "--java", os.path.join(OUT, "gen"),
           "--min-sdk-version", "24", "--target-sdk-version", "34",
           "--version-code", "1", "--version-name", "1.0",
           "--auto-add-overlay"]
    for f in glob.glob(os.path.join(flat, "*.flat")):
        cmd.extend(["-R", f])
    run(cmd)

    # 3. Compile Java
    print("[3/7] javac...")
    classes = os.path.join(OUT, "classes")
    os.makedirs(classes, exist_ok=True)
    javas = []
    for root, dirs, files in os.walk(JAVA_SRC):
        for f in files:
            if f.endswith(".java"):
                javas.append(os.path.join(root, f))
    run(["javac", "-d", classes, "-classpath", ANDROID_JAR,
         "-source", "11", "-target", "11"] + javas)

    # 4. Dex
    print("[4/7] d8...")
    run([D8, "--lib", ANDROID_JAR, "--output", OUT, "--min-api", "24"]
        + glob.glob(os.path.join(classes, "**", "*.class"), recursive=True))

    # 5. Add classes.dex and native libs using system zip
    print("[5/7] zip classes.dex + libs...")
    # Create staging dir with everything to add
    stage = os.path.join(OUT, "stage")
    os.makedirs(stage, exist_ok=True)
    shutil.copy2(os.path.join(OUT, "classes.dex"), os.path.join(stage, "classes.dex"))
    if os.path.exists(JNI):
        for abi in os.listdir(JNI):
            ap = os.path.join(JNI, abi)
            if os.path.isdir(ap):
                dst = os.path.join(stage, "lib", abi)
                os.makedirs(dst, exist_ok=True)
                for f in os.listdir(ap):
                    shutil.copy2(os.path.join(ap, f), os.path.join(dst, f))

    cwd = os.getcwd()
    os.chdir(stage)
    # Add classes.dex compressed
    shell(f'{ZIP} -9 "{base_apk}" classes.dex')
    # Add native libs stored (no compression)
    if os.path.exists("lib"):
        shell(f'{ZIP} -0 -r "{base_apk}" lib')
    os.chdir(cwd)
    shutil.rmtree(stage, ignore_errors=True)

    # 6. Align & sign
    print("[6/6] align & sign...")
    aligned = os.path.join(OUT, "aligned.apk")
    run([ZIPALIGN, "-f", "-p", "4", base_apk, aligned])

    ks = os.path.join(OUT, "debug.keystore")
    if not os.path.exists(ks):
        run(["keytool", "-genkey", "-v", "-keystore", ks,
             "-storepass", "android", "-alias", "androiddebugkey",
             "-keypass", "android", "-keyalg", "RSA", "-keysize", "2048",
             "-validity", "10000", "-dname", "CN=Wuziqi,O=Dev,C=CN"])

    run([APKSIGN, "sign", "--ks", ks,
         "--ks-pass", "pass:android", "--ks-key-alias", "androiddebugkey",
         "--key-pass", "pass:android",
         "--out", OUT_APK, aligned])

    mb = os.path.getsize(OUT_APK) / 1048576
    print(f"\n  [OK] {OUT_APK}  ({mb:.1f} MB)")

if __name__ == "__main__":
    build()
