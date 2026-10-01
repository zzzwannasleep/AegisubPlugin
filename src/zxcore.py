# Copyright (C) 2026 zzzwannasleep
# 原作者：zzzwannasleep（https://github.com/zzzwannasleep/AegisubPlugin）
# 授权：LGPL-3.0-or-later，条文见 LICENSE；出处与附加的署名要求见 NOTICE。
"""轴效工作台的底层：字幕数据（Lua 导出 / 改动写回）、VSFilter 渲染、视频音频片段、卡拉OK模板、自动 \\k。
不含界面，fxedit.py（界面）和 zxai.py（AI）都用它。"""
import ctypes, io, os, re, threading, wave

HOME = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------- 字幕数据
# Lua 导出（zhouxiao.lua 的 dump_subs）：一行一条，制表符分隔，字段里的 \ 换行 制表符 转义
STYLE_F = ["name", "fontname", "fontsize", "color1", "color2", "color3", "color4", "bold", "italic", "underline",
           "strikeout", "scale_x", "scale_y", "spacing", "angle", "borderstyle", "outline", "shadow", "align",
           "margin_l", "margin_r", "margin_t", "margin_b", "encoding"]
DIA_F = ["comment", "layer", "start_time", "end_time", "style", "actor", "margin_l", "margin_r", "margin_t",
         "margin_b", "effect", "text"]
BOOL_F = {"bold", "italic", "underline", "strikeout", "comment"}
STR_F = {"name", "fontname", "style", "actor", "effect", "text", "color1", "color2", "color3", "color4"}


def esc(s):
    return str(s).replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n")


def unesc(s):
    return re.sub(r"\\(.)", lambda m: {"t": "\t", "n": "\n"}.get(m.group(1), m.group(1)), s)


def _conv(k, v):
    if k in BOOL_F:
        return v in ("1", "true", True, 1)
    if k in STR_F:
        return v
    x = float(v)
    return int(x) if x == int(x) else x


def _out(k, v):
    if k in BOOL_F:
        return "1" if v else "0"
    return str(v)


class Doc:
    """Aegisub 字幕表的快照。rows[k] 对应 Lua 里 subs[k+1]"""

    def __init__(self, path=None):
        self.rows = []
        if path:
            for line in open(path, encoding="utf-8"):
                p = [unesc(x) for x in line.rstrip("\n").split("\t")]
                i, cls = int(p[0]), p[1]
                if cls == "info":
                    r = {"class": "info", "key": p[2], "value": p[3]}
                elif cls == "style":
                    r = {"class": "style", **{k: _conv(k, v) for k, v in zip(STYLE_F, p[2:])}}
                elif cls == "dialogue":
                    r = {"class": "dialogue", **{k: _conv(k, v) for k, v in zip(DIA_F, p[2:])}}
                else:
                    r = {"class": cls}
                r["i"] = i
                self.rows.append(r)

    def info(self):
        return {r["key"]: r["value"] for r in self.rows if r["class"] == "info"}

    def res(self):
        inf = self.info()
        return int(float(inf.get("PlayResX", 0) or 0)) or 1920, int(float(inf.get("PlayResY", 0) or 0)) or 1080

    def styles(self):
        return {r["name"]: r for r in self.rows if r["class"] == "style"}

    def by_i(self, i):
        return self.rows[i - 1]

    def dialogue(self):
        return [r for r in self.rows if r["class"] == "dialogue"]


class Edits:
    """待应用的改动；Lua 那边按行号从大到小执行，行号不会乱"""

    def __init__(self):
        self.sets, self.dels, self.ins, self.styles = {}, set(), {}, {}
        self.info = {}   # 字幕文件头（[Script Info]）要写的键值

    def set(self, i, **kw):
        self.sets.setdefault(i, {}).update(kw)

    def delete(self, i):
        self.dels.add(i)

    def insert_after(self, i, row):
        self.ins.setdefault(i, []).append({"class": "dialogue", **row})

    def upsert_style(self, st):
        self.styles[st["name"]] = dict(st)

    def empty(self):
        return not (self.sets or self.dels or self.ins or self.styles or self.info)

    def count(self):
        return len(self.sets) + len(self.dels) + sum(map(len, self.ins.values())) + len(self.styles)

    def merged(self, other):
        e = Edits()
        for src in (self, other):
            for i, kw in src.sets.items():
                e.set(i, **kw)
            e.dels |= src.dels
            for i, rows in src.ins.items():
                e.ins.setdefault(i, []).extend(rows)
            e.styles.update(src.styles)
            e.info.update(src.info)
        return e

    def view(self, doc):
        """改动后的样子（给预览用）：返回 (样式表, 事件行列表)，事件行带 'i'（原行号，新插的是 None）"""
        styles = {k: dict(v) for k, v in doc.styles().items()}
        styles.update({k: dict(v) for k, v in self.styles.items()})
        ev = []
        for r in doc.rows:
            i = r["i"]
            if r["class"] == "dialogue" and i not in self.dels:
                ev.append({**r, **self.sets.get(i, {})})
            for n in self.ins.get(i, []):
                ev.append({**n, "i": None})
        return styles, ev

    def write(self, path):
        out = []
        for k, v in self.info.items():
            out.append("\t".join(["info", esc(k), esc(v)]))
        for name, st in self.styles.items():
            st = {**st, "margin_b": st.get("margin_b", st.get("margin_t", 0))}
            out.append("\t".join(["style"] + [esc(ass_color(st.get(k, 0)) if k.startswith("color") else
                                                  _out(k, st.get(k, 0))) for k in STYLE_F]))
        for i, kw in self.sets.items():
            for k, v in kw.items():
                out.append("\t".join(["set", str(i), k, esc(_out(k, v))]))
        for i in self.dels:
            out.append(f"del\t{i}")
        for i, rows in self.ins.items():
            for r in rows:
                out.append("\t".join(["ins", str(i)] + [esc(_out(k, r.get(k, ""))) for k in DIA_F]))
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(out) + "\n")


