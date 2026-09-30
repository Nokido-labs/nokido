#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""forge_public_mirror.py -- fabrique un SNAPSHOT public sans historique.

POURQUOI PAS UN MIROIR DE BRANCHES
==================================
Mesure 2026-08-29 : un secret reel (`google_api`) vit dans le blob `1e437b11be`
de `sandbox/live_bridge.map`, atteignable depuis `alpha` ET `beta` -- donc depuis
les branches qu'un miroir publierait. « Ne publier que alpha + beta » ne protege
donc RIEN, contrairement a ce que supposait la checklist.

Un snapshot ORPHELIN (commit sans parent) ne porte aucun objet ancien : ce qui
n'est pas dans l'arbre publie n'existe pas pour le clone. C'est le seul chemin
qui n'exige pas de reecrire un historique deja pousse sur deux hebergeurs.

CE QU'IL NE FAIT PAS
====================
- Il ne POUSSE rien. Il fabrique une ref locale ; publier reste un geste owner,
  explicite, vers un remote nomme.
- Il ne remplace pas la ROTATION de la cle : ce qui a ete pousse est dehors, et
  un snapshot propre ne de-publie pas le passe.
- Il ne touche NI a l'index courant NI aux branches existantes (index temporaire).

Usage :
    forge_public_mirror.py                    # dry-run : contenu et verdict
    forge_public_mirror.py --apply            # cree refs/heads/public-snapshot
    forge_public_mirror.py --source beta --apply
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

__FORGE_COLOR__ = "infra/deploy : snapshot public sans historique (miroir)"

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REF_SNAPSHOT = "refs/heads/public-snapshot"

# Ce qui ne doit JAMAIS partir. `sandbox/` porte le blob compromettant et des
# artefacts de run ; `RAG_plain_bak/` des dumps de bench (blobs >100 Mo, donnees
# tierces possibles) ; `.claude/` la config locale des agents.
#
# `docs/roadmap_product_4phases.md` : decision owner du 2026-08-30. Ce n'est pas un
# secret technique, c'est de la STRATEGIE COMMERCIALE — grille de prix, cibles
# d'acquisition nommees (Synology, Vade Secure, Datto/Kaseya, Tenable, Microsoft),
# criteres de valorisation et seuils d'ARR. Rien de tout cela n'aide un utilisateur
# du logiciel, et publier ses propres cibles de rachat affaiblit la position de
# celui qui les vise. Le fichier reste au depot prive, il ne part pas au miroir.
#: Chaque exclusion editoriale porte son MOTIF. La structure est un dict et non
#: une liste : une exclusion sans motif devient impossible a ecrire, au lieu
#: d'etre seulement deconseillee. Le NR verifie en plus qu'aucune n'attrape le
#: coeur publiable -- sans quoi un `*.py` ajoute ici rendrait un export « propre »
#: et VIDE, ce qui est un echec deguise en succes.
EXCLUSIONS_MOTIFS = {
    "sandbox": "artefacts de run ; porte aussi le blob compromettant de 2026-08-29",
    "RAG_plain_bak": "dumps de bench (blobs >100 Mo, donnees tierces possibles)",
    ".claude": "configuration locale des agents",
    "logs": "journaux d'execution locaux",
    "Nokido.env": "fichier d'environnement local",
    ".env": "fichier d'environnement local",
    "docs/roadmap_product_4phases.md":
        "STRATEGIE COMMERCIALE (decision owner 2026-08-30) : grille de prix, cibles "
        "d'acquisition nommees, seuils d'ARR. N'aide aucun utilisateur du logiciel, et "
        "publier ses propres cibles de rachat affaiblit celui qui les vise",
    # 2026-09-15 : les quatre GIF depassaient la borne d'audit (4 Mo) et l'un le cap
    # public (5 Mo). Le plafond n'est PAS releve : un equivalent publiable existe
    # deja. Les .webm correspondants (< 3,2 Mo) restent exportes, donc la
    # demonstration est preservee -- c'est une substitution de format, pas une perte.
    "docs/launch/media/demo_feed_real.gif":
        "11,83 Mo : representation lourde remplacee par demo_feed_real.webm (3,16 Mo)",
    "docs/launch/media/demo_graph_real.gif":
        "4,60 Mo : representation lourde remplacee par demo_graph_real.webm (1,76 Mo)",
    "docs/launch/media/demo_recon_real.gif":
        "4,28 Mo : representation lourde remplacee par demo_recon_real.webm (1,37 Mo)",
    "docs/launch/media/demo_netcfg_real.gif":
        "4,10 Mo : representation lourde remplacee par demo_netcfg_real.webm (1,22 Mo)",
}

