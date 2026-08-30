param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[A-Fa-f0-9]{64}$")]
    [string]$AcceptedSourceTreeId
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Version = "0.8.0"
$ReleaseRoot = Join-Path $Root "Release\v$Version"
$ReadyRoot = Join-Path $Root "Release\Release Ready"
# Historical source-gate marker: Join-Path $env:TEMP "LeanDesk_0.8.0_Correction_4_Build_Venv"
# Historical source-gate marker: Join-Path $env:TEMP "LeanDesk_0.8.0_Correction_5_Build_Venv"
$Venv = Join-Path $env:TEMP "LeanDesk_0.8.0_Correction_6_Build_Venv"
$Dist = Join-Path $Root "dist"
$Build = Join-Path $Root "build"
$BuildStartUtc = [DateTime]::UtcNow.ToString("o")

function Write-Step([string]$Text) {
    Write-Host "`n=== $Text ===" -ForegroundColor Cyan
}

function Require-File([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Required file missing: $Path"
    }
}

function Find-SignTool {
    $patterns = @(
        "$env:ProgramFiles(x86)\Windows Kits\10\bin\*\x64\signtool.exe",
        "$env:ProgramFiles(x86)\Windows Kits\10\bin\x64\signtool.exe"
    )
    foreach ($pattern in $patterns) {
        $found = Get-ChildItem -Path $pattern -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending |
            Select-Object -First 1
        if ($found) { return $found.FullName }
    }
    return $null
}

