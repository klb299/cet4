# -*- coding: utf-8 -*-
"""CET-4 真题词汇提取工具 · 一键运行

用法：
    python run.py                     # 全量构建，输出到 output/
    python run.py --levels AB         # 只要基础高频 + 核心必背
    python run.py --examples 5        # 每个词最多 5 条真题例句
    python run.py --min-count 2       # 只在真题中出现 2 次以上的词
    python run.py --only-years 2025年6月,2025年12月   # 只构建指定场次
    python run.py --check             # 体检：只校验数据，不出文件
"""
import argparse
import os
import sys
import webbrowser
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import corpus, extractor, exporters, family, phonetics, similar  # noqa: E402
from core.lexicon import Lexicon                        # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
DIR_LEX = os.path.join(BASE, "data", "lexicon")
DIR_PHON = os.path.join(BASE, "data", "phonetics")
DIR_CORPUS = os.path.join(BASE, "data", "corpus")
DIR_TRANS = os.path.join(BASE, "data", "translation")
DIR_IMPORT = os.path.join(BASE, "data", "import")
DIR_OUT = os.path.join(BASE, "output")
FILE_STOP = os.path.join(BASE, "data", "stopwords.txt")


def _lint(lex, blocks, ph=None):
    """数据体检：把会影响使用体验的问题一次性列出来，不阻断构建。"""
    warn = []

    # 1) 只有 0-1 句的残块：没有上下文，例句的 prev/next 会空
    thin = [b for b in blocks if len(b.sentences) <= 1]
    if thin:
        warn.append(f"{len(thin)} 个题型块正文不足 2 句，例句不会带上下文："
                    + "、".join(f"{b.year}{b.section}" for b in thin[:4])
                    + ("…" if len(thin) > 4 else ""))

    # 2) 有正文却没有题干的块：卡片里"原题"一栏会一直空着
    noq = [b for b in blocks if b.sentences and not b.questions]
    if noq:
        warn.append(f"{len(noq)} 个题型块没有 @question，卡片里「原题」会为空"
                    f"（多为选词填空/长篇阅读，官方未公布题干）")

    # 3) 译文覆盖不全
    bad_tr = [b for b in blocks if b.sentences and not any(s.trans for s in b.sentences)]
    if bad_tr:
        warn.append(f"{len(bad_tr)} 个题型块完全没有译文："
                    + "、".join(f"{b.year}{b.section}" for b in bad_tr[:4])
                    + ("…" if len(bad_tr) > 4 else ""))

    # 4a) 同一词条义项过多，卡面会很长（对 370 分档尤其不友好）
    fat = sorted((c for c in lex.entries.values() if len(c.senses) >= 8),
                 key=lambda e: -len(e.senses))
    if fat:
        warn.append(f"词库有 {len(fat)} 个词义项 ≥8 条，卡面偏长，建议精简："
                    + "、".join(f"{e.word}({len(e.senses)})" for e in fat[:6]))

    # 4b) 义项里出现字面重复 —— 比"太长"更糟：卡面会显示两条一模一样的释义。
    #     2026-09-30 清理时，sweat 里"出汗"出现过 4 次、visa 里"签证"3 次。
    dup_sense = []
    for w, e in lex.entries.items():
        seen, hit = set(), set()
        for s in e.senses:
            core = s.lstrip("*").strip()
            if core in seen:
                hit.add(core)
            seen.add(core)
        if hit:
            dup_sense.append((w, sorted(hit)))
    if dup_sense:
        warn.append(f"词库有 {len(dup_sense)} 个词义项字面重复（卡面会出现两条一样的释义）："
                    + "、".join(f"{w}({'/'.join(h)})" for w, h in dup_sense[:5])
                    + ("…" if len(dup_sense) > 5 else ""))

    # 5) 音标：缺多少、有没有明显写坏的
    if ph is not None and len(ph):
        no_ph = [w for w, e in lex.entries.items() if " " not in w and not e.phonetic]
        if no_ph:
            warn.append(f"{len(no_ph)} 个单词型词条没有音标（卡片上不显示音标位）："
                        + "、".join(no_ph[:8]) + ("…" if len(no_ph) > 8 else ""))
        broken = [w for w, e in lex.entries.items()
                  if e.phonetic and not phonetics.looks_like_ipa(e.phonetic)]
        if broken:
            warn.append(f"{len(broken)} 条音标看着不像音标，检查 data/phonetics/："
                        + "、".join(f"{w}({lex.entries[w].phonetic[:12]})"
                                    for w in broken[:6]))

    if warn:
        print("数据体检：")
        for w in warn:
            print("  · " + w)
        print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--levels", default="ABC", help="保留等级，默认 ABC 全要")
    ap.add_argument("--examples", type=int, default=3, help="每词最多例句数")
    ap.add_argument("--min-count", type=int, default=1, help="真题最小出现次数")
    ap.add_argument("--only-years", default="", help="只保留这些场次，逗号分隔，如 2025年6月")
    ap.add_argument("--check", action="store_true", help="只做数据体检，不生成文件")
    ap.add_argument("--out-dir", default=DIR_OUT)
    ap.add_argument("--no-open", action="store_true", help="不自动打开网页")
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    lex = Lexicon.load(DIR_LEX)
    if lex.issues:
        print(f"词库格式问题 {len(lex.issues)} 处：")
        for msg in lex.issues[:15]:
            print("  ! " + msg)
        if len(lex.issues) > 15:
            print(f"  … 另有 {len(lex.issues) - 15} 处")
        print()

    # 音标：单独一份数据，挂在词条上。缺失不影响构建，只在体检里提示。
    ph = phonetics.Phonetics.load(DIR_PHON)
    n_ph = lex.attach_phonetics(ph)
    if ph.issues:
        print(f"音标文件问题 {len(ph.issues)} 处：")
        for msg in ph.issues[:10]:
            print("  ! " + msg)
        print()

    blocks = corpus.load_corpus(DIR_CORPUS) + corpus.load_imports(DIR_IMPORT)
    if args.only_years:
        keep_years = {y.strip() for y in args.only_years.split(",") if y.strip()}
        blocks = [b for b in blocks if b.year in keep_years]
    if not blocks:
        print("没有读到任何真题语料，请把真题文本放到 data/corpus/ 或 data/import/。")
        return 1

    n_trans, miss, mism = corpus.load_translations(DIR_TRANS, blocks)
    if miss:
        print(f"译文未匹配 {len(miss)} 块：{[m[2] for m in miss][:5]}")
    if mism:
        print(f"译文句数与原文不一致 {len(mism)} 块：{mism[:5]}")

    # 数据体检：把影响使用的问题一次性列出来
    _lint(lex, blocks, ph)

    # 停用词表：功能词和题干套话不计入"未收录"，否则它们会霸占清单前排
    stop = extractor.load_stopwords(FILE_STOP)
    cov = {}
    cards, unknown, total = extractor.extract(
        lex, blocks, max_examples=args.examples, stopwords=stop, coverage=cov)
    passages = extractor.annotate_passages(lex, blocks)
    keep = set(args.levels.upper())
    cards = [c for c in extractor.sort_cards(cards)
             if c.entry.level in keep and c.count >= args.min_count]

    # 易混词：只看保留下来的卡片，否则会推荐一个不在词表里的词，点了搜不到
    conf = similar.find_confusables(cards)
    for c in cards:
        c.confuse = conf.get(c.word, [])

    # 词族：除卡片词外，把"词库里有、语料没出现"的原形也带上，
    # 否则 quickly 这种"只考过派生词"的词就永远连不回 quick
    fam = family.build_families([c.word for c in cards],
                                extra=[w for w in lex.entries if " " not in w])
    for c in cards:
        c.family = fam.get(c.word, [])

    n_tr = sum(1 for c in cards for o in c.occurrences if o.trans)
    n_real = sum(1 for c in cards for o in c.occurrences if o.source != "sim")
    n_sim = sum(1 for c in cards for o in c.occurrences if o.source == "sim")
    n_src = Counter(getattr(b, "source", "real") for b in blocks)
    print(f"词库 {len(lex)} 词 | 语料 {len(blocks)} 个题型块"
          f"（真题 {n_src.get('real', 0)} / 仿真 {n_src.get('sim', 0)}"
          + (f" / 导入 {n_src['import']}" if n_src.get("import") else "")
          + f"，{n_trans} 块配了译文）| 扫描 {total} 个英文词次")
    print(f"命中重点词 {len(cards)} 个，例句 {n_real + n_sim} 条"
          f"（真题 {n_real} + 仿真 {n_sim}，{n_tr} 条带中文译文）")
    if n_sim:
        print(f"  注意：仿真例句占 {n_sim / max(n_real + n_sim, 1) * 100:.0f}%，"
              f"卡面与导出文件里已逐条标注来源，频次类表述会把两者分开写。")
    if cov.get("bodyContent"):
        print(f"覆盖率：这 {len(cards)} 个词命中正文 {cov['bodyHit']}/{cov['bodyTokens']} 词次"
              f"（{cov['bodyHit'] / max(cov['bodyTokens'], 1) * 100:.1f}%）；"
              f"去掉功能词后 {cov['bodyHitContent']}/{cov['bodyContent']}"
              f"（{cov['bodyHitContent'] / cov['bodyContent'] * 100:.1f}%）")
    print(f"易混词提示 {len(conf)} 个词条（拼写距离 1 或相邻换位）| "
          f"词族 {len(fam)} 个词条（后缀剥离，只连查得到的原形）")
    # 音标覆盖只统计单词型卡片：固定搭配（because of）本来就没有单个音标，
    # 混进分母会凭空看到一个永远到不了 100% 的百分比
    solo = [c for c in cards if " " not in c.word]
    n_card_ph = sum(1 for c in solo if c.entry.phonetic)
    if ph and len(ph):
        print(f"音标覆盖 {n_card_ph}/{len(solo)} 个单词型词条"
              f"（{n_card_ph / max(len(solo), 1) * 100:.1f}%），来源 data/phonetics/")
    lv = Counter(c.entry.level for c in cards)
    print("等级分布：" + "  ".join(
        f"{k}={v}" for k, v in sorted(lv.items())))

    if args.check:
        print("\n--check：只做了体检，未生成文件。")
        return 0

    html = exporters.build_html(cards, blocks, os.path.join(args.out_dir, "index.html"),
                                passages=passages, stopwords=stop, coverage=cov)
    md = exporters.build_markdown(cards, blocks,
                                  os.path.join(args.out_dir, "真题词汇表_按年份题型.md"))
    csv1 = exporters.build_csv(cards, os.path.join(args.out_dir, "真题词汇表_完整.csv"))
    csv2 = exporters.build_anki(cards, os.path.join(args.out_dir, "Anki导入包.csv"))
    unk, n = exporters.build_unknown(unknown, os.path.join(args.out_dir, "未收录高频词.txt"))
    wb = exporters.build_unknown_workbench(
        unknown, os.path.join(args.out_dir, "未收录词工作台.html"))
    # manifest / sw.js / 图标：让「添加到主屏幕」断网也能打开
    pwa = exporters.build_pwa(args.out_dir)

    # 入口页也由构建生成：它的数字原来写死在 HTML 里，词库涨到 1550 之后
    # 首页还写着 1016，线上因此长期落后一整版。链接用相对路径，
    # 这样 root 页放在项目根、产物在 output/ 时都能点开。
    def _rel(p):
        return os.path.relpath(p, BASE).replace("\\", "/")

    landing = exporters.build_landing(
        cards, blocks, os.path.join(BASE, "index.html"),
        href_main=_rel(os.path.join(args.out_dir, "index.html")),
        href_md=_rel(os.path.join(args.out_dir, "真题词汇表_按年份题型.md")),
        href_anki=_rel(os.path.join(args.out_dir, "Anki导入包.csv")),
        coverage=cov)

    print("\n输出：")
    for p in (landing, html, md, csv1, csv2, unk, wb):
        print("  " + p)
    print("  " + "\n  ".join(pwa) + "   （离线支持）")
    print(f"\n未收录高频词 {n} 个，可补充进 data/lexicon/ 让词表更全"
          f"（打开未收录词工作台.html 边看语境边补）。")

    # 这句原来是 webbrowser.open("file:///" + html.replace("\\", "/"))。
    # 本项目的路径本身带中文（D:\项目\4级\…），拼出来的 URL 没做百分号编码，
    # 浏览器拿到的是裸 UTF-8，部分环境下打不开或打开成乱码；
    # Path.as_uri() 会正确处理盘符、斜杠与百分号编码。
    if not args.no_open:
        webbrowser.open(Path(html).as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
