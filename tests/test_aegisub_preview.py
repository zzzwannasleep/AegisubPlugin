r"""真 Aegisub 端到端：文件夹里的字体（没装进系统）在 Aegisub 自己的预览里画得出来

为什么非要这一条：插件用的是 AddFontResourceEx(FR_PRIVATE)——只注册给当前进程。
Aegisub 的预览渲染器到底认不认（libass 走 DirectWrite，CSRI/xy-VSFilter 走 GDI），
在别的进程里怎么测都只是「像」，只有真开一次 Aegisub 才算数。

做法：从本机装着的 Aegisub 复制一份**隔离的**安装（不碰你正在用的那个，两个进程互不影响），
往里放插件 + 一份 fx_settings.json 指向字体文件夹，然后开两次：

    A 趟：插件启动时注册字体  → libass 选字体的日志里，那几个名字应该落到字体文件本身
    B 趟：把 fx_settings.json 挪走（不注册）→ 同样几个名字应该跟「绝无此字体」一样回退

证据是 **Aegisub 自己写的日志** `log\<时间>.json` 里的 `subtitle/provider/libass`
fontselect 行（纯文本，不靠肉眼）；顺带截一张自己窗口的图，能截就再比一下像素。

    python tests\test_aegisub_preview.py            # 跑（约 1 分钟，会弹两个 Aegisub 窗口）
    python tests\test_aegisub_preview.py --fresh    # 重新复制隔离安装
    python tests\test_aegisub_preview.py --clean    # 跑完把隔离安装删掉

需要：本机的真 Aegisub（tools\testconfig.py 找得到）、PATH 里的 ffmpeg、
     环境变量 ZX_FONT_DIR 指向一个放着「没装进系统」的字体的文件夹。
字段不够就跳过（返回 0），不会把别人的机器判成失败。

隔离安装放在 %TEMP%\zx_aeg_preview\（不在仓库里，也不放进 tests\fixtures\generated\）：
**必须是纯 ASCII 路径**——插件里 zx_home() 有一条既有设计：`?user` 带非 ASCII 字符时
（比如 Aegisub 装在中文目录下）组件目录会退到 `%ProgramData%\zhouxiao-autotime`，
把测试台放在中文路径下就会去读那份设置，测不到隔离安装里的字体文件夹。
"""
import ctypes
import ctypes.wintypes as wt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

import bootstrap  # noqa: F401
import testconfig as C

z, fe, ai = C.load_src()

OK, BAD, SKIP = [], [], []
u32 = ctypes.windll.user32
FF = shutil.which("ffmpeg")
BASE = os.path.join(tempfile.gettempdir(), "zx_aeg_preview")
EXCLUDE = ("zhouxiao-autotime", "autoback", "autosave", "log", "ffms2cache",
           "crashdumps", "catalog", "feedDump", "dictionaries")


def check(name, cond, detail=""):
    (OK if cond else BAD).append(name)
    print(("  OK   " if cond else "  FAIL ") + name + (("   " + str(detail)) if detail else ""))


def skip(name, why):
    SKIP.append(name)
    print("  --   %s（跳过：%s）" % (name, why))


# ------------------------------------------------------------------ 隔离安装
def iso_dir():
    return os.path.join(BASE, "aeg")


def build_iso(fresh=False):
    iso = iso_dir()
    if fresh and os.path.isdir(iso):
        shutil.rmtree(iso)
    exe = os.path.join(iso, "aegisub.exe")
    if os.path.exists(exe):
        return iso, False
    src = C.aegisub_dir()
    os.makedirs(iso, exist_ok=True)
    r = subprocess.run(["robocopy", src, iso, "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/NP",
                        "/XD"] + [os.path.join(src, d) for d in EXCLUDE], capture_output=True)
    if not os.path.exists(exe):
        raise SystemExit("复制隔离安装失败（robocopy %d）：%s" % (r.returncode,
                                                            r.stdout.decode("utf-8", "replace")[-300:]))
    return iso, True


