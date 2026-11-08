# -*- coding: utf-8 -*-
"""出预览图：词卡 / 精读 / 做题 / 手机端 / 小屏。

词卡与精读是整页长图，高度上万像素，缩略图里变成一根线，没人看得清，
所以另外截一张只取首屏的第一张卡。
"""
import os, sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "tests"))
from cdp import Browser

# 相对脚本位置算路径；预览图默认写到项目同级的 output/cet4预览，
# 十几兆 PNG 不进仓库，换位置用环境变量 CET4_PREVIEW
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(BASE, "output", "index.html")
SHOT = os.environ.get("CET4_PREVIEW") or os.path.join(
    os.path.dirname(BASE), "output", "cet4预览")
os.makedirs(SHOT, exist_ok=True)
URL = "file:///" + HTML.replace("\\", "/").replace(" ", "%20")

b = Browser(9336)
try:
    b.open(URL)
    b.ev("localStorage.clear(); known=new Set(); srs={}; render();")
    b.ev("document.getElementById('showTrans').checked=true;"
         "document.body.classList.add('show-t');render();")
    b.shot(os.path.join(SHOT, "01_背单词_词卡.png"))
    # 只截首屏：整页长图缩略后看不出字
    b.send("Page.captureScreenshot", {"captureBeyondViewport": False})
    import base64 as _b64
    with open(os.path.join(SHOT, "00_首屏_词卡.png"), "wb") as f:
        f.write(_b64.b64decode(b.send("Page.captureScreenshot",
                                      {"captureBeyondViewport": False})["data"]))

    b.ev("document.querySelector('#viewSeg .seg-b[data-view=read]').click();"
         "rIdx=1;renderPassage();document.getElementById('rTrans').click();")
    b.shot(os.path.join(SHOT, "02_精读_整篇带译文.png"))

    b.ev("document.querySelector('#viewSeg .seg-b[data-view=quiz]').click();")
    b.ev("document.querySelectorAll('#qOpts .qopt')[qList[qIdx].ans].click();")
    b.shot(os.path.join(SHOT, "03_做题_选词填空.png"))

    b.send("Emulation.setDeviceMetricsOverride",
           {"width": 390, "height": 780, "deviceScaleFactor": 2, "mobile": True})
    b.ev("document.querySelector('#viewSeg .seg-b[data-view=card]').click();render();")
    b.shot(os.path.join(SHOT, "04_手机端.png"))

    # 320px 小屏：验证最窄的真机宽度下不横滑、底部条装得下
    b.send("Emulation.setDeviceMetricsOverride",
           {"width": 320, "height": 660, "deviceScaleFactor": 2, "mobile": True})
    b.ev("render();window.scrollTo(0,0);")
    b.shot(os.path.join(SHOT, "05_小屏320.png"), full=False)
    print("已出图：", ", ".join(sorted(
        f for f in os.listdir(SHOT) if f.endswith(".png") and f[0].isdigit())))
finally:
    b.close()
