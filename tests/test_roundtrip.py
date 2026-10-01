r"""不开 Aegisub，跑通 0.24 的三页工作台链路：Lua 导出 → Python 算改动 → 写 fx_ops.tsv → Lua 应用。

菜单 7 / 8 / 9 走的是同一条路（zhouxiao.lua 的 workbench）：
    Lua:    dump_subs → 写 fxjob.json → spawn(fxedit.py --job ...) → apply_ops → set_undo_point
    Python: 读 fx_dump.tsv → 用户在窗口里改 → 写 fx_ops.tsv
这里把 spawn 换成假的：Python 那一半直接调 src 里的 fxedit / zxcore 算出 ops，
于是不用开 Aegisub、不弹窗，也能验「一次点击 = 一次撤销点」和 apply_ops 的每条语义。

素材全是合成的（tests\fixtures.py），不绑某一部番；想换成别的卡拉OK模板：
    set ZX_KARA_TEMPLATE=<模板文件路径>

    python tests\test_roundtrip.py
"""
import bootstrap  # noqa: F401
import json
import os
import re
import shutil
import tempfile
import traceback
from collections import Counter
from types import SimpleNamespace

import testconfig as C
import fixtures as F

z, fe, ai = C.load_src()

OK = []
BAD = []


def check(name, cond, detail=""):
    (OK if cond else BAD).append(name)
    print(("  OK   " if cond else "  FAIL ") + name + (("   " + str(detail)) if detail and not cond else ""))


def section(title):
    print("\n" + title)


# ================================================================ 加载 Lua + 假 Aegisub
LUA_MARK = "-- 日志最后一行"          # testconfig.load_lua() 就是用这个记号插钩子的
# 假 subs 表：Aegisub 的 subs[i] 给的是副本，改完要写回 subs[i]，所以读的时候也拷一份
WRAP_LUA = r'''
function(t)
  local s = newproxy(true)
  local mt = getmetatable(s)
  mt.__len = function() return #t end
  mt.__index = function(_, k)
    if k == "insert" then return function(i, l) table.insert(t, i, l) end end
    if k == "delete" then return function(i) table.remove(t, i) end end
    if k == "append" then return function(l) t[#t + 1] = l end end
    local l = t[k]
    if not l then return nil end
    local c = {}
    for a, b in pairs(l) do c[a] = b end
    return c
  end
  mt.__newindex = function(_, k, v) t[k] = v end
  return s
end
'''


def lua_source():
    """从 src\\ 读插件源码；src 不在才退回 testconfig 指的线上文件。

    这里没有直接用 C.load_lua()：它会插 `if ZX_SPAWN then spawn = ZX_SPAWN end`，
    但那行是**加载那一刻**执行的 —— 等 load_lua 返回再设 ZX_SPAWN 已经来不及了
    （spawn 是整块 chunk 的局部量，宏闭包早就把它绑死了）。所以下面自己插同一行钩子，
    只是先把 ZX_SPAWN 摆进全局表再 execute。钩子内容与 testconfig 里的一致。
    """
    p = os.path.join(C.SRC, "zhouxiao.lua")
    return C.read(p) if os.path.exists(p) else C.lua_source()


def template_rows():
    """卡拉OK模板行：优先环境变量 / 仓库里的社区模板，都没有就用合成的最小模板。
    返回 (模板行, 来源)。模板 .ass 里还有它自己的歌词行，只取 template/code 那些 ——
    真实用法也是 z.template_rows() 这么挑的。"""
    for p in (os.environ.get("ZX_KARA_TEMPLATE"), os.path.join(C.FIXTURES, "kara_t1.ass")):
        if p and os.path.exists(p):
            rows = z.template_rows(z.parse_ass(C.read(p))[2])
            if rows:
                return rows, os.path.basename(p)
    # 合成模板只留 syl 级：line 级模板会把源行整行换掉，那样「\k 保留」就没法验了
    synth = [F.template("template syl", r"{\an5\pos($center,$middle)\fad(150,150)\bord2\3c&H203040&}"),
             F.template("template syl", r"{\k}")]
    return z.template_rows(z.parse_ass(F.build_ass(synth))[2]), "合成模板"


