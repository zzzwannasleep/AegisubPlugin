r"""AI 助手回归：本机起假接口（OpenAI 兼容 / Anthropic 双协议），跑完整的「查行 → 改行 → 看图 → 回答」。

绝不连外网：假接口只监听 127.0.0.1 上端口 0 自动分配的临时端口。
AI 页不真开视频：job 里 video 留空，render 走「灰底 + VSFilter」那条路，回给模型的仍是真的 PNG 字节；
真正要验的是「图片有没有作为图片块回给模型」，跟背景是不是真实帧无关。
用假 App（构造后 withdraw()，不显示窗口）跑真实界面层，需要事件循环时用 app.update() 泵。

    python tests\test_ai.py
"""
import bootstrap  # noqa: F401
import testconfig as C
import fixtures

import http.server
import json
import os
import threading
import time

z, fe, ai = C.load_src()

KEY = "k-test"
NEW_TEXT = r"{\blur1}AI 改的"   # 假模型第二轮要把 30 行改成这个
RENDER_MS = 606000             # 假模型第三轮要看的时刻；也是 job 里的当前时间
STEPS = 4                      # 假模型一共被问 4 轮

OK = []
BAD = []

# 每次请求的观察记录。断言统一放主线程做：assert 抛在假接口的服务线程里只会变成「连接断掉」，
# 主线程看到一个莫名的 URLError，看不出到底哪条格式不对。
TRACE = []
VIOLATIONS = []


def check(name, cond, detail=""):
    (OK if cond else BAD).append(name)
    print(("  OK   " if cond else "  FAIL ") + name + (("   " + str(detail)) if detail and not cond else ""))


def _snap(path):
    """按字节备份：ai.json 是用户真实配置，必须以完全相同的内容还原（别被换行符翻译动过）"""
    if os.path.exists(path):
        with open(path, "rb") as f:
            return f.read()
    return None


def _quiet_destroy(app):
    """销毁前取消所有排队的 after 回调。

    App 里 poll() 每 30ms 自排一次，直接 destroy() 会留下已经作废的定时脚本；
    下一个 App 泵事件循环时 Tcl 会去跑它，往 stderr 吐一堆 invalid command name。
    不影响判定，但测试输出应该干净。
    """
    try:
        ids = app.tk.call("after", "info")
        # 走裸 Tcl 的 after cancel，不用 tkinter 的 after_cancel：后者会顺手 deletecommand，
        # 等 destroy() 再删一次同名 Tcl 命令时就炸 "can't delete Tcl command"。
        for aid in (app.tk.splitlist(ids) if ids else ()):
            try:
                app.tk.call("after", "cancel", aid)
            except Exception:
                pass
    except Exception:
        pass
    app.destroy()


def _restore(path, bak):
    if bak is None:
        # 原来就没有：删掉测试新建的，别给用户留一个空配置
        if os.path.exists(path):
            os.remove(path)
    else:
        with open(path, "wb") as f:
            f.write(bak)


# ---------------------------------------------------------------- 假模型
def model_reply(n, imgs):
    """按「已经回填了几个工具结果」决定这一轮说什么、调什么。

    这正是要验的循环：模型不自己记账，全靠客户端把工具结果喂回来才知道走到第几步。
    """
    if n == 0:
        return "我先看看所选的行。", ("list_lines", {"style": "Text CN", "to_index": 40})
    if n == 1:
        return "", ("set_lines", {"changes": [{"index": 30, "text": NEW_TEXT}]})
    if n == 2:
        return "改好了，看一眼效果。", ("render", {"time_ms": RENDER_MS})
    return "看到了 %d 张图，改完了，去预览看吧。" % imgs, None


def _args(raw):
    try:
        return json.loads(raw or "{}")
    except ValueError:
        return raw   # 两段 arguments 没拼起来：原样留着，断言里能看见断在哪


def inspect(proto, body):
    """挑出一次请求里要断言的三样：模型回带的工具调用、回填的工具结果、图片块数"""
    msgs = body.get("messages") or []
    calls, results, imgs = [], [], 0
    if proto == "openai":
        for m in msgs:
            for tc in (m.get("tool_calls") or []):
                fn = tc.get("function") or {}
                calls.append({"name": fn.get("name"), "input": _args(fn.get("arguments"))})
            if m.get("role") == "tool":
                results.append(m.get("content"))
        # 工具结果里的图，OpenAI 协议放不进 tool 消息，插件会补一条 user 消息（image_url）
        imgs = sum(1 for m in msgs if m.get("role") == "user" and isinstance(m.get("content"), list)
                   for p in m["content"] if p.get("type") == "image_url")
    else:
        for m in msgs:
            for b in (m.get("content") or []):
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_use":
                    calls.append({"name": b.get("name"), "input": b.get("input")})
                elif b.get("type") == "tool_result":
                    c = b.get("content")
                    if isinstance(c, list):
                        results.append("".join(x.get("text", "") for x in c if x.get("type") == "text"))
                        imgs += sum(1 for x in c if x.get("type") == "image")
                    else:
                        results.append(c)
    return calls, results, imgs


