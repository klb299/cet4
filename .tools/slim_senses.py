# -*- coding: utf-8 -*-
"""精简义项 >=7 条的 34 个词条：去重复、去同义换皮、去边缘义，压到 <=6 条。

为什么值得做：370 分档的卡点不是"义项不够全"，是"义项太多看不完"。
widespread 原来 8 条其实就"广泛"一个意思，worthwhile 8 条里 5 条是"值得"的换皮，
warmth 里还混了一条错的（"生气" —— warmth 没这个意思）。
这类堆砌对背单词是纯噪音。
"""
import os, sys
sys.stdout.reconfigure(encoding='utf-8')
root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
ld = os.path.join(root, 'data', 'lexicon')

# 词 -> 精简后的义项（* 标常考义；顺序即卡面顺序）
SLIM = {
    'way':        '*方法,方式;道路;方面;情况;远远地,大大地',
    'visit':      '*拜访,访问;参观;探望;出诊',
    'walk':       '*走,步行;散步;遛(狗);步态',
    'screen':     '*屏幕;屏风;放映;筛查',
    'watch':      '*观看,注视;观察;当心;手表;看守',
    'water':      '*水;水域,海域;给…浇水;流口水;泪水',
    'warmth':     '*温暖,暖和;热情,友好;温情,亲切',
    'waste':      '*浪费;废物,废料;荒地;消耗;废弃的',
    'well':       '*好,令人满意地;完全地;健康的;井;涌出',
    'subject':    '*主题,题目;学科;主语;受试者;使服从',
    'view':       '*观点,看法;视野;景色;看待,考虑;查看',
    'want':       '*想要,希望;需要;缺少;贫困',
    'weather':    '*天气,气象;气候;经受住;风化',
    'welcome':    '*欢迎;迎接;乐意接受;受欢迎的',
    'track':      '*小路;跑道;轨道;足迹,踪迹;跟踪,追踪',
    'weigh':      '*称重;有…重;权衡,考虑;重压于',
    'weight':     '*重量,体重;重压;重担;重要性;权衡',
    'total':      '*总的,全部的;彻底的;总数,总额;合计,总数达',
    'transfer':   '*转移,调动;转让;转乘,换乘;转录',
    'unite':      '*联合,团结;统一,合并;使结合',
    'widespread': '*普遍的,广泛的;分布广的,蔓延的',
    'stroke':     '*中风;击打;划水,划(船);一笔,一画;抚摸',
    'worthwhile': '*值得做的,值得花时间的;有价值的;合算的',
    'brain':      '*脑,大脑;智力,头脑;脑力;聪明的人',
    'carry':      '*携带,搬运;传播;支撑;具有;刊登',
    'present':    '*礼物;目前,现在;出席的;呈现;提出,颁发',
    'wait':       '*等待,等候;期待;推迟;伺候',
    'rent':       '*租金,房租;租用,出租;租借;地租;撕裂',
    'spot':       '*地点;斑点;污点;少量;发现,认出',
    'stream':     '*小河,溪流;流,一股;潮流;流动,流出;按能力分班',
    'volume':     '*音量;体积,容积;容量;卷,册;大量,许多',
    'wrap':       '*包,裹;缠绕;覆盖;围巾,披肩;包装材料',
    'utility':    '*功用,效用;公用事业;实用的;实用程序',
    'upright':    '*直立的,竖直的;正直的,诚实的;笔直地;竖立物,直立柱',
}

done, missing = {}, set(SLIM)
for fn in sorted(os.listdir(ld)):
    if not fn.endswith('.txt'):
        continue
    p = os.path.join(ld, fn)
    lines = open(p, encoding='utf-8').read().split('\n')
    out, ch = [], []
    for raw in lines:
        s = raw.strip()
        if s and not s.startswith('#'):
            w = s.split('|')[0].strip()
            if w in SLIM:
                parts = s.split('|')
                old_n = len(parts[2].split(';'))
                parts[2] = SLIM[w]
                out.append('|'.join(parts))
                ch.append((w, old_n, len(SLIM[w].split(';'))))
                missing.discard(w)
                continue
        out.append(raw)
    if ch:
        open(p, 'w', encoding='utf-8', newline='\n').write('\n'.join(out))
        done[fn] = ch

n = 0
for fn, ch in done.items():
    for w, a, b in sorted(ch):
        print('  %-12s %2d 义 -> %d 义' % (w, a, b))
        n += 1
print('\n共精简 %d 个词' % n)
if missing:
    print('!! 词库里没找到：', sorted(missing))
