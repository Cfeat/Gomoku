/**
 * JNI wrapper — redirects Rapfi's std::cin/cout via custom streambuf.
 * Thread-safe, no dup2, no fd manipulation. Works on all Android versions.
 */
#include <jni.h>
#include <string>
#include <thread>
#include <mutex>
#include <condition_variable>
#include <iostream>
#include <unistd.h>

extern "C" int main(int argc, char* argv[]);

// ===================================================================
// Engine input buffer (Java writes, engine reads via std::cin)
// ===================================================================
class EngineInBuf : public std::streambuf {
    std::string            buf;
    std::mutex             mtx;
    std::condition_variable cv;
    bool                   done = false;
    static constexpr size_t N = 4096;
    char                   raw[N];

public:
    EngineInBuf() { setg(raw + N, raw + N, raw + N); }  // empty

    void feed(const std::string& s) {
        { std::lock_guard<std::mutex> lk(mtx); buf += s; buf += '\n'; }
        cv.notify_one();
    }

    void stop() {
        { std::lock_guard<std::mutex> lk(mtx); done = true; }
        cv.notify_one();
    }

    void clear() {
        std::lock_guard<std::mutex> lk(mtx);
        buf.clear(); done = false;
        setg(raw + N, raw + N, raw + N);
    }

protected:
    int underflow() override {
        if (gptr() < egptr()) return traits_type::to_int_type(*gptr());

        std::unique_lock<std::mutex> lk(mtx);
        cv.wait(lk, [this]{ return !buf.empty() || done; });
        if (done && buf.empty()) return traits_type::eof();

        size_t n = buf.size() < N ? buf.size() : N;
        std::copy_n(buf.data(), n, raw);
        buf.erase(0, n);
        setg(raw, raw, raw + n);
        return traits_type::to_int_type(*raw);
    }
};

// ===================================================================
// Engine output buffer (engine writes via std::cout, Java reads)
// ===================================================================
class EngineOutBuf : public std::streambuf {
    std::string            acc;
    std::mutex             mtx;
    std::condition_variable cv;
    bool                   ready = false;

public:
    void clear() {
        std::lock_guard<std::mutex> lk(mtx);
        acc.clear(); ready = false;
    }

    // Block until a full line is available, return it (without newline)
    std::string getline() {
        std::unique_lock<std::mutex> lk(mtx);
        while (true) {
            auto pos = acc.find('\n');
            if (pos != std::string::npos) {
                std::string line = acc.substr(0, pos);
                acc.erase(0, pos + 1);
                ready = acc.find('\n') != std::string::npos;
                while (!line.empty() && (line.back() == '\r' || line.back() == ' '))
                    line.pop_back();
                return line;
            }
            cv.wait(lk);
        }
    }

protected:
    int overflow(int c) override {
        if (c == traits_type::eof()) return traits_type::eof();
        bool notify = false;
        {
            std::lock_guard<std::mutex> lk(mtx);
            acc += (char)c;
            if (c == '\n') { ready = true; notify = true; }
        }
        if (notify) cv.notify_one();
        return c;
    }

    std::streamsize xsputn(const char* s, std::streamsize n) override {
        bool notify = false;
        {
            std::lock_guard<std::mutex> lk(mtx);
            acc.append(s, (size_t)n);
            if (acc.find('\n') != std::string::npos) { ready = true; notify = true; }
        }
        if (notify) cv.notify_one();
        return n;
    }
};

// ===================================================================
// Global state
// ===================================================================
static EngineInBuf   g_in;
static EngineOutBuf  g_out;
static std::streambuf* g_cin_orig  = nullptr;
static std::streambuf* g_cout_orig = nullptr;
static bool g_running = false;
static std::thread g_engine_thread;
static std::mutex g_engine_mutex;

extern "C" {

JNIEXPORT void JNICALL
Java_com_wuziqi_app_MainActivity_setWorkDir(JNIEnv* env, jclass, jstring jpath) {
    const char* s = env->GetStringUTFChars(jpath, nullptr);
    chdir(s);
    env->ReleaseStringUTFChars(jpath, s);
}

JNIEXPORT jboolean JNICALL
Java_com_wuziqi_app_MainActivity_init(JNIEnv*, jclass) {
    std::lock_guard<std::mutex> lk(g_engine_mutex);

    // Wait for previous engine thread to finish (if any)
    if (g_engine_thread.joinable()) {
        g_in.stop();
        g_engine_thread.join();
    }

    g_in.clear();
    g_out.clear();

    if (!g_cin_orig)  g_cin_orig  = std::cin.rdbuf(&g_in);
    else              std::cin.rdbuf(&g_in);
    if (!g_cout_orig) g_cout_orig = std::cout.rdbuf(&g_out);
    else              std::cout.rdbuf(&g_out);

    g_running = true;
    g_engine_thread = std::thread([]{
        char* argv[] = {(char*)"rapfi", nullptr};
        main(1, argv);
        std::cin.rdbuf(g_cin_orig);
        std::cout.rdbuf(g_cout_orig);
        g_running = false;
    });

    return JNI_TRUE;
}

JNIEXPORT void JNICALL
Java_com_wuziqi_app_MainActivity_write(JNIEnv* env, jclass, jstring jcmd) {
    const char* s = env->GetStringUTFChars(jcmd, nullptr);
    g_in.feed(s);
    env->ReleaseStringUTFChars(jcmd, s);
}

JNIEXPORT jstring JNICALL
Java_com_wuziqi_app_MainActivity_read(JNIEnv* env, jclass) {
    while (g_running) {
        std::string line = g_out.getline();
        if (line.empty()) continue;
        if (line.rfind("MESSAGE", 0) == 0 || line.rfind("INFO", 0) == 0 ||
            line.rfind("DEBUG", 0) == 0   || line.rfind("ERROR", 0) == 0)
            continue;
        return env->NewStringUTF(line.c_str());
    }
    return env->NewStringUTF("ERROR:engine stopped");
}

JNIEXPORT void JNICALL
Java_com_wuziqi_app_MainActivity_end(JNIEnv*, jclass) {
    g_in.stop();
    g_running = false;
}

JNIEXPORT jboolean JNICALL
Java_com_wuziqi_app_MainActivity_isRunning(JNIEnv*, jclass) {
    return g_running ? JNI_TRUE : JNI_FALSE;
}

} // extern "C"