EXCLUSIONS = list(EXCLUSIONS_MOTIFS)

#: Alias de lecture. `EXCLUSIONS` est un choix EDITORIAL -- ce qui n'a pas sa
#: place dans un depot public -- et n'a JAMAIS valeur d'autorite de securite.
#: L'autorite unique est `blocked_paths` du profil public de
#: `.git-publish-rules.json` (cf. `_politique_publique`). Mesure du 2026-09-15 :
#: cette liste declarait 7 chemins, l'export n'en appliquait que 3 (les quatre
#: autres ne sont pas versionnes), et 94 chemins interdits par la politique
#: sortaient quand meme, parce que ce module ne la lisait pas.
OPTIONAL_EXPORT_EXCLUSIONS = EXCLUSIONS

# ── Classification des detections de fuite ───────────────────────────────────
# DETECTION != REMEDIATION. `_LEAK_RX` (gate egress) trouve des chaines qui
# RESSEMBLENT a une fuite ; il ne dit pas si c'en est une. Mesure du 2026-09-15 :
# 827 fichiers signales, dont 748 ne portaient que du loopback -- la doc d'un
# systeme local-first en est faite -- et parmi le reste, `babel.min.js` exposait
# 112 « IP » qui sont des numeros de VERSION, et `threading.local` (Python
# standard) etait lu comme un hote interne.
#
# QUATRE ETATS, et le dernier ne bascule JAMAIS vers « sain » par defaut : ce
# qu'on ne sait pas nommer reste UNKNOWN, et UNKNOWN empeche la certification.
SENSITIVE_CONFIRMED = "SENSITIVE_CONFIRMED"
BENIGN_LOCALHOST = "BENIGN_LOCALHOST"
BENIGN_LITERAL = "BENIGN_LITERAL"
INDETERMINE = "UNKNOWN"

_RX_LOOPBACK = __import__("re").compile(r"^127(?:\.\d{1,3}){3}$")
_RX_IPV4 = __import__("re").compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")
_RX_CHEMIN_USER = __import__("re").compile(
    r"^(?:[A-Za-z]:\\Users\\|/(?:home|root)/)([^\\/\s\"']+)")

#: Litteraux NOMMES un par un. Une liste blanche : ce qui n'y est pas ne devient
#: pas benin, il devient UNKNOWN.
_BENIN_LITTERAUX = frozenset({
    "threading.local", "settings.local", "docker.internal",
    "host.docker.internal", "gateway.docker.internal",
})

#: Marques de substitution : un chemin qui porte un placeholder ne fuite rien.
_PLACEHOLDERS_UTILISATEUR = frozenset({
    "<owner>", "<user>", "USER", "%USERNAME%", "${USER}", "$USER",
    "Default", "runner", "vscode", "ubuntu",
})

def _est_asset_tiers(chemin: str) -> bool:
    """Bundle minifie ou dependance vendue : ses « IP » sont des versions."""
    c = (chemin or "").lower()
    return (c.endswith((".min.js", ".min.css", ".lock"))
            or "-bundle.js" in c or "/vendor/" in c or "/static/" in c)

def classer_fuite(valeur, chemin: str = "") -> str:
    """Une detection brute -> l'un des quatre etats. JAMAIS « sain » par defaut."""
    v = str(valeur).strip()
    if _RX_LOOPBACK.match(v):
        return BENIGN_LOCALHOST
    if v in _BENIN_LITTERAUX:
        return BENIGN_LITERAL
    if _RX_IPV4.match(v) and _est_asset_tiers(chemin):
        return BENIGN_LITERAL          # numero de version dans un bundle tiers
    m = _RX_CHEMIN_USER.match(v)
    if m:
        nom = m.group(1).strip("`,.;:)]}\"'")
        if nom in _PLACEHOLDERS_UTILISATEUR:
            return BENIGN_LITERAL
        return SENSITIVE_CONFIRMED     # chemin utilisateur REEL
    return INDETERMINE