def prep_iso(iso, fonts):
    """插件 + 设置：字体文件夹写进这份隔离安装自己的组件目录"""
    os.makedirs(os.path.join(iso, "zhouxiao-autotime"), exist_ok=True)
    settings = os.path.join(iso, "zhouxiao-autotime", "fx_settings.json")
    with open(settings, "w", encoding="utf-8") as f:
        json.dump({"fonts_dir": fonts}, f)
    shutil.copyfile(C.lua_path(), os.path.join(iso, "automation", "autoload", "zhouxiao.lua"))
    # 把「未标记色彩矩阵」这类告警关掉：这是 Aegisub 开头的选项框，测试里没人去点
    cfg = os.path.join(iso, "config.json")
    try:
        conf = json.load(open(cfg, encoding="utf-8"))
        conf.setdefault("Video", {})["Untagged Matrix Warning"] = False
        conf["Video"]["HDR Video Warning"] = False
        json.dump(conf, open(cfg, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    except (OSError, ValueError):
        pass
    return settings


def dismiss_dialogs(pid, main_hwnd):
    """Aegisub 开头会弹选项框（未标记色彩矩阵、分辨率不匹配……），不点掉主窗口是禁用的，
    预览就不会渲染。这里把不属于主窗口、又属于这个进程的可见顶层窗口都点掉，返回它们的标题。"""
    others = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cb(h, _):
        if h == main_hwnd or not u32.IsWindowVisible(h):
            return True
        p = wt.DWORD()
        u32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value != pid:
            return True
        n = ctypes.create_unicode_buffer(512)
        c = ctypes.create_unicode_buffer(256)
        u32.GetWindowTextW(h, n, 512)
        u32.GetClassNameW(h, c, 256)
        if n.value.strip():
            others.append((h, n.value, c.value))
        return True

    u32.EnumWindows(cb, 0)
    for h, _title, cls in others:
        u32.SetForegroundWindow(h)
        u32.keybd_event(0x0D, 0, 0, 0)             # 回车：按掉对话框的默认按钮
        u32.keybd_event(0x0D, 0, 2, 0)
        if cls == "#32770":
            u32.PostMessageW(h, 0x0111, 1, 0)      # WM_COMMAND / IDOK：兜底
        else:
            u32.PostMessageW(h, 0x0010, 0, 0)      # WM_CLOSE：wx 自己的对话框兜底
    if others:
        time.sleep(0.5)
    return [t for _h, t, _c in others]


# ------------------------------------------------------------------ 素材
def make_clip(path):
    if os.path.exists(path):
        return True
    # 带上色彩矩阵标签：不然 Aegisub 开头会弹「Untagged video」那个选项框
    r = subprocess.run([FF, "-y", "-f", "lavfi", "-i", "color=c=0x202020:s=640x360:d=2",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-color_primaries", "bt709",
                        "-color_trc", "bt709", "-colorspace", "bt709", path], capture_output=True)
    return r.returncode == 0 and os.path.exists(path)


def make_ass(path, clip, zh, en):
    fmt = ("Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
           "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
           "MarginL, MarginR, MarginV, Encoding")
    rows = [("T_ZH", zh, 60), ("T_EN", en, 180), ("T_BAD", "绝无此字体XYZ", 300)]
    styles = ["Style: %s,%s,40,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,5,10,10,10,1"
              % (n, f) for n, f, _ in rows]
    events = ["Dialogue: 0,0:00:00.00,0:00:09.00,%s,,0,0,0,0,,{\\pos(320,%d)}轴效字体 AaBb 123" % (n, y)
              for n, _, y in rows]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("[Script Info]\nScriptType: v4.00+\nPlayResX: 640\nPlayResY: 360\n"
                "LayoutResX: 640\nLayoutResY: 360\nWrapStyle: 0\n"
                "ScaledBorderAndShadow: yes\nYCbCr Matrix: TV.709\n\n[V4+ Styles]\nFormat: " + fmt +
                "\n" + "\n".join(styles) +
                "\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n" +
                "\n".join(events) + "\n\n[Aegisub Project Garbage]\nVideo File: " + clip + "\n")


# ------------------------------------------------------------------ 开窗口 / 读日志
def window_of(subs_name):
    """找 Aegisub 主窗口：标题里有这个字幕文件名，取客户区最大的那个"""
    best = (0, None)
    out = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cb(hwnd, _):
        n = ctypes.create_unicode_buffer(512)
        u32.GetWindowTextW(hwnd, n, 512)
        if subs_name in n.value and u32.IsWindowVisible(hwnd):
            r = wt.RECT()
            u32.GetWindowRect(hwnd, ctypes.byref(r))
            out.append(((r.right - r.left) * (r.bottom - r.top), hwnd, n.value))
        return True

    u32.EnumWindows(cb, 0)
    for area, hwnd, title in out:
        if area > best[0]:
            best = (area, (hwnd, title))
    return best[1]


def read_logs(logdir, since):
    """Aegisub 的日志是一串拼在一起的 JSON；只读这次会话新写的那些"""
    lines = []
    if not os.path.isdir(logdir):
        return lines
    for name in sorted(os.listdir(logdir)):
        p = os.path.join(logdir, name)
        try:
            if os.path.getmtime(p) < since:
                continue
            text = open(p, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for chunk in re.findall(r"\{[^{}]*\}", text):
            try:
                lines.append(json.loads(chunk))
            except ValueError:
                pass
    return lines


def font_picks(logs):
    """{样式里写的字体名: libass 最后选中的那个字体}"""
    picks = {}
    for l in logs:
        if l.get("section") != "subtitle/provider/libass":
            continue
        m = re.match(r"fontselect: \((.+?), \d+, \d+\) -> (\S+)", (l.get("message") or "").strip())
        if m:
            picks[m.group(1)] = m.group(2)
    return picks


def steal_focus(hwnd):
    """前台锁：普通 SetForegroundWindow 会失败，Alt 键 + AttachThreadInput 才是通行做法"""
    u32.AllowSetForegroundWindow(ctypes.c_uint(-1))          # ASFW_ANY
    tid_fore = u32.GetWindowThreadProcessId(u32.GetForegroundWindow(), None)
    tid_self = ctypes.windll.kernel32.GetCurrentThreadId()
    u32.AttachThreadInput(tid_fore, tid_self, True)
    try:
        u32.keybd_event(0x12, 0, 0, 0)                       # Alt 按下
        u32.SetForegroundWindow(hwnd)
        u32.BringWindowToTop(hwnd)
        u32.keybd_event(0x12, 0, 2, 0)                       # Alt 抬起
    finally:
        u32.AttachThreadInput(tid_fore, tid_self, False)


def nudge(hwnd):
    """戳一下窗口：改尺寸 + 强制重绘 + 步进一帧。
    Aegisub 是「视频框被画到才去算这一帧字幕」，光等它不会自己动。"""
    r = wt.RECT()
    u32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    u32.SetWindowPos(hwnd, -1, r.left, r.top, w + 2, h + 2, 0x0004 | 0x0010)   # NOZORDER|NOACTIVATE
    u32.SetWindowPos(hwnd, -1, r.left, r.top, w, h, 0x0004 | 0x0010)
    u32.RedrawWindow(hwnd, None, None, 0x0001 | 0x0200 | 0x0080 | 0x0100)      # INVALIDATE|ERASE|ALLCHILDREN|UPDATENOW
    u32.keybd_event(0x27, 0, 0, 0)                                              # → 步进一帧
    u32.keybd_event(0x27, 0, 2, 0)


def one_run(tag, iso, ass, settings, register):
    """开一次 Aegisub：注册/不注册，把日志和截图收回来"""
    fake = settings + ".off"
    if register and os.path.exists(fake):
        os.replace(fake, settings)
    elif not register and os.path.exists(settings):
        os.replace(settings, fake)
    logdir = os.path.join(iso, "log")
    png = os.path.join(BASE, "shot_%s.png" % tag)
    t0 = time.time()
    p = subprocess.Popen([os.path.join(iso, "aegisub.exe"), ass], cwd=iso)
    shot = None
    try:
        win = None
        for _ in range(80):
            time.sleep(0.5)
            win = window_of(os.path.basename(ass))
            if win:
                break
        if not win:
            return None, None, "窗口没开出来"
        hwnd, title = win
        u32.ShowWindow(hwnd, 9)                                      # SW_RESTORE
        u32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)   # TOPMOST|NOSIZE|NOMOVE|SHOWWINDOW
        # 等它把视频打开，然后一遍遍戳，直到日志里出现「真的渲染了」的证据
        logs = []
        seen = []
        for i in range(12):
            for t in dismiss_dialogs(p.pid, hwnd):
                if t not in seen:
                    seen.append(t)
                    print("     点掉了开头的选项框：%s" % t)
            steal_focus(hwnd)
            nudge(hwnd)
            time.sleep(2)
            logs = read_logs(logdir, t0)
            if font_picks(logs):
                print("     第 %d 次戳它之后开始渲染了" % (i + 1))
                break
        # 标题可能在加载视频后变了，截之前重新取一次
        win = window_of(os.path.basename(ass)) or (hwnd, title)
        hwnd, title = win
        if os.path.exists(png):
            os.remove(png)
        rc = subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y", "-f", "gdigrab",
                             "-i", "title=" + title, "-frames:v", "1", "-pix_fmt", "rgb24", png],
                            capture_output=True)
        if rc.returncode == 0 and os.path.exists(png) and os.path.getsize(png) > 0:
            shot = png
    finally:
        subprocess.run(["taskkill", "/F", "/PID", str(p.pid)], capture_output=True)
        time.sleep(2)
    return read_logs(logdir, t0), shot, None


