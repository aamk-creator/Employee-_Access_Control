$ErrorActionPreference = 'Stop'

$listeners = Get-NetTCPConnection -LocalPort 8069 -State Listen -ErrorAction SilentlyContinue
if (-not $listeners) {
    Write-Output 'No Odoo server process found.'
    exit 0
}

$listeners | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object {
    Stop-Process -Id $_ -Force
}

Write-Output 'Odoo server stopped.'
