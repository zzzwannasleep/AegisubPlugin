"""把 src 里的真源码塞回 zhouxiao.lua（可反复跑）。

    python tools/embed.py                 # 写入 lua（源码仓库里那份 + 线上那份）
    python tools/embed.py --check         # 只校验：线上 lua 等于「src 容器 + src 内嵌块」吗（不写）
    python tools/embed.py --version 0.25  # 顺便改版本号
    python tools/embed.py --deploy        # 写完再同步到组件目录 zhouxiao-autotime

两份 lua 是一模一样的：`src\\zhouxiao.lua` 是权威版本（容器那部分在这里改），线上那份是它的部署。
只改 AUTOTIME_PY / FXEDIT_PY / ZXCORE_PY / ZXAI_PY / INSTALL_PS1 这五段的正文，
每段的头尾标记和文件其它部分一个字节都不动。
"""
import hashlib
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "src")
SRC_LUA = os.path.join(SRC, "zhouxiao.lua")
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import testconfig as C   # 路径只在这里定义一次；Aegisub 目录不存在时它会报一句人话

BLOCKS = [
    ("AUTOTIME_PY", "autotime.py", True),
    ("FXEDIT_PY", "fxedit.py", False),
    ("ZXCORE_PY", "zxcore.py", False),
    ("ZXAI_PY", "zxai.py", False),
    ("INSTALL_PS1", "install.ps1", True),
]


def read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def write(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.replace(tmp, path)   # 原子替换：中途断了也不会留半个 lua


def splice(text, var, body):
    marker = "\n%s = [==[\n" % var
    at = text.find(marker)
    if at < 0:
        raise SystemExit("README 里那个 lua 里没有内嵌块 %s" % var)
    start = at + len(marker)
    end = text.find("]==]", start)
    if end < 0:
        raise SystemExit("内嵌块没结尾：%s" % var)
    return text[:start] + body + text[end:]


def main():
    check = "--check" in sys.argv
    deploy = "--deploy" in sys.argv
    version = sys.argv[sys.argv.index("--version") + 1] if "--version" in sys.argv else None

    lua = C.lua_path()
    live = read(lua) if os.path.exists(lua) else None
    # 权威版本是仓库里的 src\zhouxiao.lua（Lua 那部分在这里改）；线上那份是它的部署，两份必须一样
    base = read(SRC_LUA) if os.path.exists(SRC_LUA) else (live or "")
    if not base:
        raise SystemExit("src\\zhouxiao.lua 和线上 lua 都没有，先放一份进去")
    text = base

    for var, name, bom in BLOCKS:
        body = read(os.path.join(SRC, name))
        if name.endswith(".py"):
            compile(body, name, "exec")          # 语法不过就别塞
        if "]==]" in body:
            raise SystemExit("%s 里出现了 ]==]，会把内嵌块提前截断" % name)
        if body.startswith("\ufeff"):
            raise SystemExit("%s 不能带 BOM（BOM 由 Lua 写文件时加，见 %s）" % (name, var))
        text = splice(text, var, body)

    if version:
        if not re.match(r"^\d+(\.\d+)*$", version):
            raise SystemExit("版本号长得不对：%s" % version)
        text, n = re.subn(r'script_version = "[\d.]+"', 'script_version = "%s"' % version, text)
        if n != 1:
            raise SystemExit("script_version 找到了 %d 处，应该是 1 处" % n)
        write(SRC_LUA, text)                     # 容器里也改掉，不然两边又不一样
        with open(os.path.join(SRC, "VERSION"), "w", encoding="utf-8", newline="\n") as f:
            f.write(version + "\n")
        print("版本 -> %s（lua 和 src/VERSION 都改了）" % version)

    if check:
        if live is None:
            print("线上 lua 不存在：%s" % lua)
            return 1
        if live == text:
            print("OK  src（容器 + 内嵌块）和线上 lua 逐字节一致  %s"
                  % hashlib.sha256(text.encode("utf-8")).hexdigest()[:12])
            return 0
        print("不一样！")
        print("  src 算出来  %s" % hashlib.sha256(text.encode("utf-8")).hexdigest())
        print("  线上现在    %s" % hashlib.sha256(live.encode("utf-8")).hexdigest())
        for var, name, _ in BLOCKS:
            old, new = read_blk(live, var), read_blk(text, var)
            if old != new:
                print("  差在 %s（线上 %d 字符，src 里 %d 字符）" % (var, len(old), len(new)))
        if splice_free(live) != splice_free(text):
            print("  差在 Lua 主体（容器）——两份对不上，跑 tools/embed.py 覆盖线上那份")
        return 1

    if text == base and live == text and not deploy:
        print("lua 没变化，不用写")
    else:
        write(SRC_LUA, text)
        write(lua, text)
        print("写入 %s 和 %s（各 %d 字符）" % (SRC_LUA, lua, len(text)))

    if deploy:
        for _, name, _ in BLOCKS:
            if name.endswith(".py"):
                shutil.copyfile(os.path.join(SRC, name), os.path.join(C.component_dir(), name))
                print("  同步组件目录 %s" % name)
    return 0


def splice_free(text):
    """只看容器：把五段内嵌正文挖掉，留下 Lua 那部分"""
    for var, _, _ in BLOCKS:
        marker = "\n%s = [==[\n" % var
        at = text.find(marker)
        if at < 0:
            return text
        start = at + len(marker)
        end = text.find("]==]", start)
        text = text[:start] + "<BODY>" + text[end:]
    return text


def read_blk(text, var):
    marker = "\n%s = [==[\n" % var
    at = text.find(marker)
    start = at + len(marker)
    return text[start:text.find("]==]", start)]


if __name__ == "__main__":
    sys.exit(main())
