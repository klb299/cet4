# -*- coding: utf-8 -*-
"""CET-4 词库：加载、屈折还原、词性优先级判断。

数据文件格式为紧凑的管道分隔文本：
    单词|词性|义项(分号分隔，带 * 者为常考义)|等级(A基础/B核心/C进阶)|搭配提示
多词固定搭配（如 because of）也允许，单词列直接写整个短语。

音标不写在这里，由 core/phonetics.py 从 data/phonetics/ 单独加载后挂上来，
这样词库文件不用为每个词多维护一列，也方便一键换英式/美式音标。
"""
import os
import re

LEVEL_NAME = {"A": "基础高频", "B": "核心必背", "C": "进阶拓展"}
LEVEL_ORDER = {"A": 0, "B": 1, "C": 2}   # 精读视图按此排序"本文重点词"

# 常见不规则变化：变形 -> 原形。
# 这里刻意用「有序 (变形, 原形) 列表」而不是 dict：
#   dict 字面量遇到重复键会静默丢掉先写的那条（历史上一度把
#   leaves->leave 覆盖成了 leaves->leaf，而且不留任何痕迹），
#   列表则重复就是重复，顺序还明确表达了优先级：先写先命中。
IRREGULAR_PAIRS = [
    ("am", "be"), ("is", "be"), ("are", "be"), ("was", "be"), ("were", "be"),
    ("been", "be"), ("being", "be"),
    ("has", "have"), ("had", "have"), ("having", "have"),
    ("does", "do"), ("did", "do"), ("done", "do"), ("doing", "do"),
    ("went", "go"), ("gone", "go"), ("goes", "go"), ("going", "go"),
    ("made", "make"), ("makes", "make"), ("making", "make"),
    ("took", "take"), ("taken", "take"), ("takes", "take"), ("taking", "take"),
    ("came", "come"), ("comes", "come"), ("coming", "come"),
    ("saw", "see"), ("seen", "see"), ("sees", "see"), ("seeing", "see"),
    ("got", "get"), ("gotten", "get"), ("gets", "get"), ("getting", "get"),
    ("knew", "know"), ("known", "know"), ("knows", "know"), ("knowing", "know"),
    ("thought", "think"), ("thinks", "think"), ("thinking", "think"),
    ("found", "find"), ("finds", "find"), ("finding", "find"),
    ("gave", "give"), ("given", "give"), ("gives", "give"), ("giving", "give"),
    ("told", "tell"), ("tells", "tell"), ("telling", "tell"),
    ("became", "become"), ("becomes", "become"), ("becoming", "become"),
    ("left", "leave"), ("leaves", "leave"), ("leaving", "leave"),
    ("felt", "feel"), ("feels", "feel"), ("feeling", "feel"),
    ("put", "put"), ("puts", "put"), ("putting", "put"),
    ("brought", "bring"), ("brings", "bring"), ("bringing", "bring"),
    ("began", "begin"), ("begun", "begin"), ("begins", "begin"), ("beginning", "begin"),
    ("kept", "keep"), ("keeps", "keep"), ("keeping", "keep"),
    ("held", "hold"), ("holds", "hold"), ("holding", "hold"),
    ("wrote", "write"), ("written", "write"), ("writes", "write"), ("writing", "write"),
    ("stood", "stand"), ("stands", "stand"), ("standing", "stand"),
    ("heard", "hear"), ("hears", "hear"), ("hearing", "hear"),
    ("let", "let"), ("lets", "let"), ("letting", "let"),
    ("meant", "mean"), ("means", "mean"), ("meaning", "mean"),
    ("set", "set"), ("sets", "set"), ("setting", "set"),
    ("met", "meet"), ("meets", "meet"), ("meeting", "meet"),
    ("ran", "run"), ("runs", "run"), ("running", "run"),
    ("paid", "pay"), ("pays", "pay"), ("paying", "pay"),
    ("sat", "sit"), ("sits", "sit"), ("sitting", "sit"),
    ("spoke", "speak"), ("spoken", "speak"), ("speaks", "speak"), ("speaking", "speak"),
    ("lay", "lie"), ("lying", "lie"), ("lies", "lie"),
    ("led", "lead"), ("leads", "lead"), ("leading", "lead"),
    ("read", "read"), ("reads", "read"), ("reading", "read"),
    ("grew", "grow"), ("grown", "grow"), ("grows", "grow"), ("growing", "grow"),
    ("lost", "lose"), ("loses", "lose"), ("losing", "lose"),
    ("fell", "fall"), ("fallen", "fall"), ("falls", "fall"), ("falling", "fall"),
    ("sent", "send"), ("sends", "send"), ("sending", "send"),
    ("built", "build"), ("builds", "build"), ("building", "build"),
    ("understood", "understand"), ("understands", "understand"), ("understanding", "understand"),
    ("drew", "draw"), ("drawn", "draw"), ("draws", "draw"), ("drawing", "draw"),
    ("broke", "break"), ("broken", "break"), ("breaks", "break"), ("breaking", "break"),
    ("spent", "spend"), ("spends", "spend"), ("spending", "spend"),
    ("cut", "cut"), ("cuts", "cut"), ("cutting", "cut"),
    ("rose", "rise"), ("risen", "rise"), ("rises", "rise"), ("rising", "rise"),
    ("drove", "drive"), ("driven", "drive"), ("drives", "drive"), ("driving", "drive"),
    ("bought", "buy"), ("buys", "buy"), ("buying", "buy"),
    ("wore", "wear"), ("worn", "wear"), ("wears", "wear"), ("wearing", "wear"),
    ("chose", "choose"), ("chosen", "choose"), ("chooses", "choose"), ("choosing", "choose"),
    ("sought", "seek"), ("seeks", "seek"), ("seeking", "seek"),
    ("won", "win"), ("wins", "win"), ("winning", "win"),
    ("hid", "hide"), ("hidden", "hide"), ("hides", "hide"), ("hiding", "hide"),
    ("hit", "hit"), ("hits", "hit"), ("hitting", "hit"),
    ("shot", "shoot"), ("shoots", "shoot"), ("shooting", "shoot"),
    ("sold", "sell"), ("sells", "sell"), ("selling", "sell"),
    ("dealt", "deal"), ("deals", "deal"), ("dealing", "deal"),
    ("fed", "feed"), ("feeds", "feed"), ("feeding", "feed"),
    ("flew", "fly"), ("flown", "fly"), ("flies", "fly"), ("flying", "fly"),
    ("forgot", "forget"), ("forgotten", "forget"), ("forgets", "forget"), ("forgetting", "forget"),
    ("froze", "freeze"), ("frozen", "freeze"), ("freezes", "freeze"), ("freezing", "freeze"),
    ("hung", "hang"), ("hangs", "hang"), ("hanging", "hang"),
    ("knelt", "kneel"), ("kneels", "kneel"), ("kneeling", "kneel"),
    ("rang", "ring"), ("rung", "ring"), ("rings", "ring"), ("ringing", "ring"),
    ("sank", "sink"), ("sunk", "sink"), ("sinks", "sink"), ("sinking", "sink"),
    ("struck", "strike"), ("strikes", "strike"), ("striking", "strike"),
    ("swore", "swear"), ("sworn", "swear"), ("swears", "swear"), ("swearing", "swear"),
    ("threw", "throw"), ("thrown", "throw"), ("throws", "throw"), ("throwing", "throw"),
    ("woke", "wake"), ("woken", "wake"), ("wakes", "wake"), ("waking", "wake"),
    # 名词不规则复数 / 比较级
    ("children", "child"), ("people", "person"), ("men", "man"), ("women", "woman"),
    ("feet", "foot"), ("teeth", "tooth"), ("mice", "mouse"), ("geese", "goose"),
    ("lives", "life"), ("wives", "wife"), ("knives", "knife"), ("leaves", "leaf"),
    ("selves", "self"), ("wolves", "wolf"), ("shelves", "shelf"), ("thieves", "thief"),
    ("teeth", "tooth"), ("oxen", "ox"), ("data", "datum"), ("media", "medium"),
    ("analyses", "analysis"), ("crises", "crisis"), ("bases", "basis"), ("theses", "thesis"),
    ("phenomena", "phenomenon"), ("criteria", "criterion"),
    ("better", "good"), ("best", "good"), ("worse", "bad"), ("worst", "bad"),
    ("further", "far"), ("furthest", "far"), ("farther", "far"),
    ("more", "many"), ("most", "many"), ("less", "little"), ("least", "little"),
    # 下面这批是"补完 15 册才救得回来"的：原形原来不在词库里，
    # 映射就算写在这里也命中不了（IRREGULAR 只在 base in entries 时才建索引），
    # 于是 eat/see/drink/bear/die/sleep/show 的整个变形族全被记成未收录。
    ("ate", "eat"), ("eaten", "eat"),
    ("drank", "drink"), ("drunk", "drink"),
    ("born", "bear"), ("bore", "bear"),
    ("dies", "die"), ("died", "die"), ("dying", "die"),
    ("slept", "sleep"), ("sleeps", "sleep"), ("sleeping", "sleep"),
    ("showed", "show"), ("shown", "show"), ("shows", "show"),
]

