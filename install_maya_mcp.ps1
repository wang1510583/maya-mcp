param(
    [string]$MayaVersion = '2024',
    [switch]$SkipCodex
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'uv is required. Install uv, then run this script again.'
}
if (-not (Test-Path -LiteralPath '.venv-mcp\Scripts\python.exe')) {
    uv venv --python 3.12 .venv-mcp
    if ($LASTEXITCODE -ne 0) { throw 'Python environment creation failed' }
}
$mcpPython = Join-Path $PSScriptRoot '.venv-mcp\Scripts\python.exe'
uv pip install --python $mcpPython -r requirements-mcp.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
$mayaBase = if ($env:MAYA_APP_DIR) { $env:MAYA_APP_DIR } else { Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'maya' }
$mayaScripts = Join-Path $mayaBase "$MayaVersion\scripts"
& $mcpPython -m maya_mcp.install --prepare --scripts-dir $mayaScripts
if ($LASTEXITCODE -ne 0) { throw 'Maya startup installation failed' }
if (-not $SkipCodex) {
    if (-not (Get-Command codex -ErrorAction SilentlyContinue)) { throw 'codex CLI not found; use -SkipCodex for other MCP clients' }
    # Name specific to this integration; other MCP servers are preserved.
    codex mcp add maya-agent -- $mcpPython (Join-Path $PSScriptRoot 'scripts\run_maya_mcp.py')
    if ($LASTEXITCODE -ne 0) { throw 'Codex MCP registration failed' }
}
Write-Host 'Installed. In a running Maya, drag install_maya_mcp.mel into the viewport; otherwise start Maya normally.'