def _politique_publique():
    """(profil_public, module_egress, erreur) -- l'AUTORITE de securite d'export.

    FAIL-CLOSED : si la politique est illisible, l'appelant refuse de produire un
    snapshot. Publier sans avoir pu lire la politique serait exactement le repli
    silencieux que la chaine de preuve interdit ailleurs.
    """
    try:
        from nokido_agent.app import forge_git_egress as _eg
    except Exception:  # noqa: BLE001
        try:
            from app import forge_git_egress as _eg  # type: ignore[no-redef]
        except Exception as e:  # noqa: BLE001
            return None, None, "politique inatteignable (%s)" % type(e).__name__
    try:
        profil = (_eg.load_manifest().get("profiles") or {}).get("public")
    except Exception as e:  # noqa: BLE001
        return None, None, "manifeste illisible (%s)" % type(e).__name__
    if not profil:
        return None, None, "profil « public » absent du manifeste"
    return profil, _eg, None


# Chemins purges de l'HISTOIRE dans le mode --historique. Aux exclusions du
# snapshot s'ajoutent les fichiers d'environnement nommement identifies par
# l'audit du 2026-08-29 (ils ne sont plus dans l'arbre courant, mais ils sont
# dans l'histoire, et c'est justement ce qu'on retire ici).
PURGE_HISTORIQUE = EXCLUSIONS + [
    "LaForge.env",
    "LaForge.env.bak",
    "LaForge - Copie.env",
]


def _git(*args, env=None, check=False):
    e = {**os.environ, "GIT_TERMINAL_PROMPT": "0", **(env or {})}
    r = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(ROOT), *args],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=e, timeout=600)
    if check and r.returncode != 0:
        raise RuntimeError("git %s -> %s" % (" ".join(args[:2]), r.stderr.strip()[:160]))
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def _index_temporaire(source, profil=None, eg=None):
    """Rend (tree, optionnelles, bloques, env) : l'arbre de `source` moins DEUX
    familles, tenues SEPAREES parce qu'elles n'ont pas la meme autorite.

      - `optionnelles` : OPTIONAL_EXPORT_EXCLUSIONS, choix editorial local ;
      - `bloques`      : `blocked_paths` du profil public, SECURITE, autorite
                         unique. Applique ici parce que `git rm --cached` ne
                         comprend pas les globs du manifeste (`**/x/**`) : on
                         enumere l'index et on filtre avec le meme
                         `_path_blocked` que le gate egress -- un seul juge.

    Passe par un GIT_INDEX_FILE dedie : l'index courant et les branches ne sont
    jamais touches, donc l'operation est sans effet de bord meme interrompue.
    """
    fd, chemin = tempfile.mkstemp(prefix="nokido_mirror_", suffix=".index")
    os.close(fd)
    os.unlink(chemin)  # git veut creer le fichier lui-meme
    env = {"GIT_INDEX_FILE": chemin}
    _git("read-tree", source, env=env, check=True)

    # ORDRE VOULU : la SECURITE d'abord, sur l'arbre COMPLET. Si l'editorial
    # passait en premier, la politique ne verrait que le reliquat -- un chemin
    # editorial trop large masquerait son travail sans que personne ne le voie,
    # et son compte serait faux. Le recouvrement entre les deux listes est alors
    # une defense en profondeur, jamais une dependance.
    bloques = {"regles": len((profil or {}).get("blocked_paths") or []),
               "fichiers": 0, "par_regle": {}, "echantillon": [],
               "applique_sur": "arbre complet, AVANT les exclusions editoriales"}
    motifs = (profil or {}).get("blocked_paths") or []
    if motifs and eg is not None:
        _rc, complet, _ = _git("ls-files", env=env)
        a_retirer = [p for p in complet.splitlines()
                     if p.strip() and eg._path_blocked(p.strip(), motifs)]
        for i in range(0, len(a_retirer), 200):   # par lots : ligne de commande bornee
            _git("rm", "--cached", "-q", "--ignore-unmatch", "--",
                 *a_retirer[i:i + 200], env=env)
        for p in a_retirer:
            r = eg._path_blocked(p, motifs)
            cle = str(r if isinstance(r, str) else "?")
            bloques["par_regle"][cle] = bloques["par_regle"].get(cle, 0) + 1
        bloques["fichiers"] = len(a_retirer)
        bloques["echantillon"] = sorted(a_retirer)[:10]
        bloques["echantillon_note"] = ("%d retire(s), %d montre(s)"
                                       % (len(a_retirer), min(10, len(a_retirer))))

    optionnelles = []
    for chemin_exclu in OPTIONAL_EXPORT_EXCLUSIONS:
        rc, _out, _ = _git("rm", "--cached", "-r", "-q", "--ignore-unmatch",
                           "--", chemin_exclu, env=env)
        rc2, liste, _ = _git("ls-tree", "-r", "--name-only", source,
                             "--", chemin_exclu)
        n = len(liste.splitlines()) if (rc == 0 and liste) else 0
        optionnelles.append({"chemin": chemin_exclu, "fichiers": n,
                             "effet": "retire" if n else "sans objet (non versionne)",
                             "motif": EXCLUSIONS_MOTIFS.get(chemin_exclu, "NON DECLARE")})

    _, tree, _ = _git("write-tree", env=env, check=True)
    try:
        os.unlink(chemin)
    except OSError as e:  # noqa: BLE001
        sys.stderr.write("[mirror] index temporaire non supprime (%s)\n" % e)
    return tree, optionnelles, bloques, env


