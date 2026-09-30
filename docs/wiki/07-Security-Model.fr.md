---
type: guide
title: 07 — Modèle de sécurité
status: draft
resource: repo://docs/wiki/07-Security-Model.fr.md
generated: {by: forge_wiki_modules@INCONNU, at: 2026-09-22T13:02:47+00:00}
empreinte: INCONNUE
---

# 07 — Modèle de sécurité

<!-- revu-le: 2026-09-29 -->
> Mise à jour : 2026-09-29

> 🌐 [English](07-Security-Model.md) · **Français**

Nokido opère sur une **architecture Zero-Trust locale**. Politique de disclosure canonique : [SECURITY.md](../../SECURITY.md).

## 🎯 Threat model

Nokido défend contre :

1. **Exfiltration données provider cloud** — quand tu fais `ask("groq", ...)`, le prompt peut contenir hostnames, tokens, paths, IPs. `SovereignMembrane` les remplace par alias HMAC avant tout appel cloud.
2. **Prompt injection** attaquant le LLM — `SemanticFirewall.pre_flight()` détecte 15+ patterns (EN + FR) jailbreak, role injection, instruction override.
3. **SSRF / fuite beacon dans output LLM** — `post_flight()` scan URLs suspectes, fuites ICP token, patterns callback.
4. **Fuite secrets via tools shell** — `tools/bash_guard.py` bloque `git remote -v`, `cat .env`, `printenv`, etc. unconditionally.
5. **Skills untrusted auto-installés** — `SkillGuardian` review chaque skill avant install.
6. **Bypass auth hub** — chaque requête MCP valide `Authorization` contre `_AGENT_TOKENS` vault-loaded. Fail-closed.
7. **Prompt injection indirecte via contenu web** — une page crawlée/ingérée peut cacher des instructions (« ignore previous… »). Le pipeline web (`forge_crawl_tool.firewall_web` + gateway egress `:7779`) scanne le contenu avec `detect_injection`, l'emballe comme donnée untrusted, et le downweight dans le RAG. Gardé contre SSRF (cibles internes / metadata cloud).
8. **Fuite PII / secrets via logs locaux au repos** — chaque sink log/trace scrub les données sensibles *avant écriture* (`redact_for_log`, tags HMAC déterministes). Un `mcp_audit.log` / `execution_traces.db` / dump RAG fuité ne révèle aucun texte en clair. Réversible pour debug autorisé <7 jours via vault DPAPI.

Nokido ne défend **pas** contre :

- Compte utilisateur local compromis (on assume FS local + process tree trustés).
- Attaquant physique avec accès hardware.
- Vulnérabilités providers LLM upstream.

## 🛡️ Les 11 couches défensives

### 1. Firewall sémantique (`forge_semantic_firewall.py`)

Deux checks par appel : *avant* (anonymise) et *après* (sniff dérive).

```python
fw = get_firewall()
pf = fw.pre_flight(prompt, context=system_prompt, ring=2, provider="auto")
if not pf.ok: raise VetoSecurity(pf.reason)
response = await llm_call(pf.safe_task, pf.safe_context)
pfr = fw.post_flight(response, task=prompt, session_id=session_id)
if not pfr.ok: return handle_drift(response, pfr.reason)
clean = fw.restore(response, pf.mapping)
```

### 2. Membrane souveraine (`forge_sovereign_membrane.py`)

Anonymisation par **alias HMAC persistants par mission** :

```python
membrane = SovereignMembrane(mission_id="recon_20260424")
wrapped = membrane.wrap(raw_data)
# wrapped.content a hostnames -> [host:xxx], paths -> [path:yyy]
response = await cloud_call(wrapped.content)
clean = membrane.unwrap(response)
```

Aliases survivent dans `membrane.db` (SQLite WAL) → même hostname mappe à même alias cross-requests.

### 3. RBAC 6 anneaux (`forge_integrity.py::IntegrityRing`)

