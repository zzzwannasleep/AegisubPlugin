# Copyright (C) 2026 zzzwannasleep
# 原作者：zzzwannasleep（https://github.com/zzzwannasleep/AegisubPlugin）
# 授权：LGPL-3.0-or-later，条文见 LICENSE；出处与附加的署名要求见 NOTICE。
"""AI 字幕助手：OpenAI 兼容协议 / Anthropic 协议，流式输出 + 工具调用。
只用标准库（urllib），走系统代理设置。Key 存在组件目录的 ai.json，只在本机。"""
import base64, json, os, urllib.request

HOME = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.join(HOME, "ai.json")


def load_conf():
    try:
        return json.load(open(CONF, encoding="utf-8"))
    except (OSError, ValueError):
        return {"protocol": "openai", "base_url": "https://api.openai.com/v1", "key": "", "model": ""}


def save_conf(c):
    with open(CONF, "w", encoding="utf-8") as f:
        json.dump(c, f, ensure_ascii=False, indent=1)


class Stopped(Exception):
    pass


def _sse(resp, stop):
    """一行行读 SSE：生成 (event, data dict)"""
    event = None
    for raw in resp:
        if stop():
            raise Stopped()
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data = line[5:].strip()
            if data == "[DONE]":
                return
            try:
                yield event, json.loads(data)
            except ValueError:
                pass
        elif not line:
            event = None


def _post(url, headers, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"content-type": "application/json", **headers})
    try:
        return urllib.request.urlopen(req, timeout=300)
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", "replace")[:800]
        raise RuntimeError(f"接口返回 {e.code}：{msg}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"连不上 {url}：{e.reason}（检查 Base URL、网络或代理）") from None


# 内部统一的消息格式（接近 Anthropic）：
# {"role": "user"|"assistant", "content": [{"type": "text", "text"}, {"type": "image", "png": bytes},
#   {"type": "tool_use", "id", "name", "input"}, {"type": "tool_result", "id", "content": str, "png": bytes|None}]}
class Client:
    def __init__(self, conf):
        self.c = conf

    def chat(self, system, messages, tools, on_text, stop):
        """发一轮，流式回调 on_text(片段)；返回助手这一轮的 content 列表"""
        if not self.c.get("key") or not self.c.get("model"):
            raise RuntimeError("先在上面填 Base URL、Key、模型，点「保存」")
        if self.c.get("protocol") == "anthropic":
            return self._anthropic(system, messages, tools, on_text, stop)
        return self._openai(system, messages, tools, on_text, stop)

    # ---------------- OpenAI 兼容（/chat/completions）
    def _openai(self, system, messages, tools, on_text, stop):
        base = self.c["base_url"].rstrip("/")
        url = base if base.endswith("/chat/completions") else base + "/chat/completions"
        msgs = [{"role": "system", "content": system}]
        for m in messages:
            if m["role"] == "assistant":
                text = "".join(b["text"] for b in m["content"] if b["type"] == "text")
                calls = [{"id": b["id"], "type": "function",
                          "function": {"name": b["name"], "arguments": json.dumps(b["input"], ensure_ascii=False)}}
                         for b in m["content"] if b["type"] == "tool_use"]
                d = {"role": "assistant", "content": text or None}
                if calls:
                    d["tool_calls"] = calls
                msgs.append(d)
                continue
            parts, imgs = [], []
            for b in m["content"]:
                if b["type"] == "tool_result":
                    msgs.append({"role": "tool", "tool_call_id": b["id"], "content": b["content"]})
                    if b.get("png"):
                        imgs.append(b["png"])
                elif b["type"] == "text":
                    parts.append({"type": "text", "text": b["text"]})
                elif b["type"] == "image":
                    imgs.append(b["png"])
            parts += [{"type": "image_url", "image_url": {"url": "data:image/png;base64," +
                                                           base64.b64encode(p).decode()}} for p in imgs]
            if parts:   # 工具结果里的图 OpenAI 协议放不进 tool 消息，跟一条 user 消息发
                msgs.append({"role": "user", "content": parts if imgs else "".join(p["text"] for p in parts)})
        body = {"model": self.c["model"], "messages": msgs, "stream": True}
        if tools:
            body["tools"] = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                               "parameters": t["schema"]}} for t in tools]
        resp = _post(url, {"authorization": "Bearer " + self.c["key"]}, body)
        text, calls = "", {}
        with resp:
            for _, d in _sse(resp, stop):
                for ch in d.get("choices") or []:
                    delta = ch.get("delta") or {}
                    if delta.get("content"):
                        text += delta["content"]
                        on_text(delta["content"])
                    for tc in delta.get("tool_calls") or []:
                        c = calls.setdefault(tc.get("index", 0), {"id": "", "name": "", "args": ""})
                        c["id"] = tc.get("id") or c["id"]
                        fn = tc.get("function") or {}
                        c["name"] += fn.get("name") or ""
                        c["args"] += fn.get("arguments") or ""
        out = [{"type": "text", "text": text}] if text else []
        for k in sorted(calls):
            c = calls[k]
            try:
                args = json.loads(c["args"] or "{}")
            except ValueError:
                args = {"_bad_json": c["args"]}
            out.append({"type": "tool_use", "id": c["id"] or f"call_{k}", "name": c["name"], "input": args})
        return out

    # ---------------- Anthropic（/v1/messages）
    def _anthropic(self, system, messages, tools, on_text, stop):
        base = self.c["base_url"].rstrip("/")
        url = base if base.endswith("/messages") else (base + "/messages" if base.endswith("/v1") else base + "/v1/messages")
        msgs = []
        for m in messages:
            blocks = []
            for b in m["content"]:
                if b["type"] == "text":
                    if b["text"]:
                        blocks.append({"type": "text", "text": b["text"]})
                elif b["type"] == "image":
                    blocks.append({"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                               "data": base64.b64encode(b["png"]).decode()}})
                elif b["type"] == "tool_use":
                    blocks.append({"type": "tool_use", "id": b["id"], "name": b["name"], "input": b["input"]})
                elif b["type"] == "tool_result":
                    content = [{"type": "text", "text": b["content"]}]
                    if b.get("png"):
                        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                                    "data": base64.b64encode(b["png"]).decode()}})
                    blocks.append({"type": "tool_result", "tool_use_id": b["id"], "content": content})
            msgs.append({"role": m["role"], "content": blocks})
        body = {"model": self.c["model"], "max_tokens": 8192, "system": system, "messages": msgs, "stream": True}
        if tools:
            body["tools"] = [{"name": t["name"], "description": t["description"], "input_schema": t["schema"]}
                             for t in tools]
        resp = _post(url, {"x-api-key": self.c["key"], "authorization": "Bearer " + self.c["key"],
                           "anthropic-version": "2023-06-01"}, body)
        out, cur = [], None
        with resp:
            for ev, d in _sse(resp, stop):
                t = d.get("type") or ev
                if t == "content_block_start":
                    cb = d["content_block"]
                    cur = {"type": "text", "text": ""} if cb["type"] == "text" else \
                        {"type": "tool_use", "id": cb.get("id"), "name": cb.get("name"), "_json": ""} \
                        if cb["type"] == "tool_use" else None
                    if cur:
                        out.append(cur)
                elif t == "content_block_delta" and cur is not None:
                    dl = d["delta"]
                    if dl.get("type") == "text_delta":
                        cur["text"] += dl["text"]
                        on_text(dl["text"])
                    elif dl.get("type") == "input_json_delta":
                        cur["_json"] += dl.get("partial_json", "")
                elif t == "content_block_stop":
                    cur = None
                elif t == "error":
                    raise RuntimeError("接口报错：" + json.dumps(d.get("error", d), ensure_ascii=False)[:500])
        for b in out:
            if b["type"] == "tool_use":
                try:
                    b["input"] = json.loads(b.pop("_json") or "{}")
                except ValueError:
                    b["input"] = {}
        return out


