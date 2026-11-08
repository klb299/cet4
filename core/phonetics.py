# -*- coding: utf-8 -*-
"""音标表：加载与查询。

数据文件放在 data/phonetics/ 下，一行一个词：
    单词|音标          例：abandon|əˈbændən
音标不带外层斜杠（展示层统一补 /…/），允许一个词多行给出多种读音，
后写的覆盖先写的，方便手工修正。

目录下所有 .txt 都会加载，所以可以放 en_US.txt / en_GB.txt，
也可以另开一份 zz_custom.txt 只写想覆盖的词（文件名以 zz_ 开头是为了
按字典序排在最后，后加载的覆盖先加载的）。

关于符号归一化：上游 ipa-dict 给的是**美音音位变体**写法，`ɹ ɫ ɝ ɡ` 这些
符号虽然音理上更准确，但跟国内词书（牛津/朗文/历年四级词汇书）的写法对不上，
学生拿去和自己的书对照会以为看错了。所以加载时统一转成词书写法，
映射表见 LEARNER_MAP。想保留上游原样，传 normalize=False。
"""
import os
import re

_SLASH = "/"

# 上游符号 -> 国内词书通行写法
#   ɹ -> r     美音 r 的音位变体符号，词书一律写 r
#   ɫ -> l     暗 l 变体，词书一律写 l
#   ɡ -> g     U+0261 拉丁小写脚本 g，与 ASCII g 肉眼几乎一样，
#              但复制出去搜不到、跨字体还会缺字，统一成 ASCII
#   ɛ -> e     DRESS 元音，牛津/朗文/柯林斯中文版都写 /e/
#   ɝ -> ɜːr   重读卷舌元音（bird / work），词书写 /ɜːr/
#   ɚ -> ər    非重读卷舌元音（teacher 词尾），词书写 /ər/
#   ᵻ -> ɪ     部分实现用来标弱化的 ɪ
LEARNER_MAP = {
    "\u0279": "r",      # ɹ
    "\u026b": "l",      # ɫ
    "\u0261": "g",      # ɡ
    "\u025b": "e",      # ɛ
    "\u025d": "\u025c\u02d0r",   # ɝ -> ɜːr
    "\u025a": "\u0259r",         # ɚ -> ər
    "\u1d7b": "\u026a",          # ᵻ -> ɪ
}


def normalize(ipa):
    """把上游的美音音位变体符号转成国内词书的通行写法。"""
    if not ipa:
        return ""
    for src, dst in LEARNER_MAP.items():
        if src in ipa:
            ipa = ipa.replace(src, dst)
    return ipa


class Phonetics:
    def __init__(self, table=None, issues=None):
        self.table = table or {}      # word -> ipa（不带斜杠）
        self.issues = issues or []

    @classmethod
    def load(cls, dir_path, normalize_symbols=True):
        table, issues = {}, []
        if not dir_path or not os.path.isdir(dir_path):
            return cls(table, issues)
        for fn in sorted(os.listdir(dir_path)):
            if not fn.lower().endswith(".txt") or fn.startswith("."):
                continue
            path = os.path.join(dir_path, fn)
            with open(path, encoding="utf-8") as f:
                for ln, raw in enumerate(f, 1):
                    line = raw.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "|" not in line:
                        issues.append(f"{fn}:{ln} 缺少 | 分隔，已跳过：{line[:30]}")
                        continue
                    word, _, ipa = line.partition("|")
                    word = word.strip().lower()
                    ipa = ipa.strip().strip(_SLASH).strip()
                    if not word or not ipa:
                        issues.append(f"{fn}:{ln} 缺单词或缺音标，已跳过：{line[:30]}")
                        continue
                    if normalize_symbols:
                        ipa = normalize(ipa)
                    # 按文件名字典序加载，后面的覆盖前面的
                    table[word] = ipa
        return cls(table, issues)

    def get(self, word):
        """查音标。原形查不到时再试一次去屈折，尽量别留空。"""
        if not word:
            return ""
        w = word.strip().lower()
        hit = self.table.get(w)
        if hit:
            return hit
        for cand in _strip_inflection(w):
            hit = self.table.get(cand)
            if hit:
                return hit
        return ""

    def __len__(self):
        return len(self.table)


def _strip_inflection(w):
    """把一个词形往原形方向剥，用于音标兜底（只影响音标，不影响检索）。"""
    out = []
    if w.endswith("ies") and len(w) > 4:
        out.append(w[:-3] + "y")
    if w.endswith("ing") and len(w) > 5:
        out += [w[:-3], w[:-3] + "e"]
    if w.endswith("ied") and len(w) > 4:
        out.append(w[:-3] + "y")
    if w.endswith("ed") and len(w) > 4:
        out += [w[:-2], w[:-1]]
    if w.endswith("es") and len(w) > 4:
        out.append(w[:-2])
    if w.endswith("s") and not w.endswith("ss") and len(w) > 3:
        out.append(w[:-1])
    return [c for c in out if len(c) >= 2]


def looks_like_ipa(s):
    """粗略校验：音标应含音标系字符或至少不是纯英文单词。用于数据体检。"""
    if not s:
        return False
    if re.search(r"[\u0250-\u02AF\u02B0-\u02FF\u03B1-\u03C9\u02CC\u02C8\u02D0]", s):
        return True
    # 少数简单词只有 ASCII（如 "æ" 都能覆盖到，这里是兜底）
    return bool(re.fullmatch(r"[A-Za-zˈˌ.\-]+", s))