def color_hex(c):
    """Aegisub 的 &HAABBGGRR& / &HBBGGRR& → AABBGGRR"""
    h = re.sub(r"[^0-9A-Fa-f]", "", str(c)[2:] if str(c).upper().startswith("&H") else str(c))
    return h.upper().rjust(8, "0")[-8:]


def ass_color(hex8):
    return "&H" + color_hex(hex8) + "&"


def ms2ass(ms):
    ms = max(0, int(ms) + 5) // 10 * 10   # 和 Aegisub 一样四舍五入到厘秒
    return "%d:%02d:%02d.%02d" % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms // 10 % 100)


def style_line(st):
    def v(k):
        x = st.get(k, 0)
        if k.startswith("color"):
            return "&H" + color_hex(x)
        if k in BOOL_F:
            return "-1" if x else "0"
        return str(x)
    keys = STYLE_F[:21] + ["margin_t", "encoding"]   # ASS 只有一个垂直边距
    return "Style: " + ",".join(v(k).replace(",", "，") if k in ("name", "fontname") else v(k) for k in keys)


def ass_doc(doc, styles, events, t0=None, t1=None):
    """拼一份给 VSFilter 的 ASS。只带 [t0, t1] 里的行（几十万行的字幕也不慢）"""
    inf = doc.info()
    head = ["[Script Info]", "ScriptType: v4.00+"]
    for k in ("PlayResX", "PlayResY", "WrapStyle", "ScaledBorderAndShadow", "YCbCr Matrix", "LayoutResX", "LayoutResY"):
        if k in inf:
            head.append(f"{k}: {inf[k]}")
    if "PlayResX" not in inf:
        head += ["PlayResX: 1920", "PlayResY: 1080"]
    out = head + ["", "[V4+ Styles]",
                  "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
                  "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
                  "Alignment, MarginL, MarginR, MarginV, Encoding"]
    out += [style_line(s) for s in styles.values()]
    out += ["", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    for e in events:
        if e.get("comment") or e.get("class") != "dialogue":
            continue
        if t0 is not None and (e["end_time"] < t0 or e["start_time"] > t1):
            continue
        out.append(f"Dialogue: {e['layer']},{ms2ass(e['start_time'])},{ms2ass(e['end_time'])},{e['style']},"
                   f"{e.get('actor', '')},{e.get('margin_l', 0)},{e.get('margin_r', 0)},{e.get('margin_t', 0)},"
                   f"{e.get('effect', '')},{e['text']}")
    return ("\n".join(out) + "\n").encode("utf-8")


# ---------------------------------------------------------------- 渲染：Aegisub 自带的 xy-VSFilter（CSRI 接口）
class _Fmt(ctypes.Structure):
    _fields_ = [("pixfmt", ctypes.c_int), ("w", ctypes.c_uint), ("h", ctypes.c_uint)]


class _Frame(ctypes.Structure):
    _fields_ = [("pixfmt", ctypes.c_int), ("planes", ctypes.c_void_p * 4), ("strides", ctypes.c_ssize_t * 4)]


class VSFilter:
    BGRX = 0x102

    def __init__(self, dll, w, h):
        d = self.d = ctypes.CDLL(dll)
        d.csri_renderer_default.restype = ctypes.c_void_p
        d.csri_open_mem.restype = ctypes.c_void_p
        d.csri_open_mem.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t, ctypes.c_void_p]
        d.csri_request_fmt.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Fmt)]
        d.csri_render.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Frame), ctypes.c_double]
        d.csri_close.argtypes = [ctypes.c_void_p]
        self.inst, self.doc = None, None
        self.resize(w, h)

    def resize(self, w, h):
        self.w, self.h = w, h
        self.buf = (ctypes.c_ubyte * (w * h * 4))()
        self.frame = _Frame(self.BGRX)
        self.frame.planes[0] = ctypes.addressof(self.buf)
        self.frame.strides[0] = w * 4
        self.doc = None

    def render(self, doc, bg, t):
        if doc != self.doc:
            if self.inst:
                self.d.csri_close(self.inst)
            self.inst = self.d.csri_open_mem(self.d.csri_renderer_default(), doc, len(doc), None)
            if self.inst:
                self.d.csri_request_fmt(self.inst, ctypes.byref(_Fmt(self.BGRX, self.w, self.h)))
            self.doc = doc
        ctypes.memmove(self.buf, bg, min(len(bg), len(self.buf)))
        if self.inst:
            self.d.csri_render(self.inst, ctypes.byref(self.frame), t)
        return bytes(self.buf)


