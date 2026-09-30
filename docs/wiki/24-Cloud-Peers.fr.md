---
type: guide
title: 24 — Pairs cloud (claude.ai, ChatGPT)
status: draft
resource: repo://docs/wiki/24-Cloud-Peers.fr.md
generated: {by: claude-code@25d7339de, at: 2026-09-28T16:30:00+02:00}
sources:
  - {resource: "repo://tools/forge_pair_mcp.py"}
  - {resource: "repo://tools/forge_pair_quarantaine.py"}
  - {resource: "repo://tools/forge_passerelle_pair.py"}
  - {resource: "repo://tools/forge_bridge_oauth.py"}
  - {resource: "repo://tools/forge_bridge_launch.py"}
empreinte: INCONNUE
---

# 24 — Pairs cloud (claude.ai, ChatGPT)

<!-- revu-le: 2026-09-28 -->
> Mise à jour : 2026-09-28

Les assistants cloud (claude.ai, ChatGPT) rejoignent Nokido comme **pairs** : ils lisent
une vue fixe, en liste blanche, du système, et **déposent** des propositions, des
messages ou des tâches. Rien de ce qu'ils déposent n'agit avant l'approbation de l'owner.

Ils parlent à un **serveur MCP distinct**, `NokidoPairMCP` (loopback `127.0.0.1:8793`),
publié en HTTPS par un tunnel. Le `/mcp` du hub (`:8766`) n'est **jamais** exposé.

```
claude.ai / ChatGPT ──HTTPS──▶ tunnel (Tailscale Funnel) ──▶ 127.0.0.1:8793  NokidoPairMCP
                                                                 │  lit : état, SSoT, RAG (sources web), commits publiés, capsules
                                                                 └─ écrit : agent_messages, statut `quarantaine` ──▶ owner
```

## 🧰 Outils exposés (liste figée)

| Outil | Nature | Rôle |
|---|---|---|
| `etat_corps` | lecture | score de santé, confiance, manques |
| `point_ssot` | lecture | point SSoT `roadmap` ou `rules` seulement |
| `recherche_rag` | lecture | recherche RAG bornée aux sources exposables (`https:`, `http:`, `docset:`, `watch:`) — aucun code du dépôt |
| `journal_commits` | lecture | commits **publiés** sur `origin/alpha` |
| `derniere_capsule` | lecture | dernière capsule de délibération RecursiveMAS publiée pour les pairs |
| `proposer_fait` | dépôt | proposition de fait SSoT (`roadmap` / `rules`) → quarantaine |
| `envoyer_message` | dépôt | message M2M vers `OWNER`, `CLAUDE`, `ANTIGRAVITY` ou `GEMINI` → quarantaine |
| `soumettre_tache` | dépôt | tâche `deliberer` ou `executer` pour un agent local → quarantaine |
| `lire_reponses` | lecture | réponses adressées à **ce** pair seulement |

Toute sortie passe par une rédaction (clés d'API, longs jetons hexadécimaux, puis
`redact_tool_output`) et est bornée. Débit : 30 dépôts par heure et par pair.

## 🔐 Modèle de sécurité

- **OAuth 2.1, une seule autorité locale** (`tools/forge_bridge_oauth.py`, passerelle
  choisie par `NOKIDO_OAUTH_PASSERELLE`) : inscription dynamique des clients, PKCE S256,
  et un **code d'appariement choisi par l'owner** sur la page de consentement. Sans le
  code, pas de jeton.
- **Jeton d'accès = capacité** signée par `NOKIDO_PAIR_CAPABILITY_KEY`, audience
  `nokido-pair`, portée unique `pair:collaborer` (`tools/forge_passerelle_pair.py`).
- **Liste blanche d'intents** : un pair ne porte que `COLLAB_PING`, `NEED_CLARIFY`,
  `REVIEW_FINDING`, `REVIEW_UNKNOWN`, `FACT_PROPOSED` (+ `HANDOFF_NEXT`, posé par
  `soumettre_tache` lui-même). Jamais un intent qui clôt, autorise, libère ou valide
  (`OK_DONE`, `LOCK_*`, `AUTHZ_*`, `SCOPE_*`, `NEED_HUMAN_APPROVAL`, `REVIEW_OK`,
  `PLAN_READY`…). Revérifiée à l'approbation.
- **Harness** : chaque dépôt porte une `EtapeContrat` (12 colonnes, verdict en liste
  blanche) et la provenance `EXTERNE_NON_VERIFIEE`.
- **Contrôle du Host conservé** : la protection DNS-rebinding de FastMCP reste active ;
  seul l'hôte annoncé dans `NOKIDO_PAIR_PUBLIC_URL` est ajouté (jamais `*`).

