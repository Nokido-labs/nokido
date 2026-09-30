# Procedure bascule NSSM LocalSystem -> user

## Pourquoi
Le hub Nokido tourne actuellement sous `LocalSystem`. Tous les outils CLI lances par
le hub (gemini.cmd, claude.cmd, ollama, etc.) heritent de ce contexte et regardent
`C:\WINDOWS\system32\config\systemprofile\.gemini\` au lieu de
`~\.gemini\`. Resultat : ton abo Gemini Ultra est invisible cote hub.

## Etat avant
- Service : `LaForgeMCP`
- ObjectName actuel : `LocalSystem`
- Profil hub : `C:\WINDOWS\system32\config\systemprofile\.gemini\` (vide, jamais loggue)
- Profil utilisateur : `~\.gemini\` (compte <your-gmail-oauth-account> en `old`,
  pas de `oauth_creds.json`)

## Etat apres
- ObjectName : `.\user`
- Profil hub = profil utilisateur
- Compte Ultra <your-gmail-oauth-account> utilisable depuis le hub
- WCM (Credential Manager) accessible nativement par-utilisateur

## Procedure

### Etape 1 : Re-login Gemini OAuth (interactif, dans terminal user)

```cmd
gemini
```

A la 1ere question (Auth Method), choisir "Login with Google".
Le browser s'ouvre, choisir <your-gmail-oauth-account>, accepter.

Verification :
```cmd
type %USERPROFILE%\.gemini\oauth_creds.json
type %USERPROFILE%\.gemini\google_accounts.json
```

`google_accounts.json` doit afficher `"active": "<your-gmail-oauth-account>"`.
`oauth_creds.json` doit exister.

### Etape 2 : Lancer le script de bascule (PowerShell admin)

```powershell
cd "~\Script python IA\Nokido"
powershell -ExecutionPolicy Bypass -File tools\nssm_switch_to_user.ps1
```

Le script va :
1. Sauvegarder la config NSSM dans `sandbox/backups/nssm-switch-{timestamp}/`
2. Verifier que `oauth_creds.json` existe
3. Demander ton mot de passe Windows
4. Accorder `SeServiceLogonRight` a user (via secedit)
5. Bascule `nssm set LaForgeMCP ObjectName .\user <mdp>`
6. Restart service + attente /health
7. Test `ask` provider=gemini_cli depuis le hub (verifie auth fonctionne)

### Etape 3 : Verifier

Apres le script :
- `nssm get LaForgeMCP ObjectName` doit afficher `.\user`
- `Get-Service LaForgeMCP` doit etre RUNNING
- Le test gemini_cli a la fin du script doit retourner "pong" (ou similaire)

Si bridge stdio Claude Desktop semble bizarre apres bascule, redemarrer Claude Desktop.

## Rollback

Si quelque chose casse :
```cmd
nssm set LaForgeMCP ObjectName LocalSystem
nssm restart LaForgeMCP
```

Le hub revient sous LocalSystem comme avant. Aucune perte de donnees.

## Risques

- Si le mot de passe user change ulterieurement, le service ne demarrera plus.
  Solution : `nssm set LaForgeMCP ObjectName .\user <nouveau_mdp>`.
- Si user est verrouille, le service ne demarre pas tant que pas deverrouille
  (sauf si le compte a "Log on as a service" qui evite ce probleme - applique).
- Tous les paths absolus dans les configs Nokido restent valides (les chemins
  `~\...` sont identiques quel que soit le compte de service).

## Backup forensique

Avant la bascule, ce qui est sauvegarde :
- `sandbox/backups/nssm-{ts_pre}/nssm_dump.txt` (config complete avant)
- `sandbox/backups/nssm-{ts_pre}/google_accounts.json` (etat profil Gemini)
- `sandbox/backups/nssm-{ts_pre}/MANIFEST.md` (procedure rollback)

Le script PS1 ajoute son propre backup `sandbox/backups/nssm-switch-{ts}/`.
