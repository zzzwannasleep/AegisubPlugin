# 轴效（Aegisub 插件）

字幕组「轴效」岗位用的 Aegisub 自动化插件：导入中日 txt、打轴、主次/歌词/注释/屏字、
自动粗轴、特效工作台（特效样式 / 卡拉OK / AI 助手）。

**作者：zzzwannasleep** ｜ **当前版本 0.24**，跑在 arch1t3cht 增强版 Aegisub（`D:\Video\Aegisub-3.4.2`）。

## 目录里有什么

```
src\zhouxiao.lua     插件本体（Aegisub 加载的就是它）
src\autotime.py      自动粗轴：人声分离 + whisper 强制对齐
src\fxedit.py        特效工作台的窗口（tkinter）
src\zxcore.py        工作台的公共部分：ASS 读写、预览、K 帧时间轴
src\zxai.py          AI 助手的两种协议（OpenAI 兼容 / Anthropic）
src\install.ps1      组件安装脚本（独立 Python 环境 + 两个模型）
src\VERSION          版本号，和 zhouxiao.lua 里的 script_version 一起改
tools\extract.py     从 lua 里抽出上面几段（一般只在接管时用一次）
tools\embed.py       把 src 塞回 lua（改完必须跑）+ --check / --version / --deploy
tools\status.py      看 src、线上 lua、组件目录对不对得上
tools\selftest.py    回归测试（不开 Aegisub 也能跑）
tools\luaharness.py  selftest 用的 Aegisub API 模拟台
tools\testconfig.py  测试用的路径和模块加载（别在测试里写死盘符）
tests\               各个专项测试，见下面「测试」
```

## 改代码的流程

Python 那四段**不是独立文件**，它们以长字符串的形式内嵌在 `zhouxiao.lua` 里（变量名
`AUTOTIME_PY` / `FXEDIT_PY` / `ZXCORE_PY` / `ZXAI_PY` / `INSTALL_PS1`），Aegisub 每次跑宏时
写到组件目录去。所以：

1. 改 `src\` 里的文件（**别改组件目录里的同名文件**，它们会被覆盖）
2. `python tools/embed.py` 塞回 `src\zhouxiao.lua` → 同时写进线上 `automation\autoload\zhouxiao.lua`
3. `python tools/status.py` 确认三边一致
4. 回到 Aegisub：**自动化 → 重新扫描自动化目录**（或重启 Aegisub）
5. `python tools/embed.py --deploy` 可以把组件目录的 Python 也一并同步（可选；正常用
   Aegisub 跑一次宏也会自动写）

改版本号：`python tools/embed.py --version 0.25` —— lua 里的 `script_version` 和
`src\VERSION` 会一起改。

## 测试

不用 Aegisub 的部分，一条命令跑完（一个测试一个子进程）：

```bat
D:\Video\Aegisub-3.4.2\zhouxiao-autotime\env\Scripts\python.exe tools\selftest.py --all
```

必须用组件目录里那个 Python（`zhouxiao-autotime\env\Scripts\python.exe`）——测试要 lupa、
av、torch 这些包，它们只装在组件环境里。单独跑某一个测试：
`python tools\selftest.py`（插件本身那 32 项）、`python tests\run_all.py kara`（只跑名字带 kara 的）。

| 测试 | 管什么 |
|---|---|
| `tools\selftest.py` | 源码三边一致、四段 Python 语法、组件环境自检（DirectML + 两个模型）、导入中日 txt、主次成对切换、同步时间（含句数对不上时中止）、加注释/加屏字、歌词定位 |
| `tests\test_kara_parity.py` | 卡拉OK 切法不变量：`\k` 读法 ↔ `auto_k` 写回往返一致（拆开/合并/空音节） |
| `tests\test_roundtrip.py` | 工作台整条链路：Lua 导出 → Python 算改动 → 写 ops → Lua 应用（特效样式/卡拉OK/AI 三页） |
| `tests\test_show.py` | 样式库、编号专用（`ED CN #05`）、按视频文件名认方案、弹框次数 |
| `tests\test_ai.py` | AI 助手双协议（OpenAI 兼容 / Anthropic），本机假接口，含流式、工具调用、图片回填 |

