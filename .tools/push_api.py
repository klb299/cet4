# -*- coding: utf-8 -*-
"""通过 GitHub REST API 推送（git push 走不通时的备用通道）。

什么时候需要它：这台机器直连不了 github.com，只能经由代理访问 api.github.com。
`git push` 走的是 github.com:443，代理会直接 502；而 api.github.com 一直是通的。
所以用 Git Data API 手工搬一次：blob → tree → commit → 更新 ref。

和 .tools/push_github.py 的区别：
  · 那边是"全量重传、一个快照提交"，远端历史会断；
  · 这里只传**变化的文件**，并且把新提交的 parent 指向远端当前 HEAD，
    历史仍然连续，推完 git log 是接得上的。

用法：
    python .tools/push_api.py --token ghp_xxx
    python .tools/push_api.py --token ghp_xxx --dry     # 只列出会变哪些文件
"""
import argparse
import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "https://api.github.com"
BIG = 512 * 1024          # 超过这个大小的文件单独报一下耗时，方便判断是不是卡住了


def api(method, path, token, body=None, tries=4, quiet=False, timeout=180):
    url = path if path.startswith("http") else API + path
    data = json.dumps(body).encode() if body is not None else None
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=data, method=method)
            req.add_header("Authorization", "token " + token)
            req.add_header("Accept", "application/vnd.github+json")
            req.add_header("User-Agent", "cet4-push-api")
            if data:
                req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read().decode("utf-8")
                return r.status, (json.loads(raw) if raw.strip() else {})
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            try:
                payload = json.loads(raw)
            except Exception:
                payload = {"message": raw[:300]}
            if 400 <= e.code < 500:
                return e.code, payload
            last = "HTTP %d %s" % (e.code, payload.get("message", ""))
        except Exception as e:      # noqa: BLE001
            last = str(e)
        if not quiet:
            print("      重试 %d/%d：%s" % (i + 1, tries, last))
        time.sleep(2 * (i + 1))
    raise RuntimeError("API 失败：%s" % last)


