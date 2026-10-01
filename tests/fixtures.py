"""测试夹具：合成一份字幕表 / 一份 .ass / 一份工作台导出（fx_dump.tsv）。

原来测试依赖无职 08 的真实导出和一份社区模板；这里给出等价的合成版本，
让测试不绑死在某一部番上（真实素材仍然可以用环境变量指）。
"""
import os
import sys

import bootstrap  # noqa: F401  （放好 sys.path）
import testconfig as C  # noqa: E402

DEFAULT_STYLE = {"name": "Default", "fontname": "Arial", "fontsize": 48, "color1": "&H00FFFFFF&",
                 "color2": "&H000000FF&", "color3": "&H00000000&", "color4": "&H00000000&", "bold": False,
                 "italic": False, "underline": False, "strikeout": False, "scale_x": 100, "scale_y": 100,
                 "spacing": 0, "angle": 0, "borderstyle": 1, "outline": 2, "shadow": 2, "align": 2,
                 "margin_l": 10, "margin_r": 10, "margin_t": 10, "margin_b": 10, "encoding": 1}

# 工作台页面上要用的几个样式（和「轴效起步」样式库同名，特效预设按名字找）
EXTRA_STYLES = [
    {"name": "Screen", "fontname": "Microsoft YaHei", "fontsize": 64, "color1": "&H00FFFFFF&",
     "color2": "&H000000FF&", "color3": "&H00000000&", "color4": "&H80000000", "bold": False, "italic": False,
     "underline": False, "strikeout": False, "scale_x": 100, "scale_y": 100, "spacing": 0, "angle": 0,
     "borderstyle": 1, "outline": 3, "shadow": 0, "align": 5, "margin_l": 10, "margin_r": 10,
     "margin_t": 10, "margin_b": 10, "encoding": 1},
    {"name": "Text CN", "fontname": "Microsoft YaHei", "fontsize": 58, "color1": "&H00FFFFFF&",
     "color2": "&H000000FF&", "color3": "&H00202020&", "color4": "&H80000000", "bold": False, "italic": False,
     "underline": False, "strikeout": False, "scale_x": 100, "scale_y": 100, "spacing": 0, "angle": 0,
     "borderstyle": 1, "outline": 2, "shadow": 0, "align": 2, "margin_l": 10, "margin_r": 10,
     "margin_t": 32, "margin_b": 32, "encoding": 1},
    {"name": "Text JP", "fontname": "Yu Gothic", "fontsize": 44, "color1": "&H00FFFFFF&",
     "color2": "&H000000FF&", "color3": "&H00202020&", "color4": "&H80000000", "bold": False, "italic": False,
     "underline": False, "strikeout": False, "scale_x": 100, "scale_y": 100, "spacing": 0, "angle": 0,
     "borderstyle": 1, "outline": 2, "shadow": 0, "align": 2, "margin_l": 10, "margin_r": 10,
     "margin_t": 10, "margin_b": 10, "encoding": 1},
    {"name": "OP CN", "fontname": "Microsoft YaHei", "fontsize": 56, "color1": "&H00FFFFFF&",
     "color2": "&H000000FF&", "color3": "&H00A05020&", "color4": "&H80000000", "bold": True, "italic": False,
     "underline": False, "strikeout": False, "scale_x": 100, "scale_y": 100, "spacing": 0, "angle": 0,
     "borderstyle": 1, "outline": 2, "shadow": 0, "align": 2, "margin_l": 10, "margin_r": 10,
     "margin_t": 32, "margin_b": 32, "encoding": 1},
    {"name": "OP JP", "fontname": "Yu Gothic", "fontsize": 48, "color1": "&H00FFFFFF&",
     "color2": "&H000000FF&", "color3": "&H00A05020&", "color4": "&H80000000", "bold": True, "italic": False,
     "underline": False, "strikeout": False, "scale_x": 100, "scale_y": 100, "spacing": 0, "angle": 0,
     "borderstyle": 1, "outline": 2, "shadow": 0, "align": 8, "margin_l": 10, "margin_r": 10,
     "margin_t": 32, "margin_b": 32, "encoding": 1},
    {"name": "ED CN", "fontname": "Microsoft YaHei", "fontsize": 56, "color1": "&H00FFFFFF&",
     "color2": "&H000000FF&", "color3": "&H00403020&", "color4": "&H80000000", "bold": False, "italic": False,
     "underline": False, "strikeout": False, "scale_x": 100, "scale_y": 100, "spacing": 0, "angle": 0,
     "borderstyle": 1, "outline": 2, "shadow": 0, "align": 2, "margin_l": 10, "margin_r": 10,
     "margin_t": 32, "margin_b": 32, "encoding": 1},
    {"name": "ED JP", "fontname": "Yu Gothic", "fontsize": 46, "color1": "&H00FFFFFF&",
     "color2": "&H000000FF&", "color3": "&H00403020&", "color4": "&H80000000", "bold": False, "italic": False,
     "underline": False, "strikeout": False, "scale_x": 100, "scale_y": 100, "spacing": 0, "angle": 0,
     "borderstyle": 1, "outline": 2, "shadow": 0, "align": 8, "margin_l": 10, "margin_r": 10,
     "margin_t": 32, "margin_b": 32, "encoding": 1},
]
ALL_STYLES = [DEFAULT_STYLE] + EXTRA_STYLES


