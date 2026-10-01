"""轴效粗轴：已有原文（日文或中文），让 whisper 做强制对齐（找每句在哪），不做听写。

- 人声分离：UVR 的 MDX-Net 模型（ONNX），跑在 DirectML 上 —— N 卡 / A 卡 / Intel 独显都能用
- 对齐：whisper base 跑在 CPU 上（只是对齐不是听写，算量很小，一集约 1 分钟）
- 解码：PyAV，不依赖系统里装 ffmpeg

用法：
  python autotime.py 视频 原文.txt 输出.tsv [--vocals] [--lang zh]
  python autotime.py --job job.json      # Aegisub 插件走这条，路径放 json 里避开命令行编码问题

输出 tsv 每行对应原文 txt 的一行（空行已跳过，和插件导入的行一一对应）：
  开始毫秒 \t 结束毫秒 \t 置信度(0~1) \t 待查原因（空 = 没问题）
"""
import argparse, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
MODELS = os.environ.get("ZX_MODELS", os.path.join(HERE, "models"))
MDX = os.path.join(MODELS, "UVR-MDX-NET-Voc_FT.onnx")
# 人工轴习惯在开口前留一点。9 集真实番剧（4 个组）里模型开头比人工晚：中位 0.19 秒；
# 各组习惯不同（Prejudice 0.05、喵萌/绿茶 0.18、NEST 0.25），插件对话框里可以改，这里是默认值。
# 试过用人声波形起点代替模型给的词开头，反而更散（≤0.2 秒从 86% 掉到 69~76%），所以还是「词开头 − 常数」
LEAD = 0.2
LANG = "ja"   # 原文语言：ja / zh，align() 里按任务设
# whisper 听中文常出繁体，开头给一句简体提示能压住
PROMPT = {"zh": "以下是普通话的句子。"}
# 对着杂音 / 静音最爱编的固定句子，听到了当没听到
JUNK = ("ご視聴", "字幕由", "请不吝点赞", "Amara")
# 相邻两句挨得近（上一句结尾到下一句开头不到 LINK 秒，含重叠）→ 上一句结尾接到下一句开头。
# 人工轴 43% 的相邻句是严丝合缝接上的；不处理的话插件有 4% 的相邻句重叠（两句同时显示、叠在一起），人工只有 0.8%。
# 0.3 秒时结尾误差最小，再大会把本该断开的句子也接上
LINK = 0.3


def read_lines(path):
    # 和 zhouxiao.lua 的 read_lines 同一规则：去 BOM、去首尾空白、跳过空行
    with open(path, encoding="utf-8-sig") as f:
        return [s.strip() for s in f if s.strip()]


def decode(video, sr, layout):
    """视频里的音频 → float32 numpy，形状 (声道, 采样点)"""
    import av, numpy as np
    out = []
    with av.open(video) as c:
        rs = av.AudioResampler(format="fltp", layout=layout, rate=sr)
        for frame in c.decode(audio=0):
            for f in rs.resample(frame):
                out.append(f.to_ndarray())
        for f in rs.resample(None):
            out.append(f.to_ndarray())
    return np.concatenate(out, axis=1)


