$ErrorActionPreference = "Stop"
& "$PSScriptRoot\start-seekdb.ps1"
Push-Location (Split-Path $PSScriptRoot -Parent)
try { npm run dev } finally { Pop-Location }
