# Nokido — wrappers de routage CLI (option B, togglable). Maintenu dans le repo.
#
# Setup (1 ligne dans $PROFILE) :
#   notepad $PROFILE   puis ajoute :
#   . "$env:USERPROFILE/Script python IA/Nokido/tools/nokido_cli_aliases.ps1"
#   ... puis recharge :  . $PROFILE
#
# Usage :
#   lf-route on|off|status [claude|gemini|cline|copilot|all]   # bascule le flag partagé
#   claude-lf / gemini-lf / cline-lf / copilot-lf [args]        # lance le CLI (routé si ON+hub up, sinon natif)
#
# Fallback : si routage ON mais hub :8766 down -> lancement NATIF auto (le CLI ne casse jamais).

$script:LF  = "$env:USERPROFILE/miniforge3/python.exe"
$script:LFR = "$env:USERPROFILE/Script python IA/Nokido/tools/forge_cli_route.py"

function lf-route   { & $script:LF $script:LFR @args }
function claude-lf  { & $script:LF $script:LFR launch claude @args }
function gemini-lf  { & $script:LF $script:LFR launch gemini @args }
function cline-lf   { & $script:LF $script:LFR launch cline @args }
function copilot-lf { & $script:LF $script:LFR launch copilot @args }
