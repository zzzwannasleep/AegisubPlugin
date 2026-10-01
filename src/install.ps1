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
