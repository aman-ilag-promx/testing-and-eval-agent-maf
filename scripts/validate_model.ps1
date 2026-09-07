param(
	[Parameter(Mandatory = $true)]
	[string]$ModelFile,

	[string]$MypyTarget,

	[string]$ImportCheck
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $pythonExe)) {
	throw "Project virtual environment Python not found at $pythonExe"
}

$modelPath = Join-Path $repoRoot $ModelFile

if (-not (Test-Path $modelPath)) {
	throw "Model file not found: $ModelFile"
}

if ([string]::IsNullOrWhiteSpace($MypyTarget)) {
	$MypyTarget = $ModelFile
}

Set-Location $repoRoot

Write-Host "`n[1/6] Scanning for malformed annotations..."

$malformedPatterns = @(
	'list\[str\]"""',
	'list\[UUID\]"""',
	'dict\[.*\]"""',
	'str"""',
	'Self"""',
	'Path"""',
	'UUID"""'
)

$matches = Select-String -Path $modelPath -Pattern $malformedPatterns

if ($matches) {
	$matches
	throw "Malformed return annotation detected."
}

Write-Host "No malformed return annotations found."

Write-Host "`n[2/6] Compiling the complete source tree..."

& $pythonExe -m compileall -q .\src

if ($LASTEXITCODE -ne 0) {
	throw "Python compilation failed."
}

Write-Host "Python compilation passed."

Write-Host "`n[3/6] Applying Ruff formatting..."

& $pythonExe -m ruff format $ModelFile

if ($LASTEXITCODE -ne 0) {
	throw "Ruff formatting failed."
}

Write-Host "`n[4/6] Running Ruff lint validation..."

& $pythonExe -m ruff check $ModelFile

if ($LASTEXITCODE -ne 0) {
	throw "Ruff linting failed."
}

Write-Host "`n[5/6] Verifying Ruff formatting..."

& $pythonExe -m ruff format --check $ModelFile

if ($LASTEXITCODE -ne 0) {
	throw "Ruff format verification failed."
}

Write-Host "`n[6/6] Running mypy and import validation..."

& $pythonExe -m mypy $MypyTarget

if ($LASTEXITCODE -ne 0) {
	throw "Mypy validation failed."
}

if (-not [string]::IsNullOrWhiteSpace($ImportCheck)) {
	& $pythonExe -c $ImportCheck

	if ($LASTEXITCODE -ne 0) {
		throw "Model import validation failed."
	}
}

Write-Host "`n$ModelFile validation passed."
