r"""字体文件夹：字体留在文件夹里，不装进系统也能用。

用户不想为了做特效把字体装进系统（占地方、卸载也麻烦），所以插件走的是「只注册给本进程」：
Lua 侧在 Aegisub 里 AddFontResourceExW(FR_PRIVATE)，Python 侧在工作台进程里做同一件事；
不写注册表、不往系统字体目录拷东西、进程一退就没了。Aegisub 的预览是 csri 的 xy-VSFilter
（靠 GDI 找字体），进程里注册过它就认得 —— 这条是这里最要紧的断言。

分五层验：
  1. 字体名解析：ttf / otf / ttc 的 name 表 → 家族名（中文名优先），坏文件不炸；
  2. 目录扫描：只收字体文件、含子目录、不重复，且没真字形的合成分不会被列进界面；
  3. GDI 解析：装了的字体认自己；没装又没注册的名字会回退成别的（所以「认自己」= 真用上了）；
  4. Lua 侧：Aegisub 加载插件时按 fx_settings.json 里的字体文件夹注册（在假 Aegisub 里真跑）；
  5. 真渲染：同一份字幕，用文件夹里的字体画出来的画面和回退字体画出来的不一样。

第 4、5 层各起一个子进程跑（AddFontResourceEx 是进程级的，同一个进程里注册过第二次就数不出来了），
需要 ZX_FONT_DIR 指一个「没装进系统的字体」文件夹，没设就跳过（会打印跳过原因）。

    python tests\test_fonts.py
"""
import json
import os
import re
import struct
import subprocess
import sys
import tempfile
import traceback

import bootstrap  # noqa: F401  （放好 sys.path，必须在最前面）
import luaharness  # noqa: E402
import testconfig as C  # noqa: E402

z, _fe, _ai = C.load_src()

OK = []
BAD = []
SKIP = []


def check(name, cond, detail=""):
    (OK if cond else BAD).append(name)
    print(("  OK   " if cond else "  FAIL ") + name + (("   " + str(detail)) if detail and not cond else ""))


def head(title):
    print("\n== " + title)


def skip(name, why):
    SKIP.append(name)
    print("  （跳过）%s：%s" % (name, why))


# ================================================================ 造字体文件

def name_table(records):
    """records: [(平台, 语言, 名字类型, 文字)] → name 表（Unicode / Windows 的记录是 UTF-16BE）"""
    strings, recs = b"", b""
    for pid, lid, nid, text in records:
        raw = text.encode("utf-16-be" if pid in (0, 3) else "ascii")
        recs += struct.pack(">HHHHHH", pid, 1, lid, nid, len(raw), len(strings))
        strings += raw
    return struct.pack(">HHH", 0, len(records), 6 + 12 * len(records)) + recs + strings


def make_font(records, version=b"\x00\x01\x00\x00"):
    """一个只有 name 表的 sfnt：解析家族名够用（family_names 不校验 checksum）。
    表记录里的偏移按规范是「相对文件开头」的，独立字体就是 28。"""
    nt = name_table(records)
    return version + struct.pack(">HHHH", 1, 16, 0, 0) + b"name" + struct.pack(">III", 0, 28, len(nt)) + nt


def make_ttc(fonts):
    """ttcf 头 + 每个字体一份表目录。TTC 里表偏移一律相对文件开头（真字体也这样，写测试时踩过一次）"""
    at, heads, blobs = 12 + 4 * len(fonts), [], []
    for f in fonts:
        b = bytearray(f)
        base = at + sum(len(x) for x in blobs)
        for i in range(int.from_bytes(b[4:6], "big")):      # 把每条表记录的偏移改成绝对偏移
            r = 12 + i * 16
            b[r + 8:r + 12] = struct.pack(">I", int.from_bytes(b[r + 8:r + 12], "big") + base)
        heads.append(base)
        blobs.append(bytes(b))
    return (b"ttcf" + struct.pack(">II", 0x00010000, len(fonts))
            + b"".join(struct.pack(">I", h) for h in heads) + b"".join(blobs))


REC = [(3, 0x0409, 1, "Test Latin"), (3, 0x0804, 1, "测试字体"),
       (3, 0x0409, 16, "Test Latin Typo"), (1, 0, 1, "MacName")]