def to_ppm(bgra, w, h):
    rgb = bytearray(w * h * 3)
    rgb[0::3], rgb[1::3], rgb[2::3] = bgra[2::4], bgra[1::4], bgra[0::4]
    return b"P6 %d %d 255\n" % (w, h) + bytes(rgb)


def to_png(bgra, w, h):
    """不靠 PIL 的 PNG 编码（发给 AI 看图用）"""
    import struct, zlib
    raw = bytearray()
    for y in range(h):
        row = bgra[y * w * 4:(y + 1) * w * 4]
        rgb = bytearray(w * 3)
        rgb[0::3], rgb[1::3], rgb[2::3] = row[2::4], row[1::4], row[0::4]
        raw += b"\0" + rgb

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + chunk(b"IEND", b""))


# ---------------------------------------------------------------- 视频 / 音频片段（PyAV）
class Video:
    """一段视频：按时间取帧（缩到预览宽度，BGRA），取一段音频成 wav"""

    def __init__(self, path, width):
        import av
        self.path, self.w = path, width
        with av.open(path) as c:
            s = c.streams.video[0]
            self.fps = float(s.average_rate or s.guessed_rate or 24000 / 1001)
            self.src_w, self.src_h = s.codec_context.width, s.codec_context.height
            self.duration = float(c.duration / 1e6) if c.duration else 0
            self.has_audio = bool(c.streams.audio)
        self.h = round(self.w * self.src_h / self.src_w / 2) * 2

    def _bgra(self, f):
        p = f.reformat(width=self.w, height=self.h, format="bgra").planes[0]
        data = bytes(p)
        if p.line_size != self.w * 4:
            data = b"".join(data[i * p.line_size:i * p.line_size + self.w * 4] for i in range(self.h))
        return data

    def frames(self, start, stop_flag):
        """从 start 秒起一帧帧解出来：生成 (秒, BGRA)"""
        import av
        with av.open(self.path) as c:
            s = c.streams.video[0]
            s.thread_type = "AUTO"
            c.seek(int(max(0, start - 1) / s.time_base), stream=s)
            for f in c.decode(s):
                if stop_flag():
                    return
                if f.time is None or f.time < start - 0.5 / self.fps:
                    continue
                yield f.time, self._bgra(f)

    def frame_at(self, t):
        for ft, data in self.frames(t, lambda: False):
            return ft, data
        return t, bytes(self.w * self.h * 4)

    def wav(self, t0, t1, path):
        """[t0, t1] 秒的音频 → 44.1k 立体声 wav 文件；没音轨返回 False"""
        import av
        if not self.has_audio:
            return False
        pcm = bytearray()
        with av.open(self.path) as c:
            s = c.streams.audio[0]
            c.seek(int(max(0, t0 - 1) / s.time_base), stream=s)
            rs = av.AudioResampler(format="s16", layout="stereo", rate=44100)
            first = None
            for fr in c.decode(s):
                if fr.time is not None and fr.time > t1:
                    break
                for o in rs.resample(fr):
                    if first is None:
                        first = fr.time or 0
                    pcm += bytes(o.planes[0])[:o.samples * 4]
        if first is None:
            return False
        cut = max(0, int((t0 - first) * 44100)) * 4
        pcm = pcm[cut:cut + int((t1 - t0) * 44100) * 4]
        with wave.open(path, "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(44100)
            w.writeframes(bytes(pcm))
        return True


def wav_slice(src, t, dst):
    """wav 从第 t 秒开始的部分另存（从中间开始播放用）"""
    with wave.open(src, "rb") as r:
        r.setpos(min(r.getnframes(), int(t * r.getframerate())))
        data = r.readframes(r.getnframes())
        params = r.getparams()
    with wave.open(dst, "wb") as w:
        w.setparams(params)
        w.writeframes(data)


class Sound:
    """winsound 只能异步放文件，不能异步放内存"""

    @staticmethod
    def play(path):
        import winsound
        winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)

    @staticmethod
    def stop():
        import winsound
        winsound.PlaySound(None, 0)


# ---------------------------------------------------------------- 字宽（和 Aegisub 的 text_extents 同一算法：GDI，字号放大 64 倍量）
class _LOGFONTW(ctypes.Structure):
    _fields_ = [("lfHeight", ctypes.c_long), ("lfWidth", ctypes.c_long), ("lfEscapement", ctypes.c_long),
                ("lfOrientation", ctypes.c_long), ("lfWeight", ctypes.c_long), ("lfItalic", ctypes.c_byte),
                ("lfUnderline", ctypes.c_byte), ("lfStrikeOut", ctypes.c_byte), ("lfCharSet", ctypes.c_byte),
                ("lfOutPrecision", ctypes.c_byte), ("lfClipPrecision", ctypes.c_byte), ("lfQuality", ctypes.c_byte),
                ("lfPitchAndFamily", ctypes.c_byte), ("lfFaceName", ctypes.c_wchar * 32)]


