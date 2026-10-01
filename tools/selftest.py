"""轴效插件自检：不开 Aegisub，把 Lua 的核心流程和 Python 段的语法过一遍。

    python tools/selftest.py

覆盖：
  1. lua 语法 + src 里的五段源码能塞回 lua（逐字节一致）
  2. Python 四段语法；lua 里内嵌的和 src 里的一致
  3. 组件环境自检：autotime.py --check（DML provider、两个模型都在）
  4. import_txt：中日各自成行、不合并；同一个 txt 导两次不重复
  5. 2 主次：只选中文那边，日文那边跟着换
  6. 5 同步时间：日文时间复制给中文；句数对不上就停
  7. 3 注释 / 4 屏字：插在选中行下面、时间照抄（开视频时屏字取当前帧 +2 秒）
  8. 6 歌词定位：开始铺辅助线出示例 → 记录吸附后写进样式 → 取消清干净
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8")

import embed as embedtool          # noqa: E402
import luaharness                  # noqa: E402

LUA = embedtool.LUA
SRC = os.path.join(ROOT, "src")
HOME = r"D:\Video\Aegisub-3.4.2\zhouxiao-autotime"
PY = os.path.join(HOME, "env", "Scripts", "python.exe")

FAILED = []
PASSED = []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(name)
    print(("  OK   " if cond else "  FAIL ") + name + (("   " + str(detail)) if detail and not cond else ""))


def section(title):
    print("\n" + title)


def write_txt(path, lines, bom=False):
    data = ("\ufeff" if bom else "") + "".join(l + "\r\n" for l in lines)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(data)
    return path


CN = ["东京是晴天。", "今天也一起加油吧。", "我回来了。"]
JP = ["東京は晴れです。", "今日も一緒に頑張りましょう。", "ただいま。"]
T1, T2, T3 = (2_000, 5_000), (6_000, 9_000), (10_000, 12_500)
# Aegisub 新建字幕里的 Default：插件没有样式可抄时会拿它当底
DEFAULT_STYLE = {"name": "Default", "fontname": "Arial", "fontsize": 48, "color1": "&H00FFFFFF&",
                 "color2": "&H000000FF&", "color3": "&H00000000&", "color4": "&H00000000&",
                 "bold": False, "italic": False, "underline": False, "strikeout": False,
                 "scale_x": 100, "scale_y": 100, "spacing": 0, "angle": 0, "borderstyle": 1,
                 "outline": 2, "shadow": 2, "align": 2, "margin_l": 10, "margin_r": 10,
                 "margin_t": 10, "margin_b": 10, "encoding": 1}


# 选中行时给的是「现在看到的行号」：插件内部会自己补样式、自己 shift 选中的行号，
# 所以测试里不要预先加偏移，直接数当前字幕里的行号。
ALL_STYLES = ["Text CN", "Text JP", "Text CN Top", "Text JP Top", "OP CN", "OP JP",
              "ED CN", "ED JP", "Insert CN", "Insert JP", "Note", "Screen"]


def row_of(rows, style, text=None):
    """当前字幕里第一个符合条件的行号（Aegisub 的 1 起算），不做任何样式的预偏移"""
    for i, r in enumerate(rows, 1):
        if r.get("class") == "dialogue" and r.get("style") == style and (text is None or r.get("text") == text):
            return i
    raise AssertionError("没有 style=%s text=%s 的行" % (style, text))


def test_source_parity():
    section("1-2. 源码一致性")
    original = embedtool.read(LUA)
    text = original
    for var, name, _ in embedtool.BLOCKS:
        body = embedtool.read(os.path.join(SRC, name))
        if name.endswith(".py"):
            try:
                compile(body, name, "exec")
            except SyntaxError as e:
                check("%s 语法" % name, False, e)
                continue
            check("%s 语法" % name, True)
        text = embedtool.splice(text, var, body)
    check("塞回 lua 后逐字节一致", text == original)
    with open(os.path.join(SRC, "zhouxiao.lua"), encoding="utf-8", newline="") as f:
        check("src/zhouxiao.lua 和线上一致", f.read() == original)
    check("lua 能整体 parse（load）", _lua_syntax_ok(original))


def _lua_syntax_ok(src):
    import lupa.luajit21 as L
    lua = L.LuaRuntime()
    f, err = lua.eval("function(s) local ok, e = load(s) return ok, e end")(src)
    return bool(f)


def test_env():
    section("3. 组件环境")
    if not os.path.exists(PY):
        check("组件 Python 环境", False, "没装（%s）" % PY)
        return
    r = subprocess.run([PY, os.path.join(HOME, "autotime.py"), "--check"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    ok = r.returncode == 0 and "自检通过" in (r.stdout or "")
    check("autotime.py --check", ok, (r.stdout or "") + (r.stderr or ""))


def build(tmp):
    """一次导入中日两份 txt，返回 (h, cn_lines, jp_lines)"""
    h = luaharness.Harness(home=os.path.join(tmp, "home"), video=r"D:\fake\Show S01E03.mkv")
    h.make_subs(styles=[DEFAULT_STYLE],
                dialogue=[{"style": "Default", "text": "x", "start_time": 100, "end_time": 200}])
    cn_txt = write_txt(os.path.join(tmp, "cn.txt"), CN, bom=True)
    jp_txt = write_txt(os.path.join(tmp, "jp.txt"), JP)
    h.dialog = {"__file__": cn_txt}
    rows = h.run("轴效/1 导入 txt")
    h.dialog = {"__file__": jp_txt}
    rows = h.run("轴效/1 导入 txt")
    return h, rows


def test_import(tmp):
    section("4. import_txt：中日各自成行、不合并")
    h, rows = build(tmp)
    dia = h.dialogues(rows)
    cn = [r for r in dia if r["style"] == "Text CN"]
    jp = [r for r in dia if r["style"] == "Text JP"]
    check("中文 3 行、日文 3 行", len(cn) == 3 and len(jp) == 3, (len(cn), len(jp)))
    check("中文行的文字就是原句（没和日文合一行）", [r["text"] for r in cn] == CN)
    check("日文行的文字就是原句", [r["text"] for r in jp] == JP)
    check("导入时时间都是 0", all(r["start_time"] == 0 and r["end_time"] == 0 for r in cn + jp))
    check("图层：日文 0、中文 1", {r["layer"] for r in jp} == {0} and {r["layer"] for r in cn} == {1})
    check("BOM 的 txt 也能读（首行没带 BOM 残留）", cn[0]["text"] == CN[0], repr(cn[0]["text"]))
    check("样式表建了 Text CN / Text JP", {"Text CN", "Text JP"} <= set(h.styles(rows)))

    h.dialog = {"__file__": os.path.join(tmp, "cn.txt")}
    rows = h.run("轴效/1 导入 txt")
    check("同一个 txt 再导一次不重复", len(h.dialogues(rows)) == 7, len(h.dialogues(rows)))


def test_set_kind(tmp):
    section("5. 主次 / 歌词：中日成对切换")
    h, rows = build(tmp)
    dia = h.dialogues(rows)
    idx = [i + 1 for i, r in enumerate(rows) if r.get("style") == "Text CN"]
    rows = h.run("轴效/2 设为次要（顶部）", sel=idx)
    dia = h.dialogues(rows)
    check("中文全变 Text CN Top", {r["style"] for r in dia if r["style"].startswith("Text CN")} == {"Text CN Top"})
    check("日文跟着变 Text JP Top", {r["style"] for r in dia if r["style"].startswith("Text JP")} == {"Text JP Top"})

    rows = h.run("轴效/2 设为 ED 歌词", sel=idx)
    dia = h.dialogues(rows)
    check("再切 ED，两边都跟上", {r["style"] for r in dia if r["style"].startswith(("ED",))} == {"ED CN", "ED JP"})


def test_sync(tmp):
    section("6. 同步时间（日 → 中）")
    h, rows = build(tmp)
    times = [(2_000, 5_000), (6_000, 9_000), (10_000, 12_500)]
    n = 0
    for r in h.refresh():                 # 直接改底层行 = 用户打完轴（下标访问才是改原表）
        if r["style"] == "Text JP":
            r["start_time"], r["end_time"] = times[n]
            n += 1
    rows = h.run("轴效/5 同步时间（中日）")
    cn = [r for r in h.dialogues(rows) if r["style"] == "Text CN"]
    check("中文拿到日文的 3 组时间",
          [(r["start_time"], r["end_time"]) for r in cn] == times,
          [(r["start_time"], r["end_time"]) for r in cn])

    # 句数对不上 → 停下，不写
    h2, rows2 = build(os.path.join(tmp, "short"))
    h2.dialog = {"__file__": write_txt(os.path.join(tmp, "short", "cn2.txt"), CN[:2])}
    rows2 = h2.run("轴效/1 导入 txt")
    before = [(r.get("start_time"), r.get("end_time")) for r in h2.dialogues(rows2)]
    h2.run("轴效/5 同步时间（中日）")
    check("句数对不上时取消了", h2.cancelled is not None)
    check("取消时一行都没动",
          [(r.get("start_time"), r.get("end_time")) for r in h2.dialogues(h2.snapshot())] == before)


def test_insert(tmp):
    section("7. 加注释 / 加屏字")
    h = luaharness.Harness(home=os.path.join(tmp, "home2"), video="", frames=0)
    h.make_subs(styles=[DEFAULT_STYLE],
                dialogue=[{"style": "Text CN", "text": "第一句", "start_time": 1000, "end_time": 3000}])
    rows = h.run("轴效/3 加注释", sel=[row_of(h.snapshot(), "Text CN")])
    dia = h.dialogues(rows)
    note = [r for r in dia if r["style"] == "Note"]
    check("注释插在原行下面", len(note) == 1 and dia.index(note[0]) == dia.index(dia[0]) + 1)
    check("注释时间照抄、文字带「注：」", note[0]["start_time"] == 1000 and note[0]["text"] == "注：", note and note[0]["text"])

    h2 = luaharness.Harness(home=os.path.join(tmp, "home3"), video=r"D:\fake\v.mkv", frames=100)
    h2.make_subs(styles=[DEFAULT_STYLE],
                 dialogue=[{"style": "Text CN", "text": "第一句", "start_time": 1000, "end_time": 3000}])
    rows = h2.run("轴效/4 加屏字", sel=[row_of(h2.snapshot(), "Text CN")])
    scr = [r for r in h2.dialogues(rows) if r["style"] == "Screen"]
    check("屏字插在下面", len(scr) == 1)
    check("屏字取当前帧：ms(100)=4200，时长 2 秒",
          scr and (scr[0]["start_time"], scr[0]["end_time"]) == (4200, 6200),
          scr and (scr[0]["start_time"], scr[0]["end_time"]))
    check("屏字默认放画面正中", scr and "\\pos(960,540)" in scr[0]["text"], scr and scr[0]["text"])


def test_locate(tmp):
    section("8. 歌词定位：开始 → 记录 → 取消")
    h = luaharness.Harness(home=os.path.join(tmp, "home4"), video="")
    h.make_subs(styles=[DEFAULT_STYLE])
    h.dialog = {"k": "OP"}
    rows = h.run("轴效/6 歌词定位：开始")
    dia = h.dialogues(rows)
    guides = [r for r in dia if r["effect"] == "轴效辅助线"]
    marks = [r for r in dia if str(r["effect"]).startswith("轴效定位")]
    check("铺了 2 条辅助线", len(guides) == 2, len(guides))
    check("放了中/日两条示例", len(marks) == 2 and {r["style"] for r in marks} == {"OP CN", "OP JP"})

    # 把日文示例拖到顶部中线上方，记录后应该写进 OP JP 样式
    for r in h.refresh():
        if str(r["effect"]).startswith("轴效定位:OP") and r["style"] == "OP JP":
            r["text"] = "{\\an8\\pos(960,20)}" + str(r["text"]).split("}", 1)[-1]
    rows = h.run("轴效/6 歌词定位：记录")
    st = h.styles(rows)
    check("写进了 OP JP 样式（对齐/边距变了）",
          st["OP JP"]["align"] in range(1, 10) and (st["OP JP"]["margin_t"] or 0) >= 0)
    check("记录后辅助线和示例都清掉了",
          not [r for r in h.dialogues(rows) if str(r.get("effect", "")).startswith(("轴效定位", "轴效辅助线"))])

    h.dialog = {"k": "ED"}
    h.run("轴效/6 歌词定位：开始")
    rows = h.run("轴效/6 歌词定位：取消")
    check("取消后也清干净了",
          not [r for r in h.dialogues(rows) if str(r.get("effect", "")).startswith(("轴效定位", "轴效辅助线"))])


def main():
    print("轴效插件自检（不开 Aegisub）")
    try:
        test_source_parity()
    except Exception as e:
        check("源码一致性", False, e)
    test_env()
    tmp = tempfile.mkdtemp(prefix="zx_selftest_")
    try:
        test_import(tmp)
        test_set_kind(tmp)
        test_sync(tmp)
        test_insert(tmp)
        test_locate(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n通过 %d 项，失败 %d 项" % (len(PASSED), len(FAILED)))
    if FAILED:
        print("失败：\n  " + "\n  ".join(FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
