# -*- coding: utf-8 -*-
"""抽取引擎：在真题句子中命中词库词条，还原词形、判断语境词性、聚合真题出处。"""
import re
from collections import defaultdict

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'\-]*")


def load_stopwords(path):
    """读停用词表。一行可写多个词，空格或换行分隔，# 开头是注释。"""
    out = set()
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.split("#", 1)[0].strip()
                if not line:
                    continue
                out.update(w.strip().lower() for w in line.split() if w.strip())
    except OSError:
        return out
    return out

DET = {"a", "an", "the", "this", "that", "these", "those", "my", "your", "his",
       "her", "its", "our", "their", "some", "any", "no", "each", "every",
       "another", "other", "such", "what", "which", "his"}
AUX = {"be", "is", "are", "was", "were", "been", "am", "have", "has", "had",
       "will", "would", "can", "could", "shall", "should", "may", "might",
       "must", "do", "does", "did", "to", "get", "gets", "got"}
DEG = {"very", "quite", "rather", "too", "so", "more", "most", "extremely",
       "highly", "really", "fairly", "pretty", "increasingly", "relatively"}
PREP = {"of", "in", "on", "at", "for", "with", "by", "from", "about", "into",
        "over", "under", "through", "during", "against", "without", "within"}

SECTION_ORDER = {"仔细阅读": 0, "选词填空": 1, "长篇阅读": 2, "听力": 3, "翻译": 4, "写作": 5}

# 精读视图的"本文重点词"按这个顺序排（A 基础 → C 进阶）
LEVEL_ORDER = {"A": 0, "B": 1, "C": 2}


def guess_pos(tokens, i):
    """粗略判断该词在句中的词性，用于给学习者提示。"""
    w = tokens[i].lower()
    prev = tokens[i - 1].lower() if i > 0 else ""
    prev2 = tokens[i - 2].lower() if i >= 2 else ""
    nxt = tokens[i + 1].lower() if i + 1 < len(tokens) else ""
    if prev in DET or (prev in DEG and prev2 in DET):
        return "名词"
    if prev in AUX and (w.endswith("ing") or w.endswith("ed")):
        return "动词"
    if prev in DEG or prev.endswith("ly"):
        return "形容词/副词"
    if prev == "to" and nxt not in DET:
        return "动词"
    if w.endswith("ly") and prev not in DET:
        return "副词"
    if nxt in DET or (nxt.endswith("s") and nxt not in PREP):
        return "动词"
    if prev in PREP and w.endswith("ing"):
        return "动名词"
    return ""


class Occurrence:
    __slots__ = ("word", "form", "pos_hint", "sentence", "prev", "next",
                 "year", "set", "section", "title", "topic", "block",
                 "trans", "qtrans", "kind", "source")

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)

    def related_question(self):
        """返回 (题干, 题干序号)；优先取提到该词的那道题，否则取本块第一题。"""
        qs = getattr(self.block, "questions", []) or []
        if not qs:
            return "", -1
        low = self.form.lower()
        for i, q in enumerate(qs):
            if low in q.lower():
                return q, i
        return qs[0], 0

    def as_dict(self):
        # 只有正文句才去挂"原题"：题干/选项本身就是那句话，
        # 再挂一遍会变成同一段文字在卡面上出现两次
        q, qtrans = "", ""
        if self.kind == "body":
            q, qi = self.related_question()
            qts = getattr(self.block, "qtrans", []) or []
            qtrans = qts[qi] if 0 <= qi < len(qts) else ""
        return {
            "form": self.form,
            "posHint": self.pos_hint,
            "sentence": self.sentence,
            "prev": self.prev,
            "next": self.next,
            "year": self.year,
            "set": self.set,
            "section": self.section,
            "title": self.title,
            "topic": self.topic,
            "question": q,
            "trans": self.trans,
            "questionTrans": qtrans,
            "kind": self.kind,
            "src": self.source,
        }


