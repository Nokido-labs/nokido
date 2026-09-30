# PROTOCOLE AUTH GEMINI CLI — 2026-04-28T15:30 CEST
# Statut: DÉFINITIF — cause racine identifiée dans chunk-WFCK2Z32.js

## Cause racine

getConsentForOauth() a 3 branches :
  1. isHeadlessMode() → true → getOauthConsentNonInteractive() (stdin readline)
  2. CoreEvent.ConsentRequest listener présent → getOauthConsentInteractive()
  3. Aucun des deux → FatalAuthenticationError "consent could not be obtained"

Le restart post-/auth relance le process sans TTY propre (Windows) :
  - isHeadlessMode() = true (stdin.isTTY = false)
  - Mais getOauthConsentNonInteractive() essaie de lire stdin → bloqué car pas de TTY
  - Résultat : "Authentication consent could not be obtained"

## PROTOCOLE CORRECT (une fois pour toutes)

### Étape 1 — Supprimer le token expiré/corrompu
```powershell
Remove-Item "$env:USERPROFILE\.gemini\oauth_creds.json" -Force
```

### Étape 2 — Lancer Gemini dans un VRAI terminal interactif
Ouvrir un NOUVEAU PowerShell ou CMD (pas Windows Terminal embedded, pas VS Code terminal).
Taper simplement :
```powershell
gemini
```
Sans aucun argument. Le CLI détecte le TTY → isHeadlessMode() = false → 
ConsentRequest listener actif → navigateur s'ouvre → auth complète → token sauvé.

### Étape 3 — NE PLUS utiliser /auth
Une fois authentifié, le token dure jusqu'à expiration (~1h).
Ne JAMAIS taper /auth dans une session déjà lancée — ça relance le process
sans TTY et brise le handshake.

### Étape 4 — Si le navigateur ne s'ouvre pas automatiquement
```powershell
$env:NO_BROWSER = "true"
gemini
```
Le CLI affiche une URL à copier-coller manuellement dans le navigateur.

## Pour les sessions suivantes (token valide)
```powershell
gemini  # dans un PowerShell natif, sans argument
```
Le CLI lit ~/.gemini/oauth_creds.json → pas besoin de re-auth.

## Watcher settings.json (protection headless)
Le CLI réécrit headless.disableMcp=true à chaque restart sans TTY.
Watcher à créer : forge_gemini_settings_watcher.py (surveille le fichier
et repatche disableMcp=false si réécrit — BACKLOG)
