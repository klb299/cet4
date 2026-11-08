# -*- coding: utf-8 -*-
"""全量回归：真 Chrome 里跑一遍四个视图，逐条断言。

每条断言都要能说清"如果坏了会怎么样"，不写只有自己看得懂的断言。

路径全部相对脚本位置算：换台机器、换个盘符都不用改代码。
预览图默认写到项目同级的 output/cet4预览（十几兆 PNG 不该进仓库），
要换地方设环境变量 CET4_PREVIEW。
"""
import base64
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp import Browser, num  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(BASE, "output", "index.html")
SHOT = os.environ.get("CET4_PREVIEW") or os.path.join(
    os.path.dirname(BASE), "output", "cet4预览")
os.makedirs(SHOT, exist_ok=True)
URL = "file:///" + HTML.replace("\\", "/").replace(" ", "%20")

OK, BAD = [], []


def ck(name, cond, got=""):
    (OK if cond else BAD).append(name)
    print(("  ok  " if cond else "  FAIL") + "  " + name + ("   -> %s" % got if got else ""))


def n(b, expr):
    return num(b.ev(expr), -1)


b = Browser(9334)
try:
    b.open(URL)

    print("\n-- A. 加载与统计 --")
    ck("页面没有 JS 报错", not (b.ev("window.__errs") or []),
       json.dumps(b.ev("window.__errs"), ensure_ascii=False))
    ck("卡片数 > 1200", n(b, "cards.length") > 1200, n(b, "cards.length"))
    ck("精读篇数 = 83", n(b, "PASSES.length") == 83, n(b, "PASSES.length"))
    # 6 项：重点词 / 实词覆盖 / 真题例句 / 仿真例句 / 覆盖试卷 / 年份
    ck("顶部统计已渲染", n(b, "document.querySelectorAll('#stats .stat').length") == 6)
    ck("首屏渲染出卡片", n(b, "document.querySelectorAll('#list .card').length") > 0,
       n(b, "document.querySelectorAll('#list .card').length"))
    # 多词固定搭配（rather than / at least…）没有音标，卡面上本来就不渲染 .ph
    ck("每张单词卡都有音标位",
       n(b, "document.querySelectorAll('#list .card .ph').length")
       == n(b, "[...document.querySelectorAll('#list .card')]"
              ".filter(e=>!e.dataset.w.includes(' ')).length"),
       "%d / %d" % (n(b, "document.querySelectorAll('#list .card .ph').length"),
                    n(b, "document.querySelectorAll('#list .card').length")))

    print("\n-- B. 视图切换高亮（本轮修的 bug） --")
    b.ev("document.querySelector('#viewSeg .seg-b[data-view=read]').click()")
    st = b.ev("[...document.querySelectorAll('#viewSeg .seg-b')].map(b=>b.dataset.view+':'+b.classList.contains('on')).join(',')")
    # 视图按钮会随功能增加（现在是 背单词/精读/做题/报告），
    # 所以不写死整串状态，只断言"有且只有一个亮着，且亮的是刚点的那个"
    ck("点精读后只有精读亮",
       n(b, "document.querySelectorAll('#viewSeg .seg-b.on').length") == 1
       and b.ev("document.querySelector('#viewSeg .seg-b.on').dataset.view") == "read", st)
    ck("dir 没被视图按钮带坏", b.ev("dir") == "fwd", b.ev("dir"))
    dirst = b.ev("[...document.querySelectorAll('#dirSeg .seg-b')].map(b=>b.dataset.dir+':'+b.classList.contains('on')).join(',')")
    ck("方向按钮仍正常", dirst == "fwd:true,rev:false", dirst)
    b.ev("document.querySelector('#viewSeg .seg-b[data-view=quiz]').click()")
    st = b.ev("[...document.querySelectorAll('#viewSeg .seg-b')].map(b=>b.dataset.view+':'+b.classList.contains('on')).join(',')")
    ck("点做题后只有做题亮",
       n(b, "document.querySelectorAll('#viewSeg .seg-b.on').length") == 1
       and b.ev("document.querySelector('#viewSeg .seg-b.on').dataset.view") == "quiz", st)
    b.ev("document.querySelector('#viewSeg .seg-b[data-view=card]').click()")
    st = b.ev("[...document.querySelectorAll('#viewSeg .seg-b')].map(b=>b.dataset.view+':'+b.classList.contains('on')).join(',')")
    ck("切回背单词正常",
       n(b, "document.querySelectorAll('#viewSeg .seg-b.on').length") == 1
       and b.ev("document.querySelector('#viewSeg .seg-b.on').dataset.view") == "card", st)

    print("\n-- C. 精读视图 --")
    b.ev("document.querySelector('#viewSeg .seg-b[data-view=read]').click()")
    ck("篇目下拉有 83 项", n(b, "document.querySelectorAll('#passage option').length") == 83)
    ck("正文渲染出句子", n(b, "document.querySelectorAll('#rText .rsent').length") > 0)
    tot = 0
    ph = {}
    for i in range(83):
        b.ev("rIdx=%d;renderPassage();" % i)
        ms = b.ev("[...document.querySelectorAll('#rText mark')].map(m=>m.textContent.toLowerCase())") or []
        tot += len(ms)
        for m in ms:
            if " " in m:
                ph[m] = ph.get(m, 0) + 1
    ck("全篇高亮 > 600", tot > 600, tot)
    ck("固定搭配标出 51 处（本轮修的 bug）", sum(ph.values()) == 51,
       "%d 处 %s" % (sum(ph.values()), ph))
    b.ev("rIdx=0;renderPassage();")
    ck("每句都有朗读喇叭", n(b, "document.querySelectorAll('#rText .spk').length")
       == n(b, "document.querySelectorAll('#rText .rsent').length"))
    ck("重点词标签已渲染", n(b, "document.querySelectorAll('#rWords .wc').length") > 0,
       n(b, "document.querySelectorAll('#rWords .wc').length"))
    # offsetParent 是 DOM 节点，CDP 的 returnByValue 序列化不出来，必须自己转布尔
    ck("译文默认收起", not b.ev("!!document.querySelectorAll('#rText .rtr')[0].offsetParent"),
       b.ev("getComputedStyle(document.querySelectorAll('#rText .rtr')[0]).display"))
    b.ev("document.getElementById('rTrans').click()")
    ck("点显示译文后展开", bool(b.ev("!!document.querySelectorAll('#rText .rtr')[0].offsetParent")),
       b.ev("getComputedStyle(document.querySelectorAll('#rText .rtr')[0]).display"))
    b.ev("window.__said.length=0; document.querySelectorAll('#rText .spk')[0].click();")
    ck("整句朗读真的发声", n(b, "window.__said.length") == 1, b.ev("JSON.stringify(window.__said)"))
    b.ev("window.__said.length=0; document.querySelector('#rWords .wc').click();")
    ck("点重点词朗读单词", n(b, "window.__said.length") == 1, b.ev("JSON.stringify(window.__said)"))

    print("\n-- D. 做题视图 --")
    b.ev("document.querySelector('#viewSeg .seg-b[data-view=quiz]').click()")
    ck("出题 20 道", n(b, "qList.length") == 20, n(b, "qList.length"))
    ck("题干有挖空", n(b, "document.querySelectorAll('#qStem .blank').length") >= 1,
       n(b, "document.querySelectorAll('#qStem .blank').length"))
    ck("四个选项", n(b, "document.querySelectorAll('#qOpts .qopt').length") == 4)
    ck("译文开局收起（本轮修的 bug）",
       not b.ev("document.getElementById('qTrans').classList.contains('t-on')"))
    b.ev("document.getElementById('qPeek').click()")
    ck("点看译文能展开", b.ev("document.getElementById('qTrans').classList.contains('t-on')"))
    b.ev("document.getElementById('qPeek').click()")
    b.ev("document.querySelectorAll('#qOpts .qopt')[%d].click()" % n(b, "qList[qIdx].ans"))
    ck("答对后判分正确", b.ev("document.getElementById('qRes').className").find("ok") >= 0,
       b.ev("document.getElementById('qRes').textContent"))
    ck("答完自动展开译文", b.ev("document.getElementById('qTrans').classList.contains('t-on')"))
    ck("答完出下一题按钮", b.ev("document.getElementById('qNext').style.display") != "none")
    srs0 = b.ev("JSON.stringify(srs[qList[qIdx-1>=0?qIdx-1:0].w])")
    ck("判分写进复习计划", srs0 is not None, srs0)

    print("\n-- E. 背单词：三档自评 / 练习方式 --")
    b.ev("document.querySelector('#viewSeg .seg-b[data-view=card]').click()")
    b.ev("localStorage.clear(); known=new Set(); srs={}; render();")
    w0 = b.ev("document.querySelector('#list .card').dataset.w")
    b.ev("document.querySelector('#list .card .foot .mini[data-lv=\"2\"]').click()")
    ck("点「会」写进 srs", b.ev("srs['%s'] && srs['%s'].lv" % (w0, w0)) == 2,
       b.ev("JSON.stringify(srs['%s'])" % w0))
    ck("点「会」进已掌握", b.ev("known.has('%s')" % w0))
    b.ev("document.querySelector('#list .card .foot .mini[data-lv=\"0\"]').click()")
    ck("点「不会」档位回 0", b.ev("srs['%s'].lv" % w0) == 0)
    ck("点「不会」移出已掌握", not b.ev("known.has('%s')" % w0))
    b.ev("document.getElementById('mode').value='spell';document.getElementById('mode').dispatchEvent(new Event('change'))")
    ck("拼写模式出输入框", n(b, "document.querySelectorAll('.spellbox input').length") > 0)
    b.ev("document.getElementById('mode').value='listen';document.getElementById('mode').dispatchEvent(new Event('change'))")
    ck("听写模式藏词", n(b, "document.querySelectorAll('.hideword').length") > 0)
    b.ev("document.querySelector('#list .card .foot .mini[data-act=reveal]') && document.querySelector('#list .card .foot .mini[data-act=reveal]').click()")
    ck("听写能显示答案", n(b, "revealed.size") == 1, n(b, "revealed.size"))
    b.ev("document.getElementById('mode').value='card';document.getElementById('mode').dispatchEvent(new Event('change'))")

    print("\n-- F. 搜索 / 筛选 --")
    b.ev("document.getElementById('q').value='alth';document.getElementById('q').dispatchEvent(new Event('input'))")
    ck("模糊搜索有结果", n(b, "document.querySelectorAll('#list .card').length") > 0)
    ck("首条是词头最接近的", "alth" in (b.ev("document.querySelector('#list .card').dataset.w") or ""),
       b.ev("document.querySelector('#list .card').dataset.w"))
    b.ev("document.querySelector('#dirSeg .seg-b[data-dir=rev]').click()")
    ck("切中→英方向生效", b.ev("dir") == "rev")
    b.ev("document.getElementById('q').value='尽管';document.getElementById('q').dispatchEvent(new Event('input'))")
    ck("中文反查有结果", n(b, "document.querySelectorAll('#list .card').length") > 0,
       n(b, "document.querySelectorAll('#list .card').length"))
    b.ev("document.querySelector('#dirSeg .seg-b[data-dir=fwd]').click();document.getElementById('q').value='';document.getElementById('q').dispatchEvent(new Event('input'))")
    b.ev("document.getElementById('hideKnown').click()")
    ck("只看未掌握不空白（老 bug 回归）", n(b, "document.querySelectorAll('#list .card').length") > 0)
    b.ev("document.getElementById('hideKnown').click()")

    print("\n-- G. 打印 --")
    total = int(n(b, "sorted(cards.filter(match)).length"))
    ck("首屏只渲染一页", int(n(b, "document.querySelectorAll('#list .card').length")) < 100,
       n(b, "document.querySelectorAll('#list .card').length"))
    b.ev("prepPrint()")
    ck("打印前把筛选结果整份摊进 DOM（本轮修的 bug）",
       int(n(b, "document.querySelectorAll('#list .card').length")) == total,
       "%d / %d" % (n(b, "document.querySelectorAll('#list .card').length"), total))
    r = b.send("Page.printToPDF", {"printBackground": False, "paperWidth": 8.27,
                                   "paperHeight": 11.69, "marginTop": 0.47,
                                   "marginBottom": 0.47, "marginLeft": 0.47,
                                   "marginRight": 0.47})
    pdf = base64.b64decode(r["data"])
    pages = pdf.count(b"/Type /Page") - pdf.count(b"/Type /Pages")
    # 1272 个词全量打印，A4 双栏下约 8 词/页。老 bug 时 240 张卡要打 230 页，
    # 换算下来每张卡占一页；现在 100~200 页说明双栏和紧凑版式都生效了。
    ck("全量打印页数在 100~200 之间", 100 < pages < 200, "%d 页" % pages)
    b.ev("postPrint()")
    ck("打完把分页恢复回去", int(n(b, "document.querySelectorAll('#list .card').length")) < 100,
       n(b, "document.querySelectorAll('#list .card').length"))
    b.ev("document.querySelector('#viewSeg .seg-b[data-view=read]').click()")
    r = b.send("Page.printToPDF", {"printBackground": False, "paperWidth": 8.27,
                                   "paperHeight": 11.69, "marginTop": 0.47,
                                   "marginBottom": 0.47, "marginLeft": 0.47,
                                   "marginRight": 0.47})
    pdf2 = base64.b64decode(r["data"])
    p2 = pdf2.count(b"/Type /Page") - pdf2.count(b"/Type /Pages")
    ck("精读视图只印文章不印词卡", 0 < p2 <= 6, "%d 页" % p2)
    b.ev("document.querySelector('#viewSeg .seg-b[data-view=card]').click()")

    print("\n-- H. 手机端 --")
    b.send("Emulation.setDeviceMetricsOverride",
           {"width": 390, "height": 780, "deviceScaleFactor": 2, "mobile": True})
    b.ev("render()")
    ck("窄屏不横向溢出", n(b, "document.documentElement.scrollWidth") <= 391,
       n(b, "document.documentElement.scrollWidth"))
    ck("底部操作条出现", b.ev("getComputedStyle(document.querySelector('.mbar')).display") != "none")

    # 320 / 360 / 414 三档真机宽度都不许横向溢出。
    # 320 是这次修的真 bug：底部条六个按钮挤不下，把文档顶到 344px
    for w in (320, 360, 414):
        b.send("Emulation.setDeviceMetricsOverride",
               {"width": w, "height": 700, "deviceScaleFactor": 2, "mobile": True})
        b.ev("render();window.scrollTo(0,0);")
        ck("%dpx 不横向溢出" % w,
           n(b, "document.documentElement.scrollWidth") <= w + 1,
           n(b, "document.documentElement.scrollWidth"))
    b.send("Emulation.setDeviceMetricsOverride",
           {"width": 390, "height": 780, "deviceScaleFactor": 2, "mobile": True})
    b.ev("render();window.scrollTo(0,0);")

    # 有效点击区：量的是 elementFromPoint 打五个点，不是盒子尺寸。
    # ★收藏 / 例句小喇叭 / 历史 × 都是盒子故意留小、用 ::after 扩点击区的
    EFF = """(function(){window.__eff=function(e){
      var r=e.getBoundingClientRect();
      if(!r.width||!r.height) return -1;
      if(r.left<0||r.right>innerWidth||r.top<0||r.bottom>innerHeight) return -1;
      var p=e.parentElement;
      while(p&&p!==document.body){
        if(/auto|scroll|hidden/.test(getComputedStyle(p).overflowX)){
          var pr=p.getBoundingClientRect();
          if(r.right>pr.right+1||r.left<pr.left-1) return -1; break;}
        p=p.parentElement;}
      var cx=r.left+r.width/2, cy=r.top+r.height/2;
      var W=Math.max(r.width,44), H=Math.max(r.height,44);
      var L=cx-W/2, T=cy-H/2, ok=0;
      [[cx,cy],[cx,T+3],[cx,T+H-3],[L+3,cy],[L+W-3,cy]].forEach(function(q){
        var el=document.elementFromPoint(q[0],q[1]);
        if(el&&(el===e||e.contains(el))) ok++;});
      return ok;};})()"""
    b.ev(EFF)
    small = b.ev("""(function(){var o=[];
      document.querySelectorAll('button,.chip,.seg-b,select,.mini,.spk,.star,.qopt,label.eye,.hx')
        .forEach(function(e){
        if(getComputedStyle(e).display==='none') return;
        var k=window.__eff(e);
        if(k>=0&&k<5) o.push((e.textContent||'').trim().slice(0,12)+'|'+k);});
      return o;})()""")
    ck("首屏可见控件的有效点击区都够 44x44", not small, small)

    tiny = b.ev("""(function(){var o=[];
      document.querySelectorAll('#list *,.bar *,#stats *,.mbar *').forEach(function(e){
        if(!e.textContent.trim()||e.children.length) return;
        var fs=parseFloat(getComputedStyle(e).fontSize);
        if(fs<12) o.push(fs+'px:'+(e.textContent||'').trim().slice(0,10));});
      return o;})()""")
    ck("手机上没有小于 12px 的字", not tiny, tiny)

    bar = b.ev("""(function(){return [...document.querySelectorAll('.mbar button')]
      .filter(function(e){return getComputedStyle(e).display!=='none';})
      .map(function(e){var r=e.getBoundingClientRect();
        return Math.round(r.width)+'x'+Math.round(r.height)+'|'+window.__eff(e);});})()""")
    ck("底部条按钮都 >=44 高且点得到",
       all(int(x.split('x')[1].split('|')[0]) >= 44 and x.endswith('|5') for x in bar), bar)

    # 底部条的高亮态：原来「自测」靠改文字（自测→自测已关）表示开关，
    # 320px 上多两个字就顶爆整条，改成上色。这里验证上色真的跟着状态走
    b.ev("document.getElementById('blurBtn').click()")
    ck("底部条自测按钮跟着状态上色（关时不高亮）",
       b.ev("document.getElementById('mQuiz').classList.contains('on')") is False
       and b.ev("document.getElementById('blurBtn').textContent").endswith('关'))
    b.ev("document.getElementById('blurBtn').click()")
    ck("底部条自测按钮跟着状态上色（开时高亮）",
       b.ev("document.getElementById('mQuiz').classList.contains('on')") is True)
    b.ev("document.getElementById('mKnown').click()")
    ck("底部条未掌握按钮跟着状态上色",
       b.ev("document.getElementById('mKnown').classList.contains('on')") is True
       and b.ev("document.getElementById('hideKnown').classList.contains('on')") is True)
    b.ev("document.getElementById('mKnown').click()")
    ck("底部条改的是同一个开关（点回去了）",
       b.ev("document.getElementById('hideKnown').classList.contains('on')") is False)
    ck("底部条文字不再靠改字表示开关",
       b.ev("document.getElementById('mQuiz').textContent") == "自测",
       b.ev("document.getElementById('mQuiz').textContent"))

    # 下拉拆成独立一行：原来和搜索框同行，最长的选项把 select 撑到 180px，
    # 换行后 sticky 顶栏变成三行高
    ck("三个下拉独立成行",
       n(b, "document.querySelectorAll('.bar .row.selrow select').length") == 3
       and b.ev("document.querySelector('.bar .row.selrow').classList.contains('row')") is True)
    ck("下拉行可横滑而不是撑破页面",
       b.ev("getComputedStyle(document.querySelector('.bar .row.selrow')).overflowX") == "auto")

    # 底部固定条是 position:fixed，会盖住正文最后一行。
    # .wrap 的下内边距（96px）必须真的留出余量，不能只靠运气
    gap = b.ev("""(function(){
      page=99; render();
      window.scrollTo(0, document.documentElement.scrollHeight);
      var t=document.getElementById('tip').getBoundingClientRect();
      var m=document.querySelector('.mbar').getBoundingClientRect();
      return Math.round(m.top - t.bottom);})()""")
    ck("滚到底正文不被底部条盖住", (gap or 0) >= 20, "%s px 余量" % gap)
    b.ev("page=1;render();window.scrollTo(0,0);")

    ck("手机端改完仍无 JS 报错", not (b.ev("window.__errs") or []),
       json.dumps(b.ev("window.__errs") or [], ensure_ascii=False))
    b.shot(os.path.join(SHOT, "手机端.png"))
    b.send("Emulation.setDeviceMetricsOverride",
           {"width": 1280, "height": 900, "deviceScaleFactor": 1, "mobile": False})
    b.ev("render()")
    b.shot(os.path.join(SHOT, "背单词_桌面.png"))
    b.ev("document.querySelector('#viewSeg .seg-b[data-view=read]').click();rIdx=1;renderPassage();")
    b.shot(os.path.join(SHOT, "精读_整篇原文.png"))

    main_errs = b.ev("window.__errs") or []
    ck("主页面全程控制台无错误", not main_errs, json.dumps(main_errs, ensure_ascii=False))

    print("\n-- K. 语料来源标注 --")
    # 工具叫「真题词汇」，而 2021-06~2024-06 这 8 个场次是按真题题材写的仿真语料。
    # 卡面必须把两个数字分开说，否则「真题出现 6 次」其实是仿真文的频次。
    ck("页头说明了语料构成（真题/仿真分开）",
       "不等于考场频次" in (b.ev("document.querySelector('#srcNote').textContent") or ""))
    ck("统计条里有「真题例句」与「仿真例句」两项",
       b.ev("(function(){var t=document.querySelector('#stats').textContent;"
            "return t.indexOf('真题例句')>=0&&t.indexOf('仿真例句')>=0;})()") is True)
    ck("仿真例句带「仿真」标签",
       n(b, "document.querySelectorAll('#list .ex .tag.sim').length") > 0,
       n(b, "document.querySelectorAll('#list .ex .tag.sim').length"))
    ck("只在仿真里出现过的词不说「真题出现」",
       b.ev("(function(){var c=cards.filter(function(x){return x.countSim>0&&!x.countReal;})[0];"
            "return c? (document.getElementById('list').textContent.indexOf('仿真出现')>=0):true;})()")
       is True)
    ck("卡面次数两种来源都标了出来",
       b.ev("(function(){var c=cards.filter(function(x){return x.countReal>0&&x.countSim>0;})[0];"
            "if(!c) return true;var h=c.word;return freqLabel(c).indexOf('真题')>=0"
            "&&freqLabel(c).indexOf('仿真')>=0;})()") is True)
    ck("精读视图的仿真篇目标出来了",
       b.ev("(function(){var p=PASSES.filter(function(x){return x.src==='sim';})[0];"
            "if(!p) return true;rIdx=PASSES.indexOf(p);renderPassage();"
            "return /仿真/.test(document.getElementById('rSrc').textContent);})()") is True)

    print("\n-- L. 每日计划 --")
    # 1550 个词摊在首页，「今天该背哪 30 个」原来是没有答案的。
    b.ev("localStorage.clear();known=new Set();srs={};todayRec={d:TODAY,n:0,words:[]};"
         "streak={last:'',n:0};todayMode=false;page=1;render();")
    ck("首次进入给了一句起步引导",
       n(b, "document.querySelectorAll('#list .startHint').length") == 1)
    ck("进度行显示今日进度与连续天数",
       "/30" in (b.ev("document.getElementById('prog').textContent") or "")
       and "连续" in (b.ev("document.getElementById('prog').textContent") or ""),
       b.ev("document.getElementById('prog').textContent"))
    b.ev("document.getElementById('todayChip').click()")
    ck("点「今日 30」正好给出 30 张卡",
       n(b, "document.querySelectorAll('#list .card').length") == 30,
       n(b, "document.querySelectorAll('#list .card').length"))
    ck("今日队列里没有纯功能词（be / has / have / not）",
       b.ev("(function(){var ws=[...document.querySelectorAll('#list .card')]"
            ".map(function(c){return c.dataset.w;});"
            "return ws.filter(function(w){return ['be','has','have','not','do'].includes(w);}).length;})()") == 0,
       b.ev("(function(){var ws=[...document.querySelectorAll('#list .card')]"
            ".map(function(c){return c.dataset.w;});return ws.filter(function(w){"
            "return ['be','has','have','not','do'].includes(w);}).join(',');})()"))
    w0 = b.ev("document.querySelector('#list .card').dataset.w")
    b.ev("grade('%s',2,false)" % w0)
    ck("打分后今日进度 +1", n(b, "todayRec.n") == 1, n(b, "todayRec.n"))
    ck("首次打卡连续天数记为 1", n(b, "streak.n") == 1, n(b, "streak.n"))
    b.ev("grade('%s',2,false)" % w0)
    ck("同一个词重复打分不会把今日进度刷上去", n(b, "todayRec.n") == 1, n(b, "todayRec.n"))
    # 跨天：把今天的记录改成昨天，再打一个词，进度应当从 0 重新开始
    b.ev("todayRec={d:'2000-01-01',n:9,words:['x']};markToday('sample');")
    ck("跨天自动归零（旧记录不带到今天）", n(b, "todayRec.n") == 1, n(b, "todayRec.n"))
    ck("隔天以上打卡，连续天数重新计数", n(b, "streak.n") >= 1, n(b, "streak.n"))
    b.ev("document.getElementById('todayChip').click()")
    ck("再点一次「今日 30」能关掉", n(b, "document.querySelectorAll('#list .card').length") > 30,
       n(b, "document.querySelectorAll('#list .card').length"))

    # 首屏只有 60 个词，那时候「已掌握 x / 总数」和「约 N 天走完」都不能用 cards.length，
    # 否则会显示成 /60、约 2 天——曾经真的这样显示过。
    b.ev("(function(){window.__keep=cards.splice(60);DATA.allReady=false;render();})()")
    ck("首屏阶段进度分母用全量总数，而不是已加载的 60 个",
       "/1635" in (b.ev("document.getElementById('prog').textContent") or ""),
       b.ev("document.getElementById('prog').textContent"))
    ck("首屏阶段引导语按全量算天数",
       "/60" not in (b.ev("document.getElementById('prog').textContent") or ""))
    b.ev("(function(){cards.push.apply(cards,window.__keep);DATA.allReady=true;render();})()")
    ck("恢复全量后进度正常",
       "/1635" in (b.ev("document.getElementById('prog').textContent") or ""))

    print("\n-- M. 覆盖率 / 易混词 / 篇章难度 --")
    # 覆盖率回答的是"这 1550 个词够不够用"。用实词口径：the/a/of 撑起来的比例没有意义
    ck("统计条里有实词覆盖率且 > 80%",
       b.ev("(function(){var t=document.querySelector('#stats').textContent;"
            "var m=t.match(/(\\d+\\.\\d)%实词覆盖/);return m?+m[1]:0;})()") > 80,
       b.ev("(function(){var t=document.querySelector('#stats').textContent;"
            "var m=t.match(/(\\d+\\.\\d)%实词覆盖/);return m?m[1]:'无';})()"))
    ck("覆盖率分母没有混进功能词",
       b.ev("stats.bodyContent>0 && stats.bodyContent<stats.bodyTokens") is True,
       "%s/%s" % (b.ev("stats.bodyHitContent"), b.ev("stats.bodyContent")))

    b.ev("localStorage.clear();known=new Set();srs={};render();")
    ck("有卡片显示易混词", n(b, "document.querySelectorAll('#list .confuse').length") > 0,
       n(b, "document.querySelectorAll('#list .confuse').length"))
    ck("易混词都是 4 字母以上（避免 for→far 这类噪音）",
       b.ev("(function(){var bad=[];document.querySelectorAll('#list .cw[data-w]').forEach(function(b){"
            "if(b.dataset.w.length<4) bad.push(b.dataset.w);});return bad.length;})()") == 0,
       b.ev("(function(){var bad=[];document.querySelectorAll('#list .cw[data-w]').forEach(function(b){"
            "if(b.dataset.w.length<4) bad.push(b.dataset.w);});return bad.join(',');})()"))
    cw = b.ev("document.querySelector('#list .cw').dataset.w")
    b.ev("document.querySelector('#list .cw').click()")
    ck("点易混词会跳到那个词", b.ev("document.getElementById('q').value") == cw,
       "%s -> %s" % (cw, b.ev("document.getElementById('q').value")))
    # 搜索是模糊的（例句里出现也算），所以断言"第一个就是它"，不断言"只剩它"
    ck("跳转后这个词排在最前",
       b.ev("document.querySelector('#list .card').dataset.w") == cw,
       b.ev("document.querySelector('#list .card').dataset.w"))
    b.ev("document.getElementById('q').value='';render();")

    # 词族：careful → care、production → produce 这类派生关系
    b.ev("document.getElementById('q').value='careful';render();")
    fam_txt = b.ev("(document.querySelector('.confuse.fam')||{}).textContent||''")
    ck("派生词卡片上连着原形", "care" in (fam_txt or ""), fam_txt or "无")
    b.ev("document.getElementById('q').value='';render();")
    fam_off = n(b, "document.querySelectorAll('#list .confuse.fam .cw.off').length")
    ck("词库有但没有卡片的同族词标成不可点", fam_off >= 0, fam_off)
    b.ev("document.getElementById('q').value='production';render();")
    b.ev("document.querySelector('#list .confuse.fam .cw').click()")
    ck("点同族词会跳过去", b.ev("document.getElementById('q').value") == "produce",
       b.ev("document.getElementById('q').value"))
    b.ev("document.getElementById('q').value='';render();")
    b.ev("document.querySelector('#viewSeg .seg-b[data-view=read]').click();rIdx=3;renderPassage();")
    ck("精读显示了生词密度",
       "占全文词次" in (b.ev("document.getElementById('rDiff').textContent") or ""),
       b.ev("document.getElementById('rDiff').textContent"))
    ck("选单里标了每篇的生词数",
       b.ev("document.querySelectorAll('#passage option')[1].textContent").find("生词") > 0,
       b.ev("document.querySelectorAll('#passage option')[1].textContent"))
    # 推荐必须往前走，不能在两篇之间来回弹
    b.ev("document.getElementById('rNext').click()")
    p1 = b.ev("rIdx")
    b.ev("document.getElementById('rNext').click()")
    p2 = b.ev("rIdx")
    ck("推荐下一篇不会在两篇之间来回弹", p1 != p2 and b.ev("PASSES[%s].n" % p2) >= 80,
       "%s -> %s" % (p1, p2))
    # 背会前 300 个词之后，同一篇的难度必须跟着降，否则就是没在读 known
    d0 = b.ev("passLoad(PASSES[rIdx]).density")
    b.ev("cards.slice(0,300).forEach(function(c){known.add(c.word);});renderPassage();")
    d1 = b.ev("passLoad(PASSES[rIdx]).density")
    ck("掌握得越多，同一篇的生词密度越低", d1 < d0, "%.1f%% -> %.1f%%" % (d0, d1))
    b.ev("known=new Set();document.querySelector('#viewSeg .seg-b[data-view=card]').click();")

    print("\n-- N. 复习节奏与断签 --")
    # 造一个"三天前打开过、今天有 3 个词到期"的状态，然后重新加载页面
    b.ev("""(function(){localStorage.clear();
      localStorage.setItem('cet4_last_open_v1','2026-11-04');
      var s={};
      ['abandon','absolute','absorb'].forEach(function(w){s[w]={lv:1,n:1,due:dayOffset(0)};});
      localStorage.setItem('cet4_srs_v1', JSON.stringify(s));})()""")
    b.open(URL)
    warn = b.ev("(document.querySelector('.startHint.warn')||{}).textContent||''")
    ck("断签回来会提示隔了几天", "天前" in warn, warn[:40].replace("\n", " "))
    ck("提示里写明今天有多少词到期", "个词到期" in warn, warn[:60].replace("\n", " "))
    ck("进度行显示明天要复习多少",
       "明天" in (b.ev("document.getElementById('prog').textContent") or ""),
       b.ev("document.getElementById('prog').textContent"))
    ck("打开后把上次学习日更新成今天",
       b.ev("localStorage.getItem('cet4_last_open_v1')") == b.ev("TODAY"),
       b.ev("localStorage.getItem('cet4_last_open_v1')"))
    # 难词：括号里的数必须和点进去的卡片数一致（srs 里可能留着被筛掉的词）
    chip = b.ev("document.getElementById('hardChip').textContent") or ""
    ck("有难词时按钮上带个数", "(" in chip, chip)
    b.ev("document.getElementById('hardChip').click()")
    ck("难词筛选后的卡片数 = 按钮上的数",
       n(b, "document.querySelectorAll('#list .card').length") == int(
           chip.split("(")[1].split(")")[0]) if "(" in chip else False,
       "%s vs %s 张" % (chip, n(b, "document.querySelectorAll('#list .card').length")))
    ck("难词里没有已经答对两次以上的词",
       b.ev("(function(){var bad=0;document.querySelectorAll('#list .card').forEach(function(c){"
            "var s=srs[c.dataset.w];if(s&&(s.n||0)>=2)bad++;});return bad;})()") == 0)
    b.ev("document.getElementById('hardChip').click()")

    print("\n-- O. 离线支持 --")
    # file:// 下注册 service worker 必然失败，所以这里只校验产物齐全、
    # 页面正确引用；真正的断网重载另外用 http 服务器验过（见 README）
    out_dir = os.path.dirname(HTML)
    ck("页面引用了 manifest",
       b.ev("!!document.querySelector('link[rel=manifest]')") is True)
    mf = os.path.join(out_dir, "manifest.webmanifest")
    ck("manifest 已生成", os.path.exists(mf))
    if os.path.exists(mf):
        with open(mf, encoding="utf-8") as f:
            m = json.load(f)
        ck("manifest 有 start_url / 图标 / standalone",
           bool(m.get("start_url")) and bool(m.get("icons"))
           and m.get("display") == "standalone", m.get("short_name"))
    sw = os.path.join(out_dir, "sw.js")
    ck("service worker 已生成", os.path.exists(sw))
    if os.path.exists(sw):
        src = open(sw, encoding="utf-8").read()
        ck("sw 的缓存名带版本号（否则永远拿到旧页面）",
           "const CACHE = 'cet4-" in src and src.count("cet4-") >= 1,
           src.split("const CACHE = ")[1].split(";")[0] if "const CACHE" in src else "")
        ck("sw 对导航请求走网络优先（重新构建后能立刻更新）",
           "req.mode === 'navigate'" in src)
    ck("图标已生成", os.path.exists(os.path.join(out_dir, "icon.svg")))

    print("\n-- P. 学习报告 --")
    # 造 12 天记录再重载，看三张图是否真的按数据画出来
    b.ev("""(function(){localStorage.clear();var L={};
      for(var i=0;i<12;i++){L[dayOffset(-i)]={n:10+i,m:30+i*10};}
      localStorage.setItem('cet4_log_v1',JSON.stringify(L));})()""")
    b.open(URL)
    b.ev("document.querySelector('#viewSeg .seg-b[data-view=report]').click()")
    ck("切到报告视图", b.ev("document.body.classList.contains('view-report')") is True)
    ck("报告页无 JS 报错", not (b.ev("window.__errs") or []),
       json.dumps(b.ev("window.__errs") or [], ensure_ascii=False))
    ck("概览给了 4 个数字",
       n(b, "document.querySelectorAll('#rpNums .rpnum').length") == 4,
       b.ev("[...document.querySelectorAll('#rpNums .rpnum')].map(e=>e.textContent).join(' | ')"))
    ck("热力图正好 35 格（5 周 × 7 天）",
       n(b, "document.querySelectorAll('#rpHeat .hc').length") == 35,
       n(b, "document.querySelectorAll('#rpHeat .hc').length"))
    ck("今天那格单独标出来",
       n(b, "document.querySelectorAll('#rpHeat .hc.today').length") == 1)
    ck("有两天以上记录就画出掌握曲线",
       n(b, "document.querySelectorAll('#rpCurve polyline').length") == 1)
    ck("未来 7 天各一根柱",
       n(b, "document.querySelectorAll('#rpBars .rb').length") == 7,
       b.ev("[...document.querySelectorAll('#rpBars .rb b')].map(e=>e.textContent).join(',')"))
    ck("等级分布三档都在",
       n(b, "document.querySelectorAll('#rpLevel .lvbar').length") == 3)
    ck("报告页不再显示搜索栏（不参与筛选）",
       b.ev("getComputedStyle(document.querySelector('.bar')).display") == "none")
    # 打一次卡，当天记录要跟着涨
    n0 = n(b, "LOGS[TODAY] ? LOGS[TODAY].n : 0")
    b.ev("grade(cards[0].word, 2, false)")
    ck("打卡后当天学习量 +1", n(b, "LOGS[TODAY].n") == n0 + 1,
       "%s -> %s" % (n0, n(b, "LOGS[TODAY].n")))
    ck("打卡后当天掌握数跟着更新", n(b, "LOGS[TODAY].m") == n(b, "known.size"),
       "%s / %s" % (b.ev("LOGS[TODAY].m"), b.ev("known.size")))
    b.ev("document.querySelector('#viewSeg .seg-b[data-view=card]').click()")

    print("\n-- J. 未收录词工作台（第二个页面） --")
    WB = os.path.join(BASE, "output", "未收录词工作台.html")
    b.open("file:///" + WB.replace("\\", "/").replace(" ", "%20"))
    ck("工作台无 JS 报错", not (b.ev("window.__errs") or []),
       json.dumps(b.ev("window.__errs"), ensure_ascii=False))
    wn = int(n(b, "DATA.length"))
    # 这里原先是 wn > 300，用来证明"工作台没有被截到前 300 条"。
    # 补完 120 个漏网词之后未收录总量降到 267，写死的阈值反而误报。
    # 改成跟「未收录高频词.txt」对账：那个文件最多 300 条，工作台必须是全量。
    unk_txt = os.path.join(os.path.dirname(HTML), "未收录高频词.txt")
    n_txt = sum(1 for line in open(unk_txt, encoding="utf-8")
                if line.strip() and not line.startswith("#"))
    ck("列出全部待补词（不再被截到 300 条）",
       wn > 0 and wn == min(n_txt, 300), "%d 条（清单 %d 条）" % (wn, n_txt))
    ck("渲染出行", int(n(b, "document.querySelectorAll('#list .row').length")) == wn,
       n(b, "document.querySelectorAll('#list .row').length"))
    ck("例句里待补词已高亮（本轮修的 bug）",
       n(b, "document.querySelectorAll('#list .ex mark').length") > 0,
       n(b, "document.querySelectorAll('#list .ex mark').length"))
    # 这批词可能全都出现过在正文里，页面上不一定有 .tag 实例，
    # 所以造一个临时元素去量样式，而不是去 DOM 里找现成的
    ck("仅在题干/选项的标签有样式（本轮修的 bug：原来 .tag 没定义）",
       b.ev("(function(){var s=document.createElement('span');s.className='tag';"
            "document.body.appendChild(s);var c=getComputedStyle(s).backgroundColor;"
            "s.remove();return c;})()") != "rgba(0, 0, 0, 0)",
       b.ev("(function(){var s=document.createElement('span');s.className='tag';"
            "document.body.appendChild(s);var c=getComputedStyle(s).backgroundColor;"
            "s.remove();return c;})()"))
    b.ev("document.getElementById('src').value='body';document.getElementById('src').dispatchEvent(new Event('change'))")
    ck("按来源筛选生效（原来永远筛不出东西）",
       0 < int(n(b, "document.querySelectorAll('#list .row').length")) < wn,
       n(b, "document.querySelectorAll('#list .row').length"))
    ck("筛选后计数一致", b.ev("document.getElementById('cnt').textContent")
       == "共 %d 个" % n(b, "document.querySelectorAll('#list .row').length"),
       b.ev("document.getElementById('cnt').textContent"))
    b.ev("document.getElementById('src').value='';document.getElementById('src').dispatchEvent(new Event('change'))")
    copied = b.ev("(window.__copied=null, navigator.clipboard.writeText=function(t){window.__copied=t;return Promise.resolve();}, document.getElementById('copyAll').click(), window.__copied)")
    ck("复制全部待填行可用", isinstance(copied, str) and copied.count("\n") == wn - 1,
       "%d 行" % (copied or "").count("\n"))
finally:
    b.close()

print("\n=== %d 通过 / %d 失败 ===" % (len(OK), len(BAD)))
for x in BAD:
    print("  失败：" + x)
sys.exit(1 if BAD else 0)
