param(
    [Parameter(Mandatory=$true)]
    [string]$Service,
    [Parameter(Mandatory=$true)]
    [ValidateSet("py312", "py314")]
    [string]$Target,
    [switch]$DryRun
)

$pyMap = @{
    "py312" = "$env:USERPROFILE\miniforge3\python.exe"
    "py314" = "$env:USERPROFILE\miniforge3\envs\laforge_py314\python.exe"
}
$py = $pyMap[$Target]

Write-Host "[$Service] BEFORE Application: $(nssm get $Service Application)"
Write-Host "[$Service] BEFORE AppParameters: $(nssm get $Service AppParameters)"

if ($DryRun) {
    Write-Host "[DRY-RUN] Would switch to: $py"
    exit 0
}

nssm set $Service Application $py
if ($Target -eq "py314") {
    # Multiline env block (NSSM accepts CRLF separator)
    $envBlock = "PYTHONIOENCODING=utf-8`r`nPYTHONUTF8=1`r`nPYTHONNOUSERSITE=1"
    nssm set $Service AppEnvironmentExtra $envBlock
} else {
    # py312 base also needs UTF8 for Graph + others using emoji prints
    $envBlock = "PYTHONIOENCODING=utf-8`r`nPYTHONUTF8=1"
    nssm set $Service AppEnvironmentExtra $envBlock
}
nssm restart $Service
Start-Sleep -Seconds 12
$status = (nssm status $Service)
Write-Host "[$Service] AFTER  Application: $(nssm get $Service Application)"
Write-Host "[$Service] Status: $status"

if ($status -ne "SERVICE_RUNNING") {
    # Wait longer for heavy services (torch_geometric, etc.) before rollback
    Write-Host "Waiting +20s for heavy startup..."
    Start-Sleep -Seconds 20
    $status = nssm status $Service
    Write-Host "Status after extra wait:" $status
}
if ($status -ne "SERVICE_RUNNING") {
    Write-Host "ERR service NOT RUNNING after 32s - manual investigation required" -ForegroundColor Red
    exit 1
}
exit 0