SYSTEM = """你是字幕组「轴效」（打轴 + 特效）的助手，直接在 Aegisub 里帮用户读、改 ASS 字幕。用中文回答，简洁。

你能用工具读字幕、改字幕、跑卡拉OK模板、看渲染效果。改动不会马上写进字幕：先进入「待应用」列表，
用户在右边预览里看效果，满意了点「应用」才写回 Aegisub（整批一步撤销）。所以放心改，改完告诉用户去预览。

规则：
- 行用「行号」指代（工具返回的 #号，就是 Aegisub 字幕表里的位置），新插入的行没有行号，要再改只能清空重来。
- 没被要求就不要动时间轴、不要动对白文字；翻译内容不归你管，除非用户要求。
- 这个插件的约定：中日各自一行（Text CN / Text JP、OP CN / OP JP……成对样式，靠顺序一一对应）；
  次要台词用 Top 样式；Screen 是屏字、Note 是注释；特效栏写「fx层」的是特效叠层副本；
  特效栏 fx 是卡拉OK模板生成的行，karaoke 是模板的源行（注释状态），template / code 开头的注释行是模板。
- 屏字要贴合画面：先用 render 看当前帧，按画面上原字的位置、颜色、角度写 \\pos \\c \\3c \\frz \\fax 等。
- 改完关键效果，用 render 看一眼再汇报（能看图的模型）。

ASS 常用标签：\\pos(x,y) \\move(x1,y1,x2,y2[,t1,t2]) \\an1-9 \\fad(入,出) \\t([t1,t2,][accel,]标签) \\blur \\be \\bord \\shad
\\c/\\1c \\2c \\3c \\4c &HBBGGRR& \\alpha \\1a \\3a &HAA& \\fs \\fn \\fscx \\fscy \\fsp \\frz \\frx \\fry \\fax \\fay \\org
\\clip(x1,y1,x2,y2) \\iclip \\clip(矢量) \\p1 绘图 \\k \\kf \\ko（厘秒）。颜色是 BGR 顺序。

卡拉OK模板（Aegisub 自带 kara-templater）：模板写成注释行，样式和要套的歌词行相同，特效栏写类型：
  code once / code line / code syl：跑 Lua 代码（定义变量函数）
  template line / template syl / template char（可加 noblank notext loop N multi fxgroup 等修饰）：生成行
  文本里 $变量：$start $end $dur $mid $i $syln $left $center $right $top $middle $bottom $width $height
  （前面加 s / l 表示音节 / 整行，如 $scenter $lleft），!Lua 表达式!，retime("syl"|"line"|"start2syl"|"syl2end"|"presyl"|"postsyl"|"sylpct"|"set",加开始,加结束)，
  j / maxj 是 loop 计数，_G 访问全局（_G.ass_color、_G.HSV_to_RGB 等 util 函数）。
  歌词源行要带 \\k 逐字时间。写好模板后用 run_karaoke 生成并预览。"""

