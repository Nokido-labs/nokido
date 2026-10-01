"""forge_ci_check.py — etat de la CI apres push.

API ajoutee depuis le 2026-09-22 (premiere ligne de la docstring de chaque symbole) :
- `couverture_des_rouges` — Etat du dernier run GitHub termine de `branch` face au sha qu'on va certifier.
- `tests_rouges` — (fichier, test) des lignes `FAILED` de pytest, dans l'ordre, sans doublon.
"""

from __future__ import annotations

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "proprioception/ci-externe"

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPO = "Nokido-labs/nokido-private"   # atelier source (renomme le 2026-09-30)
API = "https://api.github.com"

# Console Windows = cp1252 : sans ca, tiret cadratin et accents sortent en mojibake
# (mesure 2026-07-28 sur la sortie reelle). Meme garde qu'en tete de ci_local.py.
# JAMAIS sous pytest : reconfigurer le flux de CAPTURE le referme pour les tests
# suivants du meme worker xdist (mesure 2026-09-04).
if "pytest" not in sys.modules:
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

# Un run sans etape qui stagne au-dela de ce seuil n'attend plus un slot :
# il attend un runner qui ne viendra pas.
STUCK_QUEUED_S = 300


def _creds() -> str | None:
    """Le jeton vient du coffre, jamais de l'environnement."""
    for p in (ROOT / "app", ROOT):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    try:
        from nokido_agent.app.forge_secrets import get_secret

        return get_secret("GITHUB_TOKEN")
    except Exception:
        return None


def _api(path: str, cred: str) -> dict:
    req = urllib.request.Request(
        API + path,
        headers={
            "Authorization": "Bearer %s" % cred,
            "Accept": "application/vnd.github+json",
            "User-Agent": "nokido-ci-check",
        },
    )
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8"))


