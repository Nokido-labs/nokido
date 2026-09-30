---
type: guide
title: 08 — Vault & secrets
status: draft
resource: repo://docs/wiki/08-Vault-and-Secrets.fr.md
generated: {by: forge_wiki_modules@INCONNU, at: 2026-09-22T13:02:47+00:00}
empreinte: INCONNUE
---

# 08 — Vault & secrets

<!-- revu-le: 2026-09-29 -->
> Mise à jour : 2026-09-29

> 🌐 [English](08-Vault-and-Secrets.md) · **Français**

Nokido stocke les secrets dans un vault chiffré par l'OS — **jamais** dans `.env` committé. Cette page couvre l'architecture vault, le CLI, et la migration depuis des setups `.env`-only legacy.

## 🔐 Pourquoi pas `.env` ?

Un fichier `.env` est :
- Facilement committé par accident.
- Plaintext sur disque, lisible par tout process local.
- Per-clone, per-host : à re-déployer sur chaque machine.
- Non chiffré — backups, snapshots, `Get-Childitem env:` l'exposent.

Nokido a migré 33+ secrets hors de `.env` vers un vault chiffré machine-wide en mai 2026. Le `.env` restant ne contient que de la **config** (URLs, ports, flags) — jamais de secrets.

## 🗄️ Backends par OS

| OS | Backend | Module | Scope |
|---|---|---|---|
| Windows | DPAPI `CRYPTPROTECT_LOCAL_MACHINE` | `ctypes.windll.crypt32` (pas besoin pywin32) | Machine-wide — lisible par tous comptes locaux (sandbox users inclus). |
| macOS | Keychain | `keyring` (Python) | Per-user. |
| Linux | libsecret / Secret Service | `keyring` (Python) | Per-user, requiert package `libsecret` + daemon keyring (GNOME Keyring, KWallet, etc.). |

Backend auto-détecté au runtime via `sys.platform`. Module : `app/forge_machine_vault.py::available()`.

### Pourquoi machine-wide sur Windows ?

Nokido a plusieurs **comptes service non-user** : `LaForgeSbxOnline`, `LaForgeSbxOffline`, `LaForgeTrustedRunners`, `LaForge-Master` (SYSTEM). Le DPAPI **user-scope** rendrait les secrets de chaque compte invisibles aux autres. Le DPAPI machine-scope (flag `0x04`) résout ça : chiffrement avec la clé machine, déchiffrement par tout compte local.

## 🔄 La chaîne de priorité

`app/forge_secrets.py::get_secret()` parcourt :

```
1. Cache mémoire (per-session)
   ↓ miss
2. Vault machine (DPAPI / Keychain / libsecret)
   ↓ miss
3. WCM (Windows Credential Manager, per-user) — legacy
   ↓ miss
4. Nokido.env — last resort, warning logué
   ↓ miss
5. os.environ — last-last resort, warning logué
   ↓ miss
6. return None (ou raise ValueError si required=True)
```

## 📋 CLI

### `nokido-secrets`

```bash
# Voir où sont les secrets
nokido-secrets status
# Coffre machine (12): ['FORGE_TOKEN_CLAUDE', 'FORGE_TOKEN_GEMINI', ...]
# Manquants (2): ['ANTHROPIC_API_KEY', 'OPENROUTER_API_KEY']

# Set un secret
nokido-secrets set --key GROQ_API_KEY

# Get (preview only — last 4 chars)
nokido-secrets get --key GROQ_API_KEY
# GROQ_API_KEY = ***xx1z
```

### `nokido-vault` — direct CRUD

```bash
nokido-vault test
nokido-vault list
nokido-vault set -k CLE
nokido-vault get -k CLE
nokido-vault del -k CLE
```

### API Python

```python
from forge_secrets import get_secret, set_secret, require

token = get_secret("FORGE_MCP_TOKEN", required=True)  # raise si absent

creds = require("GROQ_API_KEY", "GEMINI_API_KEY")

set_secret("MY_KEY", "secret-value")

from forge_secrets import invalidate_cache
invalidate_cache("MY_KEY")  # après rotation
```

## 🧪 Bootstrap fresh install

```bash
# 1. Migrer le master token
nokido-secrets set -k FORGE_MCP_TOKEN

# 2. Générer per-agent tokens
python tools/forge_vault_seed_agent_tokens.py --from-env-file Nokido.env

# 3. Verify
python tools/forge_vault_seed_agent_tokens.py --verify

# 4. Ajouter clés providers via UI :
#    http://127.0.0.1:8766/admin/providers
```

## 🔁 Rotation

```bash
# 1. Generate nouveau
python -c "import secrets; print(secrets.token_hex(32))"

# 2. Overwrite vault
nokido-vault set -k FORGE_TOKEN_CLAUDE

# 3. Restart hub
nssm restart LaForge-Master   # Windows

# 4. Update config client (Claude Desktop, Codex, etc.)
```

Resynchroniser tous les clients après une rotation : `tools/forge_mcp_json_sync.py`
(voir [04 — Clients MCP](04-MCP-Clients-Setup.fr.md)).

## 🚨 Restauration — coffre corrompu ou perdu

