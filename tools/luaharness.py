"""用 lupa 模拟 Aegisub 的自动化 API，不开 Aegisub 就能跑插件的 Lua 部分。

这里只搭台子（mock + subs 表），用例在 tools/selftest.py 里。
真正跑之前要注意两件事：
  1. lupa 用的是标准 io 库，打不开含中文的路径，所以测试用的文件都放在纯英文的临时目录里；
  2. 插件里 aegisub.decode_path("?user") 指向哪，它就往哪写 Python 源码，
     所以要指到临时目录，别指到真的组件目录。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import testconfig as C   # noqa: E402  （路径只在 testconfig 里定义）

import lupa.luajit21 as L  # noqa: E402

LUA = None   # 用 lua_path()：别在 import 阶段就要求 Aegisub 目录存在


def lua_path():
    return C.lua_path()


class Harness:
    """加载 zhouxiao.lua，并暴露：macros / rows / styles_by_name / logs / 各种可控开关"""

    def __init__(self, lua_path=None, home=None, video="", frames=None, dialog=None):
        lua_path = lua_path or C.lua_path()
        self.home = home or os.path.join(os.environ.get("TEMP", "."), "zx_selftest_home")
        os.makedirs(self.home, exist_ok=True)
        self.lua = L.LuaRuntime(unpack_returned_tuples=True)
        self.g = self.lua.globals()
        self.cancelled = None      # aegisub.cancel 抛出来的原因
        self.logs = []             # (level, 已经格式化好的文字)
        self.dialog = dialog or {}  # 每个对话框的假答案
        self.dialog_calls = []
        self.undos = []
        self._lines = []
        self._styles = []
        self._setup(video, frames)
        src = open(lua_path, encoding="utf-8").read()
        # 插件用 FFI 的 CreateProcessW 起窗口，测试里换成假的
        cut = src.index("-- 日志最后一行")
        src = src[:cut] + "if ZX_SPAWN then spawn = ZX_SPAWN end\n" + src[cut:]
        self.g.ZX_SPAWN = lambda cmd, opts=None: (self.spawned.append(cmd), 0)[1]
        self.spawned = []
        self.lua.execute(src)

    # ---- mock Aegisub ----
    def _setup(self, video, frames):
        lua = self.lua
        g = self.g
        g.ZX_HOME = self.home

        def log(level, fmt, *args):
            text = fmt % args if args else fmt
            self.logs.append((level, text.rstrip("\n")))

        def cancel(*a):
            self.cancelled = a[0] if a else "cancel"
            raise RuntimeError("aegisub.cancel")

        def display(controls, buttons=None):
            """按控件的名字猜是哪个对话框，答「用户点了确定、没选样式方案」。
            要改答案就设 h.dialog（里面的键会组成返回给 Lua 的 res 表，__file__ 除外）。"""
            self.dialog_calls.append(controls)
            return ("确定", lua.table_from(self.dialog_res()))

        def open_dialog(*a):
            return self.dialog.get("__file__")

        def props():
            return lua.table_from({"video_file": video, "video_position": frames or 0})

        g.macros = lua.table()
        g.aegisub = lua.table_from({
            "register_macro": lambda name, desc, fn: g.macros.__setitem__(name, fn),
            "decode_path": lambda p: (self.home + "\\" if p == "?user" else C.aegisub_dir()),
            "log": log,
            "cancel": cancel,
            "dialog": lua.table_from({"display": display, "open": open_dialog}),
            "progress": lua.table_from({
                "title": lambda *a: None, "task": lambda *a: None,
                "set": lambda *a: None, "is_cancelled": lambda *a: False,
            }),
            "project_properties": props,
            "ms_from_frame": lambda f: f * 42,
            "text_extents": lambda st, text: (len(text) * (st["fontsize"] or 48), (st["fontsize"] or 48)),
            "set_undo_point": lambda name: self.undos.append(name),
            "debug": lua.table_from({"out": lambda *a: None}),
            "unicode": lua.table_from({"char": lambda c: chr(c), "len": lambda s: len(s)}),
            "util": lua.table_from({}),
        })

    # ---- 造字幕 ----
    def dialog_res(self):
        """对话框的默认答案：每个字段都给个有意义的空值，再叠上 h.dialog 里指定的。
        样式方案框默认「不用方案」（ZX_Catalog 记成 '-'），歌词定位默认 OP。"""
        res = {"catalog": "不用方案", "new": "", "num": 0, "k": "OP", "lead": 0.2, "vocals": True, "q": ""}
        res.update({k: v for k, v in self.dialog.items() if k != "__file__"})
        return res

    def make_subs(self, info=None, styles=None, dialogue=None):
        """info: {key: value}；styles: [{name:...}]；dialogue: [{...}]
        返回 (lua 的 subs 表, Python 那边的行列表)"""
        rows = []
        for k, v in (info or {"PlayResX": "1920", "PlayResY": "1080"}).items():
            rows.append({"class": "info", "section": "[Script Info]", "key": k, "value": str(v)})
        for st in styles or []:
            rows.append({**st, "class": "style", "section": "[V4+ Styles]"})
        for d in dialogue or []:
            full = {"class": "dialogue", "section": "[Events]", "comment": False, "layer": 0,
                    "start_time": 0, "end_time": 0, "style": "Default", "actor": "", "effect": "",
                    "margin_l": 0, "margin_r": 0, "margin_t": 0, "margin_b": 0, "text": ""}
            full.update(d)
            rows.append(full)
        rows = [self.lua.table_from(r) for r in rows]
        self._rows = list(rows)
        self._tbl = self.lua.table_from(rows)
        self._subs = self._wrap(self._tbl)
        self._live = [self._tbl[k] for k in range(1, len(self._tbl) + 1)]  # 底层行，直接改它 = 用户改了字幕
        return self._subs, self._live

    def _wrap(self, t):
        lua = self.lua
        code = r'''
        function(t)
          local s = newproxy(true)
          local mt = getmetatable(s)
          mt.__len = function() return #t end
          mt.__index = function(_, k)
            if k == "insert" then return function(i, l) table.insert(t, i, l) end end
            if k == "delete" then return function(i) table.remove(t, i) end end
            if k == "append" then return function(l) t[#t + 1] = l end end
            local l = t[k] if not l then return nil end
            local c = {} for a, b in pairs(l) do c[a] = b end return c
          end
          mt.__newindex = function(_, k, v) t[k] = v end
          return s
        end
        '''
        return lua.eval(code)(t)

    # ---- 调用宏 ----
    def run(self, macro, sel=None, active=None):
        """sel 用 1 起算的行号（Aegisub 的规矩）。返回底层行列表的快照。"""
        self.cancelled = None
        self.logs = []
        self.undos = []
        sel = sel or []
        try:
            self.g.macros[macro](self._subs, self.lua.table_from(sel), active or (sel[0] if sel else 0))
        except Exception as e:
            msg = str(e)
            if "aegisub.cancel" in msg:
                self.cancelled = msg                      # 插件主动取消：正常路径，不算错
            else:
                raise
        return self.snapshot()

    def refresh(self):
        """底层行被整体换过之后（插入 / 删除行），重新做一份引用"""
        self._live = [self._tbl[k] for k in range(1, len(self._tbl) + 1)]
        return self._live

    def snapshot(self):
        self.refresh()
        return [dict(r) for r in self._live]

    @staticmethod
    def dialogues(rows):
        return [r for r in rows if r.get("class") == "dialogue"]

    @staticmethod
    def styles(rows):
        return {r["name"]: r for r in rows if r.get("class") == "style"}

    @staticmethod
    def infos(rows):
        return {r["key"]: r["value"] for r in rows if r.get("class") == "info"}