class _SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


class _TEXTMETRICW(ctypes.Structure):
    _fields_ = [(n, ctypes.c_long) for n in ("tmHeight", "tmAscent", "tmDescent", "tmInternalLeading",
                                             "tmExternalLeading", "tmAveCharWidth", "tmMaxCharWidth", "tmWeight",
                                             "tmOverhang", "tmDigitizedAspectX", "tmDigitizedAspectY")] + \
               [(n, ctypes.c_wchar) for n in ("tmFirstChar", "tmLastChar", "tmDefaultChar", "tmBreakChar")] + \
               [(n, ctypes.c_byte) for n in ("tmItalic", "tmUnderlined", "tmStruckOut", "tmPitchAndFamily",
                                             "tmCharSet")]


class Measure:
    def __init__(self):
        g = self.g = ctypes.windll.gdi32
        g.CreateCompatibleDC.restype = ctypes.c_void_p
        g.CreateFontIndirectW.restype = ctypes.c_void_p
        g.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        g.GetTextExtentPoint32W.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int, ctypes.POINTER(_SIZE)]
        g.GetTextMetricsW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_TEXTMETRICW)]
        g.SetMapMode.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self.dc = g.CreateCompatibleDC(None)
        g.SetMapMode(self.dc, 1)
        self.fonts, self.cache = {}, {}

    def extents(self, st, text):
        key = (st["fontname"], st["fontsize"], bool(st["bold"]), bool(st["italic"]), bool(st.get("underline")),
               bool(st.get("strikeout")), st.get("encoding", 1), st.get("spacing", 0), st.get("scale_x", 100),
               st.get("scale_y", 100), text)
        if key in self.cache:
            return self.cache[key]
        fk = key[:7]
        if fk not in self.fonts:
            lf = _LOGFONTW()
            lf.lfHeight = int(st["fontsize"] * 64)
            lf.lfWeight = 700 if st["bold"] else 400
            lf.lfItalic, lf.lfUnderline, lf.lfStrikeOut = bool(st["italic"]), fk[4], fk[5]
            lf.lfCharSet = int(st.get("encoding", 1)) & 0xff
            lf.lfOutPrecision, lf.lfClipPrecision, lf.lfQuality, lf.lfPitchAndFamily = 4, 0, 4, 0
            lf.lfFaceName = str(st["fontname"])[:31]
            self.fonts[fk] = self.g.CreateFontIndirectW(ctypes.byref(lf))
        self.g.SelectObject(self.dc, self.fonts[fk])
        sz, spacing = _SIZE(), float(st.get("spacing", 0)) * 64
        width = height = 0
        if spacing:
            for ch in text:
                self.g.GetTextExtentPoint32W(self.dc, ch, 1, ctypes.byref(sz))
                width += sz.cx + spacing
                height = sz.cy
        elif text:
            self.g.GetTextExtentPoint32W(self.dc, text, len(text), ctypes.byref(sz))
            width, height = sz.cx, sz.cy
        tm = _TEXTMETRICW()
        self.g.GetTextMetricsW(self.dc, ctypes.byref(tm))
        sx, sy = float(st.get("scale_x", 100)) / 100, float(st.get("scale_y", 100)) / 100
        r = (sx * width / 64, sy * height / 64, sy * tm.tmDescent / 64, sy * tm.tmExternalLeading / 64)
        self.cache[key] = r
        return r