class WordCard:
    def __init__(self, entry):
        self.entry = entry
        self.word = entry.word
        self.count = 0
        self.occurrences = []
        self.years = set()
        self.sections = set()
        # 按来源拆开计数：86% 的语料是仿真文，总次数不能直接叫「真题出现次数」。
        # count 仍保留为总数（排序、统计都用它），卡面展示时用下面两组分开说。
        self.count_real = 0
        self.count_sim = 0
        self.years_real = set()
        self.years_sim = set()
        # 易混词由 core.similar 构建期算出后挂上来（只影响展示，不参与统计）
        self.confuse = []
        # 同族词由 core.family 算出：[(词, 'base'/'derived', 有没有卡片)]
        self.family = []

    def add(self, occ):
        self.count += 1
        self.occurrences.append(occ)
        self.years.add(occ.year)
        self.sections.add(occ.section)
        if occ.source == "sim":
            self.count_sim += 1
            self.years_sim.add(occ.year)
        else:
            self.count_real += 1
            self.years_real.add(occ.year)

    def finalize(self, max_examples=3):
        """例句挑选：先保正文原句，再跨题型、跨年份分散，最后按题型重要度排序。

        题干与选项也进例句池（见 extract 里的说明），但它们是"补充证据"，
        排序时排在正文句之后，只有在正文句凑不够 max_examples 时才顶上来。
        """
        def key(o):
            return (0 if o.kind == "body" else 1,
                    SECTION_ORDER.get(o.section, 9), o.year)
        pool = sorted(self.occurrences, key=key)
        picked, used = [], set()
        for o in pool:
            sig = (o.kind, o.section, o.year)
            if sig in used:
                continue
            used.add(sig)
            picked.append(o)
            if len(picked) >= max_examples:
                break
        if len(picked) < max_examples:
            for o in pool:
                if o not in picked:
                    picked.append(o)
                if len(picked) >= max_examples:
                    break
        self.occurrences = picked

    def as_dict(self):
        return {
            "word": self.word,
            "pos": self.entry.pos,
            "senses": self.entry.senses_display(),
            "level": self.entry.level,
            "levelName": {"A": "基础高频", "B": "核心必背", "C": "进阶拓展"}.get(
                self.entry.level, self.entry.level),
            "note": self.entry.note,
            "phonetic": getattr(self.entry, "phonetic", ""),
            "count": self.count,
            "countReal": self.count_real,
            "countSim": self.count_sim,
            "years": sorted(self.years),
            "yearsReal": sorted(self.years_real),
            "yearsSim": sorted(self.years_sim),
            "sections": sorted(self.sections, key=lambda s: SECTION_ORDER.get(s, 9)),
            "confuse": [w for w, _d in getattr(self, "confuse", [])],
            "family": [[w, r, bool(h)] for w, r, h in getattr(self, "family", [])],
            "examples": [o.as_dict() for o in self.occurrences],
        }


def highlight(sentence, forms):
    """在句子中高亮目标词形（大小写不敏感）。

    forms 是这一句里属于同一个词的所有词形（leave / leaves / left…），
    传字符串也兼容。必须按整词边界匹配：
    原实现写成 re.escape(form) + r"\\w*"，于是 the 会把 they / their / them /
    there 一起涂黄，实测语料里有 313 处这种"高亮出来的词根本不是目标词"。
    """
    if isinstance(forms, str):
        forms = [forms]
    forms = [f for f in dict.fromkeys(forms) if f]
    if not forms:
        return sentence
    # 长词形优先，避免 "the" 先吃掉 "there" 的开头
    alts = "|".join(re.escape(f) for f in sorted(forms, key=len, reverse=True))
    pat = re.compile(r"\b(?:" + alts + r")\b", re.I)
    return pat.sub(lambda m: f"[[{m.group(0)}]]", sentence)