class Bench:
    """假 Aegisub：mock 掉 aegisub API，spawn 换成「自己算 fx_ops.tsv」。"""

    def __init__(self, root):
        import lupa.luajit21 as L
        assert root.isascii(), "临时目录带中文时 Lua 的 zx_home() 会退到 ProgramData，测试不好判路径"
        self.user = os.path.join(root, "user")                    # decode_path("?user")
        self.home = os.path.join(self.user, "zhouxiao-autotime")  # Lua 的 zx_home()
        os.makedirs(self.home, exist_ok=True)
        # 有 lite2.txt，ensure_installed 才认为组件装好了；否则它要弹安装框、跑 install.ps1
        with open(os.path.join(self.home, "lite2.txt"), "w", encoding="utf-8") as f:
            f.write("ok")
        self.undos = []       # set_undo_point 收到的名字
        self.logs = []
        self.spawned = []
        self.mode = None      # 跑哪个菜单，决定假 spawn 算哪一页的改动
        self.ops = ""         # 最近一次工作台写出的 fx_ops.tsv
        self.job = None
        self.kara_log = ""
        self.answer = True    # False = 模拟用户点了取消（工作台什么都不写）
        self.lua = L.LuaRuntime(unpack_returned_tuples=True)
        self.lua.globals().ZX_SPAWN = self._spawn
        self._mock_aegisub()
        text = lua_source()
        assert "ZX_SPAWN" not in text and LUA_MARK in text, "zhouxiao.lua 换了样子，钩子插不进去了"
        at = text.index(LUA_MARK)
        self.lua.execute(text[:at] + "if ZX_SPAWN then spawn = ZX_SPAWN end\n" + text[at:])

    def _mock_aegisub(self):
        lua, g = self.lua, self.lua.globals()

        def register(name, desc, fn):
            g.macros[name] = fn

        def log(level, fmt, *args):
            self.logs.append((level, (fmt % args) if args else fmt))

        def cancel(*a):
            raise RuntimeError("aegisub.cancel：%s" % (a[0] if a else ""))

        def display(*a, **kw):
            # 工作台这条路不该弹任何框；弹了就是回归
            raise RuntimeError("这一步不该弹对话框：%r" % (a[0] if a else a,))

        g.macros = lua.table()
        g.aegisub = lua.table_from({
            "register_macro": register,
            "decode_path": lambda p: (self.user + "\\") if p == "?user" else (C.AEGISUB + "\\"),
            "log": log,
            "cancel": cancel,
            "dialog": lua.table_from({"display": display, "open": lambda *a: None}),
            "progress": lua.table_from({"title": lambda *a: None, "task": lambda *a: None,
                                        "set": lambda *a: None, "is_cancelled": lambda *a: False}),
            "project_properties": lambda: lua.table_from({"video_file": os.environ.get("ZX_VIDEO", ""),
                                                          "video_position": 0}),
            "ms_from_frame": lambda f: 0,
            "text_extents": lambda st, text: (len(text) * 40, 40),
            "set_undo_point": lambda name: self.undos.append(name),
            "debug": lua.table_from({"out": lambda *a: None}),
            "unicode": lua.table_from({"char": lambda c: chr(c), "len": lambda s: len(s)}),
        })

    def _spawn(self, cmd, opts=None):
        """Lua 要起 fxedit.py 时走这里：读它写的 fxjob.json，用 src 的 Python 算出 fx_ops.tsv。"""
        self.spawned.append(cmd)
        if "fxedit.py" not in cmd:
            raise AssertionError("这条 spawn 不是工作台：%s" % cmd)
        m = re.search(r'--job "([^"]+)"', cmd)
        job_path = m.group(1) if m else os.path.join(self.home, "fxjob.json")
        # 组件目录跑偏了就说明 decode_path 没按测试的来，后面全白测
        if os.path.normcase(os.path.dirname(job_path)) != os.path.normcase(self.home):
            raise AssertionError("工作台用的不是测试的组件目录：%s" % job_path)
        with open(job_path, encoding="utf-8") as f:
            job = json.load(f)
        self.job = job
        if job["tab"] != self.mode:
            raise AssertionError("菜单 7/8/9 送来的页面是 %s，测试以为在跑 %s" % (job["tab"], self.mode))
        if self.answer:
            self._make_ops(job)
        return 0

    def _make_ops(self, job):
        """工作台里「用户改完点应用」那一下：doc + sel → Edits → fx_ops.tsv"""
        doc = z.Doc(job["dump"])
        sel = [int(i) for i in job["sel"]]
        if self.mode == "fx":
            preset = {q["name"]: q for q in fe.seeds()}["Screen 发光"]
            self.preset = preset
            e = fe.fx_edits(doc, sel, lambda l: preset, POS, z.Measure())
        elif self.mode == "kara":
            tpl, _ = template_rows()
            styles, events = z.Edits().view(doc)
            names = {doc.by_i(i)["style"] for i in sel}
            e, self.kara_log = fe.kara_edits(z.Kara(job["aegisub_dir"]), doc, styles, events, set(sel),
                                             {s: [dict(r, style=s) for r in tpl] for s in names})
        else:
            e = self._ai_edits(doc, sel)
        e.write(job["out"])
        self.ops = C.read(job["out"])

    def _ai_edits(self, doc, sel):
        """AI 助手页：0.24 里「AI 说了什么就改什么」是 fxedit.AiTab.tool() 里的纯逻辑，
        这里给它一个假 app（只要 doc / edits / all_edits），跑的还是 src 里那份代码，
        只是把模型那一端换成本地写好的几次工具调用。"""
        e = z.Edits()
        app = SimpleNamespace(doc=doc, all_edits=lambda: e, edits_changed=lambda: None)
        shim = SimpleNamespace(app=app, edits=e, update_pending=lambda: None,
                               view=lambda: e.view(doc))
        calls = [
            ("set_lines", {"changes": [{"index": sel[0], "text": r"{\blur2}AI 改过的字"}]}),
            ("insert_lines", {"after_index": sel[0], "lines": [
                {"start_ms": 1000, "end_ms": 2000, "style": "AI新样式", "layer": 5,
                 "text": "AI 插的行"}]}),
            ("delete_lines", {"indices": [sel[1]]}),
            ("set_style", {"name": "AI新样式", "fontsize": 77, "color1": "&H0000FFFF&"}),
            ("set_style", {"name": "Text CN", "fontsize": 40}),   # 同名 = 覆盖已有样式
        ]
        for name, arg in calls:
            res = fe.AiTab.tool(shim, name, arg)
            if "待应用" not in res:
                raise AssertionError("AI 工具 %s 没生效：%s" % (name, res))
        # App.apply() 会把当前方案 / 编号写进文件头（fxedit.py 的 apply），这里照做
        e.info.update({"ZX_Catalog": "测试番", "ZX_Number": "8"})
        return e