# ---------------------------------------------------------------- 卡拉OK模板：直接跑 Aegisub 自带的 kara-templater.lua
# 它依赖的 aegisub.util / aegisub.unicode 是 MoonScript + C 写的，这里照原逻辑用纯 Lua 重写；
# parse_karaoke_data（C++）也照 Aegisub 的规则重写：第 0 个音节是第一个 \k 之前的内容
LUA_SHIM = r'''
local function U8(s, i) local c = s:byte(i) or 0
  if c < 0x80 then return 1 elseif c < 0xE0 then return 2 elseif c < 0xF0 then return 3 else return 4 end end
local unicode = {}
unicode.charwidth = function(s, i) return U8(s, i or 1) end
unicode.chars = function(s) local i = 1 return function() if i > #s then return end
  local w = U8(s, i); local c = s:sub(i, i + w - 1); local ci = i; i = i + w; return c, ci end end
unicode.len = function(s) local n = 0 for _ in unicode.chars(s) do n = n + 1 end return n end
unicode.codepoint = function(s) local c, w = s:byte(1), U8(s, 1)
  if w == 1 then return c end local cp = c % (2 ^ (7 - w))
  for k = 2, w do cp = cp * 64 + (s:byte(k) % 64) end return cp end
unicode.to_upper_case = string.upper
unicode.to_lower_case = string.lower
unicode.to_fold_case = string.lower
package.preload["aegisub.unicode"] = function() return unicode end

local util = {}
util.copy = function(t) local r = {} for k, v in pairs(t) do r[k] = v end return r end
util.deep_copy = function(tbl) local seen = {}
  local function cp(v) if type(v) ~= "table" then return v end if seen[v] then return seen[v] end
    local r = {} seen[v] = r for k, x in pairs(v) do r[k] = cp(x) end return r end
  return cp(tbl) end
util.ass_color = function(r, g, b) return string.format("&H%02X%02X%02X&", b, g, r) end
util.ass_alpha = function(a) return string.format("&H%02X&", a) end
util.ass_style_color = function(r, g, b, a) return string.format("&H%02X%02X%02X%02X", a, b, g, r) end
util.extract_color = function(s)
  local a, b, g, r = s:match("&H(%x%x)(%x%x)(%x%x)(%x%x)")
  if a then return tonumber(r, 16), tonumber(g, 16), tonumber(b, 16), tonumber(a, 16) end
  b, g, r = s:match("&H(%x%x)(%x%x)(%x%x)&")
  if b then return tonumber(r, 16), tonumber(g, 16), tonumber(b, 16), 0 end
  a = s:match("&H(%x%x)&")
  if a then return 0, 0, 0, tonumber(a, 16) end
  local r2, g2, b2, a2 = s:match("#(%x%x)(%x?%x?)(%x?%x?)(%x?%x?)")
  if r2 then return tonumber(r2, 16), tonumber(g2, 16) or 0, tonumber(b2, 16) or 0, tonumber(a2, 16) or 0 end
end
util.alpha_from_style = function(s) return util.ass_alpha(select(4, util.extract_color(s))) end
util.color_from_style = function(s) local r, g, b = util.extract_color(s) return util.ass_color(r or 0, g or 0, b or 0) end
util.clamp = function(v, lo, hi) if v < lo then return lo elseif v > hi then return hi else return v end end
util.HSV_to_RGB = function(H, S, V)
  local r, g, b = 0, 0, 0
  if S == 0 then r = util.clamp(V * 255, 0, 255) g = r b = r
  else H = math.abs(H) % 360 local Hi = math.floor(H / 60) local f = H / 60 - Hi
    local p, q, t = V * (1 - S), V * (1 - f * S), V * (1 - (1 - f) * S)
    local T = {{V, t, p}, {q, V, p}, {p, V, t}, {p, q, V}, {t, p, V}, {V, p, q}}
    r, g, b = T[Hi + 1][1] * 255, T[Hi + 1][2] * 255, T[Hi + 1][3] * 255 end
  return r, g, b end
util.HSL_to_RGB = function(H, S, L)
  local r, g, b
  H = math.abs(H) % 360 S = util.clamp(S, 0, 1) L = util.clamp(L, 0, 1)
  if S == 0 then r, g, b = L, L, L
  else local Q = L < 0.5 and L * (1 + S) or L + S - L * S local P = 2 * L - Q local Hk = H / 360
    local Tr, Tg, Tb
    if Hk < 1/3 then Tr, Tg, Tb = Hk + 1/3, Hk, Hk + 2/3 elseif Hk > 2/3 then Tr, Tg, Tb = Hk - 2/3, Hk, Hk - 1/3
    else Tr, Tg, Tb = Hk + 1/3, Hk, Hk - 1/3 end
    local function comp(T) if T < 1/6 then return P + (Q - P) * 6 * T elseif T < 1/2 then return Q
      elseif T < 2/3 then return P + (Q - P) * (2/3 - T) * 6 else return P end end
    r, g, b = comp(Tr), comp(Tg), comp(Tb) end
  return math.floor(r * 255 + 0.5), math.floor(g * 255 + 0.5), math.floor(b * 255 + 0.5) end
util.trim = function(s) return (s:gsub("^%s*(.-)%s*$", "%1")) end
util.headtail = function(s) local a, b, h, t = s:find("(.-)%s+(.*)") if a then return h, t else return s, "" end end
util.words = function(s) return function() if s == "" then return end local h, t = util.headtail(s) s = t return h end end
util.interpolate = function(p, lo, hi) if p <= 0 then return lo elseif p >= 1 then return hi else return p * (hi - lo) + lo end end
util.interpolate_color = function(p, a, b) local r1, g1, b1 = util.extract_color(a) local r2, g2, b2 = util.extract_color(b)
  return util.ass_color(util.interpolate(p, r1, r2), util.interpolate(p, g1, g2), util.interpolate(p, b1, b2)) end
util.interpolate_alpha = function(p, a, b)
  return util.ass_alpha(util.interpolate(p, select(4, util.extract_color(a)), select(4, util.extract_color(b)))) end
package.preload["aegisub.util"] = function() return util end

function include(name)
  for dir in string.gmatch(ZX_INCLUDE, "[^;]+") do
    local f = io.open(dir .. "/" .. name, "rb")
    if f then local src = f:read("*a") f:close()
      src = src:gsub("^\239\187\191", "")
      return assert(loadstring(src, "@" .. name))() end
  end
  error("include 找不到 " .. name)
end

local LOG = {}
math.mod = math.mod or math.fmod   -- 老模板（Aegisub 2.x 时代）用的 Lua 5.0 函数
aegisub = {
  lua_automation_version = 4,
  register_macro = function() end, register_filter = function() end,
  gettext = function(s) return s end,
  set_undo_point = function() end,
  cancel = function() error("aegisub.cancel") end,
  progress = {set = function() end, task = function() end, title = function() end, is_cancelled = function() return false end},
  debug = {out = function(level, fmt, ...)
    if type(level) ~= "number" then fmt, level = level, 0 end
    if level <= 2 then LOG[#LOG + 1] = string.format(fmt, ...) end end},
  log = function(...) aegisub.debug.out(...) end,
  video_size = function() return ZX_VW, ZX_VH end,   -- 当成开着和脚本分辨率一样的视频
  text_extents = function(st, text) return ZX_EXTENTS(st, text) end,
  ms_from_frame = function(f) return math.floor(f * 1000 / ZX_FPS + 0.5) end,
  frame_from_ms = function(ms) return math.floor(ms * ZX_FPS / 1000) end,
  decode_path = function(p) return p end,
}
function ZX_LOG() local s = table.concat(LOG) LOG = {} return s end

-- Aegisub 的 AssKaraoke：按 \k \K \kf \ko 切音节，第 0 个是第一个 \k 之前的内容（时长 0）
aegisub.parse_karaoke_data = function(line)
  local syls, cur, t = {}, {duration = 0, start_time = 0, end_time = 0, tag = "", text = "", text_stripped = ""}, 0
  local text = line.text
  local pos = 1
  local function push() syls[#syls + 1] = cur end
  while pos <= #text do
    local a, b, block = text:find("^{(.-)}", pos)
    if a then
      local rest, last = "", 1
      for s, tag, num, e in block:gmatch("()\\([kK][fo]?)(%d+)()") do
        rest = rest .. block:sub(last, s - 1)
        last = e
        if cur.text ~= "" or cur.duration > 0 or #syls > 0 or rest ~= "" then
          if rest ~= "" then cur.text = cur.text .. "{" .. rest .. "}" rest = "" end
          push()
        end
        local d = tonumber(num) * 10
        cur = {duration = d, start_time = t, end_time = t + d, tag = tag, text = "", text_stripped = ""}
        t = t + d
      end
      rest = rest .. block:sub(last)
      if rest ~= "" then cur.text = cur.text .. "{" .. rest .. "}" end
      pos = b + 1
    else
      local c = text:match("^[^{]+", pos)
      cur.text = cur.text .. c
      cur.text_stripped = cur.text_stripped .. c
      pos = pos + #c
    end
  end
  push()
  local out = {}
  if syls[1].duration == 0 and syls[1].tag == "" then
    for k = 1, #syls do out[k - 1] = syls[k] end
  else
    out[0] = {duration = 0, start_time = 0, end_time = 0, tag = "", text = "", text_stripped = ""}
    for k = 1, #syls do out[k] = syls[k] end
  end
  return out
end

-- Aegisub 的 LuaJIT 开了 5.2 兼容，ipairs 认 __ipairs（karaskel 用 ipairs(subs)）
local raw_ipairs = ipairs
function ipairs(t)
  local mt = type(t) == "userdata" and getmetatable(t)
  if mt and mt.__ipairs then return mt.__ipairs(t) end
  return raw_ipairs(t)
end

-- 假的 subs：Aegisub 里是 userdata，LuaJIT 只对 userdata 认 __len
function ZX_SUBS(rows, resx, resy)
  local t = rows
  local s = newproxy(true)
  local mt = getmetatable(s)
  mt.__len = function() return #t end
  mt.__ipairs = function(u) local i = 0 return function() i = i + 1 if t[i] then return i, u[i] end end, u, 0 end
  mt.__index = function(_, k)
    if k == "insert" then return function(i, ...) for n, l in ipairs({...}) do table.insert(t, i + n - 1, l) end end end
    if k == "delete" then return function(...)
      local idx = {...} if type(idx[1]) == "table" then idx = idx[1] end
      table.sort(idx, function(a, b) return a > b end)
      for _, i in ipairs(idx) do table.remove(t, i) end end end
    if k == "deleterange" then return function(a, b) for i = b, a, -1 do table.remove(t, i) end end end
    if k == "append" then return function(...) for _, l in ipairs({...}) do t[#t + 1] = l end end end
    if k == "script_resolution" then return function() return resx, resy end end
    local l = t[k]
    if l == nil then return nil end
    local c = {} for a, b in pairs(l) do c[a] = b end return c
  end
  mt.__newindex = function(_, k, v)
    if k < 0 then table.insert(t, -k, v) elseif k == 0 then t[#t + 1] = v else t[k] = v end
  end
  return s, t
end
'''


