"""测试用的路径和模块加载。所有测试脚本都从这里拿路径，别再写死盘符。

环境变量（可选，都有默认值）：
    ZX_COMPONENT   组件目录（默认 D:\\Video\\Aegisub-3.4.2\\zhouxiao-autotime）
    ZX_PY          用哪个 Python 跑子进程（默认组件目录里的 env\\Scripts\\python.exe）
    ZX_VIDEO       测试视频（GUI 截图测试要；默认真实番剧那集）
    ZX_AEGISUB     Aegisub 目录（默认从组件目录推出来）
"""
import contextlib
import importlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "src")
TESTS = os.path.join(ROOT, "tests")
FIXTURES = os.path.join(TESTS, "fixtures")
GEN = os.path.join(FIXTURES, "generated")

COMPONENT = os.environ.get("ZX_COMPONENT", r"D:\Video\Aegisub-3.4.2\zhouxiao-autotime")
AEGISUB = os.environ.get("ZX_AEGISUB", os.path.dirname(COMPONENT.rstrip("\\/")))
PY = os.environ.get("ZX_PY", os.path.join(COMPONENT, "env", "Scripts", "python.exe"))
LUA = os.path.join(AEGISUB, "automation", "autoload", "zhouxiao.lua")
VSFILTER = os.path.join(AEGISUB, "csri", "VSFilter.dll")

VIDEO = os.environ.get("ZX_VIDEO", os.path.join(
    r"D:\Video\TestVideo",
    r"[NEST] Mushoku Tensei Jobless Reincarnation S03 - 08 [CR WEB-DL 1080p AVC AAC][JPSC_JPTC]",
    r"[NEST] Mushoku Tensei Jobless Reincarnation S03 - 08 [CR WEB-DL 1080p AVC AAC][JPSC_JPTC].mkv"))

# 插件里的菜单名，测试里按名字取宏
MACRO = {
    "import": "轴效/1 导入 txt",
    "autotime": "轴效/1 导入 txt + 自动粗轴",
    "main": "轴效/2 设为主要（底部）",
    "top": "轴效/2 设为次要（顶部）",
    "op": "轴效/2 设为 OP 歌词",
    "ed": "轴效/2 设为 ED 歌词",
    "insert": "轴效/2 设为插曲歌词",
    "note": "轴效/3 加注释",
    "screen": "轴效/4 加屏字",
    "sync": "轴效/5 同步时间（中日）",
    "locate": "轴效/6 歌词定位：开始",
    "record": "轴效/6 歌词定位：记录",
    "unlocate": "轴效/6 歌词定位：取消",
    "fx": "轴效/7 特效样式",
    "kara": "轴效/8 卡拉OK特效",
    "ai": "轴效/9 AI 助手",
}


def read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def need(path, what):
    """缺文件就直接给一句人话，而不是后面报个莫名其妙的错"""
    if not os.path.exists(path):
        raise SystemExit("缺 %s：%s\n（可以用环境变量 ZX_COMPONENT / ZX_VIDEO 改路径）" % (what, path))
    return path


def gen(name):
    os.makedirs(GEN, exist_ok=True)
    return os.path.join(GEN, name)


def load_src(home=COMPONENT):
    """从 src\\ 导入 zxcore / fxedit / zxai，并把 HOME 指到组件目录。

    直接 import 的话 HOME 会是 src\\，那些「运行时要读的文件」（fx_presets.json、
    ai_history.json、kara_pack）就找不到；组件目录才是跑起来时的 HOME。
    """
    if SRC not in sys.path:
        sys.path.insert(0, SRC)
    for name in ("zxcore", "fxedit", "zxai"):
        sys.modules.pop(name, None)
    zxcore = importlib.import_module("zxcore")
    fxedit = importlib.import_module("fxedit")
    zxai = importlib.import_module("zxai")
    if home:
        zxcore.HOME = home
        fxedit.HOME = home
        zxai.HOME = home
        zxai.CONF = os.path.join(home, "ai.json")
    return zxcore, fxedit, zxai


def lua_source():
    return read(need(LUA, "线上 zhouxiao.lua"))


def load_lua(src=None, spawn=None, hook_before="-- 日志最后一行"):
    """加载 zhouxiao.lua 到 lupa，返回 runtime。

    spawn 是给测试用的替身：插件用 FFI 的 CreateProcessW 起工作台窗口，测试里必须换掉，
    否则会真弹 pythonw 窗口。**必须在 execute 之前就摆进全局表**——插件里 `spawn` 是整块
    chunk 的局部量，宏注册时闭包已经绑死，加载完再设就晚了（这条是真踩过的坑）。
    """
    import lupa.luajit21 as L
    lua = L.LuaRuntime(unpack_returned_tuples=True)
    text = src if src is not None else lua_source()
    if "ZX_SPAWN" not in text and hook_before in text:
        at = text.index(hook_before)
        text = text[:at] + "if ZX_SPAWN then spawn = ZX_SPAWN end\n" + text[at:]
    if spawn is not None:
        lua.globals().ZX_SPAWN = spawn
    lua.execute(text)
    return lua


@contextlib.contextmanager
def temp_home():
    """给一组测试一个干净的 user 目录（decode_path("?user") 会指向它）"""
    import tempfile
    d = tempfile.mkdtemp(prefix="zx_test_")
    yield d
