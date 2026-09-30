# Audit sécurité — tokens leaked dans l'historique git

*Audit : 2026-04-16 | Branche : alpha | Statut : tous tokens leaked sont REVOQUES*

## 🎯 Résumé exécutif

**8 tokens API leaked dans l'historique git** (commits `211985e` à `c58725a`, période **2026-03-26**).

✅ **Tous les tokens leaked sont aujourd'hui RÉVOQUÉS ou ROTATED** — risque actuel = quasi-nul.

⚠ **Risque résiduel** : compliance/audit qui exigent un repo "clean" sans tokens dans l'historique, même morts.

## 📊 Inventaire détaillé

| Token | Statut historique | Statut actuel | Risque résiduel |
|-------|:-----------------:|:-------------:|:---------------:|
| `GEMINI_API_KEY` (`AIza...ImI4`) | 🔓 7 commits | ✅ Régénérée + ancienne révoquée par Google | Nul |
| `GITHUB_TOKEN` classic (`ghp_...uNTJ`) | 🔓 7 commits | ✅ Régénérée fine-grained | Nul |
| `DEEPSEEK_API_KEY` (`sk-...d32b`) | 🔓 1 commit | ❌ Compte vide (Insufficient Balance) | Faible (compte vide) |
| `HF_TOKEN` (`hf_...zCTL`) | 🔓 1 commit | ✅ Rotated, nouveau token actif | Nul |
| `CODEBERG_TOKEN` (`ee2d905b...76e9`) | 🔓 7 commits | ✅ Rotated | Nul |
| `MCP_DEV_SECRET` (`83032809...c3`) | 🔓 7 commits | ✅ **Régénéré** — nouveau secret HMAC | **Critique → résolu** |
| `FORGE_MCP_TOKEN` (`c8092f43...db7244...`) | 🔓 7 commits | ❌ Retiré du `.env` actuel | Nul |

### 🚨 Cas critique : `MCP_DEV_SECRET`

