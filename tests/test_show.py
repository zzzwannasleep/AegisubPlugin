r"""样式方案：Python 写的 .sty 能被 Lua 读、编号专用优先、按视频文件名认番、以及弹框次数。

「样式方案」= 样式库 catalog\名字.sty（Aegisub 样式管理器也读写）+ 旁边的 名字.fx.json；
同一个样式可以有「ED CN #05」这种编号专用版本；字幕文件头用 ZX_Catalog / ZX_Number 记着用哪个方案。
这里验两条链路真的接得上：
  1. Python 工作台（fxedit.Library）写出来的库，Lua 插件能原样读出来（含编号专用和特效配方）；
  2. 插件在假 Aegisub 里跑完整流程时，「问用户用哪个方案」的弹框次数（DIALOGS）不多不少。

lupa 的 LuaJIT 自带的 io 库打不开含中文的路径，所以按老测试的办法把 Lua 的 io.open 换成
「用 Python 开文件」的 shim，并用 package.preload.lfs 提供目录列举 —— 插件那边完全不知情，
其余照原样跑。样式库一律用临时目录，真的 D:\Video\Aegisub-3.4.2\catalog 一个字节都不动（结尾有守卫断言）。

    python tests\test_show.py
"""
import os
import tempfile
import traceback

import bootstrap  # noqa: F401  （放好 sys.path，必须在最前面）
import testconfig as C  # noqa: E402
import fixtures  # noqa: E402

# 界面上的宏名一律从 testconfig 的映射取，别在这里再抄一份
z, fe, _ai = C.load_src()

OK = []
BAD = []

# 「艾莉同学」这一系的视频文件名；Lua 的 title_stem 和 Python 的 fe.title_stem 都该认成同一段标题
ALYA_01 = r"D:\v\[Nekomoe] Tokidoki Bosotto Russia-go de Dereru Tonari no Alya-san - 01 [1080p].mkv"
ALYA_05 = r"E:\x\[Nekomoe] Tokidoki Bosotto Russia-go de Dereru Tonari no Alya-san - 05 [1080p].mkv"
OTHER = r"D:\v\随便一个视频.mp4"
FRIEREN_03 = r"D:\v\[SweetSub] Sousou no Frieren - 03.mkv"
FRIEREN_04 = r"D:\v\[SweetSub] Sousou no Frieren - 04.mkv"


def check(name, cond, detail=""):
    (OK if cond else BAD).append(name)
    print(("  OK   " if cond else "  FAIL ") + name + (("   " + str(detail)) if detail and not cond else ""))


def head(title):
    print("\n== " + title)


# ================================================================ Python 侧：fxedit.Library

def alias_of(cat, video):
    """按视频文件名去 alias 表里查方案名（这就是「重新读库」时能拿到的东西）"""
    p = os.path.join(cat, "zhouxiao-alias.tsv")
    try:
        rows = [l.rstrip("\n").split("\t") for l in open(p, encoding="utf-8") if "\t" in l]
    except OSError:
        return None
    stem = fe.title_stem(video)
    for a, b in rows:
        if a == stem:
            return b
    return None


