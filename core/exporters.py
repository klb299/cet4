# -*- coding: utf-8 -*-
"""输出层：交互式 HTML 学习页、Markdown 分类文档、Anki/Excel CSV、未收录词报告。"""
import csv
import json
import os
import re
import time
from collections import Counter, defaultdict

LEVEL_NAME = {"A": "基础高频", "B": "核心必背", "C": "进阶拓展"}


def year_key(y):
    """把 '2023年12月' 变成可比较的数字，避免 12月 排在 6月 前面。"""
    m = re.match(r"(\d{4})年(?:\s*(\d{1,2})月)?", y or "")
    if not m:
        return 0
    return int(m.group(1)) * 100 + int(m.group(2) or 0)


def _stats(cards, blocks, coverage=None):
    years = sorted({b.year for b in blocks if b.year}, key=year_key)
    levels = Counter(c.entry.level for c in cards)
    src_blocks = Counter(getattr(b, "source", "real") for b in blocks)
    # 词次按来源拆开：这是首页那句「真题原句 N 条」能不能写「真题」的依据
    src_tokens = Counter()
    for b in blocks:
        n = sum(len(re.findall(r"[A-Za-z][A-Za-z'\-]*", s.text)) for s in b.sentences)
        src_tokens[getattr(b, "source", "real")] += n
    return {
        "wordCount": len(cards),
        "exampleCount": sum(len(c.occurrences) for c in cards),
        "hitCount": sum(c.count for c in cards),
        "years": years,
        "levels": {LEVEL_NAME.get(k, k): v for k, v in levels.items()},
        "blockCount": len(blocks),
        "blockReal": src_blocks.get("real", 0),
        "blockSim": src_blocks.get("sim", 0),
        "blockImport": src_blocks.get("import", 0),
        "tokenReal": src_tokens.get("real", 0),
        "tokenSim": src_tokens.get("sim", 0),
        "tokenImport": src_tokens.get("import", 0),
        # 有多少个词真的在可核实真题里出现过 —— 比「命中 1550 个」诚实得多
        "wordReal": sum(1 for c in cards if c.count_real),
        "exampleReal": sum(1 for c in cards for o in c.occurrences
                           if getattr(o, "source", "real") != "sim"),
        "exampleSim": sum(1 for c in cards for o in c.occurrences
                          if getattr(o, "source", "real") == "sim"),
        "yearReal": sorted({y for c in cards for y in c.years_real}, key=year_key),
        "yearSim": sorted({y for c in cards for y in c.years_sim}, key=year_key),
        # 词汇覆盖率：这批判重点词能盖住正文多少实词。
        # 用"去掉功能词"的口径，因为 the/a/of 撑起来的比例没有学习意义。
        "bodyTokens": (coverage or {}).get("bodyTokens", 0),
        "bodyHit": (coverage or {}).get("bodyHit", 0),
        "bodyContent": (coverage or {}).get("bodyContent", 0),
        "bodyHitContent": (coverage or {}).get("bodyHitContent", 0),
        "coverage": round((coverage or {}).get("bodyHitContent", 0)
                          / max((coverage or {}).get("bodyContent", 1), 1) * 100, 1),
    }


POS_KEY_RE = re.compile(r"^(n|v|adj|adv|pron|prep|conj|num|art|int|aux)\.")


def _pos_key(pos):
    """取主词性做干扰项分池的键。n./v. 之类的前缀决定它是名词题还是动词题。"""
    m = POS_KEY_RE.match((pos or "").strip())
    return m.group(1) if m else "other"


def _pos_pool(cards):
    """选词填空的干扰项池：同等级同词性的词最像真的干扰项。

    某个池不足 4 个词时，前端退化到 *|词性（跨等级同词性）。
    实测 16 个池里只有 B|conj 一个不够，退化路径必须留着。
    """
    pool = defaultdict(list)
    for c in cards:
        if " " in c.word:          # 固定搭配的长度和形态都不像干扰项
            continue
        k = f"{c.entry.level}|{_pos_key(c.entry.pos)}"
        pool[k].append(c.word)
        pool[f"*|{_pos_key(c.entry.pos)}"].append(c.word)
    return dict(pool)


def build_html(cards, blocks, out_path, passages=None, stopwords=(), coverage=None):
    payload = [c.as_dict() for c in cards]
    stats = _stats(cards, blocks, coverage)

    # 数据分两段下发，让浏览器边下载边渲染。
    #
    # 为什么要拆：整页 4MB 时，手机在 30KB/s 的链路上要等 40 秒才看见第一屏
    # （GitHub Pages 在国内大致就是这个速度）。而实际首屏只需要十几张卡。
    # 浏览器解析 HTML 是流式的：把「前 200 个词」放在主脚本之前，
    # 主脚本执行完就能先渲染出一屏；剩下 1400 多个词作为后续 <script> 继续 push，
    # 下载完再补一次渲染。同样 4MB，用户 5~8 秒就能开始背第一个词。
    #
    # 不拆成独立 .js 文件是为了保住"双击 index.html 就能用"——file:// 下 fetch 会被拦，
    # 但同文档里的 <script> 一直是可执行的。
    FIRST = 60           # 首屏先给多少词：移动端一屏 15 张、桌面 40 张，60 个够撑住
    STEP = 260           # 之后每段多少词

    def seg(items, target, size):
        """把 items 切成若干段 push 语句，每段之间浏览器可以继续解析。"""
        out = []
        for i in range(0, len(items), size):
            body = ",".join(json.dumps(x, ensure_ascii=False, sort_keys=True)
                            for x in items[i:i + size])
            out.append("%s.push(%s);" % (target, body))
        return out

    head = {"cards": [], "stats": stats, "posPool": _pos_pool(cards),
            # 今日计划的补位要跳过纯功能词：按频次排序，
            # 榜首全是 be / has / have / not 这类，占掉名额没用
            "stop": sorted(stopwords or ()), "passages": []}
    data_head = json.dumps(head, ensure_ascii=False).replace("</", "<\\/")

    first = seg(payload[:FIRST], "DATA.cards", FIRST)
    rest = seg(payload[FIRST:], "DATA.cards", STEP)
    rest += seg(passages or [], "DATA.passages", 20)
    # 顺序要紧：先补索引、把 allReady 置上，再渲染。
    # 反过来（先 render 后 reindex）的话，「难词 (N)」会按首屏那 60 个词算，
    # 全量到齐后也不会更新，按钮上永远缺个数。
    rest.append("reindexCards(); DATA.allReady = true; render(); initPassagePicker();")
    data_first = "\n".join(first).replace("</", "<\\/")
    data_rest = "\n".join(rest).replace("</", "<\\/")

    tpl = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#2563eb">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="mobile-web-app-capable" content="yes">
<!-- 离线：manifest + service worker 由构建一并生成在同一目录。
     file:// 打开时注册会失败（没有 secure context），脚本里已静默跳过，
     所以本地双击 index.html 的用法不受影响。 -->
<link rel="manifest" href="manifest.webmanifest">
<link rel="apple-touch-icon" href="icon.svg">
<title>CET-4 真题词汇本 · 结合题目背单词</title>
<style>
:root{
  --bg:#f5f6f8; --panel:#ffffff; --line:#e5e7eb; --line2:#eef0f3;
  --ink:#1f2328; --ink2:#4b5563; --ink3:#8b95a3;
  --brand:#2563eb; --brand-soft:#eff4ff;
  --la:#15803d; --la-bg:#e8f6ec; --lb:#1d4ed8; --lb-bg:#e8effd; --lc:#7c3aed; --lc-bg:#f1eafd;
  --mark:#fff2b8; --shadow:0 1px 2px rgba(16,24,40,.05),0 4px 14px rgba(16,24,40,.05);
}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);overflow-x:hidden;
  font:15px/1.7 -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif;
  padding-bottom:env(safe-area-inset-bottom)}