SECOND = make_font([(3, 0x0409, 1, "Second Font")])


# ================================================================ 1~3. 解析 / 扫描

def test_parse(tmp):
    head("1. 字体名解析（合成字体，不看你机器上装了什么）")
    p = os.path.join(tmp, "a.ttf")
    with open(p, "wb") as f:
        f.write(make_font(REC))
    names = z.family_names(p, limit=4)
    check("中文名排在最前（样式里常用它）", names[:1] == ["测试字体"], names)
    check("英文名也在", "Test Latin Typo" in names, names)
    check("Mac 那份乱码不要", not any("Mac" in n for n in names), names)
    check("默认最多给两个名字", len(z.family_names(p)) == 2, z.family_names(p))

    q = os.path.join(tmp, "b.otf")
    with open(q, "wb") as f:
        f.write(make_font(REC, version=b"OTTO"))
    check("otf（OTTO 头）一样解析", z.family_names(q)[:1] == ["测试字体"], z.family_names(q))

    t = os.path.join(tmp, "c.ttc")
    with open(t, "wb") as f:
        f.write(make_ttc([make_font(REC), SECOND]))
    tn = z.family_names(t, limit=4)
    check("ttc 里两个字体的名字都读得到（表偏移是绝对偏移）",
          "测试字体" in tn and "Second Font" in tn, tn)


def test_bad(tmp):
    head("2. 坏文件不炸")
    check("路径不存在 → 空表", z.family_names(os.path.join(tmp, "没有这个.ttf")) == [])
    p = os.path.join(tmp, "bad.ttf")
    with open(p, "wb") as f:                      # 表数写成一万多个，文件却很短
        f.write(b"\x00\x01\x00\x00\xff\xff\x00\x00" + b"\x00" * 40)
    check("乱字节 → 空表", z.family_names(p) == [], z.family_names(p))
    q = os.path.join(tmp, "note.dat")
    with open(q, "wb") as f:
        f.write(b"not a font at all" * 4)
    check("不是字体 → 空表", z.family_names(q) == [])
    d = os.path.join(tmp, "空目录")
    os.makedirs(d, exist_ok=True)
    check("空目录 → 空", z.font_files(d) == [] and z.scan_fonts(d) == {})


def test_scan(tmp):
    head("3. 目录扫描")
    sub = os.path.join(tmp, "fonts", "子目录")
    os.makedirs(sub, exist_ok=True)
    root = os.path.dirname(sub)
    for name, data in (("a.ttf", make_font(REC)), ("b.OTF", make_font([(3, 0x0409, 1, "Upper Ext")])),
                       ("readme.txt", b"not a font")):
        with open(os.path.join(root, name), "wb") as f:
            f.write(data)
    with open(os.path.join(sub, "c.ttc"), "wb") as f:
        f.write(make_ttc([SECOND]))
    got = [os.path.basename(x) for x in z.font_files(root)]
    check("只收字体文件（含子目录、大小写都认、顺序稳定）", got == ["a.ttf", "b.OTF", "c.ttc"], got)
    sc = z.scan_fonts(root)
    check("家族名 → 文件对得上", sc.get("测试字体", "").endswith("a.ttf") and "Second Font" in sc, sorted(sc))
    check("目录不存在 → 空", z.font_files(os.path.join(tmp, "没这个目录")) == []
          and z.scan_fonts(os.path.join(tmp, "没这个目录")) == {})
    check("只有名字、没有真字形的合成分不会被列进界面", z.usable_fonts(root) == {}, sorted(z.usable_fonts(root)))


# ================================================================ 4. GDI

def test_gdi():
    head("4. GDI 解析：装了才认，没装会回退")
    win = os.environ.get("WINDIR", r"C:\Windows")
    cand = [os.path.join(win, "Fonts", n) for n in ("arial.ttf", "segoeui.ttf", "simhei.ttf", "msyh.ttc")]
    p = next((x for x in cand if os.path.exists(x)), None)
    if p is None:
        skip("系统字体被 GDI 认出来", "这台机器上常见系统字体一个都没找到")
    else:
        names = z.family_names(p, limit=4)
        check("%s 能读出家族名" % os.path.basename(p), bool(names), names)
        check("系统装了的字体：GDI 至少认它的一个名字",
              any(z.font_ok(n) for n in names), (names, [z.resolve_face(n) for n in names]))
    fake = "绝对不存在的字体名XYZ"
    check("没装的名字 GDI 不认（会回退成别的字体）", not z.font_ok(fake), z.resolve_face(fake))
    check("resolve_face 回退到的不是它自己", z._face_norm(z.resolve_face(fake)) != z._face_norm(fake),
          z.resolve_face(fake))