def build_library(cat):
    """Python 工作台：建一部番的样式库，ED CN 同时有通用版和第 5 集专用版"""
    lib = fe.Library(cat)
    check("Library() 建出「轴效起步」样式库",
          fe.CATALOG_SEED in lib.cats and os.path.exists(os.path.join(cat, fe.CATALOG_SEED + ".sty")),
          sorted(lib.cats))
    seed = {p["name"]: p for p in lib.cats.get(fe.CATALOG_SEED, [])}
    has_ed = "ED CN" in seed
    check("「轴效起步」里有 ED CN 可以派生", has_ed, sorted(seed))
    if not has_ed:
        # 后面的用例全都从这条派生；起步库里没有就没法继续，别再往下报一串看不懂的错
        raise RuntimeError("起步样式库里没有 ED CN")

    ed = fe.migrate({"cat": "艾莉同学", "name": "ED CN",
                     "style": dict(seed["ED CN"]["style"], fontname="通用ED字体")})
    ed5 = fe.migrate({"cat": "艾莉同学", "name": "ED CN #05",
                      "style": dict(seed["ED CN"]["style"], fontname="第5集ED字体", fontsize=77)})
    ed5["fx"]["glow"] = 1   # 特效配方要跟着 .fx.json 一起存取，不能只有样式
    lib.cats["艾莉同学"] = [ed, ed5]
    lib.write("艾莉同学")
    check("写出的 .sty 里有通用版和编号专用版",
          os.path.exists(os.path.join(cat, "艾莉同学.sty"))
          and os.path.exists(os.path.join(cat, "艾莉同学.fx.json")))

    lib.add_alias(ALYA_01, "艾莉同学")
    print("   alias 文件：" + open(os.path.join(cat, "zhouxiao-alias.tsv"), encoding="utf-8").read().strip())

    lib2 = fe.Library(cat)   # 重新读一遍：下面这些都必须只靠磁盘上的文件成立

    def pick(name, num):
        return lib2.pick("艾莉同学", name, num) or {}

    check("重新读库：编号 5 拿第 5 集专用那条",
          pick("ED CN", 5).get("style", {}).get("fontname") == "第5集ED字体",
          pick("ED CN", 5).get("style", {}).get("fontname"))
    check("重新读库：编号 4 回落通用那条",
          pick("ED CN", 4).get("style", {}).get("fontname") == "通用ED字体",
          pick("ED CN", 4).get("style", {}).get("fontname"))
    check("编号 0（不分集）时名字去掉 #05 后缀找通用",
          pick("ED CN #05", 0).get("name") == "ED CN", pick("ED CN #05", 0).get("name"))
    check("特效配方跟着 .fx.json 存取（第 5 集那条 glow=1）",
          pick("ED CN", 5).get("fx", {}).get("glow") == 1, pick("ED CN", 5).get("fx", {}).get("glow"))
    check("add_alias 重读仍在", alias_of(cat, ALYA_05) == "艾莉同学", alias_of(cat, ALYA_05))
    check("alias 记的是标题部分（和 Python/Lua 两个 title_stem 一致）",
          alias_of(cat, ALYA_01) == "艾莉同学", alias_of(cat, ALYA_01))


# ================================================================ Lua 侧：假 Aegisub

# 假 aegisub：不开 Aegisub、不弹真窗口。DIALOGS 是这套测试的核心证据，只由 dialog.display 累加
FAKE_AEGISUB = r'''
macros = {}
DIALOGS = 0          -- 「用哪个样式方案」的弹框次数
ANSWER = nil         -- 非 nil 时模拟用户手填的答案（{catalog=, new=, num=}）
DLG_DEFAULTS = {}    -- 最近一次弹框里各控件的默认值
LOGS = {}            -- 插件日志先攒着，由 Python 按顺序打出来（Lua 的 print 不走 Python 的缓冲，会串行）

aegisub = {
  register_macro = function(name, desc, fn) macros[name] = fn end,
  decode_path = function(p) return USER end,
  log = function(l, f, ...)
    if f then LOGS[#LOGS + 1] = string.format(f, ...):gsub("%s+$", "") end
  end,
  cancel = function() error("aegisub.cancel（插件主动取消了，这次用例不该走到这）") end,
  project_properties = function() return {video_file = VIDEO, video_position = 0} end,
  ms_from_frame = function(f) return 0 end,
  text_extents = function(st, text) return #text * 10, 20 end,
  progress = {title = function() end, task = function() end, set = function() end,
              is_cancelled = function() return false end},
  set_undo_point = function() end,
  dialog = {
    display = function(ctl, buttons)
      DIALOGS = DIALOGS + 1
      local v = {}
      for _, c in ipairs(ctl) do if c.name then v[c.name] = c.value end end
      DLG_DEFAULTS = v
      return "确定", ANSWER or v
    end,
    open = function() return TXT end,
  },
}
-- 外部进程绝不能真起（插件里 spawn 走 FFI 的 CreateProcessW），测试里换成会报错的桩
ZX_SPAWN = function(cmd) error("测试里不该起外部进程：" .. tostring(cmd)) end

-- Aegisub 的 subs 表和 Lua 数组不一样：要支持 #、insert、delete、append，元素还是只读副本
function wrap_subs(t)
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

# Lua 的 io.open / require "lfs" 换成 Python 实现：LuaJIT 自带的那个打不开中文路径
IO_SHIM = r'''
io.open = function(p, m)
  local h = PYOPEN(p, m or "r")
  if not h then return nil, p .. ": No such file or directory" end
  return {
    read = function(self, fmt) return h.read(fmt) end,
    write = function(self, s) h.write(s) end,
    close = function() h.close() end,
    lines = function() local i = -1 return function() i = i + 1 return h.line(i) end end,
  }
