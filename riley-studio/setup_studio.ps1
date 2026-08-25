# setup_studio.ps1 - one-command local installer for RILEY STUDIO.
#
#   powershell -ExecutionPolicy Bypass -File riley-studio\setup_studio.ps1
#       installs FFmpeg into riley-studio\bin (portable, offline afterwards)
#
#   ... -Ai            also installs ComfyUI + venv + custom node packs
#   ... -Ai -CpuOnly   force CPU torch wheels (no NVIDIA GPU)
#
# Nothing is installed system wide and nothing phones home after download.
# Idempotent: re-run any time, completed parts are skipped.
#
# AI tier location (big wheels/models never on a space-starved OneDrive
# drive): RILEY_STUDIO_AI_HOME env var wins, else D:\riley-studio-ai,
# else repo-local ai-stack\.

param(
    [switch]$Ai,
    [switch]$CpuOnly
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$bin  = Join-Path $PSScriptRoot "bin"

function Step($msg) { Write-Host "[riley-studio-setup] $msg" }

# ---------------------------------------------------------------- ffmpeg

if ((Test-Path (Join-Path $bin "ffmpeg.exe")) -and
    (Test-Path (Join-Path $bin "ffprobe.exe"))) {
    Step "FFmpeg already present in riley-studio\bin - skipping"
} else {
    New-Item -ItemType Directory -Force -Path $bin | Out-Null
    $zip = Join-Path $env:TEMP "rileystudio-ffmpeg.zip"
    $url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    Step "downloading FFmpeg (essentials build) ..."
    Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
    Step "extracting ffmpeg.exe + ffprobe.exe ..."
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [System.IO.Compression.ZipFile]::OpenRead($zip)
    try {
        foreach ($entry in $archive.Entries) {
            if ($entry.Name -in @("ffmpeg.exe", "ffprobe.exe")) {
                $dst = Join-Path $bin $entry.Name
                [System.IO.Compression.ZipFileExtensions]::
                    ExtractToFile($entry, $dst, $true)
                Step "installed $dst"
            }
        }
    } finally { $archive.Dispose() }
    Remove-Item $zip -ErrorAction SilentlyContinue
}

& (Join-Path $bin "ffmpeg.exe") -version | Select-Object -First 1

# ------------------------------------------------------------- ai tier

if (-not $Ai) {
    Step "done (core tier). For local AI generation re-run with -Ai"
    exit 0
}

$stack = $env:RILEY_STUDIO_AI_HOME
if (-not $stack) {
    if (Test-Path "D:\") { $stack = "D:\riley-studio-ai" }
    else { $stack = Join-Path $root "ai-stack" }
}
New-Item -ItemType Directory -Force -Path $stack | Out-Null
$comfy = Join-Path $stack "ComfyUI"

if (Test-Path (Join-Path $comfy "main.py")) {
    Step "ComfyUI already cloned - skipping"
} else {
    Step "cloning ComfyUI (comfyanonymous/ComfyUI) ..."
    cmd /c "git clone --depth 1 https://github.com/comfyanonymous/ComfyUI `"$comfy`" 2>&1"
    if ($LASTEXITCODE -ne 0) { throw "git clone failed ($LASTEXITCODE)" }
}

# custom node packs: GGUF loaders + video helpers
$packs = @(
    @{ url = "https://github.com/city96/ComfyUI-GGUF";          dir = "ComfyUI-GGUF" },
    @{ url = "https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite"; dir = "ComfyUI-VideoHelperSuite" }
)
foreach ($p in $packs) {
    $dst = Join-Path (Join-Path $comfy "custom_nodes") $p.dir
    if (Test-Path $dst) { Step "$($p.dir) already present - skipping" }
    else {
        Step "cloning $($p.dir) ..."
        cmd /c "git clone --depth 1 $($p.url) `"$dst`" 2>&1"
        if ($LASTEXITCODE -ne 0) { throw "git clone failed for $($p.dir)" }
    }
}

# venv + torch + requirements
$venv = Join-Path $stack "venv"
if (-not (Test-Path (Join-Path $venv "Scripts\python.exe"))) {
    Step "creating venv at $venv ..."
    python -m venv "$venv"
    if ($LASTEXITCODE -ne 0) { throw "python -m venv failed" }
}
$py = Join-Path $venv "Scripts\python.exe"

if (-not (Test-Path (Join-Path $venv ".torch-installed"))) {
    if ($CpuOnly) {
        Step "installing CPU torch wheels ..."
        & $py -m pip install --upgrade pip
        & $py -m pip install torch torchvision torchaudio
    } else {
        Step "installing CUDA 12.8 torch wheels (large download) ..."
        & $py -m pip install --upgrade pip
        & $py -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
    }
    if ($LASTEXITCODE -ne 0) { throw "torch install failed" }
    & $py -m pip install -r (Join-Path $comfy "requirements.txt")
    if ($LASTEXITCODE -ne 0) { throw "comfyui requirements failed" }
    Set-Content -Path (Join-Path $venv ".torch-installed") -Value "ok"
}

Step ""
Step "AI stack ready at: $stack"
Step "start ComfyUI:"
Step "  & `"$py`" `"$((Join-Path $comfy 'main.py'))`" --port 8188 --lowvram"
Step "then start the studio engine:"
Step "  python riley-studio\server.py"
Step "model weights are pulled from the Studio Models window or:"
Step "  POST http://127.0.0.1:8288/api/models/pull {`"key`":`"sd15`"}"
