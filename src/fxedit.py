# Copyright (C) 2026 zzzwannasleep
# 原作者：zzzwannasleep（https://github.com/zzzwannasleep/AegisubPlugin）
# 授权：LGPL-3.0-or-later，条文见 LICENSE；出处与附加的署名要求见 NOTICE。
"""轴效特效工作台：特效样式 / 卡拉OK / AI 助手 三页，右边是带声音的视频预览（所选行前后各 5 秒）。
预览用 Aegisub 自带的 xy-VSFilter 渲染；卡拉OK直接跑 Aegisub 的 kara-templater.lua（在 Python 里用 LuaJIT）。
改动先攒着，点「应用」才写回 Aegisub（整批一步撤销）。

    python fxedit.py --job fxjob.json      Aegisub 插件走这条"""
import ctypes, json, os, queue, re, sys, tempfile, threading, time, tkinter as tk, tkinter.font
import urllib.parse, urllib.request
from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk

HOME = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOME)
import zxcore as z
import zxai

PW = 960
PRESETS = os.path.join(HOME, "fx_presets.json")
PACK = os.path.join(HOME, "kara_pack")
PACK_REPO = "Seekladoom/Aegisub-Karaoke-Effect-481-Templates"
PACK_DIR = "ASS Template/"
SETTINGS = os.path.join(HOME, "fx_settings.json")

# ================================================================ 特效样式预设
KEYS = ["fontname", "fontsize", "color1", "color2", "color3", "color4", "bold", "italic", "underline", "strikeout",
        "scale_x", "scale_y", "spacing", "angle", "borderstyle", "outline", "shadow", "align",
        "margin_l", "margin_r", "margin_v", "encoding"]
BASE = dict(fontname="Microsoft YaHei", fontsize=60, color1="00FFFFFF", color2="000000FF", color3="00000000",
            color4="80000000", bold=1, italic=0, underline=0, strikeout=0, scale_x=100, scale_y=100, spacing=0,
            angle=0, borderstyle=1, outline=3, shadow=0, align=5, margin_l=10, margin_r=10, margin_v=10, encoding=1)
ANIMS = ["无", "弹出", "放大落下", "由糊变清", "擦入", "从下滑入", "从上滑入", "从左滑入", "从右滑入", "逐字出现"]
FX0 = dict(fade_in=0, fade_out=0, blur=0.0, anim="无", anim_ms=300, glow=0, glow_size=6, glow_blur=6,
           glow_color="40A0FF", double=0, double_size=4, double_color="FFFFFF")


def seeds():
    """内置预设：名字是插件的样式名，应用后中日配对、同步时间照常。只示范常见做法，字体颜色按作品改。字号按 1080p"""
    CN, JP = "Microsoft YaHei", "Yu Gothic"

    def p(name, fx, extra="", **kw):
        return {"name": name, "style": {**BASE, **kw}, "fx": {**FX0, **fx}, "extra": extra, "extra_layers": []}
    op = dict(fade_in=250, fade_out=250, blur=0.8, glow=1, glow_size=6, glow_blur=7, glow_color="2050A0")
    return [
        p("OP CN", op, fontname=CN, fontsize=58, align=2, margin_v=32, outline=2, color3="00A05020"),
        p("OP JP", op, fontname=JP, fontsize=48, align=8, margin_v=32, outline=2, color3="00A05020"),
        p("ED CN", dict(fade_in=400, fade_out=400, blur=1), fontname=CN, fontsize=56, align=2, margin_v=32, bold=0,
          outline=2, color3="00403020"),
        p("ED JP", dict(fade_in=400, fade_out=400, blur=1), fontname=JP, fontsize=46, align=8, margin_v=32, bold=0,
          outline=2, color3="00403020"),
        p("Insert CN", dict(fade_in=200, fade_out=200, blur=0.6), fontname=CN, fontsize=48, align=9, margin_l=40,
          margin_r=40, margin_v=65, outline=2, color3="00604080"),
        p("Insert JP", dict(fade_in=200, fade_out=200, blur=0.6), fontname=JP, fontsize=38, align=9, margin_l=40,
          margin_r=40, margin_v=22, outline=2, color3="00604080"),
        p("Note", dict(fade_in=150, fade_out=150, blur=0.5), fontname=CN, fontsize=44, align=7, margin_l=40,
          margin_v=22, outline=2),
        p("Screen", dict(fade_in=150, fade_out=150, blur=1), fontname=CN, fontsize=64, align=5, outline=3),
        p("Screen 发光", dict(fade_in=150, fade_out=150, blur=0.8, glow=1, glow_size=8, glow_blur=10,
                            glow_color="40A0FF"), fontname=CN, fontsize=64, align=5, outline=0),
        p("Screen 弹出", dict(fade_in=80, fade_out=150, blur=1, anim="弹出", anim_ms=230), fontname=CN, fontsize=64,
          align=5, outline=3),
        p("Screen 擦入", dict(fade_out=150, blur=1, anim="擦入", anim_ms=700), fontname=CN, fontsize=64, align=5,
          outline=3),
        p("Screen 滑入", dict(fade_in=200, fade_out=150, blur=1, anim="从下滑入", anim_ms=300), fontname=CN,
          fontsize=64, align=5, outline=3),
        p("Screen 逐字", dict(fade_out=150, blur=1, anim="逐字出现", anim_ms=80), fontname=CN, fontsize=64, align=5,
          outline=3),
        p("Screen 手写", dict(fade_in=400, fade_out=300, blur=0.6, anim="由糊变清", anim_ms=400), fontname=CN,
          fontsize=64, align=5, bold=0, outline=0, shadow=0, color1="00303030"),
        p("Screen 双描边", dict(fade_in=150, fade_out=150, blur=0.8, double=1, double_size=5, double_color="FFFFFF"),
          fontname=CN, fontsize=64, align=5, outline=3, color3="00804020"),
        p("Screen 暗框", dict(fade_in=150, fade_out=150, blur=0.6), fontname=CN, fontsize=52, align=5,
          borderstyle=3, outline=10, color3="A0000000", color4="A0000000"),
    ]


def migrate(p):
    """老版本（0.18）预设只有 layers：第一层当「额外标签」，其余层放 extra_layers"""
    if "fx" not in p:
        lay = [x for x in p.get("layers", []) if x.strip()]
        p["fx"], p["extra"], p["extra_layers"] = dict(FX0), lay[0] if lay else "", lay[1:]
    p["fx"] = {**FX0, **p["fx"]}
    p.setdefault("extra", "")
    p.setdefault("extra_layers", [])
    p["style"] = {**BASE, **p.get("style", {})}
    return p


def num(x):
    x = float(x)
    return int(x) if x == int(x) else round(x, 2)


def bgr(rgb):
    rgb = rgb.lstrip("#").upper().rjust(6, "0")
    return rgb[4:6] + rgb[2:4] + rgb[0:2]


def preset_style(p):
    """预设 → 样式 dict（zxcore 的字段）"""
    s = p["style"]
    st = {k: s[k] for k in KEYS if k != "margin_v"}
    st["name"] = p["name"]
    st["margin_t"] = st["margin_b"] = s["margin_v"]
    for k in ("bold", "italic", "underline", "strikeout"):
        st[k] = bool(st[k])
    return st


def line_geom(measure, st, text, res, pos, line):
    """这行字的定位点和外框（脚本坐标）。pos=None 时按对齐和边距算"""
    m = re.search(r"\\an(\d)", text)
    an = int(m.group(1)) if m else int(st["align"])
    plain = re.sub(r"\{[^}]*\}", "", text)
    rows = plain.replace("\\n", "\\N").split("\\N")
    ws = [measure.extents(st, r)[0] for r in rows] or [0]
    h1 = measure.extents(st, rows[0] or "字")[1]
    w, h = max(ws), h1 * len(rows)
    col, row = (an - 1) % 3, (an - 1) // 3
    if pos is None:
        W, H = res
        ml = line.get("margin_l") or st["margin_l"]
        mr = line.get("margin_r") or st["margin_r"]
        mv = line.get("margin_t") or st["margin_t"]
        x = ml if col == 0 else W - mr if col == 2 else (ml + W - mr) / 2
        y = H - mv if row == 0 else H / 2 if row == 1 else mv
    else:
        x, y = pos
    left = x - w * col / 2
    top = y - h if row == 0 else y - h / 2 if row == 1 else y
    return (x, y), (left, top, left + w, top + h)


def build_layers(p, geom):
    """预设的特效 → ([(头部标签, 逐字用的透明标签或 None)...], \\move 或 None)，第一层在最上面"""
    fx, s = p["fx"], p["style"]
    (x, y), (l, t, r, b) = geom
    a = int(fx["anim_ms"])
    sx, sy = float(s["scale_x"]), float(s["scale_y"])
    common = ""
    if fx["fade_in"] or fx["fade_out"]:
        common += "\\fad(%d,%d)" % (fx["fade_in"], fx["fade_out"])
    blur = float(fx["blur"])
    anim, move = fx["anim"], None
    if anim == "弹出":
        common += "\\fscx%g\\fscy%g\\t(0,%d,\\fscx%g\\fscy%g)\\t(%d,%d,\\fscx%g\\fscy%g)" % (
            sx * .6, sy * .6, a * .65, sx * 1.08, sy * 1.08, a * .65, a, sx, sy)
    elif anim == "放大落下":
        common += "\\fscx%g\\fscy%g\\t(0,%d,\\fscx%g\\fscy%g)" % (sx * 1.4, sy * 1.4, a, sx, sy)
    elif anim == "擦入":
        common += "\\clip(%d,%d,%d,%d)\\t(0,%d,\\clip(%d,%d,%d,%d))" % (
            l - 20, t - 40, l - 20, b + 40, a, l - 20, t - 40, r + 20, b + 40)
    elif anim.endswith("滑入"):
        d = float(s["fontsize"]) * .8
        dx, dy = {"从下滑入": (0, d), "从上滑入": (0, -d), "从左滑入": (-d, 0), "从右滑入": (d, 0)}[anim]
        move = "\\move(%g,%g,%g,%g,0,%d)" % (round(x + dx, 1), round(y + dy, 1), round(x, 1), round(y, 1), a)
    blur_tag = ("\\blur%g\\t(0,%d,\\blur%g)" % (blur + 6, a, blur)) if anim == "由糊变清" else \
        ("\\blur%g" % blur if blur else "")
    pc = anim == "逐字出现"
    extra = p.get("extra", "").strip().strip("{}")
    layers = [(common + blur_tag + extra, "alpha" if pc else None)]
    out = float(s["outline"])
    if fx["double"]:
        layers.append((common + blur_tag + "\\bord%g\\3c&H%s&\\shad0" % (
            out + float(fx["double_size"]), bgr(fx["double_color"])), "alpha" if pc else None))
    if fx["glow"]:
        g = out + (float(fx["double_size"]) if fx["double"] else 0) + float(fx["glow_size"])
        layers.append((common + "\\bord%g\\blur%g\\3c&H%s&\\1a&HFF&\\shad0" % (
            g, float(fx["glow_blur"]), bgr(fx["glow_color"])), "3a" if pc else None))
    for e in p.get("extra_layers", []):
        if e.strip():
            layers.append((common + e.strip().strip("{}"), None))
    return layers, move


def per_char(body, step, tag):
    """逐字出现：每个字前面插 {\\alpha&HFF&\\t(t,t+1,\\alpha&H00&)}（发光层用 \\3a）"""
    out, k = "", 0
    for m in re.finditer(r"\{[^}]*\}|\\[Nnh]|.", body):
        s = m.group(0)
        if s.startswith("{") or s in ("\\N", "\\n", "\\h") or s.isspace():
            out += s
            continue
        out += "{\\%s&HFF&\\t(%d,%d,\\%s&H00&)}%s" % (tag, k * step, k * step + 1, tag, s)
        k += 1
    return out


CATALOG_SEED = "轴效起步"
NUM_RE = re.compile(r"\s#(\d+)$")   # 方案里「编号专用」的样式名后缀：ED CN #05（编号 = 集数、期数……）


def base_name(n):
    return NUM_RE.sub("", n)


def num_name(n, num):
    return "%s #%02d" % (base_name(n), num)


def partner(name):
    m = NUM_RE.search(name)
    suf, b = (m.group(0) if m else ""), base_name(name)
    for a, c in ((" CN", " JP"), (" JP", " CN")):
        if b.endswith(a):
            return b[:-3] + c + suf


