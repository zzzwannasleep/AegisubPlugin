"""插件在哪、组件在哪、用哪个 Python 跑测试——全仓库只有这里定义这些路径。

**不写死盘符。** 顺序是：环境变量 → 在仓库附近自动找（同级目录、上级目录）→ 报错说清楚
该设哪个环境变量。clone 到别的机器上只要 Aegisub 目录在仓库旁边，什么都不用设。

环境变量：
    ZX_AEGISUB     Aegisub 目录（里面要有 automation\\autoload\\ 和 csri\\）
    ZX_COMPONENT   组件目录（默认 <Aegisub>\\zhouxiao-autotime）
    ZX_PY          跑子进程用的 Python（默认 <组件>\\env\\Scripts\\python.exe）
    ZX_VIDEO       要用真实视频跑 GUI 测试时指过去（默认不用，测试自己合成视频）
    ZX_KARA_TEMPLATE  换一份卡拉OK模板跑 roundtrip
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
COMPONENT_NAME = "zhouxiao-autotime"     # 插件自己起的组件目录名，和 Lua 里 zx_home() 一致


def _looks_like_aegisub(path):
    return bool(path) and os.path.isdir(os.path.join(path, "automation", "autoload"))


def _find_aegisub():
    """在仓库附近找 Aegisub：先同级，再往上两层。只认同级目录名里带 aegisub 的，
    免得把别的仓库认进来。"""
    for base in (os.path.dirname(ROOT), os.path.dirname(os.path.dirname(ROOT))):
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base)):
            p = os.path.join(base, name)
            if "aegisub" in name.lower() and _looks_like_aegisub(p):
                return p
    return None


def aegisub_dir():
    p = os.environ.get("ZX_AEGISUB")
    if p:
        return p
    p = _find_aegisub()
    if p:
        return p
    raise SystemExit(
        "找不到 Aegisub 目录。设环境变量 ZX_AEGISUB 指过去，例如：\n"
        "    set ZX_AEGISUB=D:\\你的\\Aegisub\n"
        "或者把这个仓库放在 Aegisub 目录旁边（同级）。\n"
        "目录里应该有 automation\\autoload\\ 和 csri\\。")


def component_dir():
    return os.environ.get("ZX_COMPONENT") or os.path.join(aegisub_dir(), COMPONENT_NAME)


PY = os.environ.get("ZX_PY")            # None = 按组件目录推
VIDEO = os.environ.get("ZX_VIDEO")      # None = 测试自己合成视频


def python_exe():
    return PY or os.path.join(component_dir(), "env", "Scripts", "python.exe")


def lua_path():
    return os.path.join(aegisub_dir(), "automation", "autoload", "zhouxiao.lua")


def vsfilter_path():
    return os.path.join(aegisub_dir(), "csri", "VSFilter.dll")


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


def load_src(home=None):
    """从 src\\ 导入 zxcore / fxedit / zxai，并把 HOME 指到组件目录。

    直接 import 的话 HOME 会是 src\\，那些「运行时要读的文件」（fx_presets.json、
    ai_history.json、kara_pack）就找不到；组件目录才是跑起来时的 HOME。
    home=None 时用组件目录；测试里也可以传一个临时目录来隔离。
    """
    if SRC not in sys.path:
        sys.path.insert(0, SRC)
    for name in ("zxcore", "fxedit", "zxai"):
        sys.modules.pop(name, None)
    zxcore = importlib.import_module("zxcore")
    fxedit = importlib.import_module("fxedit")
    zxai = importlib.import_module("zxai")
    if home is None:
        try:
            home = component_dir()
        except SystemExit:
            home = None      # 没装 Aegisub 也允许只用纯 Python 的部分
    if home:
        zxcore.HOME = home
        fxedit.HOME = home
        zxai.HOME = home
        zxai.CONF = os.path.join(home, "ai.json")
    return zxcore, fxedit, zxai


def lua_source():
    return read(need(lua_path(), "线上 zhouxiao.lua"))


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


def __getattr__(name):
    """老的写法 `C.AEGISUB` / `C.LUA` / `C.COMPONENT` / `C.VSFILTER` 还能用，
    但改成用到时才解析——解析不到会报一句人话，而不是在 import 阶段直接炸。"""
    if name == "AEGISUB":
        return aegisub_dir()
    if name == "COMPONENT":
        return component_dir()
    if name == "LUA":
        return lua_path()
    if name == "VSFILTER":
        return vsfilter_path()
    raise AttributeError(name)
