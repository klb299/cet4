# 工程日志（交接必读）

> 给接手的人或 AI：**读完这一页就能改代码，不用先读 4000 行**。
> 迭代历史见 [CHANGELOG.md](CHANGELOG.md)，用户视角的说明见 [README.md](README.md)。
> 最后更新：2026-11-09，对应提交 `69183498`。

---

## 一、如果只能记住五件事

1. **产物是构建出来的，别手改**。`output/` 和根目录 `index.html` 都由 `python run.py` 生成，
   手改下次构建就没了。Pages 直接吃这些文件，所以「改代码 → 构建 → 提交」三步不能省。
2. **页面上有两个"看起来一样其实不是一个"的东西**：`stats.wordCount` 是总数（1635），
   而首屏阶段 `cards.length` 只有 60。任何"共 N 个""约 N 天"都必须用前者。
3. **数据是分段流式下发的**，四段 `<script>` 的执行顺序是有讲究的（见第五节），
   改顺序会静默出错——页面照常显示，只是数字和功能悄悄不对。
4. **语料 86% 是仿真，不是真题**。所有展示与导出都必须标明来源，这条不能为了好看而放宽。
5. **改完一定跑 `python tests/run_all.py`**（216 条，约 3 分钟）。
   它抓的正是过去踩过的坑：词库漏词、屈折残留、首屏数字、精读空白。

---

## 二、这个项目是什么 / 不是什么

| 是 | 不是 |
|---|---|
| 从四级语料里抽词、配真题例句、做成可离线背的网页 | 不是词典，释义只给常考义，不追求全 |
| 面向基础薄弱（370 分区间）的学习工具 | 不是背单词算法的实验场，SRS 很简单（3 档自评 + 间隔） |
| 单文件、可离线、可放 U 盘双击打开 | 不是 Web 应用，没有后端、没有账号、数据全在 localStorage |

线上：<https://klb299.github.io/cet4/>（仓库 `klb299/cet4`，本地目录名仍叫 `cet4-word-miner`）

---

## 三、目录与职责

```
cet4-word-miner/
├─ run.py                构建入口：读数据 → 抽取 → 导出全部产物
├─ core/
│  ├─ lexicon.py         词库加载、词形折回（_reduce / IRREGULAR_PAIRS）、短语匹配
│  ├─ corpus.py          语料解析（## / @topic / @body 标记）、来源判定、译文挂载
│  ├─ extractor.py       核心：扫描语料 → Occurrence → WordCard → 排序；精读段落标注
│  ├─ exporters.py       2723 行，HTML 模板 + 全部前端 JS + MD/CSV/Anki/PWA/入口页
│  ├─ similar.py         易混词（编辑距离 1 / 相邻换位）
│  ├─ family.py          词族（后缀剥离，剥完必须查得到原形）
│  └─ phonetics.py       音标加载与 IPA 合法性检查
├─ data/
│  ├─ lexicon/           16 个 .txt，共 2353 词 ← 词库本体
│  ├─ corpus/            11 个年份 .txt，83 个题型块
│  ├─ translation/       11 个年份 .txt，按块内句序逐行对齐的译文
│  ├─ phonetics/         en_US.txt（脚本整份重写）+ zz_custom.txt（手工覆盖）
│  ├─ reference/         cet4_outline.txt（第三方大纲词表，只用来对账）
│  ├─ import/            用户导入的纯文本，跑 run.py 会自动并进来
│  └─ stopwords.txt      6 类停用词，决定"哪些词不做卡片"
├─ tests/                216 条断言 + CDP 客户端
├─ .tools/               一次性/运维脚本（抓音标、对账、推送、截图）
├─ output/               构建产物（要提交，Pages 直接用）
└─ index.html            入口页（构建生成）
```

---

## 四、构建流水线

```
data/corpus/*.txt ─┐
data/import/*.txt ─┴→ corpus.load_corpus / load_imports → Block[]（每个块 = 一篇文章/一段听力）
                              ↓ corpus.load_translations 把译文按句序挂上去
data/lexicon/*.txt → Lexicon（词条 + 词形索引）
data/phonetics/    → attach_phonetics（缺失不影响构建）
                              ↓
            extractor.extract(lex, blocks, stopwords, coverage)
                              ↓
        cards（1635 张）+ unknown（未收录词）+ total（词次）
                              ↓  sort_cards（按等级 → 次数 → 字母）
        similar.find_confusables / family.build_families 挂到卡上
        extractor.annotate_passages 生成 83 篇精读正文
                              ↓
   exporters.build_html / markdown / csv / anki / unknown / pwa / landing
                              ↓
        output/index.html（4.19MB）、真题词汇表_*.md/.csv、Anki导入包.csv…
```

