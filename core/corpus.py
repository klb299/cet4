# -*- coding: utf-8 -*-
"""真题语料库：解析结构化真题文本，切分句子，保留题目情境。

结构化标记（.txt / .md 均支持）：
    #### 2024年6月 第1套        <- 一套试卷
    ## 仔细阅读 | Passage One   <- 一个题型块
    @topic 一句话情境说明
    @question 46. What does ...?
    @choice A) ...
    @body
    正文段落……
"""
import os
import re

# 常见缩写，避免被误判为句末
ABBREV = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "mt", "vs", "etc",
    "e.g", "i.e", "e.g.", "i.e.", "inc", "ltd", "co", "u.s", "u.k", "u.n",
    "fig", "no", "approx", "dept", "gov", "jan", "feb", "mar", "apr",
    "jun", "jul", "aug", "sep", "oct", "nov", "dec",
}

SENT_SPLIT = re.compile(r"(?<=[.!?])[\"')\]]?\s+")


class Sentence:
    __slots__ = ("text", "idx", "block", "trans")

    def __init__(self, text, idx, block):
        self.text = text
        self.idx = idx
        self.block = block
        self.trans = ""


# 语料来源：real = 可在公开来源核实的真题片段；sim = 按真题题材人工撰写的仿真语料；
# import = 用户自己放进 data/import/ 的文本，来源未经核实。
# 这个标记必须一路带到卡面上：工具叫「真题词汇」，而 2021-06 ~ 2024-06 这 8 个场次
# 全是仿真语料（占全部词次的 86%）。不标的话，卡面上的「真题出现 6 次」
# 其实是「仿真文里出现 6 次」，频次排序也变得不可信。
SOURCE_NAME = {"real": "真题", "sim": "仿真", "import": "导入"}
SOURCE_ORDER = {"real": 0, "sim": 1, "import": 2}


def detect_source(raw, year=""):
    """从文件头注释判断来源；没有线索时按年份约定兜底。

    判定顺序有讲究：「仿真真题语料」这句话里同时含「仿真」和「真题」，
    所以必须先查「仿真」，否则 8 个仿真场次会被判成真题。
    """
    head = raw[:1500]
    if "仿真" in head:
        return "sim"
    if "真题" in head or "回忆版" in head or "考后整理" in head:
        return "real"
    m = re.match(r"^(\d{4})年", year or "")
    if m:
        # 与 data/2025-2026来源说明.md 的约定一致：2025 年起才存在可核实的真题片段
        return "real" if int(m.group(1)) >= 2025 else "sim"
    return "import"


class Block:
    """一个题型块（一篇文章 / 一段听力材料 / 一篇翻译 / 一篇范文）。"""

    __slots__ = ("section", "title", "year", "set_name", "topic", "questions",
                 "choices", "body", "sentences", "trans", "qtrans", "source")

    def __init__(self, section, title, year, set_name, topic, source="real"):
        self.section = section
        self.title = title
        self.year = year
        self.set_name = set_name
        self.topic = topic or ""
        self.questions = []
        self.choices = []
        self.body = ""
        self.sentences = []
        self.trans = []      # 与 sentences 按序对齐的中文译文
        self.qtrans = []     # 与 questions 按序对齐的题干译文
        self.source = source  # real / sim / import，见 SOURCE_NAME


def split_sentences(text):
    """把段落切成句子，尽量避开缩写与小数点。"""
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    rough = SENT_SPLIT.split(text)
    out = []
    buf = ""
    for seg in rough:
        cand = (buf + " " + seg).strip() if buf else seg
        # 后一段以小写字母开头 → 多半是引号内标点造成的误切，合并回去
        if seg[:1].islower():
            buf = cand
            continue
        last = cand.rstrip(".\"'”)]").split()[-1].lower() if cand.split() else ""
        if last in ABBREV or re.match(r"^[A-Z]$", cand.rstrip(".")[-1:] or " "):
            buf = cand
            continue
        out.append(cand)
        buf = ""
    if buf:
        out.append(buf)
    return [s.strip() for s in out if len(s.strip()) > 2]