function Get-OrCreate-Certificate {
    $subject = "CN=Dietrich AI Labs"
    $cert = Get-ChildItem Cert:\CurrentUser\My | Where-Object {
        $_.Subject -eq $subject -and
        $_.HasPrivateKey -and
        $_.EnhancedKeyUsageList.ObjectId -contains "1.3.6.1.5.5.7.3.3"
    } | Sort-Object NotAfter -Descending | Select-Object -First 1
    if (-not $cert) {
        $cert = New-SelfSignedCertificate `
            -Type CodeSigningCert `
            -Subject $subject `
            -CertStoreLocation Cert:\CurrentUser\My `
            -KeyAlgorithm RSA `
            -KeyLength 3072 `
            -HashAlgorithm SHA256 `
            -NotAfter (Get-Date).AddYears(5)
    }
    return $cert
}

Set-Location $Root
Write-Step "Preflight"
$required = @(
    "lean_desk_suite.py", "make_artwork.py", "README.md", "EULA.txt",
    "LICENSE.txt", "THIRD_PARTY_NOTICES.txt", "LeanDesk_Suite_Installer.iss",
    "requirements.lock.txt", "tools\run_authoritative_tests.py",
    "tools\package_cleanliness.py", "tools\source_manifest.py",
    "tools\validate_build_gate.py", "SOURCE_MANIFEST.json", "SOURCE_TREE_ID.txt",
    "test_leandesk.py", "test_compatibility.py",
    "tests\test_correction_1_safety.py", "tests\test_correction_2_qa.py",
    "tests\test_correction_3_qa.py", "tests\test_correction_4_qa.py",
    "tests\test_correction_5_qa.py", "tests\test_correction_6_qa.py"
)
foreach ($name in $required) { Require-File (Join-Path $Root $name) }

$Python = $null
if (Get-Command py -ErrorAction SilentlyContinue) { $Python = "py" }
elseif (Get-Command python -ErrorAction SilentlyContinue) { $Python = "python" }
else { throw "Python 3 was not found." }

$env:PYTHONDONTWRITEBYTECODE = "1"
$env:PYTEST_ADDOPTS = "-p no:cacheprovider"
$AcceptedSourceTreeId = $AcceptedSourceTreeId.ToUpperInvariant()
$SourceManifestPath = Join-Path $Root "SOURCE_MANIFEST.json"

Write-Step "Verify accepted source identity"
& $Python (Join-Path $Root "tools\source_manifest.py") --root $Root --verify
if ($LASTEXITCODE -ne 0) { throw "Recorded source manifest is invalid." }
$PreTestSourceTreeId = (Get-Content -LiteralPath (Join-Path $Root "SOURCE_TREE_ID.txt") -Raw).Trim().ToUpperInvariant()
if ($PreTestSourceTreeId -ne $AcceptedSourceTreeId) { throw "Accepted source-tree identity mismatch." }
$SourceManifestSHA256 = (Get-FileHash -LiteralPath $SourceManifestPath -Algorithm SHA256).Hash

Write-Step "Clear all stale shipping outputs before the gate"
Remove-Item $Dist, $Build, $ReleaseRoot, $ReadyRoot, (Join-Path $Root "LeanDesk_Suite.spec") `
    -Recurse -Force -ErrorAction SilentlyContinue

Write-Step "Verify exact source staging cleanliness"
& $Python (Join-Path $Root "tools\package_cleanliness.py") $Root
if ($LASTEXITCODE -ne 0) { throw "Source staging contains cache, bytecode, link, or reparse artifacts." }

Write-Step "Create isolated build environment"
if (-not (Test-Path $Venv)) {
    if ($Python -eq "py") { & py -3 -m venv $Venv }
    else { & python -m venv $Venv }
}
$VenvPython = Join-Path $Venv "Scripts\python.exe"
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r (Join-Path $Root "requirements.lock.txt")

Write-Step "Run canonical recursive automated gate"
$RunId = [Guid]::NewGuid().ToString("N")
$GateEvidenceRoot = Join-Path $env:LOCALAPPDATA "LeanDeskBuildEvidence\0.8.0-c6\$RunId"
New-Item $GateEvidenceRoot -ItemType Directory -Force | Out-Null
$GateReport = Join-Path $GateEvidenceRoot "AUTHORITATIVE_TEST_GATE.json"
$PytestTempRoot = Join-Path $GateEvidenceRoot "pytest-owned-temp"
& $VenvPython (Join-Path $Root "tools\run_authoritative_tests.py") `
    --report $GateReport --basetemp $PytestTempRoot
$GateExitCode = $LASTEXITCODE
Require-File $GateReport
$GateAuthorization = Join-Path $GateEvidenceRoot "BUILD_GATE_AUTHORIZATION.json"
& $VenvPython (Join-Path $Root "tools\validate_build_gate.py") `
    --report $GateReport `
    --source-root $Root `
    --expected-source-id $AcceptedSourceTreeId `
    --expected-manifest-sha256 $SourceManifestSHA256 `
    --authorization $GateAuthorization
if ($LASTEXITCODE -ne 0 -or $GateExitCode -ne 0) { throw "Canonical automated gate failed closed before packaging." }
Require-File $GateAuthorization

Write-Step "Generate artwork"
& $VenvPython make_artwork.py
if ($LASTEXITCODE -ne 0) { throw "Artwork generation failed." }
& $VenvPython (Join-Path $Root "tools\source_manifest.py") --root $Root --verify
if ($LASTEXITCODE -ne 0) { throw "Source identity changed before PyInstaller." }
if ((Get-FileHash -LiteralPath $SourceManifestPath -Algorithm SHA256).Hash -ne $SourceManifestSHA256) {
    throw "Source manifest changed before PyInstaller."
}

Write-Step "Build one-file Windows application"
Require-File $GateAuthorization
Remove-Item $Dist, $Build -Recurse -Force -ErrorAction SilentlyContinue
& $VenvPython -m PyInstaller `
    --noconfirm --clean --onefile --windowed --specpath $Build `
    --name "LeanDesk_Suite" `
    --icon (Join-Path $Root "lean_desk_suite.ico") `
    --version-file (Join-Path $Root "version_info.txt") `
    --add-data "README.md;." `
    --add-data "EULA.txt;." `
    --add-data "CHANGELOG.md;." `
    --add-data "LICENSE.txt;." `
    --add-data "THIRD_PARTY_NOTICES.txt;." `
    --add-data "assets;assets" `
    --collect-all docx `
    --collect-all reportlab `
    --collect-all openpyxl `
    --collect-all pptx `
    --collect-all spellchecker `
    (Join-Path $Root "lean_desk_suite.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }
$Exe = Join-Path $Dist "LeanDesk_Suite.exe"
Require-File $Exe
& $VenvPython (Join-Path $Root "tools\source_manifest.py") --root $Root --verify
if ($LASTEXITCODE -ne 0) { throw "Source identity changed before Inno Setup." }

Write-Step "Prepare release directories"
Remove-Item $ReleaseRoot, $ReadyRoot -Recurse -Force -ErrorAction SilentlyContinue
New-Item $ReleaseRoot, $ReadyRoot -ItemType Directory -Force | Out-Null
Copy-Item $Exe $ReleaseRoot
$ReleaseExe = Join-Path $ReleaseRoot "LeanDesk_Suite.exe"
Copy-Item (Join-Path $Root "lean_desk_suite.ico") $ReleaseRoot
Copy-Item (Join-Path $Root "README.md") $ReleaseRoot
Copy-Item (Join-Path $Root "CHANGELOG.md") $ReleaseRoot
Copy-Item (Join-Path $Root "EULA.txt") $ReleaseRoot
Copy-Item (Join-Path $Root "LICENSE.txt") $ReleaseRoot
Copy-Item (Join-Path $Root "THIRD_PARTY_NOTICES.txt") $ReleaseRoot
Copy-Item (Join-Path $Root "assets") (Join-Path $ReleaseRoot "assets") -Recurse
Copy-Item $GateReport (Join-Path $ReleaseRoot "AUTHORITATIVE_TEST_GATE.json")

Write-Step "Self-sign application when SignTool is available"
$SignTool = Find-SignTool
$Cert = Get-OrCreate-Certificate
$PublicCert = Join-Path $ReleaseRoot "Dietrich_AI_Labs_Public_Certificate.cer"
Export-Certificate -Cert $Cert -FilePath $PublicCert -Force | Out-Null
if ($SignTool) {
    & $SignTool sign /sha1 $Cert.Thumbprint /fd SHA256 /td SHA256 /tr http://timestamp.digicert.com $ReleaseExe
    if ($LASTEXITCODE -ne 0) { throw "EXE signing failed." }
    & $SignTool verify /pa /v $ReleaseExe |
        Out-File (Join-Path $ReleaseRoot "SIGNATURE_REPORT.txt") -Encoding utf8
} else {
    "Windows SDK SignTool was not found. The certificate was created/exported, but the EXE was not signed." |
        Out-File (Join-Path $ReleaseRoot "SIGNATURE_REPORT.txt") -Encoding utf8
}

Write-Step "Locate Inno Setup"
$ISCC = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles(x86)\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $ISCC -and (Get-Command winget -ErrorAction SilentlyContinue)) {
    winget install --id JRSoftware.InnoSetup -e `
        --accept-source-agreements --accept-package-agreements --silent
    $ISCC = @(
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles(x86)\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $ISCC) {
    throw "Inno Setup 6 was not found and could not be installed automatically."
}

Write-Step "Build installer"
Require-File $GateAuthorization
& $ISCC "/DSourceRoot=$ReleaseRoot" "/DOutputRoot=$ReleaseRoot" `
    (Join-Path $Root "LeanDesk_Suite_Installer.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup build failed." }
$Installer = Join-Path $ReleaseRoot "LeanDesk_Suite_Setup_0.8.0.exe"
Require-File $Installer
if ($SignTool) {
    & $SignTool sign /sha1 $Cert.Thumbprint /fd SHA256 /td SHA256 /tr http://timestamp.digicert.com $Installer
    if ($LASTEXITCODE -ne 0) { throw "Installer signing failed." }
    "`n`n===== INSTALLER SIGNATURE =====`n" | Add-Content (Join-Path $ReleaseRoot "SIGNATURE_REPORT.txt")
    & $SignTool verify /pa /v $Installer | Add-Content (Join-Path $ReleaseRoot "SIGNATURE_REPORT.txt")
}

Write-Step "Create complete shipping checksums"
$ChecksumPath = Join-Path $ReleaseRoot "SHA256SUMS.txt"
Get-ChildItem $ReleaseRoot -File -Recurse |
    Where-Object { $_.FullName -ne $ChecksumPath } |
    Sort-Object FullName |
    ForEach-Object {
    $hash = Get-FileHash $_.FullName -Algorithm SHA256
    $relative = [IO.Path]::GetRelativePath($ReleaseRoot, $_.FullName).Replace("\", "/")
    "$($hash.Hash)  $relative"
} | Set-Content $ChecksumPath -Encoding ascii

Write-Step "Create release packages"
Require-File $GateAuthorization
$Portable = Join-Path $ReadyRoot "LeanDesk_Suite_Portable_0.8.0.zip"
$InstallerZip = Join-Path $ReadyRoot "LeanDesk_Suite_Installer_0.8.0.zip"
$Complete = Join-Path $ReadyRoot "LeanDesk_Suite_Complete_0.8.0.zip"

Compress-Archive -Path @(
    $ReleaseExe,
    (Join-Path $ReleaseRoot "lean_desk_suite.ico"),
    (Join-Path $ReleaseRoot "README.md"),
    (Join-Path $ReleaseRoot "EULA.txt"),
    (Join-Path $ReleaseRoot "LICENSE.txt"),
    (Join-Path $ReleaseRoot "THIRD_PARTY_NOTICES.txt"),
    $PublicCert,
    (Join-Path $ReleaseRoot "SHA256SUMS.txt")
) -DestinationPath $Portable -Force

Compress-Archive -Path @(
    $Installer,
    $PublicCert,
    (Join-Path $ReleaseRoot "README.md"),
    (Join-Path $ReleaseRoot "EULA.txt"),
    (Join-Path $ReleaseRoot "SHA256SUMS.txt")
) -DestinationPath $InstallerZip -Force

Compress-Archive -Path (Join-Path $ReleaseRoot "*") -DestinationPath $Complete -Force

Write-Step "Verify final source identity and write build provenance"
& $VenvPython (Join-Path $Root "tools\source_manifest.py") --root $Root --verify
if ($LASTEXITCODE -ne 0) { throw "Source identity changed during build." }
$PostBuildSourceTreeId = (Get-Content -LiteralPath (Join-Path $Root "SOURCE_TREE_ID.txt") -Raw).Trim().ToUpperInvariant()
$PostBuildManifestSHA256 = (Get-FileHash -LiteralPath $SourceManifestPath -Algorithm SHA256).Hash
if ($PostBuildSourceTreeId -ne $AcceptedSourceTreeId -or $PostBuildManifestSHA256 -ne $SourceManifestSHA256) {
    throw "Final source identity does not match the authorized source."
}
$BuildStopUtc = [DateTime]::UtcNow.ToString("o")
$BuildProvenance = [ordered]@{
    schema = 1
    classification = "ENGINEERING_BUILD_EVIDENCE_NOT_QA_APPROVAL"
    accepted_source_tree_id = $AcceptedSourceTreeId
    source_manifest_sha256 = $SourceManifestSHA256
    source_identity_before_build = $PreTestSourceTreeId
    source_identity_after_build = $PostBuildSourceTreeId
    source_identity_matched_before_and_after = $true
    build_start_utc = $BuildStartUtc
    build_stop_utc = $BuildStopUtc
    authoritative_test_gate_sha256 = (Get-FileHash -LiteralPath $GateReport -Algorithm SHA256).Hash
    exe_sha256 = (Get-FileHash -LiteralPath $ReleaseExe -Algorithm SHA256).Hash
    installer_sha256 = (Get-FileHash -LiteralPath $Installer -Algorithm SHA256).Hash
    portable_zip_sha256 = (Get-FileHash -LiteralPath $Portable -Algorithm SHA256).Hash
    installer_zip_sha256 = (Get-FileHash -LiteralPath $InstallerZip -Algorithm SHA256).Hash
    complete_release_zip_sha256 = (Get-FileHash -LiteralPath $Complete -Algorithm SHA256).Hash
}
$BuildProvenance | ConvertTo-Json -Depth 4 |
    Set-Content (Join-Path $GateEvidenceRoot "BUILD_PROVENANCE.json") -Encoding utf8

Write-Step "Complete"
Write-Host "Detailed release: $ReleaseRoot" -ForegroundColor Green
Write-Host "GitHub-ready ZIPs: $ReadyRoot" -ForegroundColor Green
Write-Host "Build evidence: $GateEvidenceRoot" -ForegroundColor Green
