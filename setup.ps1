
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$ComfyArchiveUrl = 'https://github.com/Comfy-Org/ComfyUI/releases/download/v0.39.0/ComfyUI_windows_portable_nvidia_cu126.7z'
$ComfyArchivePath = Join-Path $ProjectRoot 'ComfyUI_windows_portable_nvidia_cu126.7z'
$ComfyDir = Join-Path $ProjectRoot 'ComfyUI_windows_portable'

function Write-Section([string]$Message) {
    Write-Host "`n=== $Message ===" -ForegroundColor Cyan
}

function Get-SevenZip {
    $cmd = Get-Command '7z.exe' -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    $candidates = @(
        (Join-Path $env:ProgramFiles '7-Zip\7z.exe'),
        (Join-Path ${env:ProgramFiles(x86)} '7-Zip\7z.exe')
    )

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) {
            return $candidate
        }
    }

    $winget = Get-Command 'winget.exe' -ErrorAction SilentlyContinue
    if ($winget) {
        Write-Host '7-Zip is required to extract ComfyUI. Attempting installation with winget...'
        & $winget.Source install --id 7zip.7zip --exact --accept-package-agreements --accept-source-agreements

        if ($LASTEXITCODE -eq 0) {
            $cmd = Get-Command '7z.exe' -ErrorAction SilentlyContinue
            if ($cmd) { return $cmd.Source }

            foreach ($candidate in $candidates) {
                if ($candidate -and (Test-Path $candidate)) {
                    return $candidate
                }
            }
        }
    }

    throw '7-Zip was not found. Install it from https://www.7-zip.org/ and run setup.bat again.'
}

