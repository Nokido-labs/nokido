#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""forge_release_gate.py -- le point d'entree UNIQUE avant d'ouvrir ou de livrer.

POURQUOI
========
Les briques de qualite existent deja et MORDENT : gate ALIGNEMENT et scan secret
au pre-commit, egress au push, gitleaks en workflow dedie, cliquets mutation et
duplication, verrou de composition (`forge_release_lock`). Ce qui manquait n'est
pas un controle de plus -- c'est UN point ou tout converge et qui REFUSE.

Une CI de developpement est volontairement tolerante : elle fait du triage
incremental, sinon elle est rouge en permanence et plus personne ne la lit. Une
RELEASE ne l'est pas. Ce module est donc separe de `ci.yml` a dessein, et il
n'assouplit rien : il agrege et il tranche.

TROIS ETATS, jamais deux -- repris du verrou de composition :
    0  GO            tous les controles verts
    1  NO-GO         au moins un controle rouge
    2  INDETERMINE   au moins un controle n'a pas pu etre mesure

Le troisieme est le plus important : **une absence de mesure n'est jamais un
succes**. On ne livre pas dans le doute, on va chercher la mesure.

Usage :
    LAFORGE_PYTHON tools/forge_release_gate.py           # verdict lisible
    LAFORGE_PYTHON tools/forge_release_gate.py --json    # pour un workflow
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

__FORGE_COLOR__ = "livraison/gate-de-release"

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERT, ROUGE, ILLISIBLE = "vert", "rouge", "illisible"
_EXCLUS = re.compile(r"_attic|legacy|sandbox|inspirations|_mcp_repos|__pycache__")


def _git(*args, cwd=None):
    try:
        r = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(cwd or ROOT),
                            *args],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=60,
                           env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except (OSError, subprocess.SubprocessError) as e:
        return 255, "", str(e)


def ctrl_syntaxe():
    """Aucun .py du perimetre livre ne doit etre casse. Un fichier ILLISIBLE
    compte comme non mesure, jamais comme sain."""
    casses, illisibles, vus = [], [], 0
    for d in ("app", "tools"):
        for dp, _dn, fn in os.walk(ROOT / d):
            if _EXCLUS.search(dp):
                continue
            for f in fn:
                if not f.endswith(".py"):
                    continue
                p = Path(dp) / f
                vus += 1
                try:
                    src = p.read_text(encoding="utf-8", errors="replace")
                except OSError as e:
                    illisibles.append("%s (%s)" % (f, e))
                    continue
                try:
                    compile(src, str(p), "exec")
                except SyntaxError as e:
                    casses.append("%s l.%s" % (p.relative_to(ROOT), e.lineno))
    if illisibles:
        return ILLISIBLE, "%d illisibles sur %d : %s" % (len(illisibles), vus, illisibles[:3])
    if casses:
        return ROUGE, "%d fichiers casses : %s" % (len(casses), casses[:5])
    return VERT, "%d fichiers, 0 erreur" % vus


# Artefacts DERIVES, reecrits par le hook post-commit (`tools/forge_post_commit.py`)
# apres CHAQUE commit. Le tampon `<!-- STATS:<sha du HEAD> -->` du README est une
# auto-reference impossible a satisfaire -- exactement la limite deja assumee par
# `forge_release_lock` (« un fichier ne peut pas contenir son propre hash ») : le
# commiter change le sha, donc le hook le reecrit, donc l'arbre redevient sale.
# Retirer le sha ne suffirait pas : les compteurs `rag_chunks` / `embeddings`
# bougent en continu. Mesure 2026-08-30 : l'arbre s'est resali TROIS fois pendant
# une seule session, et un controle rouge par construction finit par etre ignore.
# On les ecarte donc du verdict, mais on les NOMME dans le detail : un angle mort
# tu redevient un vert.
_ARTEFACTS_POST_COMMIT = {
    "README.md",
    "docs/skills/nokido/SKILL.md",
    "docs/wiki/20-Modules-Reference.md",
    "sandbox/workspace/organ_map_full.json",
}