class Kara:
    """在 Python 里跑 Aegisub 的 kara-templater.lua：模板行 + 带 \\k 的歌词行 → 生成的 fx 行"""

    def __init__(self, aegisub_dir, fps=24000 / 1001):
        from lupa.luajit21 import LuaRuntime
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.measure = Measure()
        g = self.lua.globals()
        inc = [os.path.join(aegisub_dir, "automation", "include"), os.path.join(aegisub_dir, "automation", "autoload")]
        g.ZX_INCLUDE = ";".join(p.replace("\\", "/") for p in inc)
        g.ZX_FPS = fps
        g.ZX_EXTENTS = lambda st, text: self.measure.extents(
            {k: st[k] for k in ("fontname", "fontsize", "bold", "italic", "underline", "strikeout", "encoding",
                                "spacing", "scale_x", "scale_y")}, text or "")
        self.lua.execute(LUA_SHIM)
        src = open(os.path.join(aegisub_dir, "automation", "autoload", "kara-templater.lua"), encoding="utf-8-sig").read()
        self.lua.execute(src)

    def _lua_row(self, r):
        d = {k: v for k, v in r.items() if k != "i"}
        d["section"] = {"info": "[Script Info]", "style": "[V4+ Styles]"}.get(r["class"], "[Events]")
        if r["class"] == "style":
            d["color1"], d["color2"], d["color3"], d["color4"] = (ass_color(d[k]) for k in ("color1", "color2", "color3", "color4"))
            d.setdefault("margin_b", d.get("margin_t", 0))
            d["relative_to"] = 2
        if r["class"] == "dialogue":
            d.setdefault("margin_b", d.get("margin_t", 0))
            d["extra"] = self.lua.table()
        t = self.lua.table_from(d)
        return t

    def run(self, info, styles, templates, lines, res):
        """templates / lines：dialogue 行（dict）。lines 里带 'zi'（原文件行号）。
        返回 [(zi, 源行改成的样子, [生成的 fx 行...])]，和 kara-templater 的报错输出"""
        rows = [{"class": "info", "key": k, "value": v} for k, v in info.items()]
        rows += list(styles.values()) + list(templates) + list(lines)
        lt = self.lua.table_from([self._lua_row(r) for r in rows])
        for k, r in enumerate(rows):
            if "zi" in r:
                lt[k + 1]["zi"] = r["zi"]
        g = self.lua.globals()
        g.ZX_VW, g.ZX_VH = res[0], res[1]
        subs, back = g.ZX_SUBS(lt, res[0], res[1])
        try:
            self.lua.globals().filter_apply_templates(subs, self.lua.table())
        except Exception as ex:   # 模板表达式出错时 kara-templater 先把原因写进日志再 cancel，报原因
            raise RuntimeError(self.lua.globals().ZX_LOG().strip() or str(ex)) from None
        out, cur = {}, None
        for k in range(1, len(back) + 1):
            l = back[k]
            if l["class"] != "dialogue":
                continue
            zi = l["zi"]
            py = {f: (l[f] if l[f] is not None else "") for f in DIA_F}
            py["comment"] = bool(py["comment"])
            if zi is None:
                continue
            if l["effect"] == "fx":
                out.setdefault(zi, [None, []])[1].append(py)
            else:
                out.setdefault(zi, [None, []])[0] = py
        return [(zi, v[0], v[1]) for zi, v in out.items()], self.lua.globals().ZX_LOG()