TOOLS = [
    {"name": "list_lines", "description": "列出字幕行（改动后的样子）。可按行号范围、样式、时间、文字过滤。最多返回 200 行",
     "schema": {"type": "object", "properties": {
         "from_index": {"type": "integer"}, "to_index": {"type": "integer"},
         "style": {"type": "string", "description": "样式名（包含即可）"},
         "contains": {"type": "string"}, "time_from_ms": {"type": "integer"}, "time_to_ms": {"type": "integer"},
         "include_fx": {"type": "boolean", "description": "是否列出卡拉OK生成的 fx 行，默认否"}}}},
    {"name": "get_styles", "description": "样式列表（ASS Style 行格式）", "schema": {"type": "object", "properties": {
        "names": {"type": "array", "items": {"type": "string"}}}}},
    {"name": "set_lines", "description": "改已有的行（按行号）。只写要改的字段",
     "schema": {"type": "object", "required": ["changes"], "properties": {"changes": {"type": "array", "items": {
         "type": "object", "required": ["index"], "properties": {
             "index": {"type": "integer"}, "text": {"type": "string"}, "style": {"type": "string"},
             "start_ms": {"type": "integer"}, "end_ms": {"type": "integer"}, "layer": {"type": "integer"},
             "effect": {"type": "string"}, "comment": {"type": "boolean"}, "actor": {"type": "string"}}}}}}},
    {"name": "insert_lines", "description": "在某行后面插入新行（after_index=0 插在最前）。卡拉OK模板行 comment=true、effect 写 template…",
     "schema": {"type": "object", "required": ["after_index", "lines"], "properties": {
         "after_index": {"type": "integer"}, "lines": {"type": "array", "items": {
             "type": "object", "required": ["text", "style", "start_ms", "end_ms"], "properties": {
                 "text": {"type": "string"}, "style": {"type": "string"}, "start_ms": {"type": "integer"},
                 "end_ms": {"type": "integer"}, "layer": {"type": "integer"}, "effect": {"type": "string"},
                 "comment": {"type": "boolean"}, "actor": {"type": "string"}}}}}}},
    {"name": "delete_lines", "description": "删除行（按行号）", "schema": {"type": "object", "required": ["indices"],
                                                                     "properties": {"indices": {"type": "array", "items": {"type": "integer"}}}}},
    {"name": "set_style", "description": "新建或修改样式。颜色写 &HAABBGGRR（AA 是透明度，00 不透明）。只写要改的字段，新样式其余照抄 Default",
     "schema": {"type": "object", "required": ["name"], "properties": {
         "name": {"type": "string"}, "fontname": {"type": "string"}, "fontsize": {"type": "number"},
         "color1": {"type": "string"}, "color2": {"type": "string"}, "color3": {"type": "string"},
         "color4": {"type": "string"}, "bold": {"type": "boolean"}, "italic": {"type": "boolean"},
         "scale_x": {"type": "number"}, "scale_y": {"type": "number"}, "spacing": {"type": "number"},
         "angle": {"type": "number"}, "borderstyle": {"type": "integer"}, "outline": {"type": "number"},
         "shadow": {"type": "number"}, "align": {"type": "integer"}, "margin_l": {"type": "integer"},
         "margin_r": {"type": "integer"}, "margin_v": {"type": "integer"}}}},
    {"name": "run_karaoke", "description": "对这些歌词行跑卡拉OK模板（用字幕里同样式的 template/code 注释行），生成 fx 行进待应用。"
                                           "k_mode：keep=保留已有 \\k（没有就均分），even=全部重新均分",
     "schema": {"type": "object", "required": ["indices"], "properties": {
         "indices": {"type": "array", "items": {"type": "integer"}},
         "k_mode": {"type": "string", "enum": ["keep", "even"]}}}},
    {"name": "render", "description": "渲染某一时刻的画面（视频帧 + 改动后的字幕），返回图片给你看", "schema": {
        "type": "object", "required": ["time_ms"], "properties": {"time_ms": {"type": "integer"}}}},
    {"name": "clear_pending", "description": "清空所有待应用的改动（从头来）", "schema": {"type": "object", "properties": {}}},
]
