-- 轴效：打轴 + 特效字幕
--
-- Copyright (C) 2026 zzzwannasleep
-- 原作者：zzzwannasleep（https://github.com/zzzwannasleep/AegisubPlugin）
--
-- 本程序是自由软件：你可以按 GNU 宽通用公共许可证（LGPL）第 3 版或更新版本的条款
-- 再分发和/或修改它。本程序按「现状」提供，不附带任何担保。
-- 条文见 LICENSE / LICENSE.GPL-3.0；出处与附加的署名要求见 NOTICE。
--
-- 只管各组通用的结构（对照 Haruhana / 喵萌 / 绿茶 / smzase 的成品）：
--   中日分样式、各自一行、时间相同，日文贴边、中文在里；次要台词用一对顶部样式；
--   OP/ED/插曲 歌词各一对中日样式；注释、屏字各一个样式
-- 字体、颜色、描边这些每部作品不一样：有样式方案就从方案拿（见下面「样式方案」），没有就照抄 Default，在样式管理器里改
-- 流程：1 导入日文 txt、1 导入中文 txt（各导一次，各是一组行）→ 打日文轴 → 5 同步时间给中文
--       → 2 主次 / 歌词 → 3 注释 / 4 屏字 → 7 特效样式 / 8 卡拉OK特效 / 9 AI 助手（同一个工作台窗口）→ 发布
-- 中日靠顺序对应：日文第 N 句 ↔ 中文第 N 句（按样式分中/日，不管在文件哪里）
script_name = "轴效"
script_description = "导入 txt / 主次与歌词 / 注释 / 屏字 / 同步中日时间 / 歌词定位 / 特效工作台（特效样式、卡拉OK、AI 助手）"
script_author = "轴效"
script_version = "0.24"

-- 名字, 对齐, 字号(占画面高的比例), 垂直边距(同)
-- 比例取的是几个组的大致中间值，只为了开箱能看，具体作品自己调
local STYLES = {
  {"Text CN", 2, 0.065, 0.045},
  {"Text JP", 2, 0.040, 0.010},
  {"Text CN Top", 8, 0.065, 0.045},
  {"Text JP Top", 8, 0.040, 0.010},
  -- 歌词：各组位置不统一，这里取多数（日文顶部、中文底部），按作品改
  {"OP CN", 2, 0.055, 0.030},
  {"OP JP", 8, 0.045, 0.030},
  {"ED CN", 2, 0.055, 0.030},
  {"ED JP", 8, 0.045, 0.030},
  -- 插曲常和对白同时出现，各组都挪到顶部角上、中日叠在一起；左上给了 Note，这里放右上
  {"Insert CN", 9, 0.045, 0.060},
  {"Insert JP", 9, 0.035, 0.020},
  {"Note", 7, 0.045, 0.020},
  {"Screen", 5, 0.060, 0},
}
-- 成对的中日样式，按「类」分：主要、次要、OP、ED、插曲
local KINDS = {
  main = {"Text CN", "Text JP"},
  top = {"Text CN Top", "Text JP Top"},
  op = {"OP CN", "OP JP"},
  ed = {"ED CN", "ED JP"},
  insert = {"Insert CN", "Insert JP"},
}
local PAIR, SIDE = {}, {} -- PAIR: 中文样式 → 日文样式；SIDE: 样式 → 1 中 / 2 日
for _, k in pairs(KINDS) do
  PAIR[k[1]] = k[2]
  SIDE[k[1]], SIDE[k[2]] = 1, 2
end

