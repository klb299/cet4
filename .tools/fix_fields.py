# -*- coding: utf-8 -*-
"""修复 21 条「等级列被搭配顶掉」+ worthy 行尾多竖线的数据错位"""
import os, sys
sys.stdout.reconfigure(encoding='utf-8')
ld = os.path.join(os.path.dirname(__file__), '..', 'data', 'lexicon')

# 词 -> 正确等级（按真题频次与四级考频人工判定）
FIX = {
    'ability': 'A', 'equip': 'B', 'estimate': 'A', 'jealous': 'B',
    'layer': 'A', 'offend': 'B', 'segment': 'B', 'shortage': 'A',
    'spectrum': 'B', 'stake': 'B', 'susceptible': 'C', 'turnover': 'C',
    'versus': 'A', 'warrior': 'C', 'wary': 'C', 'weary': 'C',
    'subordinate': 'C', 'conscience': 'B', 'checkout': 'A',
    'commuter': 'B', 'barely': 'B',
}

changed = []
for fn in sorted(os.listdir(ld)):
    if not fn.endswith('.txt'):
        continue
    p = os.path.join(ld, fn)
    src = open(p, encoding='utf-8').read()
    out, n = [], 0
    for raw in src.split('\n'):
        s = raw.strip()
        parts = s.split('|') if s and not s.startswith('#') else None
        if parts and parts[0] in FIX and len(parts) == 4:
            # 4 段：word|pos|senses|colloc  —— 把 colloc 挪到第 5 段，补回等级
            out.append('%s|%s|%s|%s|%s' % (parts[0], parts[1], parts[2],
                                           FIX[parts[0]], parts[3]))
            n += 1
            changed.append((fn, parts[0], FIX[parts[0]]))
        elif parts and parts[0] == 'worthy' and len(parts) == 6 and parts[5] == '':
            # 行尾多了一个竖线：worthy|pos|senses|LEVEL|colloc|
            out.append('%s|%s|%s|%s|%s' % (parts[0], parts[1], parts[2], 'A', parts[3]))
            n += 1
            changed.append((fn, 'worthy', 'A'))
        else:
            out.append(raw)
    if n:
        open(p, 'w', encoding='utf-8', newline='\n').write('\n'.join(out))
        print('%-22s 修 %d 行' % (fn, n))
print('\n共修', len(changed), '条')
for c in changed:
    print('  ', c)