def _audit_du_tree(tree, profil=None, eg=None):
    """Verifie que l'ARBRE publie ne porte ni secret reel ni fuite residuelle.

    TROIS DEFAUTS CORRIGES le 2026-09-15, tous mesures sur l'artefact :

    1. LES BLOBS HORS BORNE DISPARAISSAIENT EN SILENCE. La borne de 4 Mo ecartait
       les gros blobs AVANT comptage : ils n'etaient ni dans `blobs`, ni dans
       `non_inspectes`. L'audit rendait donc « vert » en ayant omis 4 blobs
       (11,83 / 4,60 / 4,28 / 4,10 Mo). Un vert obtenu sans avoir regarde n'est
       pas un vert : ils sont desormais COMPTES, NOMMES, et l'etat ne peut plus
       etre vert tant qu'ils ne sont pas traites explicitement.
    2. LE CAP DU PROFIL N'ETAIT PAS VERIFIE ICI. Un fichier au-dessus de
       `max_file_bytes` partait sans que le miroir le sache.
    3. `scrub: true` NE MASQUAIT RIEN. Le controle de fuite host/IP/path vit dans
       le gate egress et n'y rend qu'un AVERTISSEMENT non bloquant, tandis que le
       masqueur (`forge_sovereign_membrane`) n'est importe par aucun chemin
       d'export. Tant que la remediation n'est pas branchee, une fuite residuelle
       REFUSE le snapshot au lieu de le laisser passer en jaune.

    On reutilise `_LEAK_RX` du gate egress : un seul motif de fuite pour toute la
    chaine, jamais un second detecteur parallele.
    """
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.tools.forge_history_secret_audit import (EXCEPTIONS, MOTIFS, _est_factice,
                                                lire_blobs)
    except Exception as e:  # noqa: BLE001
        return {"etat": "illisible", "detail": "audit indisponible (%s)" % type(e).__name__}
    import re
    rc, liste, _ = _git("ls-tree", "-r", "--long", tree)
    if rc != 0:
        return {"etat": "illisible", "detail": "ls-tree a echoue"}
    # Lecture par FLUX : un `cat-file` par blob rendait cet audit inutilisable
    # (tue au bout de 115 s sur cet arbre). Un seul process, alimente en lot.
    cibles, hors_borne, trop_gros = {}, [], []
    cap_profil = int((profil or {}).get("max_file_bytes") or 0)
    for ligne in liste.splitlines():
        champs = ligne.split(None, 4)
        if len(champs) < 5 or champs[1] != "blob":
            continue
        sha, taille, nom = champs[2], champs[3], champs[4].strip()
        t = int(taille) if taille.isdigit() else -1
        if cap_profil and t > cap_profil:
            trop_gros.append({"fichier": nom, "octets": t, "cap": cap_profil})
        if t >= 0 and t <= 4_000_000:
            cibles[sha] = nom
        else:
            hors_borne.append({"fichier": nom, "octets": t,
                               "etat": "OVER_LIMIT" if t >= 0 else "TAILLE_ILLISIBLE",
                               "borne_audit": 4_000_000})
    if not cibles and not hors_borne:
        return {"etat": "vert", "findings": [], "blobs": 0,
                "hors_borne": [], "depassent_le_cap": trop_gros}
    trouves, non_lus, exemptes = [], 0, []
    for sha, data, _taille in lire_blobs(list(cibles)):
        if data is None:
            non_lus += 1
            continue
        if cibles.get(sha) in EXCEPTIONS:
            exemptes.append(cibles[sha])
            continue
        for typ, motif in MOTIFS.items():
            if [h for h in re.findall(motif, data) if not _est_factice(h)]:
                trouves.append({"fichier": cibles.get(sha, "?"), "type": typ})
    base = {"blobs": len(cibles), "hors_borne": hors_borne,
            "depassent_le_cap": trop_gros,
            "couverture": "%d inspecte(s) / %d blob(s) uniques"
                          % (len(cibles), len(cibles) + len(hors_borne))}
    if trouves:
        return dict(base, etat="rouge", findings=trouves)
    if non_lus:
        # Un blob non inspecte n'est pas un blob propre : on ne certifie pas
        # un snapshot dont une partie n'a pas ete regardee.
        return dict(base, etat="illisible", findings=[], non_inspectes=non_lus)
    if hors_borne:
        # MEME REGLE, appliquee a ce que la BORNE ecartait : ils etaient
        # silencieusement absents du denominateur. Ils y sont, et ils bloquent.
        return dict(base, etat="illisible", findings=[],
                    raison_illisible=("%d blob(s) au-dessus de la borne d'audit, "
                                      "jamais inspecte(s)" % len(hors_borne)))
    # Fuite residuelle : seulement si le profil DEMANDE un scrub.
    if (profil or {}).get("scrub") and eg is not None and getattr(eg, "_LEAK_RX", None):
        # `lire_blobs` rend des OCTETS (les motifs de secrets de
        # `forge_history_secret_audit` sont compiles sur bytes), tandis que
        # `_LEAK_RX` du gate egress est compile sur du TEXTE. Decoder ici plutot
        # que dupliquer le motif en bytes : un seul motif de fuite pour toute la
        # chaine. Les blobs binaires ressortent en caracteres de remplacement,
        # ce qui ne peut produire qu'un faux NEGATIF -- jamais un faux positif.
        non_decodes = 0
        compte = {SENSITIVE_CONFIRMED: 0, BENIGN_LOCALHOST: 0,
                  BENIGN_LITERAL: 0, INDETERMINE: 0}
        f_sensibles, f_indetermines = {}, {}
        for sha, data, _t in lire_blobs(list(cibles)):
            if data is None:
                continue
            try:
                texte = data.decode("utf-8", "replace") if isinstance(data, bytes) else data
            except Exception:  # noqa: BLE001
                non_decodes += 1
                continue
            nom = cibles.get(sha, "?")
            for brut in eg._LEAK_RX.findall(texte):
                classe = classer_fuite(brut, nom)
                compte[classe] += 1
                if classe == SENSITIVE_CONFIRMED:
                    f_sensibles[nom] = f_sensibles.get(nom, 0) + 1
                elif classe == INDETERMINE:
                    f_indetermines.setdefault(nom, set()).add(str(brut)[:60])
        if non_decodes:
            base["non_decodes"] = non_decodes
        base["detections"] = dict(compte)
        base["fichiers_sensibles"] = len(f_sensibles)
        base["fichiers_indetermines"] = len(f_indetermines)

        if compte[SENSITIVE_CONFIRMED]:
            top = sorted(f_sensibles.items(), key=lambda x: -x[1])[:20]
            return dict(base, etat="rouge", findings=[],
                        sensibles_confirmes=[{"fichier": f, "occurrences": n} for f, n in top],
                        sensibles_note=("%d fichier(s) porteur(s), %d montre(s). Un "
                                        "masquage a l'export CASSERAIT le produit (un "
                                        "chemin d'interpreteur aliase rend le script "
                                        "inexecutable) : la remediation est une "
                                        "correction A LA SOURCE."
                                        % (len(f_sensibles), min(20, len(f_sensibles)))))
        if compte[INDETERMINE]:
            # On ne certifie pas ce qu'on n'a pas su NOMMER. Un detecteur qui
            # bascule l'inconnu vers « sain » fabrique un vert sans mesure.
            ech = sorted(f_indetermines.items(), key=lambda x: -len(x[1]))[:15]
            return dict(base, etat="illisible", findings=[],
                        indetermines=[{"fichier": f, "valeurs": sorted(v)[:3]} for f, v in ech],
                        indetermines_note=("%d fichier(s) portent %d detection(s) que la "
                                           "classification n'a pas su trancher ; %d "
                                           "montre(s). UNKNOWN ne devient jamais sain "
                                           "par defaut."
                                           % (len(f_indetermines), compte[INDETERMINE],
                                              min(15, len(f_indetermines)))))
        base["scrub_verifie"] = (
            "0 detection sensible ni indeterminee sur %d blob(s) inspecte(s) ; "
            "benines ecartees : %d loopback, %d litteraux"
            % (len(cibles), compte[BENIGN_LOCALHOST], compte[BENIGN_LITERAL]))
    return dict(base, etat="vert", findings=[],
                exceptions_appliquees=sorted(set(exemptes)))


