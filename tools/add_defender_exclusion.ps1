# add_defender_exclusion.ps1
# Ajoute les exclusions Windows Defender pour llama-cpp-python
# Lance en PowerShell Administrateur

Write-Host "=== Exclusions Windows Defender pour llama-cpp-python ===" -ForegroundColor Cyan

$paths = @(
    "$env:USERPROFILE\miniforge3\Lib\site-packages\llama_cpp",
    "$env:USERPROFILE\miniforge3\python.exe",
    "$env:USERPROFILE\Script python IA\Nokido\app"
)

foreach ($path in $paths) {
    try {
        Add-MpPreference -ExclusionPath $path
        Write-Host "OK  Exclusion ajoutee: $path" -ForegroundColor Green
    } catch {
        Write-Host "FAIL $path : $_" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "Exclusions actuelles:" -ForegroundColor Yellow
(Get-MpPreference).ExclusionPath | ForEach-Object { Write-Host "  - $_" }

Write-Host ""
Write-Host "Teste maintenant: cd Nokido && python sandbox\_test_llamacpp.py" -ForegroundColor Cyan
