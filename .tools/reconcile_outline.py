# -*- coding: utf-8 -*-
"""词库 × 大纲词表 对账。

目的不是"把大纲 4427 个词全塞进词库"——本项目是真题驱动的，语料里没出现过的词
收了也不会生成卡片。真正要回答的是三个问题：

  1. 语料里出现过、大纲也要求掌握、词库却没收录的词有哪些？  ← 这才是漏网，必须补
  2. 词库收了的词里，哪些其实不在大纲内？                    ← 判断是否超纲，决定等级
  3. A 级（基础高频）到底是不是"高频"？                      ← 等级分层是否还有意义

用法：
    python .tools/reconcile_outline.py            # 打印并写 output/词库对账报告.md
    python .tools/reconcile_outline.py --top 40   # 每张表列多少条
"""
import argparse
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core import corpus, extractor          # noqa: E402
from core.lexicon import Lexicon            # noqa: E402

DIR_LEX = os.path.join(BASE, "data", "lexicon")
DIR_CORPUS = os.path.join(BASE, "data", "corpus")
DIR_TRANS = os.path.join(BASE, "data", "translation")
DIR_IMPORT = os.path.join(BASE, "data", "import")
FILE_STOP = os.path.join(BASE, "data", "stopwords.txt")
FILE_OUTLINE = os.path.join(BASE, "data", "reference", "cet4_outline.txt")
OUT_MD = os.path.join(BASE, "output", "词库对账报告.md")


def load_outline(path):
    """读参考词表。返回 {单词: 原始释义}。"""
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "|" not in line:
                continue
            w, tr = line.split("|", 1)
            w = w.strip().lower()
            if w:
                out[w] = tr.strip()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=25)
    args = ap.parse_args()

    lex = Lexicon.load(DIR_LEX)
    blocks = corpus.load_corpus(DIR_CORPUS) + corpus.load_imports(DIR_IMPORT)
    corpus.load_translations(DIR_TRANS, blocks)
    stop = extractor.load_stopwords(FILE_STOP)
    cards, unknown, _ = extractor.extract(lex, blocks, stopwords=stop)

    outline = load_outline(FILE_OUTLINE)
    if not outline:
        print("没有找到 data/reference/cet4_outline.txt，先跑一次词表导入。")
        return 1

    lex_words = set(lex.entries)
    lex_solo = {w for w in lex_words if " " not in w}

    # ① 语料里出现过、大纲要求、词库没有 → 真正的漏网
    gap = [(w, v) for w, v in unknown.items() if w in outline and len(w) >= 3]
    gap.sort(key=lambda kv: (-kv[1]["b"], -kv[1]["n"], kv[0]))

    # ② 词库有、大纲无 → 超纲或专有名词
    beyond = sorted((w for w in lex_solo if w not in outline),
                    key=lambda w: -cards[w].count if w in cards else 0)
    beyond_hit = [(w, cards[w].count) for w in beyond if w in cards]

    # ③ A 级是不是真高频
    lv = {}
    for c in cards.values():
        lv.setdefault(c.entry.level, []).append(c.count)
    lv_stat = {k: (len(v), sum(1 for x in v if x >= 3), sum(1 for x in v if x == 1))
               for k, v in lv.items()}

    covered = len(lex_solo & set(outline))
    print(f"词库 {len(lex_solo)} 词（单词型） | 大纲参考 {len(outline)} 词 | 交集 {covered}")
    print(f"漏网（语料出现过 + 大纲内 + 词库未收）：{len(gap)}")
    print(f"超纲（词库有、大纲无）：{len(beyond)}，其中在语料里出现过的 {len(beyond_hit)}")
    for k in "ABC":
        if k in lv_stat:
            n, hi, once = lv_stat[k]
            print(f"  {k} 级 {n} 个：出现≥3 次 {hi}，只出现 1 次 {once}")

    lines = [
        "# 词库对账报告", "",
        "> 由 `.tools/reconcile_outline.py` 生成。参考词表见 `data/reference/cet4_outline.txt`，",
        "> 是第三方整理的 4427 词表，**不是官方考纲**，只用来发现遗漏，不参与构建。", "",
        "## 一、总览", "",
        "| 指标 | 数量 |", "|---|---|",
        f"| 词库单词型词条 | {len(lex_solo)} |",
        f"| 大纲参考词表 | {len(outline)} |",
        f"| 两者交集 | {covered} |",
        f"| 漏网（语料出现过 + 大纲内 + 词库未收） | {len(gap)} |",
        f"| 超纲（词库有、参考表无） | {len(beyond)} |", "",
        "## 二、该补的词（语料里真出现过，大纲也要求）", "",
        "按「正文出现次数」降序。「正文」是只计阅读/听力正文的次数，「总次」含题干与选项。", "",
        "| 单词 | 正文 | 总次 | 大纲释义 |", "|---|---|---|---|",
    ]
    for w, v in gap[: args.top]:
        lines.append(f"| **{w}** | {v['b']} | {v['n']} | {outline[w][:40]} |")
    if len(gap) > args.top:
        lines.append(f"| … | | | 另有 {len(gap) - args.top} 个 |")

    lines += ["", "## 三、超纲词（词库有、参考表没有）", "",
              "这些不一定要删：可能是四级常见但参考表漏收，也可能是专有名词/技术词。",
              "下面按在语料里出现的次数排序，出现次数多的要单独判断。", "",
              "| 单词 | 等级 | 出现次数 | 释义 |", "|---|---|---|---|"]
    for w, cnt in beyond_hit[: args.top]:
        e = lex.entries[w]
        lines.append(f"| {w} | {e.level} | {cnt} | {'；'.join(e.senses_display())[:30]} |")

    lines += ["", "## 四、等级分层现状", "",
              "| 等级 | 词数 | 出现≥3 次 | 只出现 1 次 |", "|---|---|---|---|"]
    for k in "ABC":
        if k in lv_stat:
            n, hi, once = lv_stat[k]
            lines.append(f"| {k} | {n} | {hi} | {once} |")
    lines += ["", "A 级本应代表「基础高频」。如果 A 级里只出现 1 次的词占比很高，",
              "说明它混进了长尾词，等级筛选就失去意义了。", ""]

    os.makedirs(os.path.dirname(OUT_MD), exist_ok=True)
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n报告已写入：" + OUT_MD)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