# ================================================================ 5. Lua 侧（子进程）

def test_lua(tmp):
    head("5. Aegisub 加载插件时就注册（假 Aegisub 里真跑）")
    folder = C.font_dir()
    if not folder:
        skip("插件加载时按 fx_settings.json 注册字体", "没设 ZX_FONT_DIR")
        return
    files = z.font_files(folder)
    if not files:
        skip("插件加载时按 fx_settings.json 注册字体", "%s 里没有字体文件" % folder)
        return

    home = os.path.join(tmp, "home")
    comp = os.path.join(home, "zhouxiao-autotime")
    os.makedirs(comp, exist_ok=True)
    with open(os.path.join(comp, "fx_settings.json"), "w", encoding="utf-8") as f:
        json.dump({"fonts_dir": folder}, f, ensure_ascii=False)

    h = luaharness.Harness(home=home)        # 加载插件 = Aegisub 启动
    line = next((t for lv, t in h.logs if "字体文件夹" in t), "")
    check("插件加载时注册了字体（日志里有）", "注册了" in line, h.logs)
    m = re.search(r"注册了 (\d+) 个", line)
    n_lua = int(m.group(1)) if m else 0
    check("Lua 数出来的字体文件数和 Python 一样（宽字符目录也走得通）", n_lua == len(files), (n_lua, len(files), line))
    with open(C.lua_path(), encoding="utf-8", newline="") as f:
        src = f.read()
    check("注册用的是只给本进程的 FR_PRIVATE（0x10）", "0x10" in src)
    check("按设置里的文件夹注册（不是写死的路径）", "folder_fonts_from_settings" in src)

    # 空白文件夹：不该有任何输出
    with open(os.path.join(comp, "fx_settings.json"), "w", encoding="utf-8") as f:
        json.dump({"fonts_dir": os.path.join(tmp, "空空 的目录")}, f, ensure_ascii=False)
    h2 = luaharness.Harness(home=home)
    check("设置指向空文件夹时安静地什么都不做", not any("字体文件夹" in t for lv, t in h2.logs), h2.logs)


# ================================================================ 6. 真渲染（子进程）

def test_render():
    head("6. 没装进系统的字体，预览（xy-VSFilter）真能画出来")
    if not os.path.exists(C.vsfilter_path()):
        skip("xy-VSFilter 渲染", "找不到 %s" % C.vsfilter_path())
        return
    folder = C.font_dir()
    if not folder:
        skip("文件夹字体能渲染", "没设 ZX_FONT_DIR")
        return
    fonts = z.scan_fonts(folder)
    if not fonts:
        skip("文件夹字体能渲染", "%s 里没有字体文件" % folder)
        return

    unreg = [n for n in sorted(fonts) if not z.font_ok(n)]
    if not unreg:
        skip("文件夹字体能渲染", "这些字体其实都装进系统了（换一个没装的再测）")
        return
    check("注册之前：这个名字解析到的是别的字体（说明没装进系统）",
          z._face_norm(z.resolve_face(unreg[0])) != z._face_norm(unreg[0]),
          (unreg[0], z.resolve_face(unreg[0])))

    z.load_fonts(folder)                      # 工作台/插件做的就是这一步
    fam = next((n for n in unreg if z.font_ok(n)), None)
    check("注册之后 GDI 就认了，而且解析出来就是它自己",
          bool(fam) and z._face_norm(z.resolve_face(fam)) == z._face_norm(fam),
          (unreg[:3], z.resolve_face(fam) if fam else None))
    if not fam:
        return

    img_a = render(fam)
    img_b = render("绝对不存在的字体名XYZ")     # 同一份字幕、只换字体名 → 这条必然是回退字体
    check("文件夹字体画出来的画面 ≠ 回退字体画的（说明真用上了它）", img_a != img_b,
          "两图一样：%d 字节" % len(img_a))

    # 新开一个进程：同样的名字就解析不到了 —— 证明字体只是注册给本进程，没装进系统
    code = ("import sys;sys.path.insert(0,%r);import zxcore as z;print(z.resolve_face(%r))" % (C.SRC, fam))
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    got = (r.stdout or "").strip()
    check("新进程里这个名字没了（确实没装进系统）", bool(got) and z._face_norm(got) != z._face_norm(fam), got)


