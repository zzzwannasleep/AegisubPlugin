"""跑一遍所有自动测试，一个文件一个子进程（一个崩了不影响别的）。

    python tests\\run_all.py                 # 全跑
    python tests\\run_all.py kara parity     # 只跑名字里带这些词的
    python tests\\run_all.py --py <别的python>

test_gui.py 不在自动套件里（它要弹真窗口、要人看），单跑：
    python tests\\test_gui.py fx
"""
import os
import subprocess
import sys
import time

import bootstrap  # noqa: F401
import testconfig as C  # noqa: E402

SKIP = {"test_gui.py", "run_all.py"}


def main():
    args = [a for a in sys.argv[1:]]
    py = C.PY
    if "--py" in args:
        i = args.index("--py")
        py = args[i + 1]
        del args[i:i + 2]
    pick = [a.lower() for a in args]

    files = sorted(f for f in os.listdir(C.TESTS)
                   if f.startswith("test_") and f.endswith(".py") and f not in SKIP)
    if pick:
        files = [f for f in files if any(p in f.lower() for p in pick)]
    if not files:
        print("没有匹配的测试")
        return 1
    if not os.path.exists(py):
        print("找不到 Python：%s\n用 --py 指定，或设环境变量 ZX_PY" % py)
        return 1

    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    bad = []
    print("用 %s\n" % py)
    for f in files:
        t0 = time.time()
        r = subprocess.run([py, os.path.join(C.TESTS, f)], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=env)
        dt = time.time() - t0
        ok = r.returncode == 0
        tail = ""
        for line in reversed((r.stdout or "").splitlines()):
            if "通过" in line or "失败" in line:
                tail = line.strip()
                break
        if not ok and not tail:
            tail = (r.stderr or "").strip().splitlines()[-1] if (r.stderr or "").strip() else "无输出"
        print("%-4s %-24s %6.1fs  %s" % ("OK" if ok else "FAIL", f, dt, tail))
        if not ok:
            bad.append(f)
            print("---- %s 的输出 ----" % f)
            print((r.stdout or "").rstrip())
            if r.stderr:
                print("---- stderr ----")
                print(r.stderr.rstrip())

    print("\n%d 个测试文件：%d 通过，%d 失败" % (len(files), len(files) - len(bad), len(bad)))
    if bad:
        print("失败：" + "、".join(bad))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
