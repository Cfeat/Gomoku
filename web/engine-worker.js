/**
 * engine-worker.js — 在 Web Worker 中加载 Rapfi WASM 引擎，转发 stdin/stdout。
 *
 * Rapfi 的 Emscripten 构建（MODULARIZE=1，EXPORT_NAME=Rapfi）暴露 Rapfi 工厂函数；
 * preamble.js 已把引擎 stdin/stdout 桥接到：
 *   Module.sendCommand(cmd)      —— 写入一行命令并同步执行一次协议循环
 *   onReceiveStdout(line)        —— 引擎输出一行
 *   onReceiveStderr(line)        —— 引擎错误输出一行
 *
 * 与主线程的消息协议：
 *   -> { cmd }                     主线程发送一条协议命令
 *   <- { type: 'ready' }           WASM 模块初始化完成
 *   <- { type: 'stdout', line }    引擎标准输出一行
 *   <- { type: 'stderr', line }    引擎错误输出一行
 *   <- { type: 'error', message }  加载失败
 *   <- { type: 'exit', code }      引擎退出
 */
'use strict';

// 加载 Emscripten 生成的引擎 JS（定义全局 Rapfi 工厂）
importScripts('./rapfi-single-simd128.js');

Rapfi({
  // 兜底定位：确保 .wasm / .data 与本脚本同目录解析（兼容 GitHub Pages 子路径部署）
  locateFile: function (path) { return new URL(path, self.location).href; },
  onReceiveStdout: function (line) { postMessage({ type: 'stdout', line: line }); },
  onReceiveStderr: function (line) { postMessage({ type: 'stderr', line: line }); },
  onExit: function (code) { postMessage({ type: 'exit', code: code }); },
}).then(function (Module) {
  self._Module = Module;
  postMessage({ type: 'ready' });
}).catch(function (err) {
  postMessage({ type: 'error', message: String(err) });
});

self.onmessage = function (e) {
  const cmd = e.data && e.data.cmd;
  if (!cmd || !self._Module) return;
  // 单线程 WASM 下 sendCommand 是同步阻塞的，但这里阻塞的是 worker 线程，
  // 主线程不受影响，可持续接收 stdout 消息做实时渲染。
  self._Module.sendCommand(cmd);
};
