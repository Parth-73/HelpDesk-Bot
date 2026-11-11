$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    $runtimePath = Join-Path (Split-Path $PSScriptRoot -Parent) '.tools\node-v22.16.0-win-x64'
    if (-not (Test-Path -LiteralPath (Join-Path $runtimePath 'node.exe'))) { throw 'Install Node.js 22.12+ and reopen your terminal.' }
    $env:Path = $runtimePath + ';' + $env:Path
}
& npm.cmd run dev
