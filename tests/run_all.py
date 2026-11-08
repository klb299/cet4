# -*- coding: utf-8 -*-
"""一次跑完全部回归：主回归 + 边界回归。

用法：
    python tests/run_all.py            # 两套都跑
    python tests/run_all.py all        # 同上
    python tests/run_all.py mobile     # 只跑手机端专项审计

为什么要有这个：原来两套测试要分别记两个文件名，提交前很容易只跑一套。
这里返回非 0 便于挂 CI 或写进 pre-commit。
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable

SUITES = {
    "all": [("数据门禁", "audit_data.py"), ("主回归", "test_all.py"),
            ("边界回归", "test_edge.py")],
    "data": [("数据门禁", "audit_data.py")],
    "edge": [("边界回归", "test_edge.py")],
    "mobile": [("手机端审计", "audit_mobile.py")],
}


def main():
    which = (sys.argv[1] if len(sys.argv) > 1 else "all").lower()
    if which not in SUITES:
        print("可选：%s" % "、".join(SUITES))
        return 2

    failed = []
    for label, script in SUITES[which]:
        path = os.path.join(HERE, script)
        print("\n" + "=" * 56)
        print("%s（%s）" % (label, script))
        print("=" * 56)
        rc = subprocess.call([PY, path])
        if rc != 0:
            failed.append(label)

    print("\n" + "=" * 56)
    if failed:
        print("有失败：" + "、".join(failed))
        return 1
    print("全部通过：" + "、".join(label for label, _ in SUITES[which]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
