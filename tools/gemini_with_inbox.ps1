# gemini_with_inbox.ps1
# Wrapper pour Gemini CLI qui pre-injecte l'inbox dans le contexte.
#
# USAGE : remplacer "gemini <prompt>" par ".\gemini_with_inbox.ps1 <prompt>"
#   ou mieux : creer un alias PowerShell
#   > Set-Alias gemc ".\gemini_with_inbox.ps1"
#
# PRINCIPE :
#   1. Lit les 5 derniers blocs de ~/.gemini/inbox.md
#   2. Si des nouveaux messages depuis derniere lecture -> ajoute au prompt
#   3. Invoque gemini CLI avec le prompt enrichi
#   4. Marque la timestamp de la derniere lecture dans ~/.gemini/last_read_ts
#
# Resultat : Gemini voit AUTOMATIQUEMENT les notifs nouvelles sans
# avoir besoin de Get-Content manuel.

param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $UserArgs
)

$InboxPath = Join-Path $HOME ".gemini\inbox.md"
$LastReadPath = Join-Path $HOME ".gemini\last_read_ts"
$MaxBlocks = 5

# 1. Determiner le timestamp de derniere lecture
if (Test-Path $LastReadPath) {
    $LastReadTs = [DateTime]::Parse((Get-Content $LastReadPath -Raw).Trim())
} else {
    # Premier usage : lire tout ce qui date des 10 dernieres minutes
    $LastReadTs = (Get-Date).AddMinutes(-10)
}

# 2. Parser l'inbox pour extraire les nouveaux blocs
$NewBlocks = @()
if (Test-Path $InboxPath) {
    $Content = Get-Content $InboxPath -Raw -Encoding utf8
    $Blocks = $Content -split '(?=^## \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', 0, 'Multiline'
    
    foreach ($Block in $Blocks) {
        if ($Block -match '^## (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})') {
            $BlockTs = [DateTime]::Parse($Matches[1])
            if ($BlockTs -gt $LastReadTs) {
                $NewBlocks += $Block.Trim()
            }
        }
    }
    
    # Limiter aux N plus recents pour eviter de polluer le contexte
    if ($NewBlocks.Count -gt $MaxBlocks) {
        $NewBlocks = $NewBlocks[-$MaxBlocks..-1]
    }
}

# 3. Construire le prompt enrichi
$UserPrompt = $UserArgs -join " "

if ($NewBlocks.Count -gt 0) {
    $InboxContext = @"
[INBOX NOKIDO - $($NewBlocks.Count) nouvelle(s) notification(s) depuis derniere session]

$($NewBlocks -join "`n---`n")

---

[PROMPT UTILISATEUR]
$UserPrompt
"@
    
    Write-Host "[gemini_with_inbox] $($NewBlocks.Count) nouvelle(s) notif(s) pre-injectee(s)" -ForegroundColor Yellow
} else {
    $InboxContext = $UserPrompt
    Write-Host "[gemini_with_inbox] inbox a jour, prompt pur" -ForegroundColor Green
}

# 4. Marquer le timestamp de cette lecture
(Get-Date).ToString("yyyy-MM-dd HH:mm:ss") | Set-Content -Path $LastReadPath -Encoding utf8

# 5. Invoquer gemini CLI
gemini $InboxContext
