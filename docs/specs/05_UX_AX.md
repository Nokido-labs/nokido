# Spécification 05 : Expérience Réelle UX / AX de Nokido
*Reconstitution empirique stricte depuis le code source — Version 1.0 (2026-10-26)*

> **Règle méthodologique absolue** : Chaque structure de données, message textuel, code d'erreur, statut ou champ documenté ci-dessous cite explicitement sa source dans le code sous la forme `fichier:ligne`. Aucun élément n'est issu d'une maquette ou d'une intention non codée. Tout fait non localisé est désigné par la mention `NON TROUVÉ dans le code`.

---

## 1. AX — Ce que voit un agent client (Agent eXperience)

### 1.1 Refus d'admission de job

Le lancement d'un job détaché passe par le point de contrôle d'admission unifié `admettre_lancement` (app/forge_job_runner.py:69-113), qui invoque le régulateur biométrique `check_ressources` et la gestion des baux de lane de `forge_lane_admission` (app/forge_lane_admission.py:397-466).

#### 1.1.1 Refus pour saturation de la machine (RAM ou CPU)
Lorsque les ressources physiques dépassent les seuils critiques (`MAX_RAM_PCT = 85.0` [%], `MAX_CPU_PCT = 90.0` [%], `RESERVE_GB = 4.0` [Go], sources : app/forge_lane_admission.py:46-50), le retour direct d'`admettre_lancement` (app/forge_job_runner.py:98-105) produit exactement le dictionnaire suivant :

```python
{
    "ok": False,
    "admit": False,
    "lane": lane,                          # ex: "auto:mon_script.py" ou "auto:mon_script.py@online" (L89-92)
    "reason": res.get("reason"),            # Motif généré par check_ressources (voir ci-après)
    "reserve": res.get("reserve"),          # Action de libération tentée ou "rien a liberer" (app/forge_lane_admission.py:435)
    "freed_gb": res.get("freed_gb"),        # Quantité de RAM libérée en Go (float) (L436)
    "alt_cloud": res.get("alt"),            # Valeur de ALT_CLOUD ("openrouter:free", app/forge_lane_admission.py:43, 434)
    "react": (
        "machine saturee : alleger, attendre, ou router cloud :free -- JAMAIS relancer le meme "
        "travail en appel direct (run shell/python) pour passer le garde : mesurer qui tient la RAM, "
        "attendre ou liberer, puis relancer en job"
    )
}
```

Détail des motifs `reason` renvoyés par `check_ressources` (app/forge_lane_admission.py:410-449) :
- Si la mesure système échoue / est dégradée (app/forge_lane_admission.py:414-418) :
  `"MESURE INDISPONIBLE (signes vitaux illisibles) - refus par precaution, pas sur une charge observee"`
- Si la RAM est saturée après tentative d'éviction via `_try_reserve()` (app/forge_lane_admission.py:426-429) :
  `"RISQUE EMBOLIE RAM ({ram_pct}% > 85.0% ou dispo {ram_dispo_gb} Go < reserve 4.0 Go ; source {source}, age {age_s} s)"`
  *(Note : si désaccord entre observateurs live et sampler, la mention `"; ram_desaccord ..."` est adjointe par app/forge_lane_admission.py:363-365).*
- Si le CPU est saturé (app/forge_lane_admission.py:443-446) :
  `"RISQUE EMBOLIE CPU ({cpu_pct}% > 90.0%, mesure sur {fenetre_s} via {source})"`

#### 1.1.2 Refus pour voie occupée (`lane` active)
Si la machine n'est pas saturée mais qu'un bail de lane existe déjà (app/forge_job_runner.py:106-111) :

```python
{
    "ok": False,
    "admit": False,
    "lane": lane,
    "busy_by": occupe.get("holder"),       # Identifiant du job détenant le bail (ex: "job_a1b2c3d4e5f6")
    "reason": f"lane '{lane}' occupee (1 job lourd/lane)",
    "alt_cloud": "openrouter:free",
    "react": "ne pas empiler : router cloud :free / autre lane / attendre"
}
```

#### 1.1.3 Forme retournée par l'admission bas niveau `admit()`
Si un composant appelle directement `admit(lane, holder, ...)` (app/forge_lane_admission.py:452-466) :
- Échec ressources : `{"admit": False, "reason": ..., "alt": "openrouter:free", "source": ..., ...}` (sans la clé `"ok"`, ligne 456).
- Échec acquisition de lane : `{"admit": False, "busy_by": holder, "alt": "openrouter:free", "reason": "lane occupée"}` (ligne 465).
- Succès : `{"admit": True, "lane": lane, "reason": "lane acquise"}` ou `"léger admis"` (lignes 459, 462).

---

### 1.2 Messages des hooks de garde

Les hooks interviennent dans les boucles clients pour contraindre l'action. Leurs refus sont interceptés soit sur `stderr` avec un code de sortie bloquant (`exit 2`), soit sous forme de JSON structuré sur `stdout`.

