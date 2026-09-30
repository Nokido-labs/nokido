# run_jea_admin.ps1 — Lance install_jea.ps1 en tant qu'admin
Start-Process powershell -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$env:USERPROFILE\Script python IA\Nokido\config\jea\install_jea.ps1`"" -Wait
