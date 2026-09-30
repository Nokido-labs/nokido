# Nokido — Plan d'isolation par user sandbox (Online/Offline)

Statut : **PLAN — à relire avant build.** Modèle calqué sur Codex CLI
(`CodexSandboxOnline` / `CodexSandboxOffline`).

---

## 1. Objectif & modèle de menace

**Trou actuel :** le hub Nokido (`tools/nokido_hub.py`, lancé par le
service NSSM `LaForge-Master`) tourne en **LocalSystem (SYSTEM)**. Donc
chaque `run` (shell/python), chaque `orchestrate`, chaque tâche d'agent =
**exécution de code arbitraire avec privilèges SYSTEM**.

Vecteurs : injection de prompt, `orchestrate` qui déraille, outil CTF mal
cadré, code généré par un LLM. N'importe lequel → compromission SYSTEM.

**Cible :** le code exécuté par `run`/`orchestrate` tourne sous un user
**standard sans admin**, avec deux variantes réseau (Online / Offline).
Le hub lui-même reste SYSTEM (il doit spawn sous d'autres tokens) — seuls
les **process enfants** d'exécution de code descendent en privilège.

Périmètre : code-exec uniquement (scope choisi). Les daemons Nokido
(trusted) restent inchangés. Pas de migration full-stack.

---

## 2. Comptes à créer

| Compte | Réseau | Groupes | Usage |
|--------|--------|---------|-------|
| `LaForgeSandboxOnline`  | oui (internet) | `Utilisateurs` + `LaForgeSandboxUsers` | tâches qui ont besoin du net (fetch, research, pip) |
| `LaForgeSandboxOffline` | **loopback only** | `Utilisateurs` + `LaForgeSandboxUsers` | défaut — tout le reste |

Contraintes communes :
- comptes **locaux**, **PAS** dans `Administrateurs`, **PAS** dans
  `docker-users`, **PAS** dans Remote Desktop Users
- mot de passe aléatoire fort (32+ car.), `Le mot de passe expire = Jamais`
- droit `SeBatchLogonRight` ("Ouvrir une session en tant que tâche") —
  requis pour `LOGON32_LOGON_BATCH`
- `SeInteractiveLogonRight` **retiré** (pas de login interactif)
- groupe `LaForgeSandboxUsers` : custom, **aucun privilège ajouté** — sert
  juste de tag ACL

---

## 3. Isolation réseau (le Offline)

Un compte Windows n'est pas privé de réseau par défaut. Mécanisme :
**Windows Firewall, règle outbound scoped par SID**.

```
# Bloque TOUT sortant pour LaForgeSandboxOffline
New-NetFirewallRule -DisplayName "LaForge-Sandbox-Offline-block-out" `
  -Direction Outbound -Action Block `
  -LocalUser "D:(A;;CC;;;<SID_Offline>)"

# Autorise le loopback (hub :8766, ollama :11434) — exception AVANT le block
New-NetFirewallRule -DisplayName "LaForge-Sandbox-Offline-allow-loopback" `
  -Direction Outbound -Action Allow -RemoteAddress 127.0.0.0/8,::1 `
  -LocalUser "D:(A;;CC;;;<SID_Offline>)"
```

Résultat : `Offline` peut joindre le hub + ollama (loopback) mais **rien
sur internet**. C'est exactement le modèle `abkit/isolation.py` du
benchmark AgentBeats — mais appliqué au **niveau OS**, pas en monkeypatch
Python. Plus solide.

`Online` : aucune règle de blocage → accès net normal.

---

## 4. ACLs (`icacls`)

Le user sandbox doit pouvoir : lire le code à exécuter, écrire ses
résultats — **rien d'autre**.

| Chemin | Droit sandbox | Raison |
|--------|---------------|--------|
| `LaForge\.run_tmp\` | **Read** | le hub y écrit le script, le sandbox le lit |
| `LaForge\sandbox\workspace\` (nouveau) | **Modify** | espace de travail dédié, seul endroit writable |
| `LaForge\` (reste) | **Read** seulement | exécuter des scripts oui, modifier le code Nokido non |
| `RAG\embeddings.db` | **Read** (ou aucun) | un runaway ne doit pas corrompre la RAG |
| `C:\Windows`, autres users | **aucun** (hérité, non accordé) | étanchéité système |

Le `TEMP`/`TMP` du process sandbox → forcé vers `sandbox\workspace\tmp`.

---

## 5. Modification du hub — `app/forge_mcp_registry.py`

Cible : `handle_run` (action `shell`/`python`) + le dispatch
`orchestrate`. Aujourd'hui : `subprocess.Popen` → hérite de SYSTEM.

Nouveau : helper `_spawn_as_sandbox(cmd, online: bool)`.

```python
# pseudo — pywin32
import win32security, win32process, win32con, win32profile

def _spawn_as_sandbox(cmdline: str, online: bool) -> tuple[str, str, int]:
    user = "LaForgeSandboxOnline" if online else "LaForgeSandboxOffline"
    pwd  = _load_sandbox_secret(user)          # cf. §6
    # SYSTEM possède SeTcbPrivilege -> LogonUser de n'importe quel compte
    token = win32security.LogonUser(
        user, ".", pwd,
        win32con.LOGON32_LOGON_BATCH,
        win32con.LOGON32_PROVIDER_DEFAULT)
    env = win32profile.CreateEnvironmentBlock(token, False)
    # CreateProcessAsUser : process enfant tourne SOUS le token sandbox
    win32process.CreateProcessAsUser(token, None, cmdline, ...)
    # capture stdout/stderr via pipes, timeout, retour
```

Points :
- le hub (SYSTEM) garde le droit de spawn — il ne *baisse* pas son propre
  privilège, il *crée* un enfant à privilège réduit
- `online` choisi par la logique §7
- timeout + capture inchangés
- dépendance : `pywin32` (déjà présent dans miniforge3 — à confirmer)

---

## 6. Stockage du secret sandbox

Mots de passe générés au setup, stockés **DPAPI scope machine**
(`win32crypt.CryptProtectData` + `CRYPTPROTECT_LOCAL_MACHINE`), fichier
`sandbox\.sandbox_creds` ACL'd **SYSTEM + Administrateurs seulement**.

Le hub (SYSTEM) déchiffre au démarrage. Aucun mot de passe en clair, ni
dans le code, ni dans `Nokido.env`, ni dans le RAG.

---

## 7. Logique Online vs Offline

**Default-deny réseau.** `run`/`orchestrate` → `Offline` par défaut.

`Online` seulement si :
- argument explicite `network=true` sur le tool `run`, OU
- le tool appelé est réseau par nature (`web_search`, `crawl`,
  `research_agent`, install de package)

Tout le reste (analyse de code, calcul, CTF local, génération) → `Offline`.

---

## 8. Ce qui reste SYSTEM / hors sandbox

- le hub, la registry, les daemons (`brain_worker`, `hebbian`, RAG…) —
  code Nokido trusted, inchangés
- contrôle NSSM, restart supervisor — **ne doivent PAS** passer par le
  `run` sandboxé ; si une tâche d'agent tente ça → échoue (correct : un
  agent n'a pas à redémarrer des services)
- **Docker** : le sandbox n'est **pas** dans `docker-users` (accès Docker
  ≈ root → tuerait l'intérêt). Les tâches Docker/Exegol gardent leur
  chemin dédié, hors sandbox `run`

---

## 9. Tests d'étanchéité (avant de déclarer OK)

| Test | Attendu |
|------|---------|
| `run` task `whoami` | affiche `LaForgeSandboxOffline`, **pas** SYSTEM |
| `run` task écrit `C:\Windows\System32\x.txt` | **AccessDenied** |
| `run` task écrit dans `sandbox\workspace\` | OK |
| `run` Offline : `urllib.urlopen('https://example.com')` | **échec réseau** |
| `run` Offline : appel hub `127.0.0.1:8766` | OK (loopback autorisé) |
| `run` Online : fetch `https://example.com` | OK |
| `run` task lit le profil de `user` ou un secret SYSTEM | **AccessDenied** |
| `run` task `net user x /add` | **échec** (pas admin) |

---

## 10. Risques & points de vigilance

- **Profil user** : `CreateProcessAsUser` sans profil chargé → forcer
  `TEMP`/`HOME` vers `sandbox\workspace\`. Sinon erreurs d'écriture.
- **`pywin32`** : confirmer présence dans l'env miniforge3.
- **`.run_tmp` lisible** : sans le droit Read, le sandbox ne peut pas
  lire le script à exécuter → vérifier l'ACL.
- **Tâches admin légitimes** : si un workflow Nokido avait besoin
  d'admin via `run`, il casse. À auditer avant — normalement aucun
  workflow agent légitime n'en a besoin.
- **Latence** : `LogonUser`+`CreateProcessAsUser` ajoute ~20-50 ms par
  exécution. Négligeable.
- **Première exécution** : le compte n'a jamais ouvert de session →
  `LOGON32_LOGON_BATCH` ok sans profil, mais tester.

---

## 11. Ordre de build

1. Script setup `tools/forge_sandbox_setup.py` : crée les 2 users +
   groupe + ACLs + règles firewall + génère/chiffre les secrets.
   (idempotent, relançable)
2. Helper `_spawn_as_sandbox()` dans un module dédié
   `app/forge_sandbox_exec.py`.
3. Câbler `handle_run` + dispatch `orchestrate` dessus.
4. Lancer les 8 tests d'étanchéité §9.
5. `anchor_solution` du design.

---

## 12. Claude CLI & Gemini CLI sur le PC

`claude.exe` (Claude Code) et Gemini CLI tournent en interactif, en tant
que `user` (admin). Leur exécution shell/python est **déjà forcée à
travers le hub `run`** par `bash_guard.py`.

Conséquence directe du plan : dès que `run` est sandboxé (§5), **Claude et
Gemini exécutent en sandbox Offline par défaut, comme tout le reste.**
C'est voulu — même un agent interactif ne doit pas taper SYSTEM/admin par
réflexe. Une injection dans le contexte de Claude ne donne plus SYSTEM.

Mais le **dev de Nokido** a parfois besoin du système : enregistrer un
service NSSM, modifier un fichier protégé, redémarrer le supervisor,
patcher du code hors `sandbox\`. D'où l'échappatoire ci-dessous.

---

## 13. Échappatoire — mode dev privilégié (sudo-semantics)

Nouveau paramètre sur `run` / `orchestrate` : `privileged: bool`
(défaut **false** → sandbox).

**Rings réels** (`forge_integrity.IntegrityRing`, plus bas = plus privilégié) :
MASTER −1, SYSTEM 0, DEV 1, TRUSTED 2, COLLAB 3, UNTRUSTED 4.
Mapping `_AGENT_RING` (`nokido_hub.py`) : `CLAUDE`=2, `CODEX`=2,
`GEMINI`=3, hooks/`SERVICES`=4.

`privileged=true` n'est honoré que si **les DEUX** conditions sont vraies :

**(a) Caller = agent interactif reconnu PAR NOM.** Whitelist explicite
`{CLAUDE, CLAUDE_CLI, CODEX, GEMINI, GEMINI_HEADLESS}` via l'entête
`X-Agent-Name`. **On ne se fie PAS au numéro de ring** — cf. §14, le
fallback ring est cassé. Tout nom hors whitelist (workers, `AGENTBEATS`,
`WORKER`, hooks, code généré) → **jamais** éligible.

**(b) Mode dev armé.** Token capability DEV valide et non-expiré.

Armement = **action humaine out-of-band**, hors de portée d'un agent :
```
LAFORGE_PYTHON tools/forge_dev_mode.py arm        # toi, dans ton shell
```
→ mint un token HMAC via `forge_integrity` (ring=DEV, **TTL 30 min**),
écrit dans `sandbox\.dev_mode_token` (ACL SYSTEM + user seulement).

Le hub, sur `run privileged=true`, vérifie le token :
- token valide + ring DEV → exécution **en tant que `user`** (admin),
  hors sandbox → accès système complet pour le dev
- pas de token / expiré / ring < DEV → `privileged` **ignoré
  silencieusement** → exécution sandbox Offline normale

Pourquoi c'est sûr :
- une **injection de prompt ne peut pas armer** — le mint exige le secret
  machine + la commande interactive. L'agent ne peut que *demander*
  `privileged=true`, jamais *ouvrir la fenêtre*.
- **TTL 30 min** → la fenêtre dev se referme seule. `forge_dev_mode.py
  disarm` pour fermer manuellement.
- chaque exécution privilégiée → **log audit** (`audit_log` existe déjà)
  + idéalement un toast Windows.

Modèle = `sudo` : tu t'authentifies une fois, fenêtre courte, tout est
tracé, et l'autonome n'y a jamais accès.

Réutilise l'existant : `forge_integrity.py` (IntegrityRing + capability
tokens HMAC) — pas de nouveau système d'auth.

---

## 14. Constat — le ring n'est PAS une base de confiance fiable

Lecture complète de `_resolve_ring` (`tools/nokido_hub.py:335-369`).
**Trois** chemins donnent ring 0 (SYSTEM) à un appelant local :

- l.342 `if not HUB_TOKEN: return (0,"local") if local`
- l.357 token dérivé-par-agent, nom non mappé + local → `0`
- **l.366 fallback token master** : tout appelant présentant `HUB_TOKEN`,
  en local → `return (0, agent_id)`

Or le **token master** est le chemin d'auth courant — `.mcp.json`,
l'agent benchmark, les workers l'utilisent tous. Donc en pratique
**tout caller local au token master = ring 0 = SYSTEM**. Le mapping
`_AGENT_RING` (CLAUDE=2, GEMINI=3…) ne s'applique QUE aux rares tokens
dérivés-par-agent (l.355-357).

Conséquence : **le numéro de ring ne distingue pas la confiance.** Le
flipper (l.366 → ring bas) a un blast radius large — daemons et
opérations hub comptent sur local-master = ring 0. **Ce n'est PAS un
fix une-ligne** ; ne pas y toucher dans le cadre du sandbox.

C'est pour ça que le design §13 est correct ET nécessaire : l'escape
hatch **ne se fie pas au ring** — uniquement (a) whitelist de NOM
d'agent + (b) token dev-mode armé. Le sandbox lui-même est OS-level,
indépendant du ring.

---

## 15. Pas d'« étape 0 fix une-ligne »

Le plan initial annonçait « corriger le fallback ring en une ligne » —
**erroné** après lecture du code (cf. §14). Le sandbox ne dépend pas du
ring ; aucun préalable à patcher dans `nokido_hub.py`.

Le durcissement de `_resolve_ring` (rendre les tokens dérivés-par-agent
obligatoires, retirer le fallback master `local→0`) est un **chantier
séparé** — à planifier, hors périmètre sandbox, car blast radius large.

Build sandbox = directement §11, étapes 1-5.

---

Rien d'autre n'est exécuté tant que ce plan n'est pas validé.