def construire(source="alpha", apply=False):
    rc, _, _ = _git("rev-parse", "--verify", "--quiet", source)
    if rc != 0:
        return {"ok": False, "raison": "source « %s » introuvable" % source}
    profil, eg, err_pol = _politique_publique()
    if err_pol:
        # FAIL-CLOSED. Produire un snapshot sans avoir pu lire la politique, c'est
        # exactement le repli silencieux que cette chaine interdit partout ailleurs.
        return {"ok": False, "source": source, "applique": False,
                "raison": "politique de publication illisible : %s" % err_pol}

    tree, optionnelles, bloques, _ = _index_temporaire(source, profil, eg)
    audit = _audit_du_tree(tree, profil, eg)
    rapport = {
        "source": source, "tree": tree[:12],
        # DEUX familles, jamais fondues : l'une est un choix, l'autre une autorite.
        "bloques_par_politique": bloques,
        "exclusions_optionnelles": optionnelles,
        "profil": {"scrub": profil.get("scrub"),
                   "max_file_bytes": profil.get("max_file_bytes"),
                   "regles_bloquantes": len(profil.get("blocked_paths") or [])},
        "audit_du_snapshot": audit, "applique": False,
    }
    if audit["etat"] != "vert":
        rapport["ok"] = False
        rapport["raison"] = ("snapshot NON cree : l'arbre porte encore des secrets ou "
                             "des fuites, ou n'a pas pu etre integralement audite "
                             "(etat=%s)" % audit["etat"])
        return rapport
    if not apply:
        rapport["note"] = "DRY-RUN : rien cree. Relancer avec --apply."
        return rapport
    _, sha_src, _ = _git("rev-parse", source)
    message = ("Nokido — public snapshot (%s)\n\n"
               "Snapshot SANS historique : commit orphelin, aucun objet anterieur.\n"
               "L'atelier prive n'est pas publie. Source interne : %s\n"
               % (source, sha_src[:12]))
    rc, commit, err = _git("commit-tree", tree, "-m", message)
    if rc != 0:
        rapport["raison"] = "commit-tree a echoue : %s" % err[:140]
        return rapport
    rc, _, err = _git("update-ref", REF_SNAPSHOT, commit)
    if rc != 0:
        rapport["raison"] = "update-ref a echoue : %s" % err[:140]
        return rapport
    rapport.update({"applique": True, "ref": REF_SNAPSHOT, "commit": commit[:12],
                    "publier": "geste OWNER : git push <remote-public> "
                               "%s:refs/heads/main" % REF_SNAPSHOT})
    return rapport


