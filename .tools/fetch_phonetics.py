# -*- coding: utf-8 -*-
"""一次性工具：从 ipa-dict 拉英文音标，只保留词库实际用到的词，落到 data/phonetics/。

用法：
    python .tools/fetch_phonetics.py            # 默认 en_US
    python .tools/fetch_phonetics.py en_GB      # 换英式音标

为什么要"只保留词库用到的词"：
    上游 en_US.txt 有 3MB / 13 万词条，直接塞进仓库又大又没意义。
    我们只要 data/lexicon/ 里出现过的词，一千多行、几十 KB，
    既能跟着仓库走，也让构建完全不依赖网络。

网络：走 api.github.com 的 raw 模式而不是 raw.githubusercontent.com，
      后者在国内经常连接被掐（RemoteDisconnected），前者一直可用。
      首次下载会缓存到系统临时目录，重跑不用再下。
"""
import http.client
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from core.lexicon import Lexicon                     # noqa: E402

API_RAW = ("https://api.github.com/repos/open-dict-data/ipa-dict/"
           "contents/data/{variant}.txt")
# 多镜像按顺序试。实测国内直连 GitHub（不管是 raw.githubusercontent 还是
# api.github.com 的 raw 模式）都极易在第 3MB 处被掐成 IncompleteRead，
# 重试也未必成功；jsdelivr 的 CDN 反而 2 秒多就能整份拿到，所以放前面。
SOURCES = [
    ("jsdelivr-fastly",
     "https://fastly.jsdelivr.net/gh/open-dict-data/ipa-dict@master/data/{variant}.txt",
     None),
    ("jsdelivr",
     "https://cdn.jsdelivr.net/gh/open-dict-data/ipa-dict@master/data/{variant}.txt",
     None),
    ("github-api-raw", API_RAW, "application/vnd.github.raw"),
]
DEST_DIR = os.path.join(BASE, "data", "phonetics")
CACHE_DIR = os.path.join(tempfile.gettempdir(), "cet4-ipa-cache")


def _fetch(url, accept, timeout=180):
    headers = {"User-Agent": "cet4-word-miner-phonetics"}
    if accept:
        headers["Accept"] = accept
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def download(variant, tries=3):
    """按镜像顺序下载音标表，命中缓存直接返回。"""
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache = os.path.join(CACHE_DIR, f"{variant}.txt")
    if os.path.exists(cache) and os.path.getsize(cache) > 100000:
        print(f"用缓存：{cache}  ({os.path.getsize(cache)/1024/1024:.2f} MB)")
        with open(cache, encoding="utf-8") as f:
            return f.read()

    last = None
    for name, tpl, accept in SOURCES:
        url = tpl.format(variant=variant)
        for i in range(tries):
            try:
                print(f"[{name}] 第 {i+1} 次下载 …")
                t = time.time()
                text = _fetch(url, accept)
                print(f"  OK {len(text)/1024/1024:.2f} MB，用时 {time.time()-t:.0f}s")
                with open(cache, "w", encoding="utf-8") as f:
                    f.write(text)
                return text
            except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
                # HTTPException 必须一起接：连接被中途掐断时抛的是
                # http.client.IncompleteRead，它不是 OSError 的子类，
                # 只写 OSError 的话重试永远轮不到。
                last = e
                print(f"  失败：{type(e).__name__}: {e}")
                if i < tries - 1:
                    time.sleep(3)
        print(f"[{name}] 放弃，换下一个镜像")
    raise SystemExit(f"所有镜像都失败，最后一次错误：{last}")


def parse(text):
    """上游格式：词<TAB>/音标/，多读音以逗号分隔。返回 {词: 第一个音标}。"""
    table = {}
    for line in text.splitlines():
        if not line or "\t" not in line:
            continue
        w, _, pron = line.partition("\t")
        w = w.strip().lower()
        pron = pron.split(",")[0].strip()
        if not w or not pron:
            continue
        if pron.startswith("/") and pron.endswith("/"):
            pron = pron[1:-1]           # 去掉外层斜杠，展示层自己加
        table.setdefault(w, pron)
    return table


def main():
    variant = (sys.argv[1] if len(sys.argv) > 1 else "en_US").strip()
    lex = Lexicon.load(os.path.join(BASE, "data", "lexicon"))
    if not lex.entries:
        raise SystemExit("词库是空的，先确认 data/lexicon/ 下有 .txt")

    want = sorted(w for w in lex.entries if " " not in w)
    print(f"词库 {len(lex.entries)} 条，需要音标的单词型条目 {len(want)} 个")

    table = parse(download(variant))
    print(f"上游音标表 {len(table)} 条")

    os.makedirs(DEST_DIR, exist_ok=True)
    out = os.path.join(DEST_DIR, f"{variant}.txt")

    # 手工补充文件（zz_custom.txt 之类）里已经写过的词不算"缺"，
    # 否则每次跑完都会把手工补齐的词再报一遍，看着像没补上
    manual = set()
    for fn in sorted(os.listdir(DEST_DIR)):
        if not fn.lower().endswith(".txt") or fn == os.path.basename(out):
            continue
        with open(os.path.join(DEST_DIR, fn), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "|" in line:
                    manual.add(line.split("|", 1)[0].strip().lower())

    hit, miss = [], []
    for w in want:
        if w in table or w in manual:
            hit.append(w)
        else:
            miss.append(w)

    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(f"# 英文音标（{variant}）\n")
        f.write("# 格式：单词|音标（不含外层斜杠）\n")
        f.write("# 由 .tools/fetch_phonetics.py 从 open-dict-data/ipa-dict 生成，"
                "只保留 data/lexicon/ 里出现过的词\n")
        f.write("# 这个文件会被脚本整份重写，手改的内容会丢；"
                "要手工改读音请写进 zz_custom.txt\n\n")
        # 只写上游表里真有的词；靠手工文件覆盖的那几个不能写进来，
        # 否则 table[w] 直接 KeyError
        for w in sorted(w for w in want if w in table):
            f.write(f"{w}|{table[w]}\n")

    print(f"\n已写入 {out}")
    print(f"  命中 {len(hit)} / {len(want)}（{len(hit)/max(len(want),1)*100:.1f}%）"
          + (f"，其中 {len(manual)} 个来自手工文件" if manual else ""))
    if miss:
        print(f"  缺音标 {len(miss)} 个：{'、'.join(miss[:40])}"
              + ("…" if len(miss) > 40 else ""))
        print("  这些词在卡片里不显示音标（不会报错），需要的话写进 "
              f"{DEST_DIR}\\zz_custom.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