def extract(lexicon, blocks, max_examples=3, stopwords=(), coverage=None):
    """扫描语料，产出词卡。

    扫描范围是三种文本：正文句、题干、选项。
    为什么题干和选项也要扫：这两块（162 条题干 + 312 条选项）原来完全没进
    统计，但读题干时遇到的生词（infer / attitude / according to）恰恰是做题
    真正卡人的地方。纳入之后卡片的"真题出现次数"更贴近考场。
    它们只在例句挑选里做补充（finalize 里排正文句之后），不会挤掉真题原句。

    stopwords 里的词（功能词、题干套话）不进未收录清单，只参与词次统计。
    未收录词会记两个数字：n 总出现次数、b 其中来自正文句的次数。
    b 更值得看——只在题干里出现过的词多半是套话，补进词库的价值低。

    coverage 传入一个 dict 就把"词库覆盖了多少正文词次"填进去。
    这个数字用来回答一个很实际的问题：这 1550 个词到底够不够读真题？
    只统计正文（kind == "body"），题干与选项不计入——那是做题语言，不是阅读语言。
    """
    cards = {}
    unknown = defaultdict(lambda: {"n": 0, "b": 0, "s": []})
    total_tokens = 0
    stop = set(stopwords or ())

    def scan(text, b, kind, trans="", prev="", next_="", qidx=-1):
        """扫一段文本，把命中的词记到卡片上。返回扫到的词次。"""
        nonlocal total_tokens
        tokens = TOKEN_RE.findall(text)
        lowered = [t.lower() for t in tokens]
        total_tokens += len(tokens)

        hits = defaultdict(list)
        matched = []
        covered = set()      # 被词库覆盖的 token 位置，短语占多个位置
        for i, low in enumerate(lowered):
            ph = lexicon.lookup_phrase(lowered, i)
            if ph:
                phrase, pentry, n = ph
                surface = " ".join(tokens[i:i + n])
                hits[phrase].append(surface)
                matched.append((phrase, pentry, surface, ""))
                covered.update(range(i, min(i + n, len(tokens))))
            if len(low) < 3:
                continue
            hit = lexicon.lookup(low)
            if hit:
                base, entry = hit
                hits[base].append(tokens[i])
                matched.append((base, entry, tokens[i], guess_pos(lowered, i)))
                covered.add(i)
            elif not ph:
                if low in stop:
                    continue
                u = unknown[low]
                u["n"] += 1
                if kind == "body":
                    u["b"] += 1
                    if len(u["s"]) < 2:
                        u["s"].append(text[:160])

        if coverage is not None and kind == "body":
            coverage["bodyTokens"] = coverage.get("bodyTokens", 0) + len(tokens)
            coverage["bodyHit"] = coverage.get("bodyHit", 0) + len(covered)
            coverage["bodySentences"] = coverage.get("bodySentences", 0) + 1
            # 再算一遍"去掉功能词"的口径：全部词次里 the/a/of 占了大头，
            # 用它们撑起来的 63% 没有意义。学习者真正要认得的是实词，
            # 实词覆盖率（95%）才是"这个工具够不够用"的答案。
            for i, low in enumerate(lowered):
                if len(low) < 3 or low in stop:
                    continue
                coverage["bodyContent"] = coverage.get("bodyContent", 0) + 1
                if i in covered:
                    coverage["bodyHitContent"] = coverage.get("bodyHitContent", 0) + 1

        for base, entry, surface, phint in matched:
            card = cards.get(base)
            if card is None:
                card = cards[base] = WordCard(entry)
            card.add(Occurrence(
                word=base, form=surface, pos_hint=phint,
                sentence=highlight(text, hits[base]),
                prev=prev, next=next_,
                year=b.year, set=b.set_name, section=b.section, title=b.title,
                topic=b.topic, block=b, trans=trans, qtrans="", kind=kind,
                source=getattr(b, "source", "real")))

    for b in blocks:
        sents = b.sentences
        for si, sent in enumerate(sents):
            scan(sent.text, b, "body",
                 trans=getattr(sent, "trans", ""),
                 prev=sents[si - 1].text if si > 0 else "",
                 next_=sents[si + 1].text if si + 1 < len(sents) else "")
        qts = getattr(b, "qtrans", []) or []
        for qi, q in enumerate(getattr(b, "questions", []) or []):
            if q:
                scan(q, b, "question",
                     trans=qts[qi] if qi < len(qts) else "")
        for ch in getattr(b, "choices", []) or []:
            if ch:
                scan(ch, b, "choice")

    for c in cards.values():
        c.finalize(max_examples=max_examples)
    return cards, unknown, total_tokens


