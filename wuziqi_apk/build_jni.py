#!/usr/bin/env python3
"""Build librapfi.so (Rapfi + JNI wrapper) for Android ARM64 using NDK directly."""
import os, sys, subprocess, glob, shutil

BASE     = os.path.dirname(os.path.abspath(__file__))
RAPFI    = os.path.join(BASE, "..", "rapfi", "Rapfi")
JNI_DIR  = os.path.join(BASE, "jni")
DEP      = os.path.join(BASE, "..", "dependency")
NDK      = os.path.join(DEP, "android-sdk", "ndk", "26.1.10909125")
TOOLCHAIN = os.path.join(NDK, "toolchains", "llvm", "prebuilt", "windows-x86_64")
SYSROOT  = os.path.join(TOOLCHAIN, "sysroot")
CLANG    = os.path.join(TOOLCHAIN, "bin", "clang++.exe")

# Build targets: (ABI, target triple, CFLAGS extra)
TARGETS = [
    ("arm64-v8a",   "aarch64-linux-android24",     ["-march=armv8-a+simd"]),
]

# Source files
SOURCES = [
    "command/argutils.cpp", "command/benchmark.cpp", "command/command.cpp",
    "command/gomocup.cpp",
    "core/hash.cpp", "core/iohelper.cpp", "core/utils.cpp", "core/platform.cpp",
    "core/version.cpp",
    "database/dbclient.cpp", "database/dbutils.cpp", "database/dbtypes.cpp",
    "database/yxdbstorage.cpp",
    "eval/eval.cpp", "eval/evaluator.cpp", "eval/mix9svqnnue.cpp", "eval/mix10nnue.cpp",
    "game/board.cpp", "game/movegen.cpp", "game/pattern.cpp",
    "search/hashtable.cpp", "search/movepick.cpp", "search/opening.cpp",
    "search/searchcommon.cpp", "search/searchoutput.cpp", "search/searchthread.cpp",
    "search/timecontrol.cpp",
    "search/ab/history.cpp", "search/ab/search.cpp",
    "search/mcts/node.cpp", "search/mcts/search.cpp",
    "config.cpp", "internalConfig.cpp", "main.cpp",
    "external/lz4/src/lz4_all.c", "external/lz4/src/xxhash.c",
]

INCLUDES = [
    RAPFI,
    os.path.join(RAPFI, "command"),
    os.path.join(RAPFI, "core"),
    os.path.join(RAPFI, "database"),
    os.path.join(RAPFI, "eval"),
    os.path.join(RAPFI, "game"),
    os.path.join(RAPFI, "search"),
    os.path.join(RAPFI, "search/ab"),
    os.path.join(RAPFI, "search/mcts"),
    os.path.join(RAPFI, "tuning"),
    os.path.join(RAPFI, "external/lz4/include"),
    os.path.join(RAPFI, "external/simde/include"),
    os.path.join(RAPFI, "external/cpptoml/include"),
    os.path.join(RAPFI, "external/cxxopts/include"),
]

CFLAGS = [
    "-std=c++17", "-stdlib=libc++", "-fPIC", "-O3", "-DNDEBUG", "-DANDROID",
    "-DNO_COMMAND_MODULES", "-DUSE_NEON",
    "-Wall", "-Wno-unused-variable", "-Wno-unused-function",
    "-Wno-missing-braces", "-Wno-sign-compare",
]

LFLAGS = [
    "-shared", "-Wl,-soname,librapfi.so",
    # Android 15+ devices may use 16KB pages; 4KB-aligned ELFs fail to dlopen.
    "-Wl,-z,max-page-size=16384",
    "-lm", "-latomic", "-static-libstdc++",
]

def build():
    for abi, target, extra_cflags in TARGETS:
        out_dir = os.path.join(BASE, "build_jni", abi)
        out_so  = os.path.join(BASE, "app", "src", "main", "jniLibs", abi, "librapfi.so")
        os.makedirs(out_dir, exist_ok=True)
        os.makedirs(os.path.dirname(out_so), exist_ok=True)

        objs = []
        tflags = CFLAGS + extra_cflags

        # Compile Rapfi sources
        for src in SOURCES:
            path = os.path.join(RAPFI, src)
            obj  = os.path.join(out_dir, src.replace("/", "_") + ".o")
            cmd = [CLANG, "-c", path, "-o", obj, f"--target={target}", f"--sysroot={SYSROOT}"]
            for inc in INCLUDES:
                cmd += ["-I", inc]
            cmd += tflags
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            objs.append(obj)

        # Compile JNI wrapper
        jni_src = os.path.join(JNI_DIR, "engine_jni.cpp")
        jni_obj = os.path.join(out_dir, "engine_jni.cpp.o")
        cmd = [CLANG, "-c", jni_src, "-o", jni_obj, f"--target={target}", f"--sysroot={SYSROOT}"]
        for inc in INCLUDES:
            cmd += ["-I", inc]
        cmd += tflags
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        objs.append(jni_obj)

        # Link
        cmd = [CLANG, f"--target={target}", f"--sysroot={SYSROOT}",
               "-o", out_so] + objs + LFLAGS
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        size = os.path.getsize(out_so) / (1024 * 1024)
        print(f"  {abi}: librapfi.so  ({size:.1f} MB)")

    print(f"\n[OK] JNI libraries built")

if __name__ == "__main__":
    build()
