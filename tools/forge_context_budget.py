"""forge_context_budget.py — ce que le contexte RESIDENT coute, a chaque tour.

__FORGE_COLOR__ = "observabilite/budget-de-contexte"

POURQUOI (owner, 2026-09-12). Le depot a des cliquets pour la mutation, la
duplication, les regles d'or, la couverture NR. Il n'en avait aucun pour la seule
ressource depensee a CHAQUE tour de chaque session : le contexte resident.
Mesure du jour : ~154 Ko, dont 51,6 % pour un seul fichier.

Un chiffre dans une conversation disparait avec elle. Ce module en fait un
ARTEFACT, et le NR associe en fait un CLIQUET : le resident ne doit plus croitre
sans decision. La reduction viendra ensuite — on abaisse alors le plafond, ce qui
est un geste explicite, trace, et reversible.

⚠️ TROIS ETATS, JAMAIS DEUX. Une partie du resident vit dans le PROFIL de l'owner
(`~/.claude/skills`), que les comptes de service ne peuvent pas lire — `exists()`
y rend False, et un refus lu comme une absence ferait tomber le total a l'insu de
tous. Ce qui n'a pas pu etre lu est donc compte `INDETERMINE` et NOMME, jamais
additionne comme un zero. Le budget ne porte que sur ce qui est LISIBLE partout,
c'est-a-dire les fichiers du depot.

Usage :
    forge_context_budget.py            # rapport lisible
    forge_context_budget.py --json
    forge_context_budget.py --check    # 0 sous budget, 1 au-dessus
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Plafond pose sur la MESURE du 2026-09-12, pas sur une cible souhaitee : un
# cliquet gele l'etat courant et interdit la degradation. Abaisser ce chiffre est
# une decision, et elle se voit dans le diff.
BUDGET_DEPOT_OCTETS = 125_000

# ⚠️ TROIS COMPTEURS, JAMAIS UN SEUL (owner, 2026-09-12). La premiere version de
# ce module annoncait « TOTAL DEPOT 121 674 -> ok » face a une baseline de
# 154 336. L'ecart n'etait PAS une reduction : 154 336 - 18 389 (MEMORY)
# - 14 273 (descriptions) = 121 674, au chiffre pres. Le denominateur avait
# change, pas le resident. Un tel rapport devient un faux vert des qu'on ne se
# souvient plus de l'amputation.
#
#   RESIDENT_TOTAL     tout ce qui est effectivement resident
#   RESIDENT_BUDGETED  le sous-ensemble reellement sous plafond
#   RESIDENT_UNKNOWN   le resident qu'on n'a PAS pu mesurer
#
# Et la regle qui ferme le piege : tant qu'un poste est INDETERMINE,
# RESIDENT_TOTAL vaut INDETERMINE — jamais un nombre. Sinon « RULES baisse,
# CLAUDE.md baisse, skills illisibles » se conclurait « gain de 25 % » en
# ignorant justement un composant resident.

# BASELINE T0 — FIGEE. Toute comparaison ulterieure se fait a denominateur
# IDENTIQUE, poste par poste. Ne pas reecrire ces chiffres : c'est le temoin.
T0 = {
    "date": "2026-09-12",
    "total": 154_336,
    "par_poste": {
        "RULES_SHARED.md": 79_698,
        "CLAUDE.md (Nokido)": 38_312,
        "MEMORY.md": 18_389,
        "descriptions de skills": 14_273,
        "CLAUDE.md (racine)": 3_664,
    },
}

# Budgets SEPARES : sans cela, « instructions -30 % / memoire +300 % » passerait
# pour une amelioration.
BUDGETS = {
    "kernel_depot": BUDGET_DEPOT_OCTETS,   # RULES_SHARED + les deux CLAUDE.md
    "memoire": 25_000,                      # cap de chargement de l'auto-memoire
    "descriptions_skills": 16_000,          # T0 = 14 273, marge courte assumee
}

# Fichiers du DEPOT, lisibles par tous les comptes -> ils portent le budget.
RESIDENT_DEPOT = [
    ("RULES_SHARED.md", ROOT / "RULES_SHARED.md"),
    ("CLAUDE.md (Nokido)", ROOT / "CLAUDE.md"),
    ("CLAUDE.md (racine)", ROOT.parent / "CLAUDE.md"),
]

# Resident hors depot : mesure quand on peut, DECLARE sinon.
PROFIL = Path(os.environ.get("LAFORGE_PROFIL_OWNER") or r"%USERPROFILE%")
RESIDENT_PROFIL = [
    ("MEMORY.md", PROFIL / ".claude" / "projects"
     / "C--Users-user-Script-python-IA" / "memory" / "MEMORY.md"),
]
SKILLS_DIR = PROFIL / ".claude" / "skills"

# ⚠️ UNE SEULE RACINE NE DECRIT PAS LE POSTE (mesure 2026-09-20). `SKILLS_DIR`
# etait la seule racine lue, alors que les descriptions residentes viennent d'au
# moins quatre endroits : le profil, le CACHE DE PLUGINS (367 `SKILL.md` sur
# disque ce jour-la), les skills du depot et ceux du projet. Le module etait donc
# honnete sur ce qu'il ne pouvait pas LIRE, et muet sur ce qu'il ne REGARDAIT
# pas — exactement le defaut du 2026-09-19 : « un controle vrai ne couvre que ce
# qu'il mesure ». Un poste lu sur une racine sur quatre aurait pu sortir `ok`.
RACINES_SKILLS = [
    ("profil", PROFIL / ".claude" / "skills"),
    ("plugins", PROFIL / ".claude" / "plugins" / "cache"),
    ("projet", ROOT / ".claude" / "skills"),
    ("depot", ROOT / "docs" / "skills"),
]

# ⚠️ CE QUE LE DEPOT GOUVERNE — et donc ce que le CLIQUET peut juger.
#
# Deux des quatre racines vivent dans le PROFIL de la machine : elles ne sont pas
# dans le commit, aucun diff ne peut les corriger, et elles different d'une
# machine a l'autre. Mesure du 2026-09-20 sur un MEME sha :
#
#     poste local  45 603 o (86 skills)     runner CI  28 727 o  -> DEPASSE
#
# Le runner a son propre profil et son propre cache de plugins. Le cliquet
# rendait donc DEUX verdicts pour UN commit : il echouait sur GitHub et passait
# en local. Un cliquet dont le denominateur change avec la machine ne juge rien,
# et surtout ne se rattache a aucun commit -- or c'est exactement ce que la
# phase 0 exige (« un statut FERME PAR COMMIT »).
#
# Le budget porte donc sur les racines du DEPOT. Le hors-depot reste MESURE et
# RAPPORTE, jamais juge : cesser de juger n'autorise pas a cesser de montrer,
# sinon la croissance qu'on ne juge plus devient invisible.
RACINES_GOUVERNEES = ("projet", "depot")

# RELAIS DE MESURE. Aucun canal du hub n'atteint le profil owner (mesure
# 2026-09-20 : compte sandbox refuse, `ps_clm` ferme par l'attestation DEV), et
# c'est VOULU. Le seul executeur automatique qui y lit est un hook, lance sous le
# compte de session. Il depose son releve ici ; ce module le SERT — mais jamais
# comme une lecture directe, et jamais s'il est perime : `STALE` n'est pas une
# mesure, servir un chiffre de la semaine derniere fabriquerait un faux calme.
RELEVE_SKILLS = ROOT / "sandbox" / "workspace" / "context_skills_releve.json"
RELEVE_TTL_S = 24 * 3600


def _taille(p: Path):
    """(octets, motif) — `stat` peut LEVER, pas seulement rendre un absent."""
    try:
        return p.stat().st_size, None
    except OSError as exc:
        return None, type(exc).__name__


def _description_de(fichier: Path):
    """Longueur de la seule `description` du frontmatter, ou None si illisible."""
    try:
        txt = fichier.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    fin = txt.find("\n---", 3)
    tete = txt[:fin] if fin > 0 else txt[:2000]
    m = re.search(r"^description:\s*(.+?)(?=\n[a-zA-Z_-]+:|\Z)", tete,
                  re.M | re.S)
    return len(" ".join((m.group(1) if m else "").split()))


def _lire_racine(racine: Path):
    """({nom_de_skill: octets}, motif_de_refus | None).

    ⚠️ ABSENT n'est pas ILLISIBLE, et la difference decide du verdict. Sous un
    compte de service `Path.exists()` ne rend pas `False` : il LEVE
    `PermissionError [WinError 5]` (mesure faite sur ce module meme). Mais une
    racine dont l'absence est PROUVEE — le parcours aboutit et ne rend rien — est
    un vide CERTAIN : la traiter en inconnue rendrait le poste INDETERMINE pour
    toujours, donc inutile. On separe donc le refus (OSError) du vide.

    ⚠️ ET SURTOUT : le parcours est EXPLICITE parce que `Path.rglob` AVALE les
    `OSError` rencontrees en chemin. Premiere version de ce correctif : une
    racine refusee y rendait zero fichier SANS lever, donc le poste sortait `ok`
    avec un total ampute — precisement le faux vert que ce module existe pour
    interdire. Le NR l'a attrape parce qu'il simule un REFUS et non une absence.
    """
    trouves, refus = {}, None
    ignores = {".git", "node_modules", "__pycache__", ".venv"}
    pile, racine_vue = [Path(racine)], False
    while pile:
        d = pile.pop()
        try:
            with os.scandir(d) as it:
                entrees = list(it)
        except FileNotFoundError:
            # Absence PROUVEE : le parcours a abouti et n'a rien trouve. C'est un
            # vide CERTAIN, pas un inconnu — le compter comme inconnu rendrait le
            # poste INDETERMINE pour toujours, donc incapable de se fermer.
            racine_vue = True
            continue
        except OSError as exc:
            refus = refus or type(exc).__name__
            racine_vue = True
            continue
        racine_vue = True
        for e in entrees:
            try:
                est_dossier = e.is_dir(follow_symlinks=False)
            except OSError as exc:
                refus = refus or type(exc).__name__
                continue
            if est_dossier:
                if e.name not in ignores:
                    pile.append(Path(e.path))
            elif e.name == "SKILL.md":
                taille = _description_de(Path(e.path))
                if taille is None:
                    refus = refus or "IllisibleSKILL"
                    continue
                # Le cache de plugins REPLIQUE les skills (`cache/` et
                # `marketplaces/`) : sans cle par NOM, le poste serait double ou
                # triple, et toute « reduction » mesuree ensuite serait la
                # disparition d'un doublon plutot qu'un gain.
                trouves.setdefault(Path(e.path).parent.name, taille)
    if not racine_vue:
        refus = refus or "NonParcourue"
    return trouves, refus


def _releve_depose():
    """(dict|None, raison). Le relais n'est servi que FRAIS, et il le dit."""
    try:
        brut = json.loads(RELEVE_SKILLS.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, "aucun releve exploitable (%s)" % type(exc).__name__
    age = time.time() - float(brut.get("mesure_le") or 0)
    if age > RELEVE_TTL_S:
        return None, ("releve perime (%.1f h > %.1f h) — STALE n'est pas une mesure"
                      % (age / 3600.0, RELEVE_TTL_S / 3600.0))
    return brut, None


def descriptions_skills() -> dict:
    """Seule la `description` d'un skill est residente ; son corps ne l'est pas.

    Le distinguer est essentiel : un SKILL.md de 24 Ko avec une description de
    200 caracteres coute 200 caracteres, pas 24 Ko.

    Quatre etats, jamais deux :
      ok          toutes les racines declarees ont ete parcourues ;
      RELEVE      une racine a REFUSE, mais un releve FRAIS couvre le poste ;
      PARTIEL     une racine a refuse et rien ne la couvre -> plancher NOMME ;
      INDETERMINE rien de fiable (y compris : un releve perime).
    """
    # POINT D'INJECTION HISTORIQUE. `SKILLS_DIR` reste la racine « profil » et
    # continue donc de mordre. Sans cela, elargir la portee DESARMAIT en silence
    # le monkeypatch des NR existants : ils passaient toujours, en ne testant
    # plus rien — meme famille qu'un durcissement jamais appele (2026-09-18).
    racines = [(nom, (SKILLS_DIR if nom == "profil" else chemin))
               for nom, chemin in RACINES_SKILLS]
    par_skill, lues, refusees = {}, [], []
    for nom, racine in racines:
        trouves, refus = _lire_racine(Path(racine))
        if refus:
            refusees.append("%s(%s)" % (nom, refus))
            continue
        lues.append(nom)
        for cle, taille in trouves.items():
            par_skill.setdefault(cle, taille)

    plancher = sum(par_skill.values())
    # Le sous-total GOUVERNE se calcule a part : il ne doit dependre NI du volume
    # NI de la lisibilite des racines hors depot. Son etat lui est propre — une
    # racine DU DEPOT qui refuse rend le poste gouverne INDETERMINE, et cela seul
    # doit suspendre le verdict.
    gouv_octets, gouv_refus = 0, []
    for nom, racine in racines:
        if nom not in RACINES_GOUVERNEES:
            continue
        trouves_g, refus_g = _lire_racine(Path(racine))
        if refus_g:
            gouv_refus.append("%s(%s)" % (nom, refus_g))
            continue
        gouv_octets += sum(trouves_g.values())
    base = {"octets": plancher, "n": len(par_skill),
            "racines_lues": lues, "racines_illisibles": refusees,
            "octets_gouvernes": None if gouv_refus else gouv_octets,
            "etat_gouverne": "INDETERMINE" if gouv_refus else "ok",
            "racines_gouvernees_illisibles": gouv_refus}
    if not refusees:
        return dict(base, etat="ok")

    releve, raison = _releve_depose()
    if releve is not None:
        return dict(base, etat="RELEVE",
                    octets=int(releve.get("octets") or 0),
                    n=int(releve.get("n") or 0),
                    raison="releve depose le %s" % releve.get("mesure_le"))
    if "perime" in raison:
        # Un chiffre mort ne remplace pas une mesure absente : on retombe sur
        # INDETERMINE en DISANT pourquoi, plutot que de servir le plancher comme
        # s'il valait le total.
        return dict(base, etat="INDETERMINE", raison=raison)
    return dict(base, etat="PARTIEL",
                raison="racine(s) illisible(s) : %s — le chiffre ci-dessus est un "
                       "PLANCHER, pas un total" % ", ".join(refusees))


def ecrire_releve(chemin: Path | None = None, force: bool = False) -> dict:
    """Depose la mesure la ou un compte moins privilegie pourra la LIRE.

    Appele par un hook tournant sous le compte de session (le seul executeur
    automatique qui atteint le profil owner). Ne coute aucun token.

    Le parcours traverse plusieurs centaines de `SKILL.md` ; un hook de
    SessionStart le paierait a CHAQUE ouverture pour une valeur qui bouge a peine.
    Tant que le releve est FRAIS au sens de `RELEVE_TTL_S` — le meme seuil que
    celui qui decide s'il est servable, pour qu'il n'y ait pas deux definitions de
    la fraicheur dans le module — il est laisse tel quel et le dit (`reecrit`).
    """
    cible = Path(chemin or RELEVE_SKILLS)
    if not force:
        deja, _raison = _releve_depose()
        if deja is not None and cible == Path(RELEVE_SKILLS):
            return dict(deja, reecrit=False)
    r = descriptions_skills()
    charge = {"mesure_le": time.time(), "octets": r.get("octets"),
              "n": r.get("n"), "etat_source": r.get("etat"),
              "racines_lues": r.get("racines_lues"),
              "racines_illisibles": r.get("racines_illisibles")}
    cible.parent.mkdir(parents=True, exist_ok=True)
    cible.write_text(json.dumps(charge, ensure_ascii=False, indent=1),
                     encoding="utf-8")
    return dict(charge, reecrit=True)


def mesurer() -> dict:
    depot, indetermines = {}, []
    total_depot = 0
    for nom, p in RESIDENT_DEPOT:
        taille, err = _taille(p)
        if taille is None:
            indetermines.append("%s (%s)" % (nom, err))
            depot[nom] = None
        else:
            depot[nom] = taille
            total_depot += taille

    hors_depot = {}
    for nom, p in RESIDENT_PROFIL:
        taille, err = _taille(p)
        if taille is None:
            indetermines.append("%s (%s)" % (nom, err))
        hors_depot[nom] = taille
    sk = descriptions_skills()
    hors_depot["descriptions de skills"] = sk.get("octets")
    # ⚠️ UN PLANCHER N'EST PAS UNE MESURE JUGEABLE. Elargir la portee a fait
    # passer ce poste de None a un nombre PARTIEL, et le verdict de budget s'est
    # remis a le comparer au plafond : `12784 > 16000` -> False -> « ok ». Le
    # faux vert que ce module existe pour interdire, reintroduit par le bas.
    # Attrape par `test_un_budget_ne_se_declare_pas_tenu_sur_un_poste_illisible`.
    # ⚠️ LE VERDICT PORTE SUR LE GOUVERNE, PAS SUR LE TOTAL. Juger le total
    # revenait a faire echouer une CI pour des fichiers absents du commit, que
    # personne ne pouvait corriger par un diff (mesure 2026-09-20). Le total
    # continue d'etre rendu, et `descriptions_skills_etat` dit ce qu'il vaut.
    sk_jugeable = (sk.get("octets_gouvernes")
                   if sk.get("etat_gouverne") == "ok" else None)
    # `RELEVE` est une MESURE — faite ailleurs, par un executeur qui pouvait lire,
    # et refusee des qu'elle est perimee. La compter comme inconnue laisserait le
    # poste INDETERMINE a jamais, c'est-a-dire sans aucun moyen de se fermer.
    if sk["etat"] not in ("ok", "RELEVE"):
        indetermines.append("descriptions de skills (%s)"
                            % (sk.get("raison") or sk.get("etat")))

    connus = total_depot + sum(v for v in hors_depot.values() if v)

    # RESIDENT_TOTAL n'est un NOMBRE que si tout a pu etre lu. Sinon c'est
    # INDETERMINE, et aucun gain global ne peut etre annonce.
    complet = not indetermines
    # ⚠️ UN BUDGET NE SE DECLARE PAS « ok » SUR CE QU'IL N'A PAS MESURE. Premiere
    # version : `(None or 0) > 16000` rendait False, donc « ok » — le meme faux
    # vert que celui qu'on venait de fermer un cran plus haut, mais par poste.
    # Trois etats ici aussi : True (depasse) / False (tenu) / None (INDETERMINE).
    def _verdict(valeur, plafond):
        return None if valeur is None else valeur > plafond

    depassements = {
        "kernel_depot": _verdict(total_depot, BUDGETS["kernel_depot"]),
        "memoire": _verdict(hors_depot.get("MEMORY.md"), BUDGETS["memoire"]),
        "descriptions_skills": _verdict(sk_jugeable,
                                        BUDGETS["descriptions_skills"]),
    }
    return {
        "T0": T0,
        "budgets": BUDGETS,
        "RESIDENT_BUDGETED": total_depot,
        "RESIDENT_BUDGETED_tokens_est": total_depot // 4,
        "RESIDENT_UNKNOWN": indetermines,
        "RESIDENT_TOTAL": connus if complet else None,
        "RESIDENT_TOTAL_etat": "MESURE" if complet else "INDETERMINE",
        "resident_partiel_octets": connus,
        "depot_octets": depot,
        "hors_depot_octets": hors_depot,
        # L'etat du poste voyage avec sa valeur : un lecteur qui voit 12784 doit
        # pouvoir savoir que c'est un PLANCHER et non un total.
        "descriptions_skills_etat": sk["etat"],
        "descriptions_skills_racines_illisibles": sk.get("racines_illisibles"),
        "depassements": depassements,
        # `depasse` ne vaut True que sur un DEPASSEMENT MESURE : un poste
        # indetermine ne fait echouer aucun cliquet, mais il ne le fait pas
        # passer non plus — il ressort dans RESIDENT_UNKNOWN.
        "depasse": any(v is True for v in depassements.values()),
        "budgets_NON_VERIFIES": [k for k, v in depassements.items() if v is None],
        "budget_depot_octets": BUDGET_DEPOT_OCTETS,
        "depot_total": total_depot,
        "depot_tokens_est": total_depot // 4,
        "resident_connu_octets": connus,
        "resident_connu_tokens_est": connus // 4,
        "INDETERMINES": indetermines,
        "comparaison_T0": (
            {"delta_total": connus - T0["total"]} if complet else
            {"delta_total": "INDETERMINE — un poste resident n'a pas pu etre lu ; "
                            "comparer a T0 exigerait le MEME denominateur"}),
        "note": "tokens estimes = octets/4. `/context` donne la mesure vraie ; "
                "ce module mesure le DISQUE et ne voit ni le prompt systeme ni "
                "les schemas d'outils non deferes.",
    }


# Ou LIRE la valeur observee de chaque poste. La table est explicite parce que les
# postes ne vivent pas au meme endroit : le depot est un total, les deux autres
# sont des entrees du dictionnaire hors-depot. Sans elle, l'explication devrait
# deviner -- et une explication qui devine est pire que pas d'explication.
_OBSERVE = {
    "kernel_depot": lambda m: m.get("depot_total"),
    "memoire": lambda m: (m.get("hors_depot_octets") or {}).get("MEMORY.md"),
    "descriptions_skills": lambda m: (m.get("hors_depot_octets") or {}).get(
        "descriptions de skills"),
}


def expliquer(m: dict) -> str:
    """Nomme le poste QUI A DECLENCHE le verdict, avec son ecart au plafond.

    POURQUOI. `depasse` agrege TROIS budgets, mais le cliquet imprimait la seule
    ventilation de `kernel_depot`. Le 2026-09-14 il a donc annonce « le contexte
    resident du depot depasse son budget : 124907 o pour 125000 » -- un chiffre
    SOUS son plafond -- alors que la cause etait `memoire` (25239 / 25000). Une
    heure d'enquete du mauvais cote, sur un module qui, lui, etait juste : il
    portait deja les trois etats et ne faisait jamais basculer `depasse` sur un
    `None`. Ce qui manquait n'etait pas la mesure, c'etait de la DIRE.

    Un agregat qui ne nomme pas ce qui l'a fait basculer renvoie l'enqueteur au
    hasard, et le hasard choisit le poste le plus visible.

    Trois sorties, jamais deux : le(s) poste(s) DEPASSE(S) avec leur ecart, les
    postes NON VERIFIES -- qui ne sont ni tenus ni depasses et ne doivent jamais
    se lire comme une cause -- et, quand rien ne deborde, une phrase qui le dit
    (une explication vide se relit comme un defaut de l'explication)."""
    budgets = m.get("budgets") or {}
    verdicts = m.get("depassements") or {}
    causes, non_verifies = [], []
    for poste, verdict in verdicts.items():
        if verdict is None:
            non_verifies.append(poste)
            continue
        if verdict is not True:
            continue
        lire = _OBSERVE.get(poste)
        observe = lire(m) if lire else None
        plafond = budgets.get(poste)
        if observe is None or plafond is None:
            causes.append("%s: au-dela du plafond, chiffres indisponibles" % poste)
        else:
            causes.append("%s: %d o / %d (+%d)"
                          % (poste, observe, plafond, observe - plafond))
    bouts = [("DEPASSE -> " + " ; ".join(causes)) if causes
             else "aucun depassement mesure"]
    if non_verifies:
        bouts.append("NON VERIFIE (ni tenu ni depasse) : " + ", ".join(non_verifies))
    return " | ".join(bouts)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--releve", action="store_true",
                    help="depose la mesure du poste skills pour les comptes qui "
                         "ne peuvent pas lire le profil (a lancer en hook)")
    ap.add_argument("--force", action="store_true",
                    help="avec --releve : reecrire meme si le releve est frais")
    args = ap.parse_args(argv)
    if args.releve:
        charge = ecrire_releve(force=args.force)
        print("releve %s : %s skills, %s o -> %s"
              % ("depose" if charge.get("reecrit") else "deja frais",
                 charge["n"], charge["octets"], RELEVE_SKILLS))
        return 0
    m = mesurer()
    if args.json:
        print(json.dumps(m, ensure_ascii=False, indent=1))
    else:
        print("=== CONTEXTE RESIDENT (mesure disque) ===")
        for nom, v in m["depot_octets"].items():
            print("  %-22s %8s o   [depot, sous budget]"
                  % (nom, v if v is not None else "INDET"))
        for nom, v in m["hors_depot_octets"].items():
            print("  %-22s %8s o   [hors depot, hors budget]"
                  % (nom, v if v is not None else "INDET"))
        print("  %-22s %8d o  (~%d tok est.)  [SOUS BUDGET]"
              % ("RESIDENT_BUDGETED", m["RESIDENT_BUDGETED"],
                 m["RESIDENT_BUDGETED_tokens_est"]))
        if m["RESIDENT_TOTAL"] is None:
            print("  %-22s %8s      <- un poste resident n'a pas pu etre lu"
                  % ("RESIDENT_TOTAL", "INDETERMINE"))
            print("  %-22s %8d o  (plancher, PAS un total)"
                  % ("  dont mesure", m["resident_partiel_octets"]))
        else:
            print("  %-22s %8d o  (~%d tok est.)"
                  % ("RESIDENT_TOTAL", m["RESIDENT_TOTAL"],
                     m["RESIDENT_TOTAL"] // 4))
        for cle, depasse in m["depassements"].items():
            etat = ("NON VERIFIE (poste illisible)" if depasse is None
                    else "DEPASSE" if depasse else "ok")
            print("  budget %-16s %8d o -> %s"
                  % (cle, m["budgets"][cle], etat))
        print("  T0 (%s) : %d o — comparaison : %s"
              % (m["T0"]["date"], m["T0"]["total"],
                 m["comparaison_T0"]["delta_total"]))
        if m["INDETERMINES"]:
            print("\n  NON MESURE (n'est PAS zero) : %s"
                  % ", ".join(m["INDETERMINES"]))
            print("  => aucun gain global ne peut etre annonce tant que ce poste "
                  "n'est pas lisible.")
    if args.check:
        return 1 if m["depasse"] else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