end
package.preload.lfs = function()
  return {dir = function(d)
    local l = PYLIST(d)
    local i = 0
    return function() i = i + 1 return l[i] end
  end}
end
'''


class PyFile:
    """io.open 的替身：交给 Python 开，UTF-8、中文路径、BOM 都照原样过。
    插件里 write_file 是 "wb" 模式、read_lines 是 "rb" 模式，这里统一按文本处理。"""

    def __init__(self, path, mode):
        self.f = open(path, mode.replace("b", ""), encoding="utf-8", newline="")
        self.buf = None

    def read(self, fmt="*a"):
        return self.f.read()

    def line(self, i):
        if self.buf is None:
            self.buf = self.f.read().splitlines()
        return self.buf[i] if i < len(self.buf) else None

    def write(self, s):
        self.f.write(s)

    def close(self):
        self.f.close()


def pyopen(path, mode="r"):
    try:
        return PyFile(path, mode)
    except OSError:
        return None


def plugin_source():
    """和 testconfig.load_lua 同一个手法：插一个 ZX_SPAWN 钩子，把 spawn 换成可注入的桩。
    这里要自己插是因为 io 的 shim 必须在插件源码执行之前就位，没法直接用 load_lua()。"""
    text = C.lua_source()
    if "if ZX_SPAWN then spawn = ZX_SPAWN end" not in text:
        at = text.index("-- 日志最后一行")
        text = text[:at] + "if ZX_SPAWN then spawn = ZX_SPAWN end\n" + text[at:]
    return text


class LuaSide:
    """假 Aegisub + 载入插件"""

    def __init__(self, user, txt):
        import lupa.luajit21 as L
        self.lua = L.LuaRuntime(unpack_returned_tuples=True)
        self.g = self.lua.globals()
        self.g.USER = user.replace("\\", "/") + "/"
        self.g.VIDEO = ""
        self.g.TXT = txt.replace("\\", "/")
        self.lua.execute(FAKE_AEGISUB)
        self.g.PYOPEN = pyopen
        self.g.PYLIST = lambda d: self.lua.table_from(os.listdir(d) if os.path.isdir(d) else [])
        self.lua.execute(IO_SHIM)
        self.lua.execute(plugin_source())

    # ---- 造一份字幕 ----
    def new_file(self):
        """刚打开、只有 Default 样式、没有任何 ZX_ 记录的字幕"""
        rows = [{"class": "info", "section": "[Script Info]", "key": "PlayResX", "value": "1920"},
                {"class": "info", "section": "[Script Info]", "key": "PlayResY", "value": "1080"},
                dict(fixtures.DEFAULT_STYLE, **{"class": "style", "section": "[V4+ Styles]"})]
        tbl = self.lua.table_from([self.lua.table_from(r) for r in rows])
        return self.g.wrap_subs(tbl), tbl

    # ---- 调宏 ----
    def run(self, macro, subs, sel=None):
        sel = sel or []
        self.g.macros[C.MACRO[macro]](subs, self.lua.table_from(sel), sel[-1] if sel else 0)
        logs, i = self.g.LOGS, 1
        while logs[i] is not None:
            print("     插件日志：" + str(logs[i]).rstrip())
            i += 1
        self.g.LOGS = self.lua.table()

    @property
    def dialogs(self):
        return self.g.DIALOGS

    @dialogs.setter
    def dialogs(self, n):
        self.g.DIALOGS = n

    def defaults(self):
        return self.g.DLG_DEFAULTS

    def answer(self, **kw):
        self.g.ANSWER = self.lua.table_from(kw) if kw else None

    def video(self, path):
        self.g.VIDEO = path


def rows_of(t):
    return [t[k] for k in range(1, len(t) + 1)]


def styles_of(t):
    return {r["name"]: r for r in rows_of(t) if r["class"] == "style"}


def info_of(t):
    return {r["key"]: r["value"] for r in rows_of(t) if r["class"] == "info"}


def dialogues_of(t):
    return [r for r in rows_of(t) if r["class"] == "dialogue"]


def sel_of(t):
    """随便挑一行歌词来点「设为 ED 歌词」：最后一条对白行"""
    idx = [k for k in range(1, len(t) + 1) if t[k]["class"] == "dialogue"]
    return [idx[-1]] if idx else []


def drop_style(subs, t, name):
    """删掉一条样式行：逼下一次功能调用重新走 resolve_catalog，
    这样「已经记着方案 / 记着『不用方案』就不该再问」才是真的被测到，而不是因为样式齐了跳过。"""
    for k in range(1, len(t) + 1):
        if t[k]["class"] == "style" and t[k]["name"] == name:
            subs.delete(k)
            return True
    return False


def run_lua(user, txt):
    head("Lua 侧：假 Aegisub 里的完整流程")
    lua = LuaSide(user, txt)

    # ---- 第 1 集：字幕里没记方案 → 弹一次框，默认值按视频文件名猜 ----
    lua.video(ALYA_01)
    lua.dialogs = 0
    subs, t = lua.new_file()
    lua.run("import", subs)
    d = lua.defaults()
    print("   第 1 集：弹框 %d 次；框里默认 方案=%s 编号=%s" % (lua.dialogs, d["catalog"], d["num"]))
    check("没记方案时正好弹一次框（核心）", lua.dialogs == 1, lua.dialogs)
    check("框里默认方案 = 按视频文件名认出的「艾莉同学」", d["catalog"] == "艾莉同学", d["catalog"])
    check("框里默认编号 = 文件名里的 01", d["num"] == 1, d["num"])

    inf, st = info_of(t), styles_of(t)
    print("   文件头：%s；ED CN 字体：%s" % ({k: v for k, v in inf.items() if k.startswith("ZX")},
                                            st["ED CN"]["fontname"]))
    check("文件头写对 ZX_Catalog", inf.get("ZX_Catalog") == "艾莉同学", inf.get("ZX_Catalog"))
    check("文件头写对 ZX_Number", inf.get("ZX_Number") == "1", inf.get("ZX_Number"))
    check("ED CN 用的是样式库里的字体", st["ED CN"]["fontname"] == "通用ED字体", st["ED CN"]["fontname"])
    check("库里没有的样式照抄 Default", st["Text CN"]["fontname"] == "Arial", st["Text CN"]["fontname"])

    dl = dialogues_of(t)
    check("导入的行数与样式对得上（插了文件头之后行号没挪错）",
          len(dl) == 2 and dl[0]["style"] == "Text JP",
          [(r["style"], r["text"]) for r in dl])

    # ---- 同一份字幕再点功能：样式已齐，不该再问 ----
    lua.dialogs = 0
    lua.run("ed", subs, sel_of(t))
    check("同一份字幕再点功能不再弹框", lua.dialogs == 0, lua.dialogs)

    # ---- 删掉一条样式再点：这次真的进了 resolve_catalog，靠文件头里记着的方案挡住弹框 ----
    lua.dialogs = 0
    check("删掉一条样式行（为了逼出 resolve_catalog）", drop_style(subs, t, "Screen"))
    lua.run("ed", subs, sel_of(t))
    check("文件头记着方案时，缺样式也照样不弹框", lua.dialogs == 0, lua.dialogs)

    # ---- 第 5 集：新文件，按 alias 认番、按文件名认集数，ED CN 用第 5 集专用那条 ----
    lua.video(ALYA_05)
    lua.dialogs = 0
    subs, t = lua.new_file()
    lua.run("import", subs)
    d, st = lua.defaults(), styles_of(t)
    print("   第 5 集：弹框 %d 次；默认 方案=%s 编号=%s；ED CN 字体=%s 字号=%s"
          % (lua.dialogs, d["catalog"], d["num"], st["ED CN"]["fontname"], st["ED CN"]["fontsize"]))
    check("新一集仍然只弹一次框", lua.dialogs == 1, lua.dialogs)
    check("按 alias 认出番（不是靠 .sty 文件名猜的）", d["catalog"] == "艾莉同学", d["catalog"])
    check("按文件名认出第 5 集", d["num"] == 5, d["num"])
    check("ED CN 用第 5 集专用那条的字体", st["ED CN"]["fontname"] == "第5集ED字体", st["ED CN"]["fontname"])
    check("ED CN 用第 5 集专用那条的字号", st["ED CN"]["fontsize"] == 77, st["ED CN"]["fontsize"])

    # ---- 选「不用方案」：记成 -，样式照抄 Default，之后不再问 ----
    lua.video(OTHER)
    lua.answer(catalog="不用方案", new="", num=0)
    lua.dialogs = 0
    subs, t = lua.new_file()
    lua.run("import", subs)
    check("选「不用方案」时也弹一次框", lua.dialogs == 1, lua.dialogs)
    check("选「不用方案」记成 -", info_of(t).get("ZX_Catalog") == "-", info_of(t).get("ZX_Catalog"))
    check("选「不用方案」时样式照抄 Default", styles_of(t)["ED CN"]["fontname"] == "Arial",
          styles_of(t)["ED CN"]["fontname"])
    check("删掉一条样式行（为了逼出 resolve_catalog）", drop_style(subs, t, "Screen"))
    lua.run("ed", subs, sel_of(t))
    check("记着『不用方案』之后不再问（弹框数仍为 1）", lua.dialogs == 1, lua.dialogs)

    # ---- 框里填新方案名：建出空 .sty，下集默认值跟着变 ----
    lua.answer(catalog="不用方案", new="葬送的芙莉莲", num=3)
    lua.video(FRIEREN_03)
    lua.dialogs = 0
    subs, t = lua.new_file()
    lua.run("import", subs)
    check("新建方案时弹一次框", lua.dialogs == 1, lua.dialogs)
    check("框里填的新方案名记进文件头", info_of(t).get("ZX_Catalog") == "葬送的芙莉莲",
          info_of(t).get("ZX_Catalog"))
    check("新建方案会建出 .sty（空库，Aegisub 样式管理器能打开）",
          os.path.exists(os.path.join(user, "catalog", "葬送的芙莉莲.sty")),
          os.listdir(os.path.join(user, "catalog")))
    check("新建的是空库（只有 BOM，一条样式都没抄进去）",
          os.path.getsize(os.path.join(user, "catalog", "葬送的芙莉莲.sty")) <= 3,
          os.path.getsize(os.path.join(user, "catalog", "葬送的芙莉莲.sty")))

    lua.answer()          # 之后用框里的默认值
    lua.video(FRIEREN_04)
    lua.dialogs = 0
    subs, t = lua.new_file()
    lua.run("import", subs)
    d = lua.defaults()
    print("   新番下一集：弹框 %d 次；框里默认 方案=%s 编号=%s" % (lua.dialogs, d["catalog"], d["num"]))
    check("新方案建好之后，下一集仍然弹一次框确认", lua.dialogs == 1, lua.dialogs)
    check("下一集默认方案跟着变成新建的那个", d["catalog"] == "葬送的芙莉莲", d["catalog"])
    check("下一集默认编号跟着文件名走", d["num"] == 4, d["num"])


# ================================================================ 主流程

def catalog_snapshot():
    """真的 catalog 目录快照，用来证明这个测试没往那儿写东西"""
    d = os.path.join(C.AEGISUB, "catalog")
    if not os.path.isdir(d):
        return None
    return sorted((f, os.path.getsize(os.path.join(d, f))) for f in os.listdir(d))


def main():
    print("样式方案：.sty 样式库 / 编号专用 / 按文件名认番 / 弹框次数")
    real_cat = os.path.join(C.AEGISUB, "catalog")
    before = catalog_snapshot()

    user = tempfile.mkdtemp(prefix="zx_show_")
    cat = os.path.join(user, "catalog")
    txt = os.path.join(user, "ja.txt")
    with open(txt, "w", encoding="utf-8", newline="") as f:
        f.write("おはよう\nこんにちは\n")
    print("临时 user 目录（样式库都在这里）：" + user)
    print("Lua 插件源码：" + C.LUA)

    try:
        head("Python 侧：fxedit.Library 写库 / 读库 / alias")
        build_library(cat)
        run_lua(user, txt)
    except Exception:
        BAD.append("未预期的异常")
        traceback.print_exc()

    # 硬性要求：绝不碰真的 catalog 目录。既比快照，也比「Lua 新建的那个方案到底落在哪」
    if before is None:
        print("\n   （没有真的 catalog 目录 %s，跳过这项守卫）" % real_cat)
    else:
        check("测试没往真的 catalog 目录里写东西", catalog_snapshot() == before, real_cat)
        check("Lua 侧建的方案只落在临时目录里",
              os.path.exists(os.path.join(cat, "葬送的芙莉莲.sty"))
              and not os.path.exists(os.path.join(real_cat, "葬送的芙莉莲.sty")), real_cat)

    print("\n通过 %d 项，失败 %d 项" % (len(OK), len(BAD)))
    return 1 if BAD else 0


if __name__ == "__main__":
    raise SystemExit(main())