Si `data/machine_vault.dat` est corrompu ou supprimé. Depuis le durcissement du coffre du
2026-09-28 (2b), les **noms réservés** (`FORGE_MCP_TOKEN`, secrets JWT...) ne s'écrivent
que sous SYSTEM (mode dev de l'owner, `ps_clm`) : lancer le semeur là pour eux, sinon son
refus le dira.

```bash
# Effacer + reconstruire (après sauvegarde)
rm data/machine_vault.dat

# Ré-ensemencer depuis un .env de sauvegarde (si tu en as gardé un)
python tools/forge_vault_seed_agent_tokens.py --from-env-file /chemin/vers/backup.env

# Ou régénérer des jetons neufs
python tools/forge_vault_seed_agent_tokens.py --from-stdin <<EOF
FORGE_TOKEN_CLAUDE=$(python -c "import secrets; print(secrets.token_hex(32))")
FORGE_TOKEN_GEMINI=$(python -c "import secrets; print(secrets.token_hex(32))")
# ...
EOF
```

Après la reconstruction, mettre à jour chaque config client qui référence les anciens
bearers (`tools/forge_mcp_json_sync.py`, voir [04 — Clients MCP](04-MCP-Clients-Setup.fr.md)).

## 💽 Chiffrement au repos — volume `V:`

Les grosses bases (`%NOKIDO_DATA%\embeddings.db`) vivent dans un conteneur VeraCrypt monté au
démarrage par la tâche SYSTEM `LaForge-VC-Boot` (`tools/nokido_start.ps1` la déclenche
et attend `%NOKIDO_DATA%\embeddings.db`, jusqu'à 90 s, puis échoue en le disant). Le fichier-clé
est détenu par **SYSTEM seul** (coffre réservé) : pas de copie owner, aucune étape
graphique.

`tools/forge_at_rest_veracrypt.py` :

| Commande | Effet |
|---|---|
| `--status` | état du volume |
| `--verifier-cle` | prouve que la clé ouvre l'en-tête **sans VeraCrypt** (PBKDF2 + AES-XTS, magie `VERA`) : `OUVRE` / `NON` / `ILLISIBLE` — ne démonte jamais pour le savoir |
| `--rekey` | essai à blanc d'un changement de clé d'en-tête ; `--appliquer` écrit : les deux groupes d'en-têtes sauvegardés et relus, nouvelle clé rangée et relue **avant** toute écriture, en-tête relu après, restauration automatique en cas d'échec |
| `--rekey-restaurer` / `--rekey-clore` | restaurer les en-têtes sauvegardés / clore la fenêtre de changement |

Un changement de clé change la **clé d'en-tête**, pas la clé maîtresse du volume :
révoquer une clé maîtresse exposée demande un conteneur neuf et une recopie.

## 🛡️ Propriétés sécurité

- **Chiffrement au repos** : DPAPI AES-CBC. Keychain AES-256-GCM. libsecret selon agent.
- **Isolation process** : déchiffrement requiert clé LocalMachine (Win) ou unlock user-session (macOS/Linux).
- **Pas de persistance logs** : `forge_secrets` ne log jamais les *valeurs*, juste les *noms* + previews `***xxxx`.
- **Garde pre-commit** : `bash_guard` bloque `cat .env`, etc. inconditionnel.

## 🪪 Réutilisation — le vault de rédaction (DLP logs réversible)

La même primitive DPAPI (`forge_machine_vault._protect` / `_unprotect`) alimente un **second vault distinct** pour la couche DLP-logs ([Modèle de sécurité §9](07-Security-Model.fr.md)) — pas un store de secrets, un compromis de confidentialité.

Quand un sink log scrub des PII *réversiblement*, la valeur originale est stockée chiffrée DPAPI dans `sandbox/redaction_vault.db`, indexée par son tag HMAC déterministe (`[EMAIL:7f3a]`). Un débogueur local autorisé restaure le clair via `forge_semantic_firewall.deanonymize_log(text)` — mais seulement **7 jours** : `forge_log_retention` prune les entrées passé la fenêtre, après quoi les logs sont **irréversibles au repos** (le tag reste, la valeur disparaît). Fuite hors-machine = inutile (clé machine DPAPI absente). Défaut pour les logs = irréversible ; réversibilité opt-in par sink (`net_log`).

## ❓ FAQ

**Q. Sync vault cross-machines ?**
Non — DPAPI machine-scope lie les clés au hardware-derived key de *cette* machine. Pour déploiement cross-machine, utiliser adapter 1Password / Vault / Bitwarden CLI.

**Q. Containers Docker ?**
Vault per-container (volume `vault_data`). Au démarrage container, mount `Nokido.env` + run `forge_vault_seed_agent_tokens.py` une fois.

**Q. Voir contenu vault sans leak ?**
`nokido-vault list` montre *noms*. `nokido-secrets get -k KEY` montre `***xxxx` (4 derniers chars).

**Q. Hub a besoin ring 0 pour lire vault ?**
Non — vault lu in-process par `forge_secrets`. Ring check sur *dispatch tool MCP*. Accès vault gatedt par identité process OS.
