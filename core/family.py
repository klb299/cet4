# -*- coding: utf-8 -*-
"""词族：把同一个词根的派生词聚在一起（care / careful / careless、produce / production）。

为什么有用：四级阅读里"生词"常常不是完全陌生，而是换个词性就认不出——
认识 produce 却在 production 上卡住，认识 care 却反应不过来 careless。
把同族词挂在卡片上，是把"死记一个词"变成"认识一串词"。

做法刻意保守：只做**后缀剥离**，剥完必须能在词库里查到原形，才认为是一族。
不引入词根词典，也不猜——宁可少连，不能把 career 连到 care 上。
"""
from collections import defaultdict

# (后缀, 剥离后可能需要的还原形式)。顺序即优先级：先匹配到的为准。
RULES = [
    ("ness", ("", "y", "i")),
    ("ment", ("", "e")),
    ("ful", ("", "e")),
    ("less", ("", "e")),
    ("ity", ("", "e", "y")),
    ("tion", ("", "e", "t")),
    ("sion", ("", "e", "t")),
    ("ance", ("ant", "e")),
    ("ence", ("ent", "e")),
    ("ive", ("", "e")),
    ("ize", ("", "e")),
    ("ise", ("", "e")),
    ("ous", ("", "e", "ion")),
    ("al", ("", "e")),
    ("ly", ("", "le")),
]

MIN_BASE = 3        # 原形至少 3 个字母
MIN_DROP = 2        # 至少剥掉 2 个字母，避免 bus → bu 这种


def _candidates(word, suffix, tails):
    stem = word[:-len(suffix)]
    if len(stem) < MIN_BASE:
        return []
    out = []
    for t in tails:
        cand = stem + t
        if t == "y" and stem[-1:] in ("i", "e"):
            cand = stem[:-1] + "y"
        out.append(cand)
    return out


def build_families(words, extra=()):
    """返回 {单词: [(同族词, 关系, 有没有卡片), …]}，关系是 'base' 或 'derived'。

    只连"派生词 → 原形"这一条边，再用并查集把共享同一个原形的词并入一 family。

    extra 是词库里存在、但语料里没出现（因此没有卡片）的词。
    把它们也算进来，是为了让 quick 这种"原形没考过、只考了 quickly"的族也能连上；
    这类成员在卡面上只显示不可点，点了也搜不到卡片。
    """
    words = set(words)
    universe = words | set(extra)
    parent = {w: w for w in universe}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    edge = {}
    for w in universe:
        for suffix, tails in RULES:
            if not w.endswith(suffix) or len(w) - len(suffix) < MIN_DROP:
                continue
            hit = None
            for cand in _candidates(w, suffix, tails):
                if cand in universe and cand != w:
                    hit = cand
                    break
            if hit:
                edge[w] = hit
                union(w, hit)
                break

    groups = defaultdict(set)
    for w in universe:
        groups[find(w)].add(w)

    out = {}
    for w in words:
        members = groups[find(w)] - {w}
        if not members:
            continue
        # 原形排前面：先按"是不是别人派生出来的"区分，再按长度
        def key(x):
            return (0 if x not in edge else 1, len(x), x)
        out[w] = [(m, "base" if m not in edge else "derived", m in words)
                  for m in sorted(members, key=key)[:4]]
    return out
