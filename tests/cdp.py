# -*- coding: utf-8 -*-
"""极简 CDP 客户端：起 headless Chrome，注入 speechSynthesis 桩，执行 JS 取结果。

为什么要有这个：页面上的 TTS / localStorage / 排版都是纯前端行为，
Python 侧看 index.html 源码只能看到字符串，看不出点下去到底会不会生效。
必须用真浏览器跑一遍才能算验证过。
"""
import base64
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request

import websocket

# Chrome 的位置按平台找一遍：写死一个 Windows 路径的话，Linux/macOS 上
# 连测试都起不来，CI 也就没法跑。CET4_CHROME 可以强制指定。
CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]
CHROME = os.environ.get("CET4_CHROME") or next(
    (p for p in CHROME_CANDIDATES if os.path.exists(p)), "chrome")

# 在页面脚本之前把 speechSynthesis 换掉：
# headless Chrome 不带语音包，getVoices() 一直是空数组，
# 代码会走在线兜底分支，测试里就会冒出网络请求。
STUB = """
(function(){
  var errs = [];
  window.__errs = errs;
  window.addEventListener('error', function(e){ errs.push(String(e.message)); });
  window.addEventListener('unhandledrejection', function(e){ errs.push('rej:'+e.reason); });
  var ce = console.error;
  console.error = function(){ errs.push([].slice.call(arguments).join(' ')); ce.apply(console, arguments); };
  var said = [];
  var voices = [{name:'Stub EN-US', lang:'en-US', localService:true, default:true},
                {name:'Stub EN-GB', lang:'en-GB', localService:true, default:false}];
  window.__said = said;
  function U(t){ this.text=t; this.lang=''; this.rate=1; this.pitch=1; this.voice=null; }
  window.SpeechSynthesisUtterance = U;
  /* speechSynthesis 在 Window 上是只读访问器，直接赋值在非严格模式下静默失败，
     于是代码拿到的是真对象，把假的 Utterance 喂进去直接抛 TypeError。
     必须用 defineProperty 覆盖。 */
  Object.defineProperty(window, 'speechSynthesis', {configurable: true, value: {
    speak: function(u){ said.push({t:u.text, lang:u.lang, rate:u.rate}); },
    cancel: function(){}, getVoices: function(){ return voices.slice(); },
    addEventListener: function(t, f){ if(t === 'voiceschanged') setTimeout(f, 0); },
    onvoiceschanged: null
  }});
})();
"""


class Browser:
    def __init__(self, port=9333):
        self.port = port
        self.prof = tempfile.mkdtemp(prefix="cdp_")
        self.proc = subprocess.Popen([
            CHROME, "--headless=new", "--disable-gpu", "--no-first-run",
            "--no-default-browser-check", "--disable-extensions",
            "--remote-debugging-port=%d" % port,
            # Chrome 111+ 会校验 WS 握手的 Origin，不带这个直接 403
            "--remote-allow-origins=*",
            "--user-data-dir=" + self.prof,
            "--allow-file-access-from-files", "about:blank",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.ws = None
        self._id = 0
        for _ in range(80):
            try:
                with urllib.request.urlopen("http://127.0.0.1:%d/json/version" % port,
                                            timeout=1) as r:
                    json.load(r)
                break
            except Exception:
                time.sleep(0.25)
        targets = json.load(urllib.request.urlopen(
            "http://127.0.0.1:%d/json/list" % port, timeout=5))
        page = [t for t in targets if t["type"] == "page"][0]
        # 60 秒：页面主体是 3.9MB 内联数据的单文件，打印那一步要把 1600 多张卡
        # 一次性摊进 DOM，30 秒偶尔不够，会抛 WebSocketTimeoutException 把整轮测试打断。
        self.ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=60)
        self.send("Page.enable")
        self.send("Runtime.enable")
        self.send("Log.enable")

    def send(self, method, params=None, sid=None):
        self._id += 1
        msg = {"id": self._id, "method": method, "params": params or {}}
        self.ws.send(json.dumps(msg))
        while True:
            raw = self.ws.recv()
            d = json.loads(raw)
            if d.get("id") == self._id:
                if "error" in d:
                    raise RuntimeError("%s -> %s" % (method, d["error"]))
                return d.get("result", {})

    def ev(self, expr):
        r = self.send("Runtime.evaluate", {
            "expression": expr, "returnByValue": True, "awaitPromise": True})
        if r.get("exceptionDetails"):
            raise RuntimeError("JS: " + json.dumps(
                r["exceptionDetails"].get("exception", {}).get("description", ""),
                ensure_ascii=False))
        return r.get("result", {}).get("value")

    def open(self, url, width=1280, height=900, pre=None):
        """pre：在页面脚本之前额外注入的 JS，用来造坏 localStorage 之类的脏环境。"""
        self.send("Emulation.setDeviceMetricsOverride", {
            "width": width, "height": height, "deviceScaleFactor": 1, "mobile": False})
        self.send("Page.addScriptToEvaluateOnNewDocument", {"source": STUB})
        if pre:
            # 注入脚本是累积的：不删掉的话，第二次 open 会把第一次的 pre 也跑一遍，
            # 前一个用例造的脏数据就被后来的 localStorage.clear() 洗掉了。
            r = self.send("Page.addScriptToEvaluateOnNewDocument", {"source": pre})
            pid = r.get("identifier")
        self.send("Page.navigate", {"url": url})
        # 等页面真正加载完，而不是固定 sleep 2.5 秒：
        # 学习页的数据是分两批流式下发的，固定的等待时间既可能不够（首屏 60 词之后
        # 还有 1500 多个词要 push）又拖慢每条用例。readyState === 'complete'
        # 意味着所有 <script> 都执行完了，此时 cards / PASSES 才是全量。
        for _ in range(60):
            time.sleep(0.25)
            try:
                if self.ev("document.readyState") == "complete":
                    break
            except Exception:
                pass
        time.sleep(0.4)
        self.ev("1")
        if pre and pid:
            try:
                self.send("Page.removeScriptToEvaluateOnNewDocument", {"identifier": pid})
            except Exception:
                pass

    def shot(self, path, full=True):
        r = self.send("Page.captureScreenshot", {"captureBeyondViewport": full})
        with open(path, "wb") as f:
            f.write(base64.b64decode(r["data"]))

    def close(self):
        try:
            if self.ws:
                self.ws.close()
        except Exception:
            pass
        try:
            self.proc.terminate()
            self.proc.wait(timeout=8)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass
        shutil.rmtree(self.prof, ignore_errors=True)


def num(v, default=None):
    """把 JS 返回值转成数字。注意 0 是真值判断的坑： (ev(..) or 99) 会把 0 变 99。"""
    if v is None or v is True or v is False:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default
