r"""卡拉OK 的两条不变量：切法和写回必须往返一致。

Lua 侧「6 歌词定位」和 K 帧时间轴按原 \k 读切法（k_starts），Python 侧按自定切法写回（auto_k），
两者必须对得上，否则每点一次应用都会改掉用户的切法。用测试自己合成的一句，不绑死某部番。

    python tests\test_kara_parity.py
"""
import bootstrap  # noqa: F401
import testconfig as C

z, fe, ai = C.load_src()
OK = []
BAD = []


def check(name, cond, detail=""):
    (OK if cond else BAD).append(name)
    print(("  OK   " if cond else "  FAIL ") + name + (("   " + str(detail)) if detail and not cond else ""))


def main():
    print("卡拉OK：\\k 切法 <-> auto_k 写回")

    # 1. 按字打：auto_k 写出来的，k_starts 要一模一样读回来
    text, dur = "消えた世界", 2000
    starts = [300, 600, 900, 1200, 1500]
    t = z.auto_k(text, dur, starts=starts)
    check("按字打：写回再读回一致", z.k_starts(t, dur) == (list(text), starts), z.k_starts(t, dur))
    check("按字的 \\k 时长按相邻间隔给", "{\\k30}{\\k30}消{\\k30}え" in t, t)

    # 2. 自定切法：空音节 = 同一个字多唱一拍（拆开 / 合并）
    syl = ["い", "つ", "", "の日に"]
    s2 = [0, 200, 400, 600]
    t2 = z.auto_k(r"{\an5}いつの日に", 1000, starts=s2, syls=syl)
    check("拆开/合并：写回再读回一致", z.k_starts(t2, 1000) == (syl, s2), z.k_starts(t2, 1000))
    check("空音节写成没有字的 \\k", "{\\k20}{\\k40}の日に" in t2, t2)
    check("原有的 \\an5 保留", t2.startswith(r"{\an5}"), t2)

    # 3. 读别人的 \k：连续的 \k 之间没有字，就是同一个字的切法（读侧的真实行为）
    got = z.k_starts(r"{\k20}いつ{\k50}の{\k30}日に", 1000)
    check("读原 \\k：相邻的 \\k 合并成一个字", got == (["いつ", "の", "日に"], [0, 200, 700]), got)
    check("读原 \\k：总时长对得上", sum(got[1]) <= 1000, got[1])

    # 4. 没打 \k 连在一起的文本要拆成能认的字
    check("没时间的文本按字铺开",
          z.k_starts(r"{\an5}いつの日に", 1000)[0] == ["い", "つ", "の", "日", "に"],
          z.k_starts(r"{\an5}いつの日に", 1000))
    check("小写的ゃ并进前一个字", z.syllables("しゃしん") == ["しゃ", "し", "ん"], z.syllables("しゃしん"))

    # 5. 切法不能吃掉字：拼回去等于原文
    for s in ("消えた世界", "Hello world", "しゃしんを撮る"):
        check("切法拼回原文：%s" % s, "".join(z.syllables(s)) == s, z.syllables(s))
    check("空格跟着前一个音节", z.syllables("Hello world") == ["Hello ", "world"], z.syllables("Hello world"))

    print("\n通过 %d 项，失败 %d 项" % (len(OK), len(BAD)))
    return 1 if BAD else 0


if __name__ == "__main__":
    raise SystemExit(main())
