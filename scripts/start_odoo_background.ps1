$ErrorActionPreference = 'Stop'

$workspace = Split-Path -Parent $PSScriptRoot
$python = Join-Path $workspace '.venv\Scripts\python.exe'
$config = Join-Path $workspace 'odoo.conf'
$sourceRoot = Join-Path $workspace 'odoo-19.0.post20260812'
$script = Join-Path $workspace 'scripts\start_odoo.ps1'

$listener = Get-NetTCPConnection -LocalPort 8069 -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    Write-Output "Odoo server already appears to be running."
    exit 0
}

Start-Process `
    -FilePath 'powershell.exe' `
    -ArgumentList @(
        '-NoProfile',
        '-ExecutionPolicy', 'Bypass',
        '-File', ('"{0}"' -f $script)
    ) `
    -WorkingDirectory $workspace `
    -WindowStyle Hidden

Write-Output 'Odoo server start requested.'
