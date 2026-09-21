param(
    [ValidateSet('setup','start','base','stop','logs','test','check','demo','load','status')]
    [string]$Action = 'start',
    [ValidateRange(1,2)][int]$Replicas = 2
)
$ErrorActionPreference = 'Stop'
$Project = Split-Path -Parent $PSScriptRoot
$ComposeFile = Join-Path $Project 'compose.yml'
$EnvFile = Join-Path $Project '.env'
if (-not (Test-Path -LiteralPath $EnvFile)) { $EnvFile = Join-Path $Project '.env.example' }
function Invoke-Docker {
    & docker @args
    if ($LASTEXITCODE -ne 0) { throw "docker falhou (código $LASTEXITCODE)." }
}
function Invoke-Compose {
    Invoke-Docker compose -p pf-api-sentinel --project-directory $Project --env-file $EnvFile -f $ComposeFile @args
}
function Wait-Endpoint([string]$Url) {
    $Deadline = [DateTime]::UtcNow.AddSeconds(90)
    while ([DateTime]::UtcNow -lt $Deadline) {
        try {
            $Result = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 3
            if ($Result.StatusCode -eq 200) { return }
        } catch { }
        Start-Sleep -Milliseconds 500
    }
    throw "Prontidão não atingida: $Url"
}
New-Item -ItemType Directory -Force -Path (Join-Path $Project 'artifacts'),(Join-Path $Project '.runtime') | Out-Null
switch ($Action) {
    'setup' {
        Invoke-Compose build api
        Invoke-Compose up -d --wait postgres redis
        Invoke-Compose run --rm -e "REPLICAS=$Replicas" tools python scripts/bootstrap.py
        & $PSCommandPath start -Replicas $Replicas
    }
    { $_ -in 'start','base' } {
        Invoke-Compose run --rm -e "REPLICAS=$Replicas" tools python -c "import os; from pathlib import Path; Path('/secrets/expected-replicas').write_text(os.environ['REPLICAS'])"
        if ($Action -eq 'start') { Invoke-Compose --profile observability up -d --scale "api=$Replicas" }
        else { Invoke-Compose up -d --scale "api=$Replicas" }
        $Settings = Invoke-Compose --profile observability config --format json | ConvertFrom-Json
        $InvestigationLinks = @{}
        foreach ($Service in @('grafana','jaeger','prometheus','alertmanager')) {
            $Port = $Settings.services.$Service.ports[0].published
            $InvestigationLinks[$Service] = "http://127.0.0.1:$Port"
        }
        Invoke-Compose run --rm tools python -c "import sys; from pathlib import Path; p=Path('/secrets/public-urls.json'); p.write_text(sys.argv[1]); p.chmod(0o644)" ($InvestigationLinks | ConvertTo-Json -Compress)
        $PublishedPort = $Settings.services.proxy.ports[0].published
        Wait-Endpoint "http://localhost:$PublishedPort/health/ready"
        Invoke-Compose cp --index 1 api:/secrets/demo.json (Join-Path $Project '.runtime/demo.json')
    }
    'stop' { Invoke-Compose --profile observability --profile tools down --remove-orphans }
    'logs' { Invoke-Compose logs --tail 100 api proxy receiver }
    'status' { Invoke-Compose --profile observability ps }
    'test' {
        try {
            Invoke-Docker compose -p pf-api-sentinel-test -f (Join-Path $Project 'compose.test.yml') up --abort-on-container-exit --exit-code-from tests tests
        } finally {
            Invoke-Docker compose -p pf-api-sentinel-test -f (Join-Path $Project 'compose.test.yml') down
        }
    }
    'check' {
        Invoke-Compose run --rm -v "${Project}:/app" tools ruff check .
        Invoke-Compose run --rm -v "${Project}:/app" tools ruff format --check .
        Invoke-Compose run --rm -v "${Project}:/app" tools mypy --cache-dir=/tmp/mypy-cache
        & python (Join-Path $PSScriptRoot 'check_monitoring.py')
        if ($LASTEXITCODE -ne 0) { throw 'Verificação de monitoramento falhou.' }
    }
    'demo' {
        & python (Join-Path $PSScriptRoot 'review.py') --scenario alerts
        if ($LASTEXITCODE -ne 0) { throw 'Demonstração falhou.' }
    }
    'load' {
        & python (Join-Path $PSScriptRoot 'review.py') --scenario load
        if ($LASTEXITCODE -ne 0) { throw 'Carga isolada falhou; confira os artefatos da rodada.' }
    }
}