def ctrl_arbre_propre():
    """Un arbre sale rend le verdict caduc : on livrerait autre chose que ce qui
    a ete mesure. Vrai des SOURCES ; faux des artefacts que le corps regenere."""
    rc, out, err = _git("status", "--porcelain", "--untracked-files=no")
    if rc != 0:
        return ILLISIBLE, "git status rc=%s %s" % (rc, err[:90])
    # PAS de decoupe par POSITION. `_git` fait `.strip()` sur la sortie ENTIERE :
    # la premiere ligne y perd son espace de tete, si bien que `l[3:]` mangeait une
    # lettre du nom (mesure 2026-08-30 : « EADME.md », et le fichier passait alors
    # pour une SOURCE sale au lieu d'un artefact derive). Le statut porcelain fait
    # un ou deux caracteres selon que la ligne a ete strippee ou non : on decoupe
    # donc sur le premier blanc, ce qui marche dans les deux cas et preserve les
    # chemins contenant des espaces.
    sales = []
    for ligne in out.splitlines():
        if not ligne.strip():
            continue
        morceaux = ligne.strip().split(None, 1)
        sales.append((morceaux[1] if len(morceaux) > 1 else morceaux[0]).strip())
    derives = sorted(f for f in sales if f in _ARTEFACTS_POST_COMMIT)
    sources = sorted(f for f in sales if f not in _ARTEFACTS_POST_COMMIT)
    if sources:
        return ROUGE, "%d fichier(s) SOURCE non commis : %s" % (len(sources), sources[:5])
    if derives:
        return VERT, ("aucune source en attente ; %d artefact(s) derive(s) du "
                      "post-commit ecarte(s) : %s" % (len(derives), derives))
    return VERT, "aucun fichier suivi en attente"


def ctrl_publication():
    """Le HEAD local doit EXISTER au distant : sinon on tague une composition que
    personne d'autre ne peut recuperer. Le distant fait autorite, jamais la ref
    de suivi `origin/<branche>` (figee des qu'un push vient d'un job)."""
    rc, branche, _ = _git("rev-parse", "--abbrev-ref", "HEAD")
    if rc != 0:
        return ILLISIBLE, "branche courante illisible"
    rc, local, _ = _git("rev-parse", "HEAD")
    rc2, sortie, err = _git("ls-remote", "origin", "refs/heads/%s" % branche)
    if rc != 0 or rc2 != 0 or not sortie:
        return ILLISIBLE, "distant injoignable (%s)" % (err[:80] or "ls-remote muet")
    distant = sortie.split()[0]
    if distant == local:
        return VERT, "%s = distant %s" % (branche, distant[:10])
    rc3, _, _ = _git("merge-base", "--is-ancestor", local, distant)
    return (VERT, "HEAD publie (distant en avance)") if rc3 == 0 else \
        (ROUGE, "HEAD %s absent du distant %s" % (local[:10], distant[:10]))


def ctrl_composition():
    """Verrou de composition : la combinaison livree est-elle celle qui a ete
    eprouvee ? Reutilise `forge_release_lock`, ne le reimplemente pas."""
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.tools.forge_release_lock import verifier
        code, detail = verifier()
    except Exception as e:  # noqa: BLE001 - un controle qui casse est INDETERMINE
        return ILLISIBLE, "verrou indisponible (%s: %s)" % (type(e).__name__, str(e)[:80])
    return {0: VERT, 1: ROUGE}.get(code, ILLISIBLE), str(detail)[:160]


def ctrl_filet_clonable():
    """La gouvernance doit survivre au CLONE : sans elle, la promesse centrale du
    depot n'est pas verifiable par celui qui l'evalue."""
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.tools import forge_hooks_install as fhi
        cablage, motif = fhi._reference()
        if cablage is None:
            return ILLISIBLE, "reference de cablage %s" % motif
        absents = sorted({e["script"] for e in cablage
                          if fhi._script_path(e["script"]) is None})
    except Exception as e:  # noqa: BLE001
        return ILLISIBLE, "installeur indisponible (%s)" % type(e).__name__
    if absents:
        return ROUGE, "cablages nommant des scripts absents : %s" % absents
    return VERT, "%d cablages, tous les scripts presents" % len(cablage)