def load_png(path):
    """借 ffmpeg 解成 RGB 原始像素（仓库里没有 PIL，PNG 的 5 种行 filter 不值当自己写）"""
    r = subprocess.run([FF, "-v", "error", "-i", path, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                       capture_output=True)
    return r.stdout


# ------------------------------------------------------------------ main
def main():
    argv = sys.argv[1:]
    fresh = "--fresh" in argv
    clean = "--clean" in argv
    fonts = C.font_dir()
    if not fonts or not os.path.isdir(fonts):
        print("没设 ZX_FONT_DIR（或目录不存在），这条测试跳过：文件夹字体要有个文件夹")
        return 0
    files = z.font_files(fonts)
    zh = en = None
    for f in files:
        names = z.family_names(f, limit=2)
        if len(names) >= 2 and not zh:
            zh, en = names[0], names[1]
    if not zh:
        print("%s 里没有「中英文名字都读得出」的字体，这条测试跳过" % fonts)
        return 0
    if z.font_ok(zh) or z.font_ok(en):
        print("%s（%s）已经装进系统了，证明不了「没装也能用」——换一个没装的字体再跑" % (zh, fonts))
        return 0
    if not FF:
        print("PATH 里没有 ffmpeg，合成素材和截图都做不了，跳过")
        return 0

    print("样本字体：%s / %s（%s，%d 个文件）" % (zh, en, fonts, len(files)))
    os.makedirs(BASE, exist_ok=True)
    iso, built = build_iso(fresh)
    print("隔离安装：%s%s" % (iso, "（这次新复制的）" if built else "（复用上次那份）"))
    settings = prep_iso(iso, fonts)
    clip = os.path.join(BASE, "clip.mp4")
    ass = os.path.join(BASE, "preview.ass")
    if not make_clip(clip):
        print("ffmpeg 合成测试视频失败，跳过")
        return 0
    make_ass(ass, clip, zh, en)

    logs_a, shot_a, err_a = one_run("on", iso, ass, settings, True)
    logs_b, shot_b, err_b = one_run("off", iso, ass, settings, False)
    if logs_a is None or logs_b is None:
        print("Aegisub 没开起来：%s %s" % (err_a, err_b))
        return 1

    pa, pb = font_picks(logs_a), font_picks(logs_b)
    print("\nA 趟（注册了字体）libass 选了：")
    for k, v in pa.items():
        print("   %-22s -> %s" % (k, v))
    print("B 趟（没注册）libass 选了：")
    for k, v in pb.items():
        print("   %-22s -> %s" % (k, v))

    bad_name = "绝无此字体XYZ"
    check("两趟都真的渲染了字幕（日志里有 fontselect）", bool(pa) and bool(pb), (len(pa), len(pb)))
    if pa and pb:
        check("A 趟：字体文件夹里的名字（中文名）解析到了别的东西，不是回退",
              pa.get(zh) and pa.get(zh) != pa.get(bad_name), pa.get(zh))
        check("A 趟：英文名也一样", pa.get(en) and pa.get(en) == pa.get(zh), (en, pa.get(en)))
        check("B 趟：不注册时它和「绝无此字体」一个下场（都回退）",
              pb.get(zh) == pb.get(bad_name) and pb.get(zh) is not None, (pb.get(zh), pb.get(bad_name)))
        check("两趟选中的字体不一样 → 差别就是插件注册带来的", pa.get(zh) != pb.get(zh),
              (pa.get(zh), pb.get(zh)))

    if shot_a and shot_b:
        ia, ib = load_png(shot_a), load_png(shot_b)
        if ia and ib and len(ia) == len(ib):
            n = sum(1 for i in range(0, len(ia), 3) if ia[i:i + 3] != ib[i:i + 3])
            check("Aegisub 预览画出来的像素也变了（%d 个像素）" % n, n > 200)
            print("   截图：%s / %s" % (shot_a, shot_b))
        else:
            skip("截图逐像素比", "两张图解码后长度不一致")
    else:
        skip("截图逐像素比", "只截自己窗口；这次没截到（日志证据已经够了）")

    if clean:
        shutil.rmtree(BASE, ignore_errors=True)
        print("测试台已删（下次跑会重新复制）")
    else:
        print("测试台留着（%s），下次直接复用" % BASE)
    print("\n通过 %d 项，失败 %d 项%s"
          % (len(OK), len(BAD), ("，跳过 %d 项" % len(SKIP)) if SKIP else ""))
    return 1 if BAD else 0


if __name__ == "__main__":
    raise SystemExit(main())
