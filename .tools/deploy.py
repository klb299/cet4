# -*- coding: utf-8 -*-
"""一条命令把站点推到 GitHub Pages，拿到手机能打开的网址。

用法：
    python .tools/deploy.py --token ghp_xxx
    python .tools/deploy.py --token ghp_xxx --repo cet4-word-miner --branch main
    GITHUB_TOKEN=ghp_xxx python .tools/deploy.py          # 从环境变量读
    python .tools/deploy.py --token ghp_xxx --dry         # 只检查，不推送

它做四件事：
  1. 用 token 换出登录名，确认仓库在不在（不在就建一个 public 仓库）
  2. 把远端历史 fetch 下来，再把当前这份工作区的内容作为**一个新提交接在它后面**
     —— 不用 force push，之前那些提交都还在
  3. 推上去
  4. 打开 Pages（已开则校正发布目录），打印手机可直接访问的地址

为什么不用 .tools/push_github.py：那个脚本走 REST API 逐个文件上传，
远端只会得到一次性的快照，本地这些提交历史全丢。这里用 git 推，历史是连续的。

安全：token 只在本次进程里用到，拼进一次性的 push/fetch URL，
不写入 .git/config，也不打印出来。推完想更保险可以去 GitHub 撤销这个 token。
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "https://api.github.com"
DEFAULT_REPO = "cet4-word-miner"


def sh(args, cwd=BASE, check=True, quiet=False):
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0 and check:
        raise RuntimeError("命令失败：%s\n%s%s" % (" ".join(args[:3]), r.stdout, r.stderr))
    return r


def api(method, path, token, body=None, tries=4):
    """调 GitHub API。网络抖动自动重试，4xx 不重试（那不是抖动）。"""
    url = path if path.startswith("http") else API + path
    data = json.dumps(body).encode() if body is not None else None
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=data, method=method)
            req.add_header("Authorization", "token " + token)
            req.add_header("Accept", "application/vnd.github+json")
            req.add_header("User-Agent", "cet4-word-miner-deploy")
            if data:
                req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read().decode("utf-8")
                return r.status, (json.loads(raw) if raw.strip() else {})
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            try:
                payload = json.loads(raw)
            except Exception:
                payload = {"message": raw[:200]}
            if 400 <= e.code < 500:
                return e.code, payload
            last = "HTTP %d %s" % (e.code, payload.get("message", ""))
        except Exception as e:      # noqa: BLE001  网络层抖动
            last = str(e)
        time.sleep(1.5 * (i + 1))
    raise RuntimeError("API 连续失败：%s" % last)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--token", default=os.environ.get("GITHUB_TOKEN", ""))
    ap.add_argument("--repo", default=DEFAULT_REPO)
    ap.add_argument("--branch", default="", help="默认取远端默认分支，没有则 main")
    ap.add_argument("--dry", action="store_true", help="只检查，不推送")
    args = ap.parse_args()

    token = (args.token or "").strip()
    if not token:
        print("缺少 token。生成方式见 README「上传到 GitHub」一节。")
        return 2

    # 1) 我是谁
    code, me = api("GET", "/user", token)
    if code != 200:
        print("token 无效或没有权限：%s %s" % (code, me.get("message", "")))
        return 2
    owner = me["login"]
    print("登录身份：%s" % owner)

    # 2) 仓库在不在
    code, repo = api("GET", "/repos/%s/%s" % (owner, args.repo), token)
    if code == 404:
        print("仓库不存在，创建 public 仓库 %s/%s …" % (owner, args.repo))
        code, repo = api("POST", "/user/repos", token, {
            "name": args.repo,
            "description": "CET-4 真题词汇本：结合真题原句背单词，可离线使用",
            "private": False,
            "has_issues": True,
            "has_wiki": False,
            "auto_init": False,
        })
        if code not in (200, 201):
            print("创建失败：%s %s" % (code, repo.get("message", "")))
            return 2
    elif code != 200:
        print("读取仓库失败：%s %s" % (code, repo.get("message", "")))
        return 2
    else:
        print("仓库已存在：%s（默认分支 %s）" % (repo["html_url"], repo.get("default_branch")))

    branch = args.branch or repo.get("default_branch") or "main"
    remote = "https://x-access-token:%s@github.com/%s/%s.git" % (token, owner, args.repo)

    # 3) 把远端历史接过来
    #    不用 --depth=1：仓库第一次部署时已经被浅克隆过，再叠一次浅拉
    #    会因为 .git/shallow 与本地已有历史打架而失败，失败后脚本会误判成
    #    "远端是空的"，直接推本地 HEAD —— 于是被 GitHub 以 non-fast-forward 拒绝。
    #    仓库才 2.6MB，完整拉一次没有负担。
    print("拉取远端 %s 的历史 …" % branch)
    fetch = sh(["git", "fetch", remote, branch], check=False)
    has_remote = (fetch.returncode == 0 and sh(
        ["git", "rev-parse", "--verify", "FETCH_HEAD"], check=False).returncode == 0)
    if not has_remote:
        print("  （拉取失败，按空仓库处理）%s" % (fetch.stderr or "").strip()[:200])

    tree = sh(["git", "write-tree"]).stdout.strip()
    name = sh(["git", "config", "user.name"], check=False).stdout.strip() or "deploy"
    mail = sh(["git", "config", "user.email"], check=False).stdout.strip() or "deploy@local"

    if has_remote:
        parent = sh(["git", "rev-parse", "FETCH_HEAD"]).stdout.strip()
        remote_tree = sh(["git", "rev-parse", parent + "^{tree}"]).stdout.strip()
        if remote_tree == tree:
            print("远端内容与本地完全一致，没有需要提交的改动。")
            commit = parent
        else:
            msg = "同步到最新版：%s" % time.strftime("%Y-%m-%d %H:%M")
            commit = sh(["git", "-c", "user.name=" + name, "-c", "user.email=" + mail,
                         "commit-tree", tree, "-p", parent, "-m", msg]).stdout.strip()
            print("生成新提交 %s（父提交 %s）" % (commit[:8], parent[:8]))
    else:
        commit = sh(["git", "rev-parse", "HEAD"]).stdout.strip()
        print("远端还没有提交，直接推本地历史（%s）" % commit[:8])

    if args.dry:
        print("\n--dry：到此为止，没有推送。")
        return 0

    # 4) 推
    print("推送 …")
    push = sh(["git", "push", remote, "%s:refs/heads/%s" % (commit, branch)], check=False)
    if push.returncode != 0:
        err = (push.stdout + push.stderr).strip()
        print("推送失败：\n%s" % err)
        low = err.lower()
        if "connect tunnel failed" in low or "could not connect" in low or "502" in low:
            print("\n这通常是网络问题：git 走的是 github.com:443，被代理挡住了；"
                  "\n而 api.github.com 往往是通的。换 API 通道即可："
                  "\n  python .tools/push_api.py --token <你的token>")
        elif "non-fast-forward" in low:
            print("\n远端有你本地没有的提交。先 git fetch 看看差异，"
                  "或者直接用 python .tools/push_api.py（它会把新提交接在远端 HEAD 后面）。")
        return 1
    print("推送完成。")

    # 5) 打开 Pages
    code, pages = api("GET", "/repos/%s/%s/pages" % (owner, args.repo), token)
    src = {"branch": branch, "path": "/"}
    if code == 404:
        code, pages = api("POST", "/repos/%s/%s/pages" % (owner, args.repo), token,
                          {"source": src})
        print("已开启 GitHub Pages。" if code in (200, 201)
              else "开启 Pages 失败：%s %s" % (code, pages.get("message", "")))
    elif code == 200:
        cur = pages.get("source") or {}
        if cur.get("branch") != branch or cur.get("path") != "/":
            code, pages = api("PUT", "/repos/%s/%s/pages" % (owner, args.repo), token,
                              {"source": src})
            print("已把发布源校正为 %s 根目录（原来是 %s %s）。"
                  % (branch, cur.get("branch"), cur.get("path")))
        else:
            print("Pages 已开启，发布源就是 %s 根目录。" % branch)
    else:
        print("读取 Pages 设置失败：%s %s" % (code, pages.get("message", "")))

    site = "https://%s.github.io/%s/" % (owner, args.repo)
    print("\n" + "=" * 52)
    print("仓库：%s" % repo["html_url"])
    print("网址：%s" % site)
    print("手机：直接打开上面这个链接，Safari/Chrome 里「添加到主屏幕」即可离线用。")
    print("首次发布要等 1~3 分钟，页面才会刷新成新版。")
    print("=" * 52)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
