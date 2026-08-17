$ErrorActionPreference = 'Stop'

$workspace = Split-Path -Parent $PSScriptRoot
$python = Join-Path $workspace '.venv\Scripts\python.exe'
$config = Join-Path $workspace 'odoo.conf'
$sourceRoot = Join-Path $workspace 'odoo-19.0.post20260812'

$env:PYTHONPATH = $sourceRoot

& $python -m odoo server `
    --config $config `
    --database employee_access_control_dev `
    --init base,employee_access_control `
    --stop-after-init