#### 1.2.1 `tools/bash_guard.py` (PreToolUse Bash / PowerShell)

Le hook découpe la commande shell en segments (tools/bash_guard.py:265-305) et applique trois couches étanches :

1. **Couche 1 : Fuite de secret** (tools/bash_guard.py:110-117) — Canal : `sys.stderr`, sortie `sys.exit(2)` :
```text
[bash_guard] BLOCKED - fuite de secret.
  Raison : {why}
  Cmd : {command[:200]}
  Regle absolue : aucun passthrough ne contourne cette couche.
```
*(Où `{why}` provient de la table `SECRET_PATTERNS`, ex: `"git remote -v/show/get-url imprime les URL remote (PAT embarque)"` L71, `"lecture d'un fichier de secrets (.env / .git config / .mcp.json / cle)"` L85, etc.).*

2. **Couche 1.5 : Monitor hors politique** (tools/bash_guard.py:155-165) — Canal : `sys.stderr`, sortie `sys.exit(2)` :
```text
[bash_guard] BLOCKED - Monitor hors politique.
  Monitor execute du shell natif : une seule forme est sanctionnee,
  le CLI de surveillance git-tracke (lecture seule).
  Forme : "<LAFORGE_PYTHON>" "<repo>/tools/forge_job_watch_cli.py" --job <job_id> | --task <task_id> | --pair [client] | --delegations [--de AGENT] [--gel-s N] [--max-s N] [--intervalle N]
  Cmd : {command[:200]}
```

3. **Couche 2 : Exécution directe interdite** (tools/bash_guard.py:320-328) — Canal : `sys.stderr`, sortie `sys.exit(2)` :
```text
[bash_guard] BLOCKED - execution directe interdite.
  Cmd : {command[:300]}
  Regle : toute execution passe par le hub :8766 (mcp__laforge-sovereign-hub__run, action=shell/python).
  Passthroughs (chaque segment doit en etre un) : curl vers :8766 | git | gh | schtasks /tn Nokido-* | nssm restart nokidomcp | nssm restart laforge-master | nssm restart nokido.
```

#### 1.2.2 `tools/hook_stop_attente_passive.py` (Stop Hook)

Ce hook inspecte la fin de tour de l'agent. En cas d'infraction, il émet un objet JSON sur `stdout` (tools/hook_stop_attente_passive.py:173) avec un code de retour `0` pour forcer le harnais à relancer l'agent :

```json
{"decision": "block", "reason": "..."}
```

Le contenu de `reason` dépend de la règle enfreinte :
- **Attente passive détectée** (tools/hook_stop_attente_passive.py:62-65, 75) :
  `"Fin de tour sur une attente passive (« {motif_capture} »). Consigne owner permanente : pendant un job, une CI ou un parcours, enchainer une autre tache du backlog -- le Monitor reveillera au verdict. Ne rendre la main que pour un geste owner ou irreversible, une decision qui lui revient, ou un backlog vide, et alors lister ce qui reste."`
- **Décision owner en prose sans `AskUserQuestion`** (sous variable `NOKIDO_GARDE_DECISION_PROSE=bloquant`, tools/hook_stop_attente_passive.py:58-60, 83, 161-163) :
  `"Decision owner evoquee en prose (« {motif_capture} ») sans AskUserQuestion dans le tour. Consigne owner permanente (18/10, 19/10) : toute decision owner en attente se pose en liste a choix multiples, une question par decision, recommandee en premier."`

#### 1.2.3 `tools/hook_recon_first.py` (PreToolUse Memory/Recon Guard)

Bloque l'instrumentation ou l'écriture sauvage sans consultation de mémoire préalable (`sys.stderr`, `sys.exit(2)`) :

- **Refus A : Symptôme déjà exploré ayant échoué par le passé** (tools/hook_recon_first.py:189-201) :
```text
[recon_first] STOP — « {symptome} » a DEJA ete explore, et ca s'est mal passe.
  {date} session {session} :
    — {extrait_piege[:170]}
  Lis ces pieges AVANT de rouvrir l'enquete. Un seul rappel :
  relance ton appel. Detail complet :
    run action=shell code="tools\\forge_symptom_index.py --ask {symptome}"
```

- **Refus B : Création d'un module ou d'un script sans consultation** (tools/hook_recon_first.py:314-336) :
```text
[recon_first] STOP — creation du {module|script d'instrument} « {nom_fichier} » sans avoir rien consulte.
  `introspect question="<le probleme>"` rend en UN appel les procedures deja appliquees,
  les enquetes anterieures et leurs pieges. Et `tools/forge_retrieval_sweep.py <terme>` balaie les 8
  surfaces, dont les OUTILS par leur nom — c'est ce que chercher le seul CONTENU rate.
  Motif le plus RECIDIVANT mesure (re-consigne de mai a juillet, jamais eteint) :
  recoder une primitive qui existait deja. Les 3 etapes de RULES_SHARED :
    1. query sql="SELECT source, substr(text,1,300) FROM rag_fts WHERE rag_fts MATCH '<domaine>' LIMIT 8"
    2. lire les [[liens]] des memoires du domaine
    3. lire le module Nokido qui couvre deja le domaine
  Un seul blocage : relance apres avoir consulte (ou tout de suite si rien n'existe).
  {historique_git_si_existant}
```

