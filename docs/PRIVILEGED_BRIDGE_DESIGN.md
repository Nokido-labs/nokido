# Design — Pont gouverné de commandes privilégiées (USER / ADMIN)

**Statut : DESIGN — à valider par user AVANT tout code.** (2026-06-17)
Module cible : `tools/forge_privileged_bridge.py` (+ `tools/forge_bridge_ack.py`).

---

## 1. Objectif / non-objectif

**Objectif.** Permettre au hub (et aux agents) d'exécuter des commandes
*owner* (user) et *admin* — wsl, docker, install, schtask Nokido, ACL scoped —
**sans aller-retour manuel `!`**, mais derrière une gouvernance *plus stricte qu'un
shell brut*.

**NON-objectif.** Pas un RCE-as-admin. Pas d'exécution de commande arbitraire.
Pas de contournement du sandbox. Le pont N'EST PAS un shell : c'est un routeur de
**classes de commandes allowlistées**, chacune validée + auditée.

## 2. Menace (pourquoi c'est sécu-critique)

Mesuré (mémoire) : *le hub exécute le code agent en SYSTEM → injection =
compromission totale*. Le sandbox (LaForgeSbxOffline) dé-privilégie PAR DÉFENSE.
Un pont qui re-donne du privilège **ré-ouvre exactement ce trou**.

Adversaire = **injection de prompt** dans l'agent → tente d'enqueue une commande
privilégiée malveillante. Le pont doit résister à un agent *compromis*, pas juste
à un agent *honnête*. ⇒ **default-deny, allowlist-CODE, signé, audité, confirm-irréversible.**

## 3. Anti-dup — briques existantes COMPOSÉES (ne pas réinventer)

| Besoin | Brique existante |
|---|---|
| Checkpoint humain sur commande | `forge_exegol_bridge.run_with_approval(command, action)` |
| Gate capability (scope/action) | `mcp_server_tools._require_capability(token, scope, action)` |
| Token HMAC + ring | `forge_integrity` (capability tokens) + `forge_videur` |
| Audit non-répudiable (chaîne HMAC) | `forge_videur._append_audit` |
| Filtre injection/DLP | `forge_semantic_firewall.pre_flight` |
| Redaction résultat sensible | `forge_sovereign_membrane.wrap/unwrap` |
| Queue req/resp owner (patron) | `forge_wasm_bridge` (submit + daemon) |
| Spawn SYSTEM→session owner | `forge_sandbox_exec.spawn_as_interactive_jobbed` |
| Stockage clé/token (PAS .env) | vault DPAPI + `forge_dev_mode._restrict_acl` (icacls SYSTEM+Admins) |
| Notify owner 0-API | `forge_job_notify` / inbox |

Le pont = **assemblage gouverné** de ces primitives, pas du neuf.

## 4. Architecture

```
   AGENT/HUB (LaForgeSbxOffline)          QUEUE (fichiers)              DAEMONS (privilégiés)
   ──────────────────────────            ───────────────              ─────────────────────
   request_privileged(class, args)  ─►  priv_bridge/<id>.req.json  ─►  USER daemon  (/RU user /IT)
     - signe (HMAC capability)                                          ADMIN daemon (/RU SYSTEM ou élevé)
     - file I/O SEUL, jamais d'exec                                       │
                                                                          ▼  pipeline gouvernance (§ infra)
   poll <id>.res.json            ◄──  priv_bridge/<id>.res.json   ◄──   exec + audit + (ack si sensible)
```

### Pipeline de gouvernance (dans le daemon, AVANT exec — ordre strict)
1. **Vérif signature** (HMAC capability, `forge_integrity`) — rejet si non signé / forgé. Anti-spoof façon `forge_videur`.
2. **Scope token** — un token USER ne peut PAS demander une classe ADMIN.
3. **Allowlist de classe** — `request.class` ∈ allowlist (CODE, pas config agent-éditable). Sinon → DENY.
4. **Validateur d'args par classe** — schéma/regex (ex. `wsl_exec` : distro ∈ {Debian}, binaire ∈ allowlist ; `icacls_scoped` : path sous racines autorisées, jamais system dirs).
5. **Firewall** `pre_flight` — injection/DLP sur la commande sérialisée.
6. **Classif irréversibilité** — install/ACL/delete/restart/schtask-create → ACK requis.
7. **Gate ACK** (si sensible) — écrit `pending/<id>.json` + **notify owner** ; HOLD jusqu'à ack (allow/deny) ou timeout (def 5 min → DENY).
8. **Exec** dans le contexte du daemon (user pour USER, élevé pour ADMIN).
9. **Audit** — append chaîne HMAC `{ts, requester, class, args_hash, verdict, ack_by, rc}` (tamper-evident).
10. **Résultat** — `res.json` (redaction membrane si flag sensible).

