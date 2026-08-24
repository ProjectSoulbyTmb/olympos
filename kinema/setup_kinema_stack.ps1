# setup_kinema_stack.ps1 - one-command local installer for KINEMA.
#
#   powershell -ExecutionPolicy Bypass -File kinema\setup_kinema_stack.ps1
#       installs FFmpeg into kinema\bin (portable, offline afterwards)
#
#   ... -Ai            also clones ComfyUI + venv under ai-stack\
#   ... -Ai -CpuOnly   force CPU torch wheels (no NVIDIA GPU)
#
# Everything lands outside OneDrive-synced storage when possible;
# nothing is installed system wide and nothing phones home after
# download. Re-run any time - it is idempotent and skips completed
# parts.
#
# AI tier location: KINEMA_AI_HOME env var wins, else D:\kinema-ai,
# else repo-local ai-stack\. Big wheels/models never go on a drive
# that cannot hold them.

param(
    [switch]$Ai,
    [switch]$CpuOnly
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot   # repo root
$bin  = Join-Path $PSScriptRoot "bin"

function Step($msg) { Write-Host "[kinema-setup] $msg" }

# ---------------------------------------------------------------- ffmpeg

if ((Test-Path (Join-Path $bin "ffmpeg.exe")) -and
    (Test-Path (Join-Path $bin "ffprobe.exe"))) {
    Step "FFmpeg already present in kinema\bin - skipping"
} else {
    New-Item -ItemType Directory -Force -Path $bin | Out-Null
    $zip = Join-Path $env:TEMP "kinema-ffmpeg.zip"
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

$stack = $env:KINEMA_AI_HOME
if (-not $stack) {
    if (Test-Path "D:\") { $stack = "D:\kinema-ai" }
    else { $stack = Join-Path $root "ai-stack" }
}
New-Item -ItemType Directory -Force -Path $stack | Out-Null
$comfy = Join-Path $stack "ComfyUI"

if (Test-Path (Join-Path $comfy "main.py")) {
    Step "ComfyUI already cloned - skipping"
} else {
    Step "cloning ComfyUI (comfyanonymous/ComfyUI) ..."
    git clone --depth 1 https://github.com/comfyanonymous/ComfyUI $comfy
}

$venv = Join-Path $stack "venv"
if (-not (Test-Path (Join-Path $venv "Scripts\python.exe"))) {
    Step "creating virtualenv ..."
    python -m venv $venv
}
$py = Join-Path $venv "Scripts\python.exe"

Step "installing torch wheels ($(@{ $true = 'cpu'; $false =
    'cuda' }[$CpuOnly.IsPresent])) ..."
if ($CpuOnly) {
    & $py -m pip install --upgrade torch torchvision torchaudio `
        --index-url https://download.pytorch.org/whl/cpu
} else {
    & $py -m pip install --upgrade torch torchvision torchaudio `
        --index-url https://download.pytorch.org/whl/cu121
}
Step "installing ComfyUI requirements ..."
& $py -m pip install -r (Join-Path $comfy "requirements.txt")

Step @"
AI tier ready. Next (one-time, manual, your choice of models):
  1. place video checkpoints into  $comfy\models\checkpoints\
     e.g. Stable Video Diffusion (stabilityai/svd_xt) or LTX-Video
     weights downloaded by you from HuggingFace
  2. start the local API:
     & "$py" "$comfy\main.py" --listen 127.0.0.1 --port 8188
  3. python -m kinema doctor      # should show: ai tier ComfyUI up
  4. python -m kinema ai template my_workflow.json   (edit, then:)
     python -m kinema ai run --path my_workflow.json --out out\
Generated clips drop straight into the mp4 production engine.
"@