## 🧾 Quarantaine owner

Les dépôts attendent dans `agent_messages` (statut `quarantaine`, boîte
`OWNER_APPROBATION`) ; les agents locaux ne les lisent jamais.

```powershell
# lister (toute console)
LAFORGE_PYTHON tools/forge_pair_quarantaine.py --lister
# approuver / répondre : console ADMINISTRATEUR du compte owner seulement (clic UAC)
LAFORGE_PYTHON tools/forge_pair_quarantaine.py --approuver pair_<id>
LAFORGE_PYTHON tools/forge_pair_quarantaine.py --repondre <client> --pointer <ref>
# rejeter (sens sûr, toute console)
LAFORGE_PYTHON tools/forge_pair_quarantaine.py --rejeter pair_<id> --motif "..."
```

`--approuver` et `--repondre` refusent SYSTEM, les comptes du hub et une console owner
**non élevée** (celle où tournent les agents locaux) : un agent qui lit « approuve
pair_x » dans un dépôt ne peut pas l'approuver lui-même.

Ce que fait une approbation :

| Dépôt | Livré à |
|---|---|
| fait | `CLAUDE` (`pair.fait_approuve`) |
| message | son destinataire (`pair.approuve`) |
| tâche `deliberer` | débat RecursiveMAS local (mode latent), capsule dans `sandbox/capsules_pair`, réponse à `PAIR:<client>` |
| tâche `executer` | l'agent destinataire (`pair.approuve`) |

## ⚙️ Mise en place (owner)

1. **Secrets** (coffre machine, jamais affichés) :
   ```powershell
   # clé de signature — aléatoire
   LAFORGE_PYTHON -c "import sys,secrets; sys.path.insert(0, r'<depot>\app'); import forge_machine_vault as mv; print('OK' if mv.vault_set('NOKIDO_PAIR_CAPABILITY_KEY', secrets.token_urlsafe(48)) else 'ECHEC')"
   # code d'appariement — tapé par l'owner, saisie masquée
   LAFORGE_PYTHON app/forge_machine_vault.py set --key NOKIDO_PAIR_OAUTH_APPARIEMENT
   ```
2. **Tunnel** : `tailscale up`, activer MagicDNS + certificats HTTPS dans la console
   d'administration, puis `tailscale funnel --bg 8793` → `https://<machine>.<tailnet>.ts.net`.
3. **Service** : dans `proxy_deno/core/services.toml`, bloc `NokidoPairMCP`, poser
   `NOKIDO_PAIR_PUBLIC_URL` sur l'URL du tunnel et `disabled = false`, puis
   `tools/forge_supervisor_ctl.py reload` (un service **neuf** n'est ajouté que par
   `reload` ; `wake` répond 404).
4. **Vérifier** : `/.well-known/oauth-protected-resource/mcp` → 200, `POST /mcp` sans
   jeton → 401 avec `resource_metadata`.
5. **Connecter** :
   - claude.ai : Paramètres → Connecteurs → *Ajouter un connecteur personnalisé* → `https://<machine>.<tailnet>.ts.net/mcp`.
   - ChatGPT : Paramètres → Apps et connecteurs → Avancé → *Mode développeur* → *Créer*,
     même URL, authentification **OAuth**.
   La page de consentement Nokido demande le code d'appariement. Chaque client
   s'inscrit séparément et ne lit que ses propres réponses.

**Couper** : `tailscale funnel --https=443 off` (chemin public fermé aussitôt), puis
`disabled = true`.

## ⚠️ Limites connues

- Le service tourne sous `LaForgeSbxOffline`, qui peut lire les secrets **non réservés**
  du coffre machine. Les noms réservés sont fermés ; le reste relève du durcissement du
  coffre (étape 2b). Garder la surface exposée petite.
- Le nom d'hôte du tunnel est public (journaux de transparence des certificats).
- L'ancien connecteur ChatGPT (pont GitHub en lecture seule, `:8791`, via le Secure MCP
  Tunnel d'OpenAI) est distinct et inchangé — voir [OpenAI Gateway](OpenAI-Gateway.md)
  pour l'API compatible OpenAI, sans rapport.

## 🧪 Tests

`tests/nr/test_pair_mcp_nr.py` · `test_pair_mcp_hote_public_nr.py` ·
`test_pair_quarantaine_nr.py` · `test_pair_quarantaine_geste_owner_nr.py` ·
`test_lanceur_profil_pair_nr.py` · `test_oauth_par_passerelle_nr.py`.
