param(
  [Parameter(Mandatory = $true)]
  [ValidateSet('orchestrator','risk','provider_adapter','ledger','notification')]
  [string]$Service,

  [Parameter(Mandatory = $true)]
  [string]$PostgresDsn,

  [string]$PythonBin = 'python'
)

# Applies Alembic migrations for a single service database.
$env:POSTGRES_DSN = $PostgresDsn
& $PythonBin -m alembic -c "alembic/$Service/alembic.ini" upgrade head
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}