def style_to_preset(st):
    """样式行（zxcore 字段）→ 预设里的 style 部分"""
    s = {k: st.get(k, BASE[k]) for k in KEYS if k != "margin_v"}
    s["margin_v"] = st.get("margin_t", 10)
    for k in ("color1", "color2", "color3", "color4"):
        s[k] = z.color_hex(s[k])
    for k in ("bold", "italic", "underline", "strikeout"):
        s[k] = int(bool(s[k]))
    return s


def title_stem(path):
    """视频文件名 → 标题部分（去掉方括号里的发布者 / 规格、编号），用来下次自动认出用哪个方案"""
    n = os.path.splitext(os.path.basename(path or ""))[0]
    n = re.sub(r"\[[^\]]*\]|\([^)]*\)|【[^】]*】", " ", n)
    n = re.split(r"\s-\s*\d{1,3}(?:v\d)?\b|\bS\d+E\d+|\bE\d{1,3}\b|第\s*\d+\s*[集话話]", n)[0]
    return re.sub(r"[\s._]+", " ", n).strip(" -")


class Library:
    """样式方案 = 样式 + 特效配方。样式存在 Aegisub 样式管理器的「样式库」文件 catalog\\名字.sty 里
    （Aegisub 自己也读写这个文件），特效配方存在旁边的 catalog\\名字.fx.json（按样式名）。编号专用的样式名带 #编号"""

    def __init__(self, d):
        self.dir = d
        os.makedirs(d, exist_ok=True)
        self.cats = {}
        for f in sorted(os.listdir(d)):
            if f.lower().endswith(".sty"):
                self.cats[f[:-4]] = self.read(f[:-4])
        if CATALOG_SEED not in self.cats:
            ents = seeds()
            try:   # 0.18 / 0.19 存在组件目录的预设并进来（同名的以你改过的为准）
                old = {p["name"]: migrate(p) for p in json.load(open(PRESETS, encoding="utf-8"))}
                ents = [old.pop(p["name"], p) for p in ents] + list(old.values())
            except (OSError, ValueError):
                pass
            for p in ents:
                p["cat"] = CATALOG_SEED
            self.cats[CATALOG_SEED] = ents
            self.write(CATALOG_SEED)

    def read(self, cat):
        try:
            text = open(os.path.join(self.dir, cat + ".sty"), encoding="utf-8-sig", errors="replace").read()
        except OSError:
            text = ""
        _, styles, _ = z.parse_ass(text)
        try:
            fx = json.load(open(os.path.join(self.dir, cat + ".fx.json"), encoding="utf-8")).get("styles", {})
        except (OSError, ValueError):
            fx = {}
        return [migrate({"cat": cat, "name": n, "style": style_to_preset(st), "fx": dict(fx.get(n, {}).get("fx", {})),
                         "extra": fx.get(n, {}).get("extra", ""), "extra_layers": fx.get(n, {}).get("extra_layers", [])})
                for n, st in styles.items()]

    def write(self, cat):
        ents = [p for p in self.cats.get(cat, []) if not p.get("local")]
        with open(os.path.join(self.dir, cat + ".sty"), "w", encoding="utf-8-sig", newline="\r\n") as f:
            f.write("".join(z.style_line(preset_style(p)) + "\n" for p in ents))
        with open(os.path.join(self.dir, cat + ".fx.json"), "w", encoding="utf-8") as f:
            json.dump({"styles": {p["name"]: {"fx": p["fx"], "extra": p["extra"],
                                              "extra_layers": p.get("extra_layers", [])} for p in ents}},
                      f, ensure_ascii=False, indent=1)

    def pick(self, cat, name, num):
        """当前字幕该用哪条：先「名字 #编号」（编号专用），再「名字」（通用）"""
        byn = {p["name"]: p for p in self.cats.get(cat, []) if not p.get("local")}
        return (byn.get(num_name(name, num)) if num else None) or byn.get(base_name(name))

    def add_alias(self, video, cat):
        """记住「这种视频文件名 → 这个方案」，同系列的下一个视频自动认出来（Lua 那边也读这个文件）"""
        stem = title_stem(video)
        if not stem or not cat:
            return
        p = os.path.join(self.dir, "zhouxiao-alias.tsv")
        try:
            rows = [l.rstrip("\n").split("\t") for l in open(p, encoding="utf-8") if "\t" in l]
        except OSError:
            rows = []
        rows = [r for r in rows if r[0] != stem] + [[stem, cat]]
        with open(p, "w", encoding="utf-8") as f:
            f.write("".join(f"{a}\t{b}\n" for a, b in rows))


def same_style(a, b):
    """两条样式外观一样（不比名字）"""
    return z.style_line({**a, "name": "x"}) == z.style_line({**b, "name": "x"})


FX_LAYER = "fx层"


def fx_edits(doc, sel, pick, pos, measure):
    """所选行套预设 → Edits。pick(行) → 用哪个预设（中日配对时日文行换成配对的预设）"""
    e = z.Edits()
    res = doc.res()
    used = {}
    for i in sorted(sel):
        l = doc.by_i(i)
        if l["class"] != "dialogue" or l["effect"] == FX_LAYER:
            continue
        p = pick(l)
        st = preset_style(p)
        st["name"] = base_name(p["name"])   # 「ED CN #05」写进字幕还是 ED CN（中日配对、同步时间靠名字）
        used[st["name"]] = st
        m, j = 0, i + 1   # 上次应用留下的叠层，先删
        while j <= len(doc.rows) and doc.by_i(j)["class"] == "dialogue" and doc.by_i(j)["effect"] == FX_LAYER \
                and doc.by_i(j)["start_time"] == l["start_time"] and doc.by_i(j)["end_time"] == l["end_time"]:
            e.delete(j)
            m, j = m + 1, j + 1
        text = l["text"]
        hm = re.match(r"^\{([^}]*)\}", text)
        head, body = (hm.group(1), text[hm.end():]) if hm else ("", text)
        old = re.search(r"\\pos\(([\d.\-]+),([\d.\-]+)\)", head)
        lp = pos or ((float(old.group(1)), float(old.group(2))) if old else None)
        keep = "".join(re.findall(r"\\(?:an\d|org\([^)]*\))", head))   # 旧标签只留对齐 / 旋转中心
        mv = re.search(r"\\move\([^)]*\)", head)
        if mv and not lp:
            keep += mv.group(0)
        geom = line_geom(measure, st, (("{%s}" % keep) if keep else "") + body, res, lp, l)
        layers, move = build_layers(p, geom)
        own = any(re.search(r"\\(pos|move)\(", t) for t, _ in layers)
        if move:
            keep = re.sub(r"\\(pos|move)\([^)]*\)", "", keep) + move
        elif lp and not own:
            keep += "\\pos(%g,%g)" % (round(lp[0], 1), round(lp[1], 1))
        base = max(0, int(l["layer"]) - m)
        n = len(layers)
        rows = []
        for k, (tags, pc) in enumerate(layers):
            b = per_char(body, int(p["fx"]["anim_ms"]), pc) if pc else body
            tg = tags + keep
            rows.append({**{f: l[f] for f in z.DIA_F}, "style": st["name"], "layer": base + n - 1 - k,
                         "text": ("{%s}" % tg if tg else "") + b, "effect": l["effect"] if k == 0 else FX_LAYER})
        e.set(i, **{f: rows[0][f] for f in ("style", "layer", "text")})
        for r in rows[1:]:
            e.insert_after(i, r)
    for st in used.values():
        e.upsert_style(st)
    return e


# ================================================================ 卡拉OK
TPL_RE = re.compile(r"\s*(template|code|mixin)\b", re.I)


def has_k(text):
    return bool(re.search(r"\\[kK][fo]?\d", text))


def kara_edits(kara, doc, styles, events, src_idx, templates, k_mode="keep", starts=None, tag="k",
               insert_templates=True, restyle=None):
    """对 src_idx 这些歌词行跑模板 → (Edits, 日志)。
    events：改动后的行（带 'i'）；templates：{样式名: [模板行]}；insert_templates：模板写进文件
    （同样式的旧模板先删）；restyle：{样式名: 新样式}（套用模板自带的字体颜色）"""
    e = z.Edits()
    by_i = {r["i"]: r for r in events if r.get("i")}
    srcs = [by_i[i] for i in sorted(src_idx) if i in by_i]
    st_all = dict(styles)
    if restyle:
        st_all.update(restyle)
        for s in restyle.values():
            e.upsert_style(s)
    lines, log = [], ""
    for n, r in enumerate(srcs):
        text, dur = r["text"], r["end_time"] - r["start_time"]
        if starts and n < len(starts) and starts[n] is not None:
            text = z.auto_k(text, dur, starts=starts[n][1], tag=tag, syls=starts[n][0])
        elif k_mode == "even" or not has_k(text):
            text = z.auto_k(text, dur, tag=tag)
        lines.append({"class": "dialogue", **{f: r[f] for f in z.DIA_F}, "text": text, "comment": False,
                      "effect": "karaoke", "zi": r["i"]})
    by_style = {}
    for l in lines:
        by_style.setdefault(l["style"], []).append(l)
    for sname, ls in by_style.items():
        tpl = templates.get(sname, [])
        if not tpl:
            log += f"样式「{sname}」没有模板，只打了 \\k\n"
            for l in ls:
                e.set(l["zi"], text=l["text"])
            continue
        res, lg = kara.run(doc.info(), {sname: st_all[sname]}, tpl, ls, doc.res())
        log += lg
        for zi, src, fx in res:
            e.set(zi, text=src["text"] if src else by_i[zi]["text"], comment=True, effect="karaoke")
            for f in fx:
                e.insert_after(zi, {**f, "comment": False})
        if insert_templates:
            for r in doc.dialogue():   # 同样式的旧模板删掉，换成这次的
                if r["style"] == sname and r["comment"] and TPL_RE.match(r["effect"]):
                    e.delete(r["i"])
            first = min(l["zi"] for l in ls)
            for t in tpl:
                e.insert_after(first - 1, {**{f: t.get(f, "") for f in z.DIA_F}, "style": sname, "comment": True,
                                           "layer": t.get("layer", 0) or 0, "start_time": 0, "end_time": 0})
    # 这些行上次生成的 fx 行：紧跟在源行后面的（本插件的写法）+ 文件末尾那堆里时间对得上的（Aegisub 的写法）
    rows, owned = doc.rows, set()
    for r in doc.dialogue():
        if r["effect"].strip().lower() == "karaoke" or r["i"] in src_idx:
            j = r["i"] + 1
            while j <= len(rows) and rows[j - 1]["class"] == "dialogue" and rows[j - 1]["effect"] == "fx":
                if r["i"] in src_idx:
                    e.delete(j)
                owned.add(j)
                j += 1
    for l in lines:
        for r in doc.dialogue():
            if r["effect"] == "fx" and r["i"] not in owned and r["style"] == l["style"] \
                    and l["start_time"] - 10000 <= r["start_time"] <= l["end_time"] + 5000:
                e.delete(r["i"])
    return e, log


def template_text(rows):
    return "\n".join("[%s] %s" % (r["effect"].strip(), r["text"]) for r in rows)


def parse_template_text(s):
    out = []
    for line in s.splitlines():
        m = re.match(r"^\s*\[([^\]]+)\]\s?(.*)$", line)
        if m:
            out.append({"class": "dialogue", "comment": True, "layer": 0, "start_time": 0, "end_time": 0,
                        "style": "", "actor": "", "margin_l": 0, "margin_r": 0, "margin_t": 0, "margin_b": 0,
                        "effect": m.group(1).strip(), "text": m.group(2)})
    return out