# ── Controles d'EXPOSITION (option --public) ────────────────────────────────
# Livrer une version et OUVRIR le depot sont deux gestes differents : le second
# est IRREVERSIBLE (ce qui est publie une fois est copie, indexe, archive). Ces
# controles ne s'appliquent donc qu'a l'ouverture, sinon ils rendraient le gate
# rouge en permanence pour de simples releases internes.
_CHECKLIST = ROOT / "docs" / "public_transition_checklist.md"
_SECTION_P0 = "Obligatoire AVANT de rendre public"
_BRANCHES_PUBLIABLES = {"alpha", "main", "beta"}


def ctrl_checklist_publique():
    """La checklist n'est pas un document, c'est une condition.

    Elle porte (mesure du 2026-08-21) des secrets dans l'HISTOIRE ancienne : le
    gate egress avait bloque le push de tags d'archive. Un HEAD propre ne repare
    pas un historique expose -- ce qui est publie une fois ne se reprend pas.
    """
    try:
        txt = _CHECKLIST.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ILLISIBLE, "checklist absente : conditions d'ouverture inconnues"
    except OSError as e:
        return ILLISIBLE, "checklist illisible: %s" % e
    bloc = txt.split(_SECTION_P0, 1)
    if len(bloc) < 2:
        return ILLISIBLE, "section « %s » introuvable" % _SECTION_P0
    corps = bloc[1].split("\n## ", 1)[0]
    ouverts = re.findall(r"^\s*-\s*\[ \]\s*(.+)$", corps, re.M)
    if ouverts:
        return ROUGE, "%d condition(s) d'ouverture non tenue(s) : %s" % (
            len(ouverts), [o[:60] for o in ouverts[:3]])
    return VERT, "toutes les conditions d'ouverture sont cochees"


def _miroir():
    p = ROOT / "sandbox" / "public_mirror_repo"
    return p if ((p / ".git").exists() or (p / "HEAD").exists()) else None


def ctrl_branches_exposees():
    """Quelles branches partiraient REELLEMENT.

    Incoherence corrigee le 2026-08-29 : ce controle jugeait les branches de
    l'ATELIER alors que la strategie retenue publie un MIROIR. Il refusait donc
    sur `review/*`, `hackathon/*` et consorts qui ne seront jamais exposees --
    exactement le meme defaut que celui deja corrige pour les secrets. Un gate
    qui controle autre chose que ce qu'on publie ne controle rien.
    """
    miroir = _miroir()
    if miroir:
        rc, out, err = _git("branch", "--format=%(refname:short)", cwd=miroir)
        if rc != 0:
            return ILLISIBLE, "miroir present mais illisible (%s)" % err[:70]
        noms = [l.strip() for l in out.splitlines() if l.strip()]
        hors = sorted(n for n in noms if n not in _BRANCHES_PUBLIABLES)
        if hors:
            return ROUGE, "le MIROIR porte %d branche(s) non publiable(s) : %s" % (
                len(hors), hors[:6])
        return VERT, "miroir : %d branche(s), toutes publiables (%s)" % (
            len(noms), ", ".join(noms[:4]))
    rc, out, err = _git("ls-remote", "--heads", "origin")
    if rc != 0 or not out:
        return ILLISIBLE, "distant injoignable (%s)" % (err[:70] or "ls-remote muet")
    noms = [l.split("refs/heads/", 1)[-1] for l in out.splitlines() if "refs/heads/" in l]
    hors = sorted(n for n in noms if n not in _BRANCHES_PUBLIABLES)
    if hors:
        return ROUGE, ("aucun miroir : l'atelier exposerait %d branche(s) interne(s) "
                       "(%s) -- fabriquer le miroir" % (len(hors), hors[:4]))
    return VERT, "%d branche(s), toutes publiables" % len(noms)