def row(text, style="Text CN", start=1000, end=3000, layer=0, effect="", comment=False, actor="",
        margin_l=0, margin_r=0, margin_t=0, margin_b=0):
    return {"class": "dialogue", "comment": comment, "layer": layer, "start_time": start, "end_time": end,
            "style": style, "actor": actor, "margin_l": margin_l, "margin_r": margin_r,
            "margin_t": margin_t, "margin_b": margin_b, "effect": effect, "text": text}


def sub(text, style, start, end, effect="karaoke", comment=False, layer=0):
    """一行歌词（源行）"""
    return row(text, style=style, start=start, end=end, layer=layer, effect=effect, comment=comment)


def template(effect, text, layer=0):
    """模板行（Comment，effect 是 template ... / code ...）"""
    return row(text, style="Default", start=0, end=0, layer=layer, effect=effect, comment=True)


def styles(extra=ALL_STYLES):
    return [dict(s) for s in extra]


def full_doc():
    """一份够工作台三页都跑得动的字幕：屏字 + 对白 + OP 歌词"""
    rows = [
        row(r"{\pos(300,900)\blur5\an7}旧屏字", style="Screen", start=1000, end=4000, layer=3),
        row(r"{\fad(200,200)}这是对白第一句", style="Text CN", start=5000, end=8000),
        row(r"{\fad(200,200)}これが最初のセリフ", style="Text JP", start=5000, end=8000, layer=1),
        sub(r"{\k71}Na{\k27}n{\k26}do {\k20}mo {\k21}ta{\k17}chi{\k32}mu{\k35}ka{\k27}i",
            "OP JP", 90540, 130100),
        sub(r"{\k50}な{\k50}ん{\k50}ど{\k50}も", "OP CN", 90540, 130100),
    ]
    return rows


# ---------------------------------------------------------------- 写文件
def esc(s):
    return str(s).replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n")


# 布尔字段落盘必须是 1/0：zxcore._conv 只认 "1" / "true"，str(True)="True" 会被当成假
_BOOL_F = {"bold", "italic", "underline", "strikeout", "comment"}


def _field(name, value):
    if name in _BOOL_F:
        return "1" if value in (True, 1, "1", "true") else "0"
    return esc(value)


def write_dump(path, rows, style_rows=None, info=None):
    """写工作台的导出格式（fx_dump.tsv）：i, class, 各字段；Lua 的 dump_subs 就是这个"""
    if "zxcore" in sys.modules:
        import zxcore as z
        sf, df = z.STYLE_F, z.DIA_F
    else:
        sf = ["name", "fontname", "fontsize", "color1", "color2", "color3", "color4", "bold", "italic",
              "underline", "strikeout", "scale_x", "scale_y", "spacing", "angle", "borderstyle", "outline",
              "shadow", "align", "margin_l", "margin_r", "margin_t", "margin_b", "encoding"]
        df = ["comment", "layer", "start_time", "end_time", "style", "actor", "margin_l", "margin_r",
              "margin_t", "margin_b", "effect", "text"]
    out, i = [], 0
    for k, v in (info or {"PlayResX": "1920", "PlayResY": "1080"}).items():
        i += 1
        out.append("\t".join([str(i), "info", esc(k), esc(v)]))
    for st in (style_rows if style_rows is not None else styles()):
        i += 1
        out.append("\t".join([str(i), "style"] + [_field(f, st[f]) for f in sf]))
    for r in rows:
        i += 1
        out.append("\t".join([str(i), "dialogue"] + [_field(f, r.get(f, "")) for f in df]))
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out) + "\n")
    return path


