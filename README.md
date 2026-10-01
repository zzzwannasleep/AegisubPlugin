# 轴效（Aegisub 插件）

字幕组「轴效」岗位用的 Aegisub 自动化插件：导入中日 txt、打轴、主次/歌词/注释/屏字、
自动粗轴、特效工作台（特效样式 / 卡拉OK / AI 助手）。

**当前版本 0.24**，跑在 arch1t3cht 增强版 Aegisub（`D:\Video\Aegisub-3.4.2`）。

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
tools\luaharness.py  测试用的 Aegisub API 模拟台
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

```bat
D:\Video\Aegisub-3.4.2\zhouxiao-autotime\env\Scripts\python.exe tools\selftest.py
```

不开 Aegisub 就把这些过一遍：源码三边一致、四段 Python 语法、组件环境自检（DirectML +
两个模型）、导入中日 txt（各自成行不合并、重复导入拒绝）、主次成对切换、同步时间
（含句数对不上时中止）、加注释/加屏字、歌词定位开始→记录→取消。

需要真窗口/真预览的部分（特效工作台的三页、AI 真接口、自动粗轴跑真实音频）还得在
Aegisub 里照 `D:\Video\轴效测试\测试说明.txt` 手测。

## 几个容易踩的地方

- **BOM**：`autotime.py` / `install.ps1` 由 Lua 写文件时加 BOM（PowerShell 5 读中文要用），
  所以 `src\` 里的源码是干净的、不带 BOM。`tools\embed.py` 会拒绝带 BOM 的源文件。
- **长括号**：源码里不能出现 `]==]`，会把内嵌块提前截断（embed.py 会拦）。
- **行尾**：全仓库用 LF（Lua 和 Python 都一样），别让编辑器改成 CRLF。
- **路径**：Lua 部分用 LuaJIT 的 FFI 调 `CreateProcessW` 启动外部程序，不经过 cmd（不弹黑窗）；
  中文路径靠宽字符传，没问题。但测试用的 `lupa` 跑的是 Lua 5.5，打不开中文路径，
  所以测试夹具都放在纯英文的临时目录里。
- **组件目录可以整个删掉**：`D:\Video\Aegisub-3.4.2\zhouxiao-autotime\` 里有 `env`（Python 环境）、
  `models`（人声分离 + whisper base）、`kara_pack`（卡拉OK模板）、以及用户数据
  （`ai.json` 的 Key、`fx_presets.json`、`lead.txt` 提前量）。卸载 = 删文件夹，
  重装会在下次用的时候自动弹窗下载。

## 备份与来源

- 官方版 Aegisub 3.4.2 备份在 `D:\Video\_dl\backup-official-3.4.2`，增强版装在 `D:\Video\Aegisub-3.4.2`。
- 这仓库建立于 2026-10-01，从当时线上的 0.24 逐字节抽出（`tools\selftest.py` 里的
  「塞回 lua 后逐字节一致」就是保证这件事）。
- 更早的开发和验证记录在 `C:\Users\65282\.claude\projects\D--Video\memory\`，
  其中 `zhouxiao-fx-workbench.md` 是最完整的一份（版本 0.19~0.24 的经验和结论）。
  那个 scratchpad 是临时目录，随时会被清掉，能搬的都应该往这仓库搬。
- 用户数据和测试素材在 `D:\Video\轴效测试\`（含测试说明和真实番剧基准）。
