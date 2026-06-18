$ErrorActionPreference = "Stop"

$ModuleDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Split-Path -Parent $ModuleDir
$Python = Join-Path $RootDir ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    $Python = "python"
}

Push-Location $ModuleDir
try {
    & $Python -m rtm_map_editor
}
finally {
    Pop-Location
}