_ASS_STYLE_FMT = ("Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
                  "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
                  "Alignment, MarginL, MarginR, MarginV, Encoding")
_ASS_EVENT_FMT = "Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
_STYLE_ORDER = ["name", "fontname", "fontsize", "color1", "color2", "color3", "color4", "bold", "italic",
                "underline", "strikeout", "scale_x", "scale_y", "spacing", "angle", "borderstyle", "outline",
                "shadow", "align", "margin_l", "margin_r", "margin_t", "encoding"]


def ass_time(ms):
    cs = max(0, int(round(ms / 10)))
    return "%d:%02d:%02d.%02d" % (cs // 360000, cs // 6000 % 60, cs // 100 % 60, cs % 100)


def build_ass(rows, style_rows=None, info=None, extra_raw=None):
    """拼一份能读回来（parse_ass）的 .ass；rows 里可以混「原始 Dialogue: 行」字符串"""
    head = ["[Script Info]", "; 合成的测试文件", "ScriptType: v4.00+", "WrapStyle: 0"]
    for k, v in (info or {"PlayResX": "1920", "PlayResY": "1080", "ScaledBorderAndShadow": "yes"}).items():
        head.append("%s: %s" % (k, v))
    out = head + ["", "[V4+ Styles]", "Format: " + _ASS_STYLE_FMT]
    for st in (style_rows if style_rows is not None else styles()):
        v = []
        for f in _STYLE_ORDER:
            x = st.get(f, 0)
            if f in ("bold", "italic", "underline", "strikeout"):
                x = -1 if x else 0
            elif f == "margin_t":
                x = st.get("margin_t", 0)
            v.append(str(x))
        out.append("Style: " + ",".join(v))
    if extra_raw:
        out += extra_raw
    out += ["", "[Events]", "Format: " + _ASS_EVENT_FMT]
    for r in rows:
        if isinstance(r, str):
            out.append(r)
            continue
        name = "Comment" if r.get("comment") else "Dialogue"
        text = str(r.get("text", "")).replace("\n", "\\N")
        out.append("%s: %d,%s,%s,%s,%s,%04d,%04d,%04d,%s,%s" % (
            name, r.get("layer", 0), ass_time(r.get("start_time", 0)), ass_time(r.get("end_time", 0)),
            r.get("style", "Default"), r.get("actor", ""), r.get("margin_l", 0), r.get("margin_r", 0),
            r.get("margin_t", 0), r.get("effect", ""), text))
    return "\n".join(out) + "\n"


def write_doc(name, rows=None, style_rows=None, info=None, extra_raw=None):
    """把合成字幕写成 .ass 放到 fixtures/generated/ 下，返回路径"""
    p = C.gen(name)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(build_ass(rows if rows is not None else full_doc(), style_rows, info, extra_raw))
    return p


def write_dump_file(name, rows=None, style_rows=None, info=None):
    p = C.gen(name)
    write_dump(p, rows if rows is not None else full_doc(), style_rows, info)
    return p


if __name__ == "__main__":
    print(write_doc("probe.ass"))
    print(write_dump_file("probe_dump.tsv"))
    import zxcore as z
    doc = z.Doc(C.gen("probe_dump.tsv"))
    info, st, rows = z.parse_ass(C.read(C.gen("probe.ass")))
    print("dump:", len(doc.rows), "行；ass:", len(rows), "行，样式", sorted(st)[:3], "info PlayResX", info.get("PlayResX"))
    print("对话框行：", [(r["style"], r["effect"], r["text"][:20]) for r in doc.dialogue()])