# ================================================================ 造字幕、跑菜单
INFO = {"PlayResX": "1920", "PlayResY": "1080"}
POS = (700, 300)      # 假装用户在特效页上点了这个位置


def subs_rows(dialogue, styles=None, info=None):
    """Lua 那边 subs 表的内容：文件头 + 样式 + 事件行（fixtures 的行 dict 直接能用）"""
    rows = [{"class": "info", "section": "[Script Info]", "key": k, "value": str(v)}
            for k, v in (INFO if info is None else info).items()]
    for st in (F.ALL_STYLES if styles is None else styles):
        d = {"class": "style", "section": "[V4+ Styles]"}
        d.update(st)
        for k in ("color1", "color2", "color3", "color4"):
            d[k] = z.ass_color(d[k])     # dump_subs 原样写字符串，统一成 Aegisub 的 &H 写法
        rows.append(d)
    for r in dialogue:
        rows.append(dict(r, section="[Events]"))
    return rows


def run_mode(bench, mode, rows, pick):
    """喂一份字幕 → 点菜单 7/8/9 → 返回 (应用前的行, 选中的行号, 应用后的行)"""
    lua = bench.lua
    t = lua.table_from([lua.table_from(r) for r in rows])
    subs = lua.eval(WRAP_LUA)(t)
    before = [dict(t[k]) for k in range(1, len(t) + 1)]
    sel = [i for i, r in enumerate(rows, 1) if r["class"] == "dialogue" and pick(r)]
    bench.mode = mode
    bench.answer = True
    bench.ops = ""
    bench.undos.clear()
    bench.spawned.clear()
    lua.globals().macros[C.MACRO[mode]](subs, lua.table_from(sel), sel[0])
    after = [dict(t[k]) for k in range(1, len(t) + 1)]
    return before, sel, after