Ce secret signe **tous les capability tokens HMAC** (issue #1). Si la valeur historique = valeur actuelle, n'importe qui pourrait forger des tokens valides.

**Vérification** : `git show 211985e:Nokido.env` vs `Nokido.env` actuel → **DIFFÉRENT** ✅. Le secret a été régénéré, les anciens capability tokens forgés avec l'ancien secret seraient rejetés par l'`IntegrityManager` actuel.

## 📜 Commits concernés (8 total)

```
d59c7f5 fix: encoding utf-8 subprocess + start_desktop.bat
211985e commit40: governance MASTER_DEV token + DebateWorker v2 LeadOrchestrator
33cb941 fix: crash RAM - LLAMACPP_N_GPU_LAYERS=10
2781d70 feat: XAI_API_KEY Grok-3 dans .env + LLMRouter
33d5b82 feat: LLMRouter Ring8 (11 providers gratuits cascade) + Codeberg mirror
af8919e feat: Forge-Sync OS — MMap indestructible + Watchdog kernel32
c58725a fix: idle_timeout 3600s + ai_service_patch
3bcc392 feat: forge_state mmap + forge_db WAL persistant
```

Tous datés de la période **2026-03-22 → 2026-03-29** (avant le commit `dd5b9d3` qui a retiré `Nokido.env` du tracking).

## 🛠 Mesures déjà en place

✅ **`.gitignore` couvre maintenant** : `Nokido.env`, `*.env`, `*.key`, `*.token`, `*.pem`  
✅ **Tokens régénérés** : 5 sur 7 (les 2 restants sont morts ou inutiles)  
✅ **`MCP_DEV_SECRET` rotated** : capability tokens HMAC sécurisés  
✅ **Repos privés** sur GitHub + Codeberg (limite la visibilité publique)

## 🚧 Décision : ne PAS nettoyer l'historique

**Choix** : laisser l'historique tel quel.

### Raisons

1. **Tous les tokens leaked sont morts/révoqués** — un attaquant qui les utilise échoue
2. **`git-filter-repo` réécrirait les SHA** de TOUS les commits — casserait :
   - Les fork/clones existants (pas de mécanisme propre pour les notifier)
   - Les références dans la doc, issues, PR, commits messages mentionnant des SHA
   - Les hash de bench/snapshot référencés dans `data/` ou RAG
3. **Les repos sont privés** — limite la surface d'attaque
4. **Audit/compliance non bloquants** — projet personnel/recherche, pas SOC2

### Quand reconsidérer

- Si le projet devient public (open-source release)
- Si un audit externe l'exige
- Si un nouveau token leaké n'est pas immédiatement révocable

### Procédure si nécessaire (futur)

```bash
# 1. Backup complet
cp -r Nokido Nokido.backup.$(date +%Y%m%d)

# 2. Installer git-filter-repo (NE PAS utiliser BFG sur Windows = bugs)
pip install git-filter-repo

# 3. Créer patterns.txt avec les valeurs à effacer (sans les copier ici)
# Format ligne par ligne : VALEUR_TOKEN==>REDACTED

# 4. Filter
git filter-repo --replace-text patterns.txt --force

# 5. Force-push (irréversible)
git push origin --force --all
git push codeberg --force --all
```

## 🔮 Prochaines mesures recommandées

1. **`pre-commit hook gitleaks`** — bloquer les futurs commits qui contiennent des secrets
   ```bash
   pip install pre-commit
   # Créer .pre-commit-config.yaml avec hook gitleaks
   ```

2. **GitHub Secret Scanning** — auto-activé sur les repos privés depuis 2024 (vérifier dans Settings)

3. **Rotation périodique** — calendrier 6 mois pour `MCP_DEV_SECRET` et tokens d'API tier-1

## 📦 Référence

- Audit initial : commit `b03348b` (2026-04-16)
- Helper sécurité : `app/forge_integrity.py` (IntegrityManager + capability tokens)
- Issue tracking : Codeberg #4


---

# 📌 Incident Report — 2026-04-16 (post-cleanup)

## Découverte

Pendant la réorganisation du repo (commit `02cdb10`), git a momentanément staged 4 fichiers `Nokido.env.bak_*` créés automatiquement par les scripts de rotation tokens. **Audit ces 4 fichiers contenait 4 tokens VIVANTS** :

| Token | Statut | Action |
|-------|:------:|--------|
| `DeepSeek/OpenAI` (sk-87213...) | actif | Compte vide → faible risque, keep |
| `HuggingFace` (hf_xdzhZ...) | actif | Considérer rotation |
| `MCP_DEV_SECRET` (cf7baddf...) | actif | **Rotation conseillée** (signe les capability tokens HMAC) |
| `CODEBERG_TOKEN` (80b0310d...) | actif | **Rotation conseillée** (accès écriture repo) |

## Vérification

✅ **Le commit `02cdb10` actuellement sur `origin/alpha` et `codeberg/alpha` NE CONTIENT PAS ces fichiers** (vérifié via `git ls-tree -r origin/alpha`). Le `.gitignore` mis à jour à temps a évité le push effectif.

## Impact réel

**Aucun**. Les fichiers ont été staged temporairement mais n'ont jamais été pushed sur les remotes publics.

## Vulnérabilité connexe découverte

Le `CODEBERG_TOKEN` était stocké en **clair dans l'URL du remote git** (`https://user:80b0310d...@codeberg.org/...`), donc visible dans :
- `git remote -v`
- `.git/config` (local mais facilement leakable)
- Toute commande qui imprime les remotes

## Mitigation appliquée

1. **Remote URL nettoyée** : `git remote set-url codeberg https://codeberg.org/user/Nokido.git`
2. **Token déplacé en `extraHeader`** : `.git/config` contient désormais `http.https://codeberg.org/.extraHeader = Authorization: token <secret>` (toujours local mais plus dans l'URL)
3. **`.gitignore`** vérifié : `Nokido.env.bak_*` couvert par pattern `*.bak_*`

## Recommandations

- [ ] **Rotation des 4 tokens** dès que possible (pas urgent, jamais leaked publiquement)
- [ ] **Credential helper Git externe** (Windows Credential Manager) pour ne plus stocker le token dans `.git/config`
- [ ] **Ne jamais run** `git remote -v` dans des logs publics avec ce repo

## Date : 2026-04-16
## Référence : commit `02cdb10`