### Deux daemons séparés (isolation de privilège)
- **USER daemon** : schtask `/RU user /IT` (= celui déjà monté pour `forge_wasm_bridge`). Classes non-élevées.
- **ADMIN daemon** : schtask `/RU SYSTEM /RL HIGHEST` (ou helper élevé). Classes élevées UNIQUEMENT, ACK systématique. Token scope distinct.

## 5. Classes de commandes — allowlist initiale (CODE)

| Classe | Tier | Validation | ACK |
|---|---|---|---|
| `wsl_exec` | USER | distro∈{Debian}, binaire∈{wasmedge,…} | non |
| `wasmedge_run` | USER | = repli `forge_wasm_bridge` (fold-in) | non |
| `docker_ctl` | USER | verbe∈{start,stop,ps,images} ; pas de `run` arbitraire | start/stop=oui |
| `winget_install` | ADMIN | package-id ∈ set curé | **oui** |
| `schtask_laforge` | ADMIN | TN match `Nokido-*` | **oui** |
| `icacls_scoped` | ADMIN | path sous env Nokido uniquement | **oui** |
| `service_ctl` | ADMIN | service ∈ `Nokido-*` / NSSM | **oui** |

Ajouter une classe = **code + revue** (handler + validateur), jamais une config que l'agent peut écrire.

## 6. Canal d'ack — choix user : **notify + fichier/CLI**

- Commande sensible → daemon écrit `pending/<id>.json {class,args,requester,ts}` + `forge_job_notify` (0 API) → inbox owner.
- Owner acks par : CLI courte `forge_bridge_ack <id> allow|deny` **OU** dépôt `ack/<id>.ack` (allow/deny + signature owner).
- Daemon poll les acks ; allow → exec ; deny/timeout(5 min) → reject + audit.
- (Extension future possible : BLE buddy couche-7 — parké, pas P0.)

## 7. Invariants sécu — NON-NÉGOCIABLES

1. **Default-deny** : pas de classe matchée → reject.
2. **Allowlist = CODE revu**, jamais config agent-éditable.
3. **Tout request signé** ; clé HMAC en **vault DPAPI** (PAS `.env`), ACL SYSTEM+Admins (icacls, `forge_dev_mode._restrict_acl`).
4. **Tout acte audité** (chaîne HMAC tamper-evident).
5. **ADMIN + destructif = toujours ACK** owner.
6. **Scope token** : USER ⊄ ADMIN.
7. **Kill-switch** : fichier flag `priv_bridge/DISABLED` → pont inerte immédiat.
8. **Rate-limit** par requester.
9. **Le daemon ne fait JAMAIS confiance au req sans signature** même local.

## 8. Fichiers
- `docs/PRIVILEGED_BRIDGE_DESIGN.md` (ce doc).
- `tools/forge_privileged_bridge.py` : `request_privileged()` (client) + `user_daemon()` + `admin_daemon()` + pipeline + handlers de classe.
- `tools/forge_bridge_ack.py` : CLI ack owner.
- `tests/test_forge_privileged_bridge.py` : default-deny, allowlist, sig invalide, ack-gate, audit-chain, scope-token, kill-switch.

## 9. Phasage
- **P0** — USER tier (wsl_exec, wasmedge_run fold-in, docker_ctl read) : signé + firewall + audit, sans ACK (non-destructif). Réutilise le daemon user déjà monté.
- **P1** — ADMIN tier (winget_install, schtask_nokido, icacls_scoped, service_ctl) + gate ACK + daemon élevé.
- **P2** — kill-switch, rate-limit, redaction membrane, option BLE.

## 10. Tests (TDD, RED d'abord)
default-deny · classe inconnue rejetée · arg hors-schéma rejeté · signature
invalide rejetée · ack timeout → deny · scope USER demande ADMIN → deny ·
audit chain vérifiable · kill-switch coupe tout.

## 11. À valider par user avant code
- [ ] Allowlist initiale de classes (§5) — OK / à amender ?
- [ ] Phasage P0 USER-only d'abord — OK ?
- [ ] Timeout ACK 5 min — OK ?
- [ ] Daemon ADMIN = `/RU SYSTEM` vs helper UAC ponctuel — préférence ?
