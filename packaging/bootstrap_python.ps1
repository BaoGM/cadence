# SPDX-License-Identifier: GPL-3.0-only
param([string]$Destination = '.deps')
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$lock = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'toolchain.lock.json') -Raw | ConvertFrom-Json
$target = [IO.Path]::GetFullPath((Join-Path $root $Destination))
New-Item -ItemType Directory -Path $target -Force | Out-Null
$spec = $lock.downloads.'python-3.12.14-windows.tar.gz'
$archive = Join-Path $target 'python-3.12.14-windows.tar.gz'
if (-not (Test-Path -LiteralPath $archive)) { Invoke-WebRequest -Uri $spec.url -OutFile $archive }
if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $spec.sha256) {
    throw 'Python archive checksum mismatch'
}
$unpack = Join-Path $target 'python-runtime'
New-Item -ItemType Directory -Path $unpack -Force | Out-Null
& tar -xzf $archive -C $unpack
if ($LASTEXITCODE -ne 0) { throw 'Python extraction failed' }
$python = Join-Path $unpack 'python/python.exe'
$actual = & $python -c 'import platform; print(platform.python_version())'
if ($LASTEXITCODE -ne 0 -or $actual -ne $lock.python) { throw 'Unexpected Python runtime version' }
$venv = Join-Path $target 'build-venv'
& $python -m venv $venv
if ($LASTEXITCODE -ne 0) { throw 'Python environment creation failed' }
if ($env:GITHUB_PATH) {
    (Join-Path $venv 'Scripts') | Out-File -LiteralPath $env:GITHUB_PATH -Append -Encoding utf8
}
Write-Output (Join-Path $venv 'Scripts/python.exe')
