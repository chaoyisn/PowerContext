$ErrorActionPreference = "Stop"
Push-Location (Split-Path $PSScriptRoot -Parent)
try { npm ci --legacy-peer-deps } finally { Pop-Location }
