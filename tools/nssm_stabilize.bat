@echo off
echo === Nokido Cleanup v1 ===

echo [1/3] Arret NSSM NokidoStreamlit...
nssm stop NokidoStreamlit
nssm set NokidoStreamlit Start SERVICE_DISABLED
echo     -> NokidoStreamlit DISABLED

echo [2/3] Arret NSSM NokidoHub (optionnel - mode direct)...
nssm stop NokidoHub
nssm set NokidoHub Start SERVICE_DEMAND_START
echo     -> NokidoHub en mode MANUEL (ne redémarre plus seul)

echo [3/3] NokidoMCP reste inchangé (géré par Claude Desktop)...

echo.
echo === Résultat ===
nssm status NokidoStreamlit
nssm status NokidoHub
nssm status NokidoMCP
echo.
echo Cleanup terminé. Streamlit ne redémarrera plus automatiquement.
pause