**命令行**：

```bash
python run.py --no-open                 # 全量构建
python run.py --check                   # 只体检，不出文件（秒级）
python run.py --levels AB --min-count 2 # 只保留 A/B 级、出现 ≥2 次的词
python run.py --only-years 2025年6月    # 只保留某些场次
```

---

## 五、前端契约（改 HTML/JS 前必读）

### 1. 数据分段：四段 `<script>`，顺序不能动

```html
<script>const DATA = {cards: [], stats, posPool, stop, passages: []}</script>
<script>DATA.cards.push(前 60 词)</script>
<script>…主脚本：const cards = DATA.cards、const PASSES = DATA.passages、所有函数…末尾 render()…</script>
<script>DATA.passages.push(全部 83 篇); initPassagePicker(); if (view==='read') renderPassage();</script>
<script>DATA.cards.push(其余 1575 词); reindexCards(); 重建 PH; DATA.allReady = true; render(); initPassagePicker(); if (view==='read') renderPassage();</script>
```

三条硬规则：

- **浏览器要整块下载完一个 `<script>` 才执行它**。所以「把正文挪到前面」如果还在同一个块里，
  等于没挪——这是 2026-11 精读页空白的根因。
- **`reindexCards()` 必须在 `render()` 之前**，否则「难词 (N)」按首屏 60 个词算，之后不更新。
- **`const PASSES = DATA.passages` 拿到的是 head 里那个空数组的引用**，后续 `push` 才有效；
  任何地方把它整体赋值（`DATA.passages = [...]`）都会让 `PASSES` 永远为空。

### 2. `DATA` 结构

| 键 | 内容 | 备注 |
|---|---|---|
| `cards[]` | 词卡，见下 | 流式 push |
| `stats` | 构建期统计（wordCount / coverage / blockCount / yearReal…） | **唯一可信的总数来源** |
| `posPool` | 按「等级\|词性」分的词池，拼写题干扰项用 | |
| `stop` | 停用词数组 | 今日计划补位时跳过 |
| `passages[]` | 83 篇精读（sents / qs / ch / w / n / src） | 单独一段下发 |
| `allReady` | 数据是否到齐 | 只在最后一段置 true |

词卡字段（`WordCard.as_dict`）：
`word / pos / senses / level / levelName / note / phonetic / count / countReal / countSim /
years / yearsReal / yearsSim / sections / confuse / family / examples[]`。
`family` 每项是 `[词, 'base'|'derived', 是否有卡片]`。

### 3. localStorage（用户改了浏览器不会提示，坏数据必须当空处理）

| 键 | 内容 |
|---|---|
| `cet4_mastered_v1` | 已掌握词集合（旧接口，仍维护） |
| `cet4_srs_v1` | `{词: {lv, n, due}}`，lv 0/1/2 |
| `cet4_today_v1` | 今日已学词（同一个词一天只计一次） |
| `cet4_log_v1` | `{日期: {n: 当天词次, m: 当时掌握数}}` ← 学习报告的全部数据来源 |
| `cet4_streak_v1` | `{last, n}` 连续天数 |
| `cet4_fav_v1` / `cet4_search_hist_v1` / `cet4_last_open_v1` / `cet4_tts_rate_v1` | 收藏 / 搜索历史 / 上次打开日 / 语速 |

读取集合统一走 `loadSet()`，写入走 `saveJSON()`；对象类数据用 try-catch 包一层
（`hist` 就是这么读的）。**新增存储键也照这个写**——用户可能手动改过 localStorage，
裸 `JSON.parse` 会整页白屏，这是第二轮踩过的坑。

### 4. 四个视图

`card`（词卡列表）/ `read`（精读）/ `quiz`（做题）/ `report`（学习报告）。
用 `body.view-xxx` 类切换，面板显隐、`.bar` 里的筛选行是否收起都在 CSS 里。

---

## 六、数据格式（改数据看这里）

**词库** `data/lexicon/*.txt`，一行一词：