def ctrl_miroir_a_jour():
    """Le miroir doit correspondre au HEAD qu'on s'apprete a publier.

    « Ne jamais publier sur la foi d'une verification ancienne » etait une regle
    ecrite ; elle reposait donc sur la vigilance de celui qui publie. Elle est ici
    MESUREE : le miroir inscrit son sha source, on le compare au HEAD courant.
    """
    miroir = _miroir()
    if not miroir:
        return ROUGE, "aucun miroir fabrique : rien a publier de propre"
    trace = miroir / ".git" / "nokido_source_sha"
    try:
        source = trace.read_text(encoding="utf-8").strip()
    except OSError:
        return ILLISIBLE, ("miroir sans trace de sa source : impossible de dire s'il "
                           "est a jour -- le regenerer")
    rc, head, _ = _git("rev-parse", "HEAD")
    if rc != 0:
        return ILLISIBLE, "HEAD courant illisible"
    if source == head:
        return VERT, "miroir a jour (%s)" % head[:12]
    rc, ecart, _ = _git("rev-list", "--count", "%s..HEAD" % source)
    return ROUGE, ("miroir fabrique sur %s, HEAD est a %s (%s commit(s) d'ecart) : "
                   "le REGENERER avant publication"
                   % (source[:12], head[:12], ecart or "?"))