VOWELS = set("aeiou")


class Entry:
    __slots__ = ("word", "pos", "senses", "level", "note", "phonetic")

    def __init__(self, word, pos, senses, level, note):
        self.word = word
        self.pos = pos
        self.senses = senses          # list[str]
        self.level = level
        self.note = note
        self.phonetic = ""            # 由 Phonetics.attach() 挂上，未加载音标时为空

    def senses_display(self):
        """带 ★ 标记常考义的义项列表，用于展示。"""
        return [("★" + s[1:] if s.startswith("*") else s) for s in self.senses]

    def as_dict(self):
        return {
            "word": self.word,
            "pos": self.pos,
            "senses": self.senses_display(),
            "level": self.level,
            "levelName": LEVEL_NAME.get(self.level, self.level),
            "note": self.note,
            "phonetic": self.phonetic,
        }


class Lexicon:
    def __init__(self, entries, index, issues=None, phrases=None, max_phrase_words=0):
        self.entries = entries        # 原形 -> Entry
        self.index = index            # 任意词形 -> 原形
        self.issues = issues or []    # 加载时发现的格式问题，供 run.py 打印
        self.phrases = phrases or {}  # 含空格的固定搭配：整串 -> Entry
        self.max_phrase_words = max_phrase_words   # 短语最长几个词，供 n-gram 匹配定上界

    @classmethod
    def load(cls, dir_path):
        entries, index, issues, dups = {}, {}, [], {}
        if not os.path.isdir(dir_path):
            return cls(entries, index, issues)
        for fn in sorted(os.listdir(dir_path)):
            if not fn.endswith(".txt") or fn.startswith("."):
                continue
            with open(os.path.join(dir_path, fn), encoding="utf-8") as f:
                for ln, raw in enumerate(f, 1):
                    line = raw.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split("|")
                    if len(parts) < 4:
                        issues.append(f"{fn}:{ln} 字段不足 4 段，已跳过：{line[:30]}")
                        continue
                    # 多词搭配的词头里含空格，normalize 空白后全部转小写
                    word = " ".join(parts[0].split()).lower()
                    pos = parts[1].strip()
                    senses = [s.strip() for s in parts[2].split(";") if s.strip()]
                    level = parts[3].strip().upper()
                    note = parts[4].strip() if len(parts) > 4 else ""
                    if not word or not senses:
                        issues.append(f"{fn}:{ln} 缺单词或缺义项，已跳过：{line[:30]}")
                        continue
                    # 等级列必须严格是 A/B/C。
                    # 早期这里写成 upper()[:1]，结果「ability to do 做…的能力」被截成 "A"
                    # 蒙混过关 —— 21 条词的搭配提示就是这么静默丢掉的。现在改成严格匹配，
                    # 一旦字段被顶位就当场报错，不再悄悄兜底。
                    if level not in ("A", "B", "C"):
                        issues.append(
                            f"{fn}:{ln} 等级列应为 A/B/C，实际是「{parts[3].strip()[:20]}」"
                            f"（多半是「义项|等级|搭配」里的等级被漏写），已按 B 兜底：{word}")
                        level = "B"
                    elif len(parts) == 4 and note == "" and " " in parts[3]:
                        issues.append(
                            f"{fn}:{ln} 只有 4 段，等级列像是被搭配提示顶掉了：{word}")
                    # 义项里混进等级字母或英文单词，多半是分号/管道写错位
                    for s in senses:
                        core = s.lstrip("*")
                        if core in ("A", "B", "C"):
                            issues.append(f"{fn}:{ln} 义项里混入等级字母「{core}」：{word}")
                        elif re.match(r"^[A-Za-z][A-Za-z'\- ]*$", core) and word not in core.lower():
                            issues.append(f"{fn}:{ln} 义项疑似英文残留「{core}」：{word}")
                    if word in entries:
                        dups.setdefault(word, []).append(f"{fn}:{ln}")
                    # 常考义排到最前，* 标记保留到输出层再转成 ★
                    senses.sort(key=lambda s: 0 if s.startswith("*") else 1)
                    entries[word] = Entry(word, pos, senses, level, note)
        for w, locs in dups.items():
            issues.append(f"词条重复，后出现者覆盖前者：{w}（{'; '.join(locs)}）")
        # 词形索引。顺序很重要：
        #   先让规则屈折（_forms）占坑，再用不规则表兜底补齐 _forms 生成不出来的
        #   （went / left / teeth 这类）。反过来会把规则的活词形挤掉。
        for w in list(entries):
            index.setdefault(w, w)
            for form in cls._forms(w):
                index.setdefault(form, w)
        for form, base in IRREGULAR_PAIRS:
            if base in entries:
                index.setdefault(form, base)

        phrases = {w: e for w, e in entries.items() if " " in w}
        max_words = max((len(w.split()) for w in phrases), default=0)
        return cls(entries, index, issues, phrases, max_words)

    @staticmethod
    def _forms(w):
        """由原形生成常见屈折形式。

        多词固定搭配（because of 之类）直接返回空：给短语加 -s / -ing
        只会往索引里塞 "because ofing" 这种永远不会被查到的垃圾键。
        """
        if " " in w:
            return []
        out = []
        if w.endswith("e"):
            out += [w[:-1] + "ing", w[:-1] + "ed", w + "s", w + "d"]
        elif w.endswith(("s", "x", "z", "ch", "sh")):
            out += [w + "es", w + "ing", w + "ed"]
        else:
            out += [w + "s", w + "ing", w + "ed"]
            # 双写末辅音
            if len(w) >= 3 and w[-1] not in VOWELS and w[-1] not in "wxy" \
                    and w[-2] in VOWELS and w[-3] not in VOWELS:
                out += [w + w[-1] + "ing", w + w[-1] + "ed"]
        if w.endswith("y") and len(w) > 2 and w[-2] not in VOWELS:
            out += [w[:-1] + "ied", w[:-1] + "ies"]
        return out

    def lookup(self, token_lower):
        """返回 (原形, Entry) 或 None。"""
        base = self.index.get(token_lower)
        if base is None:
            # 兜底：再跑一遍还原规则（应对词库外的屈折）
            for cand in self._reduce(token_lower):
                if cand in self.entries:
                    return cand, self.entries[cand]
            return None
        return base, self.entries[base]

    def lookup_phrase(self, tokens_lower, i):
        """在 tokens_lower[i] 处尝试匹配固定搭配，返回 (短语, Entry, 占几个词) 或 None。

        为什么需要它：词库里的 17 个固定搭配（because of / rather than…）
        用单词级 lookup 永远查不到，因为 TOKEN_RE 只切出单个英文单词，
        索引里 "because of" 这个键根本不会被访问到。语料里这些搭配实际
        出现了 51 次，全都白丢了。取最长匹配，避免 "as well as" 被切成
        "as well"。
        """
        if not self.phrases or i + 1 >= len(tokens_lower):
            return None
        top = min(self.max_phrase_words, len(tokens_lower) - i)
        for n in range(top, 1, -1):
            cand = " ".join(tokens_lower[i:i + n])
            entry = self.phrases.get(cand)
            if entry is not None:
                return cand, entry, n
        return None

    def attach_phonetics(self, phonetics):
        """把音标挂到每个条目上，返回有音标的条目数。"""
        n = 0
        for entry in self.entries.values():
            entry.phonetic = phonetics.get(entry.word)
            if entry.phonetic:
                n += 1
        return n

    @staticmethod
    def _reduce(w):
        cands = []
        # 所有格：student's / students' 。量过，全语料只有 16 种 20 次，
        # 但它们在未收录清单里占了前排（author's 6 次、students' 6 次），
        # 不剥掉会一直挡着真该补的词。
        if w.endswith("'s"):
            cands.append(w[:-2])
        elif w.endswith("'"):
            cands.append(w[:-1])
        if w.endswith("ies") and len(w) > 4:
            cands.append(w[:-3] + "y")
        # -ier / -iest：辅音 + y 结尾的形容词变比较级时 y 要改成 i，
        # 只剥 -er 会得到 busi / easi 这种既不是词也查不到的中间态。
        if w.endswith("ier") and len(w) > 4:
            cands.append(w[:-3] + "y")
        if w.endswith("iest") and len(w) > 5:
            cands.append(w[:-4] + "y")
        if w.endswith("ing") and len(w) > 5:
            cands += [w[:-3], w[:-3] + "e", w[:-4]]
        if w.endswith("ed") and len(w) > 4:
            cands += [w[:-2], w[:-1], w[:-3]]
        if w.endswith("es") and len(w) > 3:
            cands.append(w[:-2])
        if w.endswith("s") and not w.endswith("ss"):
            cands.append(w[:-1])
        if w.endswith("ly") and len(w) > 4:
            cands.append(w[:-2])
        # 形容词比较级/最高级：cheaper -> cheap、greater -> great。
        # 只补规则屈折不覆盖的那部分（good/bad 这类在 IRREGULAR 里）。
        # 注意会比较级误伤：container 会被拆成 contain，但 contain 在词库里
        # 只是"能查到"，语境上是错的。不过 lookup 的顺序是 _forms -> IRREGULAR ->
        # _reduce，真词优先，所以只有词库里确实没有 container 时才会走到这里。
        # -er / -est 两种剥法都要给：原形以 e 结尾的词（close/late/large）
        # 比较级只加 -r / -st，剥两个字母剩下的是 clos / lat，查不到；
        # 原形不以 e 结尾的（great/cheap）剥两个字母才对，剥一个是 greate 这种。
        if w.endswith("er") and len(w) > 4:
            cands += [w[:-2], w[:-1]]
        if w.endswith("est") and len(w) > 5:
            cands += [w[:-3], w[:-2]]
        return [c for c in cands if len(c) >= 3]

    def __len__(self):
        return len(self.entries)