```
单词|词性|*常考义;次要义|等级A/B/C|搭配提示
abandon|v.|*放弃,中止;抛弃,遗弃|B|abandon oneself to 沉溺于
```

- `*` 标记的义项会在卡面上加粗（四级常考义）
- 等级：A 基础高频（1187）/ B 核心必背（411）/ C 进阶拓展（37）
- 文件按序号加载，可以随时新增 `17_xxx.txt`
- **一个词只能出现一次**，跨文件重复不会有提示，会静默覆盖

**语料** `data/corpus/YYYY-MM.txt`：

```
# 2021年6月 CET-4 第1套（仿真真题语料…）   ← 来源判定就靠这行，见下
#### 2021年6月 第1套
## 听力 | News Report One                ← 题型 | 篇目
@topic 新闻：一座图书馆启动古籍数字化项目
@question 1. What is the report mainly about?
@choice A) …
@body
正文段落…
```

- **来源判定顺序：先查「仿真」再查「真题」**。写反了「仿真真题语料」会被判成真题——
  这是第一轮踩过的坑。没有注释时按年份兜底（≥2025 视为真题）。
- 加新语料：放进 `data/import/`（纯文本也行），构建时会并进来，来源标记为 `import`。

**译文** `data/translation/YYYY-MM.txt`：与语料同结构，`## 题型 | 篇目` 下**按句序逐行对齐**，
`@q` 开头是题干译文。句子数对不上时 `load_translations` 会报 mism，不会硬塞。

**音标** `data/phonetics/en_US.txt` 会被 `.tools/fetch_phonetics.py` 整份重写；
要手工改读音写 `zz_custom.txt`（优先级更高）。

---

## 七、六条不变量（破了就是数据错误）

| 不变量 | 现状 | 谁在守 |
|---|---|---|
| 词库格式合法、无重复、等级只有 A/B/C | 2353 词，0 issue | `audit_data.py` |
| 单词型词条音标 100% | 1624/1624 | 同上 |
| 「大纲内、语料出现过、词库却没有」≤ 30 | **0** | 同上（最灵的一条） |
| 没有屈折形式独立成条（`has` / `books` / `made`） | 0 | 同上 |
| 实词覆盖率 ≥ 95% | 96.5% | 同上 |
| 每块语料都有译文 | 83/83 | 同上 |

**为什么「屈折形式独立成条」是硬错误**：`has` 和 `have` 各算一张卡，出现次数被拆成两半，
`reader` 还会被 `_reduce` 折成 `read`。补词时如果看到 `books` 没收录，应该补 `book`。

---

## 八、已知陷阱（按"你改了什么"组织）

| 你改了什么 | 会坏成什么样 | 怎么避 |
|---|---|---|
| 改了 `.wrap` 的 padding | 所有用 `.wrap` 的容器一起变，筛选区曾经凭空多 105px | 通用容器类加样式前先 `grep` 使用者 |
| 给页面加内容 | 手机首屏点击区被挤到固定底栏下面 | 跑 `tests/audit_mobile.py` |
| 把正文塞回词卡那段脚本 | 精读要等 4MB 下完才有内容（58 秒） | 正文单独一个 `<script>` |
| 用 `cards.length` 当总数 | 首屏显示「已掌握 0/60」「约 2 天走完」 | 用 `stats.wordCount` |
| 让 `renderPassage` 直接取 `PASSES[0]` | 数据未到时抛 TypeError，整块面板空白 | 先判空，给加载提示 |
| 改 `markToday` 的调用位置 | 掌握曲线整体错位（快照慢一天） | 必须在 `known.add/delete` 之后 |
| 新增视图 | 老断言写死 `card:false,read:true…` 会三连败 | 断言改成「有且只有一个 `.on`」 |
| 热力图格子用 `aspect-ratio:1` | 撑满 760px 宽 | 给固定 18px |
| 用参考词表判超纲 | `people`/`online`/`paper` 都不在里面，会把好词降级 | 它只用来**找缺口** |
| 新增 `.cw` 元素但不带 `data-w` | 测试选择器取到 undefined | 选择器写 `.cw[data-w]` |
| 加词不跑音标脚本 | 新词没音标，门禁不过 | `python .tools/fetch_phonetics.py` |

---

## 九、测试与门禁

```bash
python tests/run_all.py          # 216 条：数据门禁 11 + 主回归 133 + 边界 72
python tests/run_all.py data     # 只跑门禁（2 秒）
python tests/audit_mobile.py     # 手机端专项：四档宽度 / 点击区 / 字号
```

