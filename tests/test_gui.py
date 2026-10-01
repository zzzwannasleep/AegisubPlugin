r"""真窗口冒烟 + 「只截自己窗口」截图：python tests\test_gui.py fx|kara|ai [--keep]

为什么必须开真窗口：三页的改动都是 after 合并 / 后台线程渲染的回调驱动的，只有把动作排进
after 队列、跑真 mainloop，切页、K 帧打点、模板重算、截图这些真实路径才会走到。

为什么断言写成 check() 而不是 assert：tkinter 把回调里抛出的异常吞进 report_callback_exception，
assert 只会被静默收走；这里显式记成失败，最后一起报「通过 N 项，失败 M 项」。

截图纪律：窗口标题先设成 ASCII（gdigrab 的 title= 过滤器按标题找窗口），只截自己这一个窗口，
绝不整屏截图——整屏会把别人屏幕上的东西写进仓库。另一个坑：gdigrab 按窗口截出来的是 BGRA 且
alpha 恒为 0，PNG 会带着这个 alpha，看图软件把整张图当全透明显示成一片白（内容其实在里面），
所以截图必须 -pix_fmt rgb24。

    python tests\test_gui.py kara            # 跑完自己关窗，返回 0/1
    python tests\test_gui.py fx --keep      # 跑完窗口留着人眼看；apply 会关窗，所以 --keep 不写 ops
"""
import bootstrap  # noqa: F401  （必须在最前面：把 tools\ src\ tests\ 放进 sys.path）

import ctypes
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import threading

import fixtures
import testconfig as C

# DPI 感知要在 Tk() 之前设：高分屏下窗口尺寸和 gdigrab 截到的像素才对得上（和 fxedit.main 一致）
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

z, fe, zxai = C.load_src()

TITLE = "zxwb-test"      # ASCII 标题：ffmpeg gdigrab 的 title= 只认它
OK, BAD = [], []
ERRORS = []              # tkinter 回调里没接住的异常
SHOT = {}                # 截图线程的结果（线程不能直接 check，要回到主线程核对）
ASKED = []               # apply 弹「没有改动」确认框的次数
FINAL = {}               # 时间轴最后的状态：截图之后拿它核对 ops 里写回的 \k


def check(name, cond, detail=""):
    (OK if cond else BAD).append(name)
    print(("  OK   " if cond else "  FAIL ") + name + (("   " + str(detail)) if detail and not cond else ""))


class E:
    """合成一个鼠标事件：KTimeline 只用到 .x 和 .delta，不需要真窗口消息"""

    def __init__(self, x, delta=0):
        self.x, self.delta = x, delta


# ---------------------------------------------------------------- 素材 / 截图
def make_video(path):
    """合成一段带音轨的小视频（testsrc2 + 正弦音）：不借任何真实番剧素材，谁跑都一样"""
    if os.path.exists(path) and os.path.getsize(path) > 20000:
        return path
    ff = shutil.which("ffmpeg")
    if not ff:
        print("找不到 ffmpeg（PATH 里没有），合成视频跳过")
        return None
    cmd = [ff, "-hide_banner", "-loglevel", "error", "-y",
           "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=24:duration=20",
           "-f", "lavfi", "-i", "sine=frequency=440:duration=20",
           "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-shortest", path]
    r = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if r.returncode != 0 or not os.path.exists(path):
        print("合成视频失败：", (r.stderr or "").strip()[-400:])
        return None
    return path


def png_size(path):
    """读 PNG 头里的宽高：够判断「截的是不是自己那个窗口」，不用解像素"""
    with open(path, "rb") as f:
        data = f.read(24)
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return 0, 0
    return struct.unpack(">II", data[16:24])


