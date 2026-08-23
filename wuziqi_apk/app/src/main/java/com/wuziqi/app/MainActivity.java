package com.wuziqi.app;

import android.app.Activity;
import android.content.res.AssetManager;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import java.io.*;

public class MainActivity extends Activity {

    private static boolean nativeOk = false;
    private static String  nativeErr = null;

    static {
        try {
            System.loadLibrary("rapfi");
            nativeOk = true;
        } catch (UnsatisfiedLinkError e) {
            nativeOk = false;
            nativeErr = e.getMessage();
        }
    }

    // ---- Native JNI ----
    private static native void    setWorkDir(String path);
    private static native boolean init();
    private static native void    write(String cmd);
    private static native String  read();
    private static native String  readWinrate();
    private static native void    resetWinrate();
    private static native String  evaluate();
    private static native void    end();
    private static native boolean isRunning();

    private WebView webView;
    private String  filesPath;
    private volatile boolean renju = false;   // 是否启用连珠禁手
    private final Handler mainHandler = new Handler(Looper.getMainLooper());

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        filesPath = getFilesDir().getAbsolutePath();

        webView = new WebView(this);
        setContentView(webView);

        WebSettings ws = webView.getSettings();
        ws.setJavaScriptEnabled(true);
        ws.setAllowFileAccess(true);
        ws.setAllowContentAccess(true);
        ws.setDomStorageEnabled(true);

        webView.setWebViewClient(new WebViewClient());
        webView.setWebChromeClient(new WebChromeClient());
        webView.addJavascriptInterface(new EngineBridge(), "Engine");

        webView.setSystemUiVisibility(
            View.SYSTEM_UI_FLAG_FULLSCREEN |
            View.SYSTEM_UI_FLAG_HIDE_NAVIGATION |
            View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
        );

        if (!nativeOk) {
            showError("Native library load failed<br/>" +
                (nativeErr != null ? nativeErr : "unknown") +
                "<br/><br/>Need arm64-v8a device.");
            return;
        }

        // Extract weight files + start engine in background
        new Thread(() -> {
            try {
                copyAssets();
                setWorkDir(filesPath);
                if (!init()) {
                    showError("Engine init failed");
                    return;
                }
                // Send startup (medium difficulty defaults; UI can override)
                write("START 15");
                String r = read(); // OK
                if (r == null || r.startsWith("ERROR")) {
                    showError("Engine start failed: " + r);
                    return;
                }
                applyDifficulty(2000, 10);
                mainHandler.post(() -> webView.loadUrl("file:///android_asset/index.html"));
            } catch (Throwable t) {
                showError("Engine crash: " + t.getMessage());
            }
        }).start();
    }

    private void applyDifficulty(int timeoutMs, int maxDepth) {
        write("INFO TIMEOUT_TURN " + timeoutMs);
        write("INFO MAX_DEPTH " + maxDepth);
        write(renju ? "INFO RULE 2" : "INFO RULE 0");   // 2=连珠(禁手) 0=无禁手
        write("INFO SHOW_DETAIL 2");   // 开启实时 INFO 输出（WINRATE / DEPTH / EVAL）
    }

    private void copyAssets() {
        try {
            AssetManager am = getAssets();
            for (String fn : am.list("")) {
                if (fn.endsWith(".bin") || fn.endsWith(".lz4") || fn.endsWith(".toml")) {
                    File dst = new File(filesPath, fn);
                    if (!dst.exists()) {
                        try (InputStream in = am.open(fn);
                             OutputStream out = new FileOutputStream(dst)) {
                            byte[] buf = new byte[8192];
                            int n;
                            while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
                        }
                    }
                }
            }
        } catch (Exception e) {
            e.printStackTrace();
        }
    }

    private void showError(String msg) {
        mainHandler.post(() -> webView.loadData(
            "<h2 style='color:red;padding:20px'>" + msg + "</h2>",
            "text/html", "UTF-8"));
    }

    // ---- JS Bridge (runs on WebView thread) ----
    public class EngineBridge {

        @JavascriptInterface
        public void configure(int timeoutMs, int maxDepth) {
            if (timeoutMs < 100) timeoutMs = 100;
            if (maxDepth < 1) maxDepth = 1;
            applyDifficulty(timeoutMs, maxDepth);
        }

        @JavascriptInterface
        public void setRule(boolean r) {
            renju = r;
        }

        private volatile String lastMove = "";

        @JavascriptInterface
        public void turn(int x, int y) {
            lastMove = "";
            resetWinrate();
            final String cmd = "TURN " + x + "," + y;
            new Thread(() -> { write(cmd); lastMove = read(); }).start();
        }

        @JavascriptInterface
        public void begin() {
            lastMove = "";
            resetWinrate();
            new Thread(() -> { write("BEGIN"); lastMove = read(); }).start();
        }

        @JavascriptInterface
        public String move() {
            return lastMove == null ? "" : lastMove;
        }

        @JavascriptInterface
        public String winrate() {
            return readWinrate();
        }

        @JavascriptInterface
        public String evaluate() {
            return MainActivity.evaluate();  // 调用同名的静态 native 方法
        }

        @JavascriptInterface
        public String newGame(int timeoutMs, int maxDepth) {
            if (timeoutMs < 100) timeoutMs = 100;
            if (maxDepth < 1) maxDepth = 1;

            // Clean shutdown
            write("END");
            try { Thread.sleep(300); } catch (Exception ignored) {}
            end();

            // Re-init
            setWorkDir(filesPath);
            if (!init()) return "ERROR:init failed";
            write("START 15");
            String r = read();
            if (r == null || (!r.equals("OK") && r.startsWith("ERROR"))) {
                return "ERROR:start failed:" + r;
            }
            applyDifficulty(timeoutMs, maxDepth);
            return "OK";
        }

        @JavascriptInterface
        public String takeback(int n) {
            // Sync undo: roll back the last n plies inside the native engine
            for (int i = 0; i < n; i++) {
                write("TAKEBACK 0,0");
                String r = read();
                if (r == null || r.startsWith("ERROR")) return r;
            }
            return "OK";
        }
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        if (!nativeOk) return;
        try { write("END"); } catch (Exception ignored) {}
        try { end(); } catch (Exception ignored) {}
    }
}