def parse_file(path):
    """解析单个语料文件，返回 Block 列表。"""
    with open(path, encoding="utf-8", errors="ignore") as f:
        raw = f.read()

    # 文件级来源：头注释一句话决定整个文件。注释里没线索时（用户自己导入的
    # 结构化文本），下面按块的首个场次年份兜底。
    file_source = detect_source(raw)

    year, set_name = "", ""
    blocks = []
    cur = None
    mode = None  # None / body / question
    buf = []

    def flush_body():
        if cur is not None:
            cur.body = "\n".join(buf).strip()
            cur.sentences = [Sentence(s, i, cur)
                             for i, s in enumerate(split_sentences(cur.body))]
        buf.clear()

    for line in raw.splitlines():
        s = line.strip()
        if s.startswith("####"):
            flush_body()
            head = s.lstrip("#").strip()
            m = re.match(r"^(\d{4})年(\d{1,2})月\s*(.*)$", head)
            if m:
                year = f"{m.group(1)}年{m.group(2)}月"
                set_name = m.group(3).strip() or "第1套"
            else:
                parts = head.split()
                year = parts[0] if parts else head
                set_name = " ".join(parts[1:]) or "第1套"
            cur = None
            mode = None
        elif s.startswith("##"):
            flush_body()
            head = s.lstrip("#").strip()
            if "|" in head:
                section, title = head.split("|", 1)
            else:
                section, title = head, head
            cur = Block(section.strip(), title.strip(), year, set_name, "",
                        source=file_source if file_source != "import"
                        else detect_source("", year))
            blocks.append(cur)
            mode = None
        elif s.startswith("@topic"):
            if cur:
                cur.topic = s.split(None, 1)[1].strip() if len(s.split(None, 1)) > 1 else ""
            mode = None
        elif s.startswith("@question"):
            if cur:
                cur.questions.append(s.split(None, 1)[1].strip()
                                     if len(s.split(None, 1)) > 1 else "")
            mode = None
        elif s.startswith("@choice"):
            if cur:
                cur.choices.append(s.split(None, 1)[1].strip()
                                   if len(s.split(None, 1)) > 1 else "")
            mode = None
        elif s.startswith("@body"):
            mode = "body"
            buf = []
        elif s.startswith("@"):
            mode = None
        else:
            if mode == "body":
                buf.append(line.rstrip())
    flush_body()
    return blocks


def parse_plain_file(path):
    """无结构标记的纯文本：按文件名推断年份与题型。"""
    name = os.path.splitext(os.path.basename(path))[0]
    year = "未标注年份"
    section = "未标注题型"
    m = re.search(r"(20\d{2})[-年]?(\d{1,2})?", name)
    if m:
        year = f"{m.group(1)}年{m.group(2)}月" if m.group(2) else f"{m.group(1)}年"
    for kw in ("听力", "阅读", "选词", "翻译", "写作", "范文", "仔细阅读", "长篇阅读"):
        if kw in name:
            section = kw
            break
    with open(path, encoding="utf-8", errors="ignore") as f:
        paras = [p.strip() for p in re.split(r"\n\s*\n", f.read()) if p.strip()]
    blocks = []
    for i, para in enumerate(paras, 1):
        # 用户扔进 data/import/ 的纯文本：来源无从核实，标 import 而不是 real，
        # 免得它在卡面上冒充「真题原句」。
        b = Block(section, f"第{i}篇", year, "导入素材", "", source="import")
        b.body = para
        b.sentences = [Sentence(s, j, b) for j, s in enumerate(split_sentences(para))]
        blocks.append(b)
    return blocks


