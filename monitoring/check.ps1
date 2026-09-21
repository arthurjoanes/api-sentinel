param(
    [string]$PrometheusImage = 'prom/prometheus:v3.5.0',
    [string]$AlertmanagerImage = 'prom/alertmanager:v0.28.1'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$Project = Split-Path -Parent $PSScriptRoot
$Checker = Join-Path $Project 'scripts/check_monitoring.py'
& python $Checker --prometheus-image $PrometheusImage --alertmanager-image $AlertmanagerImage
if ($LASTEXITCODE -ne 0) {
    throw "Verificação de monitoramento falhou (código $LASTEXITCODE)."
}
