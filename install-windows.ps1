# proxy001 一键注册机 —— Windows 远程一键脚本
#
# 用法（PowerShell 里执行，无需先下载仓库）：
#   irm https://raw.githubusercontent.com/zhacha222/proxy001-register/main/install-windows.ps1 | iex
#
# 透传参数（数量 / 免询问）：用 PROXY001_ARGS 环境变量，因为 irm|iex
# 这种执行方式下脚本拿不到命令行参数（PowerShell 的已知行为）。
#   $env:PROXY001_ARGS="--count 3 --yes"
#   irm .../install-windows.ps1 | iex
#
# 也可先下载再运行（能看清内容更安全，参数可直接跟）：
#   irm https://raw.githubusercontent.com/zhacha222/proxy001-register/main/install-windows.ps1 -OutFile i.ps1
#   powershell -ExecutionPolicy Bypass -File i.ps1 --count 3 --yes
#
# 脚本会：检测 Python -> 建虚拟环境 -> 装依赖 -> 下载代码 -> 启动交互界面

$ErrorActionPreference = 'Stop'

$Repo    = if ($env:REPO)    { $env:REPO }    else { 'zhacha222/proxy001-register' }
$Branch  = if ($env:BRANCH)  { $env:BRANCH }  else { 'main' }
$WorkDir = if ($env:WORKDIR) { $env:WORKDIR } else { Join-Path $env:USERPROFILE '.proxy001-register' }

function Say($m)  { Write-Host $m }
function Ok($m)   { Write-Host "OK  " -ForegroundColor Green -NoNewline; Write-Host $m }
function Warn($m) { Write-Host "!!  " -ForegroundColor Yellow -NoNewline; Write-Host $m }
function Die($m)  { Write-Host "XX  " -ForegroundColor Red -NoNewline; Write-Host $m; exit 1 }

Write-Host ("=" * 58) -ForegroundColor Cyan
Write-Host "  proxy001 一键注册机  ·  远程安装器" -ForegroundColor Cyan
Write-Host ("=" * 58) -ForegroundColor Cyan
Write-Host ""

# ---------- 1. 找 Python ----------
$Py = $null
foreach ($cand in @('python', 'python3', 'py')) {
    $cmd = Get-Command $cand -ErrorAction SilentlyContinue
    if (-not $cmd) { continue }
    try {
        if ($cand -eq 'py') {
            $v = & py -3 -c "import sys;print(sys.version_info[0]*100+sys.version_info[1])" 2>$null
            if ($v -and [int]$v -ge 308) { $Py = @('py', '-3'); break }
        } else {
            $v = & $cand -c "import sys;print(sys.version_info[0]*100+sys.version_info[1])" 2>$null
            if ($v -and [int]$v -ge 308) { $Py = @($cand); break }
        }
    } catch { }
}

if (-not $Py) {
    Warn "未找到 Python 3.8+"
    Say "  尝试用 winget 自动安装..."
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        try {
            winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
            Say "安装完成，请【关闭并重新打开】PowerShell 后再次运行本脚本。"
        } catch {
            Die "winget 安装失败，请手动安装：https://www.python.org/downloads/"
        }
    } else {
        Die "请手动安装 Python 3.8+：https://www.python.org/downloads/  （安装时勾选 Add to PATH）"
    }
    exit 1
}

$PyExe = $Py[0]
$PyArgs = @()
if ($Py.Count -gt 1) { $PyArgs = $Py[1..($Py.Count - 1)] }

$verStr = (& $PyExe @PyArgs -V 2>&1) -join ' '
Ok "Python: $verStr"

# ---------- 2. venv ----------
New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
$Venv = Join-Path $WorkDir 'venv'
$VenvPy = Join-Path $Venv 'Scripts\python.exe'
$PyRun = $PyExe
$PyRunArgs = $PyArgs

if (-not (Test-Path $VenvPy)) {
    Say "  [*] 创建虚拟环境 $Venv"
    try {
        & $PyExe @PyArgs -m venv $Venv 2>$null
    } catch { }
}
if (Test-Path $VenvPy) {
    $PyRun = $VenvPy
    $PyRunArgs = @()
    Ok "解释器: $VenvPy"
} else {
    Warn "虚拟环境创建失败，改用当前环境"
    Ok "解释器: $PyExe"
}

