# 五子棋

基于 [Rapfi](https://github.com/dhbloo/rapfi) 引擎的人机五子棋，提供 **Windows 桌面版**、**本地网页版**、**在线网页版（GitHub Pages）** 与 **Android APK**。

**🎮 在线试玩**：<https://cfeat.github.io/Gomoku/>（Rapfi 引擎以 WebAssembly 形式在浏览器中运行，无需安装，支持手机浏览器）

## 功能

- 15×15 五子棋，支持「无禁手（自由规则）」/「有禁手（连珠规则）」切换
- 初级 / 中级 / 高级难度（限时与搜索深度）
- 新游戏、悔棋、AI 先手
- 实时黑/白胜率显示（基于 Rapfi 引擎评估，桌面版 / 网页版 / Android 版均支持）
- 桌面 Tkinter 界面 / 手机 WebView 界面

## 目录结构

```
Wuziqi/
├── wuziqi.py              # Windows 桌面版入口
├── build_package.py       # 打包单文件 exe（PyInstaller）
├── run.bat / run_web.bat
├── engine/                # Rapfi Windows 引擎 + 权重 + config
├── wuziqi_web/            # Flask + Socket.IO 网页版（本地）
├── web/                   # 在线版静态站点（GitHub Pages，WASM 引擎）
├── wuziqi_apk/            # Android 工程与打包脚本
├── dependency/            # （本地）Android SDK / NDK 等，不上传
└── rapfi/                 # （本地）Rapfi 源码，不上传，需自行 clone
```

## 快速开始（Windows 桌面）

1. 安装 [Python 3.10+](https://www.python.org/)
2. 确认 `engine/pbrain-rapfi.exe` 与权重文件齐全
3. 运行：

```bat
run.bat
```

或：

```bat
python wuziqi.py
```

### 打包单文件 exe

```bat
pip install pyinstaller
python build_package.py
```

产物在 `dist/Wuziqi.exe`（该目录已加入 `.gitignore`）。

## 网页版

```bat
pip install -r requirements.txt
run_web.bat
```

浏览器打开终端提示的地址（默认本机 Flask 服务）。网页版同样依赖 `engine/` 下的 Windows 引擎。

## 在线网页版（GitHub Pages）

`web/` 目录是纯静态的在线版：Rapfi 引擎通过 Emscripten 编译为 WebAssembly（单线程 + SIMD128），在浏览器的 Web Worker 中运行，无需任何服务端。

- 由 [.github/workflows/deploy-pages.yml](.github/workflows/deploy-pages.yml) 自动构建部署：每次 `web/` 有改动推送到 `main`，CI 会 clone Rapfi 源码与权重、用 emsdk 编译 WASM 并发布到 GitHub Pages
- 引擎配置见 `web/engine-config.toml`（坐标模式 `none`、消息格式 `brief`，与前端协议解析一致）
- 首次加载需下载约 40 MB 权重数据，之后有浏览器缓存

## Android APK

### 环境准备

1. Clone Rapfi 源码到项目根目录（构建 JNI 需要）：

```bat
git clone --depth 1 https://github.com/dhbloo/rapfi.git rapfi
```

2. 准备 Android SDK / NDK，目录约定为：

```
dependency/android-sdk/
  ├── build-tools/34.0.0/
  ├── platforms/android-34/
  └── ndk/26.1.10909125/
```

也可修改 `wuziqi_apk/build_jni.py`、`wuziqi_apk/build_apk.py` 中的路径。

3. 本机需有：`javac`、`keytool`、`zip`（可用 Git for Windows 自带 zip）。

### 构建

```bat
cd wuziqi_apk
python build_jni.py
python build_apk.py
```

生成 `wuziqi_apk/Wuziqi.apk`。权重文件会在打包时从 `engine/` 自动复制到 assets，无需手工拷贝。

> 当前原生库仅构建 **arm64-v8a**，请使用 64 位 ARM 设备安装。

## 难度参数

与桌面版一致：

| 难度 | 限时 | 最大深度 |
|------|------|----------|
| 初级 | 800 ms | 5 |
| 中级 | 2000 ms | 10 |
| 高级 | 5000 ms | 20 |

## 上传 GitHub 说明

本仓库 **故意忽略** 以下内容（体积大或可本地重建）：

| 路径 | 原因 |
|------|------|
| `dependency/` | Android SDK/NDK 等，通常数 GB |
| `rapfi/` | 上游完整源码，请单独 clone |
| `dist/`、`*.apk` | 构建产物 |
| `wuziqi_apk/**/jniLibs/` | 编译出的 `.so` |
| APK assets 中的 `*.lz4` / `*.bin` | 与 `engine/` 重复 |

请保留并提交：`wuziqi.py`、`engine/`、`wuziqi_web/`、`wuziqi_apk` 源码与脚本、`README.md`、`LICENSE` 等。

建议首次提交前确认：

```bat
git status
```

确认没有误加 `dependency/`、`rapfi/`、`dist/`、`*.apk`。

## 致谢与许可

棋力引擎来自 **[Rapfi](https://github.com/dhbloo/rapfi)**（GNU GPLv3）。  
本项目衍生作品同样以 **GPL-3.0** 发布，详见 [LICENSE](LICENSE)。

使用或分发含 Rapfi 的二进制时，请同时提供对应源代码获取方式，以符合 GPLv3 要求。