W, H = 1280, 720


def make_doc(font):
    """走插件自己的路：zxcore.Doc 的行 → ass_doc 拼出给 VSFilter 的 ASS"""
    d = z.Doc()
    d.rows = [
        {"class": "info", "key": "PlayResX", "value": str(W), "i": 1},
        {"class": "info", "key": "PlayResY", "value": str(H), "i": 2},
        {"class": "info", "key": "WrapStyle", "value": "2", "i": 3},
        {"class": "style", "name": "Default", "fontname": font, "fontsize": 110, "color1": "FFFFFF",
         "color2": "FFFFFF", "color3": "202020", "color4": "000000", "bold": False, "italic": False,
         "underline": False, "strikeout": False, "scale_x": 100, "scale_y": 100, "spacing": 0, "angle": 0,
         "borderstyle": 1, "outline": 3, "shadow": 0, "align": 5, "margin_l": 20, "margin_r": 20,
         "margin_t": 20, "encoding": 1, "i": 4},
        {"class": "dialogue", "comment": False, "layer": 0, "start_time": 0, "end_time": 9000,
         "style": "Default", "actor": "", "margin_l": 0, "margin_r": 0, "margin_t": 0, "margin_b": 0,
         "effect": "", "text": "轴效字体测试 永龙剑 字幕 ABC 123", "i": 5},
    ]
    return d


def render(font):
    """拿 Aegisub 预览用的那支 DLL（csri 的 xy-VSFilter）把一行字画出来。
    注意 csri_render 的时间单位是「秒」，不是毫秒。"""
    if not hasattr(render, "_vsf"):
        render._vsf = z.VSFilter(C.vsfilter_path(), W, H)
    d = make_doc(font)
    return render._vsf.render(z.ass_doc(d, d.styles(), d.dialogue(), 0, 9000),
                              bytes(bytearray([32, 32, 32, 255]) * (W * H)), 1.0)


# ================================================================ 跑

def summary():
    print("\n通过 %d 项，失败 %d 项%s" % (len(OK), len(BAD), ("，跳过 %d 项" % len(SKIP)) if SKIP else ""))
    return 1 if BAD else 0


def run_part(part):
    """单独起一个进程跑一节（字体注册是进程级的，混在一起就分不清是谁注册的）"""
    r = subprocess.run([sys.executable, os.path.abspath(__file__), "--part", part],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    out = (r.stdout or "") + (r.stderr or "")
    m = re.search(r"通过 (\d+) 项，失败 (\d+) 项", out)
    p, f = (int(m.group(1)), int(m.group(2))) if m else (0, 1)
    print(out.rstrip())
    OK.extend("%s#%d" % (part, i) for i in range(p))
    BAD.extend("%s#%d" % (part, i) for i in range(f))
    if not m:
        print("  （%s 那节没跑完，退出码 %d）" % (part, r.returncode))


def main():
    if "--part" in sys.argv:
        part = sys.argv[sys.argv.index("--part") + 1]
        tmp = tempfile.mkdtemp(prefix="zx_font_part_")
        try:
            {"lua": test_lua, "render": lambda _tmp: test_render()}[part](tmp)
        except Exception:
            BAD.append("未预期的异常")
            traceback.print_exc()
        return summary()

    tmp = tempfile.mkdtemp(prefix="zx_fonts_")
    try:
        test_parse(tmp)
        test_bad(tmp)
        test_scan(tmp)
        test_gdi()
    except Exception:
        BAD.append("未预期的异常")
        traceback.print_exc()
    print("\n== 5~6. 各起一个子进程跑（上面那几节不注册字体，这两节要）")
    run_part("lua")
    run_part("render")
    return summary()


if __name__ == "__main__":
    raise SystemExit(main())
