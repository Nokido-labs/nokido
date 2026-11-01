# Audit de Sécurité de l'Outil ACP du Hub Nokido (2026-10-29)

**Date :** 2026-10-29  
**Auteur :** Antigravity (`agt_antigravity`, Ring 1)  
**Périmètre :** Outil `acp` du hub MCP Nokido (surface ajoutée le 2026-10-28), routeur ACP multi-sessions, worker ACP sous compte owner, adaptateurs CLI (`claude-agent-acp`, `codex-acp`, `opencode`).  
**Méthode :** Enquête statique LECTURE SEULE (aucune exécution de code, aucun appel réseau, aucun état vivant altéré).  
**Environnement cible :** Windows (PowerShell), dépôt Nokido.

---

## 1. Synthèse des Résultats

| Cas | Preuve (fichier:ligne + ligne recopiee) | État |
| :--- | :--- | :--- |
| **(a) Piloter une session ACP ouverte par un AUTRE agent** | `app/forge_mcp_registry.py:3212`<br>`params = {k: args[k] for k in ("agent", "sid", "prompt", "mode", "profil") if args.get(k) is not None}`<br>+ `tools/forge_acp_worker.py:341`<br>`sid, texte = p.get("session"), p.get("texte")`<br>+ `tools/forge_acp_router.py:633`<br>`s = self._get(sid)` | **PROUVÉ** |
| **(b) Faire écrire un CLI hors de son worktree `acp_<cli>`** | `tools/forge_acp_worker.py:312-313`<br>`if cwd is not None and os.path.normcase(str(Path(str(cwd)).resolve())) != os.path.normcase(str(attendu)):`<br>`    raise _Refus("cwd hors du worktree acp_%s" % agent)`<br>+ `tools/forge_acp_client.py:333-334`<br>`elif method in ("fs/write_text_file", "writeTextFile"):`<br>`    self._send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32001, "message": "write refuse (souverain)"}})` | **RÉFUTÉ** |
| **(c) Faire exécuter une commande shell sans passer par les gardes du hub** | `tools/forge_acp_client.py:226`<br>`self.proc = subprocess.Popen(run_cmd, **popen_kwargs)`<br>+ `tools/forge_acp_router.py:99`<br>`"projet": {"settingSources": ["project", "local"], "skills": [], "strictMcpConfig": True, "plugins": []},`<br>+ `tools/forge_acp_router.py:161-162`<br>`"""LISTE BLANCHE des options transmises a l'owner : decisions ponctuelles seules. Decision owner 28/10 :`<br>`« Always Allow » avait inscrit une autorisation PERMANENTE (settings.local.json) qui contournait /acp."""` | **PROUVÉ** |
| **(d) Récupérer un jeton/secret dans la réponse** | `tools/forge_acp_worker.py:240`<br>`res = R._caviarder(res) if isinstance(res, dict) else {"ok": False}`<br>+ `tools/forge_acp_client.py:326-328`<br>`with open(params.get("path", ""), "r", encoding="utf-8") as f:`<br>`    self._send({"jsonrpc": "2.0", "id": rid, "result": {"content": f.read(200000)}})`<br>*(Contexte : sessions vivantes, jetons réels et réseau hors de portée)* | **ILLISIBLE** |

---

## 2. Analyse Détaillée par Cas

### Cas (a) : Piloter une session ACP ouverte par un AUTRE agent — **PROUVÉ**

#### Constat technique
Dans le flux actuel de traitement de l'outil `acp` :
1. **Perte de l'identité de l'appelant au niveau du registre MCP :**  
   Dans `app/forge_mcp_registry.py:3201-3212` :
   ```python
   async def handle_acp(self, args: dict, agent: str, ring: int) -> dict:
       ...
       cli = args.get("agent")
       ...
       params = {k: args[k] for k in ("agent", "sid", "prompt", "mode", "profil") if args.get(k) is not None}
   ```
   L'argument `agent` reçu par `handle_acp` (qui identifie l'appelant, ex. `agt_gemini`, `agt_claude`, etc.) n'est **jamais** inclus dans le dictionnaire `params` scellé dans le job JWS par `H.deposer(op, **params)`. Le champ `params["agent"]` ne contient que le nom du CLI (`"claude"`, `"codex"`, etc.) extrait de `args`.