要真窗口的两个：

```bat
D:\Video\Aegisub-3.4.2\zhouxiao-autotime\env\Scripts\python.exe tests\test_gui.py kara
```

`test_gui.py` 会弹真窗口、按标题截自己的窗口存到 `tests\fixtures\generated\`，不进 `run_all.py`
（跑 `run_all.py` 不会带上它）。自动粗轴跑真实音频、以及需要人眼判断的预览效果，
仍然照 `D:\Video\轴效测试\测试说明.txt` 手测。

测试素材：`tests\fixtures.py` 现场合成字幕和导出文件，不绑死某一部番；
`tests\fixtures\kara_t1.ass` 是本仓库作者自己写的卡拉OK模板（社区模板不随仓库分发）。
真实素材可以用环境变量指：`ZX_COMPONENT` / `ZX_PY` / `ZX_VIDEO` / `ZX_AEGISUB`。

## 几个容易踩的地方

- **BOM**：`autotime.py` / `install.ps1` 由 Lua 写文件时加 BOM（PowerShell 5 读中文要用），
  所以 `src\` 里的源码是干净的、不带 BOM。`tools\embed.py` 会拒绝带 BOM 的源文件。
- **长括号**：源码里不能出现 `]==]`，会把内嵌块提前截断（embed.py 会拦）。
- **行尾**：全仓库用 LF（Lua 和 Python 都一样），别让编辑器改成 CRLF。
- **路径**：Lua 部分用 LuaJIT 的 FFI 调 `CreateProcessW` 启动外部程序，不经过 cmd（不弹黑窗）；
  中文路径靠宽字符传，没问题。但测试用的 lupa（LuaJIT 内核）跑的是标准 `io` 库，
  打不开含中文的路径，所以测试用的临时文件都放在纯英文的 `%TEMP%` 下，
  个别测试（`test_show.py`）干脆把 Lua 的 `io.open` 换成用 Python 开文件。
- **组件目录可以整个删掉**：`D:\Video\Aegisub-3.4.2\zhouxiao-autotime\` 里有 `env`（Python 环境）、
  `models`（人声分离 + whisper base）、`kara_pack`（卡拉OK模板）、以及用户数据
  （`ai.json` 的 Key、`fx_presets.json`、`lead.txt` 提前量）。卸载 = 删文件夹，
  重装会在下次用的时候自动弹窗下载。

## 授权

**LGPL-3.0-or-later**（GNU 宽通用公共许可证第 3 版或更新版本），条文见 [LICENSE](LICENSE)；
LGPLv3 附加引用的 GNU GPL v3 条文见 [LICENSE.GPL-3.0](LICENSE.GPL-3.0)。

**另有署名条款**（依 LGPLv3 第 3 条引入的 GPLv3 第 7(b) 条）：分发本作品或其修改版时，
必须保留「原作者：zzzwannasleep」字样、不得抹去或改写；修改版还必须标明已修改及修改日期
（GPLv3 第 5(a) 条），并且不得暗示是原作者的版本。具体见 [NOTICE](NOTICE)。

许可证管的是「能不能用、要不要开源」；署名条款管的是「改的人认不认人」——两者都要看。

## 备份与来源

- 官方版 Aegisub 3.4.2 备份在 `D:\Video\_dl\backup-official-3.4.2`，增强版装在 `D:\Video\Aegisub-3.4.2`。
- 这仓库建立于 2026-10-01，从当时线上的 0.24 逐字节抽出（`tools\selftest.py` 里的
  「塞回 lua 后逐字节一致」就是保证这件事）。
- 更早的开发和验证记录在 `C:\Users\65282\.claude\projects\D--Video\memory\`，
  其中 `zhouxiao-fx-workbench.md` 是最完整的一份（版本 0.19~0.24 的经验和结论）。
  那个 scratchpad 是临时目录，随时会被清掉，能搬的都应该往这仓库搬。
- 用户数据和测试素材在 `D:\Video\轴效测试\`（含测试说明和真实番剧基准）。
