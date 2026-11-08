# -*- coding: utf-8 -*-
"""删掉 stopwords 已判定"不该背"、词库里却没有搭配价值的纯虚词条目。

判据（两条同时满足才删）：
  1. 在 data/stopwords.txt 里 —— 也就是官方已经认定"做卡片没有学习价值"
  2. 搭配提示为空或 "—" —— 没有四级常考搭配可教
有搭配的一律留下：have to / in order to / not at all / no longer / along with /
had better / on the other hand / thousands of … 这些对 370 分档是真有用的。

are / is / was / were / been / does / did / has / had 删掉不会漏词：
IRREGULAR_PAIRS 会把它们折回 be / do / have。
"""
import os, sys
sys.stdout.reconfigure(encoding='utf-8')
root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
ld = os.path.join(root, 'data', 'lexicon')

DROP = {
    'are', 'is', 'was', 'were', 'of', 'to', 'its', 'our', 'their',
    'this', 'these', 'those', 'can', 'could', 'may', 'must', 'should', 'will',
    'does', 'did', 'quickly', 'carefully', 'really',
    'three', 'two', 'five', 'essays',
}
NOTE = ('# 注：are / is / was / were / of / to / can / should 这类纯虚词已从词库移出 ——'
        ' stopwords.txt 早就判定它们"做卡片没有学习价值"，留着只会让首页前几张卡变成 they / are。'
        ' 前四个会经 IRREGULAR_PAIRS 折回 be，不漏词。')

sw = set()
for raw in open(os.path.join(root, 'data', 'stopwords.txt'), encoding='utf-8'):
    s = raw.strip()
    if s and not s.startswith('#'):
        sw.update(s.split())

hit, lines = {}, {}
for fn in sorted(os.listdir(ld)):
    if not fn.endswith('.txt'):
        continue
    p = os.path.join(ld, fn)
    src = open(p, encoding='utf-8').read().split('\n')
    keep, dropped = [], []
    for raw in src:
        s = raw.strip()
        if s and not s.startswith('#'):
            w = s.split('|')[0].strip()
            note = s.split('|')[4].strip() if len(s.split('|')) > 4 else ''
            if w in DROP:
                assert w in sw, '%s 不在 stopwords 里，不该删' % w
                assert note in ('', '—', '-'), '%s 有搭配提示 %r，不该删' % (w, note)
                dropped.append(w)
                continue
        keep.append(raw)
    if dropped:
        hit[fn] = dropped
        # 把说明插到本分册注释块末尾
        out = []
        for raw in keep:
            out.append(raw)
        idx = 0
        for i, raw in enumerate(out):
            if raw.strip() and not raw.strip().startswith('#'):
                idx = i
                break
        out.insert(idx, NOTE)
        lines[fn] = out
        open(p, 'w', encoding='utf-8', newline='\n').write('\n'.join(out))

n = 0
for fn, ds in hit.items():
    print('%-22s 删 %2d 个：%s' % (fn, len(ds), ' '.join(sorted(ds))))
    n += len(ds)
print('\n共删 %d 条' % n)