def git(*args):
    r = subprocess.run(["git"] + list(args), cwd=BASE, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("git %s 失败：%s" % (" ".join(args), r.stderr))
    return r.stdout


def local_tree():
    """本地仓库里的 (mode, sha, path)，以 HEAD 为准。

    core.quotepath=false 是必须的：默认情况下 git 会把非 ASCII 路径
    转成 "data/2025-2026\346\235\245..." 这种八进制转义串，
    拿去拼 Windows 路径会直接报「文件名、目录名或卷标语法不正确」。
    """
    out = {}
    for line in git("-c", "core.quotepath=false", "ls-tree", "-r", "HEAD").splitlines():
        meta, path = line.split("\t", 1)
        mode, kind, sha = meta.split()
        out[path] = (mode, sha)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--token", default=os.environ.get("GITHUB_TOKEN", ""))
    ap.add_argument("--repo", default="cet4")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--message", default="")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    token = (args.token or "").strip()
    if not token:
        print("缺少 --token")
        return 2

    code, me = api("GET", "/user", token)
    if code != 200:
        print("token 无效：%s %s" % (code, me.get("message")))
        return 2
    owner = me["login"]
    repo_path = "/repos/%s/%s" % (owner, args.repo)

    # 远端当前 HEAD
    code, ref = api("GET", repo_path + "/git/ref/heads/" + args.branch, token)
    if code != 200:
        print("读不到 %s 分支：%s" % (args.branch, ref.get("message")))
        return 2
    head = ref["object"]["sha"]
    code, commit = api("GET", repo_path + "/git/commits/" + head, token)
    base_tree = commit["tree"]["sha"]
    print("远端 HEAD：%s（tree %s）" % (head[:8], base_tree[:8]))

    # 差量
    code, tree = api("GET", repo_path + "/git/trees/" + base_tree + "?recursive=1", token)
    remote = {e["path"]: e["sha"] for e in tree.get("tree", []) if e["type"] == "blob"}
    local = local_tree()
    changed = [p for p, (m, sha) in local.items() if remote.get(p) != sha]
    removed = [p for p in remote if p not in local]
    print("本地 %d 个文件，需要上传 %d 个，删除 %d 个"
          % (len(local), len(changed), len(removed)))
    if not changed and not removed:
        print("远端与本地一致，无需推送。")
        return 0
    total = sum(os.path.getsize(os.path.join(BASE, p)) for p in changed)
    print("待上传合计 %.1f MB" % (total / 1048576))
    for p in sorted(changed, key=lambda x: -os.path.getsize(os.path.join(BASE, x)))[:8]:
        print("  %8.1f KB  %s" % (os.path.getsize(os.path.join(BASE, p)) / 1024, p))

    if args.dry:
        print("\n--dry：到此为止。")
        return 0

    # 逐个建 blob
    entries = []
    t_all = time.time()
    for i, p in enumerate(changed, 1):
        full = os.path.join(BASE, p)
        size = os.path.getsize(full)
        # 内容从 git 对象里取，而不是读工作区文件。
        # Windows 上 core.autocrlf=true 会把仓库里的换行存成 LF，而构建产物
        # 落在磁盘上是 CRLF。直接传工作区文件的话，远端 blob 的 sha 永远和
        # 本地 commit 里的 sha 对不上 —— 于是每次推送都会把 4MB 的
        # output/index.html 重新传一遍（哪怕只改了一个 .md）。
        raw = subprocess.run(["git", "cat-file", "blob", local[p][1]],
                             cwd=BASE, capture_output=True).stdout
        t0 = time.time()
        # 4MB 的文件经 base64 是 5.4MB，在这条 23KB/s 的链路上要三分多钟，
        # 用默认 180 秒会被判超时然后重传，越重越慢。大文件单独放宽到 15 分钟。
        code, blob = api("POST", repo_path + "/git/blobs", token,
                         {"content": base64.b64encode(raw).decode("ascii"),
                          "encoding": "base64"},
                         tries=2, timeout=900)
        if code not in (200, 201):
            print("上传失败 %s：%s %s" % (p, code, blob.get("message")))
            return 1
        if blob.get("sha") != local[p][1]:
            print("  提醒：%s 的远端 sha 与本地不一致（%s ≠ %s），下次可能重传"
                  % (p, str(blob.get("sha"))[:8], local[p][1][:8]))
        mode = local[p][0]
        entries.append({"path": p, "mode": mode, "type": "blob", "sha": blob["sha"]})
        if size >= BIG or i % 10 == 0:
            print("  [%d/%d] %s（%.1f KB，%.1fs）"
                  % (i, len(changed), p, size / 1024, time.time() - t0))
    for p in removed:
        entries.append({"path": p, "mode": "100644", "type": "blob", "sha": None})
    print("上传完成，用时 %.1f 秒" % (time.time() - t_all))

    # 建 tree / commit / 更新 ref
    code, new_tree = api("POST", repo_path + "/git/trees", token,
                         {"base_tree": base_tree, "tree": entries})
    if code not in (200, 201):
        print("建 tree 失败：%s %s" % (code, new_tree.get("message")))
        return 1
    msg = args.message or ("同步到最新版：%s" % time.strftime("%Y-%m-%d %H:%M"))
    code, new_commit = api("POST", repo_path + "/git/commits", token,
                           {"message": msg, "tree": new_tree["sha"], "parents": [head]})
    if code not in (200, 201):
        print("建 commit 失败：%s %s" % (code, new_commit.get("message")))
        return 1
    code, upd = api("PATCH", repo_path + "/git/refs/heads/" + args.branch, token,
                    {"sha": new_commit["sha"], "force": False})
    if code not in (200, 201):
        print("更新分支失败：%s %s" % (code, upd.get("message")))
        return 1

    print("\n推送成功：%s -> %s" % (head[:8], new_commit["sha"][:8]))
    print("https://github.com/%s/%s" % (owner, args.repo))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