# ================================================================ 断言用的小工具
def op_names(text):
    return [line.split("\t", 1)[0] for line in text.splitlines() if line.strip()]


def op_count(text, name):
    return op_names(text).count(name)


def style_ops(text):
    """ops 里的 style 行 → {样式名: 字段列表}"""
    return {line.split("\t")[1]: line.split("\t") for line in text.splitlines() if line.startswith("style\t")}


def dialogue(rows):
    return [r for r in rows if r["class"] == "dialogue"]


def rows_by_actor(rows, actor):
    return [r for r in rows if r.get("actor") == actor]


def check_untouched(label, before, after, actors):
    """这些行不该被动：按 actor 找回来，内容要和应用前一模一样、行数也不能变"""
    for a in actors:
        b, f = rows_by_actor(before, a), rows_by_actor(after, a)
        check("%s：%s 没被动" % (label, a), bool(b) and b == f, (b, f))


def check_row_account(label, before, after, ops_text):
    """apply_ops 的行数账：ins - del + 新样式 + 新文件头 = 总行数变化
    （Lua 就是照这几类 op 增删行的：同名样式是原地覆盖、已存在的文件头键是原地改值）"""
    had_st = {r["name"] for r in before if r["class"] == "style"}
    had_in = {r["key"] for r in before if r["class"] == "info"}
    new_styles = sum(1 for n in style_ops(ops_text) if n not in had_st)
    new_infos = sum(1 for line in ops_text.splitlines()
                    if line.startswith("info\t") and line.split("\t")[1] not in had_in)
    want = len(before) + op_count(ops_text, "ins") - op_count(ops_text, "del") + new_styles + new_infos
    check("%s：ins - del + 新样式 + 新文件头 = 行数变化" % label, len(after) == want,
          (len(before), len(after), want, Counter(op_names(ops_text))))


def check_one_undo(bench, label):
    check("%s：一次点击只留一个撤销点" % label, len(bench.undos) == 1, bench.undos)
    check("%s：撤销点名字是工作台" % label, bench.undos[:1] == ["轴效特效工作台"], bench.undos)


def check_ops_written(bench, label):
    out = bench.job["out"] if bench.job else ""
    check("%s：fx_ops.tsv 写在组件目录里" % label,
          bool(out) and os.path.normcase(os.path.dirname(out)) == os.path.normcase(bench.home), out)
    check("%s：ops 文件存在且非空" % label, bool(bench.ops.strip()), repr(bench.ops[:80]))


# ================================================================ 1. 特效样式页
def fx_fixture():
    """两条屏字（要套预设）+ 一条对白 + 一条歌词（这俩不该动）"""
    return [
        F.row(r"{\pos(300,900)\blur5\an7}旧屏字", style="Screen", start=1000, end=4000, layer=3, actor="屏字A"),
        F.row(r"{\pos(1500,600)\an5}第二屏字", style="Screen", start=6000, end=9000, layer=2, actor="屏字B"),
        F.row(r"{\fad(200,200)}这是对白第一句", style="Text CN", start=5000, end=8000, actor="对白"),
        F.row(r"{\k50}な{\k50}ん{\k50}ど{\k50}も", style="OP JP", start=90540, end=130100,
              effect="karaoke", actor="歌词"),
    ]