def load_corpus(dir_path):
    """加载结构化语料目录；目录下还支持 import/ 子目录放用户导入的纯文本。"""
    blocks = []
    if not os.path.isdir(dir_path):
        return blocks
    for fn in sorted(os.listdir(dir_path)):
        p = os.path.join(dir_path, fn)
        if os.path.isdir(p):
            continue
        if not fn.lower().endswith((".txt", ".md")):
            continue
        blocks += parse_file(p)
    return blocks


def load_translations(dir_path, blocks):
    """把译文按 (年份, 题型, 篇目) 挂到语料块上。

    译文文件与语料文件同构，区别在于正文位置直接写中文，一行一句，
    与对应英文段落的句子顺序对齐；@q 开头的行是题干译文。
    返回 (命中块数, 未匹配到的块, 句数对不上的块)。
    """
    index = {}
    for b in blocks:
        index.setdefault((b.year, b.section, b.title), []).append(b)

    hit, missing, mismatch = 0, [], []

    def attach(cur):
        nonlocal hit
        if not cur:
            return
        key, sents, qs = cur
        targets = index.get(key)
        if not targets:
            missing.append(key)
            return
        for b in targets:
            b.trans = [s.strip() for s in sents if s.strip()]
            b.qtrans = [q.strip() for q in qs if q.strip()]
            if b.trans and len(b.trans) != len(b.sentences):
                mismatch.append((key, len(b.sentences), len(b.trans)))
            for i, sent in enumerate(b.sentences):
                sent.trans = b.trans[i] if i < len(b.trans) else ""
        hit += 1

    if not os.path.isdir(dir_path):
        return hit, missing, mismatch

    for fn in sorted(os.listdir(dir_path)):
        if not fn.lower().endswith((".txt", ".md")):
            continue
        year, cur = "", None
        with open(os.path.join(dir_path, fn), encoding="utf-8", errors="ignore") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                if s.startswith("####"):
                    attach(cur)
                    cur = None
                    head = s.lstrip("#").strip()
                    m = re.match(r"^(\d{4})年(\d{1,2})月", head)
                    year = f"{m.group(1)}年{m.group(2)}月" if m else head.split()[0]
                elif s.startswith("##"):
                    attach(cur)
                    head = s.lstrip("#").strip()
                    if "|" in head:
                        section, title = head.split("|", 1)
                    else:
                        section, title = head, head
                    cur = ((year, section.strip(), title.strip()), [], [])
                elif s.startswith("#"):
                    continue
                elif s.startswith("@q"):
                    if cur:
                        parts = s.split(None, 1)
                        cur[2].append(parts[1].strip() if len(parts) > 1 else "")
                elif cur:
                    cur[1].append(s)
        attach(cur)
    return hit, missing, mismatch


def load_imports(dir_path):
    blocks = []
    if not os.path.isdir(dir_path):
        return blocks
    for fn in sorted(os.listdir(dir_path)):
        p = os.path.join(dir_path, fn)
        if os.path.isdir(p) or re.search(r"(readme|说明|放入)", fn, re.I):
            continue
        if fn.lower().endswith((".txt", ".md")):
            # 带 #### / ## 标记的文件按结构化真题解析，否则按纯文本分段
            with open(p, encoding="utf-8", errors="ignore") as f:
                head = f.read(4000)
            if re.search(r"^\s*(####|##)\s", head, re.M):
                blocks += parse_file(p)
            else:
                blocks += parse_plain_file(p)
        elif fn.lower().endswith(".pdf"):
            blocks += read_pdf(p)
    return blocks


def read_pdf(path):
    """尽力从 PDF 抽取文本；无可用库时返回空并提示。"""
    try:
        import pdfminer.high_level  # noqa
        text = pdfminer.high_level.extract_text(path) or ""
    except Exception:
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(path)
            text = "\n".join(page.get_text() for page in doc)
        except Exception:
            return []
    name = os.path.splitext(os.path.basename(path))[0]
    import tempfile
    tmp = os.path.join(tempfile.gettempdir(), name + ".txt")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    return parse_plain_file(tmp)