class FakeAPI(http.server.BaseHTTPRequestHandler):
    """冒充模型接口：流式（SSE）返回，工具调用参数故意拆两段发"""

    def log_message(self, *a):
        pass   # 默认会往测试输出里塞一行请求日志

    def do_POST(self):
        try:
            raw = self.rfile.read(int(self.headers.get("content-length") or 0))
            body = json.loads(raw or b"{}")
        except ValueError as ex:
            VIOLATIONS.append("请求体不是 JSON：%s" % ex)
            self.send_error(400)
            return
        proto = "anthropic" if self.path.endswith("/messages") else "openai"
        self._check_format(proto, body)
        calls, results, imgs = inspect(proto, body)
        TRACE.append({"proto": proto, "path": self.path, "n": len(results), "imgs": imgs,
                      "calls": calls, "results": results})
        text, call = model_reply(len(results), imgs)
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()
        try:
            self._stream(proto, text, call)
        except OSError:
            pass   # 客户端已经断开（比如按了停止）

    def _check_format(self, proto, body):
        if body.get("stream") is not True:
            VIOLATIONS.append("[%s] 请求没带 stream=true" % proto)
        if not body.get("tools"):
            VIOLATIONS.append("[%s] 请求没带 tools" % proto)
        if proto == "anthropic":
            if self.headers.get("x-api-key") != KEY:
                VIOLATIONS.append("[anthropic] x-api-key 不对：%r" % self.headers.get("x-api-key"))
            if not self.headers.get("anthropic-version"):
                VIOLATIONS.append("[anthropic] 缺 anthropic-version")
            if not isinstance(body.get("system"), str):
                VIOLATIONS.append("[anthropic] system 应是顶层字符串，实际 %r" % type(body.get("system")))
        else:
            if self.headers.get("authorization") != "Bearer " + KEY:
                VIOLATIONS.append("[openai] authorization 不对：%r" % self.headers.get("authorization"))
            msgs = body.get("messages") or []
            if not msgs or msgs[0].get("role") != "system":
                VIOLATIONS.append("[openai] system 应放 messages[0]：%r" % (msgs[:1] or None))

    def _stream(self, proto, text, call):
        def w(ev, d):
            head = ("event: %s\n" % ev) if ev else ""
            self.wfile.write((head + "data: " + json.dumps(d, ensure_ascii=False) + "\n\n").encode("utf-8"))

        if proto == "openai":
            for ch in ([text[:3], text[3:]] if text else []):
                w(None, {"choices": [{"delta": {"content": ch}}]})
            if call:
                args = json.dumps(call[1], ensure_ascii=False)
                # 参数切成两段：客户端必须按 index 把 arguments 累积起来，拼错就会 json 解析失败
                w(None, {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {
                    "name": call[0], "arguments": args[:5]}}]}}]})
                w(None, {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {
                    "arguments": args[5:]}}]}}]})
            self.wfile.write(b"data: [DONE]\n\n")
        else:
            k = 0
            if text:
                w("content_block_start", {"type": "content_block_start", "index": k,
                                          "content_block": {"type": "text", "text": ""}})
                for ch in [text[:3], text[3:]]:
                    w("content_block_delta", {"type": "content_block_delta", "index": k,
                                              "delta": {"type": "text_delta", "text": ch}})
                w("content_block_stop", {"type": "content_block_stop", "index": k})
                k += 1
            if call:
                args = json.dumps(call[1], ensure_ascii=False)
                w("content_block_start", {"type": "content_block_start", "index": k,
                                          "content_block": {"type": "tool_use", "id": "tu1",
                                                            "name": call[0], "input": {}}})
                # 同样是两段 partial_json，验 input_json_delta 的拼接
                for part in (args[:4], args[4:]):
                    w("content_block_delta", {"type": "content_block_delta", "index": k,
                                              "delta": {"type": "input_json_delta", "partial_json": part}})
                w("content_block_stop", {"type": "content_block_stop", "index": k})
            w("message_stop", {"type": "message_stop"})


# ---------------------------------------------------------------- 字幕夹具
def dump_rows(n=30):
    """合成一份「行号 30 是 Text CN 行」的表。

    write_dump 的编号是 2 行 info + 8 个样式打头，所以第 1 条 dialogue 拿到 11 号；
    行号 30 落在第 20 条（k=19），按 k % 3 取样式正好命中 Text CN，假模型的改行才落得下去。
    时间也贴着 RENDER_MS 摆，render 出来的那一帧里真的有被改的那行。
    """
    rows = []
    for k in range(n):
        i = 11 + k
        t = 600000 + k * 300
        rows.append(fixtures.row("第 %d 行原话" % i, style="Text CN" if k % 3 != 2 else "Text JP",
                                 start=t, end=t + 1000))
    return rows


