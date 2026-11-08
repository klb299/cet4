# -*- coding: utf-8 -*-
"""易混词：找出拼写只差一两个字母的词对（adapt / adopt、form / from、quiet / quite）。

为什么值得做：四级阅读里真正的失分点常常不是"这个词不认识"，而是"这个词我认识，
但看成了另一个词"。卡面上给一行「易混：adapt / adopt」，比再背一遍释义有用。

判定只依赖拼写，不引入词向量之类的依赖：
  · 距离 1：长度相同有一处替换，或长度差 1 有一处删除/插入（adapt→adopt、affect→effect）
  · 距离 2 且等长且为相邻两字母换位（form→from、quiet→quite、casual→causal）
换位错误是手写和阅读里最常见的一类，单独补一条规则比放宽到任意距离 2 更准。
"""
from collections import defaultdict

MAX_PER_WORD = 3
# 4 个字母以下的词不做易混提示：for→far、of→off 这类"差一个字母"的组合
# 在短词里几乎必然成立，全是噪音，真正要提醒的是 adapt/adopt 这种长词。
MIN_LEN = 4


def _edit1(a, b):
    """编辑距离正好为 1。"""
    la, lb = len(a), len(b)
    if la == lb:
        return sum(1 for x, y in zip(a, b) if x != y) == 1
    if abs(la - lb) != 1:
        return False
    short, long_ = (a, b) if la < lb else (b, a)
    for i in range(len(long_)):
        if long_[:i] + long_[i + 1:] == short:
            return True
    return False


def _swap2(a, b):
    """等长且只有相邻两字母换位（form / from）。"""
    if len(a) != len(b):
        return False
    diff = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
    if len(diff) != 2:
        return False
    i, j = diff
    return j == i + 1 and a[i] == b[j] and a[j] == b[i]


def find_confusables(cards, max_per_word=MAX_PER_WORD):
    """返回 {单词: [(易混词, 距离), …]}。

    cards 用来同时提供"词性"与"出现次数"两个排序依据：
    先兄弟同词性（名词错成名词最像），再按真题出现次数降序（常考的先提醒）。

    索引为什么是三条而不是一条：只按首字母分桶会漏掉最经典的两类错误——
    affect / effect（首字母不同）、accept / except（第二位不同）。
    再按"去掉首字母的尾巴"和"去掉第二位的骨架"各建一条索引，
    三个位置上的单字母差就都能拿到候选，再逐个验证。
    """
    words = [c.word for c in cards if " " not in c.word and len(c.word) >= MIN_LEN]
    pos = {c.word: (c.entry.pos or "") for c in cards}
    freq = {c.word: c.count for c in cards}

    by_head = defaultdict(list)   # 同首字母 + 同长度（±1 长度另查，覆盖增删一个字母）
    by_tail = defaultdict(list)   # 首字母可不同，其余完全相同（affect / effect）
    by_skip = defaultdict(list)   # 首字母相同、第二位以外相同（accept / except）
    for w in words:
        by_head[(w[:1], len(w))].append(w)
        if len(w) >= 3:
            by_tail[(len(w), w[1:])].append(w)
            by_skip[(len(w), w[:1], w[2:])].append(w)

    out = defaultdict(list)
    for w in words:
        head, ln = w[:1], len(w)
        cands = []
        pool = set()
        for dl in (-1, 0, 1):
            pool.update(by_head.get((head, ln + dl), ()))
        if len(w) >= 3:
            pool.update(by_tail.get((ln, w[1:]), ()))
            pool.update(by_skip.get((ln, w[:1], w[2:]), ()))
        for other in pool:
            if other == w:
                continue
            if ln == len(other) and _swap2(w, other):
                cands.append((other, 2, 1))
            elif _edit1(w, other):
                cands.append((other, 1, 0))
        if not cands:
            continue
        # 同词性优先 → 距离近优先 → 常考优先
        cands.sort(key=lambda t: (0 if pos.get(t[0]) == pos.get(w) else 1,
                                  t[1], -freq.get(t[0], 0), t[0]))
        out[w] = [(c[0], c[1]) for c in cands[:max_per_word]]
    return dict(out)
