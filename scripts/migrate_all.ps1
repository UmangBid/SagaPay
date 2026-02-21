param(
  [string]$PythonBin = 'python'
)

# Runs migrations for all service databases.
$orchestratorDsn = if ($env:ORCHESTRATOR_POSTGRES_DSN) { $env:ORCHESTRATOR_POSTGRES_DSN } else { 'postgresql+psycopg2://finpay:finpay@localhost:5432/finpay_orchestrator' }
$riskDsn = if ($env:RISK_POSTGRES_DSN) { $env:RISK_POSTGRES_DSN } else { 'postgresql+psycopg2://finpay:finpay@localhost:5432/finpay_risk' }
$providerDsn = if ($env:PROVIDER_POSTGRES_DSN) { $env:PROVIDER_POSTGRES_DSN } else { 'postgresql+psycopg2://finpay:finpay@localhost:5432/finpay_provider' }
$ledgerDsn = if ($env:LEDGER_POSTGRES_DSN) { $env:LEDGER_POSTGRES_DSN } else { 'postgresql+psycopg2://finpay:finpay@localhost:5432/finpay_ledger' }
$notificationDsn = if ($env:NOTIFICATION_POSTGRES_DSN) { $env:NOTIFICATION_POSTGRES_DSN } else { 'postgresql+psycopg2://finpay:finpay@localhost:5432/finpay_notification' }

./scripts/migrate_service.ps1 -Service orchestrator -PostgresDsn $orchestratorDsn -PythonBin $PythonBin
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
./scripts/migrate_service.ps1 -Service risk -PostgresDsn $riskDsn -PythonBin $PythonBin
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
./scripts/migrate_service.ps1 -Service provider_adapter -PostgresDsn $providerDsn -PythonBin $PythonBin
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
./scripts/migrate_service.ps1 -Service ledger -PostgresDsn $ledgerDsn -PythonBin $PythonBin
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
./scripts/migrate_service.ps1 -Service notification -PostgresDsn $notificationDsn -PythonBin $PythonBin
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host 'All migrations applied successfully.'