def test_fx(bench):
    section("1. 菜单 7 特效样式：屏字套「Screen 发光」")
    rows = subs_rows(fx_fixture())
    before, sel, after = run_mode(bench, "fx", rows, lambda r: r["style"] == "Screen")
    label = "fx"
    print("     选 %d 行，行数 %d → %d，撤销点 %s" % (len(sel), len(before), len(after), bench.undos))
    check_ops_written(bench, label)
    check_one_undo(bench, label)
    check_row_account(label, before, after, bench.ops)

    set_rows = {line.split("\t")[1] for line in bench.ops.splitlines() if line.startswith("set\t")}
    check("fx：ops 只改这两条源行（每行 set 三个字段 + 插一行）",
          set_rows == {str(i) for i in sel} and op_count(bench.ops, "ins") == 2,
          (set_rows, sel, Counter(op_names(bench.ops))))

    preset = bench.preset
    want = fe.preset_style(preset)
    got = [r for r in after if r["class"] == "style" and r["name"] == "Screen 发光"]
    check("fx：新建了样式「Screen 发光」", len(got) == 1, [r["name"] for r in after if r["class"] == "style"])
    if got:
        g = got[0]
        # 颜色比 &H 形式、布尔比真假：Lua 的 field() 会把它们归一化
        same = all(g.get(k) == (z.ass_color(want[k]) if k.startswith("color") else want[k]) for k in z.STYLE_F)
        check("fx：新样式和预设逐字段一致（字号 %s / 对齐 %s）" % (g.get("fontsize"), g.get("align")), same,
              {k: (g.get(k), want[k]) for k in z.STYLE_F if g.get(k) != (z.ass_color(want[k]) if k.startswith("color")
                                                                        else want[k])})

    fx_rows = [r for r in dialogue(after) if r["effect"] == "fx层"]
    base_rows = [r for r in dialogue(after) if r["style"] == "Screen 发光" and r["effect"] != "fx层"]
    check("fx：每行各生一层 fx 层行", len(fx_rows) == 2 and len(base_rows) == 2, (len(fx_rows), len(base_rows)))
    # 两层里第一层留在源行上（图层 +1），第二层才是 fx 层行（图层 = 源行图层）
    check("fx：fx 层行的图层号 = 源行图层号", sorted(r["layer"] for r in fx_rows) == [2, 3],
          [r["layer"] for r in fx_rows])
    check("fx：底行图层 +1", sorted(r["layer"] for r in base_rows) == [3, 4], [r["layer"] for r in base_rows])
    glow = r"\bord8\blur10\3c&HFFA040&\1a&HFF&\shad0"
    check("fx：fx 层行文本 = 预设的发光层标签",
          len(fx_rows) == 2 and all(r"\fad(150,150)" in r["text"] and glow in r["text"] for r in fx_rows),
          [r["text"][:80] for r in fx_rows])
    check("fx：fx 层行带用户在窗口里点的 \\pos",
          len(fx_rows) == 2 and all(r"\pos(700,300)" in r["text"] for r in fx_rows),
          [r["text"][:80] for r in fx_rows])
    check("fx：底行文本 = 预设基础层 + 窗口里点的 \\pos",
          len(base_rows) == 2 and all(r"\fad(150,150)\blur0.8" in r["text"] and r"\pos(700,300)" in r["text"]
                                      for r in base_rows),
          [r["text"][:80] for r in base_rows])
    check("fx：源行的 \\an7 保留", any(r"\an7" in r["text"] for r in base_rows),
          [r["text"][:80] for r in base_rows])

    check("fx：没选中的对白、歌词一个字没动",
          all(r["text"] in (r"{\fad(200,200)}这是对白第一句", r"{\k50}な{\k50}ん{\k50}ど{\k50}も")
              for r in dialogue(after) if r["actor"] in ("对白", "歌词")))
    check_untouched(label, before, after, ("对白", "歌词"))
    changed = {"Screen 发光"}
    for n, r in {x["name"]: x for x in before if x["class"] == "style"}.items():
        if n not in changed:
            f = [x for x in after if x["class"] == "style" and x["name"] == n]
            check("fx：样式 %s 没被动" % n, f == [r], (r, f))


# ================================================================ 2. 卡拉OK页
def kara_fixture():
    """两句合成 OP 日文歌词（带 \\k）+ 一条不该动的对白"""
    return [
        F.row(r"{\k71}Na{\k27}n{\k26}do {\k20}mo {\k21}ta{\k17}chi", style="OP JP", start=90540,
              end=130100, effect="karaoke", actor="源行1"),
        F.row(r"{\k38}Ta{\k22}i{\k39}se{\k38}tsu {\k20}na", style="OP JP", start=140000,
              end=160000, effect="karaoke", actor="源行2"),
        F.row(r"{\fad(200,200)}这是对白第一句", style="Text CN", start=5000, end=8000, actor="对白"),
    ]


