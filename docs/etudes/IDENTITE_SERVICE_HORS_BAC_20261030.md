# Étude de Conception : Identité de Service Hors du Bac à Sable pour les Jobs Détachés

**Date :** 30 octobre 2026  
**Auteur :** Antigravity (`agt_antigravity`, Ring 1)  
**Contexte :** Décision de l'owner du 30/10/2026 suite aux observations de confinement du coffre (`sandbox/logs/coffre_cloisonne_observations.jsonl`).  
**Cible :** `docs/etudes/IDENTITE_SERVICE_HORS_BAC_20261030.md`  

---

## 1. Contexte & Problématique

### 1.1 Constat mesuré
Dans le journal d'audit de confinement du coffre (`sandbox/logs/coffre_cloisonne_observations.jsonl`), plusieurs processus exécutés sous le compte restreint **`LaForgeSbxOnline`** (notamment `forge_banc_amelioration.py` et `forge_rss_watcher.py`, pids 23368, 13352, 28064) déclenchent l'alerte d'observation :
```json
{"cle": "FORGE_TOKEN_SERVICES", "raison": "aurait_refuse:bac_ring_le_3", "compte": "LaForgeSbxOnline", "module": "forge_hub_client.py", ...}
{"cle": "FORGE_TOKEN_SELF_PATCHER", "raison": "aurait_refuse:bac_ring_le_3", "compte": "LaForgeSbxOnline", "module": "forge_hub_client.py", ...}
{"cle": "FORGE_TOKEN_SELF_PATCHER", "raison": "aurait_refuse:bac_ring_le_3", "compte": "LaForgeSbxOnline", "module": "forge_agent_credential.py", ...}
{"cle": "FORGE_TOKEN_RSS_WATCHER", "raison": "aurait_refuse:bac_ring_le_3", "compte": "LaForgeSbxOnline", "module": "forge_agent_credential.py", ...}
```

### 1.2 Cause racine
Ces scripts sont lancés comme **jobs détachés** via `run_job` (`app/forge_job_runner.py` -> `app/forge_sandbox_exec.py:spawn_as_sandbox_detached`).
Ils exécutent des routines nécessitant des outils MCP du hub :
- `tools/forge_self_patcher.py` (appelé par `forge_banc_amelioration.py`) appelle l'outil `ask` via `_hub_call` ;
- `app/forge_autonomous_loops.py` (ligne 2745, `_gh_recuperer`) instancie `HubClient(agent="AUTONOMOUS_LOOPS")` pour invoquer `trusted_script` ;
- `app/forge_rss_watcher.py` (ligne 430, `_ingest`) appelle l'outil `rag` (action=`ingest`).

Actuellement :
1. Le jeton de job injecté au lancement (`emettre_pour_job` dans `app/forge_oauth_route.py`) est étiqueté `"JOB"` avec une politique restreinte à `scopes: ["task:status", "task:assign"]` au Ring 3.
2. Les clients (`HubClient` dans `app/forge_hub_client.py`, `jeton_pour` dans `app/forge_agent_credential.py`) ne disposant pas d'un jeton court adapté à leurs besoins d'outils, retombent immédiatement sur `_statique()` qui interroge `get_secret("FORGE_TOKEN_*")` au coffre DPAPI/WCM.
3. Dès que le cloisonnement du coffre passera du mode observation au mode bloquant (`NOKIDO_OAUTH_ENFORCE=1`), ces lectures échoueront (`PermissionError`), brisant l'exécution de tous les bancs et démons exécutés en sandbox.

### 1.3 Exigence de l'owner
Ces appels doivent être exécutés sous une **identité de service propre, hors du bac à sable** : le job du bac ne doit détenir ni lire **aucun secret d'identité statique** (`FORGE_TOKEN_*`).

---

## 2. Tableau Comparatif des Options