.wrap{max-width:940px;margin:0 auto;padding:0 20px 80px}
header{background:var(--panel);border-bottom:1px solid var(--line);padding:26px 0 20px;margin-bottom:18px}
header .wrap{padding-bottom:0}
h1{margin:0 0 6px;font-size:22px;letter-spacing:.3px}
.sub{color:var(--ink2);font-size:13px}
.stats{display:flex;gap:10px;flex-wrap:wrap;margin-top:14px}
.stat{background:var(--brand-soft);border:1px solid #dbe6ff;border-radius:10px;padding:8px 12px;font-size:12px;color:#1e40af}
.stat b{font-size:16px;margin-right:4px}
.bar{position:sticky;top:0;z-index:20;background:rgba(245,246,248,.94);backdrop-filter:blur(8px);
  border-bottom:1px solid var(--line);padding:12px 0;margin-bottom:16px}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
input[type=text],select{border:1px solid var(--line);background:#fff;border-radius:8px;
  padding:7px 10px;font-size:13px;color:var(--ink);outline:none;
  font-family:inherit;appearance:none;-webkit-appearance:none}
input[type=text]{min-width:220px}
input[type=text]:focus,select:focus{border-color:var(--brand);box-shadow:0 0 0 3px rgba(37,99,235,.12)}
.chip{border:1px solid var(--line);background:#fff;border-radius:999px;padding:6px 13px;
  font-size:12.5px;cursor:pointer;color:var(--ink2);user-select:none;transition:.15s}
.chip:hover{border-color:#c7d2e8}
.chip.on{background:var(--brand);border-color:var(--brand);color:#fff}
.chip.la.on{background:var(--la);border-color:var(--la)}
.chip.lb.on{background:var(--lb);border-color:var(--lb)}
.chip.lc.on{background:var(--lc);border-color:var(--lc)}
.spacer{flex:1}
.btn{border:1px solid var(--line);background:#fff;border-radius:8px;padding:7px 12px;
  font-size:12.5px;cursor:pointer;color:var(--ink2);font-family:inherit}
.btn:hover{border-color:#c7d2e8;color:var(--ink)}
.eye{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--line);background:#fff;
  border-radius:8px;padding:6px 11px;font-size:12.5px;cursor:pointer;color:var(--ink2);user-select:none}
.eye svg{width:15px;height:15px;flex:none}
.eye.on{background:var(--brand);border-color:var(--brand);color:#fff}
.eye .ic-off{display:none}
.eye.on .ic-on{display:none}
.eye.on .ic-off{display:block}
.tr{display:none;font-size:13.5px;color:#0f766e;background:#f0fbf8;border-left:3px solid #5eead4;
  padding:5px 10px;border-radius:0 6px 6px 0;margin-top:6px}
body.show-t .tr{display:block}
.tr.t-on{display:block}
.trline{display:flex;gap:5px;align-items:flex-start}
.eye-sq{border:1px solid var(--line);background:#fff;border-radius:6px;padding:1px 7px;
  cursor:pointer;color:var(--ink3);font-size:11px;line-height:1.7;white-space:nowrap}
.eye-sq:hover{color:var(--brand);border-color:#c7d2e8}
.prog{font-size:12px;color:var(--ink2);white-space:nowrap}
.prog b{color:var(--brand)}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;
  box-shadow:var(--shadow);margin-bottom:14px;overflow:hidden}
.card.done{opacity:.55}
.hd{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;padding:16px 18px 10px}
.w{font-size:21px;font-weight:700;letter-spacing:.2px}
.pos{font-size:12px;color:var(--ink3);font-style:italic}
.lv{font-size:11px;border-radius:6px;padding:2px 7px;font-weight:600}
.lv.A{color:var(--la);background:var(--la-bg)}
.lv.B{color:var(--lb);background:var(--lb-bg)}
.lv.C{color:var(--lc);background:var(--lc-bg)}
.freq{font-size:11.5px;color:var(--ink3)}
/* 来源标签：仿真语料用的是琥珀色，不是装饰而是警告 —— 它的频次不来自考场 */
.tag.sim{background:#fef3c7;color:#92400e;border:1px solid #fde68a}
.tag.import{background:#eef0f3;color:#6b7280;border:1px solid #e2e5ea}
/* 页头那句语料构成说明。桌面上整段展开；手机上折成一行按钮，点开看完整说明。
   为什么必须收：这块在 390px 上占 97px，加上统计条 82px，页头一共 350px ——
   首屏一半没了，第一张词卡的收藏星会被固定底栏盖住。
   用 <details> 更省事，但新版 Chrome 用 content-visibility 隐藏折叠内容，
   CSS 里的 display:block 压不住，桌面上会渲染成一条空白黄条，所以改成显式按钮。 */
.srcnote{margin-top:10px;font-size:12px;color:var(--ink2);line-height:1.65;
  background:#fffbf0;border:1px solid #fde9c8;border-radius:9px;padding:8px 11px}
.srcsum{display:none;width:100%;text-align:left;background:none;border:0;padding:0;
  color:#92400e;font-weight:600;font-size:12px;font-family:inherit;cursor:pointer}
.srcsum::after{content:' ›';font-weight:400}
.srcnote.open .srcsum::after{content:' ⌄'}
.srcnote b{color:#92400e}
.srcnote a{color:var(--brand);text-decoration:none}
.exnote{color:#92400e;font-size:12px;background:#fffbf0;border-radius:6px;
  padding:5px 8px;margin-bottom:8px}
/* 首次进入的引导条：只是一句话，不要做成需要关掉的弹窗 */
.startHint{background:#eff4ff;border:1px solid #dbe6ff;border-radius:12px;
  padding:11px 14px;margin-bottom:12px;font-size:13px;line-height:1.7;color:#1e40af}
.startHint b{color:var(--brand)}
.startHint.warn{background:#fffbf0;border-color:#fde9c8;color:#92400e}
.startHint.warn b{color:#92400e}
/* 易混词：不影响背诵节奏，放在释义下面一行，点一下跳过去 */
.confuse{font-size:11.5px;color:var(--ink3);margin:0 0 6px;display:flex;
  gap:5px;flex-wrap:wrap;align-items:center}
.cw{border:1px dashed var(--line);background:#fff;border-radius:6px;padding:0 6px;
  font:inherit;font-family:inherit;color:var(--brand);cursor:pointer;line-height:1.6}
.cw:hover{border-color:var(--brand);background:var(--brand-soft)}
/* 同族词用紫色，和「易混」的蓝色区分开：易混是"别看错"，同族是"记住一串" */
.confuse.fam .cw{border-color:#e9d5ff;color:#7c3aed}
.confuse.fam .cw:hover{border-color:#c4a5f5;background:#faf5ff}
.confuse.fam .cw.off{color:var(--ink3);border-color:var(--line);cursor:default;
  background:transparent}
.confuse.fam .cw.off:hover{border-color:var(--line)}
/* 精读的难度行：一句话说清这篇现在读起来累不累 */
.rdiff{font-size:12px;color:var(--ink2);margin:0 0 10px}
.rdiff b{color:var(--ink)}
.dl{border-radius:5px;padding:1px 6px;font-size:11px;font-weight:600}
.dl.easy{background:#eef2f6;color:#6b7280}
.dl.good{background:#e8f6ec;color:#15803d}
.dl.hard{background:#fff8ed;color:#92400e}
.dl.vhard{background:#fdecec;color:#b42318}
.body{padding:0 18px 14px}
.senses{margin:0 0 8px;padding-left:20px}
.senses li{margin:2px 0}
.senses li:first-child{font-weight:600}
.note{color:var(--ink2);font-size:12.5px;background:#fafbfc;border-left:3px solid var(--line);
  padding:5px 10px;border-radius:0 6px 6px 0;margin-bottom:10px}
.ex{border-top:1px dashed var(--line2);padding:11px 0 3px}
.src{font-size:11.5px;color:var(--ink3);margin-bottom:5px;display:flex;gap:6px;flex-wrap:wrap;align-items:center}
.tag{background:#f1f3f6;border-radius:5px;padding:1px 6px;color:var(--ink2)}
.sent{margin:0 0 4px;font-size:14.5px}
mark{background:var(--mark);padding:0 2px;border-radius:3px;font-weight:600}
.ctx{font-size:12.5px;color:var(--ink3);margin:4px 0 0;padding-left:10px;border-left:2px solid var(--line2)}
.q{font-size:12.5px;color:#92400e;background:#fff8ed;border-radius:6px;padding:5px 9px;margin-top:6px}
.q b{color:#b45309;font-weight:600}
.foot{display:flex;gap:8px;align-items:center;padding:10px 18px;background:#fafbfc;border-top:1px solid var(--line2)}
.mini{border:1px solid var(--line);background:#fff;border-radius:7px;padding:5px 11px;font-size:12px;cursor:pointer;color:var(--ink2);font-family:inherit}
.mini.ok{background:var(--la);border-color:var(--la);color:#fff}
.blur{filter:blur(5px);cursor:pointer;transition:.2s;user-select:none}
.blur:hover{filter:blur(3px)}
.empty{text-align:center;color:var(--ink3);padding:40px 0;font-size:14px}
.more{display:block;margin:18px auto;padding:9px 22px;border:1px solid var(--brand);
  background:#fff;color:var(--brand);border-radius:9px;cursor:pointer;font-size:13px;font-family:inherit}
.tip{font-size:12px;color:var(--ink3);text-align:center;margin-top:8px}

/* ---------- 搜索增强：方向切换 / 历史 / 收藏 / 空状态 ---------- */
.srow{display:flex;gap:8px;align-items:center;flex:1 1 auto;min-width:0}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:8px;overflow:hidden;background:#fff;flex:none}
.seg-b{border:0;background:none;padding:7px 10px;font-size:12.5px;cursor:pointer;
  color:var(--ink2);font-family:inherit;line-height:1.2;white-space:nowrap}
.seg-b+.seg-b{border-left:1px solid var(--line)}
.seg-b.on{background:var(--brand);color:#fff}
.star{margin-left:auto;font-size:18px;line-height:1;color:#cbd5e1;cursor:pointer;
  user-select:none;padding:2px 4px;border-radius:6px}
.star:hover{color:#f59e0b}
.star.on{color:#f59e0b}
.hlab{font-size:12px;color:var(--ink3);flex:none}
.hitem{display:inline-flex;align-items:center;gap:5px;border:1px solid var(--line);background:#fff;
  border-radius:999px;padding:5px 6px 5px 11px;font-size:12.5px;color:var(--ink2);cursor:pointer;max-width:220px}
.hitem:hover{border-color:#c7d2e8}
.hdir{font-size:10.5px;color:var(--brand);background:var(--brand-soft);border-radius:4px;padding:0 4px;flex:none}
.ht{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.hx{color:var(--ink3);font-size:14px;line-height:1;padding:0 4px;border-radius:4px;flex:none}
.hx:hover{color:#dc2626;background:#fee2e2}
.hclr{padding:5px 10px;font-size:12px}
.empty .et{font-size:15px;font-weight:600;color:var(--ink);margin-bottom:8px}
.empty .ew{margin:0 auto 12px;padding-left:20px;max-width:460px;text-align:left;font-size:13px;color:var(--ink2)}
.empty .ew li{margin:3px 0}
.empty .eacts{display:flex;gap:8px;justify-content:center;flex-wrap:wrap}
.kbd{color:var(--ink3);font-size:11.5px}

/* ---------- 音标与朗读 ---------- */
/* 音标里全是 IPA 扩展字符（ˈ ˌ ə ʃ ŋ θ），必须显式指定带 IPA 的字体，
   否则会掉进中文回退字体，重音符被吃掉、符号变方框 */
.ph{font-family:"Charis SIL","Doulos SIL","Gentium Plus","Lucida Sans Unicode",
  "Segoe UI",Arial,sans-serif;font-size:13px;color:var(--ink2);
  letter-spacing:.2px;flex:none;white-space:nowrap}
.w.say{cursor:pointer}
.w.say:hover{color:var(--brand)}
.spk{border:0;background:none;padding:2px 4px;margin:0;cursor:pointer;line-height:1;
  font-size:15px;border-radius:6px;color:var(--ink3);flex:none;
  font-family:inherit;-webkit-tap-highlight-color:transparent}
.spk:hover{color:var(--brand);background:var(--brand-soft)}
.spk:active{transform:scale(.92)}
.spk.on{color:var(--brand)}
.spk.sm{font-size:12.5px;padding:0 3px;vertical-align:baseline;margin-left:2px}
.tts-off{opacity:.35;cursor:not-allowed}

/* ---------- 视图切换（背单词 / 做题） ---------- */
.vseg{display:inline-flex;border:1px solid var(--line);border-radius:9px;overflow:hidden;
  background:#fff;margin-top:10px}
.vseg .seg-b{padding:7px 14px;font-size:13px}
#quizPanel{display:none}
body.view-quiz #quizPanel{display:block}
body.view-quiz #list,body.view-quiz #more{display:none!important}
/* 做题时只藏词卡专属的筛选，译文开关和进度还留着用 */
body.view-quiz .chipline > .chip{display:none}
body.view-quiz #mode,body.view-quiz #blurBtn{display:none}
body.view-quiz .mbar .cardonly{display:none}

/* ---------- 精读模式 ---------- */
#readPanel{display:none}
body.view-read #readPanel{display:block}
body.view-read #list,body.view-read #more{display:none!important}
body.view-read .chipline{display:none}
body.view-read .mbar{display:none}
/* 学习报告：独立一屏，不参与筛选，所以顶部搜索栏整条收起 */
#reportPanel{display:none}
body.view-report #reportPanel{display:block}
body.view-report #list,body.view-report #more{display:none!important}
body.view-report .bar{display:none}
body.view-report .mbar{display:none}
/* 「共 N 个单词 · 快捷键」这行只对词卡列表有意义。
   精读 / 做题 / 报告页还留着它，会在面板上方撑出上百像素的空白，
   所以整块列表容器一起收起来，而不是只藏 #list。 */
body.view-read #listWrap,body.view-quiz #listWrap,body.view-report #listWrap{display:none}
.rwrap{max-width:820px}
.rbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:12px}
.rbar select{flex:1 1 auto;min-width:0}
.rsrc{font-size:12.5px;color:var(--ink2);margin-bottom:6px}
.rtopic{margin-top:0}
.rsent{font-size:15px;line-height:1.9;margin:0 0 2px;display:flex;gap:6px;align-items:flex-start}
.rsent .rt{flex:1 1 auto;min-width:0}
.rsent .spk{margin-top:2px}
body.rshow-t .rtr{display:block}
.rtr{display:none;font-size:13px;color:#0f766e;background:#f0fbf8;border-left:3px solid #5eead4;
  padding:3px 9px;border-radius:0 6px 6px 0;margin:0 0 8px 24px}
.rq{font-size:13px;color:#92400e;background:#fff8ed;border-radius:6px;padding:7px 10px;margin:10px 0 0}
.rq b{color:#b45309;font-weight:600}
.rch{font-size:12.5px;color:var(--ink2);margin:4px 0 0;padding-left:10px}
.rwords{margin-top:14px;padding-top:12px;border-top:1px solid var(--line2)}
.rwords .rtit{font-size:12.5px;color:var(--ink2);margin-bottom:8px}
.rwords .wl{display:flex;gap:6px;flex-wrap:wrap}
  /* 本文重点词：按等级着色，和词卡上的等级色一致 */
  .rwords .wc{border:1px solid var(--line);background:#fff;border-radius:8px;padding:5px 9px;
    font-size:13px;color:var(--ink2);cursor:pointer;user-select:none}
  .rwords .wc:hover{border-color:var(--brand);color:var(--brand)}
  .rwords .wc .p{color:var(--ink3);font-size:11.5px;margin-left:5px}
  .rwords .wc.lvA{border-color:#bbe5c8;background:var(--la-bg);color:var(--la)}
  .rwords .wc.lvB{border-color:#c3d7f5;background:var(--lb-bg);color:var(--lb)}
  .rwords .wc.lvC{border-color:#ddcdf5;background:var(--lc-bg);color:var(--lc)}
  .rwords .wc.noph .p{display:none}

/* ---------- 三档自评 ---------- */
.mini.no{background:#dc2626;border-color:#dc2626;color:#fff}
.mini.mid{background:#d97706;border-color:#d97706;color:#fff}
.foot .due{font-size:11.5px;color:var(--ink3);margin-left:auto}
.lvtag{font-size:10.5px;border-radius:4px;padding:0 4px;margin-left:5px;vertical-align:1px}
.lvtag.l0{background:#fee2e2;color:#b91c1c}
.lvtag.l1{background:#fef3c7;color:#92400e}
.lvtag.l2{background:var(--la-bg);color:var(--la)}

/* ---------- 拼写 / 听写 ---------- */
.spellbox{margin:2px 0 10px}
.spellbox input{width:100%;border:1px solid var(--line);border-radius:8px;padding:9px 11px;
  font-size:15px;font-family:inherit;outline:none;background:#fff;color:var(--ink);
  letter-spacing:1px}
.spellbox input:focus{border-color:var(--brand);box-shadow:0 0 0 3px rgba(37,99,235,.12)}
.spellbox.ok input{border-color:var(--la);background:var(--la-bg)}
.spellbox.bad input{border-color:#dc2626;background:#fef2f2}
.spellmsg{font-size:12.5px;margin-top:5px;min-height:18px}
.spellmsg.ok{color:var(--la)}
.spellmsg.bad{color:#dc2626}
.hideword{color:var(--ink3);letter-spacing:3px;font-size:15px}
.listenwrap{text-align:center;padding:6px 0 2px}
.listenwrap .big{font-size:30px;border:1px solid var(--line);background:#fff;border-radius:12px;
  padding:10px 22px;cursor:pointer;line-height:1;color:var(--ink2)}
.listenwrap .big:hover{border-color:var(--brand);color:var(--brand)}
.listenwrap .hint{font-size:12px;color:var(--ink3);margin-top:8px}

/* ---------- 做题模式 ---------- */
.qwrap{max-width:760px;margin:0 auto}
.qhead{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:10px}
.qsrc{font-size:12px;color:var(--ink3)}
.qidx{font-size:12.5px;color:var(--ink2);margin-left:auto;white-space:nowrap}
.qcard{background:var(--panel);border:1px solid var(--line);border-radius:14px;
  box-shadow:var(--shadow);padding:16px 18px}
.qstem{font-size:15.5px;line-height:1.85;margin:0 0 4px}
.blank{display:inline-block;min-width:40px;border-bottom:2px solid var(--brand);
  color:var(--brand);font-weight:700;text-align:center;letter-spacing:1px}
.qopt{display:block;width:100%;text-align:left;border:1px solid var(--line);background:#fff;
  border-radius:10px;padding:11px 13px;font-size:14px;cursor:pointer;color:var(--ink);
  font-family:inherit;margin-bottom:8px;transition:.12s}
.qopt:hover{border-color:#c7d2e8}
.qopt b{color:var(--ink3);margin-right:7px;font-weight:600}
.qopt.right{background:var(--la-bg);border-color:var(--la);color:var(--la)}
.qopt.right b{color:var(--la)}
.qopt.wrong{background:#fef2f2;border-color:#dc2626;color:#b91c1c}
.qopt.wrong b{color:#b91c1c}
.qopt[disabled]{cursor:default}
.qres{font-size:13px;margin-top:4px;min-height:20px}
.qres.ok{color:var(--la)}
.qres.bad{color:#dc2626}
.qbar{display:flex;gap:8px;align-items:center;margin-top:14px;flex-wrap:wrap}
.qbar .qprog{font-size:12.5px;color:var(--ink3);margin-left:auto}
.qhint{font-size:12.5px;color:var(--ink3);margin-top:8px}

/* ---------- 学习报告 ---------- */
.rpwrap{max-width:760px;margin:0 auto;padding-top:22px}
.rphead{font-size:18px;font-weight:700;margin-bottom:14px}
.rpnums{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:16px}
.rpnum{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px 14px}
.rpnum b{display:block;font-size:22px;line-height:1.25}
.rpnum span{font-size:12px;color:var(--ink3)}
.rpblock{background:var(--panel);border:1px solid var(--line);border-radius:12px;
  padding:14px 16px;margin-bottom:14px}
.rptit{font-size:14px;font-weight:600;margin-bottom:12px}
.rpsub{font-weight:400;font-size:12px;color:var(--ink3);margin-left:8px;display:inline-block}
.heat{display:grid;grid-template-columns:repeat(7,18px);gap:5px;justify-content:start}
.hc{display:block;width:18px;height:18px;border-radius:3px;background:#eef0f3}
.hc.l1{background:#c7ddfb}
.hc.l2{background:#93bdf7}
.hc.l3{background:#5b8def}
.hc.l4{background:#2563eb}
.hc.today{outline:1.5px solid #f59e0b;outline-offset:1px}
.heatlegend{display:flex;align-items:center;gap:5px;margin-top:9px;
  font-size:11px;color:var(--ink3)}
.heatlegend .hc{width:11px;height:11px;aspect-ratio:auto}
.rpsvg svg{display:block;width:100%;height:120px;overflow:visible}
.rpbars{display:grid;grid-template-columns:repeat(7,1fr);gap:8px;align-items:end;height:130px}
.rb{display:flex;flex-direction:column;justify-content:flex-end;align-items:center;
  height:100%;gap:4px}
.rb i{display:block;width:100%;background:#dbe7fb;border:1px solid #c7dafb;
  border-radius:4px 4px 0 0;min-height:3px}
.rb b{font-size:11px;color:var(--ink2);line-height:1}
.rb span{font-size:11px;color:var(--ink3);line-height:1}
.rplevel{display:flex;gap:12px;flex-wrap:wrap}
.lvbar{flex:1 1 130px}
.lvbar .t{display:flex;justify-content:space-between;font-size:12px;
  color:var(--ink2);margin-bottom:5px}
.lvbar .g{height:8px;border-radius:4px;background:#eef0f3;overflow:hidden}
.lvbar .g i{display:block;height:100%;border-radius:4px}
.lvbar.la .g i{background:var(--la)}
.lvbar.lb .g i{background:var(--lb)}
.lvbar.lc .g i{background:var(--lc)}
.qdone{text-align:center;padding:26px 10px}
.qdone .n{font-size:26px;font-weight:700;color:var(--brand)}

/* ---------- 打印 / 导出 PDF ----------
   纸上不能照抄屏幕版式：屏幕上每张卡带 3 条例句 + 出处 + 上文下文 + 原题，
   实测打印时卡片高 1105px，比 A4 可用高度（约 1032px）还高，
   于是 break-inside:avoid 只能一页塞一张，240 张打出 230 页，
   双栏也因为每栏装不下一张而失效。
   所以打印时只留"背单词真正需要的"：单词 + 音标 + 词性 + 等级 + 释义
   + 一条真题句 + 译文。 */
@media print{
  body{background:#fff}
  .bar,.mbar,.vseg,.spk,.star,.mini,#more,.tip,.eye-sq,.qopt,#ttsHint,header .sub,.rbar{display:none!important}
  /* 打印永远只出一个视图：精读视图印整篇文章，其余印词卡列表。
     不处理的话 body 上残留的 view-* 类会把面板和词卡一起印出来。
     注意 #list 的两条规则面向不同视图，不会同时命中，别合并成一条 */
  #quizPanel,#readPanel{display:none!important}
  body.view-read #readPanel{display:block!important}
  body.view-read #list{display:none!important}
  body.view-quiz #list{display:block!important}
  /* 出处标签、上文下文、原题、按钮行：屏幕上才需要，纸上是纯粹占地方 */
  .src,.ctx,.q,.foot{display:none!important}
  /* 只留第一条例句。用兄弟选择器而不是 :first-of-type，
     因为 .note 也是 div，:first-of-type 会认错 */
  .ex ~ .ex{display:none!important}
  .ex{border-top:0;padding:1px 0 0}
  .card{break-inside:avoid;page-break-inside:avoid;border:0;border-bottom:1px solid #ddd;
    border-radius:0;box-shadow:none;margin:0 0 6px;padding:0 0 4px}
  .wrap{max-width:none;padding:0}
  .hd{padding:6px 0 2px;gap:6px}
  .body{padding:0}
  .w{font-size:14px}
  .ph{font-size:11px}
  .senses{padding-left:16px;margin-bottom:2px}
  .sent,.senses li,.note,.tr{font-size:11px;line-height:1.45}
  .senses.blur{filter:none!important}
  .tr{display:block!important;background:none;border-left:2px solid #ccc;color:#333;
    padding:1px 6px;margin-top:2px}
  /* 精读的整篇排版：单栏更易读，逐句带译文，重点词列表在纸上多余（正文已高亮） */
  .rcard{border:0;padding:0;break-inside:avoid}
  .rsent{font-size:11.5px;line-height:1.55}
  .rsent .spk{display:none!important}
  .rtr{display:block!important;background:none;border-left:2px solid #ccc;color:#333;
    padding:1px 6px;margin:0 0 4px 18px}
  .rq{display:block!important;background:none;border:0;color:#333;font-size:11px;padding:2px 0}
  .rch{display:block!important;font-size:10.5px;color:#333;margin:0;padding:0}
  .rwords{display:none!important}
  /* 双栏：A4 纵向下每页能多塞一倍词条 */
  #list{column-count:2;column-gap:14px}
  @page{margin:12mm}
}

/* ---------- 手机端（宽度 < 680px） ----------
   两条硬规矩，审计脚本 .shots/audit_mobile.py 每次都按这两条量：
   1) 触控目标不小于 44px（iOS HIG）。能改盒子尺寸的直接改；改盒子会把排版撑坏的
      （★ 收藏、例句行内的小喇叭、历史记录里的 ×）盒子不动，用 ::after 把
      点击区向外扩，视觉大小不变。
   2) 正文一律 >= 12px。桌面端 11.5px 的角标在手机上又小又糊。 */
.mbar{display:none}
@media (max-width:680px){
  .wrap{padding:0 12px 96px}
  header{padding:16px 0 14px;margin-bottom:12px}
  h1{font-size:17px;line-height:1.4;margin-bottom:4px}
  .sub{font-size:12px;line-height:1.5}
  .stats{gap:6px;margin-top:10px}
  .stat{padding:6px 10px;font-size:12px;border-radius:8px}
  .stat b{font-size:14px;margin-right:3px}

  /* 顶部筛选：搜索框一行、下拉一行、筛选片一行，两行横滑，绝不横向溢出页面 */
  .bar{padding:8px 0;margin-bottom:10px}
  .bar .row{margin-bottom:6px!important}
  .bar .row:last-child{margin-bottom:0!important}
  .bar .row{flex-wrap:nowrap;overflow-x:auto;overflow-y:hidden;
    -webkit-overflow-scrolling:touch;scrollbar-width:none;padding-bottom:2px;
    /* 右侧渐隐，暗示这一行可以横滑 */
    -webkit-mask-image:linear-gradient(90deg,#000 88%,transparent);
    mask-image:linear-gradient(90deg,#000 88%,transparent)}
  .bar .row::-webkit-scrollbar{display:none}
  .bar .row>*{flex:none}
  /* 搜索行不横滑（一整行就一个输入框加方向切换），也不换行 */
  .bar .row:first-child{flex-wrap:nowrap;overflow:visible;margin-bottom:8px!important;
    -webkit-mask-image:none;mask-image:none}
  input[type=text]{min-width:0;width:100%;font-size:16px;padding:11px 12px;flex:1 1 100%;
    min-height:44px}  /* 16px 防 iOS 聚焦缩放 */
  /* 输入框必须能被压到 0 宽（flex-basis:0 + min-width:0）：
     否则它会坚持自己 205px 的固有宽度，320px 屏上整行顶到 332px 溢出屏幕 */
  .srow{flex:1 1 100%;min-width:0;max-width:100%}
  .srow input[type=text]{flex:1 1 0;width:auto}
  /* 进度挪到芯片那一行末尾,别单独占一行 */
  .prog{margin-left:auto;font-size:12px;color:var(--ink2)}
  select{font-size:13px;padding:11px 26px 11px 10px;min-height:44px;
    background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='10' height='6'><path d='M0 0l5 6 5-6z' fill='%238b95a3'/></svg>");
    background-repeat:no-repeat;background-position:right 9px center}
  /* 手机端不需要桌面那两个次要按钮,底部条里已经有了 */
  .bar .opt{display:none}
  .chip{padding:11px 16px;font-size:13px;min-height:44px;display:inline-flex;align-items:center}
  .btn,.eye{padding:11px 14px;font-size:12.5px;min-height:44px;display:inline-flex;
    align-items:center;justify-content:center}
  /* 底部条的「自测 / 未掌握 / 复习」用高亮表示开关，原来是改文字
     （自测→自测已关），320px 屏上多两个字整条就顶爆了 */
  .btn.on{background:var(--brand);border-color:var(--brand);color:#fff}

  /* 搜索增强：搜索框与方向切换同一行，历史条目触控目标 >=44px */
  .seg-b{padding:11px 13px;min-height:44px;display:inline-flex;align-items:center;font-size:13px}
  .hitem{padding:9px 6px 9px 12px;min-height:44px;font-size:13px;max-width:none}
  /* × 只有 15px 见方，盒子撑大会把胶囊撑变形，用 ::after 扩点击区到 44px */
  .hx{padding:2px 7px;font-size:15px;position:relative;
    display:inline-flex;align-items:center;justify-content:center}
  .hx::after{content:'';position:absolute;inset:-11px -7px}
  .hdir{font-size:12px}
  .hclr{min-height:44px;padding:11px 14px}
  .empty .ew{font-size:12.5px}

  /* 音标与朗读：卡片头的大喇叭直接给 40px；例句里的小喇叭是行内的，
     撑到 44 会把行距顶开，改用 ::after 扩点击区 */
  .spk{padding:6px 8px;font-size:17px;min-height:40px;min-width:40px;
    display:inline-flex;align-items:center;justify-content:center}
  .spk.sm{font-size:14px;min-height:32px;min-width:32px;padding:0 6px;
    vertical-align:middle;position:relative}
  .spk.sm::after{content:'';position:absolute;inset:-6px}
  .ph{font-size:12.5px}

  /* 练习方式与做题：选项按钮和输入框都要够大，输入框 16px 防 iOS 聚焦缩放 */
  .vseg{margin-top:8px;width:100%}
  .vseg .seg-b{flex:1;justify-content:center;min-height:46px;font-size:14px}
  .qcard{padding:14px;border-radius:12px}
  .qstem{font-size:15px;line-height:1.8}
  .qopt{padding:13px 14px;font-size:14.5px;min-height:48px}
  .qbar .btn{flex:1;justify-content:center;min-height:46px}
  .spellbox input{font-size:16px;padding:12px 12px;min-height:46px}
  .listenwrap .big{font-size:26px;padding:12px 26px;min-height:56px}
  .foot .mini{flex:1 1 auto;text-align:center;justify-content:center}
  .foot .due{width:100%;margin-left:0;font-size:12px}

  .card{border-radius:12px;margin-bottom:10px}
  .hd{padding:13px 14px 8px;gap:7px}
  /* 出现次数现在可能长到「真题 18 次 · 仿真 177 次」，会挤到第二行。
     让它固定独占一行（order 排到最后），★ 才能留在第一行右侧——
     否则 ★ 会被挤到第二行，在手机首屏正好落到固定底栏下面，点不到。 */
  .hd .freq{flex:1 1 100%;order:9;margin-top:1px}
  /* 页头在手机上要压扁：来源说明折起来、统计条改成单行横滑，
     否则 350px 的页头会把第一张词卡顶到固定底栏后面 */
  .srcsum{display:flex;align-items:center;min-height:44px}
  .srcnote:not(.open) .body{display:none}
  .stats{flex-wrap:nowrap;overflow-x:auto;padding-bottom:2px}
  .stat{flex:0 0 auto}
  .rpnums{grid-template-columns:repeat(2,1fr)}
  .rpbars{height:118px}
  /* 易混词按钮也是可点控件，手机上必须够 44 高 */
  .confuse{font-size:12px;gap:6px}
  .cw{min-height:44px;padding:6px 12px;display:inline-flex;align-items:center;font-size:12px}
  .w{font-size:19px}
  .body{padding:0 14px 12px}
  .senses{padding-left:18px;margin-bottom:7px}
  .sent{font-size:15px;line-height:1.65}   /* 正文略大，手机上更好读 */
  .ctx{font-size:12px}
  .q{font-size:12px;line-height:1.6}
  .tr{font-size:13px}
  /* 桌面端这些角标是 10.5~11.5px，手机上提到 12px */
  .tag,.lv,.lvtag,.src,.freq,.kbd{font-size:12px}
  .lvtag{padding:0 5px}
  .rwords .wc .p{font-size:12px}
  .rwords .wc{padding:9px 12px;min-height:44px;display:inline-flex;align-items:center}
  .mini{padding:11px 14px;font-size:12.5px;min-height:44px;display:inline-flex;
    align-items:center;justify-content:center}
  .eye-sq{padding:10px 12px;font-size:12px;min-height:44px;display:inline-flex;align-items:center}
  .more{min-height:46px;padding:12px 22px;font-size:13.5px}
  .foot{padding:10px 14px;gap:7px;flex-wrap:wrap}
  .foot .freq{width:100%}

  /* ★ 收藏：图标实测只有 23x22，直接撑到 44 会把卡片头部顶高一大截，
     所以盒子不动，用 ::after 把点击区向四周各扩 11px（实际约 45x44） */
  .star{position:relative;padding:2px 4px}
  .star::after{content:'';position:absolute;inset:-11px}

  /* 卡片操作按钮固定在底部，拇指可达。按钮要在一屏内放下，不能横滚 */
  .mbar{display:block;position:fixed;left:0;right:0;bottom:0;z-index:30;
    background:rgba(255,255,255,.97);backdrop-filter:blur(10px);
    border-top:1px solid var(--line);
    padding:6px 8px calc(6px + env(safe-area-inset-bottom))}
  .mbar .row{gap:6px;flex-wrap:nowrap;overflow:visible;justify-content:space-between}
  .mbar .row>*{flex:0 1 auto;min-width:0}
  /* 320px 屏上内容区只有 304px。留着「更多」的话六个按钮每个只有 42px 宽，
     不够手指点；手机上本来就有滚到底自动加载下一页（见脚本末尾的
     IntersectionObserver），列表里那个「加载更多」按钮也还在，所以这里去掉。 */
  #mMore{display:none!important}
  .mbar .btn{padding:12px 10px;font-size:12px;min-height:44px;white-space:nowrap;
    overflow:hidden;text-overflow:ellipsis}
  .mbar .mcount{display:none}
}
@media (max-width:380px){
  h1{font-size:16px}
  .stat{padding:5px 8px}
  .wrap{padding:0 10px 96px}
  .card{border-radius:10px}
  .hd{padding:12px 12px 8px}
  .body{padding:0 12px 12px}
}
@media (prefers-color-scheme:dark){
  /* 手机夜间模式：只调底色与文字，保持红涨绿跌等语义色不变 */
  :root{
    --bg:#15171a; --panel:#1d2024; --line:#2c3035; --line2:#25282c;
    --ink:#e8eaed; --ink2:#a8afb8; --ink3:#7d848d;
    --brand:#5b8def; --brand-soft:#1e2836; --mark:#5a4a17;
    --la-bg:#16301f; --lb-bg:#182338; --lc-bg:#261a3a;
  }
  .stat{background:#1e2836;border-color:#2a3a55;color:#9dbaf5}
  .srcnote{background:#2a2113;border-color:#4a3a1a;color:#d8c9a8}
  .srcnote b{color:#f0b354}
  /* 报告：热力图与柱状图在暗色下要重上一层色，否则浅蓝块会刺眼 */
  .hc{background:#25282c}
  .hc.l1{background:#1e3a5f}
  .hc.l2{background:#2a5c96}
  .hc.l3{background:#3b7dd8}
  .hc.l4{background:#5b8def}
  .rb i{background:#1e2836;border-color:#2a3a55}
  .lvbar .g{background:#25282c}
  .tag.sim{background:#3a2f13;color:#e8c07a;border-color:#5a4620}
  .tag.import{background:#25282c;color:#9aa3ae;border-color:#333940}
  .cw{background:#22262b;border-color:#3a3f45}
  .dl.easy{background:#25282c;color:#9aa3ae}
  .dl.good{background:#12301f;color:#7fd4a0}
  .dl.hard{background:#3a2f13;color:#e8c07a}
  .dl.vhard{background:#3a1c1c;color:#f0a0a0}
  .bar{background:rgba(21,23,26,.94)}
  .tag{background:#25282c}
  .note{background:#1a1d21}
  .q{background:#2a2113;color:#e8c07a}
  .q b{color:#f0b354}
  .tr{background:#132723;color:#7fd4c4;border-left-color:#2d6b5e}
  .foot{background:#191c20}
  .btn,.chip,.eye,.mini,.eye-sq,input[type=text],select,.more{background:#22262b;color:var(--ink2)}
  .eye.on,.chip.on,.mini.ok{color:#fff}
  .seg,.hitem{background:#22262b}
  .seg-b,.hitem{color:var(--ink2)}
  .seg-b.on{color:#fff}
  .seg-b+.seg-b{border-left-color:var(--line)}
  .hdir{background:#1e2836;color:#9dbaf5}
  .star{color:#4a5158}
  .star.on,.star:hover{color:#f59e0b}
  .mbar{background:rgba(29,32,36,.96)}
  /* 精读 / 做题 / 拼写 / 听写 在暗色下的底色 */
  .vseg,.qopt,.spellbox input,.listenwrap .big,.rwords .wc{background:#22262b}
  .qcard{background:var(--panel)}
  .qopt{color:var(--ink)}
  .qopt.right{background:var(--la-bg);border-color:var(--la)}
  .qopt.wrong{background:#3a1c1c;border-color:#a33}
  .spellbox.bad input{background:#3a1c1c}
  .spellbox.ok input{background:var(--la-bg)}
  .lvtag.l0{background:#3a1c1c;color:#f0a0a0}
  .lvtag.l1{background:#3a2f13;color:#e8c07a}
  .lvtag.l2{background:var(--la-bg);color:#7fd4a0}
  .blank{color:#9dbaf5;border-bottom-color:#9dbaf5}
  .rq{background:#2a2113;color:#e8c07a}
  .rq b{color:#f0b354}
  .rtr{background:#132723;color:#7fd4c4;border-left-color:#2d6b5e}
}
</style>
</head>
<body>
<header><div class="wrap">
  <h1>CET-4 历年真题重点词 · 结合题目背单词</h1>
  <div class="sub">每个词配真题原句（来源逐条标注）、中文译文与题目情境；按年份与题型归类；释义默认隐藏，点击自测</div>
  <div class="vseg" id="viewSeg">
    <button class="seg-b on" data-view="card" title="背单词：词卡 / 拼写 / 听写">背单词</button>
    <button class="seg-b" data-view="read" title="整篇精读：读真题原文，重点词高亮">精读</button>
    <button class="seg-b" data-view="quiz" title="做题：真题句子挖空选词，即时判分">做题</button>
    <button class="seg-b" data-view="report" title="学习报告：近 5 周热力图、掌握曲线、未来复习量">报告</button>
  </div>
  <div class="stats" id="stats"></div>
  <div class="srcnote" id="srcNote"></div>
</div></header>

<div class="bar"><div class="wrap">
  <div class="row" style="margin-bottom:8px">
    <div class="srow">
      <input type="text" id="q" placeholder="搜索单词 / 释义 / 真题句子…" autocomplete="off"
             autocorrect="off" autocapitalize="off" spellcheck="false" enterkeyhint="search">
      <div class="seg" id="dirSeg">
        <button class="seg-b on" data-dir="fwd" title="正向：输入英文查单词、释义、真题句（快捷键 Alt+R）">英→中</button>
        <button class="seg-b" data-dir="rev" title="反向：输入中文反查英文单词（快捷键 Alt+R）">中→英</button>
      </div>
    </div>
  </div>
  <!-- 下拉单独成行：原来它们和搜索框挤在同一行，手机上「按重要度（基础→进阶）」
       这个最长的选项把 select 撑到 180px，三个下拉换行后 sticky 顶栏变成三行高。
       拆出来后这一行横滑，顶栏高度稳定。 -->
  <div class="row selrow">
    <select id="year"><option value="">全部年份</option></select>
    <select id="sec"><option value="">全部题型</option></select>
    <select id="sort">
      <option value="level">按重要度（基础→进阶）</option>
      <option value="freq">按真题出现次数</option>
      <option value="alpha">按字母顺序</option>
    </select>
  </div>
  <div class="row hist" id="histRow" style="display:none"></div>
  <div class="row chipline">
    <select id="mode" title="背单词的出题方式：看卡 / 拼写 / 听写">
      <option value="card">看卡</option>
      <option value="spell">拼写默写</option>
      <option value="listen">听力听写</option>
    </select>
    <span class="chip" id="dueChip" title="今天该复习的词（快捷键 Alt+D）">今日复习</span>
    <span class="chip" id="todayChip" title="今日计划：先清到期复习的词，再用没学过的词补到 30 个">今日 30</span>
    <span class="chip la on" data-lv="A">基础高频</span>
    <span class="chip lb on" data-lv="B">核心必背</span>
    <span class="chip lc on" data-lv="C">进阶拓展</span>
    <span class="chip" id="hideKnown">只看未掌握</span>
    <span class="chip" id="favChip" title="只看收藏的词（快捷键 Alt+F）">★ 收藏</span>
    <span class="chip" id="hiFreq" title="只看真题出现 2 次以上的词，把只出现过一次的长尾词往下放">只看高频</span>
    <span class="chip" id="hardChip" title="总记不住的词：答对不到 2 次，且当前仍是「不会 / 模糊」">难词</span>
    <span class="prog" id="prog"></span>
    <label class="eye" id="eyeBtn">
      <input type="checkbox" id="showTrans" style="display:none">
      <svg class="ic-on" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7-11-7-11-7z"/><circle cx="12" cy="12" r="3"/></svg>
      <svg class="ic-off" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M17.94 17.94A10.07 10.07 0 0112 20c-7 0-11-8-11-8a18.45 18.45 0 015.06-5.94M9.9 4.24A9.12 9.12 0 0112 4c7 0 11 8 11 8a18.5 18.5 0 01-2.16 3.19m-6.72-1.07a3 3 0 11-4.24-4.24"/>
        <line x1="1" y1="1" x2="23" y2="23"/></svg>
      <span id="eyeTxt">显示译文</span>
    </label>
    <button class="btn" id="rate" title="朗读语速，点一下换档（快捷键 Alt+1）">语速：常速</button>
    <button class="btn" id="blurBtn" title="打开后释义打码，点击才显示">自测模式：开</button>
    <button class="btn opt" id="print"
      title="打印当前筛选出的全部单词（不只是屏幕上这几十张）；想少印点就先用等级 / 只看高频筛一遍">打印 / PDF</button>
    <button class="btn opt" id="export">导出当前为 Anki CSV</button>
    <button class="btn opt" id="reset">清空学习记录</button>
  </div>
</div></div>

<div class="wrap" id="listWrap">
  <div id="list"></div>
  <button class="more" id="more" style="display:none">加载更多</button>
  <div class="tip" id="tip"></div>
  <div class="tip" id="ttsHint"></div>
</div>

<!-- 精读模式：整篇真题原文，重点词高亮 -->
<div id="readPanel"><div class="wrap rwrap">
  <div class="rbar">
    <select id="passage" title="选一篇真题材料"></select>
    <button class="btn" id="rNext" title="按你当前的掌握情况，从生词最少的篇目开始逐个往上走">推荐下一篇</button>
    <button class="btn" id="rTrans">显示译文</button>
  </div>
  <div class="qcard rcard">
    <div class="src rsrc" id="rSrc"></div>
    <div class="rdiff" id="rDiff"></div>
    <div class="q rtopic" id="rTopic"></div>
    <div id="rText"></div>
    <div id="rQs"></div>
    <div class="rwords" id="rWords"></div>
  </div>
  <div class="qhint">原文里加亮的是词库命中的重点词，点句子旁的喇叭可整句朗读。
    「本文重点词」是可以直接点开背的——先读一遍原文再背这些词，比孤立背词表记得牢。</div>
</div></div>

<!-- 做题模式：真题句子挖空选词 -->
<div id="quizPanel"><div class="wrap qwrap">
  <div class="qhead">
    <span class="qsrc" id="qSrc"></span>
    <span class="qidx" id="qIdx"></span>
  </div>
  <div class="qcard">
    <p class="qstem" id="qStem"></p>
    <div class="tr" id="qTrans"></div>
    <div id="qOpts"></div>
    <div class="qres" id="qRes"></div>
    <div class="qbar">
      <button class="btn" id="qPeek" title="实在想不出来可以先看译文，不影响判分">看译文</button>
      <button class="btn" id="qNext" style="display:none">下一题</button>
      <button class="btn" id="qRebuild" style="display:none">换一批</button>
      <span class="qprog" id="qProg"></span>
    </div>
  </div>
  <div class="qhint">从当前筛选出的词里出题，只挑词形与原形一致且带译文的句子。
    选错的那道会自动记成「不会」，进今日复习。</div>
</div></div>

<!-- 学习报告：热力图 / 掌握曲线 / 未来复习量 -->
<div id="reportPanel"><div class="wrap rpwrap">
  <div class="rphead">学习报告</div>
  <div class="rpnums" id="rpNums"></div>

  <div class="rpblock">
    <div class="rptit">近 5 周学习量<span class="rpsub" id="rpHeatSub"></span></div>
    <div class="heat" id="rpHeat"></div>
    <div class="heatlegend"><span>少</span>
      <i class="hc l0"></i><i class="hc l1"></i><i class="hc l2"></i><i class="hc l3"></i><i class="hc l4"></i>
      <span>多</span></div>
  </div>

  <div class="rpblock">
    <div class="rptit">掌握曲线<span class="rpsub">每天结束时的已掌握词数</span></div>
    <div class="rpsvg" id="rpCurve"></div>
  </div>

  <div class="rpblock">
    <div class="rptit">未来 7 天要复习<span class="rpsub">提前看到高峰，别让某一天堆爆</span></div>
    <div class="rpbars" id="rpBars"></div>
  </div>

  <div class="rpblock">
    <div class="rptit">等级分布<span class="rpsub">按你当前掌握的进度</span></div>
    <div class="rplevel" id="rpLevel"></div>
  </div>
  <div class="qhint">报告只读 localStorage 里的学习记录，不上传任何数据。
    换设备或清空记录后，历史就没了——想留档可以用浏览器导出网页。</div>
</div></div>

<!-- 手机端：底部固定操作条 -->
<div class="mbar"><div class="row">
  <button class="btn cardonly" id="mDue" title="今天该复习的词">复习</button>
  <button class="btn cardonly" id="mQuiz" title="自测模式">自测</button>
  <button class="btn cardonly" id="mKnown" title="只看未掌握">未掌握</button>
  <button class="btn" id="mMore" style="display:none" title="加载更多">更多</button>
  <button class="btn" id="mExport" title="导出为 Anki CSV">导出</button>
  <button class="btn" id="mReset" title="清空学习记录（三档自评 + 复习计划）">重置</button>
</div></div>

<!-- 首屏数据：前 200 个词单独一段，主脚本执行完就能出第一屏 -->
<script>
const DATA = __DATA_HEAD__;
</script>
<script>
__DATA_FIRST__
</script>

<script>
const cards = DATA.cards, stats = DATA.stats, POSPOOL = DATA.posPool || {};
const STOP = new Set(DATA.stop || []);
/* 卡面出现的词。srs 里可能留着已经被 --levels / --min-count 筛掉的词，
   计数前先过一次这个集合，否则「难词 (3)」点进去只有 2 张卡。
   数据是分两批下发的：首屏只有前 200 词，后 1400 多个词到齐后要重建一次，
   否则难词计数会少一大截。 */
const CARDW = new Set();
function reindexCards(){
  CARDW.clear();
  for(const c of cards) CARDW.add(c.word);
}
reindexCards();
const KEY = 'cet4_mastered_v1', HKEY = 'cet4_search_hist_v1', FKEY = 'cet4_fav_v1';
/* localStorage 是用户可随意改的，浏览器扩展和旧版本也可能往里写过别的东西。
   之前只有 hist 包了 try，known / fav 是裸 JSON.parse —— 一旦里面存的不是合法
   JSON（或者是个对象而不是数组，new Set(obj) 同样抛错），脚本在第一行就炸，
   整页白屏，一个词都出不来。现在统一走 loadSet，坏数据直接当空处理。 */
function loadSet(k){
  try {
    const v = JSON.parse(localStorage.getItem(k) || '[]');
    return new Set(Array.isArray(v) ? v : []);
  } catch (e) { return new Set(); }
}
let known = loadSet(KEY);
let fav = loadSet(FKEY);
let hist = [];
try { hist = JSON.parse(localStorage.getItem(HKEY) || '[]'); } catch (e) { hist = []; }
if (!Array.isArray(hist)) hist = [];
let quiz = true, hideKnown = false, onlyFav = false, dir = 'fwd', page = 1;
let mode = 'card', onlyDue = false, onlyHiFreq = false, onlyHard = false, view = 'card';
/* 手机一屏装不下 40 张卡，首屏少给一点，滚动加载更快 */
const isNarrow = () => window.matchMedia('(max-width:680px)').matches;
const perPage = () => isNarrow() ? 15 : 40;
const kwNow = () => document.getElementById('q').value.trim().toLowerCase();

/* 顶部统计 */
document.getElementById('stats').innerHTML = [
  ['重点词', stats.wordCount],
  ['实词覆盖', stats.coverage ? stats.coverage + '%' : '—'],
  ['真题例句', stats.exampleReal],
  ['仿真例句', stats.exampleSim], ['覆盖试卷', stats.blockCount],
  ['年份', stats.years.length ? stats.years[0].slice(0,5)+'—'+stats.years[stats.years.length-1].slice(0,5) : '—']
].map(([k,v])=>`<span class="stat"><b>${v}</b>${k}</span>`).join('');

/* 语料构成说明。这段文字是硬性的诚实要求：
   8 个场次（2021-06 ~ 2024-06）是按真题题材人工撰写的仿真语料，
   占全部词次的绝大多数。不写清楚，卡面上的「真题出现 N 次」就是误导。 */
(function(){
  const el = document.getElementById('srcNote');
  if(!el) return;
  const tr = stats.tokenReal||0, ts = stats.tokenSim||0, tot = tr+ts || 1;
  if(!stats.blockSim && !stats.blockImport){
    el.innerHTML = `<div class="body">语料全部来自可核实的真题片段`
      + `（${stats.blockReal} 个题型块）。</div>`;
    return;
  }
  const pct = Math.round(ts / tot * 100);
  el.innerHTML =
    `<button class="srcsum" type="button" aria-expanded="false">`
    + `真题 ${stats.blockReal} 块 · 仿真 ${stats.blockSim} 块（占词次 ${pct}%）`
    + `— 来源说明</button>`
    + `<div class="body"><b>关于「真题」二字：</b>可核实的真题片段 ${stats.blockReal} 块`
    + (stats.blockImport ? `、你导入的未标注文本 ${stats.blockImport} 块` : '')
    + `；标「仿真」的 ${stats.blockSim} 块（占词次 ${pct}%）是按真题题材与难度人工撰写的，`
    + `用于补足样本，<b>它的出现次数不等于考场频次</b>。`
    + `卡面把两个数字分开写，标「真题」的才是考场原句。</div>`;
  /* 手机上折叠/展开；桌面上这个按钮是 display:none，点了也看不到 */
  const sum = el.querySelector('.srcsum');
  if(sum) sum.addEventListener('click', function(){
    const open = el.classList.toggle('open');
    sum.setAttribute('aria-expanded', open ? 'true' : 'false');
  });
})();

/* 筛选项 */
const yk = y => {const m=String(y).match(/(\d{4})年\s*(\d{1,2})?/); return m? (+m[1])*100+(+(m[2]||0)) : 0;};
const years = [...new Set(cards.flatMap(c=>c.years))].sort((a,b)=>yk(b)-yk(a));
const secs  = [...new Set(cards.flatMap(c=>c.sections))];
years.forEach(y=>document.getElementById('year').add(new Option(y,y)));
secs.forEach(s=>document.getElementById('sec').add(new Option(s,s)));

const esc = s => (s||'').replace(/[&<>]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[m]));
const hl  = s => esc(s).replace(/\[\[(.*?)\]\]/g,'<mark>$1</mark>');
const resc = s => s.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
/* 反向搜索时把命中的中文高亮出来，否则一堆译文里根本看不出为什么匹配 */
function hlZh(s, kw){
  if(!kw || !s) return esc(s);
  return esc(s).replace(new RegExp('('+resc(kw)+')','gi'),'<mark>$1</mark>');
}
/* 一个词的全部中文字面：释义 + 搭配提示 + 各句的译文/题干译文/情境。
   反向（中→英）只在这片文本里找，不再去英文里凑。 */
function zhText(c){
  return [c.senses.join(' '), c.note||'',
    c.examples.map(e=>[e.trans, e.questionTrans, e.topic].filter(Boolean).join(' ')).join(' ')
  ].join(' ').toLowerCase();
}

/* ---------- 朗读 ----------
   主路径用系统语音合成（Web Speech API）：浏览器自带、不联网、不依赖任何
   外部服务，单文件离线打开也能读。只有在系统一个英文语音都找不到时，才退回
   在线音频——在线接口要么被网络挡住、要么哪天就停了，不能当主路径。
   手机浏览器要求 speak() 必须在用户手势里触发，所以全部挂在点击事件上。 */
const TTS = (function(){
  const synth = window.speechSynthesis || null;
  const RATES = [['常速',1],['慢速',0.7],['很慢',0.5]];
  const RKEY = 'cet4_tts_rate_v1';
  let ri = 0, voice = null;
  try{ const v = parseInt(localStorage.getItem(RKEY),10); if(v>=0 && v<RATES.length) ri = v; }catch(e){}

  /* 语音列表是异步就绪的：Chrome 首次 getVoices() 常常返回空数组，
     要等 voiceschanged 事件之后才拿得到，所以两处都要 pick。 */
  function pick(){
    if(!synth || !synth.getVoices) return null;
    const vs = (synth.getVoices() || []).filter(v=>/^en/i.test(v.lang||''));
    if(!vs.length){ voice = null; return null; }
    // 优先美音（四六级听力也是美音为主），其次英音，再次任意英语语音
    vs.sort((a,b)=>(/^en[-_]US/i.test(a.lang)?0:1)-(/^en[-_]US/i.test(b.lang)?0:1));
    voice = vs[0];
    return voice;
  }
  if(synth){
    pick();
    const on = ()=>pick();
    if(synth.addEventListener) synth.addEventListener('voiceschanged', on);
    else synth.onvoiceschanged = on;
  }

  function hint(msg){
    const el = document.getElementById('ttsHint');
    if(el && !el.textContent) el.textContent = msg;
  }

  /* 兜底：在线发音。只给短文本，URL 太长会被服务端拒 */
  function online(text){
    if(text.length > 140){ hint('这句话太长了，在线发音读不了，建议装个英文语音包'); return true; }
    try{
      const a = new Audio('https://dict.youdao.com/dictvoice?type=2&audio='
        + encodeURIComponent(text));
      const p = a.play();
      if(p && p.catch) p.catch(()=>hint('在线发音没响，可能是网络不通或设备静音；装个英文语音包就能离线朗读'));
      return true;
    }catch(e){ return false; }
  }

  return {
    get rate(){ return RATES[ri][1]; },
    get label(){ return RATES[ri][0]; },
    cycle(){
      ri = (ri + 1) % RATES.length;
      try{ localStorage.setItem(RKEY, String(ri)); }catch(e){}
      return RATES[ri][0];
    },
    say(text){
      text = (text||'').trim();
      if(!text) return;
      if(synth && (voice || pick())){
        try{ synth.cancel(); }catch(e){}
        const u = new SpeechSynthesisUtterance(text);
        u.lang = (voice && voice.lang) || 'en-US';
        u.rate = RATES[ri][1];
        u.pitch = 1;
        /* 赋 voice 有可能抛异常：某些浏览器在语音列表刷新后旧对象会失效，
           或者换了语音包导致对象对不上。这里失败就退化成只给 lang，
           由浏览器自己挑一个英语嗓音，总比整句读不出来强。 */
        try{ if(voice) u.voice = voice; }catch(e){}
        synth.speak(u);
        return;
      }
      if(!online(text)) hint('这台设备没有可用的英文朗读，建议装一个英文语音包');
    }
  };
})();
/* 例句的朗读文本要现取，不能把整句塞进 data- 属性：
   句子里含引号/角括号，属性会被截断或串味 */
function sentTextOf(p){
  const c = p.cloneNode(true);
  c.querySelectorAll('button').forEach(b=>b.remove());
  return c.textContent.trim();
}
function sayWordOf(card){
  if(card) TTS.say(card.dataset.w);
}
function sayFirstVisible(){
  sayWordOf(document.querySelector('#list .card'));
}

function match(c){
  const kw = kwNow();
  const yv = document.getElementById('year').value;
  const sv = document.getElementById('sec').value;
  const on = [...document.querySelectorAll('.chip[data-lv]')].filter(e=>e.classList.contains('on')).map(e=>e.dataset.lv);
  if(!on.includes(c.level)) return false;
  if(yv && !c.years.includes(yv)) return false;
  if(sv && !c.sections.includes(sv)) return false;
  if(hideKnown && known.has(c.word)) return false;
  if(onlyFav && !fav.has(c.word)) return false;
  /* 只看高频：把只出现过一次的长尾词（约占四分之一）先放一放 */
  if(onlyHiFreq && c.count < 2) return false;
  /* 今日复习：只留到期该复习的词，没学过的词也算该学 */
  if(onlyDue && !(!srs[c.word] || (srs[c.word].due && srs[c.word].due <= TODAY))) return false;
  /* 今日 30：到期复习优先，再用没学过的词按排序补位 */
  if(todayMode && !todaySetCached().has(c.word)) return false;
  /* 难词：反复忘的那批，单独拎出来再过一遍 */
  if(onlyHard && !isHard(c.word)) return false;
  if(!kw) return true;
  if(dir === 'rev') return zhText(c).includes(kw);
  return c.word.includes(kw) || c.senses.join(' ').toLowerCase().includes(kw)
      || c.examples.some(e=>e.sentence.toLowerCase().includes(kw));
}
/* 搜索命中的相关度：正向 词头命中 > 释义命中 > 只在例句里出现。
   不这么排的话，搜 although 会被一堆"例句里恰好含 although"的词淹没。
   反向则是 首义项命中 > 其他义项 > 搭配提示 > 只在译文里出现。 */
function rel(c){
  const kw = kwNow();
  if(!kw) return 0;
  if(dir === 'rev'){
    const s = c.senses.map(x=>(x||'').toLowerCase());
    if(s[0] && s[0].includes(kw)) return 4;
    if(s.join(' ').includes(kw)) return 3;
    if((c.note||'').toLowerCase().includes(kw)) return 2;
    if(c.examples.some(e=>(e.trans||'').toLowerCase().includes(kw))) return 1;
    return 0;
  }
  if(c.word === kw) return 3;
  if(c.word.startsWith(kw)) return 2;
  if(c.word.includes(kw)) return 1;
  if(c.senses.join(' ').toLowerCase().includes(kw)) return 1;
  return 0;
}
function sorted(list){
  const m = document.getElementById('sort').value;
  const lv = {A:0,B:1,C:2};
  const hasKw = !!document.getElementById('q').value.trim();
  // 有搜索词时，先按相关度排，再按用户选的排序
  const base = (a,b)=>{
    if(m==='freq')  return b.count-a.count || a.word.localeCompare(b.word);
    if(m==='alpha') return a.word.localeCompare(b.word);
    return (lv[a.level]-lv[b.level]) || (b.count-a.count) || a.word.localeCompare(b.word);
  };
  return [...list].sort((a,b)=> hasKw ? (rel(b)-rel(a) || base(a,b)) : base(a,b));
}
/* ---------- 复习状态（三档自评 + 间隔复习） ---------- */
const SKEY = 'cet4_srs_v1';
/* 连续答对 n 次之后的下次复习间隔（天） */
const INTV = [1,2,4,7,15,30,60];
let srs = {};
try{ srs = JSON.parse(localStorage.getItem(SKEY) || '{}') || {}; }catch(e){ srs = {}; }
/* 存成数组/字符串也算坏数据，后面 srs[w].lv 会炸 */
if(!srs || typeof srs !== 'object' || Array.isArray(srs)) srs = {};
/* 隐私模式或配额写满时 setItem 会抛，别让写盘的失败打断交互 */
function saveJSON(k, v){ try{ localStorage.setItem(k, JSON.stringify(v)); }catch(e){} }
let revealed = new Set();      /* 听写模式下"已显示答案"的词 */

function iso(d){
  return d.getFullYear() + '-' + String(d.getMonth()+1).padStart(2,'0')
       + '-' + String(d.getDate()).padStart(2,'0');
}
function dayOffset(n){
  const d = new Date(); d.setDate(d.getDate() + n); return iso(d);
}
const TODAY = iso(new Date());
function saveSrs(){ saveJSON(SKEY, srs); }
/* 旧版只有「已掌握」一个开关。第一次升级时把那些词平移成"会"，
   7 天后先复习一轮，别让老用户一觉醒来进度全没 */
if(!Object.keys(srs).length && known.size){
  const due = dayOffset(7);
  known.forEach(w => { srs[w] = {lv:2, n:3, due}; });
  saveSrs();
}
/* ---------- 每日计划 ----------
   1550 个词对 370 分档来说是"打开就想关"的量：页面上只有「已掌握 0 / 1550」，
   看不出今天该背哪几个。这里给一个 30 词/天 的小目标：先清到期复习的词，
   再按等级与频次顺序用没学过的词补位。
   连续天数纯粹是心理激励，不参与任何筛选逻辑。 */
const GOAL = 30;
const TKEY = 'cet4_today_v1', STKEY = 'cet4_streak_v1';
let todayRec = {d: TODAY, n: 0, words: []};
try {
  const v = JSON.parse(localStorage.getItem(TKEY) || 'null');
  if (v && typeof v === 'object' && Array.isArray(v.words)) todayRec = v;
} catch (e) {}
/* 跨天自动归零：同一天不重置，换一天就从 0 开始 */
if (todayRec.d !== TODAY) todayRec = {d: TODAY, n: 0, words: []};
let streak = {last: '', n: 0};
try {
  const v = JSON.parse(localStorage.getItem(STKEY) || 'null');
  if (v && typeof v === 'object') streak = v;
} catch (e) {}
let todayMode = false;
let _todayCache = null;
/* 上次打开是哪天：断了三天以上回来，先把到期的清掉，别接着学新词 */
const LASTKEY = 'cet4_last_open_v1';
let lastOpen = '';
try { lastOpen = localStorage.getItem(LASTKEY) || ''; } catch (e) {}
const gapDays = (function(){
  if(!lastOpen) return 0;
  const a = new Date(lastOpen + 'T00:00:00'), b = new Date(TODAY + 'T00:00:00');
  const d = Math.round((b - a) / 86400000);
  return isFinite(d) && d > 0 ? d : 0;
})();
function markOpened(){ try { localStorage.setItem(LASTKEY, TODAY); } catch (e) {} }
/* 每日学习记录：{'2026-11-08': {n: 当天打过分的词次, m: 当天结束时的已掌握数}}
   报告页的热力图与掌握曲线全靠它。只记日期和数字，不记任何文本。 */
const LKEY = 'cet4_log_v1';
let LOGS = {};
try {
  const v = JSON.parse(localStorage.getItem(LKEY) || '{}');
  if (v && typeof v === 'object' && !Array.isArray(v)) LOGS = v;
} catch (e) { LOGS = {}; }
function saveLogs(){ saveJSON(LKEY, LOGS); }

function markToday(w){
  if (todayRec.d !== TODAY) todayRec = {d: TODAY, n: 0, words: []};
  if (!todayRec.words.includes(w)) {
    todayRec.words.push(w);
    todayRec.n = todayRec.words.length;
    saveJSON(TKEY, todayRec);
  }
  if (streak.last !== TODAY) {
    /* 昨天打过卡才算连续，隔了一天以上重新计数 */
    streak = {last: TODAY, n: streak.last === dayOffset(-1) ? (streak.n || 0) + 1 : 1};
    saveJSON(STKEY, streak);
  }
  const rec = LOGS[TODAY] || (LOGS[TODAY] = {n: 0, m: 0});
  rec.n = (rec.n || 0) + 1;
  rec.m = known.size;
  saveLogs();
  _todayCache = null;   /* 打过卡，今日队列要重算 */
}
/* 今日队列：cards 已经按「等级 A→C、出现次数降序」排好，
   所以补位补进来的就是当前最该背的那批。
   补位时先跳过纯虚词：按频次排序，榜首全是 be / for / has 这类语法词，
   它们不该占掉一天 30 个名额（实测前 3 个正是 be, for, has）。 */
const FUNC_POS = /^(pron|prep|conj|art|aux|num)\./;
function todaySet(){
  const out = new Set();
  for (const c of cards) {
    if (out.size >= GOAL) break;
    const st = srs[c.word];
    if (st && typeof st === 'object' && st.due && st.due <= TODAY) out.add(c.word);
  }
  for (const c of cards) {
    if (out.size >= GOAL) break;
    if (!srs[c.word] && !STOP.has(c.word) && !FUNC_POS.test(c.pos || '')) out.add(c.word);
  }
  /* 内容词不够 30 个时（新手第 40 天左右会遇到），再拿虚词补齐，不留空位 */
  for (const c of cards) {
    if (out.size >= GOAL) break;
    if (!srs[c.word]) out.add(c.word);
  }
  return out;
}
function todaySetCached(){
  if (!_todayCache) _todayCache = todaySet();
  return _todayCache;
}

/* 坏数据里 srs[w] 可能是个数字或字符串，取 .lv 之前先确认是对象 */
const lvOf = w => (srs[w] && typeof srs[w] === 'object' ? srs[w].lv : -1);
function grade(w, lv, rerender){
  const cur = srs[w] || {lv:-1, n:0, due:''};
  let n = cur.n || 0, due;
  if(lv === 0){ n = 0; due = TODAY; }              /* 不会：今天就得再见 */
  else if(lv === 1){ n = 1; due = dayOffset(1); }  /* 模糊：明天 */
  else { n = Math.min(cur.n + 1, INTV.length); due = dayOffset(INTV[n-1]); }
  srs[w] = {lv, n, due};
  saveSrs();
  /* known 仍然维护着：旧的「只看未掌握」筛选和进度统计都靠它 */
  lv === 2 ? known.add(w) : known.delete(w);
  saveJSON(KEY, [...known]);
  /* 每日计划：同一个词一天只计一次，改自评不会把今日进度刷上去。
     必须放在 known 更新之后——markToday 会顺手把当天的"已掌握数"快照写进 LOGS，
     放在前面就会永远慢一步，报告页的掌握曲线也就跟着错位。 */
  markToday(w);
  /* 拼写/做题里打分后不能整页重刷，会把刚填的东西冲掉，由调用方决定 */
  if(rerender !== false) render();
}
const dueCount = () => Object.keys(srs)
  .filter(w => srs[w] && typeof srs[w] === 'object' && srs[w].due && srs[w].due <= TODAY).length;
/* 难词：答对次数不到 2 次，而且现在还是「不会 / 模糊」。
   这类词是真正的钉子户——SRS 队列里它们会天天出现，但和"第一次见"的词混在一起，
   看不出"这 30 个里有一半是我反复忘的"。 */
const isHard = w => {
  const s = srs[w];
  return !!(s && typeof s === 'object' && (s.lv === 0 || s.lv === 1) && (s.n || 0) < 2);
};
const hardCount = () => Object.keys(srs).filter(w => CARDW.has(w) && isHard(w)).length;
/* 明天该复习多少个：决定"今天要不要提前清一点" */
const dueTomorrow = () => Object.keys(srs).filter(w => {
  const s = srs[w];
  return s && typeof s === 'object' && s.due === dayOffset(1);
}).length;
function dueLabel(w){
  const s = srs[w];
  if(!s) return '';
  const L = ['不会','模糊','会'][s.lv] || '';
  const d = s.due && s.due <= TODAY ? '今天该复习' : s.due ? '下次 ' + s.due.slice(5) : '';
  return `<span class="lvtag l${s.lv}">${L}</span><span class="due">${d}</span>`;
}
/* 把一段文本里的目标词挖空（拼写/听写/做题共用）。
   必须直接在 [[ ]] 标记上挖：真题句里目标词往往只以高亮形式出现
   （"not because [[they]] need it but because [[they]] feel…"），
   先把标记换成空格再回头找词，句子里就已经没有这个词了——
   这正是第一版做题模式挖不出空格的原因。 */
function blankWord(text, form){
  const f = (form || '').toLowerCase();
  let hit = false;
  let s = esc(text).replace(/\[\[(.*?)\]\]/g, (m, w) => {
    if(f && w.toLowerCase() === f){
      hit = true;
      return `<span class="blank">${'_'.repeat(Math.min(w.length, 14))}</span>`;
    }
    return w;      /* 同一个词的其它词形（taken 之于 take）保留为普通文本 */
  });
  if(hit || !f) return s;
  /* 兜底：这句里没有与本题词形一致的高亮标记，按整词边界直接挖 */
  const re = new RegExp('\\b' + resc(f) + '\\b', 'i');
  return re.test(s)
    ? s.replace(re, `<span class="blank">${'_'.repeat(Math.min(f.length, 14))}</span>`)
    : s;
}
function blankAllMarks(text){
  return esc(text).replace(/\[\[(.*?)\]\]/g, (m, w) =>
    `<span class="blank">${'_'.repeat(Math.min(w.length, 14))}</span>`);
}

/* ---------- 来源标签 ----------
   仿真语料是项目自己的选择（8 个场次按真题题材撰写），但卡面必须说清楚，
   否则「真题出现 6 次」会把仿真文的用词习惯当成考场频次卖给学生。 */
const SRC_TXT = {real:'真题', sim:'仿真', import:'导入'};
function srcTag(src){
  if(!src || src === 'real') return '';
  return `<span class="tag ${src}">${SRC_TXT[src] || src}</span>`;
}
/* 出现次数：拆开写。只有仿真出现过的词，绝不用「真题」开头。 */
function freqLabel(c){
  const r = c.countReal || 0, s = c.countSim || 0;
  if(!s) return `真题出现 ${r || c.count} 次`;
  if(!r) return `仿真出现 ${s} 次`;
  return `真题 ${r} 次 · 仿真 ${s} 次`;
}
/* 出处年份：只在仿真语料里出现的场次，后面挂「·仿真」 */
function yearLabel(y, c){
  return (c.yearsReal || []).includes(y) ? y : y + '·仿真';
}

/* 例句按当前筛选重排：选了「2025年6月」就该先看到 2025年6月 的原句，
   而不是排在前面的 2021 年仿真句。原来这里不过滤，于是筛真题场次时
   首屏第一条仍是仿真例句，加了来源标签之后这种错位特别刺眼。
   年份维度实测覆盖 100%（finalize 保证每个场次至少留一条），
   题型维度约 30% 的词在前 3 条里没有该题型，那就原样给出——
   每条例句自己带着题型标签，读者不会认错。 */
function pickExamples(c){
  const yv = (document.getElementById('year')||{}).value || '';
  const sv = (document.getElementById('sec')||{}).value || '';
  if(!yv && !sv) return {list:c.examples, filtering:false, matched:false};
  const hit = c.examples.filter(e => (!yv || e.year === yv) && (!sv || e.section === sv));
  /* 每个词只留 3 条例句，跨 11 个场次的词不可能每场都占到一条：
     实测「词 × 场次」里只有 68% 能在前 3 条中找到该场次（2025年6月 是 54%）。
     找不到时如实说明，而不是让 2021 年的句子顶着 2025 年的筛选条件出现。 */
  return hit.length
    ? {list:hit, filtering:true, matched:true}
    : {list:c.examples, filtering:true, matched:false};
}

function cardHTML(c){
  const lv = lvOf(c.word), isFav = fav.has(c.word), done = lv === 2;
  const kw = kwNow();
  /* 反向搜索时中文也要高亮；正向保持原样（例句里的 [[ ]] 标记本来就会高亮） */
  const deco = (dir === 'rev' && kw) ? (s => hlZh(s, kw)) : esc;
  const spell = mode === 'spell', listen = mode === 'listen';
  const hideW = spell || (listen && !revealed.has(c.word));
  const blurSense = quiz && !spell;   /* 拼写模式本来就要看释义，不模糊 */
  const senses = `<ul class="senses${blurSense?' blur':''}">`+c.senses.map(s=>`<li>${deco(s)}</li>`).join('')+`</ul>`;

  /* 拼写/听写模式下不展示原题与上下文：那是另一句完整原文，会把答案漏出去 */
  const picked = pickExamples(c);
  const ex = picked.list.map(e=>{
    const sent = spell ? blankAllMarks(e.sentence)
               : listen ? `<span class="hideword">（听力材料已隐藏，点上面喇叭听）</span>`
               : hl(e.sentence);
    return `
    <div class="ex">
      <div class="src">
        ${srcTag(e.src)}<span class="tag">${esc(e.year)}</span><span class="tag">${esc(e.set)}</span>
        <span class="tag">${esc(e.section)}</span><span class="tag">${esc(e.title)}</span>
        ${e.kind && e.kind !== 'body' ? `<span class="tag">${e.kind === 'question' ? '题干' : '选项'}</span>` : ''}
        ${e.posHint?`<span class="tag">此处作${esc(e.posHint)}</span>`:''}
        ${!hideW?`<span class="tag">本句词形 ${esc(e.form)}</span>`:''}
      </div>
      ${e.topic && !listen?`<div class="src">情境：${deco(e.topic)}</div>`:''}
      <p class="sent">${sent}<button class="spk sm" data-act="saySent"
        title="朗读这句话" aria-label="朗读例句">&#128266;</button></p>
      ${e.trans?`<div class="trline"><button class="eye-sq" data-act="tr">&#128065; 译文</button><span class="tr">${deco(e.trans)}</span></div>`:''}
      ${e.prev && !hideW?`<p class="ctx">上文：${esc(e.prev)}</p>`:''}
      ${e.next && !hideW?`<p class="ctx">下文：${esc(e.next)}</p>`:''}
      ${e.question && !hideW?`<div class="q"><b>原题：</b>${esc(e.question)}${e.questionTrans?`<span class="tr">${deco(e.questionTrans)}</span>`:''}</div>`:''}
    </div>`;}).join('');

  const head = hideW
    ? `<span class="hideword" title="词长 ${c.word.length} 个字母">${'●'.repeat(Math.min(c.word.length,14))}</span>`
    : `<span class="w say" data-act="sayWord" title="点单词或喇叭朗读（快捷键 Alt+S）">${esc(c.word)}</span>
       <button class="spk" data-act="sayWord" title="朗读这个单词（快捷键 Alt+S）"
         aria-label="朗读 ${esc(c.word)}">&#128266;</button>`;
  const spellbox = spell ? `
      <div class="spellbox" data-w="${esc(c.word)}">
        <input type="text" class="spellIn" placeholder="听读音、看释义，拼出这个单词后回车"
               autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false">
        <div class="spellmsg"></div>
      </div>` : '';
  const listenbtn = listen ? `
      <div class="listenwrap">
        <button class="big" data-act="sayWord" aria-label="朗读这个单词">&#128266;</button>
        <div class="hint">点喇叭听，写完再看。看不懂时点「显示答案」。</div>
      </div>` : '';
  const reveal = listen && !revealed.has(c.word)
    ? `<button class="mini" data-act="reveal">显示答案</button>` : '';

  return `<div class="card${done?' done':''}" data-w="${esc(c.word)}">
    <div class="hd">
      ${head}
      ${c.phonetic?`<span class="ph" title="音标">/${esc(c.phonetic)}/</span>`:''}
      <span class="pos">${esc(c.pos)}</span>
      <span class="lv ${c.level}">${c.levelName}</span>
      <span class="freq">${freqLabel(c)}</span>
      <span class="star${isFav?' on':''}" data-act="fav"
            title="${isFav?'取消收藏':'收藏这个词，之后可只看收藏'}">★</span>
    </div>
    <div class="body">
      ${listenbtn}
      ${spellbox}
      ${senses}
      ${c.confuse && c.confuse.length ? `<div class="confuse">易混：`
        + c.confuse.map(w=>`<button type="button" class="cw" data-act="confuse"
            data-w="${esc(w)}" title="跳到 ${esc(w)}">${esc(w)}</button>`).join('')
        + `</div>` : ''}
      ${c.family && c.family.length ? `<div class="confuse fam">同族：`
        + c.family.map(([w, rel, has]) => has
            ? `<button type="button" class="cw fw" data-act="confuse" data-w="${esc(w)}"
                title="${rel === 'base' ? '原形' : '派生词'}，点一下跳过去">${esc(w)}</button>`
            : `<span class="cw fw off" title="词库里有这个词，但真题里没出现，所以没有卡片">${esc(w)}</span>`
          ).join('')
        + `</div>` : ''}
      ${c.note?`<div class="note">${deco(c.note)}</div>`:''}
      ${picked.filtering && !picked.matched
        ? `<div class="src exnote">该词在当前筛选的场次／题型里确实出现过，但下面列出的例句都取自其他场次</div>` : ''}
      ${ex}
    </div>
    <div class="foot">
      <button class="mini${lv===0?' no':''}" data-act="lv" data-lv="0"
        title="不会：今天就会再出现">不会</button>
      <button class="mini${lv===1?' mid':''}" data-act="lv" data-lv="1"
        title="模糊：明天再复习一次">模糊</button>
      <button class="mini${lv===2?' ok':''}" data-act="lv" data-lv="2"
        title="会：进入间隔复习（1/2/4/7/15/30/60 天）">会</button>
      ${reveal}
      ${mode!=='listen'||revealed.has(c.word)?`<button class="mini" data-act="show">显示/隐藏释义</button>`:''}
      ${dueLabel(c.word)}
      <span class="freq">出处：${(c.years||[]).map(y=>esc(yearLabel(y,c))).join('、')}</span>
    </div>
  </div>`;
}
/* 空结果不能只甩一句“没有匹配”——得说清楚是卡在哪，并给一条能点出去的路 */
function emptyHTML(){
  const raw = document.getElementById('q').value.trim(), kw = kwNow();
  const lvOn = [...document.querySelectorAll('.chip[data-lv]')].filter(e=>e.classList.contains('on')).map(e=>e.dataset.lv);
  const yv = document.getElementById('year').value, sv = document.getElementById('sec').value;
  const LVN = {A:'基础高频',B:'核心必背',C:'进阶拓展'};
  let title = '没有匹配的单词';
  const why = [];
  if(onlyFav && !fav.size){
    title = '收藏夹还是空的';
    why.push('点单词卡片右上角的 ★ 即可收藏，之后用它快速回看常错词');
    if(raw) why.push('现在还带着搜索词「'+esc(raw)+'」，先清空更容易挑词');
  }else if(kw){
    title = '没找到「'+esc(raw)+'」';
    if(dir === 'rev') why.push('反向搜索只匹配中文释义与译文，换个更短的中文词试试，或切回「英→中」');
    else why.push('试试只输入前几个字母（如 alth），或改用「中→英」按中文意思反查');
  }else{
    title = '当前筛选条件下没有单词';
  }
  if(!(onlyFav && !fav.size)){
    if(lvOn.length < 3) why.push('有等级被隐藏，现在只显示：' + (lvOn.map(x=>LVN[x]).join('、') || '无'));
    if(hideKnown) why.push('开着「只看未掌握」，已标记掌握的词都被排除了');
    if(yv) why.push('限定年份：' + esc(yv));
    if(sv) why.push('限定题型：' + esc(sv));
  }
  const acts = [];
  if(raw) acts.push(['clrQ', '清空搜索词']);
  if(raw) acts.push([dir === 'rev' ? 'toFwd' : 'toRev', dir === 'rev' ? '切回「英→中」' : '试试「中→英」反查']);
  if(lvOn.length < 3) acts.push(['allLv', '显示全部等级']);
  if(hideKnown || yv || sv) acts.push(['rstFilter', '重置筛选条件']);
  return `<div class="empty">
    <div class="et">${title}</div>
    ${why.length ? `<ul class="ew">${why.map(w=>`<li>${w}</li>`).join('')}</ul>` : ''}
    <div class="eacts">${acts.map(a=>`<button class="mini" data-act2="${a[0]}">${a[1]}</button>`).join('')}</div>
  </div>`;
}function renderHist(){
  const row = document.getElementById('histRow');
  if(!hist.length){ row.style.display = 'none'; row.innerHTML = ''; return; }
  row.style.display = '';
  row.innerHTML = '<span class="hlab">最近搜索</span>' +
    hist.map((h,i)=>`<span class="hitem" data-i="${i}" title="点击回填（${h.m==='rev'?'中→英':'英→中'}）">
      <span class="hdir">${h.m === 'rev' ? '中' : '英'}</span><span class="ht">${esc(h.t)}</span>
      <span class="hx" data-del="${i}" title="删除这条">×</span></span>`).join('') +
    '<button class="btn hclr" data-act2="clrHist">清空</button>';
}
function render(){
  _todayCache = null;                 /* 打分/筛选都会改今日队列，每次重算 */
  const due = dueCount();             /* 提示条与进度行都要用，先算 */
  const list = sorted(cards.filter(match));
  const show = list.slice(0, page*perPage());
  /* 第一次打开时给一句话的路：屏幕上只有 1550 张卡的时候，人会直接关掉。
     有进度之后这句自动消失，不打扰老用户。 */
  const fresh = !known.size && !Object.keys(srs).length && page === 1 && !todayMode;
  const hint = fresh ? `<div class="startHint">第一次用？点上面的 <b>今日 30</b>：
      每天 30 个词，约 ${Math.ceil(cards.length / GOAL)} 天走完。下面就是排好的顺序。</div>` : '';
  /* 断签回来：比"接着学新词"更要紧的是把到期的那批清掉，否则欠账会越滚越大 */
  const back = !fresh && gapDays >= 3 && due > 0 && page === 1 && !todayMode && !onlyDue;
  const backHint = back ? `<div class="startHint warn">上次学习是 <b>${gapDays}</b> 天前。
      今天有 <b>${due}</b> 个词到期，先点上面的「今日复习」清掉，再学新的——
      ${dueTomorrow() ? `欠账不清，明天会变成 ${due + dueTomorrow()} 个。` : '清完今天这批，明天就不会堆上来。'}</div>` : '';
  document.getElementById('list').innerHTML =
    show.length ? hint + backHint + show.map(cardHTML).join('') : emptyHTML();
  const hasMore = list.length > show.length;
  document.getElementById('more').style.display = hasMore?'block':'none';
  document.getElementById('mMore').style.display = hasMore?'inline-block':'none';
  /* 数据分两批到：首屏 60 词先渲染，其余流式补进来。
     没到齐之前别谎报"共 60 个单词"——那会让人以为词库就这么点。 */
  document.getElementById('tip').innerHTML = (DATA.allReady
      ? `共 ${list.length} 个单词`
      : `词库加载中 ${cards.length} / ${stats.wordCount}…`)
    + ' <span class="kbd">· 点单词或 🔊 朗读 · / 聚焦搜索 · Alt+S 朗读第一个 · Alt+D 今日复习 · Alt+R 切换正反 · Alt+F 只看收藏 · Alt+1 语速</span>';
  /* 今日进度取代原来那句「已掌握 0 / 1550」：总数不变，但每天看得见自己走了多少。
     "明天 n" 是提前量——今天看到明天要复习 40 个，就不会等到明天再慌。 */
  document.getElementById('prog').innerHTML =
    `今日 <b>${todayRec.n}</b>/${GOAL} · 连续 <b>${streak.n || 0}</b> 天`
    + ` · 明天 <b>${dueTomorrow()}</b> · 已掌握 <b>${known.size}</b>/${cards.length}`;
  document.getElementById('todayChip').textContent =
    '今日 ' + GOAL + (todayRec.n >= GOAL ? ' ✓' : '');
  document.getElementById('todayChip').classList.toggle('on', todayMode);
  const hc = hardCount();
  document.getElementById('hardChip').textContent = '难词' + (hc ? ` (${hc})` : '');
  document.getElementById('hardChip').classList.toggle('on', onlyHard);
  document.getElementById('favChip').textContent = '★ 收藏' + (fav.size ? ` (${fav.size})` : '');
  document.getElementById('dueChip').textContent = '今日复习' + (due ? ` (${due})` : '');
  document.getElementById('dueChip').classList.toggle('on', onlyDue);
  document.getElementById('hiFreq').classList.toggle('on', onlyHiFreq);
  /* 底部条三个开关的状态同步。原来「自测」是靠改文字表示开关（自测→自测已关），
     320px 屏上多两个字整条按钮就挤出屏幕了，改成上色、文字不变。
     不同步的话，手机上点了根本看不出现在是开还是关。 */
  document.getElementById('mQuiz').classList.toggle('on', quiz);
  document.getElementById('mKnown').classList.toggle('on', hideKnown);
  document.getElementById('mDue').classList.toggle('on', onlyDue);
  renderHist();
  if(mode === 'spell'){
    const first = document.querySelector('.spellbox input');
    if(first) first.focus();
  }
}
const wantMore = () => { page++; render(); };

/* ---------- 做题：真题句子挖空选词 ---------- */
const POS1 = /^(n|v|adj|adv|pron|prep|conj|num|art|int|aux)\./;
const posKey = p => { const m = POS1.exec((p||'').trim()); return m ? m[1] : 'other'; };
let qList = [], qIdx = -1, qRight = 0, qAnswered = false;

function shuffle(a){
  for(let i = a.length - 1; i > 0; i--){
    const j = Math.random() * (i + 1) | 0; [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}
/* 只挑「词形与原形一致、带译文、句子够长」的例句出题。
   词形必须等于原形：不然空格处是 leads、选项里却是 lead，学生没法对。 */
function quizPool(){
  const out = [];
  sorted(cards.filter(match)).forEach(c=>{
    if(c.word.indexOf(' ') >= 0) return;   /* 固定搭配不进选择题 */
    c.examples.forEach(o=>{
      if(o.form.toLowerCase() !== c.word) return;
      const plain = o.sentence.replace(/\[\[|\]\]/g, '');
      if(!o.trans || plain.length < 40) return;
      out.push({c, o});
    });
  });
  return out;
}
function mkQ(item){
  const {c, o} = item;
  const key = c.level + '|' + posKey(c.pos);
  let cand = (POSPOOL[key] && POSPOOL[key].length >= 4) ? POSPOOL[key]
           : (POSPOOL['*|' + posKey(c.pos)] || []);
  const others = shuffle(cand.filter(w => w !== c.word)).slice(0, 3);
  if(others.length < 3) return null;
  const opts = shuffle([c.word, ...others]);
  return { w:c.word, opts, ans:opts.indexOf(c.word),
    stem: blankWord(o.sentence, o.form), trans:o.trans,
    src:`${o.year} ${o.set} · ${o.section} · ${o.title}`,
    ph:c.phonetic };
}
function startQuiz(){
  qList = shuffle(quizPool().map(mkQ).filter(Boolean)).slice(0, 20);
  qIdx = -1; qRight = 0;
  nextQ();
}
function nextQ(){
  qIdx++; qAnswered = false;
  const box = document.getElementById('qOpts');
  const rb = document.getElementById('qRebuild');
  if(qIdx >= qList.length){
    const pct = qList.length ? Math.round(qRight / qList.length * 100) : 0;
    document.getElementById('qSrc').textContent = '';
    document.getElementById('qIdx').textContent = '';
    document.getElementById('qStem').innerHTML =
      `<div class="qdone">本轮结束<div class="n">${qRight} / ${qList.length}</div>答对率 ${pct}%</div>`;
    document.getElementById('qTrans').textContent = '';
    box.innerHTML = '';
    document.getElementById('qRes').textContent = '';
    document.getElementById('qRes').className = 'qres';
    document.getElementById('qNext').style.display = 'none';
    rb.style.display = 'inline-block';
    return;
  }
  rb.style.display = 'none';
  const q = qList[qIdx];
  document.getElementById('qSrc').textContent = q.src;
  document.getElementById('qIdx').textContent = `第 ${qIdx + 1} / ${qList.length} 题`;
  document.getElementById('qStem').innerHTML = q.stem;
  const tr = document.getElementById('qTrans');
  tr.textContent = q.trans;
  /* 译文默认收起：整句的中文翻译里往往就写着空格处那个词的意思，
     开局就摊开等于把答案递到手上，选择题就没得选了。答完再自动展开当讲解。
     真想不出来的人点「看译文」自己展开，不扣分。 */
  tr.classList.remove('t-on');
  document.getElementById('qRes').textContent = '';
  document.getElementById('qRes').className = 'qres';
  document.getElementById('qNext').style.display = 'none';
  const L = 'ABCDEFGH';
  box.innerHTML = q.opts.map((w,i)=>
    `<button class="qopt" data-i="${i}"><b>${L[i]}.</b>${esc(w)}</button>`).join('');
}
function answerQ(btn){
  if(qAnswered || qIdx >= qList.length) return;
  const q = qList[qIdx];
  const right = +btn.dataset.i === q.ans;
  qAnswered = true;
  if(right) qRight++;
  document.querySelectorAll('#qOpts .qopt').forEach(b=>{
    b.disabled = true;
    if(+b.dataset.i === q.ans) b.classList.add('right');
    else if(b === btn) b.classList.add('wrong');
  });
  const res = document.getElementById('qRes');
  document.getElementById('qTrans').classList.add('t-on');   /* 答完摊开译文当讲解 */
  res.className = 'qres ' + (right ? 'ok' : 'bad');
  res.innerHTML = right ? '答对了'
    : `正确答案是 <b>${esc(q.w)}</b>，已记成「不会」，今天就会再出现`;
  grade(q.w, right ? 2 : 0, false);
  document.getElementById('qNext').style.display = 'inline-block';
  document.getElementById('qNext').textContent = qIdx + 1 >= qList.length ? '看结果' : '下一题';
  document.getElementById('qProg').textContent = `本轮答对 ${qRight}`;
  if(q.ph) TTS.say(q.w);
}
document.getElementById('list').addEventListener('click', e=>{
  const a2 = e.target.closest('[data-act2]');
  if(a2){ doAct2(a2.dataset.act2); return; }
  const card = e.target.closest('.card'); if(!card) return;
  const w = card.dataset.w;
  /* 模糊的释义整块都要能点开。原来判的是 e.target.classList，
     只有点到 <ul> 自身的空隙才算，点到里面任何一行 <li> 都没反应。 */
  const blurred = e.target.closest('.blur');
  if(blurred && !e.target.closest('[data-act]')){ blurred.classList.remove('blur'); return; }
  const btn = e.target.closest('[data-act]'); if(!btn) return;
  const act = btn.dataset.act;
  if(act==='lv'){
    grade(w, +btn.dataset.lv);
  }else if(act==='reveal'){
    revealed.add(w);
    render();
  }else if(act==='fav'){
    fav.has(w)?fav.delete(w):fav.add(w);
    saveJSON(FKEY, [...fav]);
    render();
  }else if(act==='sayWord'){
    sayWordOf(card);
  }else if(act==='saySent'){
    const p = btn.closest('.sent');
    if(p) TTS.say(sentTextOf(p));
  }else if(act==='show'){
    card.querySelector('.senses').classList.toggle('blur');
  }else if(act==='tr'){
    btn.parentElement.querySelector('.tr').classList.toggle('t-on');
  }else if(act==='confuse'){
    /* 点「易混」里的词：把它填进搜索框，只留这一个。
       年份/题型顺手清掉——否则搜出来的词可能被当前场次筛掉，看着像点了没反应。 */
    document.getElementById('q').value = btn.dataset.w;
    document.getElementById('year').value = '';
    document.getElementById('sec').value = '';
    page = 1; render();
  }
});
const qEl = document.getElementById('q');
/* 输入时顺手存历史：停顿 1 秒算一次查询，回车/失焦立刻算。
   太短的词（<2 字）不存，否则历史会被单字母刷满。 */
let histT;
qEl.addEventListener('input', ()=>{
  page = 1; render();
  clearTimeout(histT); histT = setTimeout(()=>pushHist(qEl.value), 1000);
});
qEl.addEventListener('keydown', e=>{ if(e.key === 'Enter'){ clearTimeout(histT); pushHist(qEl.value); } });
qEl.addEventListener('blur', ()=>{ clearTimeout(histT); pushHist(qEl.value); });
function pushHist(t){
  const kw = (t||'').trim(); if(kw.length < 2) return;
  const cur = kw.toLowerCase();
  /* 边打字边存会把 al / alth / altho 堆成一串：
     新词只是上一条的延伸时，直接替换掉上一条 */
  if(hist.length && hist[0].m === dir && cur.startsWith(hist[0].t.toLowerCase())
     && hist[0].t.length < kw.length){
    hist[0] = {t:kw, m:dir};
  }else{
    hist = hist.filter(h => !(h.t === kw && h.m === dir));
    hist.unshift({t:kw, m:dir});
  }
  if(hist.length > 10) hist = hist.slice(0, 10);
  saveJSON(HKEY, hist);
  renderHist();
}
/* 空状态里的引导动作 */
function doAct2(a){
  if(a === 'clrQ'){ qEl.value = ''; page = 1; render(); qEl.focus(); }
  else if(a === 'toFwd' || a === 'toRev'){ applyDir(a === 'toFwd' ? 'fwd' : 'rev'); }
  else if(a === 'allLv'){ document.querySelectorAll('.chip[data-lv]').forEach(c=>c.classList.add('on')); page = 1; render(); }
  else if(a === 'rstFilter'){
    hideKnown = false; document.getElementById('hideKnown').classList.remove('on');
    document.getElementById('year').value = ''; document.getElementById('sec').value = '';
    page = 1; render();
  }
}
/* 切换搜索方向：输入框里的字和年份/题型/等级等筛选全都留着，只换匹配方向 */
/* 选择器必须限定在 #dirSeg 内：#viewSeg 的视图按钮也是 .seg-b，
   原来用 '.seg-b' 一把抓，点视图按钮会顺带触发 applyDir(undefined)，
   于是 dir 变成 undefined，而 b.dataset.dir 对视图按钮同样是 undefined，
   undefined === undefined 成立 —— 三个视图按钮同时亮起，方向按钮反而全灭。 */
function applyDir(d){
  if(d !== 'fwd' && d !== 'rev') return;
  dir = d;
  document.querySelectorAll('#dirSeg .seg-b').forEach(b=>b.classList.toggle('on', b.dataset.dir === d));
  qEl.placeholder = d === 'rev' ? '输入中文反查单词，如：尽管、避免、影响'
                                : '搜索单词 / 释义 / 真题句子…';
  page = 1; render();
}
function toggleFavFilter(){
  onlyFav = !onlyFav;
  document.getElementById('favChip').classList.toggle('on', onlyFav);
  page = 1; render();
}
['year','sec','sort'].forEach(id=>document.getElementById(id).addEventListener('change',()=>{page=1;render();}));
/* 练习方式切换：听写模式下"已显示答案"的状态要清掉，否则换回来还是摊开的 */
document.getElementById('mode').addEventListener('change',function(){
  mode = this.value; revealed.clear(); page = 1; render();
});
document.getElementById('dueChip').addEventListener('click',function(){
  onlyDue = !onlyDue; page = 1; render();
});
document.getElementById('hiFreq').addEventListener('click',function(){
  onlyHiFreq = !onlyHiFreq; page = 1; render();
});
document.getElementById('hardChip').addEventListener('click',function(){
  onlyHard = !onlyHard; page = 1; render();
});
/* 视图切换：背单词 / 做题 */
/* ---------- 精读：整篇真题原文，重点词高亮 ---------- */
let rIdx = -1, rShowT = false;
const PASSES = DATA.passages || [];
const PH = {};
cards.forEach(c => { PH[c.word] = c.phonetic; });

/* 篇章难度：按「你还没掌握的词占全文词次的比例」算。
   注意分母必须是词次、分子必须是"这些生词出现了多少次"，不能拿生词个数除词次——
   一篇 188 词的文章里有 60 个生词，密度不是 32%，而是这些生词占了多少个词位。
   输入假说（i+1）的做法是让文本落在 3%~6% 生词，读起来才既不吃力又有收获。 */
function passLoad(p){
  const n = p.n || 0;
  let unk = 0, unkTokens = 0;
  (p.w || []).forEach(x => {
    if (known.has(x[0])) return;
    unk += 1;
    unkTokens += (x[2] || 1);
  });
  const density = n ? unkTokens / n * 100 : 0;
  let label = '很轻松', cls = 'easy';
  if(!n){ label = '过短'; cls = 'easy'; }
  else if(density >= 15){ label = '太难'; cls = 'vhard'; }
  else if(density >= 8){ label = '偏难'; cls = 'hard'; }
  else if(density >= 3){ label = '合适'; cls = 'good'; }
  return {n, unk, density, label, cls};
}

function initPassagePicker(){
  const sel = document.getElementById('passage');
  sel.innerHTML = PASSES.map((p,i) => {
    /* 选单里直接标出每篇还有多少生词，挑篇不用点进去试 */
    const tag = p.src && p.src !== 'real' ? `【${SRC_TXT[p.src] || p.src}】` : '';
    return `<option value="${i}">${tag}${esc(p.y)} ${esc(p.s)} · ${esc(p.sec)} · ${esc(p.t)}`
      + `（生词 ${passLoad(p).unk}）</option>`;
  }).join('');
  // 用 onchange 而不是 addEventListener：数据分两批到，首屏会先建一次空选单，
  // 全量后再建一次；addEventListener 会叠加两个监听，选一篇触发两遍 renderPassage。
  sel.onchange = () => { rIdx = +sel.value; renderPassage(); };
}
function renderPassage(){
  if(rIdx < 0 || rIdx >= PASSES.length) rIdx = 0;
  const p = PASSES[rIdx] || PASSES[0];
  document.getElementById('rSrc').innerHTML =
    `${srcTag(p.src)} ${esc(p.y)} ${esc(p.s)} · ${esc(p.sec)} · ${esc(p.t)}`;
  const ld = passLoad(p);
  document.getElementById('rDiff').innerHTML = ld.n
    ? `全文 ${ld.n} 词 · 还没掌握 <b>${ld.unk}</b> 个重点词`
      + `（占全文词次 <b>${ld.density.toFixed(1)}%</b>）· `
      + `<span class="dl ${ld.cls}">${ld.label}</span>`
    : `<span class="dl easy">正文过短</span> 这一块没有正文（多为只有题干的题型），不评估难度`;
  document.getElementById('rTopic').innerHTML =
    p.topic ? `<b>情境：</b>${esc(p.topic)}` : '';
  document.getElementById('rText').innerHTML = p.sents.map(s => `
    <div class="rsent">
      <span class="rt">${hl(s.t)}</span>
      <button class="spk sm" data-act="rSay" data-t="${esc(s.t.replace(/\[\[|\]\]/g,'')).replace(/"/g,'&quot;')}"
        title="朗读这句话" aria-label="朗读例句">&#128266;</button>
      ${s.tr ? `<span class="rtr">${esc(s.tr)}</span>` : ''}
    </div>`).join('');
  document.getElementById('rQs').innerHTML = p.qs.map((q,i) => `
    <div class="rq"><b>${i+1}.</b> ${esc(q.q)}${q.tr ? `<span class="rtr">${esc(q.tr)}</span>` : ''}</div>`)
    .join('')
    + (p.ch.length ? p.ch.map(c=>`<div class="rch">${esc(c)}</div>`).join('') : '');
  /* 本文命中的重点词：点一下朗读，按等级着色 */
  const LVN = {A:'基础高频', B:'核心必背', C:'进阶拓展'};
  document.getElementById('rWords').innerHTML =
    `<div class="rtit">本文重点词 ${p.w.length} 个（按等级排序，点词朗读；先读原文再背这些词，比孤立背词表记得牢）</div>
     <div class="wl">` + p.w.map(x => {
       const w = x[0], lv = x[1] || '';
       return `<span class="wc lv${lv}" data-act="rWord" data-w="${esc(w)}"
                 title="${LVN[lv] || ''}">${esc(w)}${
         PH[w] ? `<span class="p">/${esc(PH[w])}/</span>` : ''}</span>`;
     }).join('') + `</div>`;
  applyReadTrans();
}
function applyReadTrans(){
  document.body.classList.toggle('rshow-t', rShowT);
  const b = document.getElementById('rTrans');
  b.textContent = rShowT ? '隐藏译文' : '显示译文';
  b.classList.toggle('on', rShowT);
}
/* ---------- 学习报告 ----------
   三张图都不引第三方库：页面要能单文件离线跑，多一个 CDN 就多一个断网就白屏的理由。
   数据全部来自 localStorage：热力图看"有没有断"，曲线看"涨没涨"，柱状看"明天累不累"。 */
function lastDays(n){
  const out = [];
  for(let i = n - 1; i >= 0; i--) out.push(dayOffset(-i));
  return out;
}
function heatLevel(n){
  if(!n) return 0;
  if(n < 10) return 1;
  if(n < 20) return 2;
  if(n < 30) return 3;
  return 4;
}
function dayGap(dueStr){
  const a = new Date(TODAY + 'T00:00:00'), b = new Date(dueStr + 'T00:00:00');
  const d = Math.round((b - a) / 86400000);
  return isFinite(d) ? d : 0;
}
function renderReport(){
  const days = Object.keys(LOGS).filter(d => (LOGS[d] || {}).n > 0);
  const total = days.reduce((s, d) => s + (LOGS[d].n || 0), 0);
  document.getElementById('rpNums').innerHTML = [
    ['累计学习', days.length + ' 天'],
    ['累计词次', total + ' 次'],
    ['已掌握 / ' + cards.length, known.size],
    ['连续打卡', (streak.n || 0) + ' 天'],
  ].map(([k, v]) => `<div class="rpnum"><b>${v}</b><span>${k}</span></div>`).join('');

  /* 热力图：近 35 天，最后一格是今天。斜着看是"周几"，横着看是"哪一周"。 */
  const hs = lastDays(35);
  document.getElementById('rpHeat').innerHTML = hs.map(d => {
    const n = (LOGS[d] || {}).n || 0;
    return `<i class="hc l${heatLevel(n)}${d === TODAY ? ' today' : ''}"
      title="${d}：${n} 个词"></i>`;
  }).join('');
  document.getElementById('rpHeatSub').textContent =
    '近 35 天里学了 ' + hs.filter(d => (LOGS[d] || {}).n).length + ' 天';

  /* 掌握曲线：只连有记录的日期，别在没有数据的日子画成 0。
     pts 是日期字符串数组（不是对象），取值要再过一次 LOGS。 */
  const pts = lastDays(30).filter(d => LOGS[d] && typeof LOGS[d].m === 'number');
  const box = document.getElementById('rpCurve');
  if(pts.length < 2){
    box.innerHTML = '<div class="rpsub" style="margin:0">至少学两天才会出曲线——'
      + '现在的记录还不够。</div>';
  }else{
    const vals = pts.map(d => LOGS[d].m || 0);
    const max = Math.max(...vals, 1);
    const W = 300, H = 96, pad = 4;
    const xy = vals.map((m, i) => {
      const x = pad + i * (W - pad * 2) / (vals.length - 1);
      const y = H - pad - (m / max) * (H - pad * 2);
      return [x, y];
    });
    const line = xy.map(p => p[0].toFixed(1) + ',' + p[1].toFixed(1)).join(' ');
    const area = `${pad},${H} ${line} ${W - pad},${H}`;
    box.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
      <polygon points="${area}" fill="rgba(37,99,235,.10)"/>
      <polyline points="${line}" fill="none" stroke="#2563eb" stroke-width="2"
        stroke-linejoin="round" vector-effect="non-scaling-stroke"/>
      <circle cx="${xy[xy.length-1][0].toFixed(1)}" cy="${xy[xy.length-1][1].toFixed(1)}"
        r="3" fill="#2563eb"/>
    </svg>
    <div class="rpsub" style="margin:6px 0 0">${pts[0].slice(5)} 起 ${vals[0]} 个 → `
      + `今天 ${vals[vals.length-1]} 个</div>`;
  }

  /* 未来 7 天复习量：逾期的一律算到今天，否则"到期"会被藏起来 */
  const buckets = new Array(7).fill(0);
  Object.keys(srs).forEach(w => {
    const s = srs[w];
    if(!s || typeof s !== 'object' || !s.due) return;
    const idx = dayGap(s.due);
    if(idx <= 0) buckets[0] += 1;
    else if(idx < 7) buckets[idx] += 1;
  });
  const peak = Math.max(...buckets, 1);
  const wd = ['今天', '明天', '后天', '3 天', '4 天', '5 天', '6 天'];
  document.getElementById('rpBars').innerHTML = buckets.map((v, i) => `
    <div class="rb" title="${wd[i]}要复习 ${v} 个">
      <b>${v}</b>
      <i style="height:${Math.max(v / peak * 100, 2)}%"></i>
      <span>${wd[i]}</span>
    </div>`).join('');

  /* 等级分布：每个等级你掌握了多少 */
  const LV = [['A', '基础高频', 'la'], ['B', '核心必背', 'lb'], ['C', '进阶拓展', 'lc']];
  document.getElementById('rpLevel').innerHTML = LV.map(([L, name, cls]) => {
    const all = cards.filter(c => c.level === L).length;
    const got = cards.filter(c => c.level === L && known.has(c.word)).length;
    const pct = all ? (got / all * 100) : 0;
    return `<div class="lvbar ${cls}">
      <div class="t"><span>${name}</span><span>${got} / ${all}</span></div>
      <div class="g"><i style="width:${pct.toFixed(1)}%"></i></div>
    </div>`;
  }).join('');
}

function applyView(v){
  view = v;
  document.querySelectorAll('#viewSeg .seg-b').forEach(b=>b.classList.toggle('on', b.dataset.view === v));
  document.body.classList.toggle('view-quiz', v === 'quiz');
  document.body.classList.toggle('view-read', v === 'read');
  document.body.classList.toggle('view-report', v === 'report');
  if(v === 'quiz') startQuiz();
  else if(v === 'read') renderPassage();
  else if(v === 'report') renderReport();
  else render();
}
document.querySelectorAll('#viewSeg .seg-b').forEach(b=>b.addEventListener('click', ()=>applyView(b.dataset.view)));
document.getElementById('qOpts').addEventListener('click', e=>{
  const b = e.target.closest('.qopt'); if(b) answerQ(b);
});
document.getElementById('qNext').addEventListener('click', nextQ);
document.getElementById('qRebuild').addEventListener('click', startQuiz);
document.getElementById('qPeek').addEventListener('click', ()=>{
  document.getElementById('qTrans').classList.toggle('t-on');
});
/* 精读：点句子旁的喇叭读整句，点词卡读单个词 */
document.getElementById('readPanel').addEventListener('click', e=>{
  const b = e.target.closest('[data-act]'); if(!b) return;
  if(b.dataset.act === 'rSay') TTS.say(b.dataset.t);
  else if(b.dataset.act === 'rWord') TTS.say(b.dataset.w);
});
document.getElementById('rTrans').addEventListener('click', ()=>{
  rShowT = !rShowT; applyReadTrans();
});
/* 推荐下一篇：按「生词密度从少到多」排成一条路线，点一次走一篇。
   为什么不是"每次找最接近 4% 的那篇"：那样会一直在最容易的篇和当前篇之间来回弹
   （点一下跳到最容易的，再点又跳回来）。排成固定的升级路线才走得下去。
   两个过滤条件：n == 0 的块只有题干没有正文；n < 80 的块（选词填空八九个词）
   密度会被一两个词带偏——8 个词错 2 个就是 25%，比 188 词的正经文章还"难"。 */
const RECO_MIN_N = 80;
function recoOrder(){
  return PASSES.map((p, i) => ({i, d: passLoad(p).density, n: p.n || 0}))
    .filter(x => x.n >= RECO_MIN_N)
    .sort((a, b) => (a.d - b.d) || (a.i - b.i));
}
document.getElementById('rNext').addEventListener('click', ()=>{
  const order = recoOrder();
  if(!order.length) return;
  const pos = order.findIndex(x => x.i === rIdx);
  const nxt = pos < 0 ? order[0] : order[(pos + 1) % order.length];
  rIdx = nxt.i;
  document.getElementById('passage').value = nxt.i;
  renderPassage();
  window.scrollTo({top: 0, behavior: 'smooth'});
});
initPassagePicker();
/* 拼写：回车判定。用事件委托而不是给每个输入框挂监听，
   因为 render() 会整页重建 DOM，挂上去的监听跟着一起没了 */
document.getElementById('list').addEventListener('keydown', e=>{
  if(e.key !== 'Enter') return;
  const box = e.target.closest('.spellbox'); if(!box) return;
  e.preventDefault();
  const w = box.dataset.w, inp = box.querySelector('input'), msg = box.querySelector('.spellmsg');
  const val = (inp.value || '').trim().toLowerCase();
  if(!val) return;
  const right = val === w.toLowerCase();
  box.classList.remove('ok','bad');
  box.classList.add(right ? 'ok' : 'bad');
  msg.className = 'spellmsg ' + (right ? 'ok' : 'bad');
  grade(w, right ? 2 : 0, false);          /* 不能在这里 render()，输入框会被冲掉 */
  if(right){
    msg.innerHTML = '正确 ✓';
    const cur = box;
    setTimeout(()=>{ render();
      const boxes = [...document.querySelectorAll('.spellbox')];
      const nx = boxes[boxes.indexOf(cur) + 1] || boxes[0];
      if(nx) nx.querySelector('input').focus();
    }, 450);
  }else{
    msg.innerHTML = '不对，正确拼写是 <b>' + esc(w) + '</b>，已记成「不会」';
    setTimeout(render, 2600);              /* 留两秒半让人看清错在哪 */
  }
});
/* 打印前必须先把筛选结果整份摊到 DOM 里。
   列表是分页渲染的，屏幕上只有 40 张卡，直接 print 的话
   1272 个词只能印出前 40 个 —— 这是"点打印却只出一小撮"的根因。
   精读视图印的是整篇文章，不走这条路。 */
let printed = false;
function prepPrint(){
  if(printed || view === 'read') return;
  printed = true;
  const list = sorted(cards.filter(match));
  document.getElementById('list').innerHTML =
    list.length ? list.map(cardHTML).join('') : emptyHTML();
  document.getElementById('more').style.display = 'none';
}
function postPrint(){
  if(!printed) return;
  printed = false;
  render();          /* 打完把分页恢复回去，不然 1272 张卡一直挂在页面上 */
}
window.addEventListener('beforeprint', prepPrint);
window.addEventListener('afterprint', postPrint);
document.getElementById('print').addEventListener('click', () => {
  prepPrint();
  window.print();
});
document.querySelectorAll('.chip[data-lv]').forEach(c=>c.addEventListener('click',()=>{c.classList.toggle('on');page=1;render();}));
/* 翻页状态下切换筛选必须回到第 1 页：否则在第 3 页点「只看未掌握」，
   筛选后只剩 5 个词，却还按第 3 页去切，页面上直接空白，看着像坏了。
   其它筛选器都是重置的，这里原来漏了。 */
document.getElementById('hideKnown').addEventListener('click',function(){
  hideKnown=!hideKnown;this.classList.toggle('on');page=1;render();});
document.getElementById('favChip').addEventListener('click', toggleFavFilter);
document.getElementById('todayChip').addEventListener('click', function(){
  todayMode = !todayMode; page = 1; render();
});
document.querySelectorAll('#dirSeg .seg-b').forEach(b=>b.addEventListener('click', ()=>applyDir(b.dataset.dir)));
document.getElementById('histRow').addEventListener('click', e=>{
  if(e.target.closest('[data-act2="clrHist"]')){
    if(!confirm('清空全部搜索历史？此操作无法撤销。')) return;
    hist = []; localStorage.removeItem(HKEY); renderHist(); return;
  }
  const del = e.target.closest('[data-del]');
  if(del){ hist.splice(+del.dataset.del, 1); saveJSON(HKEY, hist); renderHist(); return; }
  const it = e.target.closest('.hitem');
  if(it){
    const h = hist[+it.dataset.i]; if(!h) return;
    qEl.value = h.t;
    applyDir(h.m);   /* 连当时用的方向一起恢复，省得再切一次 */
  }
});
/* 键盘快捷键：手不离键盘也能搜 */
document.addEventListener('keydown', e=>{
  const t = (e.target.tagName || '').toLowerCase();
  const typing = t === 'input' || t === 'select' || t === 'textarea';
  if((e.key === '/' && !typing) || ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K'))){
    e.preventDefault(); qEl.focus(); qEl.select(); return;
  }
  if(e.key === 'Escape'){
    if(document.activeElement === qEl){ if(qEl.value){ qEl.value = ''; page = 1; render(); } else qEl.blur(); }
    return;
  }
  if(e.altKey && e.code === 'KeyR'){ e.preventDefault(); applyDir(dir === 'fwd' ? 'rev' : 'fwd'); return; }
  if(e.altKey && e.code === 'KeyF'){ e.preventDefault(); toggleFavFilter(); return; }
  if(e.altKey && e.code === 'KeyS'){ e.preventDefault(); sayFirstVisible(); return; }
  if(e.altKey && e.code === 'Digit1'){ e.preventDefault(); cycleRate(); return; }
  if(e.altKey && e.code === 'KeyD'){ e.preventDefault();
    onlyDue = !onlyDue; document.getElementById('dueChip').classList.toggle('on', onlyDue);
    page = 1; render(); return; }
});
document.getElementById('more').addEventListener('click', wantMore);
document.getElementById('mMore').addEventListener('click', wantMore);
document.getElementById('showTrans').addEventListener('change',function(){
  document.body.classList.toggle('show-t', this.checked);
  document.getElementById('eyeBtn').classList.toggle('on', this.checked);
  document.getElementById('eyeTxt').textContent = this.checked?'隐藏译文':'显示译文';
});
document.getElementById('blurBtn').addEventListener('click',function(){quiz=!quiz;this.textContent='自测模式：'+(quiz?'开':'关');render();});
document.getElementById('mQuiz').addEventListener('click',()=>document.getElementById('blurBtn').click());
document.getElementById('mKnown').addEventListener('click',()=>document.getElementById('hideKnown').click());
document.getElementById('mDue').addEventListener('click',()=>document.getElementById('dueChip').click());
/* 语速档位：常速→慢速→很慢。跟读和听写时 0.5 倍速比调节系统音量有用得多 */
function cycleRate(){
  TTS.cycle();
  document.getElementById('rate').textContent = '语速：' + TTS.label;
}
document.getElementById('rate').addEventListener('click', cycleRate);
document.getElementById('rate').textContent = '语速：' + TTS.label;
function doExport(){
  const list = sorted(cards.filter(match));
  /* 分列导出，方便在 Anki 里自己搭模板；Python 端的 Anki导入包.csv 保持
     三列开箱即用，两者用途不同 */
  const rows = [['word','phonetic','pos','senses','sentence','trans','source','level']];
  list.forEach(c=>{
    const e = c.examples[0]||{};
    rows.push([c.word, c.phonetic?('/'+c.phonetic+'/'):'', c.pos, c.senses.join('；'),
      (e.sentence||'').replace(/\[\[|\]\]/g,''), (e.trans||'').replace(/\[\[|\]\]/g,''),
      `${e.year||''} ${e.set||''} ${e.section||''} ${e.title||''}`.trim(), c.levelName]);
  });
  const csv = rows.map(r=>r.map(v=>`"${String(v).replace(/"/g,'""')}"`).join(',')).join('\r\n');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob(['\ufeff'+csv],{type:'text/csv;charset=utf-8'}));
  a.download = 'CET4_Anki_词表.csv'; a.click();
}
document.getElementById('export').addEventListener('click', doExport);
document.getElementById('mExport').addEventListener('click', doExport);
function doReset(){
  if(!confirm('确定清空全部学习记录（三档自评与复习计划一起清）？此操作无法撤销。')) return;
  /* srs 必须一起清：只清 known 的话，卡片上"会/模糊/不会"的档位和
     今日复习队列都还在，点了重置却像没生效 */
  known.clear(); srs = {}; revealed.clear();
  localStorage.removeItem(KEY); localStorage.removeItem(SKEY);
  render();
}
document.getElementById('reset').addEventListener('click', doReset);
document.getElementById('mReset').addEventListener('click', doReset);
render();
/* 记下今天打开过。要在 render 之后写：render 里用的 gapDays 是加载时算的旧值，
   先写就把"上次是几天前"覆盖成 0 了，断签提醒永远不出现。 */
markOpened();
/* 断网也能背：注册 service worker 把本页缓存下来（地铁里刷单词就靠它）。
   只在 http(s) 下注册——file:// 没有 secure context，注册必然失败；
   失败也不抛给上层，本地双击打开的行为跟以前完全一样。 */
if('serviceWorker' in navigator && /^https?:/.test(location.protocol)){
  addEventListener('load', function(){
    navigator.serviceWorker.register('sw.js')['catch'](function(){});
  });
}

/* 手机上滚到列表底部自动加载下一页，省得每次去点按钮 */
if('IntersectionObserver' in window){
  const sentinel = document.getElementById('more');
  new IntersectionObserver(es=>{
    es.forEach(e=>{ if(e.isIntersecting && e.target.style.display!=='none') wantMore(); });
  }, {rootMargin:'400px'}).observe(sentinel);
}
/* 屏幕旋转时每页数量会变（手机 15 / 桌面 40），需要重排。
   判据用「窄屏状态是否改变」，不能判 page>1 —— 首次加载 page 就是 1，
   那样手机上会一直沿用桌面每页 40 张。 */
let rt, wasNarrow = isNarrow();
window.addEventListener('resize',()=>{
  clearTimeout(rt);
  rt = setTimeout(()=>{
    const now = isNarrow();
    if(now !== wasNarrow){ wasNarrow = now; page = 1; render(); }
  }, 200);
});
</script>

<!-- 剩余词条与精读原文：继续流式 push，下完再补一次渲染 -->
<script>
__DATA_REST__
</script>
</body>
</html>"""
    html = (tpl.replace("__DATA_HEAD__", data_head)
               .replace("__DATA_FIRST__", data_first)
               .replace("__DATA_REST__", data_rest))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path


def build_landing(cards, blocks, out_path, href_main="output/index.html",
                  href_md="output/真题词汇表_按年份题型.md",
                  href_anki="output/Anki导入包.csv", coverage=None):
    """生成项目根目录的入口页。

    这个页面原来是一份手写 HTML，里面的「1016 个重点词 / 2431 条真题原句」
    是写死的数字。词库一路加到 1550 词之后没人再回来改它，于是线上首页
    长期比实际构建结果少 534 个词 —— 首页数字只能由构建生成，手写必错。
    """
    s = _stats(cards, blocks, coverage)
    years = s["years"]
    span = f"{years[0]} ~ {years[-1]}" if years else "—"
    n_real, n_sim = s["exampleReal"], s["exampleSim"]
    src_line = (f"真题片段 {s['blockReal']} 块、仿真语料 {s['blockSim']} 块"
                if s["blockSim"] else f"全部为真题片段，共 {s['blockReal']} 块")
    stamp = time.strftime("%Y-%m-%d %H:%M")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#2563eb">
<title>CET-4 真题词汇本</title>
<style>
:root{{--bg:#f5f6f8;--panel:#fff;--line:#e5e7eb;--ink:#1f2328;--ink2:#4b5563;
  --ink3:#8b95a3;--brand:#2563eb;--soft:#eff4ff}}
*{{box-sizing:border-box;-webkit-tap-highlight-color:transparent}}
html{{-webkit-text-size-adjust:100%}}
body{{margin:0;background:var(--bg);color:var(--ink);
  font:15px/1.7 -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif;
  display:flex;align-items:center;justify-content:center;min-height:100vh;padding:20px}}
.box{{background:var(--panel);border:1px solid var(--line);border-radius:16px;
  max-width:520px;width:100%;padding:30px 26px;box-shadow:0 1px 2px rgba(16,24,40,.05),0 8px 28px rgba(16,24,40,.07)}}
h1{{margin:0 0 8px;font-size:22px;letter-spacing:.3px}}
.sub{{color:var(--ink2);font-size:13.5px;margin-bottom:20px}}
ul{{margin:0 0 22px;padding-left:20px;color:var(--ink2);font-size:13.5px}}
li{{margin:5px 0}}
li b{{color:var(--ink)}}
a.go{{display:block;text-align:center;background:var(--brand);color:#fff;text-decoration:none;
  border-radius:11px;padding:15px;font-size:15.5px;font-weight:600;margin-bottom:10px}}
a.go:active{{opacity:.85}}
.links{{display:flex;gap:8px;flex-wrap:wrap}}
.links a{{flex:1 1 auto;text-align:center;border:1px solid var(--line);border-radius:9px;
  padding:10px 12px;font-size:12.5px;color:var(--ink2);text-decoration:none;white-space:nowrap}}
.links a:active{{border-color:var(--brand);color:var(--brand)}}
.tip{{margin-top:18px;font-size:12px;color:var(--ink3);line-height:1.6;
  border-top:1px solid var(--line);padding-top:14px}}
.tip b{{color:#92400e}}
@media (prefers-color-scheme:dark){{
  :root{{--bg:#15171a;--panel:#1d2024;--line:#2c3035;--ink:#e8eaed;--ink2:#a8afb8;
    --ink3:#7d848d;--brand:#5b8def;--soft:#1e2836}}
  .links a{{border-color:#2c3035}}
}}
</style>
</head>
<body>
<div class="box">
  <h1>CET-4 历年真题重点词</h1>
  <div class="sub">结合题目背单词 · 每个词配真题原句与中文译文</div>
  <ul>
    <li><b>{s['wordCount']}</b> 个重点词，<b>{n_real + n_sim}</b> 条例句
      （真题 <b>{n_real}</b> + 仿真 {n_sim}）</li>
    <li>覆盖 <b>{span}</b>，{len(years)} 个场次、{s['blockCount']} 个题型块</li>
    <li>背完能读懂真题正文 <b>{s['coverage']}%</b> 的实词
      （{s['bodyHitContent']} / {s['bodyContent']} 个词次，已去掉 the / a / of 这类功能词）</li>
    <li>标注<b>词性、常考义、年份套次题型出处</b>，并给出此处语境词性</li>
    <li>每个词有<b>易混词提醒</b>、每日 <b>30 词</b>计划，精读按你的水平标出<b>生词密度</b></li>
    <li>默认隐藏释义与译文，<b>点击自测</b>；手机端已适配，可直接加到主屏</li>
  </ul>
  <a class="go" href="{href_main}">开始背单词 →</a>
  <div class="links">
    <a href="{href_md}">按年份题型词表</a>
    <a href="{href_anki}">Anki 导入包</a>
  </div>
  <div class="tip">
    <b>关于「真题」二字</b>：{src_line}。2021-06 ~ 2024-06 是按真题题材与难度
    人工撰写的仿真语料，用于补足样本，它的出现次数不等于考场频次；
    学习页里每条例句都标了来源。详情见仓库内 <code>data/2025-2026来源说明.md</code>。
    <br>生成于 {stamp}。
  </div>
</div>
</body>
</html>
"""
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path


def build_pwa(out_dir, version=""):
    """生成 manifest / service worker / 图标，让「添加到主屏幕」真的能离线用。

    为什么值得单独做：README 一直写着"添加到主屏幕，像 App 一样用"，
    但没有 manifest 和 service worker，断网打开就是白屏。
    这个页面本来就是 3.8MB 单文件、不需要任何后端，缓存下来才是它该有的样子。

    缓存名带版本号：每构建一次换一个，否则浏览器会一直用旧的 index.html。
    """
    ver = re.sub(r"[^0-9A-Za-z]", "", version or time.strftime("%Y%m%d%H%M"))

    manifest = {
        "name": "CET-4 真题词汇本",
        "short_name": "四级词汇",
        "description": "结合真题原句背单词：词卡、拼写、听写、精读与做题",
        "start_url": "./index.html",
        "scope": "./",
        "display": "standalone",
        "background_color": "#f5f6f8",
        "theme_color": "#2563eb",
        "lang": "zh-CN",
        "icons": [
            {"src": "icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any"},
        ],
    }
    p1 = os.path.join(out_dir, "manifest.webmanifest")
    with open(p1, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    # 图标用 SVG：不用为了几个尺寸引 Pillow，主屏图标本来就是缩略显示
    svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 192 192">
  <rect width="192" height="192" rx="42" fill="#2563eb"/>
  <text x="96" y="132" font-size="104" font-family="PingFang SC,Microsoft YaHei,sans-serif"
        font-weight="700" fill="#fff" text-anchor="middle">词</text>
</svg>
"""
    p2 = os.path.join(out_dir, "icon.svg")
    with open(p2, "w", encoding="utf-8") as f:
        f.write(svg)

    # 导航请求走网络优先（重新构建后能立刻拿到新版），失败再回落到缓存
    sw = """/* 由 core/exporters.py 的 build_pwa() 生成，不要手改。
   策略：
   · 导航请求网络优先 —— 重新构建后打开就是新版，断网才用缓存；
   · 其它同源 GET 缓存优先 —— 单文件页面本来就没有外部依赖。 */
const CACHE = 'cet4-%s';
const CORE = ['./index.html', './manifest.webmanifest', './icon.svg'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(CORE)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys()
    .then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET' || new URL(req.url).origin !== location.origin) return;
  if (req.mode === 'navigate') {
    e.respondWith(fetch(req).then(res => {
      const cp = res.clone();
      caches.open(CACHE).then(c => c.put(req, cp));
      return res;
    }).catch(() => caches.match('./index.html')));
    return;
  }
  e.respondWith(caches.match(req).then(hit => hit || fetch(req).then(res => {
    const cp = res.clone();
    caches.open(CACHE).then(c => c.put(req, cp));
    return res;
  })));
});
""" % ver
    p3 = os.path.join(out_dir, "sw.js")
    with open(p3, "w", encoding="utf-8") as f:
        f.write(sw)
    return [p1, p2, p3]


def build_markdown(cards, blocks, out_path):
    """按年份 → 题型 → 词条整理成 Markdown 文档。"""
    grouped = defaultdict(lambda: defaultdict(list))
    for c in cards:
        for o in c.occurrences:
            grouped[o.year][o.section].append((c, o))
    lines = ["# CET-4 历年真题重点词汇表", "",
             f"> 共 {len(cards)} 个重点词，"
             f"{sum(1 for c in cards for o in c.occurrences if getattr(o, 'source', 'real') != 'sim')} "
             f"条真题原句 + "
             f"{sum(1 for c in cards for o in c.occurrences if getattr(o, 'source', 'real') == 'sim')} "
             f"条仿真例句。",
             "> **来源说明**：2021-06 ~ 2024-06 的语料是按真题题材与难度人工撰写的仿真语料，"
             "标「仿真」；2025-06 起为可在公开来源核实的真题片段。仿真句只能用来熟悉语境，"
             "不能当作考场频次。",
             "> 等级：A 基础高频 / B 核心必背 / C 进阶拓展；带 ★ 者为四级常考义。", ""]
    for year in sorted(grouped, key=year_key, reverse=True):
        lines.append(f"\n## {year}\n")
        secs = grouped[year]
        for sec in sorted(secs, key=lambda s: ["仔细阅读", "选词填空", "长篇阅读",
                                               "听力", "翻译", "写作"].index(s)
                          if s in ["仔细阅读", "选词填空", "长篇阅读",
                                   "听力", "翻译", "写作"] else 9):
            items = secs[sec]
            seen, uniq = set(), []
            for c, o in items:
                if c.word not in seen:
                    seen.add(c.word)
                    uniq.append((c, o))
            lines.append(f"\n### {sec}（{len(uniq)} 词）\n")
            lines.append("| 单词 | 音标 | 词性 | 释义 | 真题原句 | 原句译文 | 出处 |")
            lines.append("|---|---|---|---|---|---|---|")
            for c, o in uniq:
                senses = "；".join(c.entry.senses_display())
                sent = o.sentence.replace("[[", "").replace("]]", "").replace("|", "/")
                trans = (o.trans or "—").replace("|", "/")
                ph = f"/{c.entry.phonetic}/" if getattr(c.entry, "phonetic", "") else "—"
                src = f"{o.year} {o.set} · {o.title}"
                if getattr(o, "source", "real") != "real":
                    src += "（仿真）"
                lines.append(f"| **{c.word}** | {ph} | {c.entry.pos} | {senses} | "
                             f"{sent} | {trans} | {src} |")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return out_path


def build_csv(cards, out_path):
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["单词", "音标", "词性", "释义", "等级", "真题原句", "原句译文", "上文", "下文",
                    "题目情境", "原题", "原题译文", "年份", "套次", "题型", "篇目", "出现次数",
                    "来源"])
        for c in cards:
            ph = f"/{c.entry.phonetic}/" if getattr(c.entry, "phonetic", "") else ""
            for o in c.occurrences:
                q, qi = o.related_question()
                qts = getattr(o.block, "qtrans", []) or []
                w.writerow([
                    c.word, ph, c.entry.pos, "；".join(c.entry.senses_display()),
                    f"{c.entry.level} {LEVEL_NAME.get(c.entry.level, '')}".strip(),
                    o.sentence.replace("[[", "").replace("]]", ""), o.trans,
                    o.prev, o.next, o.topic, q,
                    qts[qi] if 0 <= qi < len(qts) else "",
                    o.year, o.set, o.section, o.title, c.count,
                    {"real": "真题", "sim": "仿真"}.get(getattr(o, "source", "real"), "导入")])
    return out_path


def build_anki(cards, out_path):
    """Anki 导入用：正面=单词+音标+真题句，背面=词性+释义+出处。

    正面加音标是有意的：单词卡先自己读一遍再翻面，音标就在眼前，
    比翻到背面才看到更利于建立"拼写↔读音"的联结。
    """
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        for c in cards:
            o = c.occurrences[0] if c.occurrences else None
            ph = f"/{c.entry.phonetic}/" if getattr(c.entry, "phonetic", "") else ""
            front = c.word + (f"<br><span style='font-size:13px;color:#666'>{ph}</span>" if ph else "")
            back = " / ".join(c.entry.senses_display())
            if o:
                sent = o.sentence.replace("[[", "").replace("]]", "")
                # 大小写不敏感地给首次出现的词形加粗：句首的 Because 和
                # 词形 because 不是同一个字符串，直接 replace 会漏
                sent = re.sub(re.escape(o.form), lambda m: f"<b>{m.group(0)}</b>",
                              sent, count=1, flags=re.I)
                front = (f"{c.word}<br><span style='font-size:13px;color:#666'>{ph}</span>"
                         if ph else c.word) + \
                        f"<br><span style='font-size:14px'>{sent}</span>"
                back = (f"{c.entry.pos} {back}<br>{o.trans or ''}<br><i>{o.year} {o.set} · "
                        f"{o.section} · {o.title}"
                        + ("（仿真句，非考场原文）" if getattr(o, "source", "real") == "sim" else "")
                        + f"</i>"
                        + (f"<br>{c.entry.note}" if c.entry.note else ""))
            w.writerow([front, back, c.entry.level])
    return out_path


def _unknown_sorted(unknown, top=None):
    """未收录词排序：先看正文句里出现过几次，再看总次数。

    只在题干/选项里出现过的词多半是套话或选项里的干扰词，
    补进词库的价值比正文里真出现的词低，所以 b 排在 n 前面。

    top=None 表示不截断。工作台必须传 None：语料里正文出现过的未收录词
    有 678 个，截前 300 的话这 300 个全是 b>=1 的词，页面上
    「只在题干/选项出现过」这一档永远筛不出东西，等于给了个死开关。
    """
    items = [(w, d) for w, d in unknown.items()
             if w and not w.endswith("'s") and not w.endswith("'")]
    items.sort(key=lambda kv: (-kv[1].get("b", 0), -kv[1].get("n", 0), kv[0]))
    return items if top is None else items[:top]


def build_unknown(unknown, out_path, top=300):
    """未收录高频词清单（纯文本，给人快速浏览）。

    unknown 的值是 {"n": 总次数, "b": 正文句次数, "s": [最多两条正文例句]}。
    """
    items = _unknown_sorted(unknown, top)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("# 语料高频但未收录进词库的词\n")
        f.write("# 格式：单词 <Tab> 正文次数 <Tab> 总次数。可补充到 data/lexicon/ 下的任意 .txt\n")
        f.write("# 已滤掉功能词与题干套话（见 data/stopwords.txt）\n")
        f.write("# 带例句的完整工作台见 output/未收录词工作台.html\n\n")
        for w, d in items:
            f.write(f"{w}\t{d.get('b', 0)}\t{d.get('n', 0)}\n")
    return out_path, len(items)


def build_unknown_workbench(unknown, out_path, top=None):
    """未收录词工作台：带例句的单文件页，边看语境边把词库补齐。

    为什么单独出一个页面而不是塞进主页面：这份清单是"维护工具"，
    给的是加词库的人（可能是自己，也可能是想扩词表的人），
    和使用者每天刷词的场景完全不同，混在一起只会互相干扰。
    而且它不随词卡重新生成而变化，体量很小。
    """
    items = _unknown_sorted(unknown, top)
    payload = [{"w": w, "n": d.get("n", 0), "b": d.get("b", 0), "s": d.get("s", [])}
               for w, d in items]
    data_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")

    tpl = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>未收录词工作台 · CET-4 词库补全</title>
<style>
:root{--bg:#f5f6f8;--panel:#fff;--line:#e5e7eb;--ink:#1f2328;--ink2:#4b5563;
  --ink3:#8b95a3;--brand:#2563eb;--soft:#eff4ff;--ok:#15803d;--okbg:#e8f6ec}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:14px/1.7 -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif}
.wrap{max-width:900px;margin:0 auto;padding:24px 18px 60px}
h1{font-size:19px;margin:0 0 6px}
.sub{color:var(--ink2);font-size:13px;margin-bottom:16px}
.bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:14px}
input[type=text]{border:1px solid var(--line);border-radius:8px;padding:7px 10px;
  font-size:13px;font-family:inherit;outline:none;min-width:200px}
select{border:1px solid var(--line);border-radius:8px;padding:7px 10px;font-size:13px;font-family:inherit}
.btn{border:1px solid var(--line);background:#fff;border-radius:8px;padding:7px 12px;
  font-size:12.5px;cursor:pointer;font-family:inherit;color:var(--ink2)}
.btn:hover{border-color:#c7d2e8;color:var(--ink)}
.btn.ok{background:var(--ok);border-color:var(--ok);color:#fff}
.row{background:var(--panel);border:1px solid var(--line);border-radius:12px;
  padding:12px 14px;margin-bottom:10px}
.hd{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin-bottom:6px}
.w{font-size:17px;font-weight:700}
.n{font-size:12px;color:var(--ink3)}
.tag{font-size:11px;color:#92400e;background:#fff8ed;border:1px solid #fde3b8;
  border-radius:5px;padding:1px 6px}
.code{font-family:Consolas,"Courier New",monospace;font-size:12.5px;background:#f6f8fa;
  border:1px solid var(--line);border-radius:6px;padding:6px 9px;margin:6px 0 0;
  white-space:pre-wrap;word-break:break-all;color:#0f172a}
.ex{font-size:12.5px;color:var(--ink2);margin:5px 0 0;padding-left:10px;
  border-left:2px solid var(--line)}
mark{background:#fff2b8;padding:0 2px;border-radius:3px}
.tip{font-size:12px;color:var(--ink3);margin-top:18px;line-height:1.8}
.done{opacity:.45}
@media print{.bar,.btn{display:none}}
</style>
</head>
<body>
<div class="wrap">
  <h1>未收录词工作台</h1>
  <div class="sub">这些词在真题语料里出现过，但词库没收。看语境把义项填好，粘进
    <code>data/lexicon/</code> 下任意 .txt 即可。</div>
  <div class="bar">
    <input type="text" id="q" placeholder="筛选单词…" autocomplete="off">
    <select id="sort">
      <option value="freq">按正文出现次数</option>
      <option value="alpha">按字母顺序</option>
    </select>
    <select id="src">
      <option value="">全部来源</option>
      <option value="body">只在正文出现过</option>
      <option value="qonly">只在题干/选项出现过</option>
    </select>
    <button class="btn" id="copyAll">复制全部待填行</button>
    <span class="n" id="cnt"></span>
  </div>
  <div id="list"></div>
  <div class="tip">
    词库格式：<code>单词|词性|义项(分号分隔，带*者为常考义)|等级(A基础/B核心/C进阶)|搭配提示</code><br>
    填好放回 <code>data/lexicon/</code> 后重跑 <code>python run.py</code>，这些词就会进词表。<br>
    出现次数分两个数：<b>正文</b>指真题原文里出现过几次（更有参考价值），
    <b>总次数</b>还包含题干和选项。只在题干/选项里出现的词多半是套话或干扰词，
    补词库前先看一眼它的例句。<br>
    功能词与题干套话已由 <code>data/stopwords.txt</code> 过滤掉了。
  </div>
</div>
<script>
const DATA = __DATA__;
const esc = s => (s||'').replace(/[&<>]/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[m]));
const resc = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const hl = s => esc(s).replace(/\[\[(.*?)\]\]/g, '<mark>$1</mark>');
/* 例句里要把这个待补的词标出来。原样只跑一遍 [[ ]] 替换，
   而这些句子从来没被高亮过（未收录词自然不会有高亮标记），
   结果"边看语境边补词"的语境里根本看不出词在哪。 */
function hlWord(s, w){
  const t = hl(s);
  if(!w) return t;
  try{
    return t.replace(new RegExp('\\b(' + resc(w) + ')', 'gi'), '<mark>$1</mark>');
  }catch(e){ return t; }
}
function lineOf(w){ return w + '||待填释义|B|'; }
/* 筛选条件只有一份：原来 render 和「复制全部」各抄了一遍，
   改一处漏一处就会出现"页面上看到的和复制出来的不是一批词" */
function filtered(){
  const kw = document.getElementById('q').value.trim().toLowerCase();
  const by = document.getElementById('sort').value;
  const src = document.getElementById('src').value;
  const list = DATA.filter(d => {
    if(kw && !d.w.includes(kw)) return false;
    if(src === 'body' && !(d.b > 0)) return false;
    if(src === 'qonly' && d.b > 0) return false;
    return true;
  });
  return list.slice().sort(by === 'alpha'
    ? (a,b) => a.w.localeCompare(b.w)
    : (a,b) => b.b - a.b || b.n - a.n || a.w.localeCompare(b.w));
}
function render(){
  const list = filtered();
  document.getElementById('cnt').textContent = '共 ' + list.length + ' 个';
  document.getElementById('list').innerHTML = list.map(d => `
    <div class="row" data-w="${esc(d.w)}">
      <div class="hd"><span class="w">${esc(d.w)}</span>
        <span class="n">正文 ${d.b} 次 · 总计 ${d.n} 次</span>
        ${d.b === 0 ? '<span class="tag">仅在题干/选项</span>' : ''}
        <span style="flex:1"></span>
        <button class="btn" data-copy="${esc(d.w)}">复制这一行</button></div>
      ${d.s.length ? d.s.map(x=>`<div class="ex">${hlWord(x, d.w)}</div>`).join('') : '<div class="ex">（没有正文例句，只在题干或选项里出现过）</div>'}
      <div class="code">${esc(lineOf(d.w))}</div>
    </div>`).join('') || '<div class="row">没有匹配的词</div>';
}
function copy(text, btn){
  const done = () => {
    if(!btn) return;
    const old = btn.textContent;
    btn.textContent = '已复制'; btn.classList.add('ok');
    setTimeout(()=>{ btn.textContent = old; btn.classList.remove('ok'); }, 1200);
  };
  if(navigator.clipboard && navigator.clipboard.writeText){
    navigator.clipboard.writeText(text).then(done, () => fallback(text, done));
  }else fallback(text, done);
}
function fallback(text, done){
  const ta = document.createElement('textarea');
  ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
  document.body.appendChild(ta); ta.select();
  try{ document.execCommand('copy'); done(); }catch(e){ alert('复制失败，请手动选择文本'); }
  document.body.removeChild(ta);
}
document.getElementById('list').addEventListener('click', e => {
  const b = e.target.closest('[data-copy]');
  if(b) copy(lineOf(b.dataset.copy), b);
});
document.getElementById('q').addEventListener('input', render);
document.getElementById('sort').addEventListener('change', render);
document.getElementById('src').addEventListener('change', render);
document.getElementById('copyAll').addEventListener('click', function(){
  copy(filtered().map(d => lineOf(d.w)).join('\n'), this);
});
render();
</script>
</body>
</html>"""
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(tpl.replace("__DATA__", data_json))
    return out_path
