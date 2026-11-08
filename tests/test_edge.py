# -*- coding: utf-8 -*-
"""边界与容错回归：专门打正常流程碰不到的角落。

test_all.py 保证"顺顺利利点一遍是对的"，这个文件保证"用户乱来也不会白屏"。
每条断言都对应一个真实会发生的事故：
  · 浏览器扩展或旧版本往 localStorage 里写过奇怪的东西
  · 搜索框里粘进来正则符号 / 一段长文
  · 筛到 0 个结果、把词全标成已掌握
  · 精读翻到最后一页还想再往后翻
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp import Browser, num  # noqa: E402

HTML = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "output", "index.html")
URL = "file:///" + HTML.replace("\\", "/").replace(" ", "%20")

OK, BAD = [], []


def ck(name, cond, got=""):
    (OK if cond else BAD).append(name)
    print(("  ok  " if cond else "  FAIL") + "  " + name + ("   -> %s" % got if got else ""))


def n(b, expr):
    return num(b.ev(expr), -1)


def errs(b):
    return b.ev("window.__errs") or []


# ---------------------------------------------------------------- 脏 localStorage
# 修这个之前，known / fav 是裸 JSON.parse。任何一个键里存了非 JSON，
# 脚本第一行就抛，页面连一张卡都渲染不出来 —— 用户看到的是彻底白屏。
# (说明, 注入语句, 键, 坏数据仍在盘上的判据, 旧代码的写法——放进 try 里必须抛)
GET = "JSON.parse(localStorage.getItem('%s'))"
DIRTY = [
    ("mastered 存了半截 JSON",
     "localStorage.setItem('cet4_mastered_v1','{{{')", "cet4_mastered_v1",
     "localStorage.getItem('cet4_mastered_v1')==='{{{'",
     GET % "cet4_mastered_v1"),
    ("mastered 存成对象不是数组",
     "localStorage.setItem('cet4_mastered_v1','{\"a\":1}')", "cet4_mastered_v1",
     "!Array.isArray(%s)" % (GET % "cet4_mastered_v1"),
     "new Set(%s)" % (GET % "cet4_mastered_v1")),
    # 存成裸字符串：new Set("abc") 不抛，但会把 a / b / c 三个字母当已掌握的词，
    # 属于"不崩但数据被悄悄搞坏"，比崩溃更难发现
    ("mastered 存成裸字符串",
     "localStorage.setItem('cet4_mastered_v1','\"abc\"')", "cet4_mastered_v1",
     "typeof %s==='string'" % (GET % "cet4_mastered_v1"),
     "new Set(%s).size===3" % (GET % "cet4_mastered_v1")),
    ("fav 存了半截 JSON",
     "localStorage.setItem('cet4_fav_v1','[[[[')", "cet4_fav_v1",
     "localStorage.getItem('cet4_fav_v1')==='[[[['",
     GET % "cet4_fav_v1"),
    ("srs 存成数组",
     "localStorage.setItem('cet4_srs_v1','[1,2,3]')", "cet4_srs_v1",
     "Array.isArray(%s)" % (GET % "cet4_srs_v1"),
     "Array.isArray(%s)" % (GET % "cet4_srs_v1")),
    ("srs 里条目是数字",
     "localStorage.setItem('cet4_srs_v1','{\"abandon\":5}')", "cet4_srs_v1",
     "typeof %s['abandon']==='number'" % (GET % "cet4_srs_v1"),
     "typeof %s['abandon']==='number'" % (GET % "cet4_srs_v1")),
    ("搜索历史存成对象",
     "localStorage.setItem('cet4_search_hist_v1','{\"x\":1}')", "cet4_search_hist_v1",
     "!Array.isArray(%s)" % (GET % "cet4_search_hist_v1"),
     "%s.map(function(x){return x})" % (GET % "cet4_search_hist_v1")),
]

b = Browser(9335)
try:
    print("\n-- A. localStorage 被写坏时不白屏（本轮修的 bug） --")
    for label, stmt, key, badcheck, legacy in DIRTY:
        pre = ("try{ localStorage.clear(); %s; }catch(e){}" % stmt)
        b.open(URL, pre=pre)
        e = errs(b)
        rendered = int(n(b, "document.querySelectorAll('#list .card').length"))
        ck("%s：无 JS 报错" % label, not e, json.dumps(e, ensure_ascii=False))
        ck("%s：卡片照常渲染" % label, rendered > 0, "%d 张" % rendered)
        # 反证一：脏数据确实写进去了，上面的"没报错"不是因为注入失败
        # 注意括号：!!a==='b' 会被解析成 (!!a)==='b'，永远是 false
        ck("%s：脏数据确实还在盘上" % label,
           b.ev("(function(){try{return !!(%s)}catch(e){return false}})()" % badcheck))
        # 反证二：照旧代码的写法处理这份数据，要么直接抛，要么算出错误结果。
        # 少了这一条，这个用例就说明不了任何问题 —— 可能只是脏数据压根没生效。
        if legacy:
            r = b.ev("(function(){try{ return {t:false, v:!!(%s)}; }"
                     "catch(e){ return {t:true, v:String(e).slice(0,60)}; }})()" % legacy)
            ck("%s：旧写法处理它必出错（说明修的是真问题）" % label,
               bool(r and (r.get("t") or r.get("v"))), json.dumps(r, ensure_ascii=False))

    # ------------------------------------------------------------ 搜索框乱输
    print("\n-- B. 搜索框乱输不炸 --")
    b.open(URL)
    b.ev("localStorage.clear(); render();")
    for s in ["([", "\\", "*", "?", "a**b", "[[word]]", "x" * 300]:
        b.ev("var q=document.getElementById('q'); q.value=%s;"
             "q.dispatchEvent(new Event('input'));" % json.dumps(s))
        ck("搜索 %r 不报错" % (s[:12] + ("…" if len(s) > 12 else "")),
           not errs(b), json.dumps(errs(b), ensure_ascii=False))
    b.ev("var q=document.getElementById('q'); q.value='  ABIL  ';q.dispatchEvent(new Event('input'));")
    ck("大写 + 前后空格能搜到", int(n(b, "document.querySelectorAll('#list .card').length")) > 0,
       b.ev("document.querySelector('#list .card') && document.querySelector('#list .card').dataset.w"))
    b.ev("var q=document.getElementById('q'); q.value='';q.dispatchEvent(new Event('input'));")

    # ------------------------------------------------------------ 筛选
    print("\n-- C. 年份 / 题型 / 等级筛选 --")
    y = b.ev("document.getElementById('year').options[1].value")
    b.ev("var s=document.getElementById('year'); s.value=%s; s.dispatchEvent(new Event('change'));"
         % json.dumps(y))
    tot = int(n(b, "sorted(cards.filter(match)).length"))
    ck("按年份筛出结果", tot > 0, "%s -> %d" % (y, tot))
    ck("筛出的词确实都出自该年份",
       b.ev("sorted(cards.filter(match)).every(c=>c.years.includes(%s))" % json.dumps(y)))
    ck("年份筛选与统计条一致",
       int(n(b, "document.querySelectorAll('#list .card').length")) == min(tot, 40),
       "%d / %d" % (n(b, "document.querySelectorAll('#list .card').length"), tot))
    b.ev("var s=document.getElementById('year'); s.value=''; s.dispatchEvent(new Event('change'));")

    sv = b.ev("document.getElementById('sec').options[1].value")
    b.ev("var s=document.getElementById('sec'); s.value=%s; s.dispatchEvent(new Event('change'));"
         % json.dumps(sv))
    tot2 = int(n(b, "sorted(cards.filter(match)).length"))
    ck("按题型筛出结果", tot2 > 0, "%s -> %d" % (sv, tot2))
    ck("筛出的词确实都出自该题型",
       b.ev("sorted(cards.filter(match)).every(c=>c.sections.includes(%s))" % json.dumps(sv)))
    b.ev("var s=document.getElementById('sec'); s.value=''; s.dispatchEvent(new Event('change'));")

    print("\n-- D. 筛到 0 个结果 --")
    b.ev("var q=document.getElementById('q'); q.value='zzzznotaword';"
         "q.dispatchEvent(new Event('input'));")
    ck("0 结果时给空态提示而不是空白页",
       int(n(b, "document.querySelectorAll('#list .empty').length")) == 1
       or "没有匹配" in (b.ev("document.getElementById('list').textContent") or ""),
       (b.ev("document.getElementById('list').textContent") or "")[:60])
    ck("0 结果时不报错", not errs(b), json.dumps(errs(b), ensure_ascii=False))
    b.ev("prepPrint()")
    ck("0 结果时 prepPrint 不炸", not errs(b), json.dumps(errs(b), ensure_ascii=False))
    b.ev("postPrint()")
    b.ev("var q=document.getElementById('q'); q.value='';q.dispatchEvent(new Event('input'));")

    print("\n-- E. 把词全标成已掌握 --")
    b.ev("cards.forEach(c=>known.add(c.word)); render();")
    ck("全掌握后不崩", not errs(b), json.dumps(errs(b), ensure_ascii=False))
    b.ev("document.getElementById('hideKnown').click()")
    txt = b.ev("document.getElementById('list').textContent") or ""
    ck("全掌握 + 只看未掌握：给空态而不是卡死",
       int(n(b, "document.querySelectorAll('#list .card').length")) == 0
       and ("没有匹配" in txt or "没有单词" in txt),
       txt.strip()[:60])
    ck("空态下不报错", not errs(b), json.dumps(errs(b), ensure_ascii=False))
    b.ev("document.getElementById('hideKnown').click(); known.clear(); srs={}; render();")

    print("\n-- F. 排序 --")
    for mode, desc in [("freq", "按出现次数降序"), ("alpha", "按字母升序"), ("level", "按重要度")]:
        b.ev("var s=document.getElementById('sort'); s.value=%s;"
             "s.dispatchEvent(new Event('change'));" % json.dumps(mode))
        ck("切到%s不报错" % desc, not errs(b), json.dumps(errs(b), ensure_ascii=False))
        first = b.ev("sorted(cards.filter(match))[0].word")
        if mode == "freq":
            ck("次数降序：首条次数 >= 第二条",
               int(n(b, "sorted(cards.filter(match))[0].count"))
               >= int(n(b, "sorted(cards.filter(match))[1].count")),
               "%s / %s" % (n(b, "sorted(cards.filter(match))[0].count"),
                            n(b, "sorted(cards.filter(match))[1].count")))
        elif mode == "alpha":
            ck("字母升序：首条 <= 第二条",
               first <= b.ev("sorted(cards.filter(match))[1].word"),
               "%s / %s" % (first, b.ev("sorted(cards.filter(match))[1].word")))
    b.ev("var s=document.getElementById('sort'); s.value='level';"
         "s.dispatchEvent(new Event('change'));")

    print("\n-- G. 精读翻页边界 --")
    b.ev("document.querySelector('#viewSeg .seg-b[data-view=read]').click()")
    last = int(n(b, "PASSES.length")) - 1
    b.ev("rIdx=%d; renderPassage();" % last)
    ck("翻到最后一篇正常", int(n(b, "document.querySelectorAll('#rText .rsent').length")) > 0,
       n(b, "document.querySelectorAll('#rText .rsent').length"))
    ck("最后一篇不报错", not errs(b), json.dumps(errs(b), ensure_ascii=False))
    b.ev("rIdx=%d; renderPassage();" % (last + 50))
    ck("越界索引不抛异常（自动夹回合法范围）", not errs(b), json.dumps(errs(b), ensure_ascii=False))
    ck("越界后仍渲染出正文", int(n(b, "document.querySelectorAll('#rText .rsent').length")) > 0)
    b.ev("rIdx=0; renderPassage();")

    print("\n-- H. 数据完整性 --")
    b.ev("document.querySelector('#viewSeg .seg-b[data-view=card]').click()")
    # 多词固定搭配（rather than / at least …）本来就没有音标，卡面上 .ph 也整个不渲染。
    # 真正要保证的是：凡是单词，都得有音标。
    ck("单词型卡片全部有音标",
       int(n(b, "cards.filter(c=>!c.phonetic && !c.word.includes(' ')).length")) == 0,
       n(b, "cards.filter(c=>!c.phonetic && !c.word.includes(' ')).length"))
    ck("没有音标的只可能是多词搭配",
       b.ev("cards.filter(c=>!c.phonetic).every(c=>c.word.includes(' '))"),
       b.ev("JSON.stringify(cards.filter(c=>!c.phonetic).map(c=>c.word))"))
    ck("多词搭配卡面不渲染空音标",
       int(n(b, "document.querySelectorAll('#list .card .ph').length"))
       == int(n(b, "document.querySelectorAll('#list .card').length"))
       - int(n(b, "[...document.querySelectorAll('#list .card')]"
                ".filter(e=>e.dataset.w.includes(' ')).length")),
       "%d / %d" % (n(b, "document.querySelectorAll('#list .card .ph').length"),
                    n(b, "document.querySelectorAll('#list .card').length")))
    ck("渲染出的正文没有 [[ ]] 标记残留",
       "[[" not in (b.ev("document.getElementById('list').textContent") or ""),
       (b.ev("document.getElementById('list').textContent") or "")[:40])
    ck("每张卡都能拿到例句",
       int(n(b, "cards.filter(c=>c.examples && c.examples.length).length"))
       == int(n(b, "cards.length")),
       "%d / %d" % (n(b, "cards.filter(c=>c.examples && c.examples.length).length"),
                    n(b, "cards.length")))

    print("\n-- I. 其余开关 --")
    for cid in ["dueChip", "favChip", "hiFreq", "hideKnown"]:
        b.ev("document.getElementById('%s').click(); document.getElementById('%s').click();"
             % (cid, cid))
        ck("%s 开/关一轮不报错" % cid, not errs(b), json.dumps(errs(b), ensure_ascii=False))
    b.ev("document.getElementById('blurBtn').click(); document.getElementById('blurBtn').click();")
    ck("自测模式开关不报错", not errs(b), json.dumps(errs(b), ensure_ascii=False))
    b.ev("document.getElementById('showTrans').click();"
         "document.getElementById('showTrans').dispatchEvent(new Event('change'));")
    ck("全局译文开关不报错", not errs(b), json.dumps(errs(b), ensure_ascii=False))

    print("\n-- J. 语速设置 --")
    # 语速是个按钮，点一下换一档，不是下拉框
    r0 = b.ev("document.getElementById('rate').textContent")
    seen = [r0]
    for _ in range(3):                       # RATES 有 3 档：常速 / 慢速 / 很慢
        b.ev("document.getElementById('rate').click()")
        seen.append(b.ev("document.getElementById('rate').textContent"))
    ck("语速按钮点一圈会换档并绕回", seen[0] == seen[3] and len(set(seen[:3])) == 3,
       " -> ".join(seen))
    b.ev("document.getElementById('rate').click()")   # 停在慢速，好验证 rate 真的传下去
    b.ev("window.__said.length=0; document.querySelector('#list .card .spk').click();")
    ck("慢速档真的把 rate 传给了朗读",
       abs(float(b.ev("window.__said[0].rate")) - 0.7) < 0.01,
       b.ev("JSON.stringify(window.__said)"))
    ck("换语速不报错", not errs(b), json.dumps(errs(b), ensure_ascii=False))
    b.ev("window.__said.length=0; document.querySelector('#list .card .spk').click();")
    ck("换档后仍能发声", int(n(b, "window.__said.length")) == 1,
       b.ev("JSON.stringify(window.__said)"))
    ck("全程控制台无错误", not errs(b), json.dumps(errs(b), ensure_ascii=False))
finally:
    b.close()

print("\n=== %d 通过 / %d 失败 ===" % (len(OK), len(BAD)))
for x in BAD:
    print("  失败：" + x)
sys.exit(1 if BAD else 0)
