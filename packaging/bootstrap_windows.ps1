# SPDX-License-Identifier: GPL-3.0-only
param([string]$Destination = '.deps')
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$lock = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'toolchain.lock.json') -Raw | ConvertFrom-Json
$target = [IO.Path]::GetFullPath((Join-Path $root $Destination))
New-Item -ItemType Directory -Path $target -Force | Out-Null
foreach ($entry in $lock.downloads.PSObject.Properties) {
    if ($entry.Name -eq 'python-3.12.14-windows.tar.gz') { continue }
    $file = Join-Path $target $entry.Name
    if (-not (Test-Path -LiteralPath $file)) { Invoke-WebRequest -Uri $entry.Value.url -OutFile $file }
    if ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.Value.sha256) {
        throw "Unexpected download checksum: $($entry.Name)"
    }
}
$qt = Join-Path $target 'qt-archive'
New-Item -ItemType Directory -Path $qt -Force | Out-Null
& 7z x (Join-Path $target 'qtbase.7z') "-o$qt" -y | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Qt extraction failed' }
$qtConfig = Get-ChildItem -LiteralPath $qt -Filter Qt6Config.cmake -Recurse | Select-Object -First 1
if (-not $qtConfig) { throw 'Qt configuration missing' }
$qtRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $qtConfig.FullName)))
$inno = Join-Path $target 'inno'
$process = Start-Process -FilePath (Join-Path $target 'innosetup-6.7.4.exe') -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/CURRENTUSER',"/DIR=`"$inno`"") -WindowStyle Hidden -Wait -PassThru
if ($process.ExitCode -ne 0) { throw 'Inno Setup installation failed' }
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
$vs = (& $vswhere -latest -products '*' -version '[17.0,18.0)' -property installationPath | Select-Object -First 1)
if (-not $vs) { throw 'Visual Studio 2022 Build Tools must be installed on this runner' }
$cl = Join-Path $vs "VC/Tools/MSVC/$($lock.msvc)/bin/Hostx64/x64/cl.exe"
if (-not (Test-Path -LiteralPath $cl)) {
    throw "Pinned MSVC $($lock.msvc) missing. Install the matching Visual Studio 2022 toolset before building."
}
if ($env:GITHUB_ENV) {
    "CADENCE_QT_ROOT=$qtRoot" | Out-File -LiteralPath $env:GITHUB_ENV -Append -Encoding utf8
    "CADENCE_MSVC_ROOT=$vs" | Out-File -LiteralPath $env:GITHUB_ENV -Append -Encoding utf8
    "INNO_SETUP_COMPILER=$inno/ISCC.exe" | Out-File -LiteralPath $env:GITHUB_ENV -Append -Encoding utf8
}
Write-Output 'Pinned Qt and Inno inputs verified. MSVC installation located.'