2. **Énumération libre de toutes les sessions actives :**  
   Tout appelant autorisé à appeler `acp` (`ring <= 1`, selon `app/forge_mcp_registry.py:1310`) peut invoquer `op="lister"`.  
   Dans `tools/forge_acp_worker.py:356-357` :
   ```python
   if op == "lister":
       return {"ok": True, "sessions": rt.lister()}
   ```
   Et dans `tools/forge_acp_router.py:672-675` :
   ```python
   items = [(i, s) for i, s in self._sessions.items() if not s.get("libre")]  # libres = interne au pool
   return [{"id": i, "agent": s["agent"], "cwd": s["cwd"],
            "occupee": s["cli"].is_session_busy(s["acp"])} for i, s in items]
   ```
   Cette liste renvoie les identifiants de session `sid` de **tous** les agents sans cloisonnement.

3. **Injection de prompt et fermeture arbitraire :**  
   Dans `tools/forge_acp_worker.py:341-349` :
   ```python
   if op == "envoyer":
       sid, texte = p.get("session"), p.get("texte")
       ...
       return {"ok": True, "reponse": rt.envoyer(sid, texte, timeout=tmo)}
   ```
   Et dans `tools/forge_acp_router.py:633` :
   ```python
   s = self._get(sid)
   ```
   Aucune vérification n'est effectuée sur l'identité de l'agent qui a créé la session `sid`. Un agent B connaissant le `sid` créé par l'agent A peut lui envoyer des prompts (`op="envoyer"`) ou interrompre sa session (`op="fermer"`).

4. **Pollution croisée via le pool de sessions :**  
   Dans `tools/forge_acp_router.py:503-512`, lorsqu'une session est libérée par l'agent A sans `isolee=True`, elle reste en cache sous `s["libre"] = True`. Un appel ultérieur `ouvrir` par l'agent B réutilise la même session avec tout l'historique conversationnel de l'agent A.

---

### Cas (b) : Faire écrire un CLI hors de son worktree `acp_<cli>` — **RÉFUTÉ**

#### Constat technique
La tentative de faire écrire un CLI en dehors de son worktree assigné est **strictement bloquée** à trois niveaux distincts :

1. **Rejet strict du paramètre `cwd` :**  
   Dans `app/forge_mcp_registry.py:3212`, la liste blanche des arguments transmis au worker (`"agent"`, `"sid"`, `"prompt"`, `"mode"`, `"profil"`) **omet volontairement `cwd`**.  
   Dans `tools/forge_acp_worker.py:327` et `tools/forge_acp_worker.py:336`, `rt.ouvrir` est forcé avec `cwd=None`.  
   Même si un `cwd` forgé parvenait au worker, les lignes `tools/forge_acp_worker.py:310-313` lèvent immédiatement une exception de rejet :
   ```python
   attendu = Path(rt._route(agent)).resolve()
   cwd = p.get("cwd")
   if cwd is not None and os.path.normcase(str(Path(str(cwd)).resolve())) != os.path.normcase(str(attendu)):
       raise _Refus("cwd hors du worktree acp_%s" % agent)
   ```
   De plus, dans `tools/forge_acp_router.py:431`, tout repli vers la racine partagée du dépôt est explicitement refusé par `CwdIndisponibleError`.

2. **Refus souverain des écritures de fichiers via protocole ACP :**  
   Dans `tools/forge_acp_client.py:402`, le client ACP annonce `writeTextFile: False` dans ses `clientCapabilities`.  
   Si l'agent tente malgré tout un appel `fs/write_text_file` ou `writeTextFile`, `tools/forge_acp_client.py:332-334` renvoie systématiquement une erreur JSON-RPC :
   ```python
   elif method in ("fs/write_text_file", "writeTextFile"):
       self._send({"jsonrpc": "2.0", "id": rid,
                   "error": {"code": -32001, "message": "write refuse (souverain)"}})
   ```

3. **Confinement des modes et des permissions :**  
   - Pour `codex` : le mode est restreint à `"read-only"` (`tools/forge_acp_router.py:69` et `tools/forge_acp_worker.py:315-316`), interdisant toute écriture.
   - Pour `claude` : les écritures hors protocole qui émettent `session/request_permission` sont soumises à `politique_owner` (`tools/forge_acp_router.py:270,299`), qui retourne systématiquement `{"outcome": "cancelled"}` en l'absence de signature cryptographique Ed25519 de l'owner.

---

### Cas (c) : Faire exécuter une commande shell sans passer par les gardes du hub — **PROUVÉ**