def test_kara(bench):
    section("2. 菜单 8 卡拉OK特效：合成歌词套模板")
    tpl, src = template_rows()
    tpl_n = len(z.template_rows(tpl))
    print("     模板：%s，template/code 行 %d" % (src, tpl_n))
    fix = kara_fixture()
    rows = subs_rows(fix)
    before, sel, after = run_mode(bench, "kara", rows, lambda r: r["style"] == "OP JP")
    label = "kara"
    print("     选 %d 行，行数 %d → %d，撤销点 %s" % (len(sel), len(before), len(after), bench.undos))
    check_ops_written(bench, label)
    check_one_undo(bench, label)
    check_row_account(label, before, after, bench.ops)
    check("kara：模板引擎没报没模板", "没有模板" not in bench.kara_log, bench.kara_log[:200])

    # 源行只能按「Comment + karaoke」认：生成的 fx 行会连 actor 一起继承过去（kara-templater 的行为）
    d = dialogue(after)
    srcs = [r for r in d if r["effect"] == "karaoke"]
    check("kara：两句源行都还在", len(srcs) == 2, len(srcs))
    check("kara：源行变成了 Comment", len(srcs) == 2 and all(r["comment"] is True for r in srcs),
          [r["comment"] for r in srcs])
    want_k = [re.findall(r"\\k(\d+)", r["text"]) for r in fix if r["style"] == "OP JP"]
    got_k = [re.findall(r"\\k(\d+)", r["text"]) for r in srcs]
    check("kara：源行的 \\k 一个没丢", got_k == want_k, (got_k, want_k))

    fx_rows = [r for r in d if r["effect"] == "fx"]
    tp = [r for r in d if r["comment"] is True and re.match(r"\s*(template|code|mixin)\b", r["effect"], re.I)]
    check("kara：生成了 fx 行", len(fx_rows) > 0, len(fx_rows))
    check("kara：fx 行 + 模板行 = ops 里的 ins 数",
          len(fx_rows) + len(tp) == op_count(bench.ops, "ins"), (len(fx_rows), len(tp)))
    check("kara：fx 行都没被标成注释", bool(fx_rows) and all(r["comment"] is False for r in fx_rows))

    for n, r in enumerate(srcs, 1):
        i = next(k for k, x in enumerate(d) if x is r)
        check("kara：第 %d 句源行的 fx 行紧跟其后" % n,
              i + 1 < len(d) and d[i + 1]["effect"] == "fx",
              [x["effect"] for x in d[i:i + 3]])

    check("kara：模板行条数和模板文件里一致（%d）" % tpl_n, len(tp) == tpl_n, len(tp))
    check("kara：模板行带上了所选行的样式", bool(tp) and {r["style"] for r in tp} <= {"OP JP"},
          {r["style"] for r in tp})
    check("kara：模板写在第一句源行前面",
          bool(tp) and next(k for k, x in enumerate(d) if x is tp[0]) < next(k for k, x in enumerate(d) if x is srcs[0]),
          [x["effect"] for x in d[:8]])

    check_untouched(label, before, after, ("对白",))
    check("kara：文件头没变",
          [r for r in after if r["class"] == "info"] == [r for r in before if r["class"] == "info"])


# ================================================================ 3. AI 助手页
def ai_fixture():
    return [
        F.row(r"{\fad(200,200)}这是对白第一句", style="Text CN", start=5000, end=8000, actor="改我"),
        F.row(r"{\fad(200,200)}这是对白第二句", style="Text CN", start=8500, end=9500, actor="删我"),
        F.row(r"{\fad(200,200)}これが最初のセリフ", style="Text JP", start=5000, end=8000, layer=1, actor="不动"),
    ]