- **Refus C : Domaine neuf instrumenté sans consultation mémoire** (tools/hook_recon_first.py:352-364) :
```text
[recon_first] STOP — domaine « {domaine} » instrumente sans consultation memoire.
  Nokido garde une trace de ce domaine. La chercher AVANT de mesurer :
    query   sql="SELECT source, substr(text,1,300) FROM rag_fts WHERE rag_fts MATCH '{domaine} AND (solution OR bench OR fix)' LIMIT 8"
  Mesure 24-07 : 14 mesures NPU et 4 scripts pour retrouver ce qu'une
  requete rendait — la note du 2026-05-02 disait deja quel environnement
  fonctionnait. Ce blocage ne se repete pas : relance ton appel apres avoir
  regarde (ou immediatement si la trace n'existe pas).
  {historique_git_si_existant}
```

---

### 1.3 Le retour de `governed_edit`

L'outil MCP `governed_edit` est orchestré par `handle_governed_edit` (app/forge_mcp_registry.py:3471-3645) et appliqué sur disque par `governed_write` (tools/forge_governed_edit.py:271-421).

#### 1.3.1 En cas de refus ou d'échec
Le retour est renvoyé sous la forme d'une chaîne de texte brut préfixée :
- Argument inattendu (app/forge_mcp_registry.py:3492-3495) :
  `"EDIT FAIL: argument(s) inconnu(s) {inconnus} -- refus. Modes reels : 'content' (fichier COMPLET, ecrase) ou 'blocks' (SEARCH/REPLACE chirurgical). Il n'y a pas de mode append."`
- Échappement de l'arbre projet (app/forge_mcp_registry.py:3507) :
  `"SECURITY: edit hors projet refuse: {path_str}"`
- Résolution worktree impossible pour un exécuteur (app/forge_mcp_registry.py:3528) :
  `"GOVERNED EDIT BLOCKED (worktree_introuvable): {raison}"`
- Échappement du worktree assigné (app/forge_mcp_registry.py:3534) :
  `"SECURITY: edit hors worktree refuse: {path_str}"`
- Violation de la séparation des pouvoirs (app/forge_mcp_registry.py:3544) :
  `"SECURITY: Separation of powers violation: {reason}"`
- Échec d'application de blocs SEARCH/REPLACE (app/forge_mcp_registry.py:3554) :
  `"EDIT FAIL (blocs SEARCH/REPLACE): {failed}"`
- Aucun contenu fourni (app/forge_mcp_registry.py:3559) :
  `"EDIT FAIL: fournir 'content' (complet) ou 'blocks' (SEARCH/REPLACE)"`
- Dérogation `allow_critical` demandée par un ring > 1 (app/forge_mcp_registry.py:3571) :
  `"SECURITY: allow_critical refuse pour ring {ring} (reserve au ring <= 1)"`
- Gate cognitif bloquant (app/forge_mcp_registry.py:3582) :
  `"GOVERNED EDIT BLOCKED (cognitif): {cog}"`
- Blocage issu de `governed_write` (app/forge_mcp_registry.py:3587) :
  `"GOVERNED EDIT BLOCKED ({verdict['blocked']}): {verdict['reason']}"`
  *(Où `blocked` prend les valeurs : `"arbre_partage"` L286, `"not_found"` L291, `"secret"` L295, `"syntax"` L299, `"critical"` L330/354, `"judge_module"` L368, `"io"` L380, `"unverifiable"` L390, `"lost_write"` L394).*

#### 1.3.2 En cas de succès
Lorsque l'écriture est validée (compilation AST OK, vérification de non-fuite de secret, claim de tree lock, écriture atomique sur disque et relecture confirmée), le handler retourne une chaîne JSON sérialisée (app/forge_mcp_registry.py:3645) de forme :