# ---------------------------------------------------------------- 一种协议跑一遍
def run_one(proto, base, dump, hist):
    tag = "[%s] " % proto
    ai.save_conf({"protocol": proto, "base_url": base, "key": KEY, "model": "fake-model"})
    if os.path.exists(hist):
        os.remove(hist)   # 历史要从零开始，否则会接着上次的对话，步数与断言全对不上
    doc = z.Doc(dump)
    sel = [r["i"] for r in doc.dialogue() if r["style"] == "Text CN"][:2]
    job = {"tab": "ai", "dump": dump, "sel": sel, "active": sel[0], "time": RENDER_MS,
           # video 留空：不真解码视频，render 走「灰底 + VSFilter」，回给模型的仍是真 PNG
           "video": "", "vsfilter": C.VSFILTER, "aegisub_dir": C.AEGISUB, "out": ""}
    app = fe.App(job)
    app.withdraw()
    del TRACE[:]
    try:
        app.ai.inp.insert("1.0", "把第 30 行加点模糊")
        app.ai.send()
        t0 = time.time()
        while app.ai.busy and time.time() - t0 < 60:
            app.update()   # 泵事件循环：后台线程的工具要回界面线程跑，靠 poll() 转交
            time.sleep(0.02)
        for _ in range(5):   # 收尾：done() 之后可能还有排队的界面调用
            app.update()
            time.sleep(0.02)

        chat = app.ai.chat.get("1.0", "end")
        e = app.ai.edits
        steps = [t["n"] for t in TRACE]
        last = TRACE[-1] if TRACE else {"calls": [], "results": [], "imgs": 0}
        calls = last["calls"]

        print("  —— %s：请求 %d 次，工具结果数 %s，末轮图片 %d 张，待应用 %d 处"
              % (proto, len(TRACE), steps, last["imgs"], e.count()))
        check(tag + "AI 没卡住（60 秒内把 %d 轮跑完）" % STEPS, not app.ai.busy)
        check(tag + "请求次数序列是工具结果数 [0,1,2,3]（每轮回填后才问下一轮）",
              steps == list(range(STEPS)), steps)
        check(tag + "末轮把三个工具调用都回带给接口，顺序 list_lines/set_lines/render",
              [c["name"] for c in calls] == ["list_lines", "set_lines", "render"], calls)
        check(tag + "set_lines 参数（两段 SSE 拼起来）是对的",
              len(calls) > 1 and calls[1]["input"] == {"changes": [{"index": 30, "text": NEW_TEXT}]},
              calls[1:2])
        check(tag + "render 参数是 %d 毫秒" % RENDER_MS,
              len(calls) > 2 and calls[2]["input"] == {"time_ms": RENDER_MS}, calls[2:3])
        check(tag + "工具结果回填进了下一次请求（改了几行 / 是什么时刻）",
              any("改了 1 行" in (r or "") for r in last["results"])
              and any(str(RENDER_MS) in (r or "") for r in last["results"]), last["results"])
        check(tag + "图片作为图片块回给了模型（第 4 次请求正好 1 张）",
              len(steps) == STEPS and TRACE[3]["imgs"] == 1, [t["imgs"] for t in TRACE])
        check(tag + "模型报出的图数就是它看到的图数", "看到了 1 张图" in chat)
        check(tag + "第 30 行在待应用里被改成模型给的文字",
              e.sets.get(30, {}).get("text") == NEW_TEXT, e.sets.get(30))
        check(tag + "改动进了待应用列表（不是直接写回字幕）", e.count() >= 1 and 30 in e.sets, e.count())

        blob = _snap(hist)
        h = json.loads(blob.decode("utf-8")) if blob else None
        text = json.dumps(h, ensure_ascii=False)
        check(tag + "对话历史存下来了", isinstance(h, list) and len(h) >= 4,
              None if h is None else len(h))
        check(tag + "历史里有用户那句话", "把第 30 行加点模糊" in text)
        check(tag + "历史里的图只有文字（png 键和 PNG base64 都不许有）",
              '"png"' not in text and "iVBORw0KGgo" not in text)
        check(tag + "render 的工具结果文字留在了历史里", "毫秒的画面" in text)
    finally:
        _quiet_destroy(app)


def main():
    print("AI 助手：本机假接口（OpenAI 兼容 / Anthropic），流式 + 工具调用")

    dump = fixtures.write_dump_file("ai_dump.tsv", dump_rows())
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeAPI)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    print("   假接口 http://127.0.0.1:%d（只在本机，端口临时分配）" % port)

    hist = os.path.join(fe.HOME, "ai_history.json")
    conf_bak, hist_bak = _snap(ai.CONF), _snap(hist)
    try:
        for proto, base in (("openai", "http://127.0.0.1:%d/v1" % port),
                            ("anthropic", "http://127.0.0.1:%d" % port)):
            run_one(proto, base, dump, hist)
    finally:
        srv.shutdown()
        srv.server_close()
        _restore(ai.CONF, conf_bak)
        _restore(hist, hist_bak)

    check("跑完把 ai.json / ai_history.json 恢复原状",
          _snap(ai.CONF) == conf_bak and _snap(hist) == hist_bak)
    check("假接口没遇到格式问题（请求头 / system 位置 / stream / tools）", not VIOLATIONS, VIOLATIONS)

    print("\n通过 %d 项，失败 %d 项" % (len(OK), len(BAD)))
    return 1 if BAD else 0


if __name__ == "__main__":
    raise SystemExit(main())
