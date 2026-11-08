# -*- coding: utf-8 -*-
"""数据质量门禁：不启浏览器，只查数据本身。

为什么单独一套：词卡页面的回归需要真 Chrome，慢且依赖环境；
而"词库漏了 basic 这种词""音标少了几个""覆盖率掉了"这类问题，
纯数据就能查出来，应该在提交前几秒内跑完。

用法：
    python tests/audit_data.py
返回 0 表示全部达标，1 表示有指标越线（可直接挂到 CI / pre-commit）。
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from core import corpus, extractor, family, phonetics, similar   # noqa: E402
from core.lexicon import Lexicon                                 # noqa: E402

DIR_LEX = os.path.join(BASE, "data", "lexicon")
DIR_PHON = os.path.join(BASE, "data", "phonetics")
DIR_CORPUS = os.path.join(BASE, "data", "corpus")
DIR_TRANS = os.path.join(BASE, "data", "translation")
DIR_IMPORT = os.path.join(BASE, "data", "import")
FILE_STOP = os.path.join(BASE, "data", "stopwords.txt")
FILE_OUTLINE = os.path.join(BASE, "data", "reference", "cet4_outline.txt")

OK, BAD = [], []


def ck(name, cond, got=""):
    (OK if cond else BAD).append(name)
    print(("  ok  " if cond else "  FAIL") + "  " + name + ("   -> %s" % got if got else ""))


def load_outline(path):
    out = set()
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("#") or "|" not in line:
                continue
            w = line.split("|", 1)[0].strip().lower()
            if w:
                out.add(w)
    return out


def main():
    print("-- 数据质量 --")
    lex = Lexicon.load(DIR_LEX)
    ck("词库没有格式问题", not lex.issues, "；".join(lex.issues[:3]))
    ck("词库规模在 2000~3000 之间", 2000 <= len(lex) <= 3000, len(lex))

    ph = phonetics.Phonetics.load(DIR_PHON)
    n_ph = lex.attach_phonetics(ph)
    solo = [w for w in lex.entries if " " not in w]
    cover = n_ph / max(len(solo), 1) * 100
    # 音标 100% 是硬要求：卡片上有音标位却空着，比没有音标位更难看
    ck("单词型词条音标覆盖 100%", cover >= 99.9, "%.1f%%（%d/%d）" % (cover, n_ph, len(solo)))
    broken = [w for w in solo if lex.entries[w].phonetic
              and not phonetics.looks_like_ipa(lex.entries[w].phonetic)]
    ck("没有写坏掉的音标", not broken, "、".join(broken[:5]))

    blocks = corpus.load_corpus(DIR_CORPUS) + corpus.load_imports(DIR_IMPORT)
    corpus.load_translations(DIR_TRANS, blocks)
    ck("每块都有译文", all(any(s.trans for s in b.sentences) for b in blocks if b.sentences),
       "%d 块" % len(blocks))

    stop = extractor.load_stopwords(FILE_STOP)
    cov = {}
    cards, unknown, _total = extractor.extract(
        lex, blocks, stopwords=stop, coverage=cov)
    cards = extractor.sort_cards(cards)

    rate = cov.get("bodyHitContent", 0) / max(cov.get("bodyContent", 1), 1) * 100
    ck("实词覆盖率不低于 95%", rate >= 95.0, "%.1f%%" % rate)

    # 核心断言：语料里出现过、大纲也要求、词库却没有的词。
    # 这个数字就是"词库该补没补"的直接度量——2026-11 之前它是 120。
    outline = load_outline(FILE_OUTLINE)
    gap = [w for w, v in unknown.items() if w in outline and len(w) >= 3]
    ck("大纲内未收录词不超过 30 个", len(gap) <= 30,
       "%d 个：%s" % (len(gap), "、".join(sorted(gap)[:8])))

    # 屈折形式独立成条会把出现次数拆成两半，抽查几个最常见的
    ghost = [w for w in ("has", "had", "been", "made", "books", "minutes")
             if w in lex.entries]
    ck("没有屈折形式独立成条", not ghost, "、".join(ghost))

    lv = {}
    for c in cards:
        lv[c.entry.level] = lv.get(c.entry.level, 0) + 1
    ck("三个等级都有卡片", all(lv.get(k, 0) > 0 for k in "ABC"), lv)

    fam = family.build_families([c.word for c in cards],
                                extra=[w for w in lex.entries if " " not in w])
    ck("同族词至少覆盖 150 个词条", len(fam) >= 150, len(fam))
    conf = similar.find_confusables(cards)
    ck("易混词至少覆盖 250 个词条", len(conf) >= 250, len(conf))

    print("\n=== %d 通过 / %d 失败 ===" % (len(OK), len(BAD)))
    for x in BAD:
        print("  失败：" + x)
    return 1 if BAD else 0


if __name__ == "__main__":
    raise SystemExit(main())