```json
{
  "ok": true,
  "path": "app/forge_exemple.py",
  "bytes": 2841,
  "warnings": [],
  "verified": "relecture disque identique",
  "note": "AST+secret OK ; tree_lock claim ; contenu RELU verifie ; le git-gate re-scanne au commit",
  "cible": "worktree:antigravity",
  "avertissement_tdd": "TDD : aucun test ROUGE observe sur ...",
  "avertissement_cognitif": "COGNITIF : ...",
  "avertissement_reflexe": "aucune consultation `introspect` recente (120 s) avant cette ecriture...",
  "capacites_prouvees_touchees": [
    {"nom": "capacite_x", "tests": ["tests/test_x.py"]}
  ],
  "avertissement_invariant": "cette ecriture touche le perimetre de 1 capacite(s) PROUVEE(s). Ce n'est pas un changement ordinaire : rejouer tests/test_x.py avant de committer."
}
```
*(Sources des enrichissements : `cible` L3589, `avertissement_cognitif` L3591, `avertissement_reflexe` L3612, `capacites_prouvees_touchees` L3631, `avertissement_invariant` L3632-3641).*

---

## 2. CLI et Opérateur

### 2.1 Sorties de `tools/forge_job_watch_cli.py`

Le script `tools/forge_job_watch_cli.py` est l'unique outil de surveillance en lecture seule autorisé par `bash_guard` pour l'outil `Monitor`. Ses sorties sont formatées en lignes textuelles précises selon la cible surveillée :

#### 2.1.1 Surveillance d'un Job (`--job <job_id>`, tools/forge_job_watch_cli.py:491-564)
- **Terminaison nominale ou anormale** (L521-525) :
  `"JOB {job} TERMINE rc={code} — le rc est un SIGNAL, le verdict se lit sur l'artefact (JUnit, rapport), jamais sur lui | bilan {b['etat']}{'(' + str(b['chunks']) + ')' if chunks else ''} : {b['motif']}{' [' + note + ']' if note else ''}"`
  *(Où `b['etat']` est gradué par `lire_bilan` (L370-420) parmi : `ECHEC`, `ARRET_GARDE`, `VIDE`, `DECLARE`, `TERMINE_NON_VERIFIE`, `INCONNU` ; jamais `VERIFIED`).*
- **Journal silencieux mais processus actif** (L542-545) :
  `"JOB {job} journal muet depuis {min} min MAIS son arbre travaille (CPU +{cpu} s, I/O +{io} Mo{ops}) -- pas FIGE"`
- **Détection de gel** (L552-555) :
  `"JOB {job} FIGE — journal sans ecriture depuis {min} min, aucun .rc, et son arbre {INACTIF (CPU, octets et operations d'E/S stables) | ILLISIBLE (activite non lue : verdict tire du seul journal)}"`
- **Dépassement du temps maximal (`--max-s`)** (L559-560) :
  `"JOB {job} TOUJOURS EN COURS apres {min} min — ni fin ni gel detecte"`

#### 2.1.2 Surveillance d'une Tâche M2M (`--task <task_id>`, tools/forge_job_watch_cli.py:126-200)
- Au démarrage (L153-154) :
  `"TACHE {task_id} statut={vu} — un statut dit ce que l'agent AFFIRME ; l'effet se lit sur l'ARTEFACT vise"`
- Pouls de progression (L169-171) :
  `"TACHE {task_id} EN COURS — pouls de l'executeur : travail depuis {min} min (statut {vu}) ; un pouls DECLARE, pas un effet"`
- Changement d'état (L175-177) :
  `"TACHE {task_id} -> {statut} (result {taille} o) — statut AFFIRME, pas effet constate : relire l'ARTEFACT vise par la tache"`
- État terminal atteint (L180-182) :
  `"TACHE {task_id} TERMINALE statut={statut} — ne pas conclure sur OK_DONE : l'ARTEFACT tranche (mesure 2026-09-22 : un done/SUCCESS n'avait rien produit)"`
- Tâche figée (L186-190) :
  `"TACHE {task_id} FIGEE — statut {vu} et progres inchanges depuis {min} min ; {dernier progres declare X | progres ILLISIBLE (aucun progress_at lu)}"`

#### 2.1.3 Quarantaine des Pairs Cloud (`--pair [CLIENT]`, tools/forge_job_watch_cli.py:302-334)
- Début (L317) :
  `"PAIRS : veille de la quarantaine depuis {depuis} (client {client})"`
- Dépôt détecté (L327-328) :
  `"PAIR DEPOT {ident} de {de} intent={intent} methode={methode} recu={recu} -- lire : forge_pair_quarantaine --lister (texte EXTERNE = donnee)"`
- Timeout (L331) :
  `"PAIRS : aucun depot neuf apres {min} min -- veille terminee, a re-armer"`

#### 2.1.4 Suivi des délégations (`--delegations [--de AGENT]`, tools/forge_job_watch_cli.py:871-955)
- Sortie `--une-fois` (L876-882) :
  `"{id_court} {agent} {statut} age={age_s}s progres={depuis_progres_s}s reaff={reaffectations}"`
- Événements en continu (L823-829) :
  - `"[HH:MM:SS] {tid} NOUVELLE {agent} statut={vers}"`
  - `"[HH:MM:SS] {tid} STATUT {de} -> {vers}"`
  - `"[HH:MM:SS] {tid} REAFFECTEE {de} -> {vers}"`