def http_get(url, timeout=60):
    req = urllib.request.Request(url, headers={"user-agent": "zhouxiao-aegisub"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def font_names(root):
    """装了的字体：Tk 的名字（中文字体是中文名）+ 注册表里的英文名，两种都能搜"""
    names = {f for f in tk.font.families(root) if not f.startswith("@")}
    try:
        import winreg
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):   # 后者是只给当前用户装的字体
            try:
                k = winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts")
            except OSError:
                continue
            for i in range(winreg.QueryInfoKey(k)[1]):
                n = re.sub(r"\s*\((TrueType|OpenType|All res)\)$", "", winreg.EnumValue(k, i)[0])
                for part in n.split(" & "):
                    part = re.sub(r" (Bold Italic|Bold|Italic|Regular|Oblique)$", "", part).strip()
                    if part:
                        names.add(part)
    except ImportError:
        pass
    return sorted(names, key=str.lower)


def short_path(p, n=46):
    """长路径只留尾巴，界面上一行放得下"""
    p = p.replace("/", "\\").rstrip("\\")
    return p if len(p) <= n else "…" + p[1 - n:]


def load_settings():
    try:
        return json.load(open(SETTINGS, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(s):
    with open(SETTINGS, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)


# ================================================================ 预览播放器
class Player(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.video = None
        self.bg = None
        self.t0, self.t1, self.t = 0.0, 10.0, 0.0
        self.playing, self.stop_flag = False, False
        self.q = queue.Queue(maxsize=12)
        self.assdoc = b""
        self.wav = None
        self._seek_id = 0
        self.tmp = tempfile.mkdtemp(prefix="zxprev")
        vid = app.job.get("video") or ""
        if vid and os.path.exists(vid):
            try:
                self.video = z.Video(vid, PW)
            except Exception as ex:
                print("视频打不开：", ex)
        self.ph = self.video.h if self.video else round(PW * app.res[1] / app.res[0])
        self.vsf = z.VSFilter(app.job["vsfilter"], PW, self.ph)
        self.canvas = tk.Canvas(self, width=PW, height=self.ph, highlightthickness=0, cursor="crosshair", bg="#222")
        self.canvas.pack()
        self.img_id = self.canvas.create_image(0, 0, anchor="nw")
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=4)
        self.play_btn = ttk.Button(bar, text="▶ 预览", width=8, command=self.toggle)
        self.play_btn.pack(side="left")
        self.scale = ttk.Scale(bar, from_=0, to=1, command=self.on_scale)
        self.scale.pack(side="left", fill="x", expand=True, padx=6)
        self.time_lbl = ttk.Label(bar, width=24)
        self.time_lbl.pack(side="left")
        self.loop = tk.IntVar(self, 1)
        ttk.Checkbutton(bar, text="循环", variable=self.loop).pack(side="left")
        ttk.Label(self, foreground="#666", text="左键：定位　右键：清除　空格：播放 / 暂停"
                  + ("" if self.video else "；没开视频，灰底预览")).pack(anchor="w")

    def set_clip(self, t0, t1):
        self.stop()
        dur = self.video.duration if self.video and self.video.duration else t1 + 5
        self.t0, self.t1 = max(0.0, t0), min(max(t1, t0 + 1), dur)
        self.scale.configure(from_=self.t0, to=self.t1)
        self.wav = None
        if self.video and self.video.has_audio:
            def load(t0=self.t0, t1=self.t1):
                p = os.path.join(self.tmp, "clip.wav")
                try:
                    if self.video.wav(t0, t1, p):
                        self.wav = p
                except Exception as ex:
                    print("取音频失败：", ex)
            threading.Thread(target=load, daemon=True).start()
        self.invalidate()
        self.seek(self.t0 + min(5.0, (self.t1 - self.t0) / 3))

    def invalidate(self):
        """改动变了：重拼预览用的 ASS，重画当前帧"""
        a, b = self.t0 * 1000 - 1000, self.t1 * 1000 + 1000
        styles, events = self.app.preview_view()
        self.assdoc = z.ass_doc(self.app.doc, styles, events, a, b)
        if not self.playing:
            self.show(self.bg, self.t)

    def blank(self):
        return bytes([40, 40, 40, 0]) * (PW * self.ph)

    def show(self, bg, t):
        data = self.vsf.render(self.assdoc, bg or self.blank(), t)
        self.photo = tk.PhotoImage(data=z.to_ppm(data, PW, self.ph), format="PPM")
        self.canvas.itemconfig(self.img_id, image=self.photo)
        self.time_lbl.config(text="%s  (%.1f / %.1fs)" % (z.ms2ass(t * 1000), t - self.t0, self.t1 - self.t0))

    def frame_png(self, t):
        """AI 看图用：t 秒的帧 + 当前改动"""
        bg = self.video.frame_at(t)[1] if self.video else self.blank()
        return z.to_png(self.vsf.render(self.assdoc, bg, t), PW, self.ph)

    def seek(self, t):
        self.t = t
        self.scale.set(t)
        if not self.video:
            self.show(None, t)
            return
        self._seek_id += 1
        sid = self._seek_id

        def work():
            try:
                ft, data = self.video.frame_at(t)
            except Exception as ex:
                print("取帧失败：", ex)
                data = None
            self.app.ui_q.put(("seek", sid, t, data))
        threading.Thread(target=work, daemon=True).start()

    def on_scale(self, x):
        x = float(x)
        if not self.playing and abs(x - self.t) > 0.05:
            if getattr(self, "_sc", None):
                self.after_cancel(self._sc)
            self._sc = self.after(150, lambda: self.seek(x))

    def now(self):
        return self.pt0 + time.perf_counter() - self.wall0 if self.playing else self.t

    def toggle(self):
        self.stop() if self.playing else self.play()

    def play(self):
        if self.t >= self.t1 - 0.1:
            self.t = self.t0
        self.playing, self.stop_flag = True, False
        self.play_btn.config(text="⏸ 暂停")
        self.q = q = queue.Queue(maxsize=12)
        start = self.t
        if self.video:
            def dec():
                try:
                    for ft, data in self.video.frames(start, lambda: self.stop_flag):
                        if ft > self.t1:
                            break
                        while not self.stop_flag:
                            try:
                                q.put((ft, data), timeout=0.2)
                                break
                            except queue.Full:
                                pass
                        if self.stop_flag:
                            return
                except Exception as ex:
                    print("解码出错：", ex)
            threading.Thread(target=dec, daemon=True).start()
        if self.wav:
            p = os.path.join(self.tmp, "play%d.wav" % (int(time.time() * 1000) % 1000000))
            z.wav_slice(self.wav, start - self.t0, p)
            z.Sound.play(p)
        self.wall0, self.pt0 = time.perf_counter(), start
        self.after(5, self.tick)

    def tick(self):
        if not self.playing:
            return
        now = self.pt0 + time.perf_counter() - self.wall0
        if now >= self.t1:
            self.stop()
            if self.loop.get():
                self.t = self.t0
                self.play()
            return
        if self.video:
            got = None
            while self.q.queue and self.q.queue[0][0] <= now + 0.02:
                got = self.q.get_nowait()
            if got:
                self.bg, self.t = got[1], got[0]
                self.show(self.bg, now)
        else:
            self.t = now
            self.show(None, now)
        self.scale.set(now)
        self.after(8, self.tick)

    def stop(self):
        if self.playing:
            z.Sound.stop()
        self.playing, self.stop_flag = False, True
        self.play_btn.config(text="▶ 预览")


# ================================================================ 特效样式页
class FxTab(ttk.Frame):
    title = "特效样式"

    def __init__(self, nb, app):
        super().__init__(nb, padding=4)
        self.app = app
        self.lib = Library(app.job.get("catalog_dir") or os.path.join(os.path.dirname(HOME), "catalog"))
        self.cat = app.job.get("catalog") or ""
        self.num = int(app.job.get("number") or 0)
        self.cur = None
        self.pos = app.first_pos()
        self.edits = z.Edits()
        self.loading = False
        self.v = {}
        self.local = []   # 当前字幕里有、方案里没有的样式（存进方案之前）
        left = ttk.Frame(self)
        left.grid(row=0, column=0, sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)
        r1 = ttk.Frame(left)
        r1.pack(fill="x")
        ttk.Label(r1, text="样式方案").pack(side="left")
        self.cat_v = tk.StringVar(self, self.cat)
        self.cat_cb = ttk.Combobox(r1, textvariable=self.cat_v, width=14, state="readonly")
        self.cat_cb.pack(side="left", padx=2)
        self.cat_cb.bind("<<ComboboxSelected>>", lambda e: self.set_cat(self.cat_v.get()))
        ttk.Button(r1, text="新建", command=self.new_cat).pack(side="left")
        r2 = ttk.Frame(left)
        r2.pack(fill="x", pady=2)
        ttk.Label(r2, text="编号").pack(side="left")
        self.num_v = tk.StringVar(self, str(self.num))
        sp = ttk.Spinbox(r2, from_=0, to=999, width=4, textvariable=self.num_v, command=self.num_changed)
        sp.pack(side="left")
        sp.bind("<FocusOut>", lambda e: self.num_changed())
        ttk.Label(left, text="当前方案").pack(anchor="w")
        self.mine = tk.Listbox(left, width=24, height=11, exportselection=False)
        self.mine.pack(fill="both", expand=True)
        self.mine.bind("<<ListboxSelect>>", lambda e: self.pick_mine())
        bf = ttk.Frame(left)
        bf.pack(fill="x")
        for k, (label, fn) in enumerate((("新建", self.new), ("改名", self.rename), ("删除", self.delete),
                                         ("存为当前编号专用", self.save_num))):
            ttk.Button(bf, text=label, command=fn).grid(row=k // 2, column=k % 2, sticky="ew", padx=1, pady=1)
        bf.columnconfigure(0, weight=1)
        bf.columnconfigure(1, weight=1)
        ttk.Label(left, text="其他方案").pack(anchor="w", pady=(6, 0))
        self.flt = tk.StringVar(self)
        self.flt.trace_add("write", lambda *a: self.fill_tree())
        ttk.Entry(left, textvariable=self.flt).pack(fill="x")
        self.tree = ttk.Treeview(left, show="tree", height=8, selectmode="browse")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.pick_tree())
        tb = ttk.Frame(left)
        tb.pack(fill="x")
        ttk.Button(tb, text="复制到当前方案", command=self.take).pack(side="left", fill="x", expand=True)
        ttk.Button(tb, text="补回起步样式", command=self.restore).pack(side="left", fill="x", expand=True)
        self.build_style(self)
        self.build_fx(app.dock["fx"])
        opt = ttk.Frame(self)
        opt.grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self.banner = ttk.Frame(opt)
        self.banner.pack(anchor="w", fill="x")
        self.pair = tk.IntVar(self, 1)
        ttk.Checkbutton(opt, text="中日同步",
                        variable=self.pair, command=self.changed).pack(anchor="w")
        n = sum(app.doc.by_i(i)["class"] == "dialogue" for i in app.sel)
        self.use = tk.IntVar(self, 1 if app.job.get("tab", "fx") == "fx" and n else 0)
        ttk.Checkbutton(opt, text=f"把选中的样式和特效应用到所选的 {n} 行", variable=self.use,
                        command=self.changed).pack(anchor="w")
        self.pos_lbl = ttk.Label(opt, foreground="#666")
        self.pos_lbl.pack(anchor="w")
        self.hint = ttk.Label(opt, foreground="#a60")
        self.hint.pack(anchor="w")
        self.set_cat(self.cat, first=True)
        self.set_pos(self.pos)

    # ---- 样式方案 / 编号
    def entries(self):
        return self.lib.cats.get(self.cat, []) + self.local

    def set_cat(self, cat, first=False):
        if self.cur is not None:
            self.form_to(self.cur)
        self.cat = cat
        cats = sorted(s for s in self.lib.cats if s != CATALOG_SEED)
        self.cat_cb["values"] = cats
        self.cat_v.set(cat)
        docst = self.app.doc.styles()
        have = {base_name(p["name"]) for p in self.lib.cats.get(cat, [])}
        self.local = [dict(migrate({"name": n, "style": style_to_preset(st)}), cat=cat, local=True)
                      for n, st in docst.items() if n not in have]
        self.hint.config(text="" if cat else "未选样式方案")
        self.fill_mine()
        self.fill_tree()
        self.check_diff()
        l = self.app.active_line()
        want = self.lib.pick(cat, l["style"], self.num) if l else None
        ents = self.entries()
        idx = next((k for k, p in enumerate(ents) if p is want), None)
        if idx is None and l:
            idx = next((k for k, p in enumerate(ents) if p["name"] == l["style"]), None)
        if idx is None and not ents:
            self.cur = None
            self.pick_entry(self.lib.cats[CATALOG_SEED][0])
            return
        self.cur = None
        self.select_mine(idx or 0)

    def new_cat(self):
        n = simpledialog.askstring("新建样式方案", "方案名称：", parent=self)
        n = (n or "").strip()
        if not n or re.search(r'[\\/:*?"<>|]', n):
            return
        if n not in self.lib.cats:
            self.lib.cats[n] = []
            self.lib.write(n)
        self.set_cat(n)

    def num_changed(self):
        try:
            num = int(self.num_v.get())
        except ValueError:
            return
        if num != self.num:
            self.num = num
            self.set_cat(self.cat)

    def check_diff(self):
        """当前字幕的样式和方案里该用的那条不一样 → 提示条：更新到方案 / 存为编号专用 / 忽略"""
        for w in self.banner.winfo_children():
            w.destroy()
        if not self.cat:
            return
        diff = []
        for n, st in self.app.doc.styles().items():
            p = self.lib.pick(self.cat, n, self.num)
            if p and not same_style(st, preset_style(p)):
                diff.append(n)
        if not diff:
            return
        ttk.Label(self.banner, foreground="#a60", wraplength=620, justify="left",
                  text=f"与方案「{self.cat}」不一致：{'、'.join(diff[:8])}{'…' if len(diff) > 8 else ''}").pack(anchor="w")
        b = ttk.Frame(self.banner)
        b.pack(anchor="w")
        ttk.Button(b, text="更新到方案", command=lambda: self.resolve(diff, False)).pack(side="left")
        if self.num:
            ttk.Button(b, text=f"存为编号 {self.num:02d} 专用", command=lambda: self.resolve(diff, True)).pack(side="left", padx=4)
        ttk.Button(b, text="忽略", command=lambda: [w.destroy() for w in self.banner.winfo_children()]).pack(side="left")

    def resolve(self, names, per_num):
        ents = self.lib.cats[self.cat]
        docst = self.app.doc.styles()
        for n in names:
            old = self.lib.pick(self.cat, n, self.num)
            name = num_name(n, self.num) if per_num else n
            new = migrate({"cat": self.cat, "name": name, "style": style_to_preset(docst[n]),
                           "fx": dict(old["fx"]) if old else {}, "extra": old["extra"] if old else ""})
            ents[:] = [p for p in ents if p["name"] != name] + [new]
        self.lib.write(self.cat)
        self.set_cat(self.cat)

    # ---- 列表
    def label(self, p):
        tag = "（当前字幕）" if p.get("local") else ""
        mark = ""
        if not p.get("local") and base_name(p["name"]) in self.app.doc.styles() \
                and self.lib.pick(self.cat, p["name"], self.num) is p:
            mark = "  ✓当前字幕在用"
        return tag + p["name"] + mark

    def fill_mine(self):
        self.mine.delete(0, "end")
        for p in self.entries():
            self.mine.insert("end", self.label(p))

    def fill_tree(self):
        self.tree.delete(*self.tree.get_children())
        q = self.flt.get().lower().replace(" ", "")
        for cat in sorted(self.lib.cats, key=lambda s: (s == CATALOG_SEED, s)):
            if cat == self.cat:
                continue
            hits = [p for p in self.lib.cats[cat] if not q or q in (cat + p["name"]).lower().replace(" ", "")]
            if not hits:
                continue
            node = self.tree.insert("", "end", text=f"{cat}（{len(hits)}）", open=bool(q))
            for p in hits:
                self.tree.insert(node, "end", text=p["name"], values=(cat, p["name"]))

    def select_mine(self, i):
        self.mine.selection_clear(0, "end")
        if 0 <= i < self.mine.size():
            self.mine.selection_set(i)
            # 前几行就从头显示（免得通用版被滚出去看不见）；窗口刚打开时列表还没排版，see() 会按一行高去滚
            if i < int(self.mine.cget("height")):
                self.mine.yview_moveto(0)
            else:
                self.mine.see(i)
            self.pick_mine()

    def pick_mine(self):
        s = self.mine.curselection()
        if s:
            self.pick_entry(self.entries()[s[0]])

    def pick_tree(self):
        s = self.tree.selection()
        vals = self.tree.item(s[0], "values") if s else None
        if vals:
            p = next((p for p in self.lib.cats[vals[0]] if p["name"] == vals[1]), None)
            if p:
                self.mine.selection_clear(0, "end")
                self.pick_entry(p)

    def pick_entry(self, p):
        if self.cur is not None and self.cur is not p:
            self.form_to(self.cur)
        self.cur = p
        self.to_form(p)

    def mine_or_warn(self):
        if self.cur is None or self.cur.get("cat") != self.cat or not self.cat:
            messagebox.showinfo("先复制到当前方案", "这是别的方案里的样式：先点「复制到当前方案」复制一份过来再改名 / 删除 / 存。"
                                if self.cat else "先在左上角选这份字幕用哪个样式方案", parent=self)
            return False
        return True

    # ---- 界面（样式 / 特效两个小页，和以前一样）
    def var(self, key, kind=tk.StringVar):
        v = self.v[key] = kind(self)
        v.trace_add("write", lambda *a: self.changed())
        return v

    def rowmaker(self, f):
        r = [0]

        def row(label, *ws):
            ttk.Label(f, text=label).grid(row=r[0], column=0, sticky="w", pady=4, padx=(0, 8))
            box = ttk.Frame(f)
            box.grid(row=r[0], column=1, sticky="w")
            for w in ws:
                w.pack(in_=box, side="left", padx=2)
                w.lift()   # 控件比 box 先建，不抬上来会被 box 盖住
            r[0] += 1
        return row, r

    def build_style(self, parent):
        f = ttk.LabelFrame(parent, text="样式", padding=8)
        f.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        row, _ = self.rowmaker(f)

        def spin(key, lo, hi, inc=1, width=6):
            return ttk.Spinbox(f, from_=lo, to=hi, increment=inc, width=width, textvariable=self.var(key))

        self.fonts = self.app.fonts()
        self.font_cb = ttk.Combobox(f, values=self.fonts, width=24, textvariable=self.var("fontname"))
        self.font_cb.bind("<KeyRelease>", self.filter_fonts)
        fnote = ttk.Label(f, foreground="#888")
        row("字体", self.font_cb, fnote)
        self.folder_lbl = ttk.Label(f, foreground="#666")
        row("字体文件夹", ttk.Button(f, text="选择…", command=self.app.pick_fonts), self.folder_lbl)
        self.font_note_lbl = fnote
        self.var("fontname").trace_add("write", lambda *a: self.font_note())
        row("字号", spin("fontsize", 1, 999), ttk.Checkbutton(f, text="粗体", variable=self.var("bold", tk.IntVar)),
            ttk.Checkbutton(f, text="斜体", variable=self.var("italic", tk.IntVar)))
        self.swatch = {}
        for k, name in ((1, "主要颜色"), (2, "次要颜色"), (3, "边框颜色"), (4, "阴影颜色")):
            b = tk.Button(f, width=4, relief="groove", command=lambda k=k: self.pick_color(k))
            self.swatch[k] = b
            self.var(f"rgb{k}")
            row(name, b, ttk.Label(f, text="透明度"), spin(f"alpha{k}", 0, 255, 16, 4))
        row("边框 / 阴影", spin("outline", 0, 99, 0.5), spin("shadow", 0, 99, 0.5),
            ttk.Checkbutton(f, text="不透明底框", variable=self.var("box", tk.IntVar)))
        row("横向 / 纵向缩放 %", spin("scale_x", 1, 999), spin("scale_y", 1, 999))
        row("字距 / 旋转", spin("spacing", -99, 99, 0.5), spin("angle", -360, 360, 5))
        grid = ttk.Frame(f)
        a = self.var("align", tk.IntVar)
        for n in range(1, 10):
            ttk.Radiobutton(grid, text=str(n), value=n, variable=a).grid(row=2 - (n - 1) // 3, column=(n - 1) % 3)
        row("对齐", grid)
        row("边距 左 / 右 / 垂直", spin("margin_l", 0, 9999), spin("margin_r", 0, 9999), spin("margin_v", 0, 9999))

    def build_fx(self, parent):
        f = ttk.LabelFrame(parent, text="特效", padding=8)
        f.pack(fill="both", expand=True)
        row, r = self.rowmaker(f)

        def spin(key, lo, hi, inc=1, width=6):
            return ttk.Spinbox(f, from_=lo, to=hi, increment=inc, width=width, textvariable=self.var("fx_" + key))

        bv = self.var("fx_blur", tk.DoubleVar)
        blbl = ttk.Label(f, width=5)
        bv.trace_add("write", lambda *a: blbl.config(text="%.1f" % bv.get()))
        row("淡入 / 淡出 (ms)", spin("fade_in", 0, 5000, 50), spin("fade_out", 0, 5000, 50))
        row("边缘模糊", ttk.Scale(f, from_=0, to=10, length=180, variable=bv), blbl)
        row("入场动画", ttk.Combobox(f, values=ANIMS, width=10, state="readonly", textvariable=self.var("fx_anim")),
            ttk.Label(f, text="时长 / 逐字间隔 (ms)"), spin("anim_ms", 10, 5000, 10))
        self.cbtn = {}

        def cbutton(key):
            b = tk.Button(f, width=4, relief="groove", command=lambda: self.pick_fx_color(key))
            self.cbtn[key] = b
            self.var("fx_" + key)
            return b
        row("外发光", ttk.Checkbutton(f, text="开", variable=self.var("fx_glow", tk.IntVar)),
            ttk.Label(f, text="大小"), spin("glow_size", 0, 99, 1, 4), ttk.Label(f, text="模糊"),
            spin("glow_blur", 0, 50, 1, 4), ttk.Label(f, text="颜色"), cbutton("glow_color"))
        row("双层描边", ttk.Checkbutton(f, text="开", variable=self.var("fx_double", tk.IntVar)),
            ttk.Label(f, text="外圈宽"), spin("double_size", 0, 99, 1, 4), ttk.Label(f, text="颜色"),
            cbutton("double_color"))
        ttk.Label(f, text="额外标签").grid(
            row=r[0], column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.extra = tk.Text(f, width=50, height=3, undo=True, font=("Consolas", 10))
        self.extra.grid(row=r[0] + 1, column=0, columnspan=2, sticky="we")
        self.extra.bind("<<Modified>>", self.extra_mod)
        ttk.Label(f, text="输出标签", foreground="#666").grid(
            row=r[0] + 2, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.final = tk.Text(f, width=50, height=4, font=("Consolas", 9), foreground="#555", background="#f4f4f4")
        self.final.grid(row=r[0] + 3, column=0, columnspan=2, sticky="we")

    def filter_fonts(self, e):
        if e.keysym in ("Up", "Down", "Return", "Escape", "Tab"):
            return
        q = self.font_cb.get().lower().replace(" ", "")
        hit = [x for x in self.fonts if q in x.lower().replace(" ", "")] if q else self.fonts
        self.font_cb["values"] = hit or self.fonts

    def font_note(self):
        """字体名旁边那行小字：在字体文件夹里 / 找不到会顶替成什么"""
        txt, color = self.app.font_note(self.v["fontname"].get())
        self.font_note_lbl.config(text=txt, foreground=color)

    def fonts_cb_update(self):
        """字体文件夹换了：下拉、小字都跟着重来"""
        self.fonts = self.app.fonts()
        self.font_cb["values"] = self.fonts
        d = self.app.font_folder()
        if d:
            self.folder_lbl.config(text="%s（%d 个文件，能用 %d 个）" % (short_path(d), len(z.font_files(d)),
                                                                    len(self.app.folder_fonts())))
        else:
            self.folder_lbl.config(text="没设：只列系统装了的字体")
        self.font_note()

    def fnum(self, k, default):
        try:
            return num(self.v[k].get())
        except (ValueError, tk.TclError):
            return default

    def form_to(self, p):
        s = p["style"]
        for k in KEYS:
            if k.startswith("color"):
                n = k[-1]
                rgb = self.v[f"rgb{n}"].get().lstrip("#") or "FFFFFF"
                s[k] = "%02X%s" % (int(self.fnum(f"alpha{n}", 0)) & 255, bgr(rgb))
            elif k == "fontname":
                s[k] = self.v[k].get()
            elif k == "borderstyle":
                s[k] = 3 if self.v["box"].get() else 1
            elif k in self.v:
                s[k] = self.fnum(k, s.get(k, 0))
        fx = p["fx"]
        for k in FX0:
            fx[k] = self.v["fx_" + k].get() if k in ("anim", "glow_color", "double_color") else \
                self.fnum("fx_" + k, FX0[k])
        fx["glow_color"] = fx["glow_color"].lstrip("#").upper()
        fx["double_color"] = fx["double_color"].lstrip("#").upper()
        p["extra"] = self.extra.get("1.0", "end").strip()

    def to_form(self, p):
        self.loading = True
        s = p["style"]
        for k in KEYS:
            if k.startswith("color"):
                n, c = k[-1], z.color_hex(s[k])
                self.v[f"alpha{n}"].set(int(c[0:2], 16))
                self.v[f"rgb{n}"].set("#" + c[6:8] + c[4:6] + c[2:4])
                self.swatch[int(n)].config(bg="#" + c[6:8] + c[4:6] + c[2:4])
            elif k == "borderstyle":
                self.v["box"].set(1 if int(s[k]) == 3 else 0)
            elif k in self.v:
                self.v[k].set(s[k])
        for k, v in p["fx"].items():
            if "fx_" + k in self.v:
                self.v["fx_" + k].set(v)
        for k in ("glow_color", "double_color"):
            self.cbtn[k].config(bg="#" + p["fx"][k])
        self.extra.delete("1.0", "end")
        self.extra.insert("1.0", p.get("extra", ""))
        self.extra.edit_modified(False)
        self.loading = False
        self.changed()

    # ---- 增删改
    def ask_name(self, title, init):
        n = simpledialog.askstring(title, "样式名（写进字幕时就是这个名字；以 CN / JP 结尾能中日配对；"
                                          "末尾「 #05」表示编号 05 专用，写进字幕时去掉）：", initialvalue=init, parent=self)
        n = (n or "").strip().replace(",", "，")
        if n and any(p["name"] == n for p in self.lib.cats.get(self.cat, [])):
            if not messagebox.askyesno("重名", f"当前方案已经有「{n}」了，覆盖它？", parent=self):
                return None
            self.lib.cats[self.cat][:] = [p for p in self.lib.cats[self.cat] if p["name"] != n]
        return n or None

    def add_mine(self, p):
        p.pop("local", None)
        self.local = [q for q in self.local if q["name"] != p["name"]]
        self.lib.cats.setdefault(self.cat, []).append(p)
        self.lib.write(self.cat)
        self.fill_mine()
        self.cur = None
        self.select_mine(next(k for k, q in enumerate(self.entries()) if q is p))

    def copy_cur(self, name):
        self.form_to(self.cur)
        p = json.loads(json.dumps(self.cur))
        p.update(cat=self.cat, name=name)
        p.pop("local", None)
        return p

    def new(self):
        if not self.cat:
            return self.mine_or_warn()
        l = self.app.active_line()
        st = self.app.doc.styles().get(l["style"]) if l else None
        n = self.ask_name("新建样式", st["name"] if st else "新样式")
        if n:
            self.add_mine(migrate({"cat": self.cat, "name": n, "style": style_to_preset(st) if st else dict(BASE)}))

    def take(self):
        if self.cur is None or not self.cat:
            return self.mine_or_warn()
        n = self.ask_name("复制到当前方案", self.cur["name"])
        if n:
            self.add_mine(self.copy_cur(n))

    def save_num(self):
        if not self.num:
            messagebox.showinfo("编号", "未填编号", parent=self)
            return
        if self.cur is None or not self.cat:
            return self.mine_or_warn()
        n = num_name(self.cur["name"], self.num)
        self.lib.cats[self.cat][:] = [p for p in self.lib.cats[self.cat] if p["name"] != n]
        self.add_mine(self.copy_cur(n))

    def rename(self):
        if not self.mine_or_warn():
            return
        n = self.ask_name("改名", self.cur["name"])
        if n:
            self.cur["name"] = n
            if self.cur.get("local"):
                self.add_mine(self.cur)
            else:
                self.lib.write(self.cat)
                self.fill_mine()

    def delete(self):
        if not self.mine_or_warn() or self.cur.get("local"):
            return
        if messagebox.askyesno("删除", f"从方案「{self.cat}」删掉「{self.cur['name']}」？",
                               parent=self):
            self.lib.cats[self.cat].remove(self.cur)
            self.lib.write(self.cat)
            self.cur = None
            self.set_cat(self.cat)

    def restore(self):
        have = {p["name"] for p in self.lib.cats[CATALOG_SEED]}
        add = [dict(p, cat=CATALOG_SEED) for p in seeds() if p["name"] not in have]
        self.lib.cats[CATALOG_SEED] += add
        self.lib.write(CATALOG_SEED)
        self.fill_tree()
        messagebox.showinfo("补回起步样式", f"「{CATALOG_SEED}」补回 {len(add)} 个" if add else "起步样式都在", parent=self)

    def pick_color(self, k):
        c = colorchooser.askcolor(self.v[f"rgb{k}"].get(), parent=self)[1]
        if c:
            self.v[f"rgb{k}"].set(c.upper())
            self.swatch[k].config(bg=c)

    def pick_fx_color(self, key):
        c = colorchooser.askcolor("#" + self.v["fx_" + key].get().lstrip("#"), parent=self)[1]
        if c:
            self.v["fx_" + key].set(c.upper().lstrip("#"))
            self.cbtn[key].config(bg=c)

    def extra_mod(self, e):
        if self.extra.edit_modified():
            self.extra.edit_modified(False)
            self.changed()

    def set_pos(self, pos):
        self.pos = pos
        self.pos_lbl.config(text=f"\\pos{pos}" if pos else "")
        self.changed()

    # ---- 改动
    def changed(self):
        if self.loading or self.cur is None:
            return
        self.app.schedule(self.recompute)

    def current(self):
        p = json.loads(json.dumps(self.cur))
        self.form_to(p)
        return p

    def recompute(self):
        if self.cur is None:
            return
        p = self.current()
        pool = self.lib.cats.get(p.get("cat"), []) + (self.local if p.get("cat") == self.cat else [])
        mate = next((q for q in pool if q["name"] == partner(p["name"])), None) if self.pair.get() else None
        if mate is not None:
            mate = json.loads(json.dumps(mate))
            mate["fx"], mate["extra"] = dict(p["fx"]), p["extra"]

        def pick(l):
            if mate is not None and l["style"].endswith(base_name(mate["name"])[-3:]):
                return mate
            return p
        sel = [i for i in self.app.sel if self.app.doc.by_i(i)["class"] == "dialogue"]
        self.edits = fx_edits(self.app.doc, sel, pick, self.pos, self.app.measure) if (sel and self.use.get()) \
            else z.Edits()
        st = preset_style(p)
        geom = line_geom(self.app.measure, st, "示例", self.app.res, self.pos,
                         {"margin_l": 0, "margin_r": 0, "margin_t": 0})
        layers, move = build_layers(p, geom)
        self.final.delete("1.0", "end")
        self.final.insert("1.0", "\n".join("{%s%s}" % (t, move or "") for t, _ in layers))
        self.app.edits_changed()

    def save(self):
        """关窗 / 应用时：当前方案存盘（特效参数中日同步）。别的方案里的样式改了不存（要用先复制过来）"""
        if self.cur is not None:
            self.form_to(self.cur)
            p = self.cur
            if self.pair.get() and p.get("cat") == self.cat:
                for q in self.lib.cats.get(self.cat, []):
                    if q["name"] == partner(p["name"]):
                        q["fx"], q["extra"] = dict(p["fx"]), p["extra"]
        if self.cat and self.cat in self.lib.cats:
            self.lib.write(self.cat)


# ================================================================ 逐字关键帧时间轴
class KTimeline(ttk.Frame):
    """一句歌词的波形 + 每个音节一个关键帧（◆）。拖 ◆ 改时间；点音节听这一段；播放时按 K 依次打下一个音节；
    右键 ◆ 和前一个合并，右键音节在点的位置拆开（一个字的拆成「字 + 空拍」= 多唱一拍）；滚轮缩放，Shift+滚轮平移"""
    H = 170

    def __init__(self, master, app, on_change):
        super().__init__(master)
        self.app, self.on_change = app, on_change
        self.line, self.syls, self.starts = None, [], []
        self.undo, self.drag, self.tap, self.view = [], None, None, None
        self.peaks, self._peaks_key = None, None
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 4))
        ttk.Button(bar, text="◀ 上一句", command=lambda: self.on_change("step", -1)).pack(side="left")
        ttk.Button(bar, text="▶ 播放本句", command=self.play_line).pack(side="left", padx=4)
        ttk.Button(bar, text="打点 (K)", command=self.start_tap).pack(side="left")
        ttk.Button(bar, text="均分", command=self.even).pack(side="left", padx=4)
        ttk.Button(bar, text="撤销 (Ctrl+Z)", command=self.pop).pack(side="left")
        ttk.Button(bar, text="整句", command=self.fit).pack(side="left", padx=4)
        ttk.Button(bar, text="下一句 ▶", command=lambda: self.on_change("step", 1)).pack(side="left")
        self.info = ttk.Label(bar, foreground="#666")
        self.info.pack(side="left", padx=8)
        ttk.Label(self, foreground="#666", text="右键：拆开 / 合并　滚轮：缩放　Shift+滚轮：平移").pack(anchor="w")
        self.cv = tk.Canvas(self, height=self.H, bg="#1e1e1e", highlightthickness=0)
        self.cv.pack(fill="both", expand=True)
        self.cv.bind("<Configure>", lambda e: self.draw())
        self.cv.bind("<Button-1>", self.press)
        self.cv.bind("<B1-Motion>", self.motion)
        self.cv.bind("<ButtonRelease-1>", self.release)
        self.cv.bind("<Button-3>", self.right)
        self.cv.bind("<MouseWheel>", self.wheel)
        self.cv.bind("<Shift-MouseWheel>", lambda e: self.wheel(e, pan=True))
        self.after(40, self.follow)

    # ---- 数据
    def load(self, line, saved, label):
        self.line = line
        self.syls, self.starts = z.k_starts(line["text"], self.dur())
        if saved is not None:
            self.syls, self.starts = list(saved[0]), list(saved[1])
        self.undo, self.tap, self.view = [], None, None
        self.info.config(text=label)
        self.draw()

    def dur(self):
        return self.line["end_time"] - self.line["start_time"]

    def span(self):
        """整句（秒）：行前后各留 0.3 秒"""
        return self.line["start_time"] / 1000 - 0.3, self.line["end_time"] / 1000 + 0.3

    def win(self):
        return self.view or self.span()

    def x_of(self, t):
        a, b = self.win()
        return (t - a) / (b - a) * self.cv.winfo_width()

    def t_of(self, x):
        a, b = self.win()
        return a + x / max(1, self.cv.winfo_width()) * (b - a)

    def rel(self, x):
        """画布 x → 相对行开头的毫秒（10 毫秒一格）"""
        return round((self.t_of(x) * 1000 - self.line["start_time"]) / 10) * 10

    def commit(self):
        self.on_change("starts", (list(self.syls), list(self.starts)))
        self.draw()

    def push(self):
        self.undo.append((list(self.syls), list(self.starts)))

    def pop(self):
        if self.undo:
            self.syls, self.starts = self.undo.pop()
            self.commit()

    def even(self):
        """切法不动，时间按个数均分"""
        if self.line:
            self.push()
            n = len(self.starts)
            self.starts = [round(self.dur() * k / n / 10) * 10 for k in range(n)]
            self.commit()

    # ---- 缩放
    def fit(self):
        self.view = None
        self.draw()

    def wheel(self, e, pan=False):
        if not self.line:
            return
        a, b = self.win()
        s0, s1 = self.span()
        if pan:
            d = (b - a) * (-0.15 if e.delta > 0 else 0.15)
            d = max(s0 - a, min(s1 - b, d))
            a, b = a + d, b + d
        else:
            t, f = self.t_of(e.x), (0.8 if e.delta > 0 else 1.25)
            a, b = t - (t - a) * f, t + (b - t) * f
            if b - a < 0.3:
                return
            a, b = max(s0, a), min(s1, b)
        self.view = None if (a, b) == (s0, s1) else (a, b)
        self.draw()

    # ---- 画
    def hgt(self):
        return max(self.H, self.cv.winfo_height())

    def draw(self):
        cv = self.cv
        cv.delete("all")
        self.head = None
        if not self.line:
            return
        w, h = cv.winfo_width(), self.hgt()
        p = self.app.player
        a, b = self.win()
        key = (p.wav, w, a, b)
        if p.wav and self._peaks_key != key:
            self.peaks, self._peaks_key = z.wav_peaks(p.wav, a - p.t0, b - p.t0, max(1, w // 2)), key
        elif not p.wav:
            self.peaks = None
        e0 = self.x_of(self.line["end_time"] / 1000)
        cv.create_rectangle(-5, 0, self.x_of(self.line["start_time"] / 1000), h, fill="#111", outline="")
        cv.create_rectangle(e0, 0, w + 5, h, fill="#111", outline="")
        xs = [self.x_of(self.line["start_time"] / 1000 + t / 1000) for t in self.starts] + [e0]
        for k in range(len(self.syls)):
            if xs[k + 1] - xs[k] > 2:
                cv.create_rectangle(xs[k], 22, xs[k + 1], h - 4, outline="",
                                    fill="#2a4a2a" if self.tap is not None and k < self.tap else "#26323d")
        mid, amp = (22 + h - 36) / 2, (h - 60) / 2 / (max(self.peaks or [0]) or 1)
        for k, v in enumerate(self.peaks or []):
            cv.create_line(k * 2, mid - v * amp, k * 2, mid + v * amp, fill="#5aa0d8")
        for k, sy in enumerate(self.syls):
            cv.create_text((xs[k] + xs[k + 1]) / 2, h - 18, text=sy.strip() or "～",
                           fill="#eee" if sy.strip() else "#888", font=("Microsoft YaHei UI", 12))
        for k, x in enumerate(xs[:-1]):
            col = "#ff4040" if k == self.tap else "#ffb000"
            cv.create_line(x, 14, x, h, fill=col)
            cv.create_polygon(x, 4, x + 7, 12, x, 20, x - 7, 12, fill=col, outline="")
        cv.create_line(e0, 0, e0, h, fill="#888", dash=(3, 3))
        self.head = cv.create_line(-10, 0, -10, h, fill="#ff4040", width=2)

    def follow(self):
        """播放时画播放头；缩放着的时候播放头出了画面就翻页"""
        p = self.app.player
        if self.line and self.winfo_ismapped():
            if p.playing and self.view:
                a, b = self.view
                t = p.now()
                s0, s1 = self.span()
                if (t > b or t < a) and s0 <= t <= s1:
                    d = t - (b - a) * 0.1 - a
                    d = max(s0 - a, min(s1 - b, d))
                    self.view = (a + d, b + d)
                    self.draw()
            x = self.x_of(p.now()) if p.playing else -10
            if self.head:
                self.cv.coords(self.head, x, 0, x, self.hgt())
            if self.peaks is None and p.wav:
                self.draw()
        self.after(30, self.follow)

    # ---- 鼠标
    def near(self, x):
        xs = [self.x_of(self.line["start_time"] / 1000 + t / 1000) for t in self.starts]
        k = min(range(len(xs)), key=lambda k: abs(xs[k] - x), default=None)
        return k if k is not None and abs(xs[k] - x) <= 8 else None

    def which(self, t):
        """t（相对毫秒）落在第几个音节"""
        k = max((k for k, s in enumerate(self.starts) if s <= t), default=None)
        return k if k is not None and t <= self.dur() else None

    def end_of(self, k):
        return self.starts[k + 1] if k + 1 < len(self.starts) else self.dur()

    def press(self, e):
        if not self.line:
            return
        self.drag = self.near(e.x)
        if self.drag is not None:
            self.push()
            return
        k = self.which(self.rel(e.x))
        if k is not None:
            self.play_part(self.starts[k] / 1000, self.end_of(k) / 1000)

    def motion(self, e):
        k = self.drag
        if k is None:
            return
        lo = self.starts[k - 1] if k else 0
        self.starts[k] = max(lo, min(self.end_of(k), self.rel(e.x)))
        self.draw()

    def release(self, e):
        if self.drag is not None:
            self.drag = None
            if self.undo and self.undo[-1] == (self.syls, self.starts):
                self.undo.pop()
            else:
                self.commit()

    def right(self, e):
        """右键 ◆：和前一个音节合并；右键音节中间：在这里拆开"""
        if not self.line:
            return
        k = self.near(e.x)
        if k is not None:
            if k == 0:
                return
            self.push()
            self.syls[k - 1] += self.syls.pop(k)
            self.starts.pop(k)
            self.commit()
            return
        t = self.rel(e.x)
        k = self.which(t)
        if k is None or not self.starts[k] < t < self.end_of(k):
            return
        self.push()
        sy = self.syls[k]
        if len(sy.strip()) >= 2:
            frac = (t - self.starts[k]) / (self.end_of(k) - self.starts[k])
            i = max(1, min(len(sy) - 1, round(frac * len(sy))))
            left, right = sy[:i], sy[i:]
        else:
            left, right = sy, ""   # 一个字：后面加一拍空的，同一个字多唱一拍
        self.syls[k:k + 1] = [left, right]
        self.starts.insert(k + 1, t)
        self.commit()

    # ---- 声音
    def play_part(self, a, b):
        p = self.app.player
        if not p.wav:
            return
        p.stop()
        base = self.line["start_time"] / 1000 - p.t0
        out = os.path.join(p.tmp, "syl%d.wav" % (int(time.time() * 1000) % 1000000))
        z.wav_cut(p.wav, base + a, base + b, out)
        z.Sound.play(out)

    def play_line(self):
        p = self.app.player
        p.stop()
        p.t = max(p.t0, self.line["start_time"] / 1000 - 1)
        p.play()

    def start_tap(self):
        """从本句前 1 秒开始播，每按一次 K 定下一个音节的开头"""
        if not self.line:
            return
        self.push()
        self.tap = 0
        self.play_line()
        self.draw()

    def key_k(self):
        if self.tap is None:
            self.start_tap()
            return
        t = round((self.app.player.now() * 1000 - self.line["start_time"]) / 10) * 10
        k = self.tap
        lo = self.starts[k - 1] if k else 0
        self.starts[k] = max(lo, min(self.dur(), t))
        for j in range(k + 1, len(self.starts)):
            self.starts[j] = max(self.starts[j], self.starts[k])
        self.tap = k + 1 if k + 1 < len(self.starts) else None
        self.commit()


# ================================================================ 卡拉OK页
class KaraTab(ttk.Frame):
    title = "卡拉OK"

    def __init__(self, nb, app):
        super().__init__(nb, padding=6)
        self.app = app
        self.edits = z.Edits()
        self.pack_index = None
        self.shown = []
        self.tpl_file = None      # (info, styles, rows)：选中的社区模板文件
        d = app.doc
        self.src = [i for i in sorted(app.sel) if d.by_i(i)["class"] == "dialogue" and d.by_i(i)["effect"] not in ("fx", FX_LAYER)
                    and not TPL_RE.match(d.by_i(i)["effect"])]
        ttk.Label(self, text=f"所选歌词 {len(self.src)} 句").pack(anchor="w")
        self.lines = tk.Listbox(self, height=6, width=70, exportselection=False)
        self.lines.pack(fill="x")
        for i in self.src:
            l = d.by_i(i)
            self.lines.insert("end", f"#{i} {z.ms2ass(l['start_time'])} [{l['style']}] {l['text'][:60]}")
        self.kf = tk.IntVar(self, 0)
        ttk.Checkbutton(self, text="\\kf 渐变填色", variable=self.kf, command=self.changed).pack(anchor="w", pady=4)
        self.starts = [None] * len(self.src)   # 每句手动定的 (音节, 关键帧)（None = 没动过，用行里原来的 \\k）
        self.cur = 0
        self.tl = KTimeline(app.dock["kara"], app, self.tl_changed)
        self.tl.pack(fill="both", expand=True)
        self.lines.bind("<<ListboxSelect>>",
                        lambda e: self.lines.curselection() and self.show_line(self.lines.curselection()[0]))
        tf = ttk.LabelFrame(self, text="模板", padding=4)
        tf.pack(fill="both", expand=True)
        srcf = ttk.Frame(tf)
        srcf.pack(fill="x")
        self.tsrc = tk.StringVar(self, "pack")
        ttk.Radiobutton(srcf, text="社区模板合集（481 个）", value="pack", variable=self.tsrc,
                        command=self.src_changed).pack(side="left")
        ttk.Radiobutton(srcf, text="字幕里已有的 / 自己写的", value="file", variable=self.tsrc,
                        command=self.src_changed).pack(side="left", padx=8)
        self.pack_frame = ttk.Frame(tf)
        fl = ttk.Frame(self.pack_frame)
        fl.pack(fill="x")
        ttk.Label(fl, text="筛选").pack(side="left")
        self.flt = tk.StringVar(self)
        self.flt.trace_add("write", lambda *a: self.fill_pack())
        ttk.Entry(fl, textvariable=self.flt, width=18).pack(side="left", padx=4)
        ttk.Button(fl, text="获取 / 刷新列表", command=self.fetch_index).pack(side="left")
        self.pack_lbl = ttk.Label(fl, foreground="#666")
        self.pack_lbl.pack(side="left", padx=6)
        self.pack_lst = tk.Listbox(self.pack_frame, height=6, exportselection=False)
        self.pack_lst.pack(fill="x")
        self.pack_lst.bind("<<ListboxSelect>>", lambda e: self.pick_pack())
        self.restyle = tk.IntVar(self, 0)
        ttk.Checkbutton(self.pack_frame, text="套用模板样式", variable=self.restyle,
                        command=self.changed).pack(anchor="w")
        self.tpl_lbl = ttk.Label(tf, text="模板行", foreground="#666")
        self.tpl_lbl.pack(anchor="w")
        self.tpl = tk.Text(tf, height=7, width=70, font=("Consolas", 9), undo=True, wrap="none")
        self.tpl.pack(fill="both", expand=True)
        self.tpl.bind("<<Modified>>", self.tpl_mod)
        self.log = ttk.Label(self, foreground="#a33", wraplength=560, justify="left")
        self.log.pack(anchor="w")
        ttk.Label(self, foreground="#666", wraplength=560, justify="left",
                  text="社区模板来自 GitHub 上 Seekladoom 整理的合集（多为越南社区作者），版权归原作者，只下载到你电脑上用。"
                       "不少是按 720p、VSFilterMod 做的，个别标签在普通渲染器下不生效，以预览为准。").pack(anchor="w")
        try:
            self.pack_index = json.load(open(os.path.join(PACK, "index.json"), encoding="utf-8"))
        except (OSError, ValueError):
            pass
        self.fill_pack()
        self.src_changed()
        if self.src:
            self.show_line(0)

    def show_line(self, n):
        self.cur = n
        self.lines.selection_clear(0, "end")
        self.lines.selection_set(n)
        self.lines.see(n)
        l = self.app.doc.by_i(self.src[n])
        self.tl.load(l, self.starts[n], f"{n + 1} / {len(self.src)}　{l['style']}")

    def tl_changed(self, what, v):
        if what == "step":
            if self.src:
                self.show_line(max(0, min(len(self.src) - 1, self.cur + v)))
            return
        self.starts[self.cur] = v
        self.changed()

    def src_changed(self):
        if self.tsrc.get() == "pack":
            self.pack_frame.pack(fill="x", before=self.tpl_lbl)
            if self.tpl_file:
                self.set_tpl(z.template_rows(self.tpl_file[2]))
        else:
            self.pack_frame.pack_forget()
            styles = {self.app.doc.by_i(i)["style"] for i in self.src}
            self.set_tpl([r for r in z.template_rows(self.app.doc.dialogue()) if r["style"] in styles])

    def set_tpl(self, rows):
        self.tpl.delete("1.0", "end")
        self.tpl.insert("1.0", template_text(rows))
        self.tpl.edit_modified(False)
        self.changed()

    def tpl_mod(self, e):
        if self.tpl.edit_modified():
            self.tpl.edit_modified(False)
            self.changed()

    def fill_pack(self):
        self.pack_lst.delete(0, "end")
        if not self.pack_index:
            self.pack_lbl.config(text="还没获取列表")
            return
        q = self.flt.get().lower()
        self.shown = [n for n in self.pack_index if q in n.lower()]
        for n in self.shown:
            self.pack_lst.insert("end", ("✓ " if os.path.exists(os.path.join(PACK, n)) else "    ") + n[:-4])
        self.pack_lbl.config(text=f"{len(self.shown)} / {len(self.pack_index)} 个")

    def fetch_index(self):
        self.pack_lbl.config(text="从 GitHub 获取列表……")

        def work():
            try:
                d = json.loads(http_get(f"https://api.github.com/repos/{PACK_REPO}/git/trees/master?recursive=1"))
                names = sorted((t["path"][len(PACK_DIR):] for t in d["tree"]
                                if t["path"].startswith(PACK_DIR) and t["path"].endswith(".ass")), key=str.lower)
                os.makedirs(PACK, exist_ok=True)
                with open(os.path.join(PACK, "index.json"), "w", encoding="utf-8") as f:
                    json.dump(names, f, ensure_ascii=False)
                self.app.ui_q.put(("call", lambda: (setattr(self, "pack_index", names), self.fill_pack())))
            except Exception as ex:
                self.app.ui_q.put(("call", lambda ex=ex: self.pack_lbl.config(text=f"获取失败：{ex}（检查网络 / 代理）")))
        threading.Thread(target=work, daemon=True).start()

    def pick_pack(self):
        s = self.pack_lst.curselection()
        if not s:
            return
        name = self.shown[s[0]]
        path = os.path.join(PACK, name)

        def done():
            self.tpl_file = z.parse_ass(open(path, encoding="utf-8-sig", errors="replace").read())
            self.fill_pack()
            rows = z.template_rows(self.tpl_file[2])
            self.set_tpl(rows)
            if not rows:
                self.log.config(text="这个文件里没有模板行（可能只有生成好的效果），换一个", foreground="#a33")
        if os.path.exists(path):
            done()
            return
        self.pack_lbl.config(text=f"下载 {name} ……")

        def work():
            try:
                data = http_get("https://raw.githubusercontent.com/%s/master/%s" % (
                    PACK_REPO, urllib.parse.quote(PACK_DIR + name)))
                os.makedirs(PACK, exist_ok=True)
                with open(path, "wb") as f:
                    f.write(data)
                self.app.ui_q.put(("call", done))
            except Exception as ex:
                self.app.ui_q.put(("call", lambda ex=ex: self.pack_lbl.config(text=f"下载失败：{ex}")))
        threading.Thread(target=work, daemon=True).start()

    def changed(self):
        self.app.schedule(self.recompute, 300)

    def recompute(self):
        if not self.src:
            return
        rows = parse_template_text(self.tpl.get("1.0", "end"))
        if not rows:
            self.edits = z.Edits()
            self.log.config(text="还没选模板", foreground="#666")
            self.app.edits_changed()
            return
        doc = self.app.doc
        styles = {doc.by_i(i)["style"] for i in self.src}
        tpls = {s: [dict(r, style=s) for r in rows] for s in styles}
        restyle = None
        if self.restyle.get() and self.tsrc.get() == "pack" and self.tpl_file:
            info, tst, trows = self.tpl_file
            used = [r["style"] for r in z.template_rows(trows)]
            base = tst.get(used[0]) if used and used[0] in tst else next(iter(tst.values()), None)
            if base:
                k = self.app.res[1] / float(info.get("PlayResY", 0) or 288)
                restyle = {}
                for s in styles:
                    st = dict(doc.styles()[s])
                    for f in ("fontname", "color1", "color2", "color3", "color4", "bold", "italic", "borderstyle"):
                        st[f] = base[f]
                    for f in ("fontsize", "outline", "shadow", "spacing"):
                        st[f] = round(float(base[f]) * k, 2)
                    restyle[s] = st
        styles_v, events = z.Edits().view(doc)
        try:
            self.edits, log = kara_edits(self.app.kara(), doc, styles_v, events, set(self.src), tpls, "keep",
                                         self.starts, "kf" if self.kf.get() else "k", True, restyle)
            n = sum(1 for v in self.edits.ins.values() for r in v if r.get("effect") == "fx")
            self.log.config(text=(log.strip() + "\n" if log.strip() else "") + f"生成 {n} 行特效，点「预览」看",
                            foreground="#a33" if log.strip() else "#363")
        except Exception as ex:
            self.edits = z.Edits()
            self.log.config(text=f"模板出错：{ex}"[:600], foreground="#a33")
        self.app.edits_changed()


# ================================================================ AI 页
class AiTab(ttk.Frame):
    title = "AI 助手"

    def __init__(self, nb, app):
        super().__init__(nb, padding=6)
        self.app = app
        self.edits = z.Edits()
        self.conf = zxai.load_conf()
        self.hist_path = os.path.join(HOME, "ai_history.json")
        self.messages = []
        self.busy, self.stop_flag = False, False
        cf = ttk.LabelFrame(self, text="接口", padding=4)
        cf.pack(fill="x")
        self.proto = tk.StringVar(self, "Anthropic" if self.conf.get("protocol") == "anthropic" else "OpenAI 兼容")
        self.base = tk.StringVar(self, self.conf.get("base_url", ""))
        self.key = tk.StringVar(self, self.conf.get("key", ""))
        self.model = tk.StringVar(self, self.conf.get("model", ""))
        r1 = ttk.Frame(cf)
        r1.pack(fill="x")
        ttk.Combobox(r1, values=["OpenAI 兼容", "Anthropic"], width=12, state="readonly",
                     textvariable=self.proto).pack(side="left")
        ttk.Label(r1, text="Base URL").pack(side="left", padx=(6, 2))
        ttk.Entry(r1, textvariable=self.base, width=36).pack(side="left")
        r2 = ttk.Frame(cf)
        r2.pack(fill="x", pady=2)
        ttk.Label(r2, text="Key").pack(side="left")
        ttk.Entry(r2, textvariable=self.key, width=26, show="•").pack(side="left", padx=2)
        ttk.Label(r2, text="模型").pack(side="left", padx=(6, 2))
        ttk.Entry(r2, textvariable=self.model, width=20).pack(side="left")
        ttk.Button(r2, text="保存", command=self.save_conf).pack(side="left", padx=4)
        self.chat = tk.Text(self, height=15, width=70, wrap="char", state="disabled", font=("Microsoft YaHei UI", 9))
        self.chat.pack(fill="both", expand=True, pady=4)
        self.chat.tag_config("me", foreground="#1a4f9c")
        self.chat.tag_config("tool", foreground="#888")
        self.chat.tag_config("err", foreground="#b22")
        self.inp = tk.Text(self, height=3, width=70, font=("Microsoft YaHei UI", 9))
        self.inp.pack(fill="x")
        self.inp.bind("<Control-Return>", lambda e: (self.send(), "break")[1])
        b = ttk.Frame(self)
        b.pack(fill="x", pady=2)
        self.send_btn = ttk.Button(b, text="发送（Ctrl+Enter）", command=self.send)
        self.send_btn.pack(side="left")
        ttk.Button(b, text="停止", command=lambda: setattr(self, "stop_flag", True)).pack(side="left", padx=2)
        ttk.Button(b, text="清空对话", command=self.clear_chat).pack(side="left", padx=2)
        self.shot = tk.IntVar(self, 0)
        ttk.Checkbutton(b, text="附当前画面", variable=self.shot).pack(side="left", padx=6)
        self.pend = ttk.Label(b, foreground="#666")
        self.pend.pack(side="left", padx=6)
        ttk.Button(b, text="清空 AI 改动", command=self.clear_edits).pack(side="right")
        try:
            self.messages = json.load(open(self.hist_path, encoding="utf-8"))
            self.say("（接着上次的对话。换了字幕文件的话行号对不上，点「清空对话」重新开始）\n", "tool")
            for m in self.messages:
                for bl in m["content"]:
                    if bl["type"] == "text" and bl.get("text") and not bl["text"].startswith("【当前字幕情况】"):
                        self.say(("你：" if m["role"] == "user" else "AI：") + bl["text"] + "\n",
                                 "me" if m["role"] == "user" else None)
        except (OSError, ValueError):
            self.messages = []
        self.update_pending()

    def save_conf(self, quiet=False):
        self.conf = {"protocol": "anthropic" if self.proto.get() == "Anthropic" else "openai",
                     "base_url": self.base.get().strip(), "key": self.key.get().strip(),
                     "model": self.model.get().strip()}
        zxai.save_conf(self.conf)
        if not quiet:
            self.say("（接口设置已保存）\n", "tool")

    def say(self, s, tag=None):
        self.chat.configure(state="normal")
        self.chat.insert("end", s, tag or ())
        self.chat.see("end")
        self.chat.configure(state="disabled")

    def update_pending(self):
        self.pend.config(text=f"AI 待应用改动 {self.edits.count()} 处")

    def clear_edits(self):
        self.edits = z.Edits()
        self.update_pending()
        self.app.edits_changed()

    def clear_chat(self):
        self.messages = []
        self.chat.configure(state="normal")
        self.chat.delete("1.0", "end")
        self.chat.configure(state="disabled")
        self.save_hist()

    def save_hist(self):
        def strip(m):
            return {"role": m["role"], "content": [
                {"type": "text", "text": "[图片]"} if b["type"] == "image" else {k: v for k, v in b.items() if k != "png"}
                for b in m["content"]]}
        msgs = self.messages[-60:]
        while msgs and msgs[0]["role"] != "user" or (msgs and any(b["type"] == "tool_result" for b in msgs[0]["content"])):
            msgs = msgs[1:]   # 截断后第一条必须是用户的正常消息
        try:
            with open(self.hist_path, "w", encoding="utf-8") as f:
                json.dump([strip(m) for m in msgs], f, ensure_ascii=False)
        except OSError:
            pass

    def context(self):
        """第一句话附上：分辨率、样式、所选行和前后几行、当前时间"""
        doc = self.app.doc
        w, h = self.app.res
        out = [f"字幕分辨率 {w}x{h}；样式：{', '.join(doc.styles())}；视频当前时间 {self.app.job.get('time', 0)} 毫秒；"
               f"{'开着视频' if self.app.player.video else '没开视频'}。"]
        if self.app.sel:
            lo, hi = min(self.app.sel), max(self.app.sel)
            out.append("用户选中了：" + ", ".join(f"#{i}" for i in self.app.sel[:50]))
            out.append("所选行和前后几行：\n" + self.list_lines({"from_index": lo - 8, "to_index": hi + 8}))
        return "\n".join(out)

    def send(self):
        if self.busy:
            return
        text = self.inp.get("1.0", "end").strip()
        if not text:
            return
        self.save_conf(quiet=True)
        self.inp.delete("1.0", "end")
        self.say("\n你：" + text + "\n", "me")
        content = []
        if not self.messages:
            content.append({"type": "text", "text": "【当前字幕情况】\n" + self.context()})
        content.append({"type": "text", "text": text})
        if self.shot.get():
            content.append({"type": "image", "png": self.app.player.frame_png(self.app.player.t)})
        self.messages.append({"role": "user", "content": content})
        self.busy, self.stop_flag = True, False
        self.send_btn.state(["disabled"])
        threading.Thread(target=self.loop, daemon=True).start()

    def loop(self):
        client = zxai.Client(self.conf)
        post = lambda fn: self.app.ui_q.put(("call", fn))
        try:
            for _ in range(24):   # 一次提问最多 24 轮工具调用
                post(lambda: self.say("AI："))
                out = client.chat(zxai.SYSTEM, self.messages, zxai.TOOLS,
                                  lambda s: post(lambda s=s: self.say(s)), lambda: self.stop_flag)
                self.messages.append({"role": "assistant", "content": out})
                post(lambda: self.say("\n"))
                calls = [b for b in out if b["type"] == "tool_use"]
                if not calls:
                    break
                results = []
                for c in calls:
                    post(lambda c=c: self.say(f"  ⚙ {c['name']} {json.dumps(c['input'], ensure_ascii=False)[:160]}\n",
                                              "tool"))
                    res = self.app.run_main(lambda c=c: self.tool(c["name"], c["input"]))
                    text, png = res if isinstance(res, tuple) else (res, None)
                    results.append({"type": "tool_result", "id": c["id"], "content": text, "png": png})
                self.messages.append({"role": "user", "content": results})
                if self.stop_flag:
                    break
        except zxai.Stopped:
            post(lambda: self.say("\n（已停止）\n", "tool"))
        except Exception as ex:
            post(lambda ex=ex: self.say(f"\n出错：{ex}\n", "err"))
        if self.messages and self.messages[-1]["role"] == "assistant" and \
                any(b["type"] == "tool_use" for b in self.messages[-1]["content"]):
            self.messages.pop()   # 工具没跑完就停了：去掉这半轮，免得下次接口报格式错
        post(self.done)

    def done(self):
        self.busy = False
        self.send_btn.state(["!disabled"])
        self.save_hist()
        self.update_pending()

    # ---- 工具（在界面线程里跑）
    def view(self):
        return self.app.all_edits().view(self.app.doc)

    def list_lines(self, a):
        _, ev = self.view()
        out = []
        for r in ev:
            i = r.get("i")
            if not a.get("include_fx") and r["effect"] in ("fx", FX_LAYER):
                continue
            if a.get("from_index") is not None and (i is None or i < a["from_index"]):
                continue
            if a.get("to_index") is not None and (i is None or i > a["to_index"]):
                continue
            if a.get("style") and a["style"] not in r["style"]:
                continue
            if a.get("contains") and a["contains"] not in r["text"]:
                continue
            if a.get("time_from_ms") is not None and r["end_time"] < a["time_from_ms"]:
                continue
            if a.get("time_to_ms") is not None and r["start_time"] > a["time_to_ms"]:
                continue
            out.append(f"{'#%d' % i if i else '#新'} {r['start_time']}-{r['end_time']}ms [{r['style']}] L{r['layer']}"
                       f"{' 注释' if r['comment'] else ''}{' 特效栏=' + r['effect'] if r['effect'] else ''} | {r['text']}")
            if len(out) >= 200:
                out.append("……（超过 200 行，缩小范围再查）")
                break
        return "\n".join(out) or "（没有符合条件的行）"

    def tool(self, name, a):
        doc = self.app.doc
        try:
            if name == "list_lines":
                return self.list_lines(a)
            if name == "get_styles":
                styles, _ = self.view()
                return "\n".join(z.style_line(s) for n, s in styles.items() if not a.get("names") or n in a["names"])
            if name == "set_lines":
                n = 0
                for c in a.get("changes", []):
                    i = int(c["index"])
                    if not (1 <= i <= len(doc.rows)) or doc.by_i(i)["class"] != "dialogue":
                        return f"#{i} 不是字幕行，没改"
                    kw = {k: c[k] for k in ("text", "style", "layer", "effect", "comment", "actor") if k in c}
                    if "start_ms" in c:
                        kw["start_time"] = int(c["start_ms"])
                    if "end_ms" in c:
                        kw["end_time"] = int(c["end_ms"])
                    self.edits.set(i, **kw)
                    n += 1
                return f"改了 {n} 行（待应用）"
            if name == "insert_lines":
                after = int(a["after_index"])
                if after <= 0:
                    after = max([r["i"] for r in doc.rows if r["class"] in ("style", "info")] or [0])
                for l in a["lines"]:
                    self.edits.insert_after(after, {
                        "comment": bool(l.get("comment")), "layer": int(l.get("layer", 0)),
                        "start_time": int(l["start_ms"]), "end_time": int(l["end_ms"]), "style": l["style"],
                        "actor": l.get("actor", ""), "margin_l": 0, "margin_r": 0, "margin_t": 0, "margin_b": 0,
                        "effect": l.get("effect", ""), "text": l["text"]})
                return f"插入 {len(a['lines'])} 行（待应用）"
            if name == "delete_lines":
                for i in a["indices"]:
                    self.edits.delete(int(i))
                return f"删除 {len(a['indices'])} 行（待应用）"
            if name == "set_style":
                styles, _ = self.view()
                base = dict(styles.get(a["name"]) or styles.get("Default") or next(iter(styles.values())))
                for k, v in a.items():
                    if k == "margin_v":
                        base["margin_t"] = base["margin_b"] = v
                    elif k.startswith("color"):
                        base[k] = z.color_hex(v)
                    else:
                        base[k] = v
                self.edits.upsert_style(base)
                return f"样式 {a['name']} 已设置（待应用）"
            if name == "run_karaoke":
                idx = {int(i) for i in a["indices"]}
                styles, ev = self.view()
                tpls = {}
                for r in z.template_rows(ev):
                    tpls.setdefault(r["style"], []).append(r)
                e, log = kara_edits(self.app.kara(), doc, styles, ev, idx, tpls, a.get("k_mode", "keep"),
                                    insert_templates=False)
                self.edits = self.edits.merged(e)
                n = sum(1 for v in e.ins.values() for r in v if r.get("effect") == "fx")
                return f"生成 {n} 行 fx（待应用）" + (f"\n模板引擎输出：{log[:1500]}" if log.strip() else "")
            if name == "render":
                self.app.player.invalidate()
                return "这是 %d 毫秒的画面" % a["time_ms"], self.app.player.frame_png(a["time_ms"] / 1000)
            if name == "clear_pending":
                self.edits = z.Edits()
                return "已清空"
            return f"没有这个工具：{name}"
        except Exception as ex:
            return f"工具出错：{ex}"
        finally:
            self.update_pending()
            self.app.edits_changed()


# ================================================================ 主窗口
class App(tk.Tk):
    def __init__(self, job):
        super().__init__()
        global PW
        PW = max(960, min(1600, self.winfo_screenwidth() // 2 // 16 * 16))
        self.title("轴效 · 特效工作台")
        self.job = job
        self.doc = z.Doc(job["dump"]) if job.get("dump") else z.Doc()
        if not self.doc.rows:
            self.doc.rows = [{"class": "info", "key": "PlayResX", "value": "1920", "i": 1},
                             {"class": "info", "key": "PlayResY", "value": "1080", "i": 2}]
        self.res = self.doc.res()
        self.sel = list(job.get("sel") or [])
        self.settings = load_settings()
        z.load_fonts(self.settings.get("fonts_dir"))
        self.measure = z.Measure()
        self._kara, self._fonts = None, None
        self._folder, self._face_ok = None, {}
        self.ui_q = queue.Queue()
        self.pending = {}
        self.tabs = []
        right = ttk.Frame(self)
        right.grid(row=0, column=1, sticky="nsew", padx=6, pady=6)
        self.player = Player(right, self)
        self.player.pack(anchor="n")
        # 预览下面的空位：特效样式页放「特效」，卡拉OK页放关键帧时间轴，跟着切页换
        self.dock = {k: ttk.Frame(right) for k in ("fx", "kara")}
        self.nb = nb = ttk.Notebook(self)
        nb.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.player.canvas.bind("<Button-1>", self.click)
        self.player.canvas.bind("<Button-3>", lambda e: self.fx.set_pos(None))
        bot = ttk.Frame(self, padding=6)
        bot.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.status = ttk.Label(bot, foreground="#666")
        self.status.pack(side="left")
        self.fx = FxTab(nb, self)
        self.fx.fonts_cb_update()
        self.ka = KaraTab(nb, self)
        self.ai = AiTab(nb, self)
        self.tabs = [self.fx, self.ka, self.ai]
        for t in self.tabs:
            nb.add(t, text=t.title)
        nb.bind("<<NotebookTabChanged>>", lambda e: self.tab_changed())
        nb.select({"fx": 0, "kara": 1, "ai": 2}.get(job.get("tab"), 0))
        self.tab_changed()
        ttk.Button(bot, text="关闭", command=self.close).pack(side="right", padx=2)
        ttk.Button(bot, text="应用", command=self.apply).pack(side="right", padx=2)
        ttk.Button(bot, text="保存方案", command=self.fx.save).pack(side="right", padx=2)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<space>", self.space)
        self.bind("<KeyPress-k>", self.key_k)
        self.bind("<KeyPress-K>", self.key_k)
        self.bind("<Control-z>", lambda e: self.typing() or self.cur_tab() is not self.ka or self.ka.tl.pop())
        self.state("zoomed")
        self.player.set_clip(*self.clip_range())
        self.edits_changed()
        self.after(30, self.poll)

    def font_folder(self):
        return self.settings.get("fonts_dir") or ""

    def folder_fonts(self):
        """字体文件夹里能用的家族：{名字: 文件}。第一次问的时候顺手把它们注册给本进程"""
        if self._folder is None:
            self._folder = z.usable_fonts(self.font_folder())
        return self._folder

    def fonts(self):
        if self._fonts is None:
            names = set(font_names(self))
            names.update(self.folder_fonts())
            self._fonts = sorted(names, key=str.lower)
        return self._fonts

    def font_note(self, name):
        """这个字体名能不能用上：在字体文件夹里 / 系统装了 / 会回退成谁（返回文字和颜色）"""
        if not name:
            return "", "#888"
        if name in self.folder_fonts():
            return "字体文件夹里的（没装进系统）", "#0a7a44"
        if name not in self._face_ok:
            self._face_ok[name] = z.font_ok(name)
        if not self._face_ok[name]:
            return "⚠ 找不到这个字体，预览会拿「%s」顶替" % z.resolve_face(name), "#c0392b"
        return "打字筛选，↓ 展开", "#888"

    def kara(self):
        if self._kara is None:
            self._kara = z.Kara(self.job["aegisub_dir"], self.player.video.fps if self.player.video else 24000 / 1001)
        return self._kara

    def active_line(self):
        a = self.job.get("active") or (self.sel[0] if self.sel else None)
        if a and 1 <= a <= len(self.doc.rows) and self.doc.by_i(a)["class"] == "dialogue":
            return self.doc.by_i(a)
        return None

    def first_pos(self):
        l = self.active_line()
        m = l and re.search(r"\\pos\(([\d.\-]+),([\d.\-]+)\)", l["text"])
        return (float(m.group(1)), float(m.group(2))) if m else None

    def clip_range(self):
        ls = [self.doc.by_i(i) for i in self.sel if self.doc.by_i(i)["class"] == "dialogue"]
        if ls:
            return min(l["start_time"] for l in ls) / 1000 - 5, max(l["end_time"] for l in ls) / 1000 + 5
        t = self.job.get("time", 0) / 1000
        return t - 5, t + 5

    def all_edits(self):
        e = z.Edits()
        for t in self.tabs:
            e = e.merged(t.edits)
        return e

    def preview_view(self):
        return self.all_edits().view(self.doc)

    def schedule(self, fn, ms=40):
        """短时间内的多次改动合并成一次"""
        key = getattr(fn, "__func__", fn)
        if key in self.pending:
            self.after_cancel(self.pending[key])
        self.pending[key] = self.after(ms, lambda: (self.pending.pop(key, None), fn()))

    def edits_changed(self):
        if len(self.tabs) < 3:
            return
        self.player.invalidate()
        self.status.config(text=f"待应用改动 {self.all_edits().count()} 处（特效样式 {self.fx.edits.count()}、"
                                f"卡拉OK {self.ka.edits.count()}、AI {self.ai.edits.count()}）")

    def run_main(self, fn):
        """后台线程要在界面线程里跑点东西（AI 的工具），等结果"""
        box, ev = [], threading.Event()
        self.ui_q.put(("main", fn, box, ev))
        ev.wait()
        return box[0]

    def poll(self):
        try:
            while True:
                it = self.ui_q.get_nowait()
                if it[0] == "call":
                    it[1]()
                elif it[0] == "main":
                    try:
                        it[2].append(it[1]())
                    except Exception as ex:
                        it[2].append(f"出错：{ex}")
                    it[3].set()
                elif it[0] == "seek":
                    _, sid, t, data = it
                    if sid == self.player._seek_id and not self.player.playing:
                        self.player.bg, self.player.t = data, t
                        self.player.show(data, t)
        except queue.Empty:
            pass
        self.after(30, self.poll)

    def click(self, e):
        self.fx.set_pos((round(e.x * self.res[0] / PW), round(e.y * self.res[1] / self.player.ph)))

    def typing(self):
        return isinstance(self.focus_get(), (tk.Text, tk.Entry, ttk.Entry, ttk.Spinbox, ttk.Combobox))

    def space(self, e):
        if not self.typing():
            self.player.toggle()

    def key_k(self, e):
        if not self.typing() and self.cur_tab() is self.ka:
            self.ka.tl.key_k()

    def cur_tab(self):
        return self.tabs[self.nb.index("current")] if self.tabs else None

    def tab_changed(self):
        t = self.cur_tab()
        for k, f in self.dock.items():
            if t is {"fx": self.fx, "kara": self.ka}[k]:
                f.pack(fill="both", expand=True, pady=(8, 0))
            else:
                f.pack_forget()

    def pick_fonts(self):
        d = filedialog.askdirectory(title="选字体文件夹（里面的字体不装进系统，只给工作台和 Aegisub 的预览用）",
                                    parent=self, initialdir=self.font_folder() or "")
        if not d:
            return
        d = os.path.abspath(d)
        self.settings["fonts_dir"] = d
        save_settings(self.settings)
        z.load_fonts(d)
        self._folder, self._fonts, self._face_ok = None, None, {}
        self.measure = z.Measure()
        if self._kara:
            self._kara.measure = z.Measure()
        self.player.vsf.doc = None
        self.fx.fonts_cb_update()
        self.fx.changed()
        self.ka.changed()
        messagebox.showinfo("字体文件夹",
                            "%s\n\n扫到 %d 个字体文件，能用上 %d 个家族。\n没装进系统，Aegisub 关掉就没了——"
                            "下次开工作台会自动再注册一遍。" % (d, len(z.font_files(d)),
                                                          len(self.folder_fonts())), parent=self)

    def apply(self):
        e = self.all_edits()
        fx = self.fx
        if fx.cat and (not self.job.get("catalog_saved") or fx.cat != self.job.get("catalog")
                       or fx.num != int(self.job.get("number") or 0)):
            e.info.update({"ZX_Catalog": fx.cat, "ZX_Number": str(fx.num)})
        if fx.cat:
            fx.lib.add_alias(self.job.get("video"), fx.cat)
        if e.empty():
            if not messagebox.askyesno("没有改动", "没有要应用的改动，直接关闭？", parent=self):
                return
        elif self.job.get("out"):
            e.write(self.job["out"])
        self.close()

    def close(self):
        self.player.stop()
        self.fx.save()
        self.ai.save_hist()
        self.destroy()


def main():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    job = json.load(open(sys.argv[sys.argv.index("--job") + 1], encoding="utf-8")) if "--job" in sys.argv else \
        {"vsfilter": os.path.join(os.path.dirname(HOME), "csri", "VSFilter.dll"), "aegisub_dir": os.path.dirname(HOME)}
    App(job).mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        msg = traceback.format_exc()
        with open(os.path.join(HOME, "fxedit.log"), "w", encoding="utf-8") as f:
            f.write(msg)
        tk.Tk().withdraw()
        messagebox.showerror("特效工作台出错", msg[-1500:] + "\n\n（完整报错在 fxedit.log，发给做插件的人）")