def annotate_passages(lexicon, blocks, highlight_levels=("B", "C")):
    """精读视图用的整篇文本：逐句标出词库命中，附译文与题干选项。

    highlight_levels 只标 B/C（核心必背 + 进阶拓展），A 级基础词不高亮：
    13/14 册补进来的 eat/sell/open/save 这类词一旦也标，整篇几乎全黄，
    高亮就失去了"提醒你这里有个值得看的词"的作用。

    为什么单独一个函数而不是复用 extract 的循环：extract 关心的是
    "建卡片 + 记频次 + 挑例句"，这里只要"标出命中"。逻辑确实有重叠，
    但 extract 那条线还背着 unknown 计数和词性提示，硬揉在一起只会更难读。
    """
    out = []
    for b in blocks:
        sents = []
        words = {}
        wcnt = defaultdict(int)   # 该词在这篇里出现几次，用来算"生词占全文多少词次"
        for s in b.sentences:
            tokens = TOKEN_RE.findall(s.text)
            lowered = [t.lower() for t in tokens]
            hits = defaultdict(list)
            for i, low in enumerate(lowered):
                # 短语必须先于单词判断，顺序和 extract() 保持一致。
                # 反过来写的话 because / for / rather 这些"短语首词"自己就在词库里，
                # 命中一次就 continue 掉，17 个固定搭配在语料里的 51 次出现
                # 一处都标不出来（实测整篇 596 个高亮里短语 0 个）。
                ph = lexicon.lookup_phrase(lowered, i)
                if ph:
                    phrase, pentry, n = ph
                    words.setdefault(phrase, pentry.level)
                    wcnt[phrase] += 1
                    # 固定搭配不受 highlight_levels 限制：17 个搭配全是 A 级，
                    # 套用同一套等级过滤的话，语料里 51 处固定搭配一处都标不出来，
                    # 而 rather than / no longer 恰恰是阅读里最容易看漏的考点。
                    # 它们全篇只占 51 处，不会像 965 个 A 级单词那样把整篇涂黄。
                    if " " in phrase or pentry.level in highlight_levels:
                        hits[phrase].append(" ".join(tokens[i:i + n]))
                if len(low) < 3:
                    continue
                hit = lexicon.lookup(low)
                if hit:
                    base, entry = hit
                    words.setdefault(base, entry.level)
                    wcnt[base] += 1
                    if entry.level in highlight_levels:
                        hits[base].append(tokens[i])
            marked = highlight(s.text, [x for v in hits.values() for x in v]) \
                if hits else s.text
            sents.append({"t": marked, "tr": getattr(s, "trans", "")})
        qts = getattr(b, "qtrans", []) or []
        qs = []
        for qi, q in enumerate(getattr(b, "questions", []) or []):
            if q:
                qs.append({"q": q, "tr": qts[qi] if qi < len(qts) else ""})
        out.append({
            "y": b.year, "s": b.set_name, "sec": b.section, "t": b.title,
            "topic": b.topic, "sents": sents, "qs": qs,
            "src": getattr(b, "source", "real"),
            # 正文词次：精读视图用它算"生词密度"（未掌握词数 / 全文词数），
            # 只给重点词数算不出密度——同一篇里重点词多少和篇幅长短没关系
            "n": sum(len(TOKEN_RE.findall(s.text)) for s in b.sentences),
            "ch": list(getattr(b, "choices", []) or []),
            "w": [[w, lv, wcnt[w]] for w, lv in sorted(
                words.items(), key=lambda kv: (LEVEL_ORDER.get(kv[1], 9), kv[0]))],
        })
    return out


def sort_cards(cards):
    """重点词排序：等级 A→C，再按出现次数降序，再按字母。"""
    return sorted(
        cards.values(),
        key=lambda c: ({"A": 0, "B": 1, "C": 2}.get(c.entry.level, 3),
                       -c.count, c.word))
