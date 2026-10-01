"""把 zhouxiao.lua 里内嵌的 5 段代码抽出来，写成仓库里的真源码。

    python tools/extract.py [--from <别的 zhouxiao.lua>] [--out <别的 src 目录>]

只读 lua、只写 src，不碰插件目录。抽完请接着跑 tools/embed.py 校验一次：
塞回去必须和原文件逐字节一样，否则说明抽取逻辑动了东西。
"""
import hashlib
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_LUA = r"D:\Video\Aegisub-3.4.2\automation\autoload\zhouxiao.lua"

# (内嵌变量名, 仓库里的文件名, 部署时 Lua 是不是会给它加 BOM)
# BOM 是 Lua 写文件时加的（install.ps1 / autotime.py 不带 BOM，PowerShell 5 会把中文读成乱码），
# 内嵌正文本身干净没有 BOM，所以仓库里的源码也保持无 BOM。
BLOCKS = [
    ("AUTOTIME_PY", "autotime.py", True),
    ("FXEDIT_PY", "fxedit.py", False),
    ("ZXCORE_PY", "zxcore.py", False),
    ("ZXAI_PY", "zxai.py", False),
    ("INSTALL_PS1", "install.ps1", True),
]


def arg(flag, default):
    if flag in sys.argv:
        return sys.argv[sys.argv.index(flag) + 1]
    return default


def slice_block(text, var):
    """返回 (代码起, 代码止, `\\nVAR = [==[` 这个头的位置，`]==]` 这个尾的位置)。"""
    marker = "\n%s = [==[\n" % var
    at = text.find(marker)
    if at < 0:
        raise SystemExit("找不到内嵌块：%s" % var)
    start = at + len(marker)
    end = text.find("]==]", start)
    if end < 0:
        raise SystemExit("内嵌块没结尾：%s" % var)
    return start, end, at, end


def main():
    lua = arg("--from", DEFAULT_LUA)
    out = arg("--out", os.path.join(ROOT, "src"))
    text = open(lua, encoding="utf-8").read()
    os.makedirs(out, exist_ok=True)
    print("从 %s 抽" % lua)
    for var, name, bom in BLOCKS:
        start, end, _, _ = slice_block(text, var)
        body = text[start:end].removeprefix("\ufeff")  # lua 里本来就该是干净的
        if var != "INSTALL_PS1":
            compile(body, name, "exec")  # Python 段必须是能编译的
        p = os.path.join(out, name)
        with open(p, "w", encoding="utf-8", newline="") as f:
            f.write(body)
        h = hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]
        print("  %-13s -> %-13s %6d 字符  %s" % (var, name, len(body), h))

    m = re.search(r'script_version = "([\d.]+)"', text)
    vp = os.path.join(out, "VERSION")
    with open(vp, "w", encoding="utf-8", newline="\n") as f:
        f.write(m.group(1) + "\n")
    print("  %-13s -> %-13s %s" % ("script_version", "VERSION", m.group(1)))

    with open(os.path.join(out, "zhouxiao.lua"), "w", encoding="utf-8", newline="") as f:
        f.write(text)
    print("  %-13s -> %-13s %6d 字符" % ("(整个 lua)", "zhouxiao.lua", len(text)))
    print("\n搞定。接着跑： python tools/embed.py --check")


if __name__ == "__main__":
    main()
