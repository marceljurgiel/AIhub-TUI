# AIhub installer for Windows 10/11.
#
#   irm https://raw.githubusercontent.com/marceljurgiel/AIhub-TUI/main/install.ps1 | iex
#
# Installs everything AIhub needs, without administrator rights: uv (Python
# 3.12 + the engine), Bun (the terminal app) and an `aihub` command. Ollama is
# optional: install it here, point AIhub at an Ollama server, or skip.
# Re-running it updates AIhub and keeps your settings (%USERPROFILE%\.aihub).
#
# Unattended installs set these first:
#   $env:AIHUB_YES    = "1"                    don't ask; use the defaults
#   $env:AIHUB_OLLAMA = "local" | "skip" | "<server url>"
#   $env:AIHUB_MODEL  = "<name>" | "none"      starter model to download
#   $env:AIHUB_HOME   = "<dir>"                default: %LOCALAPPDATA%\AIhub
#   $env:AIHUB_SOURCE = "<zip url or path>"    install from somewhere else

function Install-AIhub {
    $ErrorActionPreference = "Stop"
    $ProgressPreference = "SilentlyContinue"   # Invoke-WebRequest is far faster without it
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

    $Repo = "marceljurgiel/AIhub-TUI"
    $Ref = if ($env:AIHUB_REF) { $env:AIHUB_REF } else { "main" }
    $Source = if ($env:AIHUB_SOURCE) { $env:AIHUB_SOURCE } else { "https://github.com/$Repo/archive/refs/heads/$Ref.zip" }
    $InstallerUrl = "https://raw.githubusercontent.com/$Repo/main/install.ps1"
    $AihubHome = if ($env:AIHUB_HOME) { $env:AIHUB_HOME } else { Join-Path $env:LOCALAPPDATA "AIhub" }
    $Yes = $env:AIHUB_YES -in @("1", "true", "yes")
    $Py = Join-Path $AihubHome ".venv\Scripts\python.exe"

    function Step($t) { Write-Host ""; Write-Host "==> " -ForegroundColor Cyan -NoNewline; Write-Host $t }
    function Ok($t) { Write-Host "  + " -ForegroundColor Green -NoNewline; Write-Host $t }
    function Warn($t) { Write-Host "  ! " -ForegroundColor Yellow -NoNewline; Write-Host $t }
    function Ask($q, $def) {
        if ($Yes) { return $def }
        try { $a = Read-Host "  $q" } catch { return $def }
        if ([string]::IsNullOrWhiteSpace($a)) { return $def } else { return $a.Trim() }
    }
    function Run {
        # Native tools write progress to stderr; only the exit code means failure.
        # (No named parameters: "-e" etc. must reach the tool, not bind here.)
        $ErrorActionPreference = "Continue"
        $exe, $rest = $args
        & $exe @rest 2>&1 | ForEach-Object { "$_" } | Out-Null
        return $LASTEXITCODE -eq 0
    }
    function Helper { & $Py -m aihub.installer @args }
    function Fetch($url, $out) { Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $out }
    function ChildPS($cmd) {
        # Third-party installers run in their own PowerShell so they can't
        # touch this script's variables.
        $ErrorActionPreference = "Continue"
        & powershell -NoProfile -ExecutionPolicy Bypass -Command $cmd *>&1 | Out-Null
        return $LASTEXITCODE -eq 0
    }

    Write-Host "AIhub installer " -NoNewline; Write-Host "- local AI in your terminal" -ForegroundColor DarkGray

    # ── 1. AIhub itself ─────────────────────────────────────────────────────
    Step "Downloading AIhub"
    $tmp = Join-Path ([IO.Path]::GetTempPath()) ("aihub-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $tmp | Out-Null
    try {
        $zip = Join-Path $tmp "aihub.zip"
        if (Test-Path $Source) { Copy-Item $Source $zip } else { Fetch $Source $zip }
        Expand-Archive -Path $zip -DestinationPath (Join-Path $tmp "x") -Force
        $src = Get-ChildItem (Join-Path $tmp "x") -Directory | Select-Object -First 1
        if (-not $src -or -not (Test-Path (Join-Path $src.FullName "pyproject.toml"))) {
            throw "the download does not look like AIhub: $Source"
        }
        # Update: move the old install aside first. If anything has it open,
        # that fails before a single file changed.
        $old = $null
        if (Test-Path $AihubHome) {
            $old = "$AihubHome.old-" + [guid]::NewGuid().ToString("N").Substring(0, 8)
            try { Rename-Item -Path $AihubHome -NewName (Split-Path $old -Leaf) -ErrorAction Stop }
            catch { throw "AIhub is in use. Close AIhub (and Ollama, if AIhub started it), then run the installer again. Nothing was changed." }
            # Keep the Python environment and the app's packages across updates.
            foreach ($keep in @(".venv", "app\node_modules", "bin")) {
                $from = Join-Path $old $keep
                if (Test-Path $from) { Move-Item $from (Join-Path $src.FullName $keep) }
            }
        }
        New-Item -ItemType Directory -Force -Path (Split-Path $AihubHome) | Out-Null
        Move-Item $src.FullName $AihubHome
        Get-ChildItem (Split-Path $AihubHome) -Directory -Filter ((Split-Path $AihubHome -Leaf) + ".old-*") |
            Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    } finally {
        Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
    }
    $version = (Select-String -Path (Join-Path $AihubHome "pyproject.toml") -Pattern '^version\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
    Ok "AIhub $version -> $AihubHome"

    # ── 2. Python engine (uv brings its own Python) ─────────────────────────
    Step "Python engine"
    $uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
    if (-not $uv) { $uv = Join-Path $HOME ".local\bin\uv.exe" }
    if (-not (Test-Path $uv)) {
        $env:UV_NO_MODIFY_PATH = "1"
        if (-not (ChildPS "irm https://astral.sh/uv/install.ps1 | iex")) { throw "could not install uv" }
        $uv = Join-Path $HOME ".local\bin\uv.exe"
        Ok "uv installed"
    }
    if (-not (Test-Path $Py)) {
        if (-not (Run $uv venv -q --python 3.12 (Join-Path $AihubHome ".venv"))) { throw "could not create the Python environment" }
    }
    if (-not (Run $uv pip install -q --python $Py -e $AihubHome)) { throw "could not install the AIhub engine" }
    Ok ("engine " + (Helper version) + " on Python " + (& $Py -c "import platform; print(platform.python_version())"))

    # ── 3. Bun + the terminal app ───────────────────────────────────────────
    Step "Terminal app"
    $bun = (Get-Command bun -ErrorAction SilentlyContinue).Source
    if (-not $bun) { $bun = Join-Path $HOME ".bun\bin\bun.exe" }
    if (-not (Test-Path $bun)) {
        if (-not (ChildPS "irm https://bun.sh/install.ps1 | iex")) { throw "could not install Bun" }
        $bun = Join-Path $HOME ".bun\bin\bun.exe"
        if (-not (Test-Path $bun)) { throw "could not install Bun" }
        Ok ("Bun " + (& $bun --version) + " installed")
    }
    Push-Location (Join-Path $AihubHome "app")
    try {
        if (-not (Run $bun install --production --frozen-lockfile)) {
            if (-not (Run $bun install --production)) { throw "could not install the app's packages" }
        }
    } finally { Pop-Location }
    Ok ("app ready (Bun " + (& $bun --version) + ")")

    # ── 4. Ollama ───────────────────────────────────────────────────────────
    Step "Ollama"
    $ollamaUrl = "http://localhost:11434"
    $ollamaOk = $false
    $choice = $env:AIHUB_OLLAMA
    $current = Helper server
    function OllamaExe {
        $c = (Get-Command ollama -ErrorAction SilentlyContinue).Source
        if ($c) { return $c }
        $p = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
        if (Test-Path $p) { return $p }
        return $null
    }
    if (-not $choice -and ((Run $Py -m aihub.installer check $current) -or (Run $Py -m aihub.installer start))) {
        $ollamaUrl = $current; $ollamaOk = $true
        Ok "Ollama is running at $ollamaUrl"
    } else {
        if (-not $choice) {
            Write-Host "  AIhub runs models through Ollama, which is not reachable at $current."
            Write-Host "    L  install Ollama on this computer"
            Write-Host "    S  use an Ollama server on your network (e.g. a PC with a GPU)"
            Write-Host "    K  skip - set it up later in AIhub (Settings)"
            $choice = Ask "Choice [L/s/k]" $(if ($Yes) { "k" } else { "l" })
        }
        switch -Regex ($choice) {
            "^(l|local)$" {
                $exe = OllamaExe
                if (-not $exe) {
                    Write-Host "  downloading Ollama (about 1 GB)..."
                    $setup = Join-Path ([IO.Path]::GetTempPath()) "OllamaSetup.exe"
                    Fetch "https://ollama.com/download/OllamaSetup.exe" $setup
                    Start-Process -FilePath $setup -ArgumentList "/VERYSILENT", "/NORESTART", "/SUPPRESSMSGBOXES" -Wait
                    Remove-Item $setup -ErrorAction SilentlyContinue
                    $exe = OllamaExe
                }
                if ($exe) {
                    if (-not (Run $Py -m aihub.installer check $ollamaUrl)) {
                        Start-Process -FilePath $exe -ArgumentList "serve" -WindowStyle Hidden
                        for ($i = 0; $i -lt 15 -and -not (Run $Py -m aihub.installer check $ollamaUrl); $i++) { Start-Sleep 1 }
                    }
                    Helper server $ollamaUrl | Out-Null
                    $ollamaOk = Run $Py -m aihub.installer check $ollamaUrl
                    if ($ollamaOk) { Ok "Ollama is running locally" } else { Warn "Ollama is installed but not running - start it from the Start menu" }
                } else { Warn "Ollama's installer failed - get it from https://ollama.com/download" }
            }
            "^(s|server)$" {
                $u = Ask "Server address (e.g. 192.0.2.10 or http://gpu-box.lan:11434)" ""
                if ($u) { $choice = $u } else { Warn "no address given - skipped"; $choice = "skip" }
            }
            "^(k|skip|none)?$" { Warn "skipped - AIhub can still use Ollama Cloud or API models (Settings)"; $choice = "skip" }
        }
        if ($choice -notmatch "^(l|local|s|server|k|skip|none)?$") {
            $ollamaUrl = Helper server $choice
            $ollamaOk = Run $Py -m aihub.installer check $ollamaUrl
            if ($ollamaOk) { Ok "using the Ollama server at $ollamaUrl" }
            else { Warn "saved $ollamaUrl, but it does not answer right now (is Ollama listening on 0.0.0.0? OLLAMA_HOST=0.0.0.0)" }
        }
    }

    if ($ollamaOk -and $env:AIHUB_MODEL -ne "none") {
        $count = [int](Helper models $ollamaUrl)
        $model = $env:AIHUB_MODEL
        if (-not $model -and $count -gt 0) {
            Ok "$count model(s) already available"
        } else {
            $ram = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
            if (-not $model) {
                $model = if ($ram -lt 8) { "llama3.2:1b" } elseif ($ram -lt 16) { "llama3.2:3b" } else { "qwen3:8b" }
                $a = Ask "Download a starter model, $model ($ram GB RAM here)? [Y/n/other name]" $(if ($Yes) { "n" } else { "y" })
                if ($a -match "^(n|no)$") { Write-Host "  pick models later in AIhub -> Models"; $model = $null }
                elseif ($a -notmatch "^(y|yes)$") { $model = $a }
            }
            if ($model) {
                Step "Downloading $model"
                Helper pull $ollamaUrl $model
                if ($LASTEXITCODE -ne 0) { Warn "could not download $model" }
            }
        }
    }

    # ── 5. The `aihub` command ──────────────────────────────────────────────
    Step "Launcher"
    $binDir = Join-Path $AihubHome "bin"
    New-Item -ItemType Directory -Force -Path $binDir | Out-Null
    $cmd = @"
@echo off
rem AIhub launcher (written by install.ps1). Re-run the installer to update.
setlocal
set "AIHUB_HOME=$AihubHome"
set "AIHUB_CORE_DIR=$AihubHome"
if /i "%~1"=="update" (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "irm $InstallerUrl | iex"
  exit /b %errorlevel%
)
if /i "%~1"=="version" goto version
if /i "%~1"=="--version" goto version
if /i "%~1"=="-v" goto version
if /i "%~1"=="cli" (
  "%AIHUB_HOME%\.venv\Scripts\aihub-cli.exe" %2 %3 %4 %5 %6 %7 %8 %9
  exit /b %errorlevel%
)
if /i "%~1"=="help" goto help
if /i "%~1"=="--help" goto help
rem The app works in the folder you start it from; Bun runs from app\ so it
rem picks up the app's tsconfig (JSX setup, console-safe characters).
if not defined AIHUB_WORKDIR set "AIHUB_WORKDIR=%CD%"
cd /d "%AIHUB_HOME%\app"
"$bun" run src\index.tsx %*
exit /b %errorlevel%
:version
echo|set /p="aihub "
"%AIHUB_HOME%\.venv\Scripts\python.exe" -m aihub.installer version
exit /b 0
:help
echo aihub            start AIhub
echo aihub update     update to the latest version
echo aihub cli ...    command-line tools (models, hardware)
echo aihub version    show the installed version
exit /b 0
"@
    $launcher = Join-Path $binDir "aihub.cmd"
    # Replace, never write through a link to someone else's file.
    if (Test-Path $launcher) { Remove-Item -Force $launcher }
    Set-Content -Path $launcher -Value $cmd -Encoding Ascii
    Ok (Join-Path $binDir "aihub.cmd")

    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if (-not $userPath) { $userPath = "" }
    if (($userPath -split ";") -notcontains $binDir) {
        [Environment]::SetEnvironmentVariable("Path", ($binDir + ";" + $userPath).TrimEnd(";"), "User")
        Ok "added $binDir to your PATH"
    }
    if (($env:Path -split ";") -notcontains $binDir) { $env:Path = "$binDir;$env:Path" }

    Write-Host ""
    Write-Host "AIhub $version is installed." -ForegroundColor Green
    Write-Host "  Start it with: aihub   (in Windows Terminal for the best look)"
    Write-Host "  Update later with 'aihub update'. Free cloud models: run 'ollama signin' and pick a :cloud model." -ForegroundColor DarkGray
}

try {
    Install-AIhub
} catch {
    Write-Host ""
    Write-Host "error: $($_.Exception.Message)" -ForegroundColor Red
    if ($env:AIHUB_YES) { exit 1 }
}