def ctrl_ui_gate_arme():
    """Un gate qui peut se SAUTER en silence n'interdit rien.

    Mesure : le job ui-acceptance ecrit `ui-gate SKIP` quand LAFORGE_ADMIN_TOKEN
    est absent. Tolerable en developpement ; inacceptable pour une ouverture, ou
    « la GUI n'a pas ete validee » doit BLOQUER et non produire un avertissement.
    """
    p = ROOT / ".github" / "workflows" / "ci-selfhosted.yml"
    try:
        txt = p.read_text(encoding="utf-8")
    except OSError as e:
        return ILLISIBLE, "workflow illisible: %s" % e
    if not re.search(r"ui-gate SKIP", txt):
        return VERT, "contrat UI sans echappatoire"
    # L'echappatoire existe dans le workflow -- mais elle ne se DECLENCHE que si
    # le secret manque. Juger sur le texte seul refuserait un contrat qui
    # s'execute en fait a chaque run : on demande son etat au REEL.
    # `gh` lit **GH_TOKEN dans l'ENVIRONNEMENT** : `gh auth login` n'est PAS
    # necessaire, et ce controle n'a donc jamais eu besoin d'une session owner.
    # Mesure 2026-08-30 : il est reste INDETERMINE toute la journee et j'ai
    # ecrit qu'il etait « owner-only » -- faux. Le jeton est AU COFFRE, comme le
    # dit la doctrine, et `forge_push_sovereign` sert deja les siens a git par ce
    # meme chemin. Il passe par l'ENV et jamais par la ligne de commande : le hub
    # journalise les args de `run`, un jeton colle dans une cmdline y resterait.
    env = dict(os.environ)
    provenance = "auth native de gh"
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_secrets import get_secret

        jeton = get_secret("GITHUB_TOKEN")
        if jeton:
            env["GH_TOKEN"] = jeton
            provenance = "jeton du coffre"
    except Exception as e:  # noqa: BLE001 - coffre indisponible : on tente l'auth native
        provenance = "coffre injoignable (%s), auth native de gh" % type(e).__name__
    r = subprocess.run(["gh", "api", "repos/Nokido-labs/nokido-private/actions/secrets",
                        "--jq", ".secrets[].name"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=60, env=env)
    if r.returncode != 0:
        return ILLISIBLE, ("echappatoire presente et etat du secret illisible "
                           "(%s ; %s) : ni arme ni desarme prouve"
                           % (r.stderr.strip()[:70], provenance))
    if "LAFORGE_ADMIN_TOKEN" in (r.stdout or ""):
        return VERT, ("echappatoire presente mais INERTE : LAFORGE_ADMIN_TOKEN est "
                      "defini, le contrat UI s'execute")
    return ROUGE, ("ui-acceptance SKIP faute de LAFORGE_ADMIN_TOKEN : le contrat UI "
                   "n'est opposable a aucune release")


def ctrl_modules_versionnes():
    """Un module non suivi par git est un TRAVAIL DANS LE VIDE.

    Mesure 2026-08-29 : `tools/nokido_historical_consolidation.py` -- le pipeline
    qui chaine generations, juge et rejeu de capacites perdues -- existait sur le
    disque et n'etait suivi par AUCUN git. Consequences concretes : il n'existait
    pour personne d'autre, aucune CI ne le jouait, et `trusted_script` refusait de
    l'executer (« privilege = code revu uniquement »). Un outil qu'on ne peut ni
    partager ni lancer en privilegie n'est pas un outil.
    """
    rc, out, err = _git("status", "--porcelain", "--untracked-files=all",
                        "--", "tools", "app")
    if rc != 0:
        return ILLISIBLE, "git status rc=%s %s" % (rc, err[:80])
    orphelins = [l[3:].strip() for l in out.splitlines()
                 if l.startswith("??") and l.strip().endswith(".py")]
    if orphelins:
        return ROUGE, "%d module(s) hors git : %s" % (len(orphelins), orphelins[:5])
    return VERT, "tous les modules de tools/ et app/ sont versionnes"


def ctrl_politique_export():
    """Le profil public bloque-t-il ENCORE les domaines critiques ?

    Les deux publieurs (forge_dist_publish, launch_public_mirror) filtrent leur
    assemblage avec `blocked_paths` du profil public -- leur push contourne le
    gate egress, donc c'est leur SEULE protection. Ce controle garde contre le
    scenario ou quelqu'un vide ou casse le profil : si un domaine critique n'y
    est plus, un futur export les laisserait fuir. On lit le manifeste REEL via
    l'autorite unique `forge_git_egress`, jamais une liste copiee ici.
    """
    try:
        sys.path.insert(0, str(ROOT / "app"))
        import forge_git_egress as _eg
        profil = (_eg.load_manifest().get("profiles") or {}).get("public") or {}
    except Exception as e:  # noqa: BLE001 - un controle qui casse est INDETERMINE
        return ILLISIBLE, "manifeste illisible (%s)" % type(e).__name__
    motifs = profil.get("blocked_paths") or []
    # Sentinelles : un chemin de CHAQUE domaine critique doit rester bloque.
    sentinelles = {
        "IP_HOLD": "docs/ip/IP_TRIAGE_CANDIDATS.md",
        "telemetrie": ".agents/orchestrator/BRIEFING.md",
        "secrets": "sandbox/secrets/x.json",
        "env-config": "config/LaForge.env",
    }
    trous = [dom for dom, ex in sentinelles.items() if not _eg._path_blocked(ex, motifs)]
    if trous:
        return ROUGE, "profil public ne bloque plus : %s" % ", ".join(trous)
    if not (profil.get("scrub") and (profil.get("max_file_bytes") or 0) > 0):
        return ROUGE, "profil public sans scrub ou sans cap de taille"
    return VERT, "profil public : %d regles, domaines critiques couverts" % len(motifs)


CONTROLES = [
    ("syntaxe", ctrl_syntaxe),
    ("modules versionnes", ctrl_modules_versionnes),
    ("arbre propre", ctrl_arbre_propre),
    ("publication", ctrl_publication),
    ("composition", ctrl_composition),
    ("filet clonable", ctrl_filet_clonable),
    ("politique export", ctrl_politique_export),
]

def ctrl_secrets_historique():
    """Ce que l'HISTOIRE exposerait, pas ce que HEAD montre.

    Mesure 2026-08-29 : un secret reel vit dans l'histoire de `alpha` ET `beta` --
    donc les branches qu'un miroir publierait. Retirer le fichier de HEAD n'y
    change rien : le commit qui l'a introduit reste lisible.
    """
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.tools.forge_history_secret_audit import audit
        r = audit()
    except Exception as e:  # noqa: BLE001 - jamais de vert par defaut de mesure
        return ILLISIBLE, "audit d'historique indisponible (%s)" % type(e).__name__
    if r["verdict"] != "EXPOSE":
        return VERT, "aucun secret reel atteignable depuis les refs publiables"
    # L'atelier porte des secrets dans son histoire -- mais ce n'est pas lui qu'on
    # publie. Si un miroir NETTOYE existe, c'est LUI le futur depot public : juger
    # la source reviendrait a laisser ce controle rouge pour toujours, et un gate
    # perpetuellement rouge finit par etre ignore.
    miroir = ROOT / "sandbox" / "public_mirror_repo"
    if (miroir / ".git").exists() or (miroir / "HEAD").exists():
        try:
            from nokido_agent.tools import forge_history_secret_audit as fhs
            origine = fhs.ROOT
            fhs.ROOT = miroir
            try:
                m = fhs.audit_exhaustif(refs=("refs/heads/alpha",),
                                        max_octets=40_000_000)
            finally:
                fhs.ROOT = origine
        except Exception as e:  # noqa: BLE001
            return ILLISIBLE, "miroir present mais non auditable (%s)" % type(e).__name__
        if m["verdict"] != "EXPOSE" and not m.get("blobs_non_inspectes"):
            return VERT, ("l'atelier garde ses secrets mais le MIROIR publiable est "
                          "propre (%s blobs, 0 non inspecte)" % m.get("blobs_lus"))
        return ROUGE, "le miroir publiable porte encore %d secret(s)" % m["exposes_si_publication"]
    return ROUGE, ("%d secret(s) reel(s) partiraient : %s -- publier le MIROIR "
                   "(forge_public_mirror --historique) ou le snapshot, pas l'atelier"
                   % (r["exposes_si_publication"],
                      sorted({f["chemin"] for f in r["findings"]})[:3]))


_RAPPORT_UI = ROOT / "sandbox" / "ui_campaign" / "report.json"
_AGE_UI_MAX_H = 24.0


def _routes_du_contrat():
    """Nombre de routes que la campagne UI declare couvrir, ou None si illisible.

    Compte par lecture AST plutot que par import : `forge_ui_campaign` tire
    playwright et l'application web au niveau module, et un import qui echoue
    rendrait ILLISIBLE a tort. Expose (et non recopie dans les tests) pour qu'un
    ajout de route n'oblige pas a mettre a jour un nombre en dur ailleurs.
    """
    try:
        import ast as _ast

        arbre = _ast.parse((ROOT / "tools" / "forge_ui_campaign.py")
                           .read_text(encoding="utf-8"))
        for n in arbre.body:
            if (isinstance(n, _ast.Assign) and isinstance(n.value, _ast.List)
                    and any(isinstance(t, _ast.Name) and t.id == "ROUTES"
                            for t in n.targets)):
                return len(n.value.elts)
    except (OSError, SyntaxError, ValueError):
        return None      # illisible ici = on ne PRETEND pas savoir
    return None


def ctrl_parcours_ui():
    """Le PARCOURS utilisateur a-t-il ete verifie dans un vrai navigateur ?

    `forge_ui_campaign` pilote firefox, se connecte par le FORMULAIRE, visite les
    routes, clique les controles surs et rend un contrat d'acceptation par route.
    Il distingue deja « viole » de « pas pu juger » (harnais absent, mesure du
    2026-08-12). Tout cela existait -- et son verdict n'atteignait PAS la decision
    de publication : la GUI pouvait etre rouge sans que le gate le sache.

    L'age compte autant que le verdict : un contrat vert d'il y a trois jours ne
    dit rien du HEAD qu'on s'apprete a publier. Meme regle que pour le miroir.
    """
    try:
        r = json.loads(_RAPPORT_UI.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ROUGE, ("aucune campagne UI jouee : le parcours utilisateur n'a jamais "
                       "ete verifie dans un navigateur (tools/forge_ui_campaign.py)")
    except (OSError, json.JSONDecodeError) as e:
        return ILLISIBLE, "rapport de campagne illisible (%s)" % type(e).__name__
    age_h = (time.time() - _RAPPORT_UI.stat().st_mtime) / 3600.0
    verdict = str(r.get("verdict", "")).upper()
    non_jugees = r.get("routes_non_jugees") or []
    en_cause = r.get("route_en_cause") or []
    if verdict not in ("CONFORME", "VIOLE"):
        return ILLISIBLE, "campagne non concluante (verdict=%s, %.0f h)" % (verdict, age_h)
    if verdict == "VIOLE" or en_cause:
        return ROUGE, "contrat UI VIOLE sur %s" % (en_cause[:4] or "route(s) non nommee(s)")
    if non_jugees:
        return ILLISIBLE, "%d route(s) NON JUGEE(S) : %s" % (len(non_jugees), non_jugees[:4])
    if age_h > _AGE_UI_MAX_H:
        return ILLISIBLE, ("contrat CONFORME mais vieux de %.0f h : un parcours vert "
                           "d'avant-hier ne dit rien du HEAD -- rejouer la campagne"
                           % age_h)
    # Le PERIMETRE du rapport doit etre celui du contrat COURANT. Mesure
    # 2026-08-30 : trois routes generatives (/ui/auto/*) ont ete ajoutees a la
    # campagne, et ce controle est reste VERT sur un rapport ANTERIEUR qui ne les
    # avait jamais visitees -- le vert survivait a l'elargissement du contrat qu'il
    # est cense faire respecter. Un rapport peut etre FRAIS et INCOMPLET : l'age ne
    # dit rien de la couverture. On compte les routes du contrat sans importer le
    # module (il tire playwright et l'app web au niveau module ; un import qui
    # echoue rendrait ILLISIBLE a tort).
    attendu = _routes_du_contrat()
    vues = (r.get("couverture_clics") or {}).get("routes_enumerees")
    if attendu is None or vues is None:
        return ILLISIBLE, ("contrat CONFORME mais perimetre inverifiable "
                           "(contrat=%s, rapport=%s) : impossible de dire si la "
                           "campagne couvre toutes les routes" % (attendu, vues))
    if vues < attendu:
        return ILLISIBLE, ("campagne jouee sur %d routes alors que le contrat en "
                           "compte %d : %d route(s) ajoutee(s) depuis n'ont jamais "
                           "ete visitees -- rejouer la campagne"
                           % (vues, attendu, attendu - vues))
    return VERT, ("parcours UI conforme, campagne de %.0f h, %d/%d routes couvertes"
                  % (age_h, vues, attendu))


CONTROLES_PUBLICS = [
    ("secrets historique", ctrl_secrets_historique),
    ("miroir a jour", ctrl_miroir_a_jour),
    ("parcours UI", ctrl_parcours_ui),
    ("checklist publique", ctrl_checklist_publique),
    ("branches exposees", ctrl_branches_exposees),
    ("contrat UI arme", ctrl_ui_gate_arme),
]


def gate(public: bool = False):
    resultats = []
    for nom, fn in CONTROLES + (CONTROLES_PUBLICS if public else []):
        try:
            etat, detail = fn()
        except Exception as e:  # noqa: BLE001 - jamais de vert par accident
            etat, detail = ILLISIBLE, "%s: %s" % (type(e).__name__, str(e)[:90])
        resultats.append({"controle": nom, "etat": etat, "detail": detail})
    rouges = [r for r in resultats if r["etat"] == ROUGE]
    flous = [r for r in resultats if r["etat"] == ILLISIBLE]
    code = 1 if rouges else (2 if flous else 0)
    verdict = {1: "NO-GO", 2: "INDETERMINE"}.get(code, "GO")
    return code, {"verdict": verdict, "code": code, "controles": resultats}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--public", action="store_true",
                    help="ajoute les conditions d'OUVERTURE du depot (irreversibles)")
    args = ap.parse_args(argv)
    code, rapport = gate(public=args.public)
    if args.json:
        print(json.dumps(rapport, ensure_ascii=False, indent=2))
        return code
    marque = {VERT: "OK  ", ROUGE: "ROUGE", ILLISIBLE: "?????"}
    for r in rapport["controles"]:
        print("  %-6s %-16s %s" % (marque[r["etat"]], r["controle"], r["detail"]))
    print("\n  VERDICT : %s (code %d)" % (rapport["verdict"], code))
    if code == 2:
        print("  Une absence de mesure n'est pas un succes : aller chercher la mesure.")
    return code


if __name__ == "__main__":
    sys.exit(main())