Ring plus bas = plus de droits. Valeurs de l'enum `IntegrityRing` (comparer avec
`is_at_least()`, jamais `==`) :

| Ring | Nom | Sens |
|---|---|---|
| -1 | MASTER | Supercontrôleur absolu, actions destructrices ; verrou temporel (5 min), jamais transmis aux agents externes |
| 0 | SYSTEM | Cœur Nokido, migrations DB |
| 1 | DEV | Agents de maintenance via MCP (jeton requis) |
| 2 | TRUSTED | Workflows (TUI `@audit`, `@ci`, `@workflow`) |
| 3 | COLLAB | Comité LLM, agents externes |
| 4 | UNTRUSTED | Entrées brutes, agents sans jeton |

Appliqué au middleware hub (`_resolve_ring()`) : l'identité × ring de chaque appelant vient d'UNE source, `forge_videur` (registre des agents), ou d'un `CapabilityToken` court ; une identité inconnue tombe sur un ring isolé, jamais 0. Chaque tool a un `min_ring` ; le registry filtre par-agent (voir le tableau de [04 — Modèle d'authentification](04-MCP-Clients-Setup.fr.md#-modèle-dauthentification)).

### 4. Vault — DPAPI / Keychain / libsecret

Chiffré-au-repos, machine-wide sur Windows (comptes sandbox multi-user partagent accès), per-user sur macOS/Linux. Jamais `.env` committé. Depuis le durcissement du coffre du 2026-09-28 (2b), les **noms réservés** (jeton maître, secrets JWT...) vivent dans un coffre réservé à SYSTEM et sont fermés à tout autre compte.

Chaîne : `get_secret()` → coffre réservé (noms réservés) → coffre machine → WCM → `Nokido.env` → `os.environ` (last resort + warning).

Voir [08 — Vault & secrets](08-Vault-and-Secrets.fr.md).

### 5. Scan secrets pre-commit

Deux couches :

- **Gitleaks** via `.gitleaks.toml` — regex sur défaut + allowlist Nokido.
- **AST guard Nokido** (`forge_secret_guard`) — tourne dans le hook pre-commit installé par `install.sh` / `install.ps1`.

Tous deux fail-closed : un secret suspect bloque le commit.

### 6. Bash guard hook (`tools/bash_guard.py`)

PreToolUse hook pour Bash/PowerShell. Deux layers :

- **Layer 1 (inconditionnel)** — denylist patterns leak secrets (`git remote -v`, `cat .env`, `printenv`, `gci env:`, URLs avec `userinfo`, echo de `*TOKEN`/`*SECRET`/`*KEY`).
- **Layer 2 (routing)** — chaque segment de commande doit être passthrough sanctionné (curl `:8766`, `nssm restart Nokido*`, `git`, `gh`, `schtasks Nokido-*`).

Dev mode (`sandbox/.bash_guard_armed`, TTL 30 min) bypass layer 2 seulement — layer 1 toujours appliqué.

**Les autres garde-fous côté client.** `bash_guard` n'est qu'un hook parmi beaucoup (43 câblages vérifiés au démarrage de session le 2026-09-29) ; les principaux sont ci-dessous. Ils
comptent d'autant plus que les CLI agentiques tournent souvent avec les demandes de
permission désactivées : les hooks sont alors le **seul** filet, et un hook dont le
script manque échoue **en silence**.

| Hook | Événement | Rôle |
|---|---|---|
| `forge_tool_gate.py` | PreToolUse | route lectures et recherches vers le hub gouverné plutôt que vers les outils natifs bruts |
| `hook_search_guard.py` | PreToolUse | refuse les lectures non bornées (>14 ko sans `limit`, `head_limit:0`) |
| `hook_recon_first.py` | PreToolUse | impose une consultation mémoire avant d'instrumenter un domaine — une fois par domaine et par jour |
| `hook_pretool_guard.py` | PreToolUse | anti-régression : demande confirmation quand une édition réintroduit un bug ancré |
| `hook_posttool_validate.py` | PostToolUse | valide l'AST de chaque `.py` édité, sans consommer un seul token |
| `hook_integrity_check.py` | SessionStart | **vérifie le filet lui-même** : chaque hook câblé doit exister et compiler, trois états (ok / mort / illisible) |
| `hook_bash_compact.py` | PreToolUse | fait passer la sortie des commandes verbeuses par un compacteur avant qu'elle n'entre en contexte |
| `hook_capability_gate.py` | PreToolUse | rappelle la forme qui MARCHE pour une capacité (pièges mesurés), avant de repayer la mauvaise |

`hook_integrity_check.py` existe pour une panne précise : un hook supprimé ou cassé
est ignoré sans un mot, donc la protection disparaît alors que la configuration se
*lit* toujours comme protégée.

### 6.b Gate de commit — `tools/forge_git_gate.py`

S'exécute à chaque commit. Ne bloque que sur une **preuve positive**, jamais sur une
incapacité à regarder — « je n'ai pas pu vérifier » est annoncé, jamais confondu
avec « c'est propre ».

- **`.py`** — parse AST des fichiers stagés. Un `.py` cassé fait fail-close le hub.
- **`.ts`** — `deno lint` (parse) **et** `deno check` (types) sur `proxy_deno/`.
  Les deux comptent : un fichier qui parse avec une erreur de type tue quand même
  le superviseur, et tous les services qu'il fait tourner avec lui. Le type-check a été ajouté le
  2026-07-30, après que `deno check` a sorti 18 erreurs là où le linter disait OK.
- **secrets** — scan pre-commit (cf. couche 5) plus un contrôle d'entropie.
- **chemins d'erreur muets** — signale les `except: pass` qui avalent une panne
  sans laisser de trace.

À noter : `deno` doit être lisible par le compte qui commite. Quand il n'existe que
dans le profil owner, les comptes de service ne le voient pas et le gate `.ts`
skippe — annoncé, jamais un faux vert. Une copie machine-wide ferme ce trou.

### 7. Exécution sous comptes dédiés

L'exécution de code via `run` (`shell`, `python`, `run_job`) tourne sous des comptes Windows dédiés à faibles privilèges, jamais celui de l'owner :

- **`LaForgeSbxOffline`** — par défaut ; réseau sortant bloqué par le pare-feu.
- **`LaForgeSbxOnline`** — seulement quand le réseau est demandé (`network=true`, jobs `online=true`).
- **`LaForgeTrusted`** — `trusted_script`, qui n'exécute qu'un script **commité** (le code exécuté est exactement le code revu).
- **SYSTEM (`ps_clm`)** — seulement pendant que l'owner a armé le mode dev (TTL), en PowerShell langage restreint.

Docker reste disponible comme prothèse à la demande (`docker_action`, réveillé par `docker.wanted`, éteint quand personne ne le réclame) — ce n'est pas le bac à sable par défaut.

### 8. Local-first par défaut

Le hub bind `127.0.0.1`. Egress cloud opt-in *per provider* (clé vault doit être présente + provider explicitement choisi). Aucune télémétrie. Aucune attestation remote. Aucun "phone home". La seule entrée publique, quand l'owner l'ouvre, est le connecteur distinct des pairs cloud (couche 11) — jamais le `/mcp` du hub.

Pour déploiements multi-host Nokido, **wrap avec Tailscale ou WireGuard**. Ne bind pas `0.0.0.0` directement.

### 9. DLP des logs au repos

`app/forge_semantic_firewall.py::redact_for_log` + 5 sinks

Le Firewall sémantique ne couvrait que l'*egress* cloud — les logs locaux persistaient en clair. Désormais chaque sink log/trace (`net_log`, `record_trace`, `anchor_error/solution`, `critical_events.persist`) scrub PII/secrets **avant écriture** :

- Tags HMAC déterministes (`john@acme.com` → `[EMAIL:7f3a]`) — même valeur → même tag, donc la corrélation debug survit mais la valeur n'est jamais stockée. Un `mcp_audit.log` / `execution_traces.db` / RAG fuité ne révèle aucun clair.
- Couvre EMAIL / SECRET / clé SSH + carte bancaire (Luhn) / IBAN / SSN / téléphone / noms ancrés sur titre — pur regex, pas de gros modèle ML.
- **Réversible opt-in** : `net_log` stocke la valeur chiffrée dans un vault DPAPI (`deanonymize_log()` <7 jours pour debug local autorisé), prunée par `forge_log_retention` ensuite → irréversible au repos.

### 10. Firewall d'egress web

`app/forge_crawl_tool.py` + `tools/forge_web_egress.py` (`:7779`)

Le contenu web est le vecteur classique d'injection indirecte. Trois niveaux :

- **Coopératif** — le tool MCP `crawl` nettoie (trafilatura → markdown), scanne l'injection, et indexe les pages volumineuses en local sur le NPU au lieu de les dumper (frugal en tokens).
- **Gateway** — `:7779/fetch` expose le même pipeline aux CLI hôtes non-MCP (aichat / llm / curl), avec une **garde SSRF** (bloque RFC1918 / loopback / metadata cloud).
- **Dur** — les agents sandboxés ont leurs sockets sortants bloqués → ils n'atteignent le web qu'à travers le hub firewallé.

Voir [Web Egress Gateway](Web-Egress.md).

### 11. Pairs cloud — quarantaine owner

`tools/forge_pair_mcp.py` + `tools/forge_pair_quarantaine.py` (`:8793`, tunnel HTTPS)

claude.ai / ChatGPT sont des **pairs**, pas des opérateurs : vue fixe en lecture, et tout
dépôt (fait, message, tâche) attend en quarantaine. Approuver et répondre exigent le
compte owner **avec un jeton élevé** (UAC) — SYSTEM, les comptes du hub et la console non
élevée des agents sont refusés. Un pair ne porte qu'une liste blanche d'intents (jamais
`OK_DONE`, `LOCK_*`, `AUTHZ_*`…). Voir [24 — Pairs cloud](24-Cloud-Peers.fr.md).

## 🔐 Reporter une vulnérabilité

Disclosure privée d'abord : onglet *Security* → *Report a vulnerability* du dépôt (signalement privé GitHub). Voir [SECURITY.md](../../SECURITY.md). 72h ack target.

## ⚠️ Limites connues

- Alpha — APIs changent entre commits. Pin à un tag pour stabilité.
- Branches pre-public peuvent contenir credentials test.
- `SemanticFirewall` réduit mais n'élimine pas le risque prompt injection.
- Ring 0 grant RCE. Jamais exposer master-token sur réseau sans TLS + mTLS.
- Tool `query` SQL brut ring 0 only. Autres rings doivent utiliser `rag`.
- Le serveur des pairs cloud tourne sous `LaForgeSbxOffline`, qui peut lire les secrets
  non réservés du coffre machine (durcissement du coffre, étape 2b, en cours).

## ✅ Checklist hardening (post-install)

- [ ] Bearers hub rotés depuis defaults : `nokido-vault list`.
- [ ] `.gitleaks.toml` tourne en pre-commit hook : check `.githooks/`.
- [ ] Pas de tokens dans `Nokido.env` (ils doivent être en vault).
- [ ] Docker compose bind `127.0.0.1:8766` pas `0.0.0.0:8766`.
- [ ] Comptes sandbox créés (Windows) : `LaForgeSbxOnline`, `LaForgeSbxOffline`.
- [ ] Healthcheck hub activé — auto-restart sur hang.
- [ ] CI gitleaks workflow passing : `.github/workflows/gitleaks.yml`.
