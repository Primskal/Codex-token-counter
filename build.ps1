[CmdletBinding()]
param(
    [string]$OutputDirectory
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $projectRoot 'dist'
}
if (-not [System.IO.Path]::IsPathRooted($OutputDirectory)) {
    $OutputDirectory = Join-Path $projectRoot $OutputDirectory
}
$OutputDirectory = [System.IO.Path]::GetFullPath($OutputDirectory)

# Release artifacts intentionally remain in dist.  A versioned copy lets a
# running older release coexist with the just-built default executable.
$projectToml = Join-Path $projectRoot 'pyproject.toml'
$versionLine = Select-String -LiteralPath $projectToml -Pattern '^version\s*=\s*"(?<version>[^"]+)"' | Select-Object -First 1
if (-not $versionLine) {
    throw "pyproject.toml에서 프로젝트 버전을 찾을 수 없습니다: $projectToml"
}
$version = $versionLine.Matches[0].Groups['version'].Value
if ($version -notmatch '^[0-9]+\.[0-9]+\.[0-9]+$') {
    throw "버전 파일명에 사용할 수 없는 프로젝트 버전입니다: $version"
}

if (-not (Test-Path -LiteralPath $python)) {
    py -3.13 -m venv (Join-Path $projectRoot '.venv')
}

& $python -m pip install -r (Join-Path $projectRoot 'requirements-dev.txt')
if ($LASTEXITCODE -ne 0) { throw '개발 의존성 설치에 실패했습니다.' }
& $python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw '테스트에 실패했습니다.' }
& $python -m PyInstaller --clean --noconfirm --distpath $OutputDirectory (Join-Path $projectRoot 'CodexTokenMonitor.spec')
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 빌드에 실패했습니다. 실행 중인 기존 EXE가 잠겨 있으면 종료 후 다시 시도하세요." }

$artifact = Join-Path $OutputDirectory 'CodexTokenMonitor.exe'
# A source-level manifest declaration is insufficient: verify that PyInstaller
# placed the exact declaration in the freshly produced PE resource.
$env:CODEX_TOKEN_MONITOR_RELEASE_EXE = $artifact
& $python -m pytest -q (Join-Path $projectRoot 'tests\test_windows_dpi_manifest.py')
if ($LASTEXITCODE -ne 0) { throw '생성된 EXE의 DPI 매니페스트 검사에 실패했습니다.' }
$env:CODEX_TOKEN_MONITOR_RELEASE_EXE = $null

if (-not (Test-Path -LiteralPath $artifact)) {
    throw "빌드 산출물을 찾을 수 없습니다: $artifact"
}
$versionedArtifact = Join-Path $OutputDirectory ("CodexTokenMonitor-v{0}.exe" -f $version)
Copy-Item -LiteralPath $artifact -Destination $versionedArtifact -Force

$primaryHash = (Get-FileHash -LiteralPath $artifact -Algorithm SHA256).Hash
$versionedHash = (Get-FileHash -LiteralPath $versionedArtifact -Algorithm SHA256).Hash
if ($primaryHash -ne $versionedHash) {
    throw "기본 및 버전 실행 파일의 SHA-256이 일치하지 않습니다."
}
Write-Host "빌드 완료: $artifact"
Write-Host "버전 산출물: $versionedArtifact"
Write-Host "SHA-256: $primaryHash"