- `tests/cdp.py` 是极简 CDP 客户端，会注入 `speechSynthesis` 桩；Chrome 路径按平台探测，
  可用 `CET4_CHROME` 覆盖。
- `tests/test_all.py` 按节组织（A 加载与统计 / C 精读 / H 手机端 / O 离线 / P 学习报告），每条断言都写了
  「如果坏了会怎么样」。
- CI（`.github/workflows/ci.yml`）：数据门禁 → 构建 → 真浏览器回归。
  **不校验「构建产物与仓库一致」**——首页带生成时间戳，每次构建都不同，这项必然失败。

---

## 十、发布（这台机器的网络很特殊）

- 只能访问 `api.github.com`，`github.com:443` 被代理挡（502 / TLS 握手失败），
  **`git push` 永远失败**。用 `.tools/push_api.py`：Git Data API 手工搬 blob → tree → commit → ref，
  只传变化文件，新提交的 parent 指向远端 HEAD，历史连续、不 force。
- 代理**只卡下载不卡上传**：4MB 上传 3~5 秒，下载同样要 40 秒。
- 中文路径要 `git -c core.quotepath=false`，否则 `ls-tree` 输出八进制转义，拼路径直接报错。
- token 需要 `repo` + `workflow` 两个 scope（仓库里有 `.github/workflows`，少 workflow 会被拒推）。
- 部署后**必须用手机尺寸真开一次线上站**：本地 `file://` 全绿，首屏数字那类 bug 只有真机才暴露。

```bash
python run.py --no-open && python tests/run_all.py
git add -A && git commit -m "改了什么"
python .tools/push_api.py --token <token>
```

---

## 十一、当前指标（2026-11-09）

```
词库 2353 词（16 册）        卡片 1635 张        例句 3581 条（真题 423 + 仿真 3158）
语料 83 块（真题 23 / 仿真 60），10309 词次
实词覆盖率 96.5%（5877/6088）  含功能词 64.6%
等级 A 1187 / B 411 / C 37     音标 1624/1624（100%）
易混词 343 个词条              词族 223 个词条
页面 4.19MB，首屏 60 词（约 40KB gzip）→ 1~4.5 秒可见，全量 33.7 秒后台到齐
```

---

## 十二、还欠着的（按优先级）

1. **语料样本薄**：每场只有 1 套（真题实际 3 套）。这是最大的短板，但公开渠道逐字可核实的
   原文就这么多，硬扩只能编——与「不给假句子」的原则冲突，所以没动。
   拿到新原文就丢 `data/import/`，重跑构建，门禁会告诉你哪里要补。
2. **词库 2353 vs 大纲 4427**：没补的 2000 多个词在语料里没出现，收了也不出卡片，纯占体积。
   等语料扩了再说。
3. **9 个题型块正文不足 2 句**、**35 个块没有 `@question`**（多为选词填空 / 长篇阅读，
   官方未公布题干），卡片里「原题」会为空。属于数据缺口，不是 bug。
4. **做题页只做过基础验证**，没像精读那样深挖过流式加载下的表现。

---

## 十三、排障速查

| 现象 | 先查 |
|---|---|
| 线上还是旧版 | 改完有没有重新 `python run.py`？`output/index.html` 提交了吗？Pages 构建 1~3 分钟 |
| 页面空白 / 数字不对 | 控制台 `window.__errs`；`DATA.allReady`；`cards.length` vs `stats.wordCount` |
| 精读没内容 | `PASSES.length`；正文那段 `<script>` 是否被合并回词卡块 |
| 「难词 (N)」数字偏小 | `reindexCards()` 是否在 `render()` 之后才调用 |
| 某个词不出卡 | 是否在 `data/stopwords.txt` 里；词库有没有（`lex.lookup`）；`--min-count` 卡掉了？ |
| 出现次数被拆成两半 | 有没有屈折形式独立成条（`audit_data.py` 会报） |
| 门禁「大纲内未收录」变多 | 跑 `.tools/reconcile_outline.py`，看 `output/词库对账报告.md` |
| 手机版面错乱 | `tests/audit_mobile.py`；`.wrap` 的 padding；页头高度 |
| push 失败 | 是不是 `github.com` 被挡 → 用 `push_api.py`；token 有没有 `workflow` scope |