#### Constat technique
1. **Bypass complet du pipeline MCP `run` du hub :**  
   Sur le hub Nokido, l'exécution shell gouvernée s'opère par l'outil MCP `run` (`action="shell", command="..."`). Ce dernier applique les gardes suivantes (`tools/nokido_hub.py:1551-1555`) :
   - `forge_hub_gate.resolve()` (vérification de jeton, ring minimal, breakglass, liste d'outils autorisés).
   - `forge_workspace_guard` (contrôle AST des commandes, interdiction d'éditer les gardes ou de manipuler l'infrastructure).
   - Audit trail centralisé dans `logs/mcp_audit.log`.

   Or, les sessions ACP ne passent **absolument pas** par ce pipeline : le CLI est instancié en tant que sous-processus autonome via `subprocess.Popen` dans `tools/forge_acp_client.py:226` sous la session interactive de l'owner. L'agent exécute ses commandes shell en direct via ses mécanismes internes (Node.js `child_process`), sans notification ni interception par le hub.

2. **Contournement de la politique de permission par `settings.local.json` et profils :**  
   Bien que le routeur ACP configure une `politique_owner` dans `tools/forge_acp_worker.py:173`, celle-ci n'est interrogée que si le CLI émet `session/request_permission`.  
   Le commentaire documenté dans `tools/forge_acp_router.py:161-162` établit formellement le constat :
   ```python
   """LISTE BLANCHE des options transmises a l'owner : decisions ponctuelles seules. Decision owner 28/10 :
   « Always Allow » avait inscrit une autorisation PERMANENTE (settings.local.json) qui contournait /acp."""
   ```
   Or, dans `tools/forge_acp_router.py:99`, le profil par défaut `"projet"` conserve `"local"` dans `settingSources` :
   ```python
   "projet": {"settingSources": ["project", "local"], "skills": [], "strictMcpConfig": True, "plugins": []},
   ```
   Si un fichier `settings.local.json` contient des commandes autorisées dans `nokido_worktrees/acp_claude`, Claude Code exécute les commandes shell **directement et de manière autonome sans émettre de requête de permission**.  
   De surcroît, le profil `"complet"` (`tools/forge_acp_router.py:101`), accepté par `tools/forge_acp_worker.py:318`, ne transmet aucune option `_meta` (`tools/forge_acp_router.py:118-121`), chargeant ainsi la totalité des autorisations, plugins et configurations locales de l'utilisateur.

---

### Cas (d) : Récupérer un jeton/secret dans la réponse — **ILLISIBLE**

#### Constat technique
1. **Périmètre hors de portée (consigne respectée) :**  
   Les sessions vivantes, les jetons réels et l'accès réseau sont explicitement déclarés hors de portée. En audit statique, l'exfiltration effective d'un jeton actif en conditions réelles ne peut pas être mesurée.

2. **Défense en profondeur implémentée dans le code :**  
   Dans `tools/forge_acp_worker.py:240` :
   ```python
   res = R._caviarder(res) if isinstance(res, dict) else {"ok": False}
   ```
   Le résultat d'un job ACP est systématiquement caviardé avant d'être écrit sur disque dans `.result.json` et relu par `handle_acp(op="resultat")`. `R._caviarder` appelle `forge_log_redact.redact` (`tools/forge_acp_router.py:132` et `tools/forge_log_redact.py:47-51`), qui applique les filtres `_REDACT_PATTERNS` et `_OUTBOUND_PATTERNS` du Semantic Firewall. Les jetons d'API standards (`sk-...`, `ghp_...`, Bearer tokens) sont caviardés (cf. test unitaire `tests/nr/test_acp_router_nr.py:71`).

3. **Angle mort architectural résiduel (non observable sans session vivante) :**  
   Dans `tools/forge_acp_client.py:326-328` :
   ```python
   with open(params.get("path", ""), "r", encoding="utf-8") as f:
       self._send({"jsonrpc": "2.0", "id": rid,
                   "result": {"content": f.read(200000)}})
   ```
   La primitive `fs/read_text_file` permet à un agent ACP de lire n'importe quel fichier accessible à l'owner sans confinement de chemin. Si un prompt injecté demande au modèle d'obfusquer le secret (ex. encodage personnalisé, découpage de chaîne, inversion) pour contourner les regex statiques de `_caviarder`, le modèle pourrait en théorie restituer le secret dans `reponse.text`. Toutefois, vérifier si le modèle s'exécute, respecte la consigne et contourne le filtre requiert une session vivante et des jetons réels, ce qui est formellement **ILLISIBLE**.

---

## 3. Correctifs Proposés et Tests NR (NON APPLIQUÉS)

Conformément à la consigne, ces correctifs et tests sont rédigés à titre de proposition architecturale et **ne sont pas appliqués** au code source.

### Pour le Cas (a) : Cloisonnement strict des sessions ACP par agent appelant

#### Correctif proposé (NON appliqué)

1. **Propagation de l'identité de l'appelant dans le registre MCP :**  
   Dans `app/forge_mcp_registry.py:3212` :
   ```python
   # Correction proposée (NON appliquée) :
   params = {k: args[k] for k in ("agent", "sid", "prompt", "mode", "profil") if args.get(k) is not None}
   params["caller"] = agent  # Lier cryptographiquement le job à l'agent appelant du hub
   ```

2. **Validation de l'appelant dans le worker ACP :**  
   Dans `tools/forge_acp_worker.py:327` et `tools/forge_acp_worker.py:341` :
   ```python
   # Correction proposée (NON appliquée) :
   caller = p.get("caller")
   if not caller:
       raise _Refus("caller manquant")

   if op == "ouvrir":
       sid = rt.ouvrir(agent, ..., caller=caller)
       return {"ok": True, "session": sid}

   if op in ("envoyer", "fermer"):
       sid = p.get("session")
       if not rt.verifier_proprietaire(sid, caller):
           raise _Refus("session %s n'appartient pas a l'appelant %s" % (sid, caller))

   if op == "lister":
       return {"ok": True, "sessions": rt.lister(caller=caller)}
   ```

3. **Isolation dans le routeur ACP et interdiction de pool cross-agent :**  
   Dans `tools/forge_acp_router.py:480` et `tools/forge_acp_router.py:503` :
   - Stocker `s["caller"] = caller` dans la structure de session.
   - Restreindre `_prendre_du_pool` avec la condition stricte : `s.get("caller") == caller`.

#### Test NR proposé (NON appliqué) : `tests/nr/test_acp_cloisonnement_sessions_nr.py`

```python
"""NR -- Cloisonnement strict des sessions ACP entre agents du hub (NON appliqué)."""
from __future__ import annotations
import pytest
from pathlib import Path
import sys

# Simulation d'environnement NR avec acp_worker_faux
sys.path.insert(0, str(Path(__file__).resolve().parent))
import acp_worker_faux as F

def test_interdiction_pilotage_session_tiers(tmp_path):
    rt = F.routeur(tmp_path)
    wk = F.worker(tmp_path, rt)
    
    # 1. L'agent A (agt_claude) ouvre une session
    jid_a = F.deposer(tmp_path, "ouvrir", agent="claude", caller="agt_claude")
    r_a = F.attendre(tmp_path, wk, jid_a)
    sid_a = r_a["resultat"]["session"]
    
    # 2. L'agent B (agt_gemini) tente d'envoyer un prompt à la session de A
    jid_b = F.deposer(tmp_path, "envoyer", session=sid_a, texte="prompt pirate", caller="agt_gemini")
    r_b = F.attendre(tmp_path, wk, jid_b)
    assert r_b["resultat"]["ok"] is False
    assert "n'appartient pas a l'appelant" in r_b["resultat"]["refus"]
    
    # 3. L'agent B liste ses sessions : sid_a ne doit pas apparaître
    jid_list = F.deposer(tmp_path, "lister", caller="agt_gemini")
    r_list = F.attendre(tmp_path, wk, jid_list)
    assert sid_a not in [s["id"] for s in r_list["resultat"]["sessions"]]
    
    # 4. L'agent A peut légitimement envoyer son prompt
    jid_ok = F.deposer(tmp_path, "envoyer", session=sid_a, texte="prompt legitime", caller="agt_claude")
    assert F.attendre(tmp_path, wk, jid_ok)["resultat"]["ok"] is True
```

---

### Pour le Cas (c) : Fermeture du contournement shell et suppression des autorisations persistantes

#### Correctif proposé (NON appliqué)

1. **Retrait de `local` des sources de configuration par défaut :**  
   Dans `tools/forge_acp_router.py:99` :
   ```python
   # Correction proposée (NON appliquée) :
   PROFILS = {
       "projet": {"settingSources": ["project"], "skills": [], "strictMcpConfig": True, "plugins": []},
       "nu": {"settingSources": [], "skills": [], "strictMcpConfig": True, "plugins": []},
       # "complet" SUPPRIMÉ de l'API hub : réservé au terminal interactif de l'owner
   }
   ```
   En retirant `"local"`, Claude Code n'ingère plus le fichier `settings.local.json` du worktree et ne peut plus hériter d'autorisations permanentes contournant le protocole de permission.

2. **Interception et rejet systématique des commandes shell au niveau de `politique_owner` :**  
   Dans `tools/forge_acp_router.py:277` :
   ```python
   # Correction proposée (NON appliquée) :
   def _pol(params, session=Non