def shot_ink(path, ff):
    """(近白像素占比, 颜色数)：真窗口里有大片预览和小片深色时间轴，
    近白不可能占绝大多数；一张全白/空窗口才会。缩到 90x50 再统计，不自己解 PNG
    （PNG 有 5 种行 filter，纯 Python 解一张 1800x1000 太慢；ffmpeg 本来就在）"""
    r = subprocess.run([ff, "-v", "error", "-i", path, "-vf", "format=rgb24,scale=90:50",
                        "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                       capture_output=True)
    b = r.stdout
    if len(b) != 90 * 50 * 3:
        return None
    px = [(b[i], b[i + 1], b[i + 2]) for i in range(0, len(b), 3)]
    lum = [0.299 * a + 0.587 * g + 0.114 * bl for a, g, bl in px]
    return sum(1 for v in lum if v > 240) / len(lum), len(set(px))


def start_shot(tab, path):
    """在后台线程截自己那个窗口：先把旧图删掉，免得上一轮的图冒充这一轮的成功"""
    if os.path.exists(path):
        os.remove(path)
    log = C.gen("gui_%s_ffmpeg.log" % tab)

    def work():
        # -pix_fmt rgb24 不是为了省空间，是必须：gdigrab 按窗口截（title=）出来的是 BGRA 且
        # alpha 全是 0（BitBlt 不填 alpha），PNG 会留着这个 alpha，看图软件就把整张图当全透明
        # 显示成一片白——内容其实在里面。去掉 alpha 才能看到真窗口。
        cmd = [shutil.which("ffmpeg") or "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
               "-f", "gdigrab", "-i", "title=" + TITLE, "-frames:v", "1", "-pix_fmt", "rgb24", path]
        # 输出重定向到文件而不是管道：某些受限环境下管道会 EPERM，文件最稳
        with open(log, "w", encoding="utf-8", errors="replace") as lf:
            rc = subprocess.run(cmd, stdout=lf, stderr=lf).returncode
        SHOT.update({"path": path, "rc": rc, "log": log,
                     "size": os.path.getsize(path) if os.path.exists(path) else 0})

    threading.Thread(target=work, daemon=True).start()


def check_shot(app):
    if not SHOT:
        check("截图：线程还没回来", False, "ffmpeg 还没跑完")
        return
    rc, size, path = SHOT["rc"], SHOT["size"], SHOT["path"]
    check("截图生成了（%s）" % os.path.basename(path), rc == 0 and size > 0,
          "ffmpeg rc=%s size=%s；看日志 %s" % (rc, size, SHOT["log"]))
    if rc != 0 or size <= 0:
        tail = ""
        try:
            tail = open(SHOT["log"], encoding="utf-8", errors="replace").read().strip()[-200:]
        except OSError:
            pass
        print("        ffmpeg 说：", tail or "（无输出）")
        return
    w, h = png_size(path)
    cw, ch = app.winfo_width(), app.winfo_height()
    sw, sh = app.winfo_screenwidth(), app.winfo_screenheight()
    check("截到的是自己那个窗口（%dx%d，客户区 %dx%d，屏幕 %dx%d）" % (w, h, cw, ch, sw, sh),
          abs(w - cw) <= 8 and abs(h - ch) <= 8 and w < sw and h < sh)
    ink = shot_ink(path, shutil.which("ffmpeg") or "ffmpeg")
    if ink is None:
        check("截图能解码出像素", False, "ffmpeg 解不出 90x50 的采样")
        return
    white, colors = ink
    check("截图是画出来的真内容（近白 %.0f%%，%d 种颜色）" % (100 * white, colors),
          white < 0.6 and colors >= 50, "近白 %.0f%% 颜色 %d" % (100 * white, colors))
    print("  截图：%s  %d 字节  %dx%d" % (path, size, w, h))


# ---------------------------------------------------------------- 主流程
def main():
    argv = sys.argv[1:]
    tab = next((a for a in argv if a in ("fx", "kara", "ai")), None)
    keep = "--keep" in argv
    if tab is None:
        print("用法：python tests\\test_gui.py fx|kara|ai [--keep]")
        return 2
    print("真窗口冒烟：%s 页%s" % (tab, "（--keep：跑完窗口留着）" if keep else ""))

    # 合成素材：一行屏字 + 一句卡拉OK（4 个音节）+ 字幕自带的模板行；不绑死任何一部番
    rows = [
        fixtures.row(r"{\pos(300,900)\blur5\an7}测试屏字", style="Screen", start=2000, end=6000, layer=3),
        fixtures.row(r"{\fad(200,200)}这是对白第一句", style="Text CN", start=2000, end=5000),
        fixtures.row(r"{\fad(200,200)}これが最初のセリフ", style="Text JP", start=2000, end=5000, layer=1),
        fixtures.sub(r"{\k50}な{\k50}ん{\k50}ど{\k50}も", "OP JP", 2000, 6000),
        fixtures.sub(r"{\k50}怎{\k50}么{\k50}就", "OP CN", 2000, 6000),
        # 注释在这里必须写 1 而不是 True：dump 落盘是 str(True)="True"，读回来只认 "1"/"true"（大小写敏感），
        # 写成 True 的话模板行会被当成普通台词行，套模板就悄悄变成「没有模板可用」
        fixtures.row(r"{\an5\fad(80,80)}", style="OP JP", start=0, end=0, effect="template syl", comment=1),
    ]
    dump = fixtures.write_dump_file("gui_dump.tsv", rows)
    doc = z.Doc(dump)
    picker = {"fx": lambda r: r["style"] == "Screen",
              "kara": lambda r: r["style"] in ("OP JP", "OP CN"),
              "ai": lambda r: r["style"] == "Text CN"}
    sel = [r["i"] for r in doc.dialogue() if picker[tab](r)]
    if not sel:
        print("合成字幕里没有 %s 页要的行" % tab)
        return 2

    # 临时样式库：只活在临时目录里，不动组件目录里的方案
    cat = tempfile.mkdtemp(prefix="zx_gui_cat_")
    lib = fe.Library(cat)
    sd = {p["name"]: p for p in lib.cats[fe.CATALOG_SEED]}
    lib.cats["测试番"] = [
        fe.migrate({"cat": "测试番", "name": "Screen", "style": dict(sd["Screen 发光"]["style"]),
                    "fx": dict(sd["Screen 发光"]["fx"])}),
        fe.migrate({"cat": "测试番", "name": "Screen #08",
                    "style": dict(sd["Screen 弹出"]["style"], fontname="Yu Gothic"),
                    "fx": dict(sd["Screen 弹出"]["fx"])}),
    ]
    lib.write("测试番")
    lib.cats["另一部番"] = [dict(sd["OP CN"], cat="另一部番"), dict(sd["ED JP"], cat="另一部番")]
    lib.write("另一部番")

    video = make_video(C.gen("gui_clip.mp4"))
    out = C.gen("gui_%s_ops.tsv" % tab)
    if os.path.exists(out):
        os.remove(out)
    shot_png = C.gen("gui_%s.png" % tab)
    kara_i = next((r["i"] for r in doc.dialogue() if r["style"] == "OP JP"), None)
    job = {"catalog_dir": cat, "catalog": "测试番", "number": 8, "catalog_saved": True, "tab": tab,
           "dump": dump, "sel": sel, "active": sel[0], "video": video or "", "time": 2000,
           "vsfilter": C.VSFILTER, "aegisub_dir": C.AEGISUB, "out": out}

    try:
        app = fe.App(job)
    except Exception as ex:
        import traceback
        traceback.print_exc()
        print("窗口开不起来：", ex)
        return 1
    app.title(TITLE)                          # ASCII 标题，给 gdigrab 的 title= 用
    app.geometry("+0+0")
    app.attributes("-topmost", True)
    app.report_callback_exception = lambda *a: ERRORS.append(a)

    # apply 在没有改动时会弹确认框；无人值守的测试里直接放行并记下来
    fe.messagebox.askyesno = lambda *a, **k: (ASKED.append(a), True)[1]

    ctx = {"tab": tab, "out": out, "keep": keep, "row": sel[0], "kara_i": kara_i, "dur": 4000}

    def ready():
        check("窗口标题是 ASCII（gdigrab 靠它认窗口）", app.title() == TITLE, app.title())
        check("当前页是 %s" % tab, app.cur_tab() is {"fx": app.fx, "kara": app.ka, "ai": app.ai}[tab])
        check("预览渲染器起来了（高 %d px）" % app.player.ph, app.player.ph > 50)
        check("合成视频打开了", app.player.video is not None,
              "player.video 为空 → 预览退化成灰底，且没有波形")
        if app.player.video:
            print("  视频：%s  %.3f fps  %.1fs" % (os.path.basename(video), app.player.video.fps,
                                                  app.player.video.duration))
        # 收成普通尺寸的窗口：默认 state("zoomed") 会占满屏幕，那样截出来的图看不出是「只截了窗口」；
        # 缩到比屏幕小、再挪开屏幕原点，截图尺寸就成了「截的是窗口而不是桌面」的硬证据
        app.state("normal")
        app.geometry("1800x1000+40+40")

    def sized():
        check("窗口按普通尺寸布局（%dx%d，屏幕 %dx%d）"
              % (app.winfo_width(), app.winfo_height(), app.winfo_screenwidth(), app.winfo_screenheight()),
              1700 <= app.winfo_width() <= 1900 and 850 <= app.winfo_height() <= 1150)

    # ---- 各页的动作：都排进 after，让真 mainloop 一盘一盘走
    steps = [(600, "窗口就绪", ready), (1250, "窗口尺寸", sized)]

    if tab == "fx":
        def fx_pick():
            check("样式方案列表非空", app.fx.mine.size() > 0 and bool(app.fx.entries()), app.fx.mine.size())
            check("按编号选中「Screen #08」", app.fx.cur is not None and app.fx.cur["name"] == "Screen #08",
                  app.fx.cur and app.fx.cur["name"])
            check("激活行就是选中的屏字行", (app.active_line() or {}).get("i") == ctx["row"])
            app.fx.set_pos((1300, 350))
            app.player.seek(2.0)
        steps.append((1300, "fx 选行 + set_pos", fx_pick))

        def fx_fonts():
            check("特效样式页有「字体文件夹」那一行", bool(app.fx.folder_lbl) and bool(app.fx.folder_lbl.winfo_exists()))
            check("字体名旁边有状态小字", bool(app.fx.font_note_lbl) and bool(app.fx.font_note_lbl.winfo_exists()))
            folder = C.font_dir()
            if not folder:
                print("  （跳过）选字体文件夹：没设 ZX_FONT_DIR")
            else:
                # 选文件夹会存设置、还会弹一个说明框：测试里都换成临时的
                old = (fe.SETTINGS, fe.filedialog.askdirectory, fe.messagebox.showinfo)
                fe.SETTINGS = os.path.join(cat, "fx_settings.json")
                fe.filedialog.askdirectory = lambda *a, **k: folder
                fe.messagebox.showinfo = lambda *a, **k: None
                try:
                    app.pick_fonts()
                finally:
                    fe.SETTINGS, fe.filedialog.askdirectory, fe.messagebox.showinfo = old
                lbl = app.fx.folder_lbl.cget("text")
                check("选完文件夹后显示了文件数和能用几个", "个文件" in lbl and "能用" in lbl, lbl)
                fams = [n for n in z.scan_fonts(folder) if n in list(app.fx.font_cb["values"])]
                check("字体文件夹里的家族名进了字体下拉", bool(fams), (fams[:3], len(app.fx.font_cb["values"])))
                if fams:
                    app.fx.v["fontname"].set(fams[0])
                    note = app.fx.font_note_lbl.cget("text")
                    check("选文件夹里的字体时小字说「没装进系统」", "没装进系统" in note, note)
            app.fx.v["fontname"].set("绝无此字体XYZ")
            check("字体名不存在时小字会警告拿谁顶替",
                  "顶替" in app.fx.font_note_lbl.cget("text"), app.fx.font_note_lbl.cget("text"))
            app.fx.v["fontname"].set("Yu Gothic")          # 后面 fx_check 还要核这个字体，先还原
        steps.append((1750, "fx 字体文件夹", fx_fonts))

        def fx_check():
            check("set_pos 后产生了待应用改动", app.fx.edits.count() > 0, app.fx.edits.count())
            styles, ev = app.preview_view()
            row = next((r for r in ev if r.get("i") == ctx["row"]), None)
            check("选中行还在改动视图里", row is not None)
            txt = row["text"] if row else ""
            check("屏字行拿到新位置 \\pos(1300,350)", "\\pos(1300,350)" in txt, txt[:90])
            check("旧位置被换掉（不再是 300,900）", "\\pos(300,900)" not in txt, txt[:90])
            check("淡入淡出写进去了", "\\fad(" in txt, txt[:90])
            check("编号专用预设的弹出动画写进去了", "\\t(" in txt and "\\fscx" in txt, txt[:130])
            st = styles.get("Screen") or {}
            check("样式换成了编号专用预设的字体（Yu Gothic）", st.get("fontname") == "Yu Gothic", st.get("fontname"))
        steps.append((2600, "fx 核对改动", fx_check))
        tail = 3400
    elif tab == "kara":
        def kara_tpl():
            check("卡拉OK页认出了所选歌词", len(app.ka.src) == 2, app.ka.src)
            print("  社区模板列表：%s 个（只读本地 index.json，不联网）" % len(app.ka.pack_index or []))
            app.ka.tsrc.set("file")          # 用字幕自带的模板行：不联网、可复现
            app.ka.src_changed()
        steps.append((1300, "kara 套模板", kara_tpl))

        def kara_gen():
            n = app.ka.edits.count()
            check("套模板后生成了待应用改动", n > 0, n)
            log = app.ka.log.cget("text")
            check("模板执行没报错", "模板出错" not in log, log[:200])
            check("日志报了生成行数", "生成" in log, log[:200])
            styles, ev = app.preview_view()
            fx = [r for r in ev if r.get("effect") == "fx"]
            check("生成了 fx 行", len(fx) > 0, len(fx))
            check("fx 行里带上了歌词正文", any("な" in r["text"] for r in fx), [r["text"][:40] for r in fx[:3]])
            src = next((r for r in ev if r.get("i") == kara_i), None)
            check("源歌词行被模板替换成注释行", bool(src) and src["comment"] is True, src and src["comment"])
        steps.append((2900, "kara 核对生成", kara_gen))

        def kara_tl():
            tl = app.ka.tl
            check("时间轴装上了这一句（4 个音节）",
                  tl.line is not None and len(tl.syls) == 4 and tl.line["style"] == "OP JP",
                  (tl.line and tl.line["style"], tl.syls, tl.starts))
            check("时间轴画布有宽度", tl.cv.winfo_width() > 100, tl.cv.winfo_width())
            app.player.seek(1.5)
        steps.append((3600, "kara 时间轴就绪", kara_tl))

        def kara_drag():
            tl = app.ka.tl
            x0 = tl.x_of(tl.line["start_time"] / 1000 + tl.starts[0] / 1000)
            tl.press(E(x0))                  # 抓住第一个 ◆
            tl.motion(E(x0 + 12))            # 往右拖
            tl.release(E(x0 + 12))
            check("拖 ◆ 改了开口时间", tl.starts[0] > 0, tl.starts)
            tl.pop()                         # 撤销（Ctrl+Z 走的是同一个 pop）
            check("撤销把开口时间收回来了", tl.starts[0] == 0, tl.starts)
        steps.append((4400, "kara 拖 ◆ + 撤销", kara_drag))

        # 第一次 K = 开打点并从「本句前 1 秒」开始播；之后 4 次填满 4 个音节。
        # 第一次 K 之后留 2.1 秒再按（而不是贴着 1 秒边）：player.play() 里切 wav / 起线程要花几十毫秒，
        # 留窄了第一个字的开口时间会被 clamp 到 0，那是测试自己的抖动，不是插件的回归
        taps = [4900, 7000, 7300, 7600, 7900]
        steps.append((taps[0], "kara 开始打点", lambda: app.event_generate("<KeyPress-k>")))
        steps.append((taps[1] - 150, "kara K 键绑定生效",
                      lambda: check("窗口的 K 键真的触发了打点", app.ka.tl.tap is not None, app.ka.tl.tap)))
        for t in taps[1:]:
            steps.append((t, "kara 按 K", lambda: app.event_generate("<KeyPress-k>")))

        def kara_assert():
            tl = app.ka.tl
            check("打点后开口时间单调不减", tl.starts == sorted(tl.starts), tl.starts)
            check("第一个字打在句首之后（确实是在播放里按的点，不是被 clamp 到 0）", tl.starts[0] > 0, tl.starts)
            diffs = [tl.starts[k + 1] - tl.starts[k] for k in range(len(tl.starts) - 1)]
            check("每次打点的间隔跟得上 300ms 的按键节奏（%s）" % diffs,
                  all(150 <= d <= 450 for d in diffs), diffs)
            check("打点结果存进了这一句", app.ka.starts[app.ka.cur] == (tl.syls, tl.starts),
                  app.ka.starts[app.ka.cur])

            n0 = len(tl.syls)
            xs = [tl.x_of(tl.line["start_time"] / 1000 + t / 1000) for t in tl.starts]
            tl.right(E(xs[1]))                        # 右键第 2 个 ◆：和第 1 个合并
            check("合并：两个音节并成一个", len(tl.syls) == n0 - 1, tl.syls)
            xs = [tl.x_of(tl.line["start_time"] / 1000 + t / 1000) for t in tl.starts] \
                + [tl.x_of(tl.line["end_time"] / 1000)]
            tl.right(E((xs[-2] + xs[-1]) / 2))        # 右键最后一个字中间：拆成「字 + 空拍」
            check("拆开：一个字的后面多出一拍空音节",
                  len(tl.syls) == n0 and tl.syls[-1] == "", tl.syls)
            text = z.auto_k(tl.line["text"], tl.dur(), starts=tl.starts, syls=tl.syls)
            check("写回的 \\k 与切法往返一致", z.k_starts(text, tl.dur()) == (tl.syls, tl.starts),
                  (z.k_starts(text, tl.dur()), tl.syls, tl.starts))
            FINAL.update({"syls": list(tl.syls), "starts": list(tl.starts)})

            w0 = tl.win()
            tl.wheel(E(tl.cv.winfo_width() / 2, 120))
            tl.wheel(E(tl.cv.winfo_width() / 2, 120))
            check("滚轮缩小了时间轴窗口", tl.win()[1] - tl.win()[0] < w0[1] - w0[0], (w0, tl.win()))
            tl.wheel(E(0, -120), pan=True)
            check("Shift+滚轮平移后窗口还有宽度", tl.win()[1] > tl.win()[0], tl.win())
            check("波形已加载", app.player.wav is not None, app.player.wav)
            app.player.stop()
        steps.append((8700, "kara 打点/合并/拆开/缩放核对", kara_assert))
        tail = 9500
    else:
        def ai_say():
            check("当前页是 AI 助手", app.cur_tab() is app.ai)
            app.ai.say("（测试：这里是 AI 对话区）\n", "tool")
        steps.append((1300, "ai 写一句", ai_say))

        def ai_check():
            txt = app.ai.chat.get("1.0", "end")
            check("对话区里能看到这句话", "（测试：这里是 AI 对话区）" in txt, txt[-90:])
            check("AI 页没有待应用改动", app.ai.edits.count() == 0, app.ai.edits.count())
            check("待应用计数已刷新", "0 处" in app.ai.pend.cget("text"), app.ai.pend.cget("text"))
        steps.append((2500, "ai 回读", ai_check))
        tail = 3300

    # ---- 收尾：截图（只截自己窗口）→ 播放预览 → 应用
    steps.append((tail, "截图", lambda: start_shot(tab, shot_png)))
    steps.append((tail + 2000, "核对截图", lambda: check_shot(app)))
    steps.append((tail + 2600, "播放预览", app.player.play))
    steps.append((tail + 4200, "播放推进",
                  lambda: print("  播放中 t=%.2f（片段 %.1f~%.1fs）" % (app.player.t, app.player.t0, app.player.t1))))

    def do_apply():
        if keep:
            print("  --keep：跳过 apply（apply 会 close→destroy，窗口就没了，所以也不写 ops）")
            return
        app.apply()
    steps.append((tail + 5000, "应用", do_apply))

    for at, name, fn in steps:
        def run(fn=fn, name=name):
            try:
                fn()
            except Exception as ex:      # 回调里的异常不能被 report_callback_exception 吞掉
                import traceback
                traceback.print_exc()
                check("步骤「%s」没抛异常" % name, False, "%s: %s" % (type(ex).__name__, ex))
        app.after(at, run)

    app.mainloop()

    # ---- 应用之后：核对 ops 文件真的写出了这一页的改动
    if not keep:
        ops = []
        if os.path.exists(out):
            ops = [ln.split("\t") for ln in
                   open(out, encoding="utf-8-sig", newline="").read().splitlines() if ln]
        print("\n窗口异常：", ERRORS or "无")
        if tab == "fx":
            check("apply 写出了 ops 文件", bool(ops), out)
            texts = [p[3] for p in ops if p[:3] == ["set", str(ctx["row"]), "text"]]
            check("ops 里有选中行的文本改动", bool(texts), [p[:3] for p in ops][:6])
            if texts:
                check("ops 写回的就是新位置 \\pos(1300,350)", "\\pos(1300,350)" in z.unesc(texts[0]),
                      z.unesc(texts[0])[:90])
        elif tab == "kara":
            check("apply 写出了 ops 文件", bool(ops), out)
            trow = [p[3] for p in ops if p[:3] == ["set", str(ctx["kara_i"]), "text"]]
            check("ops 里有卡拉OK源行的改动", bool(trow), [p[:3] for p in ops][:6])
            if trow and FINAL:
                got = z.k_starts(z.unesc(trow[0]), ctx["dur"])
                check("ops 里写回的 \\k 和 GUI 里打出来的切法往返一致",
                      got == (FINAL["syls"], FINAL["starts"]), (got, FINAL))
            fx_ins = [p for p in ops if p[0] == "ins" and len(p) > 13 and p[12] == "fx" and p[13].strip()]
            check("ops 里插进了模板生成的 fx 行", bool(fx_ins), len([p for p in ops if p[0] == "ins"]))
        else:
            check("AI 页没产生改动 → apply 不写 ops", not ops, out)
            check("apply 走了「没有改动」的确认框", bool(ASKED), ASKED)

    check("窗口回调没有抛出异常", not ERRORS, [str(e[1]) for e in ERRORS][:3])
    if os.path.exists(shot_png):
        print("截图文件：%s  %d 字节" % (shot_png, os.path.getsize(shot_png)))

    print("\n通过 %d 项，失败 %d 项" % (len(OK), len(BAD)))
    if BAD:
        print("失败项：" + "；".join(BAD))
    return 1 if BAD else 0


if __name__ == "__main__":
    raise SystemExit(main())