-- 中/日两边的对白行（跳过歌词定位的辅助行），按文件里的顺序；第 k 个中文 ↔ 第 k 个日文
local function sides(subs)
  local cn, jp = {}, {}
  for i = 1, #subs do
    local l = subs[i]
    if l.class == "dialogue" and l.effect == "" and SIDE[l.style] then
      local t = SIDE[l.style] == 1 and cn or jp
      t[#t + 1] = i
    end
  end
  return cn, jp
end

local function play_res(subs)
  local w, h = 1920, 1080
  for i = 1, #subs do
    local l = subs[i]
    if l.class == "info" then
      if l.key == "PlayResX" then w = tonumber(l.value) or w end
      if l.key == "PlayResY" then h = tonumber(l.value) or h end
    end
  end
  return w, h
end

local function json_str(s) return '"' .. s:gsub('\\', '\\\\'):gsub('"', '\\"') .. '"' end
local function exists(p)
  local f = io.open(p, "rb")
  if f then f:close() return true end
end
local function write_file(p, s)
  local f = assert(io.open(p, "wb"))
  f:write(s)
  f:close()
end
-- 启动外部程序不经过 cmd（os.execute 每次都闪一个黑窗口，start /wait 还一直挂着）：
-- 用 LuaJIT 的 FFI 直接调 Windows 的 CreateProcessW，路径是宽字符，中文路径也没问题
local ffi = require "ffi"
pcall(ffi.cdef, [[
typedef struct { uint32_t cb; void *r1, *desktop, *title; uint32_t x, y, w, h, cx, cy, fill, flags;
  uint16_t show, r2; void *r3, *hin, *hout, *herr; } ZX_SI;
typedef struct { void *process, *thread; uint32_t pid, tid; } ZX_PI;
int MultiByteToWideChar(unsigned int cp, uint32_t flags, const char *s, int n, uint16_t *w, int wn);
int CreateProcessW(const uint16_t *app, uint16_t *cmd, void *pa, void *ta, int inherit, uint32_t flags,
  void *env, const uint16_t *cwd, ZX_SI *si, ZX_PI *pi);
uint32_t WaitForSingleObject(void *h, uint32_t ms);
int GetExitCodeProcess(void *h, uint32_t *code);
int TerminateProcess(void *h, unsigned int code);
int CloseHandle(void *h);
int CreateDirectoryW(const uint16_t *path, void *sa);
]])
local function wide(s)
  local n = ffi.C.MultiByteToWideChar(65001, 0, s, #s, nil, 0)
  local w = ffi.new("uint16_t[?]", n + 1)
  ffi.C.MultiByteToWideChar(65001, 0, s, #s, w, n)
  return w
end
local function mkdir(p) ffi.C.CreateDirectoryW(wide(p), nil) end

-- 等它跑完，返回退出码（启动失败返回 nil）。console=true 给它开一个窗口（安装时要看下载进度）；
-- poll 每 0.2 秒调一次，返回 true 就结束那个程序（用户在 Aegisub 进度框里点了取消）
local function spawn(cmdline, opts)
  opts = opts or {}
  local si, pi = ffi.new("ZX_SI"), ffi.new("ZX_PI")
  si.cb = ffi.sizeof(si)
  local flags = opts.console and 0x10 or 0x08000000 -- CREATE_NEW_CONSOLE / CREATE_NO_WINDOW
  if ffi.C.CreateProcessW(nil, wide(cmdline), nil, nil, 0, flags, nil, nil, si, pi) == 0 then return nil end
  while ffi.C.WaitForSingleObject(pi.process, 200) ~= 0 do
    if opts.poll and opts.poll() then ffi.C.TerminateProcess(pi.process, 1) end
  end
  local code = ffi.new("uint32_t[1]")
  ffi.C.GetExitCodeProcess(pi.process, code)
  ffi.C.CloseHandle(pi.process)
  ffi.C.CloseHandle(pi.thread)
  return code[0]
end


-- 样式方案 = 样式 + 特效配方。样式存在 Aegisub 样式管理器的「样式库」文件（catalog\名字.sty），特效配方在
-- 旁边的 名字.fx.json（工作台用）。插件建样式时先从当前字幕用的方案拿。
-- 同一个样式可以有「编号专用」的版本，叫「ED CN #05」（编号可以是集数、期数……），字幕编号是 5 时先用它；
-- 字幕文件头记着用哪个方案、编号是几（ZX_Catalog / ZX_Number）
local function catalog_dir()
  return aegisub.decode_path("?user"):gsub("/", "\\"):gsub("\\$", "") .. "\\catalog"
end

local function info_get(subs, key)
  for i = 1, #subs do
    local l = subs[i]
    if l.class == "info" then
      if l.key == key then return l.value end
    elseif l.class ~= "unknown" then
      return nil
    end
  end
end

-- 返回插了几行（插了新行，后面的行号要跟着挪）
local function info_set(subs, key, value)
  local last
  for i = 1, #subs do
    local l = subs[i]
    if l.class == "info" then
      last = i
      if l.key == key then
        l.value = value
        subs[i] = l
        return 0
      end
    elseif last then
      break
    end
  end
  subs.insert((last or 0) + 1, {class = "info", section = "[Script Info]", key = key, value = value})
  return 1
end

local function norm(s) return (s or ""):lower():gsub("[%s%p]", "") end

-- 方案列表（不含 Aegisub 自带的 Default 和插件自带的「轴效起步」）
local function list_catalogs()
  local ok, lfs = pcall(require, "lfs")
  local out = {}
  if ok and lfs then
    pcall(function()
      for f in lfs.dir(catalog_dir()) do
        local n = f:match("^(.*)%.[Ss][Tt][Yy]$")
        if n and n ~= "Default" and n ~= "轴效起步" then out[#out + 1] = n end
      end
    end)
  end
  table.sort(out)
  return out
end

local function read_aliases()
  local t = {}
  local f = io.open(catalog_dir() .. "\\zhouxiao-alias.tsv", "rb")
  if f then
    for l in f:lines() do
      local a, b = l:match("^([^\t]+)\t([^\r]+)")
      if a then t[#t + 1] = {a, b} end
    end
    f:close()
  end
  return t
end

-- 视频文件名 → 标题部分（去掉方括号里的发布者 / 规格、编号）；和 fxedit.py 的 title_stem 同一个意思
local function title_stem(video)
  local n = (video or ""):match("([^\\/]+)$") or ""
  n = n:gsub("%.[^.]+$", ""):gsub("%b[]", " "):gsub("%b()", " "):gsub("【.-】", " ")
  local cut = #n + 1
  for _, pat in ipairs({" %- ?%d", "[Ss]%d+[Ee]%d", " [Ee]%d", "第%s*%d"}) do
    local i = n:find(pat)
    if i and i < cut then cut = i end
  end
  return (n:sub(1, cut - 1):gsub("[%s._]+", " "):gsub("^[%s%-]+", ""):gsub("[%s%-]+$", ""))
end

-- 记住「这种视频文件名 → 这个方案」，同系列的下一个视频自动认出来
local function add_alias(video, catalog)
  local stem = title_stem(video)
  if stem == "" then return end
  local rows = {}
  for _, r in ipairs(read_aliases()) do if r[1] ~= stem then rows[#rows + 1] = r[1] .. "\t" .. r[2] end end
  rows[#rows + 1] = stem .. "\t" .. catalog
  mkdir(catalog_dir())
  write_file(catalog_dir() .. "\\zhouxiao-alias.tsv", table.concat(rows, "\n") .. "\n")
end

local function guess_catalog(video)
  local v = norm((video or ""):match("([^\\/]+)$"))
  if v == "" then return nil end
  local best, len = nil, 0
  for _, r in ipairs(read_aliases()) do
    local a = norm(r[1])
    if #a > len and v:find(a, 1, true) then best, len = r[2], #a end
  end
  for _, n in ipairs(list_catalogs()) do
    local a = norm(n)
    if #a > len and v:find(a, 1, true) then best, len = n, #a end
  end
  return best
end

-- 文件名里的编号（集数、期数）：S01E05 / " - 05" / [05] / 第5 / E05
local function guess_number(video)
  local n = (video or ""):match("([^\\/]+)$") or ""
  for _, pat in ipairs({"[Ss]%d+[Ee](%d+)", " %- ?(%d%d?%d?)[^%d]", "%[(%d%d?%d?)[vV]?%d?%]", "第%s*(%d+)",
                        " [Ee][Pp]?(%d%d?%d?)[^%d]"}) do
    local e = n:match(pat)
    if e then return tonumber(e) end
  end
  return 0
end

-- → 方案名（nil = 不用方案）, 编号, 在文件头插了几行, 是不是字幕里已经记着的
-- ask=true 且字幕里没记：弹一次框问（默认填按视频文件名猜的），记进字幕文件头
local function resolve_catalog(subs, ask)
  local cat = info_get(subs, "ZX_Catalog")
  if cat then
    return cat ~= "-" and cat or nil, tonumber(info_get(subs, "ZX_Number") or "") or 0, 0, true
  end
  local ok, p = pcall(aegisub.project_properties)
  local video = ok and p and p.video_file or ""
  local gcat, gnum = guess_catalog(video), guess_number(video)
  if not ask then return gcat, gnum, 0, false end
  local none = "不用方案"
  local items = {none}
  for _, n in ipairs(list_catalogs()) do items[#items + 1] = n end
  local btn, res = aegisub.dialog.display({
    {class = "label", x = 0, y = 0, label = " 样式方案 "},
    {class = "dropdown", name = "catalog", items = items, value = gcat or none, x = 1, y = 0, width = 2},
    {class = "label", x = 3, y = 0, label = "   新建方案 "},
    {class = "edit", name = "new", value = gcat and "" or title_stem(video), x = 4, y = 0, width = 4},
    {class = "label", x = 8, y = 0, label = "   编号 "},
    {class = "intedit", name = "num", value = gnum, min = 0, max = 999, x = 9, y = 0},
  }, {"确定", "取消"})
  if btn ~= "确定" then aegisub.cancel() end
  local new = res.new:gsub("^%s+", ""):gsub("%s+$", ""):gsub('[\\/:*?"<>|]', "")
  -- 下拉选了已有的就用它；停在「不用方案」时，新建框有名字就新建，清空就是不用
  local c = res.catalog ~= none and res.catalog or (new ~= "" and new) or "-"
  if c ~= "-" then
    mkdir(catalog_dir())
    if not exists(catalog_dir() .. "\\" .. c .. ".sty") then write_file(catalog_dir() .. "\\" .. c .. ".sty", "\239\187\191") end
    if video ~= "" then add_alias(video, c) end
  end
  local n = info_set(subs, "ZX_Catalog", c) + info_set(subs, "ZX_Number", tostring(res.num))
  return c ~= "-" and c or nil, res.num, n, true
end

-- 样式库 → {样式名 = 字段表}
local function load_catalog(catalog)
  local t = {}
  local f = catalog and io.open(catalog_dir() .. "\\" .. catalog .. ".sty", "rb")
  if not f then return t end
  for l in f:lines() do
    local body = l:gsub("^\239\187\191", ""):match("^Style:%s*([^\r]*)")
    if body then
      local p = {}
      for x in (body .. ","):gmatch("([^,]*),") do p[#p + 1] = x end
      if #p >= 23 then t[p[1]] = p end
    end
  end
  f:close()
  return t
end

-- 样式库里的一行 → Aegisub 的样式表（没写到的字段照抄 base）
local function style_from_catalog(base, p, name)
  local st = {}
  for k, v in pairs(base) do st[k] = v end
  local col = function(x) return x:match("&$") and x or x .. "&" end
  local b = function(x) return (tonumber(x) or 0) ~= 0 end
  st.name, st.fontname, st.fontsize = name, p[2], tonumber(p[3])
  st.color1, st.color2, st.color3, st.color4 = col(p[4]), col(p[5]), col(p[6]), col(p[7])
  st.bold, st.italic, st.underline, st.strikeout = b(p[8]), b(p[9]), b(p[10]), b(p[11])
  st.scale_x, st.scale_y, st.spacing, st.angle = tonumber(p[12]), tonumber(p[13]), tonumber(p[14]), tonumber(p[15])
  st.borderstyle, st.outline, st.shadow, st.align = tonumber(p[16]), tonumber(p[17]), tonumber(p[18]), tonumber(p[19])
  st.margin_l, st.margin_r, st.margin_t, st.encoding = tonumber(p[20]), tonumber(p[21]), tonumber(p[22]), tonumber(p[23])
  st.margin_b = st.margin_t
  return st
end

-- 缺的样式补上：先从当前字幕用的样式方案拿（编号专用 > 通用），没有才照 Default 复制、只改对齐/字号/边距（已有的不动）；
-- 返回在前面插了几行（样式 + 文件头），事件行下标整体后移这么多
local function ensure_styles(subs)
  local have, base, last = {}, nil, nil
  for i = 1, #subs do
    local l = subs[i]
    if l.class == "style" then
      have[l.name] = true
      last = i
      if not base or l.name == "Default" then base = l end
    end
  end
  if not base then
    aegisub.log(0, "文件里一个样式都没有，先随便建一个 Default\n")
    aegisub.cancel()
  end
  local missing = {}
  for _, s in ipairs(STYLES) do if not have[s[1]] then missing[#missing + 1] = s end end
  if #missing == 0 then return 0 end
  local cat, num, shifted = resolve_catalog(subs, true)
  last = last + shifted
  local lib = load_catalog(cat)
  local _, h = play_res(subs)
  local n = 0
  for _, s in ipairs(missing) do
    local p = (num > 0 and lib[string.format("%s #%02d", s[1], num)]) or lib[s[1]]
    local st
    if p then
      st = style_from_catalog(base, p, s[1])
    else
      st = {}
      for key, v in pairs(base) do st[key] = v end
      st.name, st.align = s[1], s[2]
      st.fontsize = math.floor(h * s[3] + 0.5)
      st.margin_t = math.floor(h * s[4] + 0.5)
      st.margin_b = st.margin_t
    end
    n = n + 1
    subs.insert(last + n, st)
  end
  return n + shifted
end

local function shift(sel, n)
  local t = {}
  for k, i in ipairs(sel) do t[k] = i + n end
  return t
end

-- ponytail: 只认 UTF-8，GBK 的 txt 会乱码；真遇到再加转码
local function read_lines(path)
  local f = assert(io.open(path, "rb"))
  local s = f:read("*a")
  f:close()
  s = s:gsub("^\239\187\191", "")
  local t = {}
  for raw in (s .. "\n"):gmatch("(.-)\r?\n") do
    local line = raw:gsub("^%s+", ""):gsub("%s+$", "")
    if line ~= "" then t[#t + 1] = line end
  end
  return t
end

local function pick_txt(title)
  local f = aegisub.dialog.open(title, "", "", "文本 (*.txt)|*.txt", false, true)
  if not f then aegisub.cancel() end
  return f
end

-- 有三成以上的行带假名就算日文（平假名 / 片假名在 UTF-8 里是 E3 81 81 ~ E3 83 BF）
local function is_japanese(lines)
  local n = 0
  for _, l in ipairs(lines) do
    if l:find("\227[\129-\131][\128-\191]") then n = n + 1 end
  end
  return n > #lines * 0.3
end

-- 一个 txt 导成一组行：日文 → Text JP（layer 0），中文 → Text CN（layer 1）
-- times[i] = {开始, 结束, 待查原因}，没有就是 0
-- 同一个 txt 已经导过（这一边现有的句子和它一句不差）就不重复加：有 times 就把时间填进原来那些行
-- 返回 true = 新加了一组；false = 原来就有
local function append_lines(subs, lines, jp, times)
  ensure_styles(subs)
  local cn, jl = sides(subs)
  local mine = jp and jl or cn
  if #mine == #lines and #lines > 0 then
    local same = true
    for k, i in ipairs(mine) do
      if subs[i].text ~= lines[k] then same = false break end
    end
    if same then
      for k, i in ipairs(times and mine or {}) do
        local l, t = subs[i], times[k]
        l.start_time, l.end_time = t[1], t[2]
        l.actor = t[3] ~= "" and ("待查:" .. t[3]) or ""
        subs[i] = l
      end
      return false
    end
  end
  for i, text in ipairs(lines) do
    local t = times and times[i] or {0, 0, ""}
    subs.append({
      class = "dialogue", section = "[Events]", comment = false, layer = jp and 0 or 1,
      start_time = t[1], end_time = t[2], style = jp and "Text JP" or "Text CN", effect = "",
      actor = t[3] ~= "" and ("待查:" .. t[3]) or "",
      margin_l = 0, margin_r = 0, margin_t = 0, margin_b = 0, text = text,
    })
  end
  return true
end

-- 1. 导入一个 txt（中文日文都行，自动认），时间全是 0。中日各导一次
local function import_txt(subs)
  local lines = read_lines(pick_txt("选 txt（中文或日文，一次一个）"))
  local jp = is_japanese(lines)
  if not append_lines(subs, lines, jp) then
    aegisub.log(3, "这份%s txt 文件里已经有了（一句不差），没有重复导入\n", jp and "日文" or "中文")
    return
  end
  local cn, jl = sides(subs)
  aegisub.log(3, "认成%s，导入 %d 行（%s）。现在文件里：日文 %d 句，中文 %d 句%s\n",
    jp and "日文" or "中文", #lines, jp and "Text JP" or "Text CN", #jl, #cn,
    (#jl > 0 and #cn > 0 and #jl ~= #cn) and "——句数对不上，同步时间前先查漏行" or "")
end

-- 1. 导入 txt + 自动粗轴：whisper 拿原文（日文或中文，自动认）对齐音频（脚本在文件末尾 AUTOTIME_PY），你再细调
-- 另一边可以也粗轴，或者用「1 导入 txt」导进来再「5 同步时间」
-- 对不准的句子在「说话人」栏写「待查:原因」，按说话人排序就能先看这些
local AUTOTIME_PY, INSTALL_PS1, FXEDIT_PY, ZXCORE_PY, ZXAI_PY -- 在文件末尾，太长放后面

-- 日志最后一行（tqdm 进度条用 \r 刷新，也拆开）
local function last_line(path)
  local f = io.open(path, "rb")
  if not f then return nil end
  local s = f:read("*a")
  f:close()
  local last
  for l in s:gmatch("[^\r\n]+") do if l:find("%S") then last = l end end
  return last, s
end

-- 组件（独立 Python 环境 + 模型）装在这里，卸载 = 删掉这个文件夹
local function zx_home()
  local h = aegisub.decode_path("?user"):gsub("/", "\\"):gsub("\\$", "") .. "\\zhouxiao-autotime"
  -- Windows 命令行传不了中文路径（系统用户名是中文时 ?user 会带中文），这时退到 ProgramData
  if h:find("[\128-\255]") then h = (os.getenv("ProgramData") or "C:\\ProgramData") .. "\\zhouxiao-autotime" end
  return h
end

-- 没装就弹窗问要不要下载；装好了返回组件目录
-- lite = 只要 Python 环境 + 卡拉OK模板引擎（特效工作台用），不下粗轴的模型和 torch
local function ensure_installed(lite)
  local home = zx_home()
  mkdir(home)
  write_file(home .. "\\autotime.py", AUTOTIME_PY)          -- 每次都覆盖，插件更新了脚本跟着更新
  write_file(home .. "\\fxedit.py", FXEDIT_PY)
  write_file(home .. "\\zxcore.py", ZXCORE_PY)
  write_file(home .. "\\zxai.py", ZXAI_PY)
  write_file(home .. "\\install.ps1", "\239\187\191" .. INSTALL_PS1) -- 带 BOM，不然 PowerShell 5 读中文乱码
  -- lite2：0.19 起工作台多要一个 lupa（在 Python 里跑 Aegisub 的卡拉OK模板），老的 lite.txt / ok.txt 不算数
  local mark = home .. (lite and "\\lite2.txt" or "\\ok.txt")
  if exists(mark) then return home end
  local has_env = exists(home .. "\\env\\Scripts\\python.exe")
  local btn = aegisub.dialog.display({
    {class = "label", x = 0, y = 0, label = (lite and (has_env
      and "特效工作台要补装一个小组件（lupa，约 5MB，用来跑卡拉OK模板）。\n\n"
      or ("特效工作台第一次用，要下载一套独立的 Python 环境（下载约 40MB，不影响你电脑上已有的）。\n"
      .. "以后要用自动粗轴，再补下模型就行，这部分不会重下。\n\n"))
      or ("自动粗轴第一次用，要下载组件（下载约 600MB，装完占 1.2GB）：\n"
      .. "  · 一套独立的 Python 环境（不影响你电脑上已有的）\n"
      .. "  · 人声分离模型（UVR MDX-Net）+ 对齐模型（whisper base）\n\n"
      .. "需要独立显卡（N 卡 / A 卡都行）。\n"))
      .. "装在：" .. home .. "\n不想要了直接删这个文件夹。\n\n"
      .. "点「下载安装」会弹一个窗口显示下载进度，装完按回车关掉它，再回来接着用。"},
  }, {"下载安装", "取消"})
  if btn ~= "下载安装" then aegisub.cancel() end
  -- 安装要看下载进度，这里特意开窗口
  spawn(string.format('powershell -NoProfile -ExecutionPolicy Bypass -File "%s\\install.ps1"%s', home,
    lite and " -Lite" or ""), {console = true})
  if not exists(mark) then
    aegisub.log(0, "组件没装好，看安装窗口里的提示。网络问题的话开代理再点一次，下好的部分不会重下\n")
    aegisub.cancel()
  end
  return home
end

local function import_autotime(subs)
  local ok, p = pcall(aegisub.project_properties)
  local video = ok and p and p.video_file
  if not video or video == "" then
    aegisub.log(0, "先打开视频（视频 → 打开视频），粗轴要从视频里取音频\n")
    aegisub.cancel()
  end
  local home = ensure_installed()
  local ja = pick_txt("选 txt（日文或中文，一次一个）")
  local jl = read_lines(ja)
  local jp = is_japanese(jl)
  -- 开头提前量记在组件目录里，下次打开还是上次填的（各组习惯不同，填一次就行）
  local lead_file = home .. "\\lead.txt"
  local lf = io.open(lead_file, "rb")
  local lead = lf and tonumber(lf:read("*a")) or 0.2
  if lf then lf:close() end
  local btn, res = aegisub.dialog.display({
    {class = "label", label = " 类型 ", x = 0, y = 0},
    {class = "dropdown", name = "what", items = {"对白", "歌词"}, value = "对白", x = 1, y = 0},
    {class = "checkbox", name = "vocals", value = true, x = 2, y = 0, label = "分离人声   "},
    {class = "label", label = "对白提前 (s) ", x = 3, y = 0},
    {class = "floatedit", name = "lead", value = lead, min = 0, max = 1, step = 0.05, x = 4, y = 0},
  })
  if not btn then aegisub.cancel() end
  write_file(lead_file, string.format("%.2f", res.lead))
  -- 视频、txt 的路径全放进 json，命令行里只剩组件目录这种纯英文路径
  local job, out, log = home .. "\\job.json", home .. "\\times.tsv", home .. "\\autotime.log"
  os.remove(out)
  os.remove(log)
  write_file(job, string.format('{"video": %s, "ja_txt": %s, "out_tsv": %s, "vocals": %s, "lyrics": %s, "lead": %.2f, '
    .. '"lang": "%s", "log": %s}', json_str(video), json_str(ja), json_str(out), res.vocals and "true" or "false",
    res.what == "歌词" and "true" or "false", res.lead, jp and "ja" or "zh", json_str(log)))
  -- 不开黑窗口：进度写在日志里，这里读最后一行显示在 Aegisub 的进度框，点「取消」就停
  aegisub.progress.title(jp and "自动粗轴（日文）" or "自动粗轴（中文）")
  local cancelled = false
  spawn(string.format('"%s\\env\\Scripts\\python.exe" "%s\\autotime.py" --job "%s"', home, home, job), {poll = function()
    local l = last_line(log)
    if l then
      aegisub.progress.task(l)
      local pct = l:match("(%d+)%%")
      if pct then aegisub.progress.set(tonumber(pct)) end
    end
    cancelled = aegisub.progress.is_cancelled()
    return cancelled
  end})
  if cancelled then aegisub.cancel() end
  local r = io.open(out, "rb")
  if not r then
    local _, all = last_line(log)
    local tail = {}
    for l in (all or ""):gmatch("[^\r\n]+") do tail[#tail + 1] = l end
    aegisub.log(0, "粗轴失败，没拿到结果。下面是报错（完整的在 %s），截图发给做插件的人：\n%s\n", log,
      table.concat(tail, "\n", math.max(1, #tail - 15)))
    aegisub.cancel()
  end
  local times = {}
  for line in r:lines() do
    local s, e, _, why = line:match("^(%d+)\t(%d+)\t([%d%.]+)\t?([^\r]*)")
    times[#times + 1] = {tonumber(s) or 0, tonumber(e) or 0, why or ""}
  end
  r:close()
  local added = append_lines(subs, jl, jp, times)
  local n = 0
  for _, t in ipairs(times) do if t[3] ~= "" then n = n + 1 end end
  aegisub.log(3, "%s粗轴完成：%d 句%s，其中 %d 句标了「待查」（看说话人栏）\n", jp and "日文" or "中文",
    #times, added and "" or "（这份之前导过，时间直接填进了原来那些行，没有新加）", n)
end

-- 2. 换类：主要 / 次要（顶部）/ OP / ED / 插曲。选中文或日文都行，对应的那一句跟着一起换
local function set_kind(kind)
  local to = KINDS[kind]
  return function(subs, sel)
    sel = shift(sel, ensure_styles(subs))
    local cn, jp = sides(subs)
    local other = {} -- 行号 → 对应那一句的行号（没有就是 false）
    for k, i in ipairs(cn) do other[i] = jp[k] or false end
    for k, i in ipairs(jp) do other[i] = cn[k] or false end
    local todo = {}
    for _, i in ipairs(sel) do
      if other[i] ~= nil then
        todo[i] = true
        if other[i] then todo[other[i]] = true end
      end
    end
    for i in pairs(todo) do
      local l = subs[i]
      l.style = to[SIDE[l.style]]
      subs[i] = l
    end
    return sel
  end
end

-- 5. 同步时间：打好轴的那边（通常是日文）第 N 句的时间复制给另一边第 N 句
local function sync_times(subs)
  local cn, jp = sides(subs)
  local function timed(t)
    local n = 0
    for _, i in ipairs(t) do if subs[i].end_time > 0 then n = n + 1 end end
    return n
  end
  local from, to, name = jp, cn, "日文 → 中文"
  if timed(cn) > timed(jp) then from, to, name = cn, jp, "中文 → 日文" end
  if #from == 0 or #to == 0 then
    aegisub.log(0, "中文、日文都要先导进来才能同步\n")
    aegisub.cancel()
  end
  -- 句数对不上就不同步：按顺序配对会整体错位，宁可停下让你先查
  if #from ~= #to then
    aegisub.log(0, "句数对不上：日文 %d 句，中文 %d 句，没有同步。\n"
      .. "常见原因：同一个 txt 导了两次（删掉多的那一份）、翻译漏了一句或多了一句（补上 / 删掉）。\n"
      .. "对齐之后再点一次。\n", #jp, #cn)
    aegisub.cancel()
  end
  for k = 1, #from do
    local a, b = subs[from[k]], subs[to[k]]
    b.start_time, b.end_time = a.start_time, a.end_time
    subs[to[k]] = b
  end
  aegisub.log(3, "同步完成（%s），%d 句\n", name, #from)
end

-- 屏字的时间：开着视频就从当前帧起 2 秒，没视频就照抄选中行
local function video_time()
  local ok, p = pcall(aegisub.project_properties)
  local f = ok and p and p.video_position
  if f and f > 0 then return aegisub.ms_from_frame(f) end
end

-- 在每个选中行下面插一行，选中新插的行方便直接改字
local function insert_after(style, text, layer)
  return function(subs, sel)
    sel = shift(sel, ensure_styles(subs))
    local out = {}
    for k = #sel, 1, -1 do
      local i = sel[k]
      local l = subs[i]
      l.style, l.actor, l.effect, l.layer = style, "", "", layer
      l.text = type(text) == "function" and text(subs) or text
      if style == "Screen" then
        local t = video_time()
        if t then l.start_time, l.end_time = t, t + 2000 end
      end
      subs.insert(i + 1, l)
      out[k] = i + k
    end
    return out
  end
end

-- 屏字默认放画面正中，改 \pos 或在视频上拖
local function center_pos(subs)
  local w, h = play_res(subs)
  return string.format("{\\pos(%d,%d)}屏字", w / 2, h / 2)
end

-- 6. 歌词定位：歌词放哪要看画面，所以不写死，让你在画面上拖，再吸附到辅助线写进样式
local MARK, GUIDE = "轴效定位", "轴效辅助线"
local SAFE = 0.05 -- 安全框离画面边 5%
local SNAP = 0.03 -- 离辅助线不到画面高的 3% 就吸上去
local LYRIC = {OP = "op", ED = "ed", ["插曲"] = "insert"}
local FOREVER = 36000000 -- 辅助行从 0 挂到 10 小时，拖到哪一帧都看得见

local function guide_xy(w, h)
  return {w * SAFE, w / 3, w / 2, w * 2 / 3, w * (1 - SAFE)}, {h * SAFE, h / 3, h / 2, h * 2 / 3, h * (1 - SAFE)}
end

local function clear_helpers(subs)
  for i = #subs, 1, -1 do
    local l = subs[i]
    if l.class == "dialogue" and (l.effect == GUIDE or l.effect:find("^" .. MARK)) then subs.delete(i) end
  end
end

local function helper(style, layer, effect, text)
  return {
    class = "dialogue", section = "[Events]", comment = false, layer = layer,
    start_time = 0, end_time = FOREVER, style = style, actor = "", effect = effect,
    margin_l = 0, margin_r = 0, margin_t = 0, margin_b = 0, text = text,
  }
end

local function styles_by_name(subs)
  local t = {}
  for i = 1, #subs do
    local l = subs[i]
    if l.class == "style" then t[l.name] = {i = i, st = l} end
  end
  return t
end

-- 样式的对齐 + 边距 → 定位点坐标
local function anchor(st, w, h)
  local col, row = (st.align - 1) % 3, math.floor((st.align - 1) / 3) -- row: 0 底 1 中 2 顶
  local x = col == 0 and st.margin_l or col == 1 and (st.margin_l + w - st.margin_r) / 2 or w - st.margin_r
  local y = row == 0 and h - st.margin_b or row == 1 and h / 2 or st.margin_t
  return x, y
end

-- 示例文字尽量用这类歌词的真句子，宽度才准
local function sample_text(subs, kind, side)
  for i = 1, #subs do
    local l = subs[i]
    if l.class == "dialogue" and l.effect == "" then
      if l.style == kind[side] then return (l.text:gsub("{[^}]*}", "")) end
    end
  end
  return side == 1 and "这是一句中文歌词示例" or "日本語の歌詞のサンプルです"
end

local function locate_start(subs)
  local btn, res = aegisub.dialog.display({
    {class = "label", label = "给哪类歌词定位：", x = 0, y = 0},
    {class = "dropdown", name = "k", items = {"OP", "ED", "插曲"}, value = "OP", x = 1, y = 0},
  })
  if not btn then aegisub.cancel() end
  ensure_styles(subs)
  clear_helpers(subs)
  local kind = KINDS[LYRIC[res.k]]
  local w, h = play_res(subs)
  local xs, ys = guide_xy(w, h)
  local t = math.max(1, math.floor(h / 540))
  local function rect(x1, y1, x2, y2)
    local f = math.floor
    return string.format("m %d %d l %d %d %d %d %d %d ", f(x1), f(y1), f(x2), f(y1), f(x2), f(y2), f(x1), f(y2))
  end
  local safe = rect(xs[1], ys[1], xs[5], ys[1] + t) .. rect(xs[1], ys[5] - t, xs[5], ys[5])
    .. rect(xs[1], ys[1], xs[1] + t, ys[5]) .. rect(xs[5] - t, ys[1], xs[5], ys[5])
  local mid = ""
  for k = 2, 4 do
    mid = mid .. rect(xs[k] - t / 2, 0, xs[k] + t / 2, h) .. rect(0, ys[k] - t / 2, w, ys[k] + t / 2)
  end
  local draw = "{\\an7\\pos(0,0)\\bord0\\shad0\\blur0\\alpha&H60&\\c&H%s&\\p1}%s"
  subs.append(helper(kind[1], 100, GUIDE, draw:format("00FFFF", safe))) -- 黄：安全框
  subs.append(helper(kind[1], 100, GUIDE, draw:format("FFFF00", mid)))  -- 青：中线和三分线
  local st = styles_by_name(subs)
  for side = 1, 2 do
    local s = st[kind[side]].st
    local x, y = anchor(s, w, h)
    subs.append(helper(kind[side], 101, MARK .. ":" .. res.k,
      string.format("{\\an%d\\pos(%d,%d)}%s", s.align, math.floor(x), math.floor(y), sample_text(subs, kind, side))))
  end
  aegisub.log(3, "在字幕列表最底下点中示例行，用左边工具栏的「拖动」工具拖到想放的位置。\n"
    .. "中文、日文两条都拖好以后，点「轴效 → 6 歌词定位：记录」。\n")
end

-- 文字框（屏幕坐标）
local function bbox(st, text)
  local x, y = text:match("\\pos%(([%d%.%-]+),([%d%.%-]+)%)")
  local an = tonumber(text:match("\\an(%d)")) or st.align
  local tw, th = aegisub.text_extents(st, (text:gsub("{[^}]*}", "")))
  x, y = tonumber(x), tonumber(y)
  local col, row = (an - 1) % 3, math.floor((an - 1) / 3)
  local l = col == 0 and x or col == 1 and x - tw / 2 or x - tw
  local t = row == 0 and y - th or row == 1 and y - th / 2 or y
  return {l = l, r = l + tw, t = t, b = t + th}
end

-- 候选 {边, 目标坐标} 里找离得最近、且在吸附距离内的
local function nearest(edges, cands, lim)
  local best
  for _, c in ipairs(cands) do
    local d = math.abs(edges[c[1]] - c[2])
    if d <= lim and (not best or d < best.d) then best = {e = c[1], to = c[2], d = d} end
  end
  return best
end

-- 吸附 → 定对齐方式和边距。other 是另一种语言已经定好的框，可以互相贴
local function place(bb, w, h, other)
  local xs, ys = guide_xy(w, h)
  local ex = {l = bb.l, c = (bb.l + bb.r) / 2, r = bb.r}
  local ey = {t = bb.t, m = (bb.t + bb.b) / 2, b = bb.b}
  local hc, vc = {}, {}
  for _, e in ipairs({"l", "c", "r"}) do
    for _, g in ipairs(xs) do hc[#hc + 1] = {e, g} end
  end
  for _, e in ipairs({"t", "m", "b"}) do
    for _, g in ipairs(ys) do vc[#vc + 1] = {e, g} end
  end
  if other then
    hc[#hc + 1] = {"l", other.l}
    hc[#hc + 1] = {"c", (other.l + other.r) / 2}
    hc[#hc + 1] = {"r", other.r}
    local gap = h * 0.01
    vc[#vc + 1] = {"b", other.t - gap} -- 贴在另一行上面
    vc[#vc + 1] = {"t", other.b + gap} -- 贴在另一行下面
  end
  local lim = h * SNAP
  local sx, sy = nearest(ex, hc, lim), nearest(ey, vc, lim)
  local dx, dy = sx and sx.to - ex[sx.e] or 0, sy and sy.to - ey[sy.e] or 0
  bb = {l = bb.l + dx, r = bb.r + dx, t = bb.t + dy, b = bb.b + dy}
  local cx, cy = (bb.l + bb.r) / 2, (bb.t + bb.b) / 2
  -- 没吸上的方向按所在区域定：左三分之一左对齐，右三分之一右对齐；上半顶对齐，下半底对齐
  local he = sx and sx.e or (cx < w / 3 and "l" or cx > w * 2 / 3 and "r" or "c")
  local ve = sy and sy.e or (cy < h / 2 and "t" or "b")
  if ve == "m" and math.abs(cy - h / 2) > 1 then ve = cy < h / 2 and "t" or "b" end -- 竖直居中只认正中线
  local col = ({l = 0, c = 1, r = 2})[he]
  local row = ({b = 0, m = 1, t = 2})[ve]
  local ml, mr = 0, 0
  if he == "l" then ml = bb.l
  elseif he == "r" then mr = w - bb.r
  elseif cx >= w / 2 then ml = 2 * cx - w
  else mr = w - 2 * cx end
  local mv = ve == "t" and bb.t or ve == "b" and h - bb.b or 0
  return {align = row * 3 + col + 1, ml = math.floor(ml + 0.5), mr = math.floor(mr + 0.5),
          mv = math.floor(mv + 0.5), bb = bb, sx = sx, sy = sy}
end

local EDGE = {l = "左边", c = "水平中线", r = "右边", t = "顶边", m = "竖直中线", b = "底边"}

local function locate_record(subs)
  local w, h = play_res(subs)
  local st = styles_by_name(subs)
  local marks = {}
  for i = 1, #subs do
    local l = subs[i]
    if l.class == "dialogue" and l.effect:find("^" .. MARK) then marks[#marks + 1] = l end
  end
  if #marks == 0 then
    aegisub.log(0, "没找到示例行，先点「6 歌词定位：开始」\n")
    aegisub.cancel()
  end
  local kind = KINDS[LYRIC[marks[1].effect:match(":(.*)$")]]
  local done = {}
  for side = 1, 2 do
    for _, l in ipairs(marks) do
      if l.style == kind[side] then
        local s = st[l.style]
        local p = place(bbox(s.st, l.text), w, h, side == 2 and done[1] or nil)
        done[side] = p.bb
        s.st.align, s.st.margin_l, s.st.margin_r, s.st.margin_t, s.st.margin_b = p.align, p.ml, p.mr, p.mv, p.mv
        subs[s.i] = s.st
        aegisub.log(3, "%s：对齐 %d，左边距 %d，右边距 %d，垂直边距 %d（%s，%s）\n", l.style, p.align, p.ml, p.mr, p.mv,
          p.sx and (EDGE[p.sx.e] .. "吸上了") or "水平没吸附",
          p.sy and (EDGE[p.sy.e] .. "吸上了") or "竖直没吸附")
      end
    end
  end
  clear_helpers(subs)
end

-- 7~9. 特效工作台：弹一个窗口（fxedit.py），三页：特效样式 / 卡拉OK / AI 助手，右边带声音预览所选行前后各 5 秒
-- 整份字幕导出给它（fx_dump.tsv），它把改动写成 fx_ops.tsv，这里照着改；整批一步撤销
local DUMP_STYLE = {"name", "fontname", "fontsize", "color1", "color2", "color3", "color4", "bold", "italic",
  "underline", "strikeout", "scale_x", "scale_y", "spacing", "angle", "borderstyle", "outline", "shadow", "align",
  "margin_l", "margin_r", "margin_t", "margin_b", "encoding"}
local DUMP_DIA = {"comment", "layer", "start_time", "end_time", "style", "actor", "margin_l", "margin_r",
  "margin_t", "margin_b", "effect", "text"}
local DUMP_STR = {name = true, fontname = true, style = true, actor = true, effect = true, text = true,
  color1 = true, color2 = true, color3 = true, color4 = true}
local DUMP_BOOL = {bold = true, italic = true, underline = true, strikeout = true, comment = true}

local function esc(v)
  if type(v) == "boolean" then return v and "1" or "0" end
  return (tostring(v):gsub("\\", "\\\\"):gsub("\t", "\\t"):gsub("\n", "\\n"))
end
local function unesc(s)
  return (s:gsub("\\(.)", function(c) return c == "t" and "\t" or c == "n" and "\n" or c end))
end
local function field(k, v)
  if DUMP_BOOL[k] then return v == "1" end
  if DUMP_STR[k] then return v end
  return tonumber(v) or 0
end

local function dump_subs(subs, path)
  local f = assert(io.open(path, "wb"))
  local n = #subs
  for i = 1, n do
    if i % 5000 == 0 then aegisub.progress.set(i / n * 100) end
    local l = subs[i]
    local row = {i, l.class}
    if l.class == "info" then
      row[3], row[4] = esc(l.key), esc(l.value)
    elseif l.class == "style" or l.class == "dialogue" then
      for _, k in ipairs(l.class == "style" and DUMP_STYLE or DUMP_DIA) do row[#row + 1] = esc(l[k]) end
    end
    f:write(table.concat(row, "\t"), "\n")
  end
  f:close()
end

local function new_dialogue(p, from)
  local l = {class = "dialogue", section = "[Events]", extra = {}}
  for k, name in ipairs(DUMP_DIA) do l[name] = field(name, p[from + k - 1] or "") end
  return l
end

-- 改动文件：set 行号 字段 值 / del 行号 / ins 在哪行后 + 整行字段 / style 整条样式（同名覆盖，没有就新加）
local function apply_ops(subs, path)
  local f = io.open(path, "rb")
  if not f then return false end
  local sets, dels, ins, styles, idx = {}, {}, {}, {}, {}
  for line in f:lines() do
    line = line:gsub("\r$", "")
    local p = {}
    for x in (line .. "\t"):gmatch("([^\t]*)\t") do p[#p + 1] = unesc(x) end
    local i = tonumber(p[2])
    if p[1] == "set" then
      sets[i] = sets[i] or {}
      sets[i][p[3]] = p[4]
      idx[i] = true
    elseif p[1] == "del" then
      dels[i], idx[i] = true, true
    elseif p[1] == "ins" then
      ins[i] = ins[i] or {}
      table.insert(ins[i], p)
      idx[i] = true
    elseif p[1] == "style" then
      styles[#styles + 1] = p
    elseif p[1] == "info" then
      idx.info = idx.info or {}
      table.insert(idx.info, p)
    end
  end
  f:close()
  local infos = idx.info or {}
  idx.info = nil
  local order = {}
  for i in pairs(idx) do order[#order + 1] = i end
  table.sort(order, function(a, b) return a > b end) -- 从后往前改，前面的行号不会变
  for _, i in ipairs(order) do
    for k = #(ins[i] or {}), 1, -1 do subs.insert(i + 1, new_dialogue(ins[i][k], 3)) end
    if sets[i] and not dels[i] then
      local l = subs[i]
      for k, v in pairs(sets[i]) do l[k] = field(k, v) end
      subs[i] = l
    end
    if dels[i] then subs.delete(i) end
  end
  for _, p in ipairs(styles) do
    local by, last, base = styles_by_name(subs), nil, nil
    for i = 1, #subs do if subs[i].class == "style" then last = i end end
    local old = by[p[2]]
    local st = {}
    for k, v in pairs(old and old.st or (by.Default or {st = subs[last]}).st) do st[k] = v end
    for k, name in ipairs(DUMP_STYLE) do st[name] = field(name, p[k + 1] or "") end
    if old then subs[old.i] = st else subs.insert(last + 1, st) end
  end
  for _, p in ipairs(infos) do info_set(subs, p[2], p[3]) end
  return true
end

local function workbench(tab)
  return function(subs, sel, active)
    local home = ensure_installed(true)
    local adir = aegisub.decode_path("?data"):gsub("/", "\\"):gsub("\\$", "")
    local vsf = adir .. "\\csri\\VSFilter.dll"
    if not exists(vsf) then
      aegisub.log(0, "没找到 %s，预览要用 Aegisub 自带的 VSFilter\n", vsf)
      aegisub.cancel()
    end
    local ok, p = pcall(aegisub.project_properties)
    local video = ok and p and p.video_file or ""
    local a = subs[active or sel[1] or 1]
    local t = video_time() or (a and a.class == "dialogue" and a.start_time) or 0
    local cat, num, _, saved = resolve_catalog(subs, false)
    local dump, job, out = home .. "\\fx_dump.tsv", home .. "\\fxjob.json", home .. "\\fx_ops.tsv"
    aegisub.progress.title("把字幕交给特效工作台……")
    dump_subs(subs, dump)
    os.remove(out)
    local s = {}
    for k, i in ipairs(sel) do s[k] = tostring(i) end
    write_file(job, string.format('{"tab": "%s", "dump": %s, "sel": [%s], "active": %d, "video": %s, "time": %d, '
      .. '"vsfilter": %s, "aegisub_dir": %s, "out": %s, "catalog_dir": %s, "catalog": %s, "number": %d, '
      .. '"catalog_saved": %s}', tab, json_str(dump), table.concat(s, ","), active or 0,
      json_str(video), t, json_str(vsf), json_str(adir), json_str(out), json_str(catalog_dir()),
      json_str(cat or ""), num, saved and "true" or "false"))
    aegisub.progress.title("特效工作台开着：关掉它再回来（点取消会直接关掉工作台，不应用）")
    spawn(string.format('"%s\\env\\Scripts\\pythonw.exe" "%s\\fxedit.py" --job "%s"', home, home, job),
      {poll = aegisub.progress.is_cancelled})
    if apply_ops(subs, out) then aegisub.set_undo_point("轴效特效工作台") end
  end
end

aegisub.register_macro("轴效/1 导入 txt", "导入一个 txt（自动认中文 / 日文），中日各导一次", import_txt)
aegisub.register_macro("轴效/1 导入 txt + 自动粗轴", "导入日文或中文，同时用 whisper 对齐出时间，你再细调", import_autotime)
aegisub.register_macro("轴效/2 设为主要（底部）", "换成 Text 样式", set_kind("main"))
aegisub.register_macro("轴效/2 设为次要（顶部）", "换成 Text Top 样式", set_kind("top"))
aegisub.register_macro("轴效/2 设为 OP 歌词", "换成 OP 样式", set_kind("op"))
aegisub.register_macro("轴效/2 设为 ED 歌词", "换成 ED 样式", set_kind("ed"))
aegisub.register_macro("轴效/2 设为插曲歌词", "换成 Insert 样式", set_kind("insert"))
aegisub.register_macro("轴效/3 加注释", "选中行下面插一条 Note，时间照抄", insert_after("Note", "注：", 2))
aegisub.register_macro("轴效/4 加屏字", "从视频当前帧插一条 Screen，放画面正中", insert_after("Screen", center_pos, 3))
aegisub.register_macro("轴效/5 同步时间（中日）", "打好轴那边的时间按顺序复制给另一边", sync_times)
aegisub.register_macro("轴效/6 歌词定位：开始", "铺辅助线，放中日两条示例让你拖", locate_start)
aegisub.register_macro("轴效/6 歌词定位：记录", "示例吸附到辅助线，写进歌词样式", locate_record)
aegisub.register_macro("轴效/6 歌词定位：取消", "删掉辅助线和示例，样式不动", clear_helpers)
aegisub.register_macro("轴效/7 特效样式", "预设套到所选行：淡入淡出、发光、双层描边、入场动画……带声音预览", workbench("fx"))
aegisub.register_macro("轴效/8 卡拉OK特效", "所选歌词自动打 \\k，套社区模板或自己的模板，预览后应用", workbench("kara"))
aegisub.register_macro("轴效/9 AI 助手", "接 OpenAI / Anthropic 接口，AI 直接读改字幕、写特效，预览后应用", workbench("ai"))

-- ===================================================================
-- 下面是自动粗轴要用的两个脚本，第一次用时写到组件目录里（见 ensure_installed）
-- ===================================================================

AUTOTIME_PY = [==[
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
]==]

FXEDIT_PY = [==[
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
        row("字体", self.font_cb, ttk.Label(f, text="打字筛选，↓ 展开", foreground="#888"))
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
        ttk.Button(bot, text="预览字体文件夹…", command=self.pick_fonts).pack(side="right", padx=8)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<space>", self.space)
        self.bind("<KeyPress-k>", self.key_k)
        self.bind("<KeyPress-K>", self.key_k)
        self.bind("<Control-z>", lambda e: self.typing() or self.cur_tab() is not self.ka or self.ka.tl.pop())
        self.state("zoomed")
        self.player.set_clip(*self.clip_range())
        self.edits_changed()
        self.after(30, self.poll)

    def fonts(self):
        if self._fonts is None:
            self._fonts = font_names(self)
        return self._fonts

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
        d = filedialog.askdirectory(title="选字体文件夹", parent=self,
                                    initialdir=self.settings.get("fonts_dir") or "")
        if d:
            n = z.load_fonts(d)
            self.settings["fonts_dir"] = d
            save_settings(self.settings)
            self._fonts = None
            self.measure = z.Measure()
            if self._kara:
                self._kara.measure = z.Measure()
            self.player.vsf.doc = None
            self.fx.changed()
            self.ka.changed()
            messagebox.showinfo("字体", f"加载了 {n} 个字体文件", parent=self)

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
]==]

ZXCORE_PY = [==[
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
]==]

ZXAI_PY = [==[
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
]==]

INSTALL_PS1 = [==[
# 轴效「自动粗轴」组件安装：在本脚本所在目录装一套独立的 Python 环境 + 两个模型
# 不碰系统里已有的 Python；卸载 = 删掉这个文件夹
# 两个模型和「uv → Python → 依赖」互不相干，一开始就在后台同时下；依赖包 uv 自己也是并行下的
param([switch]$Lite)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$base = $PSScriptRoot
Set-Location $base
$env:UV_PYTHON_INSTALL_DIR = "$base\python"
$env:UV_CACHE_DIR = "$base\cache"
$TUNA = 'https://pypi.tuna.tsinghua.edu.cn/simple'

function Step($m) { Write-Host "`n== $m" -ForegroundColor Cyan }
function Fetch($url, $out) { & curl.exe -L --fail --retry 2 -o $out $url | Out-Host; return ($LASTEXITCODE -eq 0) }
# 命令输出直接打到屏幕：不然会混进函数返回值，判断永远为真
function Run { & $args[0] @($args | Select-Object -Skip 1) | Out-Host; return ($LASTEXITCODE -eq 0) }

# 后台下载：返回进程，最后统一等
$bg = @()
function FetchBg($name, $url, $out) {
    if (Test-Path $out) { return }
    $p = Start-Process curl.exe -NoNewWindow -PassThru -ArgumentList @(
        '-sL', '--fail', '--retry', '3', '-o', "`"$base\$out.part`"", $url)
    $null = $p.Handle   # PowerShell 5 不先摸一下 Handle，进程退出后拿不到 ExitCode
    $script:bg += [pscustomobject]@{ Name = $name; Out = $out; Url = $url; Proc = $p }
    Write-Host "  后台开始下载：$name"
}

try {
    if (-not $Lite) { Remove-Item ok.txt -ErrorAction SilentlyContinue }
    if (-not $Lite) {
        Step '检查显卡'
        $gpus = @((Get-CimInstance Win32_VideoController).Name)
        $gpus | ForEach-Object { Write-Host "  $_" }
        if (-not ($gpus -match 'NVIDIA|AMD|Radeon|Arc')) {
            Write-Host '  没找到 N 卡 / A 卡 / Intel Arc 独显，人声分离会跑不动。继续装也行，但不推荐。' -ForegroundColor Yellow
        }

        Step '模型（后台同时下，不用等）'
        New-Item -ItemType Directory -Force models | Out-Null
        FetchBg '人声分离模型 UVR-MDX-NET-Voc_FT（67MB，GitHub）' `
            'https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/UVR-MDX-NET-Voc_FT.onnx' `
            'models\UVR-MDX-NET-Voc_FT.onnx'
        FetchBg '对齐模型 whisper base（139MB）' `
            'https://openaipublic.azureedge.net/main/whisper/models/ed3a0b6b1c0edf879ad9b11b1af5a0e6ab5db9205f891f668f8b0e6c6326e34e/base.pt' `
            'models\base.pt'
    }

    Step '下载 uv（用来装 Python 的小工具，走清华镜像）'
    if (-not (Test-Path uv.exe)) {
        # 清华 PyPI 上 uv 的 wheel 里就带着 uv.exe
        $whl = $null
        try {
            $page = (Invoke-WebRequest -UseBasicParsing "$TUNA/uv/").Content
            $href = ([regex]::Matches($page, 'href="([^"#]+-py3-none-win_amd64\.whl)') | Select-Object -Last 1).Groups[1].Value
            if ($href) { $whl = ([Uri]::new([Uri]"$TUNA/uv/", $href)).AbsoluteUri }
        } catch { }
        if (-not ($whl -and (Fetch $whl uv.zip))) {
            Write-Host '  清华镜像不行，改走 GitHub'
            if (-not (Fetch 'https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip' uv.zip)) {
                throw '下载 uv 失败'
            }
        }
        Expand-Archive uv.zip -DestinationPath uvtmp -Force
        Copy-Item (Get-ChildItem uvtmp -Recurse -Filter uv.exe | Select-Object -First 1).FullName uv.exe
        Remove-Item uv.zip, uvtmp -Recurse -Force
    }

    Step '装 Python 3.12'
    if (-not (Test-Path env\Scripts\python.exe)) {
        if (-not (Run .\uv.exe venv env --python 3.12)) {
            Write-Host '  GitHub 连不上，改走 npmmirror 镜像'
            $env:UV_PYTHON_INSTALL_MIRROR = 'https://registry.npmmirror.com/-/binary/python-build-standalone'
            if (-not (Run .\uv.exe venv env --python 3.12)) { throw '装 Python 失败' }
        }
    }

    Step '装依赖（torch / stable-ts / onnxruntime-directml / av，约 400MB，走清华镜像，多个包同时下）'
    $pkgs = if ($Lite) { @('av', 'lupa') } else { @('torch', 'stable-ts', 'onnxruntime-directml', 'av', 'lupa') }
    if (-not (Run .\uv.exe pip install --python env\Scripts\python.exe --default-index $TUNA @pkgs)) {
        Write-Host '  清华镜像不行，改走官方 PyPI'
        if (-not (Run .\uv.exe pip install --python env\Scripts\python.exe @pkgs)) { throw '装依赖失败' }
    }

    Step '等后台的模型下完'
    foreach ($d in $bg) {
        $d.Proc.WaitForExit()
        if ($d.Proc.ExitCode -ne 0) {
            Remove-Item "$($d.Out).part" -ErrorAction SilentlyContinue
            throw "$($d.Name) 下载失败。可以手动下载 $($d.Url) 放到 $base\$($d.Out)，再点一次"
        }
        Move-Item "$($d.Out).part" $d.Out -Force
        Write-Host "  好了：$($d.Name)"
    }

    Step '自检'
    if ($Lite) {
        if (-not (Run env\Scripts\python.exe -c 'import av, tkinter, lupa.luajit21')) { throw '自检没过' }
    } elseif (-not (Run env\Scripts\python.exe autotime.py --check)) { throw '自检没过' }
    Remove-Item cache -Recurse -Force -ErrorAction SilentlyContinue
    Set-Content lite2.txt 'ok'
    if (-not $Lite) { Set-Content ok.txt 'ok' }
    Write-Host "`n装好了。回到 Aegisub 继续。" -ForegroundColor Green
} catch {
    $bg | ForEach-Object { if (-not $_.Proc.HasExited) { $_.Proc.Kill() } }
    Write-Host "`n安装失败：$_" -ForegroundColor Red
    Write-Host '网络问题的话开代理再点一次，已经下好的部分不会重下。把这个窗口截图发给做插件的人也行。'
}
Read-Host '按回车关闭'
]==]