| Option | Briques réutilisées (fichier:ligne) | À écrire | Casse | NR |
| :--- | :--- | :--- | :--- | :--- |
| **A. Service supervisé sous compte de service qui reçoit des demandes signées (Patron Worker ACP)** | • `tools/forge_acp_hub.py:214-222` (`sceller`)<br>• `tools/forge_acp_hub.py:248-261` (`deposer`)<br>• `tools/forge_acp_hub.py:264-282` (`resultat`)<br>• `tools/forge_acp_worker.py:220-236` (`authentifier` EdDSA + nonces)<br>• `tools/forge_acp_worker.py:245-275` (`scan` multithread)<br>• `tools/forge_runas_launcher.py:215-224` (`NOKIDO_IDENTITE` supervisée) | • Nouveau démon `tools/forge_service_worker.py` (ou extension d'ACP) traitant les requêtes `ask`, `rag`, `trusted_script`.<br>• Déclaration dans `services.toml` avec `runAs` et `NOKIDO_IDENTITE`.<br>• Adaptateur synchrone dans `HubClient` / `_hub_call` qui dépose le job et attend le `.done`. | • **Casse la sémantique synchrone HTTP** : latence de scrutation (1s à 3s par appel MCP), inadapté aux cascades d'appels LLM.<br>• Ajoute un service résident supplémentaire à superviser. | `tests/nr/test_service_worker_delegation_nr.py` (vérification signature JWS Ed25519, nonces anti-rejeu, exécution sous identité hors bac, 0 secret lu au coffre par le job). |
| **B. Politique RFC 8693 dédiée par identité, portée restreinte aux outils réellement appelés, émise par le hub** | • `app/forge_oauth_route.py:36-40` (`emettre_pour_job`)<br>• `app/forge_oauth_route.py:65-72` (`lier_pid`)<br>• `app/forge_oauth_route.py:89-114` (`traiter` avec DPoP + PID)<br>• `app/forge_token_exchange.py:54-61` (`emettre_jeton_lie` avec `cnf.jkt` et `act`)<br>• `app/forge_token_exchange.py:72-117` (`echanger` RFC 8693)<br>• `app/forge_job_runner.py:65-66` & `194-196` (`launch_job` injectant `NOKIDO_JOB_SUBJECT_TOKEN`)<br>• `app/forge_agent_credential.py:224-237` (`_jeton_injecte`) | • Étendre `POLITIQUE_DEFAUT` (`forge_oauth_route.py`) avec les profils de service (`SELF_PATCHER`, `AUTONOMOUS_LOOPS`, `RSS_WATCHER`) et leurs portées exactes.<br>• Paramétrer `identite` dans `launch_job` (`forge_job_runner.py`).<br>• Échangeur RFC 8693 + DPoP automatique dans `HubClient` consommant `NOKIDO_JOB_SUBJECT_TOKEN`.<br>• Suppression des fallbacks `_statique()` vers `get_secret()`. | • Rejette en 403 `insufficient_scope` tout appel d'outil non explicitement autorisé dans la politique du service (moindre privilège strict).<br>• Nécessite la signature de preuve DPoP in-process par le job. | `tests/nr/test_run_job_echange_rfc8693_portee_restreinte_nr.py` (émission jeton de job typé, échange RFC 8693 avec DPoP, appel outil autorisé 200, outil non autorisé 403, 0 lecture `FORGE_TOKEN_*`). |
| **C. Projection de jeton court sous dossier sécurisé (`NOKIDO_JETON_FICHIER`, Patron `forge_runas_launcher.py`)** | • `tools/forge_runas_launcher.py:83-84` (`RACINE_JETONS`, `ENV_JETON_FICHIER`)<br>• `tools/forge_runas_launcher.py:138-149` (`_preparer_dossier` via `icacls`)<br>• `tools/forge_runas_launcher.py:152-157` (`_ecrire_jeton`)<br>• `tools/forge_runas_launcher.py:218-234` (`_preparer_environnement` avec assertion TPM)<br>• `tools/forge_jeton_lanceur.py:65-94` (`emettre` TPM sans secret)<br>• `app/forge_agent_credential.py:209-221` (`_jeton_projete`)<br>• `app/forge_agent_credential.py:267-306` (`_servir_injecte`) | • Câbler dans `launch_job` (`forge_job_runner.py`) la création du dossier sécurisé `RACINE_JETONS / f"{identite}-{job_id}"` avec ACL `icacls` restreinte à `LaForgeSbxOnline`, et injecter `NOKIDO_JETON_FICHIER`.<br>• Nettoyage du fichier projeté à la fin du job dans `_watch_job`.<br>• Fil de renouvellement dans le hub si le job dépasse la marge de renouvellement. | • **Isolation intra-bac faible sous Windows** : tous les jobs sandboxés partagent le même compte `LaForgeSbxOnline`, permettant la lecture croisée de jetons projetés si le chemin est devinable.<br>• Expiration possible sur jobs longs sans boucle de renouvellement active côté hub. | `tests/nr/test_run_job_jeton_projete_nr.py` (projection atomique du jeton par le hub, lecture par `_jeton_projete` dans le job, suppression garantie à la terminaison, 0 secret statique lu). |

---

## 3. Détail et Analyse des Options

### Option A : Déport via Service Supervisé et Demandes Signées (Patron ACP)

#### Principe
Le job sandboxé ne possède aucune identité de service et n'appelle pas le hub directement. À l'image de `tools/forge_acp_hub.py` et `tools/forge_acp_worker.py`, le job prépare une demande signée JWS compact EdDSA (ou appelle un endpoint hub non privilégié de dépôt) déposée dans `sandbox/service_jobs/`. Un service supervisé autonome, tournant sous un compte de service hors bac (ex: `NokidoServiceWorker` avec `NOKIDO_IDENTITE=SERVICES` ou `TASK_EXECUTOR`), dépile la file, authentifie l'empreinte de la clé publique épinglée, exécute l'opération avec ses propres privilèges et écrit la réponse.

#### Briques réutilisées (extraits exacts)
- **`tools/forge_acp_hub.py:214-222`** :
```python
def sceller(op, params, cle, now=None, job_id=None) -> str:
    """JWS compact EdDSA. cle = (privee Ed25519, kid)."""
    priv, kid = cle
    corps = {"id": job_id or secrets.token_hex(16), "op": op, "params": params,
             "ts": float(time.time() if now is None else now), "nonce": secrets.token_hex(16)}
    h = b64url_encode(json.dumps({"alg": ALG, "kid": kid}, separators=(",", ":")).encode("ascii"))
    p = b64url_encode(canonique(corps))
    s = b64url_encode(priv.sign((h + "." + p).encode("ascii")))
    return h + "." + p + "." + s
```
- **`tools/forge_acp_worker.py:220-227`** :
```python
def authentifier(self, jws, stem):
    """(ok, raison, corps). Verification EdDSA avec la cle publique EPINGLEE ; sans epingle, tout est refuse."""
    try:
        epingle = self._epingle_fn()
    except Exception:
        epingle = None
    ok, raison, corps = H.verifier(jws, epingle, self._now(), self.ttl_s)
```
- **`tools/forge_runas_launcher.py:215-224`** :
```python
identite = (environ.get("NOKIDO_IDENTITE") or "").strip().upper()
if not identite:
    return message + " ; aucune identite declaree (NOKIDO_IDENTITE)"
try:
    code, jeton, chemin = _emettre_jeton(identite)
```

#### Évaluation
- **Avantages :** Confinement physique absolu (le compte sandbox ne détient aucune capacité réseau privilégiée).
- **Inconvénients majeurs :** Dégraderait fortement les performances des boucles d'auto-amélioration (`forge_banc_amelioration`, `forge_self_patcher`) qui effectuent des dizaines d'appels `ask` séquentiels ; chaque aller-retour fichier prendrait 1 à 3 secondes de tick au lieu de ~100 ms en HTTP synchrone.

---

### Option B : Politique RFC 8693 par Identité de Job avec Portée Restreinte (Recommandée)

#### Principe
Lorsqu'un script est lancé via `run_job`, `app/forge_job_runner.py` résout son identité fonctionnelle (`SELF_PATCHER`, `AUTONOMOUS_LOOPS`, `RSS_WATCHER`) et émet un jeton de job RFC 8693 typé avec cette identité (`tx.emettre_jeton_job(job_id, identite, ttl, secret)`). Le hub enregistre immédiatement la filiation du PID (`lier_pid(job_id, pid)`).  
Dans le bac, le job ne lit aucun secret au coffre : `HubClient` / `forge_agent_credential` détecte `NOKIDO_JOB_SUBJECT_TOKEN`, génère une clé éphémère DPoP et réalise l'échange sur `POST /oauth/token`.  
Le hub valide la signature du subject_token, la concordance du PID appelant, et délivre un jeton d'accès DPoP court (TTL <= 300s) portant strictement les scopes autorisés (`tools:ask`, `tools:rag:ingest`, `tools:run:trusted_script`) et `act={"sub": "job:<job_id>"}`.

#### Briques réutilisées (extraits exacts)
- **`app/forge_oauth_route.py:36-40`** :
```python
def emettre_pour_job(job_id: str, ttl: float = TTL_JOB_MAX, identite: str = "JOB",
                     now: Optional[float] = None) -> str:
    """Jeton de JOB lie au job_id ; TTL plafonne a TTL_JOB_MAX (<= duree du job)."""
    return tx.emettre_jeton_job(job_id, identite, max(1.0, min(float(ttl), TTL_JOB_MAX)),
                                _secret(), now=now)
```
- **`app/forge_oauth_route.py:65-68`** :
```python
def lier_pid(job_id: str, pid) -> None:
    """Lie le job_id au pid reellement lance (appele par le hub apres le spawn)."""
    if job_id and pid:
        LIES[job_id] = int(pid)
```
- **`app/forge_token_exchange.py:54-61`** :
```python
def emettre_jeton_lie(sujet: str, ring: int, scopes: Iterable[str], jkt: str, ttl: float,
                      secret: bytes, now: Optional[float] = None,
                      act: Optional[Dict[str, str]] = None) -> str:
    now = time.time() if now is None else now
    charge = {"typ": "access", "sub": sujet, "ring": ring, "scope": " ".join(scopes),
              "cnf": {"jkt": jkt}, "iat": now, "exp": now + ttl,
              "jti": secrets.token_urlsafe(12)}
    if act:
        charge["act"] = act
    return _signer(charge, secret)
```
- **`app/forge_token_exchange.py:108-115`** :
```python
pol = (politique or {}).get(sub["ident"])
if pol is None or audience not in pol.get("audiences", []):
    ...
if not demandees or (pol and not set(demandees) <= set(pol["scopes"])):
    ...
jeton = emettre_jeton_lie(sub["ident"], pol["ring"], demandees,
                          forge_dpop.thumbprint(dpop_jwk), ttl, secret, now,
                          act={"sub": "job:%s" % sub["job_id"]})
```
- **`app/forge_job_runner.py:193-197`** :
```python
_env_extra = None
if jeton_factory is not None:
    try:
        _env_extra = {"NOKIDO_JOB_SUBJECT_TOKEN": jeton_factory(job_id), "NOKIDO_JOB_ID": job_id}
```

#### Évaluation
- **Avantages :** 
  - Standard RFC 8693 + RFC 9449 déjà codé et testé unitairement.
  - Preuve DPoP (`cnf.jkt`) : même si un attaquant accède à l'environnement d'un processus dans le bac, le jeton d'accès est inexploitable sans la clé privée en mémoire RAM.
  - Préservation intégrale des performances HTTP synchrones de `HubClient`.
  - Application stricte du moindre privilège via les scopes.
- **Inconvénients :** Nécessite une passe de configuration des portées par profil dans `POLITIQUE_DEFAUT`.

---

### Option C : Projection de Jeton Court sous Dossier Sécurisé (Patron K8s ServiceAccount)

#### Principe
Inspiré directement de `tools/forge_runas_launcher.py` (motif des volumes projetés Kubernetes), le hub (exécuté en SYSTEM) crée avant le spawn un dossier dédié sous `C:\ProgramData\NokidoJetons\<identite>-<job_id>`. La DACL est verrouillée par `icacls` (SYSTEM F, `LaForgeSbxOnline` R).  
Le hub y écrit un jeton court issu d'une assertion TPM signée (`tools/forge_jeton_lanceur.py`) ou émis localement, et expose la variable `NOKIDO_JETON_FICHIER`.  
Côté client dans le bac, `app/forge_agent_credential.py` dispose déjà de tout le code nécessaire pour lire `NOKIDO_JETON_FICHIER` en priorité (`_jeton_projete`). Aucun secret permanent n'est lu.

#### Briques réutilisées (extraits exacts)
- **`tools/forge_runas_launcher.py:83-84`** :
```python
RACINE_JETONS = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "NokidoJetons"
ENV_JETON_FICHIER = "NOKIDO_JETON_FICHIER"
```
- **`tools/forge_runas_launcher.py:143-149`** :
```python
Path(dossier).mkdir(parents=False, exist_ok=True)
r = subprocess.run(["icacls", str(dossier), "/inheritance:r", "/grant:r",
                    "*S-1-5-18:(OI)(CI)F", f"{compte}:(OI)(CI)R"],
                   capture_output=True, text=True, errors="replace")
return r.returncode == 0
```
- **`app/forge_agent_credential.py:209-221`** :
```python
def _jeton_projete(agent: str) -> str:
    """Le jeton du fichier projete, s'il appartient a CETTE identite ; sinon ''."""
    chemin = os.environ.get(ENV_JETON_FICHIER)
    if not chemin:
        return ""
    try:
        with open(chemin, encoding="ascii") as f:
            brut = f.read().strip()
    except OSError:
        return ""
    return brut if brut and _sujet_du_jeton(brut) == agent.upper() else ""
```
- **`app/forge_agent_credential.py:276-280`** :
```python
# Le fichier projete D'ABORD : le lanceur l'a peut-etre deja renouvele par TPM --
# aucun appel reseau, aucun echange.
projete = _jeton_projete(cle)
if projete and _reste_du_jeton(projete) > reste:
    _INJECTES[cle] = injecte = projete
```

#### Évaluation
- **Avantages :** 0 modification de code dans la couche réseau HTTP ; `_jeton_projete` est déjà opérationnel dans `forge_agent_credential.py`.
- **Inconvénients :** Sur Windows, tous les jobs sandboxés s'exécutent sous le compte local `LaForgeSbxOnline`. Une ACL basée sur le nom d'utilisateur n'empêche pas un script malveillant ou compromis dans le bac d'explorer `C:\ProgramData\NokidoJetons\` pour lire le jeton projeté d'un autre job. De plus, la rotation sur les jobs dépassant 1800s nécessite un thread superviseur hors bac.

---

## 4. Recommandation Argumentée

### Choix recommandé : **Option B (Politique RFC 8693 par identité + DPoP)**

L'**Option B** s'impose comme la solution souveraine, étanche et performante pour les raisons suivantes :

1. **Étanchéité cryptographique (Anti-vol de jeton intra-bac) :**  
   Contrairement à l'Option C (fichier sur disque accessible à tout processus du même compte Windows), 