function Download-File([string]$Url, [string]$Destination, [string]$Label) {
    if ((Test-Path $Destination) -and ((Get-Item $Destination).Length -gt 0)) {
        Write-Host "Already present: $Label"
        return
    }

    $parent = Split-Path -Parent $Destination
    if (-not (Test-Path $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }

    $partial = "$Destination.partial"

    Write-Host "Downloading $Label"
    Write-Host "  URL: $Url"

    $curl = Get-Command 'curl.exe' -ErrorAction SilentlyContinue

    if ($curl) {
        & $curl.Source --location --fail --retry 3 --retry-delay 2 --continue-at '-' --output $partial $Url

        if ($LASTEXITCODE -ne 0) {
            throw "Download failed for $Label. You can rerun setup.bat to try again."
        }
    } else {
        Invoke-WebRequest -Uri $Url -OutFile $partial
    }

    if (-not (Test-Path $partial) -or (Get-Item $partial).Length -eq 0) {
        throw "Downloaded file is missing or empty: $partial"
    }

    Move-Item -LiteralPath $partial -Destination $Destination -Force
}

function Install-CivitaiModelManually(
    [string]$Label,
    [string]$ModelPageUrl,
    [string]$Filename,
    [string]$Destination
) {
    if ((Test-Path $Destination) -and ((Get-Item $Destination).Length -gt 0)) {
        Write-Host "Already present: $Label"
        return
    }

    $parent = Split-Path -Parent $Destination
    if (-not (Test-Path $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }

    # Remove stale partial files left by earlier automated Civitai download attempts.
    $partial = "$Destination.partial"
    if (Test-Path $partial) {
        Remove-Item -LiteralPath $partial -Force
    }

    while ($true) {
        Write-Section "Manual download: $Label"

        Write-Host 'Civitai may require a logged-in browser, so this model will be downloaded manually.'
        Write-Host ''
        Write-Host "1. Download the model file from this page:"
        Write-Host "   $ModelPageUrl"
        Write-Host ''
        Write-Host "2. Save or move the downloaded file to this exact path:"
        Write-Host "   $Destination"
        Write-Host ''
        Write-Host "   The filename must be: $Filename"
        Write-Host '   If your browser adds a suffix such as (1), rename the file.'
        Write-Host ''

        try {
            Start-Process $ModelPageUrl
        } catch {
            Write-Host 'Could not open the browser automatically. Open the URL above manually.'
        }

        Read-Host 'After placing the file in the target folder, press Enter to continue' | Out-Null

        if ((Test-Path $Destination) -and ((Get-Item $Destination).Length -gt 0)) {
            Write-Host "Verified: $Filename" -ForegroundColor Green
            return
        }

        Write-Host ''
        Write-Host "The file was not found at the expected location:" -ForegroundColor Yellow
        Write-Host "  $Destination" -ForegroundColor Yellow
        Write-Host 'Move the downloaded file there, then press Enter to check again.'
        Write-Host ''
    }
}

function Install-ComfyUI {
    Write-Section 'ComfyUI portable'

    $expectedMain = Join-Path $ComfyDir 'ComfyUI\main.py'

    if (Test-Path $expectedMain) {
        Write-Host "ComfyUI already exists: $ComfyDir"
    } else {
        Download-File $ComfyArchiveUrl $ComfyArchivePath 'ComfyUI portable archive (several GB)'

        $sevenZip = Get-SevenZip

        Write-Host "Extracting archive into $ProjectRoot ... This may take several minutes."
        & $sevenZip x $ComfyArchivePath "-o$ProjectRoot" -y

        if ($LASTEXITCODE -ne 0) {
            throw '7-Zip failed to extract the ComfyUI archive.'
        }

        if (-not (Test-Path $expectedMain)) {
            throw "Extraction completed, but expected file was not found: $expectedMain. Check the archive's folder structure before rerunning setup."
        }
    }

    $models = Join-Path $ComfyDir 'ComfyUI\models'
    $diffusionDir = Join-Path $models 'diffusion_models'
    $encoderDir = Join-Path $models 'text_encoders'
    $vaeDir = Join-Path $models 'vae'
    $loraDir = Join-Path $models 'loras'

    foreach ($dir in @($diffusionDir, $encoderDir, $vaeDir, $loraDir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }

    Write-Section 'Model weights'
    Write-Host 'These files are large. Ensure you have enough free disk space before continuing.'

    # Civitai models are downloaded manually to avoid authentication failures.
    Install-CivitaiModelManually `
        'WAI-Anima base model' `
        'https://civitai.com/models/2544636/wai-anima' `
        'waiANIMA_v10Base10.safetensors' `
        (Join-Path $diffusionDir 'waiANIMA_v10Base10.safetensors')

    # Hugging Face models continue to download automatically.
    Download-File `
        'https://huggingface.co/circlestone-labs/Anima/resolve/main/split_files/text_encoders/qwen_3_06b_base.safetensors' `
        (Join-Path $encoderDir 'qwen_3_06b_base.safetensors') `
        'Qwen text encoder'

    Download-File `
        'https://huggingface.co/circlestone-labs/Anima/resolve/main/split_files/vae/qwen_image_vae.safetensors' `
        (Join-Path $vaeDir 'qwen_image_vae.safetensors') `
        'Qwen image VAE'

    # Civitai LoRA: prompt for a manual download rather than aborting setup on HTTP 401.
    Install-CivitaiModelManually `
        'DND Items LoRA' `
        'https://civitai.com/models/836139/dnd-items?modelVersionId=3148559' `
        'dnd items.safetensors' `
        (Join-Path $loraDir 'dnd items.safetensors')

    Write-Host ''
    Write-Host 'All required model files are in place.' -ForegroundColor Green
}

Write-Host 'DnD Card Generator setup' -ForegroundColor Green
Write-Host "Project folder: $ProjectRoot"
Write-Host 'Normal card generation uses the bundled images and does not require ComfyUI or model weights.'
Write-Host 'This optional setup downloads ComfyUI and its image-generation models.'

$answer = Read-Host 'Install ComfyUI and download its model weights now? This requires several GB of downloads. [y/N]'

if ($answer -match '^(y|yes)$') {
    Install-ComfyUI
} else {
    Write-Host 'Skipped ComfyUI. You can run setup.bat again later to install it.'
}

Write-Section 'Finished'
Write-Host 'You can now run the comfyui server by double clicking the ComfyUI_windows_portable\run_nvidia_gpu.bat file.'
Write-Host 'If you skipped ComfyUI, bundled image variants remain available as usual.'