def template_rows(rows):
    """ASS 里的模板行：注释行，特效栏以 template / code / mixin 开头"""
    return [r for r in rows if r.get("comment") and re.match(r"\s*(template|code|mixin)\b", r.get("effect", ""), re.I)]


def parse_ass(text):
    """读一份 .ass 文件（社区模板用）：→ (info, styles, dialogue 行)"""
    info, styles, rows, fmt = {}, {}, [], None
    sec = ""
    for line in text.splitlines():
        line = line.strip("\ufeff")
        if line.startswith("["):
            sec = line.strip().lower()
            continue
        if sec == "[script info]" and ":" in line and not line.startswith(";"):
            k, v = line.split(":", 1)
            info[k.strip()] = v.strip()
        elif line.startswith("Style:"):
            p = [x.strip() for x in line[6:].split(",")]
            if len(p) >= 23:
                keys = STYLE_F[:21] + ["margin_t", "encoding"]
                st = {"class": "style"}
                for k, v in zip(keys, p):
                    if k.startswith("color"):
                        st[k] = color_hex(v)
                    elif k in BOOL_F:
                        st[k] = v not in ("0", "")
                    elif k in ("name", "fontname"):
                        st[k] = v
                    else:
                        try:
                            x = float(v)
                            st[k] = int(x) if x == int(x) else x
                        except ValueError:
                            st[k] = 0
                st["margin_b"] = st["margin_t"]
                styles[st["name"]] = st
        elif line.startswith(("Dialogue:", "Comment:")):
            com = line.startswith("Comment:")
            p = line.split(":", 1)[1].split(",", 9)
            if len(p) < 10:
                continue
            def t2ms(s):
                h, m, x = s.strip().split(":")
                return round((int(h) * 3600 + int(m) * 60 + float(x)) * 1000)
            try:
                rows.append({"class": "dialogue", "comment": com, "layer": int(p[0].strip() or 0),
                             "start_time": t2ms(p[1]), "end_time": t2ms(p[2]), "style": p[3].strip(),
                             "actor": p[4], "margin_l": int(p[5] or 0), "margin_r": int(p[6] or 0),
                             "margin_t": int(p[7] or 0), "margin_b": int(p[7] or 0), "effect": p[8], "text": p[9]})
            except ValueError:
                continue
    return info, styles, rows


# ---------------------------------------------------------------- 自动 \k
_SMALL = set("ゃゅょぁぃぅぇぉゎャュョァィゥェォヮ")