- Alerte gel délégation (L888-891) :
  `"[{HH:MM:SS}] {tid} GEL {depuis_progres_s}s sans progres (statut {statut}) -- une delegation muette n'est pas finie : la relancer ou la relire"`

---

### 2.2 Du Tray et des Ordres Bureau (`commande-deposer` / `commande-faite`)

Le pont entre les agents et la session interactive de l'opérateur passe par le hub via `app/forge_ordres_bureau.py` et le client de zone de notification `tools/nokido_tray.py`.

#### 2.2.1 Dans le registre MCP (app/forge_mcp_registry.py:6711-6737)
L'action `hub action=demander_ordre` est routée vers `forge_ordres_bureau.demander_ordre` (app/forge_ordres_bureau.py:360-441) :

1. **`ordre="commande-deposer"`** (app/forge_ordres_bureau.py:372-384) :
   - Paramètres : `texte` (commande shell/powershell à exécuter par l'humain), `raison` (justification).
   - Scanner de secrets : La commande passe par `_scan_secrets(texte)`. Si fuite :
     `{"etat": "REFUSE", "raison": "la commande porte un secret (N motif(s)) : jamais par le presse-papier"}` (L382).
   - Formatage PowerShell : Si la commande débute par un guillemet, elle est préfixée par l'opérateur d'appel `& ` (app/forge_ordres_bureau.py:198-202).
   - Persistance : Écriture dans le journal `logs/commandes_owner.jsonl` sous la forme :
     `{"evt": "depose", "id": "cmd-xxxxxxxxxxxx", "texte": texte, "raison": raison, "demandeur": demandeur, "depose_a": timestamp}` (app/forge_ordres_bureau.py:206-212).
   - Retour JSON :
     `{"etat": "DEPOSE", "commande": "cmd-xxxxxxxxxxxx"}` (L384).

2. **`ordre="commandes-en-attente"`** (app/forge_ordres_bureau.py:385-386) :
   - Retourne les commandes déposées qui ne possèdent pas encore d'événement `"faite"` ou `"annulee"` :
     `{"etat": "LISTE", "commandes": [...]}`.

3. **`ordre="commande-faite"`** (app/forge_ordres_bureau.py:387-388, 215-240) :
   - Paramètres : `cible` (identifiant `cmd-...`), `texte` (optionnel : extrait de retour collé par l'opérateur).
   - Contrôle d'accès : Autorisé sans extrait uniquement pour `CONSOMMATEURS = {"TRAY", "MASTER"}`. Pour les autres agents, l'extrait est obligatoire comme preuve (app/forge_ordres_bureau.py:221-223).
   - Écriture d'acquittement : Appose dans `logs/commandes_owner.jsonl` :
     `{"evt": "faite", "id": cid, "par": qui, "ts": timestamp, ...}` (L226-238).
   - Retour JSON :
     `{"etat": "FAITE", "commande": cid}` (L239).

#### 2.2.2 Côté client Tray (tools/nokido_tray.py)
- **Collecte** (tools/nokido_tray.py:439-462) : La fonction `_relever_commandes()` lit directement `commandes_en_attente()` dans le journal local ou se replie via MCP `demander_ordre` `commandes-en-attente`.
- **Menu contextuel** (tools/nokido_tray.py:532-541) :
  - Si aucune commande : `"📋 Commandes à taper : aucune"` (élément inactif).
  - Si commandes présentes : `"📋 Commandes à taper (N)"`, ouvrant un sous-menu par commande affichant `"{raison} — {demandeur}"` avec deux actions :
    1. `"Copier dans le presse-papier"` (tools/nokido_tray.py:492-510) : Vérifie qu'aucun marqueur de caviardage n'est présent (`texte_caviarde(texte)` L499), injecte directement dans le presse-papier Windows via l'API Win32 Ctypes (`CF_UNICODETEXT`, L464-490) sans lancer aucun process shell, puis affiche une notification ballon Windows.
    2. `"✓ Marquer comme faite"` (tools/nokido_tray.py:512-523) : Appelle le hub via `demander_ordre` `commande-faite` avec `cible=cid` et retire la commande de la liste.

---

## 3. Cockpit Web existant (app/web_hub et tools/nokido_web_hub.py)

Le cockpit web est servi par une application FastAPI unifiée s'exécutant par défaut sur le port TCP `7400` (`LAFORGE_HUB_PORT`).

### 3.1 Architecture du serveur et Middlewares

- **Point d'entrée** : tools/nokido_web_hub.py:213-281 initialise le logging non bloquant sur `uvicorn` et démarre `app.web_hub.app:app`.
- **Journal de vie et Veilleur de gel** :
  - `_journal_de_vie` (tools/nokido_web_hub.py:57-93) trace les démarrages et active `faulthandler` vers `logs/webhub_vie.log`.
  - `_veilleur_de_gel` (tools/nokido_web_hub.py:109-211) sonde `/health` toutes les 5 secondes ; après 2 échecs consécutifs, il dumpe la pile de tous les threads dans `logs/webhub_vie.log` sans jamais tuer le processus.
- **Middleware d'authentification (`AuthMiddleware`)** (app/web_hub/app.py:372-474) :
  - Implémenté en middleware ASGI pur (pour ne pas bloquer les connexions Streaming SSE, suite aux abandons de `BaseHTTPMiddleware`).
  - Vérifie le jeton JWT (cookie `laforge_jwt` ou header `Authorization: Bearer`).
  - Si non authentifié sur une route HTML : redirection HTTP 303 vers `/auth/login?next=...` (app/web_hub/app.py:446-448).
  - Si non authentifié sur une route API : réponse JSON `401 Unauthorized`.
  - Si authentifié : injecte l'en-tête interne `X-LaForge-User: <sub_du_token>` (app/web_hub/app.py:456-459).
  - Applique les en-têtes de sécurité de `_apply_security_headers` (app/web_hub/app.py:342-356) dont la CSP (`app/web_hub/csp.py`).
- **Middleware de caviardage (`RedactionMiddleware`)** (app/web_hub/app.py:486-489) : Masque les traces d'erreurs sensibles.

### 3.2 Catalogue exhaustif des pages HTML et de leurs sources de données

| Route HTML | Fonction dans le code | Fichier et Ligne source | Source réelle des données affichées |
|---|---|---|---|
| `GET /` | `root_redirect` | app/web_hub/app.py:1480 | Redirection HTTP 302 vers `/hub`. |
| `GET /hub` | `hub_shell` | app/web_hub/app.py:1494 | Redirection vers `/design/ui_kits/hub/index.html` (maquette statique greffée). Consomme les API `/api/hub/*`. |
| `GET /dashboard` | `dashboard` | app/web_hub/app.py:1486 | Rendu HTML fallback (`app/web_hub/dashboard_html.py`) basé sur le dictionnaire de tuiles `SERVICES` (app/web_hub/app.py:43-227). |
| `GET /vitals` | `vitals_page` | app/web_hub/app.py:1234 | Panneaux HTML générés par `app/web_hub/vitals_panels.py` ; fond dynamique alimenté par SSE `/api/vitals/sse` (`app/forge_vitals_tools.py`). |
| `GET /anatomy` | `anatomy_page` | app/web_hub/app.py:1292 | Fichier statique `app/web_hub/anatomy.html`. Consomme `/api/anatomy/state` (`app/forge_anatomy_state.py`). |
| `GET /organs` | `organs_page_route` | app/web_hub/app.py:710 | Module `app/web_hub/manifest_cards.py` (état déduit du manifeste des organes du système). |
| `GET /organs/partial` | `organs_partial_route` | app/web_hub/app.py:719 | Fragment HTMX rafraîchi de la section des organes (`manifest_cards.render_organs`). |
| `GET /dashboard/diag` | `diag_page_route` | app/web_hub/app.py:692 | Dashboard HTMX `app/web_hub/dashboard_diag_htmx.py` sondant les heartbeats des daemons en `sandbox/`. |
| `GET /dashboard/diag/partial` | `diag_partial_route` | app/web_hub/app.py:701 | Fragment HTMX pour swap de la table des heartbeats et alertes. |
| `GET /ui/playground` | `ui_playground_route` | app/web_hub/app.py:786 | Formulaire HTML interactif appelant en HTMX `POST /ui/generate`. |
| `GET /reports` (et `/reports/`) | `reports_page` | app/web_hub/app.py:1770 | Base SQLite `RAG/embeddings.db`, requête SQL : `SELECT source, substr(text,1,300), created_at FROM rag_chunks WHERE domain IN ('ctf','security','exploit','recon') ORDER BY created_at DESC LIMIT 50`. |
| `GET /auth/login` | `auth_login_form` | app/web_hub/app.py:1821 | Template pur `app/web_hub/login_html.py`, authentification sur `LAFORGE_ADMIN_TOKEN`. |
| `GET /launcher` | `launcher_page` | app/web_hub/app.py:2147 | Template `app/web_hub/launcher_html.py` consommant l'API `/api/launcher/*`. |
| `GET /forge/feed` | `event_feed_page` | app/web_hub/app.py:2162 | Fichier `app/web_hub/forge_feed.html` interrogeant en boucle AJAX `/api/events/history`. |
| `GET /docs` | `_docs_souverain` | app/web_hub/app.py:516 | Swagger UI rendu en local souverain depuis `/static/swagger-ui-bundle.js` et `/static/swagger-ui.css`. |
| `GET /redoc` | `_redoc_souverain` | app/web_hub/app.py:527 | ReDoc rendu en local souverain depuis `/static/redoc.standalone.js` (sans Google Fonts). |
| `GET /mcp_lab/` | `mcp_lab_page` | app/web_hub/mcp_lab.py:63 | Interface HTML de test des outils MCP par proxy vers `http://127.0.0.1:8766/mcp`. |
| `GET /rbac` | `rbac_page` | app/web_hub/rbac_views.py:80 | Fichier `app/web_hub/rbac_view.html` consommant l'API de `app/forge_rbac.py`. |
| `GET /providers` | `page_providers` | app/web_hub/provider_views.py:126 | Fichier `app/web_hub/providers.html` administrant les clés API des modèles via le coffre (`app/forge_secrets.py`). |
| `GET /llm-dashboard` | `llm_dashboard_page` | app/web_hub/app.py:1310 | Redirection HTTP 301 vers `/providers`. |
| `GET /roadmap/arbre` | `roadmap_arbre_page` | app/web_hub/wired_routes.py:432 | Vue vis-network injectée par `app/web_hub/roadmap_arbre.py` à partir du JSON `sandbox/workspace/roadmap_arbre_web.json` généré par `tools/forge_roadmap_keeper.py`. |
| `GET /swarm/graphe` | `swarm_graphe_page` | app/web_hub/wired_routes.py:449 | Graphe vis-network des agents et tâches issu de `sandbox/tasks.db` (`app/web_hub/swarm_graphe.py`). |
| `GET /golden/relecture` | `golden_relecture_page` | app/web_hub/wired_routes.py:475 | Page HTML de relecture du jeu de référence RAG basée sur `sandbox/golden_relecture_owner.json`. |
| `GET /rag` | `rag_page` | app/web_hub/wired_routes.py:734 | Fichier `app/web_hub/rag_dashboard.html` (statistiques et recherche RAG). |
| `GET /swarm` | `swarm_page` | app/web_hub/wired_routes.py:742 | Fichier `app/web_hub/swarm.html` (suivi live de l'essaim d'agents via SSE). |
| `GET /postal` | `postal_page` | app/web_hub/wired_routes.py:750 | Fichier `app/web_hub/postal.html` (boîte aux lettres inter-agents). |
| `GET /maison` | `maison_page` | app/web_hub/wired_routes.py:761 | Fichier `app/web_hub/edge_maison.html` (pilotage de la flotte edge domotique via `app/forge_edge_fleet.py`). |
| `GET /forge/debate` | `debate_page` | app/web_hub/wired_routes.py:862 | Fichier `app/web_hub/forge_debate.html` (interface de débat multi-agents). |

### 3.3 Endpoints API et Flux SSE Réels

#### 3.3.1 Données système et hub
- `GET /health` (app/web_hub/app.py:672) : `{"status": "ok", "version": ..., "hub_port": 7400}`.
- `GET /status` (app/web_hub/app.py:1422) : Sonde en parallèle (timeout 2.0s) tous les services déclarés dans `SERVICES` + le hub MCP sur `:8766/health`.
- `GET /api/hub/modules` (app/web_hub/app.py:1502) : Statut live de chaque service avec latence et provenance (`probe_service`).
- `GET /api/hub/provenance` (app/web_hub/app.py:1556) : 14 derniers appels réseau issus de `nokido_agent.app.forge_network_logger.net_history(40)`.
- `GET /api/hub/persona` (app/web_hub/app.py:1594) : Directives durables de l'owner lues dans `sandbox/persona_directives.json`.
- `GET /api/hub/overview` (app/web_hub/app.py:1655) : Intention lue dans `docs/roadmap_state.json` (`current_milestone`), souvenirs issus de `app/forge_self_correction.py` (`read_lessons`), et part d'appels locaux via `net_history`.
- `GET /api/hub/federation` (app/web_hub/app.py:1744) : Mappings RBAC ring x zone via `app/web_hub/rbac_views.py::_mod().list_mappings()`.

#### 3.3.2 Vitals et SSE
- `GET /api/vitals` (app/web_hub/app.py:1116) : Dictionnaire complet de `nokido_agent.app.forge_vitals_tools.all_vitals()`.
- `GET /api/vital/{name}` (app/web_hub/app.py:1102) : Signal vital unitaire via `VITAL_SIGNALS[name]()`.
- `GET /api/vitals/sse` (app/web_hub/app.py:1127) : Flux `text/event-stream` émettant toutes les 5s les tokens émotionnels (`surprise`, `arousal`, `frustration`, `tempo`, `salience`), limité par le sémaphore `_VITALS_SSE_SEM` (max 8 flux concurrents, L1159) et protégé contre les déconnexions orphelines par `request.is_disconnected()`.

#### 3.3.3 RAG, Swarm et Événements
- `GET /api/rag/stats` (app/web_hub/wired_routes.py:312) : Lecture de l'instantané de santé `sandbox/health_diagnostic.json` ou comptage direct SQLite sur `RAG/embeddings.db`.
- `POST /api/rag/search` (app/web_hub/wired_routes.py:355) : Recherche sémantique relayée au hub MCP (`_call("rag", {"action": "search", ...})`).
- `GET /api/swarm/stream` (app/web_hub/wired_routes.py:596) : Flux SSE suivant le fichier miroir `sandbox/reflexion.jsonl`.
- `GET /api/events/history` (app/web_hub/app.py:2179) : Historique de l'EventBus (`app/forge_state_manager.py`).
- `GET /api/launcher/{mod}/stream` (app/web_hub/app.py:2054) : Flux SSE du journal d'un service en temps réel (`tail_log_stream`).

---

## 4. ÉCARTS proposés

> **Avertissement de gouvernance** : Chacun des points de cette section constitue une **PROPOSITION** d'amélioration ou d'alignement architectural soumise à validation, et **NON UN FAIT** établi ou codé dans le système actuel.

### PROPOSITION 1 : Uniformisation du contrat de réponse des refus d'admission
- **Constat dans le code** : `admettre_lancement` (app/forge_job_runner.py:99-105) retourne un dict contenant `{"ok": False, "admit": False, "lane": ..., "reason": ..., "react": ...}`, alors que `admit()` direct (app/forge_lane_admission.py:456) exclut explicitement `"ok"` (`{k: v for k, v in verdict.items() if k != "ok"}`). De plus, `admettre_lancement` nomme le repli `alt_cloud`, tandis que `check_ressources` le nomme `alt`.
- **Proposition** : Harmoniser le schéma d'admission pour que tout appelant reçoive systématiquement le triplet canonique `{ok: bool, admit: bool, reason: str, alt_cloud: str, react: str}` quel que soit le canal d'entrée (MCP, HTTP `/admin/run_job` ou appel Python in-process).

### PROPOSITION 2 : Normalisation du canal de notification des Hooks de garde
- **Constat dans le code** : `tools/bash_guard.py` et `tools/hook_recon_first.py` écrivent sur `sys.stderr` et terminent le processus avec `sys.exit(2)` (tools/bash_guard.py:116, tools/hook_recon_first.py:336), tandis que `tools/hook_stop_attente_passive.py` écrit un payload JSON `{"decision": "block", "reason": ...}` sur `sys.stdout` et termine avec `exit 0` (tools/hook_stop_attente_passive.py:173-174).
- **Proposition** : Documenter formellement dans les spécifications d'accueil d'un agent que les hooks PreToolUse utilisent le canal `stderr/exit 2` du protocole hook CLI, alors que les hooks Stop utilisent la négociation JSON sur `stdout/exit 0`.

### PROPOSITION 3 : Élagage des routes d'accueil et des redirections en cascade du Cockpit Web
- **Constat dans le code** : L'accès à la racine `/` subit une double redirection HTTP (app/web_hub/app.py:1482 puis L1498) : `GET /` -> `302 /hub` -> `302 /design/ui_kits/hub/index.html`. Par ailleurs, `/llm-dashboard` redirige en 301 vers `/providers` (app/web_hub/app.py:1331).
- **Proposition** : Rendre la page d'accueil directement sur `/` ou `/hub` sans redirection intermédiaire, et mettre à jour le dictionnaire `SERVICES["llm_dashboard"]["target"]` directement vers `"/providers"` pour supprimer le saut 301.

### PROPOSITION 4 : Traçabilité des commandes Tray et retour d'exécution
- **Constat dans le code** : Lorsqu'une commande est marquée faite par le tray via `commande-faite` (tools/nokido_tray.py:514), aucun extrait de terminal n'est transmis (`cible=cid` sans paramètre `texte`). Le champ `extrait_retour` reste donc vide ou non documenté dans l'événement `logs/commandes_owner.jsonl` (app/forge_ordres_bureau.py:226-238).
- **Proposition** : Ajouter dans l'interface du Tray une boîte de dialogue optionnelle permettant à l'opérateur de coller les 2 ou 3 lignes de sortie de son terminal avant de valider `"✓ Marquer comme faite"`, afin d'ancrer la preuve d'exécution dans le journal.

### PROPOSITION 5 : Clarification AX sur la séparation Statut Déclaré vs Preuve sur Artefact
- **Constat dans le code** : `tools/forge_job_watch_cli.py` martèle systématiquement qu'un statut `done` ou un exit code `rc=0` n'est qu'un signal (tools/forge_job_watch_cli.py:144, 180, 521), et gradue l'état en `DECLARE` ou `TERMINE_NON_VERIFIE`, refusant tout statut `VERIFIED`.
- **Proposition** : Étendre cette sémantique à l'AX globale en intégrant un champ standard `verification_tier: "declared" | "artifact_proven"` dans toutes les réponses de l'API de tâches (`task action=result` et `task action=status`), évitant que des agents autonomes ne s'endorment sur une fausse certitude de succès.