def historique_nettoye(branche="alpha", cible=None, apply=False):
    """Miroir a HISTOIRE PRESERVEE, moins les chemins sensibles.

    Pourquoi ce mode en plus du snapshot : un depot public a UN commit orphelin
    donne peu a lire -- l'histoire d'un projet fait partie de son serieux. Ici on
    garde les 4 925 commits et on retire les fichiers, via `git filter-repo`.

    Ce n'est PAS un scrub du depot d'origine : on travaille sur un CLONE, la
    source n'est jamais modifiee. Les sha du miroir different de ceux de
    l'atelier -- c'est inevitable des qu'on touche a l'histoire, et sans
    consequence puisque le miroir est une destination, jamais une source.
    """
    cible = Path(cible or (ROOT / "sandbox" / "public_mirror_repo"))
    rapport = {"branche": branche, "cible": str(cible),
               "chemins_purges": PURGE_HISTORIQUE, "applique": False}
    rc, _, _ = _git("rev-parse", "--verify", "--quiet", branche)
    if rc != 0:
        rapport["raison"] = "branche « %s » introuvable" % branche
        return rapport
    if not apply:
        rapport["note"] = ("DRY-RUN : rien clone. --apply clone puis purge "
                           "l'histoire (le depot source n'est jamais touche).")
        return rapport
    if cible.exists():
        rapport["raison"] = ("cible deja presente : la supprimer sciemment, on "
                             "n'ecrase pas un depot existant")
        return rapport
    r = subprocess.run(["git", "-c", "safe.directory=*", "clone", "--no-local",
                        "--branch", branche, "--single-branch",
                        str(ROOT), str(cible)],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=1800)
    if r.returncode != 0:
        rapport["raison"] = "clone echoue : %s" % r.stderr.strip()[-200:]
        return rapport
    # `git filter-repo` (le BINAIRE), pas `python -m git_filter_repo` : sous
    # trusted_script l'interpreteur courant est laforge_py314, qui n'a pas le
    # module -- mesure 2026-08-29. L'outil git, lui, est le meme quel que soit
    # le compte. Ne jamais supposer que l'interpreteur du process est celui qui
    # porte les dependances.
    cmd = ["git", "filter-repo", "--invert-paths", "--force"]
    for chemin in PURGE_HISTORIQUE:
        cmd += ["--path", chemin]
    r = subprocess.run(cmd, cwd=str(cible), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=3600)
    if r.returncode != 0:
        rapport["raison"] = "filter-repo echoue : %s" % (r.stderr or r.stdout)[-250:]
        return rapport
    rapport["applique"] = True
    rapport["filter_repo"] = (r.stdout or "").strip().splitlines()[-3:]
    # Sha SOURCE inscrit HORS de l'arbre publie (dans .git/), pour qu'un controle
    # puisse dire « ce miroir date d'avant le HEAD courant ». Sans cette trace, la
    # regle « ne jamais publier sur la foi d'une verification ancienne » repose sur
    # la vigilance de celui qui publie -- donc sur rien.
    _, sha_src, _ = _git("rev-parse", branche)
    try:
        (cible / ".git" / "nokido_source_sha").write_text(sha_src, encoding="utf-8")
        rapport["source_sha"] = sha_src[:12]
    except OSError as e:  # noqa: BLE001
        rapport["source_sha"] = "NON INSCRIT (%s) : fraicheur invérifiable" % type(e).__name__
    rapport["publier"] = ("geste OWNER : git -C %s push <remote-public> "
                          "%s:refs/heads/main" % (cible, branche))
    return rapport


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", default="alpha")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--historique", action="store_true",
                    help="miroir avec l'HISTOIRE preservee, moins les chemins sensibles")
    ap.add_argument("--cible", default=None)
    args = ap.parse_args(argv)
    if args.historique:
        r = historique_nettoye(args.source, args.cible, args.apply)
        print(json.dumps(r, ensure_ascii=False, indent=2) if args.json else
              "\n".join("  %-20s %s" % (k, v) for k, v in r.items()))
        return 0 if r.get("applique") or not args.apply else 1
    r = construire(args.source, args.apply)
    print(json.dumps(r, ensure_ascii=False, indent=2) if args.json else
          "\n".join("  %-22s %s" % (k, v) for k, v in r.items()))
    return 0 if r.get("ok", True) and r.get("audit_du_snapshot", {}).get("etat") == "vert" else 1


if __name__ == "__main__":
    sys.exit(main())