class _RedirectionSansJeton(urllib.request.HTTPRedirectHandler):
    """Retire `Authorization` en suivant une redirection vers un autre hote.

    MESURE 2026-08-20. L'API des journaux repond 302 vers un stockage d'objets
    qui porte DEJA sa signature dans l'URL. Lui renvoyer notre en-tete Bearer
    le fait repondre « 401 : Server failed to authenticate the request ». Le
    jeton n'etait pas invalide -- il etait de trop. Et le presenter a un tiers
    est en soi une fuite : on ne transporte pas un secret hors de son domaine.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        nouvelle = super().redirect_request(req, fp, code, msg, headers, newurl)
        if nouvelle is not None:
            for entete in ("Authorization", "authorization"):
                nouvelle.headers.pop(entete, None)
                nouvelle.unredirected_hdrs.pop(entete, None)
        return nouvelle


def _api_texte(path: str, cred: str) -> str:
    """Journal brut d'un job. L'API redirige vers un blob ; on suit SANS jeton."""
    req = urllib.request.Request(
        API + path,
        headers={
            "Authorization": "Bearer %s" % cred,
            "Accept": "application/vnd.github+json",
            "User-Agent": "nokido-ci-check",
        },
    )
    ouvreur = urllib.request.build_opener(_RedirectionSansJeton)
    with ouvreur.open(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def lignes_utiles(journal: str, garde: int = 40) -> list[str]:
    """Ne garde du journal que ce qui EXPLIQUE l'echec.

    POURQUOI (mesure 2026-08-20). Trois fois dans la journee, un echec CI est
    reste non instruit faute de journal : `detail_run` dit QUELLE etape a rougi,
    jamais POURQUOI. Rapatrier des megaoctets serait pire -- on ne lit pas un
    flot. On extrait donc les lignes que pytest et les gardes emettent quand ils
    refusent : `FAILED`, `ERROR`, `assert`, le resume final. Un diagnostic qui
    coute plus cher que le geste qu'il eclaire n'est pas un diagnostic.
    """
    # `❌` = la croix du RESUME de ci_local. Mesure 2026-09-04 : sans elle,
    # le journal rapatrie disait « 1 gate(s) bloquant(s) en echec » sans jamais
    # nommer LEQUEL — les lignes du resume ne portent aucun des motifs d'erreur
    # et ne sont pas en queue de journal. Un extracteur qui rend le symptome
    # mais pas son sujet ne permet pas de boucler le diagnostic, et c'est
    # exactement ce pour quoi il a ete ecrit.
    motifs = ("FAILED ", "ERROR ", "E   ", "AssertionError", "Error:",
              "Traceback", "gate(s) bloquant", "NE PAS pousser",
              " failed", " error", "ModuleNotFoundError", "ImportError",
              "PermissionError", "FileNotFoundError", "❌")
    out: list[str] = []
    for ligne in journal.splitlines():
        nu = ligne.strip()
        # Les journaux GHA prefixent chaque ligne d'un horodatage ISO.
        if len(nu) > 28 and nu[4] == "-" and nu[10] == "T":
            nu = nu[nu.find(" ") + 1:] if " " in nu[:32] else nu
        if any(m in nu for m in motifs):
            out.append(nu[:400])
    # Les dernieres lignes portent le verdict : on les garde meme sans motif.
    queue = [x.strip()[:400] for x in journal.splitlines()[-12:] if x.strip()]
    for q in queue:
        if q not in out:
            out.append(q)
    return out[-garde:]


def journal_echecs(repo: str, run_id: str, garde: int = 40) -> dict:
    """Lignes utiles des jobs en ECHEC d'un run."""
    cred = _creds()
    if not cred:
        return {"ok": False, "error": "GITHUB_TOKEN introuvable (coffre DPAPI)"}
    try:
        raw = _api("/repos/%s/actions/runs/%s/jobs" % (repo, run_id), cred)
    except Exception as exc:  # noqa: BLE001 - capteur muet : il doit le DIRE
        return {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
    out = {"ok": True, "run": run_id, "jobs": []}
    for j in raw.get("jobs", []):
        if j.get("conclusion") in (None, "success", "skipped"):
            continue
        fiche = {"job": j.get("name"), "conclusion": j.get("conclusion")}
        try:
            txt = _api_texte("/repos/%s/actions/jobs/%s/logs" % (repo, j.get("id")), cred)
            fiche["lignes"] = lignes_utiles(txt, garde)
        except Exception as exc:  # noqa: BLE001
            fiche["lignes"] = []
            fiche["journal_indisponible"] = "%s: %s" % (type(exc).__name__, exc)
        out["jobs"].append(fiche)
    return out


# ROUGES A COUVRIR (decision owner 2026-09-26). GitHub ne juge un sha qu'une fois
# PUBLIE (ci-selfhosted.yml : push vers alpha seulement). Avant la CI complete
# locale, on relit donc le dernier run GitHub TERMINE de la branche : chaque test
# qu'il a vu rouge doit avoir son correctif dans le sha qu'on va certifier. Mesure
# du jour : `test_tpm_acl_gouvernee_nr` passait en local et rougissait sur GitHub
# (verdict dependant du compte) -- la CI locale ne pouvait pas le voir, seul le
# run GitHub le nommait. Observation seule, jamais bloquante (un gate neuf mesure
# son bruit avant d'enforcer). « Touche » n'est pas « corrige » : un commit qui
# modifie le fichier du test est un CANDIDAT ; un correctif qui vit dans le code
# teste n'est pas vu par cette sonde, d'ou A_VERIFIER et jamais NON.
_FAILED = re.compile(r"FAILED (tests/[^\s:]+\.py)::(\S+)")
ROUGES_VERT, ROUGES_COUVERT = "VERT", "COUVERT"
ROUGES_A_VERIFIER, ROUGES_ILLISIBLE = "A_VERIFIER", "ILLISIBLE"


def tests_rouges(lignes: list) -> list:
    """(fichier, test) des lignes `FAILED` de pytest, dans l'ordre, sans doublon."""
    vus: list = []
    for ligne in lignes:
        for paire in _FAILED.findall(ligne):
            if paire not in vus:
                vus.append(paire)
    return vus


def couverture_des_rouges(repo: str, branch: str, sha_certifie: str, commits_touchant) -> dict:
    """Etat du dernier run GitHub termine de `branch` face au sha qu'on va certifier.

    `commits_touchant(base, sha, fichier) -> [str]` : commits de `base..sha` qui
    touchent `fichier` (injecte : le depot vise est celui de l'appelant).
    Etats : VERT · COUVERT · A_VERIFIER · ILLISIBLE -- et seul VERT dit que GitHub
    est vert ; COUVERT dit seulement que chaque rouge a un correctif CANDIDAT.
    """
    etat = check(repo, branch, limit=10)
    if not etat.get("ok"):
        return {"etat": ROUGES_ILLISIBLE, "raison": etat.get("error") or etat.get("runs_error")}
    termines = [r for r in etat.get("runs", []) if r.get("status") == "completed"]
    if not termines:
        return {"etat": ROUGES_ILLISIBLE,
                "raison": "aucun run termine sur %s (vus toutes branches : %s)"
                          % (branch, etat.get("vus_toutes_branches"))}
    run = termines[0]
    run_id = (run.get("url") or "").rstrip("/").rsplit("/", 1)[-1]
    out = {"run": run_id, "head": run.get("head"), "conclusion": run.get("conclusion"),
           "en_cours_plus_recents": sum(1 for r in etat["runs"] if r.get("status") != "completed"
                                         and (r.get("created") or "") > (run.get("created") or ""))}
    if run.get("conclusion") == "success":
        return dict(out, etat=ROUGES_VERT)
    journal = journal_echecs(repo, run_id, garde=400)
    if not journal.get("ok"):
        return dict(out, etat=ROUGES_ILLISIBLE, raison=journal.get("error"))
    rouges, jobs_sans_test = [], []
    for job in journal.get("jobs", []):
        paires = tests_rouges(job.get("lignes") or [])
        if not paires:
            jobs_sans_test.append({"job": job.get("job"), "conclusion": job.get("conclusion"),
                                   "journal_indisponible": job.get("journal_indisponible")})
        for fichier, test in paires:
            rouges.append({"fichier": fichier, "test": test,
                           "commits": commits_touchant(run.get("head"), sha_certifie, fichier)})
    complet = rouges and not jobs_sans_test and all(r["commits"] for r in rouges)
    return dict(out, etat=ROUGES_COUVERT if complet else ROUGES_A_VERIFIER,
                rouges=rouges, jobs_sans_test=jobs_sans_test)


# VERDICTS PAR COMMIT -- cinq valeurs, et une seule vaut « vert » (P0, revue du
# 2026-08-20). Le piege n'est pas de lire FAIL pour PASS : c'est de lire
# « aucun run » ou « un run d'un autre commit » comme une absence de probleme.
# Un commit non teste n'est pas un commit sain, c'est un commit NON MESURE.
CI_PASS, CI_FAIL, CI_RUNNING = "PASS", "FAIL", "RUNNING"
CI_NOT_FOUND, CI_STALE = "NOT_FOUND", "STALE"
CI_VERDICTS_NON_VERTS = (CI_FAIL, CI_RUNNING, CI_NOT_FOUND, CI_STALE)


def verdict_commit(repo: str, sha: str, branch: str = "alpha",
                   fenetre: int = 40) -> dict:
    """Verdict CI d'UN commit precis. Seul `PASS` autorise a conclure.

    NOT_FOUND : aucun run ne porte ce sha. Ce n'est PAS un succes -- c'est le
                faux-vert temporel le plus facile a commettre, parce qu'il
                ressemble a « rien a signaler ».
    STALE     : des runs existent sur la branche, mais aucun pour ce sha ET le
                dernier run porte un commit DIFFERENT. Le verdict qu'on lit
                concerne alors du code qui n'est pas celui qu'on evalue.
    """
    cred = _creds()
    if not cred:
        return {"ok": False, "verdict": CI_NOT_FOUND,
                "motif": "GITHUB_TOKEN introuvable (coffre DPAPI)"}
    try:
        raw = _api("/repos/%s/actions/runs?per_page=%d" % (repo, fenetre), cred)
    except Exception as exc:  # noqa: BLE001 - un capteur muet doit le DIRE
        return {"ok": False, "verdict": CI_NOT_FOUND,
                "motif": "%s: %s" % (type(exc).__name__, exc)}
    runs = raw.get("workflow_runs", [])
    court = (sha or "")[:8]
    miens = [w for w in runs if (w.get("head_sha") or "").startswith(court)]
    if not miens:
        sur_branche = [w for w in runs if w.get("head_branch") == branch]
        if sur_branche:
            dernier = max(sur_branche, key=lambda w: w.get("created_at") or "")
            return {"ok": True, "verdict": CI_STALE, "sha": court,
                    "motif": "aucun run pour %s ; le dernier run de %s porte %s"
                             % (court, branch, (dernier.get("head_sha") or "")[:8]),
                    "vu": len(runs)}
        return {"ok": True, "verdict": CI_NOT_FOUND, "sha": court,
                "motif": "aucun run ne porte ce commit (fenetre de %d runs)" % fenetre,
                "vu": len(runs)}
    dernier = max(miens, key=lambda w: w.get("created_at") or "")
    if dernier.get("status") != "completed":
        return {"ok": True, "verdict": CI_RUNNING, "sha": court,
                "motif": "run %s en cours" % dernier.get("id"),
                "run_id": dernier.get("id")}
    conclusion = dernier.get("conclusion")
    if conclusion == "success":
        return {"ok": True, "verdict": CI_PASS, "sha": court,
                "run_id": dernier.get("id"), "motif": ""}
    # ANNULE N'EST PAS ECHOUE (mesure 2026-08-20). Un run supplante par un push
    # plus recent rend `cancelled` : les tests n'ont pas rougi, ils n'ont pas
    # fini. Le classer FAIL accuserait un commit a tort ; le classer PASS serait
    # pire. C'est un NON MESURE, et c'est tout ce qu'on peut en dire. Meme
    # raisonnement pour `skipped`, `neutral` et `stale`.
    if conclusion in ("cancelled", "skipped", "neutral", "stale", None):
        return {"ok": True, "verdict": CI_NOT_FOUND, "sha": court,
                "run_id": dernier.get("id"),
                "motif": "run %s : conclusion=%s -- ni rouge ni vert, NON MESURE"
                         % (dernier.get("id"), conclusion)}
    return {"ok": True, "verdict": CI_FAIL, "sha": court,
            "run_id": dernier.get("id"), "motif": "conclusion=%s" % conclusion}


def _age_s(iso: str | None) -> float | None:
    """Age d'un horodatage GitHub (toujours UTC, suffixe Z).

    MESURE 2026-09-02 : l'ancien calcul faisait `mktime(t) - time.timezone`.
    `mktime` interprete en heure LOCALE, et `time.timezone` est l'offset HORS heure
    d'ete -- en CEST l'age sortait donc faux d'exactement 3600 s. Un run cree a
    l'instant s'affichait « queued depuis 3605s — runner present, rien ne demarre »,
    c'est-a-dire une PANNE INVENTEE qui envoie relancer un runner qui va tres bien.
    Un garde qui crie a faux se fait desarmer : on compare desormais deux instants
    conscients de leur fuseau, ce qui est juste en toute saison.
    """
    if not iso:
        return None
    try:
        from datetime import datetime, timezone as _tz
        brut = iso.replace("Z", "").split(".")[0]
        instant = datetime.strptime(brut, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=_tz.utc)
        return time.time() - instant.timestamp()
    except Exception:
        return None


def _verdict(out: dict) -> str:
    """Traduit runs + runners en UNE phrase actionnable."""
    runs = out.get("runs") or []
    if not runs:
        return "aucun run sur cette branche"
    rr = out.get("runners")
    # `None` = illisible, et « je ne peux pas voir » n'est PAS « il n'y en a pas ».
    actifs = None if rr is None else [r for r in rr if r.get("status") != "offline"]
    last = runs[0]

    if last.get("status") == "completed":
        c = last.get("conclusion")
        base = "dernier run %s : %s" % (last["head"], c)
        if c != "success" and actifs is not None and not actifs:
            return base + " — AUCUN runner actif, suspecter le runner avant le code"
        return base
    stuck = (last.get("age_s") or 0) > STUCK_QUEUED_S and last.get("status") == "queued"
    if stuck and actifs is not None and not actifs:
        return ("run %s queued depuis %ds et AUCUN runner actif — ce n'est pas le "
                "code, c'est le runner self-hosted" % (last["head"], int(last["age_s"])))
    if stuck:
        return "run %s queued depuis %ds — runner present, rien ne demarre" % (
            last["head"], int(last["age_s"]))
    return "dernier run %s : %s" % (last["head"], last.get("status"))


def check(repo: str = DEFAULT_REPO, branch: str = "alpha", limit: int = 5) -> dict:
    """Runs recents + runners + verdict. Ne leve pas : un capteur muet doit le DIRE."""
    cred = _creds()
    if not cred:
        return {"ok": False, "error": "GITHUB_TOKEN introuvable (coffre DPAPI)"}
    out: dict = {"ok": True, "repo": repo, "branch": branch}
    try:
        # `--branch ALL` : ne filtre PAS. Sans cette porte, l'outil ne peut
        # repondre que sur la branche demandee -- et un run recent vivant
        # ailleurs reste INVISIBLE. On en conclut alors « la CI ne tourne
        # plus » alors qu'elle tourne (mesure 2026-08-19 : un run de 25 minutes
        # etait absent de `alpha` ET de `main`, les deux seules interrogees).
        # L'outil disait pourtant « @ alpha » : la limite etait NOMMEE, c'est la
        # lecture qui l'a ignoree. Une reponse filtree doit pouvoir etre
        # redemandee SANS filtre, sinon la limite se paye en fausse conclusion.
        # FILTRE COTE CLIENT (mesure 2026-08-19, RECIDIVE 2026-08-20). `?branch=`
        # ne rattache pas tous les runs : deux fois ce jour, la liste a rendu des
        # runs vieux de DEUX JOURS en ignorant ceux du jour meme, sur la branche
        # demandee. J'ai failli en conclure « CI morte » le 19, et « pas de run »
        # le 20. Le commentaire au-dessus promettait deja de pouvoir redemander
        # SANS filtre : le code ne le faisait pas. On demande donc une fenetre
        # LARGE sans filtre serveur, et on trie sur `head_branch` nous-memes --
        # meme defiance que le tri ci-dessous, pour la meme raison.
        tous = str(branch).upper() == "ALL"
        fenetre = max(limit * 6, 30)
        raw = _api("/repos/%s/actions/runs?per_page=%d" % (repo, fenetre), cred)
        bruts = raw.get("workflow_runs", [])
        retenus = bruts if tous else [w for w in bruts
                                      if w.get("head_branch") == branch]
        # Ce que la fenetre a vu, toutes branches confondues : si `retenus` est
        # vide alors que `bruts` ne l'est pas, ce n'est pas « aucun run », c'est
        # « aucun run SUR CETTE BRANCHE » -- deux phrases tres differentes.
        out["vus_toutes_branches"] = len(bruts)
        out["runs"] = [
            {"name": w.get("name"), "head": (w.get("head_sha") or "")[:8],
             "status": w.get("status"), "conclusion": w.get("conclusion"),
             "created": w.get("created_at"), "age_s": _age_s(w.get("created_at")),
             "url": w.get("html_url")}
            for w in retenus
        ]
        # ⚠️ MESURE 2026-08-18 : interroge avec `per_page=1`, l'API a rendu un run
        # du 10 JUILLET comme « dernier », et `--wait` a donc conclu sur lui.
        # L'ordre de l'API n'est pas un contrat : on TRIE nous-memes. Un capteur
        # de verite qui designe le mauvais run est pire qu'un capteur absent —
        # celui-ci sert a decider si un push est livre.
        out["runs"].sort(key=lambda w: w.get("created") or "", reverse=True)
        # La troncature vient APRES le tri : couper d'abord rendrait `limit` runs
        # arbitraires, puis en designerait le plus recent -- soit exactement le
        # faux « dernier run » que le tri existe pour empecher.
        out["runs"] = out["runs"][:limit]
    except urllib.error.HTTPError as e:
        out["ok"] = False
        out["runs_error"] = "HTTP %s" % e.code
    except Exception as e:
        out["ok"] = False
        out["runs_error"] = ("%s: %s" % (type(e).__name__, e))[:120]
    try:
        rr = _api("/repos/%s/actions/runners" % repo, cred)
        out["runners"] = [{"name": x.get("name"), "status": x.get("status"),
                           "busy": x.get("busy")} for x in rr.get("runners", [])]
    except Exception as e:
        out["runners"] = None
        out["runners_error"] = type(e).__name__
    out["verdict"] = _verdict(out)
    return out


def wait_for(repo: str = DEFAULT_REPO, branch: str = "alpha",
             timeout_s: int = 1800, interval_s: int = 30) -> dict:
    """Attend la CONCLUSION du dernier run, au lieu d'en prendre une photo.

    Un snapshot oblige l'appelant a re-interroger a la main ; entre deux lectures il
    parle d'un etat perime. Mesure 2026-07-28 : j'ai annonce « CI en cours » 34 min
    apres la fin reelle du run. L'attente vit ICI, cote serveur, dans un run_job
    detache avec notify_agent — le signal devient PUSH, l'appelant ne sonde plus.
    """
    # `per_page=1` s'est revele piegeux (cf. le tri dans `check`) : on demande une
    # petite fenetre et on lit le run le plus RECENT, jamais « celui que l'API a
    # mis en premier ».
    deadline = time.time() + timeout_s
    r = check(repo, branch, 5)
    while time.time() < deadline:
        runs = r.get("runs") or []
        if not runs or not r.get("ok"):
            r["waited"] = True
            return r
        if runs[0].get("status") == "completed":
            r["waited"] = True
            return r
        time.sleep(interval_s)
        r = check(repo, branch, 5)
    r["waited"] = True
    r["timeout"] = timeout_s
    r["verdict"] = "TIMEOUT apres %ds — %s" % (timeout_s, r.get("verdict"))
    return r


def detail_run(repo: str, run_id: str) -> dict:
    """Etapes en ECHEC d'un run precis.

    `gh run view --log-failed` rapatrie des megaoctets de journal ; l'API des
    jobs donne directement QUELLE etape a rougi. On veut le nom de l'etape, pas
    le flot : un diagnostic qui coute plus cher que le geste qu'il eclaire n'est
    pas un diagnostic (mesure 2026-08-19).
    """
    cred = _creds()
    if not cred:
        return {"ok": False, "error": "GITHUB_TOKEN introuvable (coffre DPAPI)"}
    try:
        raw = _api("/repos/%s/actions/runs/%s/jobs" % (repo, run_id), cred)
    except Exception as exc:  # noqa: BLE001 - capteur muet : il doit le DIRE
        return {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
    jobs = []
    for j in raw.get("jobs", []):
        etapes = [{"n": s.get("number"), "nom": s.get("name"),
                   "conclusion": s.get("conclusion")}
                  for s in (j.get("steps") or [])]
        jobs.append({
            "job": j.get("name"),
            "conclusion": j.get("conclusion"),
            "url": j.get("html_url"),
            "echecs": [s for s in etapes if s["conclusion"] not in (None, "success", "skipped")],
            "etapes": len(etapes),
        })
    return {"ok": True, "repo": repo, "run": run_id, "jobs": jobs}


def inventaire_workflows(repo: str) -> dict:
    """Tous les workflows ENREGISTRES cote GitHub + leur dernier run.

    Le dossier `.github/workflows/` dit ce qui est DECLARE ; il ne dit ni ce que
    GitHub a enregistre, ni si un workflow est `disabled_manually`, ni depuis
    quand il n'a plus rien produit. Un workflow desactive reste un fichier
    parfaitement lisible dans le depot : lire le repo pour juger la CI, c'est
    lire l'intention au lieu du vivant.
    """
    cred = _creds()
    if not cred:
        return {"ok": False, "error": "GITHUB_TOKEN introuvable (coffre DPAPI)"}
    try:
        raw = _api("/repos/%s/actions/workflows?per_page=100" % repo, cred)
    except Exception as exc:  # noqa: BLE001 - capteur muet : il doit le DIRE
        return {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
    out = []
    for w in raw.get("workflows", []):
        fiche = {"nom": w.get("name"), "chemin": w.get("path"),
                 "etat": w.get("state"), "id": w.get("id"),
                 "dernier": None, "conclusion": None, "age_s": None,
                 # L'identifiant du dernier run, sans quoi un « failure depuis
                 # 74 jours » ne mene a AUCUN diagnostic : on saurait qu'un
                 # garde est mort sans pouvoir dire de quoi.
                 "run_id": None, "url": None}
        try:
            r = _api("/repos/%s/actions/workflows/%s/runs?per_page=1"
                     % (repo, w.get("id")), cred)
            runs = r.get("workflow_runs") or []
            if runs:
                fiche["dernier"] = runs[0].get("created_at")
                fiche["conclusion"] = runs[0].get("conclusion") or runs[0].get("status")
                fiche["age_s"] = _age_s(runs[0].get("created_at"))
                fiche["run_id"] = runs[0].get("id")
                fiche["url"] = runs[0].get("html_url")
        except Exception as exc:  # noqa: BLE001 - un workflow illisible n'est pas mort
            fiche["conclusion"] = "NON MESURE (%s)" % type(exc).__name__
        out.append(fiche)
    out.sort(key=lambda f: f["age_s"] if f["age_s"] is not None else 10**12)
    return {"ok": True, "repo": repo, "workflows": out}


def declencher(repo: str, workflow: str, ref: str = "alpha", entrees: dict | None = None) -> dict:
    """Declenche un `workflow_dispatch`. Rend {ok, http} -- 204 = accepte.

    Un workflow en `workflow_dispatch` seul ne se prouve QUE par un
    declenchement : le lire ne dit pas s'il tourne, et le reparer sans le lancer
    ne fait que deplacer la croyance (mesure 2026-08-19 -- `gitleaks` etait
    annonce comme fallback manuel alors qu'aucun runner ne pouvait l'allouer).

    ⚠️ 204 signifie ACCEPTE, pas REUSSI : il faut ensuite relire le run.
    """
    cred = _creds()
    if not cred:
        return {"ok": False, "error": "GITHUB_TOKEN introuvable (coffre DPAPI)"}
    corps = {"ref": ref}
    if entrees:
        corps["inputs"] = entrees
    req = urllib.request.Request(
        "%s/repos/%s/actions/workflows/%s/dispatches" % (API, repo, workflow),
        data=json.dumps(corps).encode("utf-8"),
        headers={"Authorization": "Bearer %s" % cred,
                 "Accept": "application/vnd.github+json",
                 "User-Agent": "nokido-ci",
                 "Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return {"ok": True, "http": r.status, "workflow": workflow, "ref": ref}
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:300]
        except Exception:  # noqa: BLE001 - muet-ok : le code HTTP porte deja le sens
            pass
        return {"ok": False, "http": e.code, "error": detail or str(e)}
    except Exception as exc:  # noqa: BLE001 - capteur muet : il doit le DIRE
        return {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}


def main() -> int:
    ap = argparse.ArgumentParser(description="Etat de la CI GitHub apres push")
    ap.add_argument("--repo", default=DEFAULT_REPO)
    ap.add_argument("--branch", default="alpha")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--journal", default=None,
                    help="run id : rend les LIGNES UTILES des jobs en echec")
    ap.add_argument("--verdict", default=None,
                    help="sha : PASS / FAIL / RUNNING / NOT_FOUND / STALE. "
                         "Sortie 0 UNIQUEMENT sur PASS")
    ap.add_argument("--json", action="store_true", help="sortie machine")
    ap.add_argument("--garde", type=int, default=40,
                    help="lignes retenues du journal (defaut 40). Les `FAILED ...` "
                         "d'une grosse suite tombent hors de cette fenetre : il faut "
                         "pouvoir l'elargir pour NOMMER les tests, sans pour autant "
                         "rapatrier des megaoctets par defaut.")
    ap.add_argument("--run", default=None,
                    help="inspecter un run precis : etapes en ECHEC")
    ap.add_argument("--workflows", action="store_true",
                    help="inventaire des workflows enregistres + leur dernier run")
    ap.add_argument("--dispatch", default=None,
                    help="declencher un workflow_dispatch (nom de fichier, ex gitleaks.yml)")
    ap.add_argument("--wait", action="store_true",
                    help="attend la CONCLUSION du run au lieu d'en prendre une photo")
    ap.add_argument("--timeout", type=int, default=1800,
                    help="secondes max en mode --wait (defaut 1800)")
    a = ap.parse_args()

    if a.dispatch:
        d = declencher(a.repo, a.dispatch, a.branch if a.branch != "ALL" else "alpha")
        print(json.dumps(d, ensure_ascii=False) if a.json else
              ("[ci] dispatch %s -> HTTP %s%s" % (a.dispatch, d.get("http"),
               "" if d.get("ok") else " : " + str(d.get("error"))[:200])))
        if d.get("ok"):
            print("      ACCEPTE (204) n'est pas REUSSI : relire le run avec --branch ALL")
        return 0 if d.get("ok") else 1
    if a.workflows:
        w = inventaire_workflows(a.repo)
        if a.json:
            print(json.dumps(w, ensure_ascii=False, indent=1))
            return 0 if w.get("ok") else 1
        if not w.get("ok"):
            print("[ci] workflows : %s" % w.get("error"))
            return 1
        print("[ci] %s — %d workflow(s) enregistre(s)" % (w["repo"], len(w["workflows"])))
        for f in w["workflows"]:
            age = ("%.0f j" % (f["age_s"] / 86400.0)) if f["age_s"] else "jamais"
            print("  %-9s %-34s %-13s dernier: %-10s run=%-12s %s"
                  % (f["etat"], (f["nom"] or "?")[:34], f["conclusion"] or "-",
                     age, f["run_id"] or "-", f["chemin"]))
        return 0
    if a.verdict:
        d = verdict_commit(a.repo, a.verdict, a.branch)
        if a.json:
            print(json.dumps(d, ensure_ascii=False, indent=1))
        else:
            print("[ci] %s -> %s%s" % (a.verdict[:8], d["verdict"],
                                       " : " + d["motif"] if d.get("motif") else ""))
            if d["verdict"] in (CI_NOT_FOUND, CI_STALE):
                print("     un commit non mesure n'est PAS un commit sain.")
        return 0 if d.get("verdict") == CI_PASS else 1
    if a.journal:
        d = journal_echecs(a.repo, a.journal, garde=a.garde)
        if a.json:
            print(json.dumps(d, ensure_ascii=False, indent=1))
            return 0 if d.get("ok") else 1
        if not d.get("ok"):
            print("[ci] journal %s : %s" % (a.journal, d.get("error")))
            return 1
        if not d["jobs"]:
            print("[ci] run %s : aucun job en echec" % a.journal)
            return 0
        for j in d["jobs"]:
            print("\n[ci] %s -> %s" % (j["job"], j["conclusion"]))
            if j.get("journal_indisponible"):
                print("   journal INDISPONIBLE : %s" % j["journal_indisponible"])
            for ligne in j.get("lignes", []):
                print("   " + ligne)
        return 1
    if a.run:
        d = detail_run(a.repo, a.run)
        if a.json:
            print(json.dumps(d, ensure_ascii=False, indent=1))
            return 0 if d.get("ok") else 1
        if not d.get("ok"):
            print("[ci] run %s : %s" % (a.run, d.get("error")))
            return 1
        print("[ci] %s run %s" % (d["repo"], d["run"]))
        for j in d["jobs"]:
            print("  job %-46s %s (%d etapes)"
                  % (j["job"], j["conclusion"], j["etapes"]))
            for s in j["echecs"]:
                print("     ECHEC etape %-3s %s" % (s["n"], s["nom"]))
            if j["conclusion"] not in (None, "success", "skipped") and not j["echecs"]:
                # Un job rouge sans etape rouge = l'echec est AILLEURS (annulation,
                # runner perdu, timeout). Le taire ferait chercher au mauvais endroit.
                print("     (job rouge mais AUCUNE etape en echec -> annulation, "
                      "timeout ou runner perdu ; voir %s)" % j["url"])
        return 0
    r = wait_for(a.repo, a.branch, a.timeout) if a.wait else check(a.repo, a.branch, a.limit)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0 if r.get("ok") else 1
    if not r.get("ok") and r.get("error"):
        print("[ci] %s" % r["error"], flush=True)
        return 1
    print("[ci] %s @ %s — %s" % (r["repo"], r["branch"], r["verdict"]), flush=True)
    for w in r.get("runs") or []:
        state = w.get("conclusion") or w.get("status")
        print("  %s  %-16s %s  %s" % (w["head"], state, w.get("created"), w.get("name")),
              flush=True)
    rr = r.get("runners")
    if rr is None:
        print("  runners : ILLISIBLES (%s)" % r.get("runners_error"), flush=True)
    else:
        for x in rr:
            print("  runner %s : %s (busy=%s)" % (x["name"], x["status"], x["busy"]),
                  flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