def test_ai(bench):
    section("3. 菜单 9 AI 助手：改 / 插 / 删 / 新样式 / 覆盖样式 / 文件头")
    rows = subs_rows(ai_fixture())
    before, sel, after = run_mode(bench, "ai", rows, lambda r: r["style"] == "Text CN")
    label = "ai"
    print("     选 %d 行，行数 %d → %d，撤销点 %s" % (len(sel), len(before), len(after), bench.undos))
    check_ops_written(bench, label)
    check_one_undo(bench, label)
    check_row_account(label, before, after, bench.ops)

    c = Counter(op_names(bench.ops))
    check("ai：ops = set 1 / del 1 / ins 1 / style 2 / info 2",
          (c["set"], c["del"], c["ins"], c["style"], c["info"]) == (1, 1, 1, 2, 2), c)

    d = dialogue(after)
    check("ai：改的那行按 ops 改了文字",
          [r["text"] for r in d if r["actor"] == "改我"] == [r"{\blur2}AI 改过的字"],
          [r["text"] for r in d if r["actor"] == "改我"])
    check("ai：删的那行没了", not [r for r in d if r["actor"] == "删我"])
    ins = [r for r in d if r["text"] == "AI 插的行"]
    check("ai：插的行样式 / 图层对",
          len(ins) == 1 and ins[0]["style"] == "AI新样式" and ins[0]["layer"] == 5,
          [(r["style"], r["layer"]) for r in ins])

    styles = {r["name"]: r for r in after if r["class"] == "style"}
    check("ai：新样式「AI新样式」建出来了", "AI新样式" in styles and styles["AI新样式"]["fontsize"] == 77,
          styles.get("AI新样式"))
    check("ai：新样式颜色按 ops 归一化", "AI新样式" in styles and styles["AI新样式"]["color1"] == "&H0000FFFF&",
          styles.get("AI新样式", {}).get("color1"))
    n_st_before = len([r for r in before if r["class"] == "style"])
    n_st_after = len([r for r in after if r["class"] == "style"])
    check("ai：同名样式「Text CN」是原地覆盖（字号 40，样式只多出新建的那一条）",
          styles["Text CN"]["fontsize"] == 40 and n_st_after == n_st_before + 1,
          (styles["Text CN"]["fontsize"], n_st_before, n_st_after))

    infos = {r["key"]: r["value"] for r in after if r["class"] == "info"}
    check("ai：文件头写进了方案 / 编号", infos.get("ZX_Catalog") == "测试番" and infos.get("ZX_Number") == "8", infos)
    check("ai：原有文件头没被动", infos.get("PlayResX") == "1920" and infos.get("PlayResY") == "1080", infos)

    check_untouched(label, before, after, ("不动",))


# ================================================================ 4. 点取消不该改字幕
def test_cancel(bench):
    section("4. 用户点取消（工作台没写 ops）：一行都不该动，也不留撤销点")
    rows = subs_rows(fx_fixture())
    lua = bench.lua
    t = lua.table_from([lua.table_from(r) for r in rows])
    subs = lua.eval(WRAP_LUA)(t)
    before = [dict(t[k]) for k in range(1, len(t) + 1)]
    sel = [i for i, r in enumerate(rows, 1) if r["class"] == "dialogue" and r["style"] == "Screen"]
    bench.mode, bench.answer, bench.undos = "fx", False, []
    lua.globals().macros[C.MACRO["fx"]](subs, lua.table_from(sel), sel[0])
    after = [dict(t[k]) for k in range(1, len(t) + 1)]
    check("取消：没写 ops 文件", not os.path.exists(os.path.join(bench.home, "fx_ops.tsv")))
    check("取消：没设撤销点", bench.undos == [], bench.undos)
    check("取消：字幕一行没动", before == after)


def main():
    print("Lua <-> Python 工作台链路（菜单 7 / 8 / 9）")
    tmp = tempfile.mkdtemp(prefix="zx_rt_")
    try:
        for fn in (test_fx, test_kara, test_ai, test_cancel):
            try:
                fn(Bench(tmp))
            except Exception as e:
                check(fn.__name__, False, "%s\n%s" % (e, traceback.format_exc()))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n通过 %d 项，失败 %d 项" % (len(OK), len(BAD)))
    if BAD:
        print("失败：\n  " + "\n  ".join(BAD))
    return 1 if BAD else 0


if __name__ == "__main__":
    raise SystemExit(main())
