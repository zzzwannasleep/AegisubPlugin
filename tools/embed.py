"""把 src 里的真源码塞回 zhouxiao.lua（可反复跑）。

    python tools/embed.py                 # 写入 lua
    python tools/embed.py --check         # 只校验：塞回去和现在一模一样吗（不写）
    python tools/embed.py --version 0.25  # 顺便改版本号
    python tools/embed.py --deploy        # 写完再同步到组件目录 zhouxiao-autotime

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
LUA = r"D:\Video\Aegisub-3.4.2\automation\autoload\zhouxiao.lua"
HOME = r"D:\Video\Aegisub-3.4.2\zhouxiao-autotime"

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

    original = read(LUA)
    text = original

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
        with open(os.path.join(SRC, "VERSION"), "w", encoding="utf-8", newline="\n") as f:
            f.write(version + "\n")
        print("版本 -> %s（lua 和 src/VERSION 都改了）" % version)

    if check:
        a = hashlib.sha256(original.encode("utf-8")).hexdigest()
        b = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if a == b:
            print("OK  src 和 lua 里内嵌的完全一致  %s" % a[:12])
            return 0
        print("不一样！")
        print("  lua 现在    %s" % a)
        print("  塞回去之后  %s" % b)
        for var, name, _ in BLOCKS:
            old = read_blk(original, var)
            new = read_blk(text, var)
            if old != new:
                print("  差在 %s（lua 里 %d 字符，src 里 %d 字符）" % (var, len(old), len(new)))
        return 1

    if text == original and not deploy:
        print("lua 没变化，不用写")
    else:
        write(LUA, text)
        print("写入 %s（%d 字符）" % (LUA, len(text)))

    if deploy:
        for _, name, _ in BLOCKS:
            if name.endswith(".py"):
                shutil.copyfile(os.path.join(SRC, name), os.path.join(HOME, name))
                print("  同步组件目录 %s" % name)
    return 0


def read_blk(text, var):
    marker = "\n%s = [==[\n" % var
    at = text.find(marker)
    start = at + len(marker)
    return text[start:text.find("]==]", start)]


if __name__ == "__main__":
    sys.exit(main())