# ---------- 3. 下载代码 ----------
$SrcDir = Join-Path $WorkDir 'src'
$RunPy = Join-Path $SrcDir 'run.py'

if ((Test-Path $RunPy) -and ($env:FORCE_UPDATE -ne '1')) {
    Say "  [*] 已存在代码目录，跳过下载（`$env:FORCE_UPDATE='1' 可强制更新）"
} else {
    Say "  [*] 下载代码 $Repo@$Branch"
    $Tmp = Join-Path $env:TEMP ("p001-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
    New-Item -ItemType Directory -Force -Path $Tmp | Out-Null
    $zip = Join-Path $Tmp 'repo.zip'
    $url = "https://codeload.github.com/$Repo/zip/refs/heads/$Branch"
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing -TimeoutSec 120
    } catch {
        Die "下载失败：$($_.Exception.Message)`n  检查网络或仓库名（$Repo / $Branch）"
    }
    Expand-Archive -Path $zip -DestinationPath $Tmp -Force
    $extracted = Get-ChildItem -Path $Tmp -Directory | Where-Object { $_.Name -ne '' } | Select-Object -First 1
    if (-not $extracted) { Die "解包失败" }
    if (Test-Path $SrcDir) { Remove-Item -Recurse -Force $SrcDir }
    New-Item -ItemType Directory -Force -Path $SrcDir | Out-Null
    Copy-Item -Path (Join-Path $extracted.FullName '*') -Destination $SrcDir -Recurse -Force
    Remove-Item -Recurse -Force $Tmp -ErrorAction SilentlyContinue
    Ok "代码已就位: $SrcDir"
}

Set-Location $SrcDir

# ---------- 4. 装依赖 ----------
Say "  [*] 检查依赖"
& $PyRun @PyRunArgs -c "import requests, cryptography" 2>$null
if ($LASTEXITCODE -ne 0) {
    Say "  [*] 安装 requests + cryptography"
    & $PyRun @PyRunArgs -m pip install -q --upgrade pip 2>$null
    & $PyRun @PyRunArgs -m pip install -q -r requirements.txt
    & $PyRun @PyRunArgs -c "import requests, cryptography" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Warn "常规安装失败，尝试 --user"
        & $PyRun @PyRunArgs -m pip install -q --user -r requirements.txt
        & $PyRun @PyRunArgs -c "import requests, cryptography" 2>$null
        if ($LASTEXITCODE -ne 0) {
            Die "依赖安装失败，请手动执行: $PyRun -m pip install requests cryptography"
        }
    }
}
Ok "依赖就绪"

# ---------- 5. 启动 ----------
Write-Host ""
Write-Host ("=" * 58) -ForegroundColor Cyan
Write-Host "  启动交互界面" -ForegroundColor Cyan
Write-Host ("=" * 58) -ForegroundColor Cyan
Write-Host ""

# 参数来源：优先命令行（-File 方式），其次 PROXY001_ARGS 环境变量（irm|iex 方式）
$ExtraArgs = @()
if ($args -and $args.Count -gt 0) {
    $ExtraArgs = $args
} elseif ($env:PROXY001_ARGS) {
    $ExtraArgs = $env:PROXY001_ARGS -split '\s+' | Where-Object { $_ }
}

Write-Host ("[*] 启动: run.py " + ($ExtraArgs -join ' ')) -ForegroundColor DarkGray
Write-Host ""

& $PyRun @PyRunArgs run.py @ExtraArgs
$script:Proxy001Exit = $LASTEXITCODE

Write-Host ""
if ($script:Proxy001Exit -ne 0) {
    Write-Host ("[!] 退出码 " + $script:Proxy001Exit) -ForegroundColor Yellow
}

# 判断执行方式：用 -File 跑时 $PSCommandPath 有值；irm|iex 时为空。
# irm|iex 下执行 exit 会终止调用者整个 PowerShell 会话，必须避免。
if ($PSCommandPath) {
    exit $script:Proxy001Exit
}