def separate(mix):
    """MDX-Net 人声分离（参数是 UVR 里 Voc_FT 的配置）。mix: (2, n) 44.1kHz → 人声 (2, n)"""
    import numpy as np, onnxruntime as ort, torch
    n_fft, hop, dim_f, dim_t, comp = 7680, 1024, 3072, 256, 1.021
    sess = ort.InferenceSession(MDX, providers=[
        ("DmlExecutionProvider", {"performance_preference": "high_performance"}), "CPUExecutionProvider"])
    if "DmlExecutionProvider" not in sess.get_providers():
        raise RuntimeError("没找到能用的独立显卡（DirectML 不可用），人声分离跑不了")
    win = torch.hann_window(n_fft, periodic=True)
    chunk = hop * (dim_t - 1)
    trim = n_fft // 2
    gen = chunk - 2 * trim
    n = mix.shape[1]
    pad = gen - n % gen
    x = np.concatenate([np.zeros((2, trim)), mix, np.zeros((2, pad + trim))], axis=1).astype(np.float32)
    outs = []
    for i in range(0, n + pad, gen):
        w = torch.from_numpy(x[:, i:i + chunk])
        spec = torch.stft(w, n_fft, hop, window=win, center=True, return_complex=True)   # (2, 3841, 256)
        spec = torch.view_as_real(spec).permute(0, 3, 1, 2).reshape(1, 4, -1, dim_t)[:, :, :dim_f]
        pred = torch.from_numpy(sess.run(None, {sess.get_inputs()[0].name: spec.numpy()})[0])
        full = torch.zeros(1, 4, n_fft // 2 + 1, dim_t)
        full[:, :, :dim_f] = pred
        full = full.reshape(2, 2, n_fft // 2 + 1, dim_t).permute(0, 2, 3, 1).contiguous()
        wav = torch.istft(torch.view_as_complex(full), n_fft, hop, window=win, center=True, length=chunk)
        outs.append(wav[:, trim:-trim].numpy())
    return np.concatenate(outs, axis=1)[:, :n] * comp


def fix_start(words):
    """对齐常见的错：句首的词被拉进前面的静音/间奏里。只看前三个词。
    返回 (修正后的开始秒, 是否动过)"""
    durs = sorted(w.end - w.start for w in words)
    med = max(durs[len(durs) // 2], 0.05)
    start, moved = words[0].start, False
    for i, w in enumerate(words[:3]):
        # 前一个词认出来了（把握 ≥ 0.2）就停：它是真说了的，后面的词再长也是句中停顿
        # （「私　寮長の…」这种，停顿会算进第二个词里，不能因此把「私」丢掉）
        if i > 0 and (words[i - 1].probability or 0) >= 0.2:
            break
        nxt = words[i + 1] if i + 1 < len(words) else None
        if nxt and nxt.start - w.end > 1.5:          # 词和词之间空了一大段：前面那几个词是错放的
            start, moved = nxt.start, True
        elif w.end - w.start > max(0.8, 4 * med):    # 一个词长得离谱：它的开头被拉进了静音
            start, moved = max(start, w.end - med), True
        # 没认出来（把握 < 0.3）却拖了 1 秒以上：多半是拿这个字盖住了前面的哼唱 / 前奏，
        # 真正唱这个字是在它快结束的时候
        if w.end - w.start > 1.0 and (w.probability or 0) < 0.3:
            start, moved = max(start, w.end - min(med, 0.4)), True
    return start, moved


HOP = 0.02  # 人声有无按 20ms 一格判断


def speech_mask(audio):
    """干净人声（16k）→ 每 20ms 一格有没有人声。分离后的人声在没人说话时很安静（比最响处低 40dB 以上），
    所以按「比最响处低 35dB 以内」算有声；0.4 秒以内的停顿（换气、音节间）填上，0.1 秒以内的杂音去掉"""
    import numpy as np
    x = audio.numpy()
    n = int(16000 * HOP)
    fr = x[: len(x) // n * n].reshape(-1, n)
    db = 10 * np.log10((fr ** 2).mean(1) + 1e-10)
    on = db > db.max() - 35
    edges = np.flatnonzero(np.diff(np.r_[0, on.astype(int), 0]))
    for s, e in zip(edges[1:-1:2], edges[2::2]):
        if (e - s) * HOP < 0.4:
            on[s:e] = True
    edges = np.flatnonzero(np.diff(np.r_[0, on.astype(int), 0]))
    for s, e in zip(edges[::2], edges[1::2]):
        if (e - s) * HOP < 0.1:
            on[s:e] = False
    return on


def snap(start, end, on):
    """开头落在没人声处 → 挪到后面第一个人声起点；结尾落在没人声处 → 收到前面最后一个人声终点。
    专治长间隔：对齐常把句尾拖进后面的空档，或把句首提前到空档里"""
    import numpy as np
    a, b = int(start / HOP), min(int(end / HOP), len(on) - 1)
    if a < len(on) and not on[a]:
        nxt = np.flatnonzero(on[a:b])
        if len(nxt):
            start = (a + nxt[0]) * HOP - 0.05
    a = int(start / HOP)
    if b <= a:
        return start, end
    seg = on[a:b + 1]
    # 句子中间出现 1.5 秒以上的空档：这句在空档前就说完了，空档后面的人声是下一句的
    # （长间隔时对齐常把句尾一直拖到下一句开口）
    edges = np.flatnonzero(np.diff(np.r_[1, seg.astype(int), 1]))
    for gs, ge in zip(edges[::2], edges[1::2]):
        if gs > 0 and (ge - gs) * HOP >= 1.5:
            return start, (a + gs) * HOP + 0.1
    if not on[b]:
        prv = np.flatnonzero(seg)
        if len(prv):
            end = (a + prv[-1] + 1) * HOP + 0.1
    return start, end


def extend_tail(end, limit, on):
    """结尾处人声还在（拖长音、尾音）→ 一直延到这段人声结束，但不超过 limit（下一句开头 / 最多 4 秒）。
    模型给的词结尾是按「字念完」算的，歌手拖长音它不管，所以唱完之前字幕就没了"""
    import numpy as np
    b = int(end / HOP)
    if b >= len(on) or not on[b]:
        return end
    off = np.flatnonzero(~on[b:])
    run_end = (b + (off[0] if len(off) else len(on) - b)) * HOP + 0.1
    return max(end, min(run_end, limit))


def seg_conf(s):
    ps = [w.probability for w in s.words if w.probability is not None]
    return sum(ps) / len(ps) if ps else 0


def load_audio(video, vocals=True, lyrics=False):
    """→ 16k 单声道 torch 张量（分离过人声的话是干净人声）"""
    import torch
    if not vocals:
        return torch.from_numpy(decode(video, 16000, "mono")[0])
    # ponytail: 以前打对白时会把认出的整段歌静音，真实番剧里 OP / 插曲底下常压着对白，
    # 静音会把对白一起抹掉、后面整集脱轨，所以不再静音；歌声造成的错位靠 recover() 修
    return torch.from_numpy(separate16(video)[0])


def separate16(video):
    """→ (人声, 原混音)，都是 16k 单声道 float32 numpy"""
    import numpy as np, torch, torchaudio
    # 背景音乐 / 歌曲伴奏会把对齐带偏，先把人声拿出来
    print("分离人声……", flush=True)
    mix = decode(video, 44100, "stereo")
    voc = separate(mix)
    r16 = lambda x: torchaudio.functional.resample(torch.from_numpy(x.mean(axis=0).astype(np.float32)), 44100, 16000).numpy()
    return r16(voc), r16(mix)


def why_of(line, start, end, conf, moved):
    # 阈值按测试视频定的：base 模型唱歌时置信度普遍只有 0.3~0.5 但时间是对的，
    # 真错的在 0.25 以下；时长按字数算，每字不到 0.08 秒基本是被挤扁了
    return ("时长太短" if end - start < max(0.3, 0.08 * len(line)) else "开头修正过" if moved
            else "置信度低" if conf < 0.25 else "")


def islands(on, lo, hi):
    """[lo, hi] 秒内一段段连着的人声 → [(开始秒, 结束秒)]"""
    import numpy as np
    a, b = max(int(lo / HOP), 0), min(int(hi / HOP), len(on))
    if b <= a:
        return []
    edges = np.flatnonzero(np.diff(np.r_[0, on[a:b].astype(int), 0]))
    return [((a + s) * HOP, (a + e) * HOP) for s, e in zip(edges[::2], edges[1::2])]


def kana(s):
    """比文字用：去标点空格，片假名转平假名（中文只去标点）"""
    import re
    s = re.sub(r"[\s　、。，,.!?！？「」『』…・～〜ー\-：；:;“”‘’\"'（）()《》〈〉·—]", "", s)
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in s)


def refine(model, audio, on, lines, items):
    """没对上的句子单独再找一遍位置。整集一起对齐时，短句（「はい」「いた」）和字幕里没有的人声
    （笑声、喘气、没字幕的路人）会让句子落到别的人声上。这里在前后两句之间，把每段人声单独拿去听写，
    听出来的字和这一句最像、又明显比别的段像，才挪过去（对齐打分对一两个字的短句分不出来，听写能）。
    返回挪过的句子序号"""
    import difflib
    sr = 16000
    heard = {}
    def hear(s, e):
        if (s, e) not in heard:
            clip = audio[max(int((s - 0.2) * sr), 0):int((e + 0.2) * sr)]
            r = model.transcribe(clip.clone(), language=LANG, verbose=None, vad=False, temperature=0,
                                 word_timestamps=False, condition_on_previous_text=False,
                                 initial_prompt=PROMPT.get(LANG))
            txt = "".join(x.text for x in r.segments)
            # ponytail: 固定幻听句见 JUNK，再遇到别的加进去
            heard[(s, e)] = "" if any(j in txt for j in JUNK) else kana(txt)
        return heard[(s, e)]
    moved = []
    for i, it in enumerate(items):
        want = kana(lines[i])
        # 「うん」「はい」这种一两个字的，满集都是类似的声音，听写也分不出是哪段，不挪
        if len(want) <= 2 or (why_of(lines[i], *it) != "时长太短" and it[2] >= 0.25):
            continue
        lo = items[i - 1][0] + 0.1 if i > 0 else 0.0   # 前一句开口之后（抢话时两句会叠在一起，所以不用前一句结尾）
        nxt = [x for j, x in enumerate(items[i + 1:], i + 1) if not why_of(lines[j], *x)]
        hi = nxt[0][1] if nxt else len(audio) / sr
        scored = sorted(((difflib.SequenceMatcher(None, want, hear(s, e)).ratio(), s, e)
                         for s, e in islands(on, lo, hi)[:30] if 0.15 <= e - s <= 6), reverse=True)
        if not scored:
            continue
        sim, s, e = scored[0]
        runner = scored[1][0] if len(scored) > 1 else 0
        if sim < 0.3 or sim - runner < 0.1 or s - 0.3 <= it[0] <= e:
            continue   # 听不出来 / 分不出哪段 / 本来就在这段上
        # 在选中的这段人声里再对齐一次，拿到这句的起止（一段人声里可能连着好几句）
        a = max(int((s - 0.2) * sr), 0)
        r = model.align(audio[a:int((e + 0.2) * sr)].clone(), lines[i], language=LANG,
                        original_split=True, verbose=None)
        ws = [w for seg in r.segments for w in seg.words]
        if ws:
            items[i] = [*snap(a / sr + ws[0].start, a / sr + ws[-1].end, on), it[2], False]
            moved.append(i)
    return moved


def first_pass(model, audio, lines, on):
    """整段一起对齐 → [[开始, 结束, 把握, 开头是否修正过]]"""
    # nonspeech_skip = 跳过多长的无人声段。这个值对结果影响是跳跃的（测试里 2 秒让长间隔对白整体错位，
    # 5 秒让 ED 整首错位，10 秒两边都好），所以先用 10；整体错位时大片句子置信度会掉到 0.25 以下，
    # 这时换别的值重跑，取平均置信度最高的那次
    best = None
    for skip in (10, 5, 2):
        print(f"对齐（跳过 {skip} 秒以上的空档）……", flush=True)
        res = model.align(audio.clone(), "\n".join(lines), language=LANG, original_split=True, nonspeech_skip=skip)
        confs = [seg_conf(x) for x in res.segments]
        mean = sum(confs) / max(len(confs), 1)
        low = sum(c < 0.25 for c in confs)
        if best is None or mean > best[0]:
            best = (mean, res)
        if low <= 0.1 * len(lines):
            break
        print(f"  {low} 句置信度很低，可能整体错位了，换个设置再试", flush=True)
    segs = best[1].segments
    if len(segs) != len(lines):
        # ponytail: 分段数对不上就按顺序能对几句算几句，剩下的给 0 让人手打
        print(f"警告：对齐出 {len(segs)} 段，原文 {len(lines)} 行", file=sys.stderr)
    items = []
    for i in range(min(len(segs), len(lines))):
        s = segs[i]
        start, moved = fix_start(s.words) if s.words else (s.start, False)
        end = s.end
        if on is not None:
            start, end = snap(start, end, on)
        items.append([start, end, seg_conf(s), moved])
    return items


def load_model():
    import torch, stable_whisper
    torch.set_num_threads(os.cpu_count() or 4)
    return stable_whisper.load_model("base", device="cpu", download_root=MODELS)


def align(video, ja_txt, out_tsv, vocals=True, lyrics=False, lead=LEAD, lang="ja"):
    global LANG
    LANG = lang
    lines = read_lines(ja_txt)
    audio = load_audio(video, vocals, lyrics)
    model = load_model()
    on = speech_mask(audio) if vocals else None
    items = first_pass(model, audio, lines, on)
    finish(model, audio, on, lines, items, out_tsv, lyrics, lead=lead)
    return out_tsv


def hear(model, audio):
    """整段听写 → (字列表, 每个字的时间)。字按 kana() 规整过，方便和原文逐字比"""
    r = model.transcribe(audio.clone(), language=LANG, verbose=None, temperature=0,
                         condition_on_previous_text=False, word_timestamps=True, initial_prompt=PROMPT.get(LANG))
    chars, times = [], []
    for w in r.all_words():
        t = kana(w.word)
        for k, c in enumerate(t):
            chars.append(c)
            times.append(w.start + (w.end - w.start) * k / max(len(t), 1))
    return chars, times


def anchors(lines, chars, times):
    """原文和听写逐字比（difflib 找公共块，只认连着 2 字以上的），一句里对上一半以上的字就当锚点。
    返回 {行号: 估计开口秒}。块是按顺序找的，所以锚点时间天然是递增的"""
    import difflib
    L, owner, first = [], [], []
    for i, l in enumerate(lines):
        t = kana(l)
        first.append(len(L))
        L += t
        owner += [i] * len(t)
    hit = {}
    for a, b, n in difflib.SequenceMatcher(None, L, chars, autojunk=False).get_matching_blocks():
        if n >= 2:
            for k in range(n):
                hit.setdefault(owner[a + k], []).append((a + k, times[b + k]))
    out = {}
    for i, hs in hit.items():
        n = len(kana(lines[i]))
        if n >= 2 and len(hs) >= max(2, 0.5 * n):
            out[i] = hs[0][1] - (hs[0][0] - first[i]) * 0.12   # 没对上的开头几个字按每字 0.12 秒往前推
    return out


def recover(model, audio, on, lines, items, heard=None, th=3.0):
    """整集一次对齐会「脱轨」：某处错了，后面几十上百句跟着错（真实番剧 9 集里 4 集出现过）。
    这里用听写找锚点，句子离锚点超过 th 秒（没锚点的句子：跑出前后两个锚点夹住的范围）就算脱轨，
    脱轨的句子所在的那段（前后两个锚点之间）单独再对齐一次，只换脱轨的句子。
    heard：已有的听写结果（测试时复用），没有就现听。返回换过的行号"""
    sr = 16000
    chars, times = heard or hear(model, audio)
    anc = anchors(lines, chars, times)
    keys = sorted(anc)
    import bisect
    bad = set()
    for i, it in enumerate(items):
        if i in anc:
            if abs(it[0] - anc[i]) > th:
                bad.add(i)
            continue
        k = bisect.bisect(keys, i)
        if (k > 0 and it[0] < anc[keys[k - 1]] - th) or (k < len(keys) and it[0] > anc[keys[k]] + th):
            bad.add(i)
    bounds = [0] + keys + [len(lines)]
    fixed = []
    for k in range(len(bounds) - 1):
        a, b = bounds[k], bounds[k + 1]
        if a >= b or not any(a <= i < b for i in bad):
            continue
        lo = max(0.0, anc[a] - 1.0) if a in anc else 0.0
        hi = max(anc[b] + 0.3 if b in anc else len(audio) / sr, lo + 0.5)
        r = model.align(audio[int(lo * sr):int(hi * sr)].clone(), "\n".join(lines[a:b]), language=LANG,
                        original_split=True, verbose=None)
        for j, s in enumerate(r.segments[:b - a]):
            if a + j in bad and s.words:
                st, mv = fix_start(s.words)
                items[a + j] = [*snap(lo + st, lo + s.end, on), seg_conf(s), mv]
                fixed.append(a + j)
    return fixed




def finish(model, audio, on, lines, items, out_tsv, lyrics=False, heard=None, lead=LEAD):
    moved = []
    if on is not None and not lyrics:
        print("听写找锚点，修脱轨……", flush=True)
        print(f"  修了 {len(recover(model, audio, on, lines, items, heard))} 句", flush=True)
        print("没对上的句子逐段重找……", flush=True)
        moved = refine(model, audio, on, lines, items)
        print(f"  挪了 {len(moved)} 句", flush=True)
        for it in items:
            it[0] = max(0.0, it[0] - lead)
    if on is not None:
        for i, it in enumerate(items):
            nxt = items[i + 1][0] - 0.05 if i + 1 < len(items) else float("inf")
            it[1] = extend_tail(it[1], min(nxt, it[1] + 4.0), on)
    for a, b in zip(items, items[1:]):
        # 下一句开头比上一句开头还早的是抢话 / 同时说，不动
        if b[0] - a[1] < LINK and b[0] > a[0]:
            a[1] = b[0]
    with open(out_tsv, "w", encoding="utf-8") as f:
        for i in range(len(lines)):
            if i < len(items):
                start, end, conf, mv = items[i]
                why = "位置重找过" if i in moved else why_of(lines[i], start, end, conf, mv)
                f.write(f"{round(start * 1000)}\t{round(end * 1000)}\t{conf:.3f}\t{why}\n")
            else:
                f.write("0\t0\t0\t没对上\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("video", nargs="?")
    ap.add_argument("ja_txt", nargs="?")
    ap.add_argument("out_tsv", nargs="?")
    ap.add_argument("--no-vocals", action="store_true", help="不分离人声（纯对白、没有 BGM 时可以省时间）")
    ap.add_argument("--lyrics", action="store_true", help="打的是歌词（不做逐段重找）")
    ap.add_argument("--lead", type=float, default=LEAD, help="对白开头提前多少秒")
    ap.add_argument("--lang", default="ja", choices=("ja", "zh"), help="原文语言")
    ap.add_argument("--job", help="json：{video, ja_txt（原文 txt）, out_tsv, vocals, lyrics, lead, lang}")
    ap.add_argument("--check", action="store_true", help="安装自检：依赖能导入、DirectML 可用、模型在")
    a = ap.parse_args()
    if a.check:
        import onnxruntime, stable_whisper, av
        p = onnxruntime.get_available_providers()
        print("providers:", p)
        assert "DmlExecutionProvider" in p, "DirectML 不可用"
        for m in (MDX, os.path.join(MODELS, "base.pt")):
            assert os.path.exists(m), "缺模型 " + m
        print("自检通过")
        sys.exit(0)
    j = {}
    if a.job:
        with open(a.job, encoding="utf-8") as f:
            j = json.load(f)
        if j.get("log"):
            # 插件不开黑窗口：进度和报错写进日志，插件读最后一行显示在 Aegisub 的进度框里
            sys.stdout = sys.stderr = open(j["log"], "w", encoding="utf-8", buffering=1)
    try:
        if a.job:
            align(j["video"], j["ja_txt"], j["out_tsv"], j.get("vocals", True), j.get("lyrics", False),
                  j.get("lead", LEAD), j.get("lang", "ja"))
        else:
            align(a.video, a.ja_txt, a.out_tsv, not a.no_vocals, a.lyrics, a.lead, a.lang)
    except Exception:
        import traceback
        traceback.print_exc()
        if not j.get("log"):
            input("出错了，把上面的报错截图发给做插件的人。按回车关闭……")
        sys.exit(1)
