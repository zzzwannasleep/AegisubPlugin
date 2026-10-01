"""一眼看清现在是什么状态：源码、线上 lua、组件目录、环境，对不对得上。

    python tools/status.py
    python tools/status.py --diff     # 有不一致时把差异列出来
"""
import hashlib
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8")

import embed as embedtool          # noqa: E402

SRC = os.path.join(ROOT, "src")


def h12(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def main():
    lua = embedtool.C.lua_path()
    home = embedtool.C.component_dir()
    lua_raw = embedtool.read(lua) if os.path.exists(lua) else None
    print("源码仓库  %s" % ROOT)
    print("版本      %s" % embedtool.read(os.path.join(SRC, "VERSION")).strip())
    print()
    print("%-14s %-14s %-14s %s" % ("内嵌块", "src 里", "lua 里", "结果"))
    bad = 0
    for var, name, _ in embedtool.BLOCKS:
        src = embedtool.read(os.path.join(SRC, name))
        tag = "OK"
        if lua_raw is None:
            tag = "lua 不存在"
            bad += 1
        else:
            emb = embedtool.read_blk(lua_raw, var)
            if emb != src:
                tag = "不一致！"
                bad += 1
        print("%-14s %-14s %-14s %s" % (var, h12(src), h12(embedtool.read_blk(lua_raw, var)) if lua_raw else "-", tag))
    print()
    if lua_raw is not None:
        v = re.search(r'script_version = "([\d.]+)"', lua_raw).group(1)
        st = os.stat(lua)
        print("线上 lua  %s" % lua)
        print("          %d 字符，版本 %s，改于 %s" % (len(lua_raw), v, _time(st.st_mtime)))
    print()
    print("组件目录  %s" % home)
    drift = []
    for name in ("autotime.py", "fxedit.py", "zxcore.py", "zxai.py", "install.ps1"):
        src = embedtool.read(os.path.join(SRC, name))
        p = os.path.join(home, name)
        if not os.path.exists(p):
            print("  %-22s %10s" % (name, "缺"))
            continue
        disk = embedtool.read(p).removeprefix("\ufeff")
        mark = "同" if disk == src else "旧/被改过"
        if disk != src:
            drift.append(name)
        print("  %-22s %10d  %s  %s" % (name, os.path.getsize(p), _time(os.path.getmtime(p)), mark))
    for name in ("ok.txt", "lite2.txt", "models/base.pt", r"env\Scripts\python.exe", "kara_pack"):
        p = os.path.join(home, name)
        if os.path.exists(p):
            print("  %-22s %10s  %s" % (name, "目录" if os.path.isdir(p) else os.path.getsize(p),
                                        _time(os.path.getmtime(p))))
        else:
            print("  %-22s %10s" % (name, "缺"))
    print()
    if drift:
        print("注意：组件目录里的 %s 和 src 不一样（下次 Aegisub 跑宏时会被覆盖成 src 的版本）。" % "、".join(drift))
    if bad:
        print("有 %d 处对不上：改完 src 记得跑 tools/embed.py 把 lua 更新了" % bad)
        if "--diff" in sys.argv:
            for var, name, _ in embedtool.BLOCKS:
                src = embedtool.read(os.path.join(SRC, name))
                emb = embedtool.read_blk(lua_raw, var)
                if src != emb:
                    import difflib
                    print("\n--- %s ---" % name)
                    for d in list(difflib.unified_diff(emb.splitlines(), src.splitlines(),
                                                       "lua 里的", "src 里的", n=2))[:40]:
                        print(d)
        return 1
    print("src = 线上 lua 的内嵌块；组件目录见上（“同”=一致，跑 tools/selftest.py 做完整回归）")
    return 0


def _time(ts):
    import datetime
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


if __name__ == "__main__":
    sys.exit(main())