def syllables(text):
    """一句歌词切成音节：汉字 / 假名一个字一个（小写的ゃゅょ并进前一个），英文按词，空格和标点跟着前一个"""
    out = []
    for m in re.finditer(r"[A-Za-z0-9'’\-]+|.", text):
        s = m.group(0)
        if out and (s in _SMALL or re.fullmatch(r"[\s、。，．,.!！?？…~～「」『』（）()・]+", s)):
            out[-1] += s
        else:
            out.append(s)
    return out


def _weight(s):
    if re.match(r"[A-Za-z]", s):
        return max(1, len(re.findall(r"[aeiouyAEIOUY]+", s)))
    return 1


def strip_k(text):
    """去掉 \\k 类标签（重新打时间前）"""
    text = re.sub(r"\\[kK][fo]?\d+", "", text)
    return re.sub(r"\{\}", "", text)


def auto_k(text, dur_ms, starts=None, tag="k", syls=None):
    """给一句打 \\k。starts=None：按字均分（英文单词按音节数给权重）；
    starts=[每个音节开口的毫秒（相对行开头）]：按实际唱的时间（第一个字前的空白单独一个空音节）；
    syls：自己定的切法（拆开 / 合并过的音节，拼起来要等于去掉标签的正文；空字符串 = 同一个字多唱一拍）"""
    text = strip_k(text)
    lead = re.match(r"^((?:\{[^}]*\})*)", text).group(1)
    body = re.sub(r"\{[^}]*\}", "", text[len(lead):])
    if syls is None or "".join(syls) != body:
        syls = syllables(body)
    if not syls:
        return text
    total = max(1, round(dur_ms / 10))
    if starts is None:
        w = [_weight(s) for s in syls]
        acc, cs, prev = 0, [], 0
        for x in w:
            acc += x
            cur = round(total * acc / sum(w))
            cs.append(cur - prev)
            prev = cur
        pre = 0
    else:
        b = [max(0, min(total, round(x / 10))) for x in starts] + [total]
        for k in range(1, len(b)):
            b[k] = max(b[k], b[k - 1])
        pre = b[0]
        cs = [b[k + 1] - b[k] for k in range(len(syls))]
    out = lead + ("{\\%s%d}" % (tag, pre) if pre > 0 else "")
    return out + "".join("{\\%s%d}%s" % (tag, c, s) for s, c in zip(syls, cs))


def k_starts(text, dur_ms):
    r"""一句的音节和每个音节开口的毫秒（相对行开头）。带 \k 的按原来的切法和时间，没有的按字切、均分。
    第一个 \k 前的空拍算进开头的空白，中间没字的 \k 是「同一个字多唱一拍」，留成空音节"""
    if not re.search(r"\\[kK][fo]?\d", text):
        text = auto_k(text, dur_ms)
    syls, starts, t = [], [], 0
    for m in re.finditer(r"\{([^}]*)\}|([^{]+)", text):
        if m.group(1) is not None:
            for k in re.findall(r"\\[kK][fo]?(\d+)", m.group(1)):
                syls.append("")
                starts.append(t)
                t += int(k) * 10
        elif syls:
            syls[-1] += m.group(2)
        elif m.group(2):
            syls, starts = [m.group(2)], [0]   # 第一个 \k 前就有字
    while len(syls) > 1 and syls[0] == "":   # 开头的空拍
        syls.pop(0)
        starts.pop(0)
    return syls, starts


def wav_peaks(path, t0, t1, n):
    """wav 里 [t0, t1] 秒（相对文件开头）分成 n 格，每格的最大振幅 0~1（画波形用）"""
    import array
    with wave.open(path, "rb") as r:
        sr, ch = r.getframerate(), r.getnchannels()
        a, b = max(0, int(t0 * sr)), min(r.getnframes(), int(t1 * sr))
        if b <= a:
            return [0.0] * n
        r.setpos(a)
        x = array.array("h", r.readframes(b - a))
    out, step = [], (t1 - t0) * sr * ch / n
    for k in range(n):
        lo, hi = int(k * step + (t0 * sr - a) * ch), int((k + 1) * step + (t0 * sr - a) * ch)
        seg = x[max(0, lo):max(0, hi)]
        out.append(max(map(abs, seg[::4] or [0])) / 32768)
    return out


def wav_cut(src, t0, t1, dst):
    """wav 的 [t0, t1] 秒另存（单独听一个音节）"""
    with wave.open(src, "rb") as r:
        sr = r.getframerate()
        r.setpos(min(r.getnframes(), max(0, int(t0 * sr))))
        data = r.readframes(max(0, int((t1 - t0) * sr)))
        params = r.getparams()
    with wave.open(dst, "wb") as w:
        w.setparams(params)
        w.writeframes(data)


def load_fonts(folder):
    """文件夹里的字体只给本进程用（FR_PRIVATE，不装进系统）：预览和量字宽都能用上字体包"""
    n = 0
    if folder and os.path.isdir(folder):
        for root, _, files in os.walk(folder):
            for f in files:
                if f.lower().endswith((".ttf", ".otf", ".ttc", ".otc")):
                    n += ctypes.windll.gdi32.AddFontResourceExW(os.path.join(root, f), 0x10, None) > 0
    return n
