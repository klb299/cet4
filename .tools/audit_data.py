# -*- coding: utf-8 -*-
"""词库 / 停用词 数据体检"""
import re, os, sys, collections
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from core import lexicon as L

root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
ldir = os.path.join(root, 'data', 'lexicon')

rows = []          # (file, lineno, word, pos, gloss, level, colloc)
bad = []
for fn in sorted(os.listdir(ldir)):
    if not fn.endswith('.txt'): continue
    p = os.path.join(ldir, fn)
    for i, raw in enumerate(open(p, encoding='utf-8'), 1):
        s = raw.strip()
        if not s or s.startswith('#'): continue
        parts = s.split('|')
        if len(parts) < 5:
            bad.append((fn, i, s, '字段数 %d < 5' % len(parts))); continue
        w = parts[0].strip()
        if not w or not re.fullmatch(r"[a-z][a-z\-']*( [a-z][a-z\-']*)*", w):
            bad.append((fn, i, s, '词形非法: %r' % w)); continue
        lv = parts[3].strip()
        if lv not in ('A','B','C'):
            bad.append((fn, i, s, '等级非法: %r' % lv)); continue
        if not parts[1].strip():
            bad.append((fn, i, s, '缺词性'))
        if not parts[2].strip():
            bad.append((fn, i, s, '缺义项'))
        rows.append((fn, i, w, parts[1].strip(), parts[2].strip(), lv, parts[4].strip()))

print('词条总数(原始行):', len(rows))
print('格式错误行:', len(bad))
for b in bad[:40]:
    print('   ', b)

# ---- 重复 ----
dup = collections.defaultdict(list)
for r in rows: dup[r[2]].append(r)
dups = {k:v for k,v in dup.items() if len(v) > 1}
print('\n重复词条:', len(dups))
for k, v in sorted(dups.items()):
    locs = ', '.join('%s:%d(%s)' % (a,b,f) for a,b,f in v)
    same = len({(r[3], r[4], r[5]) for r in v}) == 1
    print('   %-18s %s  %s' % (k, locs, '定义一致' if same else '>>> 定义冲突'))

# ---- 停用词 ----
sw = set()
swfile = os.path.join(root, 'data', 'stopwords.txt')
for raw in open(swfile, encoding='utf-8'):
    s = raw.strip()
    if not s or s.startswith('#'): continue
    sw.update(s.split())
print('\n停用词数:', len(sw))
swdup = [w for w,c in collections.Counter(
    w for raw in open(swfile, encoding='utf-8')
    for w in (raw.strip().split() if raw.strip() and not raw.strip().startswith('#') else [])
).items() if c > 1]
print('停用词内部重复:', len(swdup), swdup[:30])

lex = {r[2] for r in rows}
both = sorted(lex & sw)
print('\n既在词库又在停用词(词库条目形同废弃):', len(both))
print('  ', both[:60])

# ---- 空搭配 / 空义项统计 ----
nocol = [r for r in rows if not r[6]]
nostar = [r for r in rows if '*' not in r[4]]
print('\n无搭配提示:', len(nocol), ' 无星标常考义:', len(nostar), nostar[:20])

# ---- 等级分布 ----
print('\n等级分布:', collections.Counter(r[5] for r in rows))
