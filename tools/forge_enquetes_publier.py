"""Publie la memoire d'enquete sous une forme partageable, generisee et FUSIONNABLE.

POURQUOI. `tools/forge_symptom_index.py` est publie dans le dist, sa memoire ne
l'est pas : `sandbox/enquetes_index.json` n'est meme pas suivi par git. Un
contributeur recoit donc un outil de memoire VIDE — il demandera « suis-je deja
passe par ce symptome ? » et recevra toujours « terrain neuf ». Or le depot a
mesure ce que coute cette absence : l'enquete ratee du 2026-07-26 a ete
ENTIEREMENT REFAITE le 29/07, trois hypotheses fausses et quatre redemarrages.

CE QUI EST PUBLIE, ET CE QUI NE L'EST PAS. On publie le couple
symptome -> pieges : c'est du savoir procedural, il vaut pour quiconque touche
ce code. On ne publie NI les transcripts, NI les chemins de la machine, NI les
identifiants de session bruts.

TROIS CHOIX DE FORMAT, dictes par un besoin BIDIRECTIONNEL — un contributeur lit
cette memoire, et renvoie la sienne dans sa PR :

  1. JSONL, UNE LIGNE PAR ENQUETE. Un JSON monolithique de 700 Ko produit un
     conflit de fusion des que deux personnes ajoutent une enquete. Ligne a
     ligne, git fusionne tout seul.
  2. TRI STABLE par clef. Sans lui, deux exports de la meme donnee produisent
     des diffs differents, et la revue devient illisible.
  3. CHAMP `origine`. En edge, N instances accumulent ; sans savoir QUI a
     observe quoi, on ne peut ni pondérer ni retirer une source douteuse.

FAIL-CLOSED. Si une donnee personnelle survit au filtre, on REFUSE d'ecrire.
Publier « presque propre » est pire que ne pas publier : ca se relit comme
verifie.

Usage :
    forge_enquetes_publier.py              (dry-run : dit ce qui sortirait)
    forge_enquetes_publier.py --apply
"""

from __future__ import annotations

__FORGE_COLOR__ = "memoire/enquete-partagee"

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "sandbox" / "enquetes_index.json"
# `docs/` est publie par le profil public ; `sandbox/` ne l'est pas.
CIBLE = ROOT / "docs" / "enquetes_partagees.jsonl"

# Regles COMPLEMENTAIRES a `forge_dist_publish.generiser_texte`, qui a ete ecrit
# pour du CODE (chemins de dev) et laisse passer ce qu'on trouve dans des
# TRANSCRIPTS. Mesure du 2026-09-19 sur l'index reel : apres ses 145
# substitutions, il restait 5 adresses mail, 2 adresses de loopback, 1 lettre de
# lecteur et 12 chemins de profil d'un AUTRE utilisateur.
_COMPLEMENT: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"[\w.+-]+@[\w-]+\.[a-z]{2,}", re.I), "<courriel>"),
    (re.compile(r"\b127\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"), "localhost"),
    (re.compile(r"\b(?:[A-Za-z]):[\\/]{1,2}Temp\b"), "%TEMP%"),
    # Toute lettre de lecteur locale hors C: — D:/ (travail), %NOKIDO_DATA%\ (donnees).
    # Mesure : apres les regles ci-dessus il en restait 6, et le controle
    # fail-closed a refuse la publication. C'est le garde qui a trouve la regle
    # manquante, pas moi.
    (re.compile(r"\b([D-Zd-z]):[\\/]{1,2}"), r"%LECTEUR%/"),
    # Tout profil Windows, pas seulement celui de l'owner.
    (re.compile(r"[Cc]:[\\/]{1,2}Users[\\/]{1,2}[A-Za-z0-9_.]+"), "%USERPROFILE%"),
)

# Ce qui ne doit JAMAIS subsister dans le fichier publie. Le controle est
# SEPARE des regles de remplacement : un filtre qui se verifie lui-meme ne
# prouve rien (il ne trouve que ce qu'il sait deja remplacer).
_INTERDITS: tuple[tuple[str, re.Pattern], ...] = (
    ("adresse de courriel", re.compile(r"[\w.+-]+@[\w-]+\.[a-z]{2,}", re.I)),
    ("chemin de profil Windows", re.compile(r"[Cc]:[\\/]{1,2}Users[\\/]{1,2}[A-Za-z0-9_.]+")),
    ("adresse IP privee", re.compile(r"\b(?:10|127|192\.168)\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")),
    ("lettre de lecteur locale", re.compile(r"\b[D-Zd-z]:[\\/]{1,2}[A-Za-z0-9_]")),
)


# Resolu UNE FOIS, au premier appel. Deux raisons, toutes deux mesurees le
# 2026-09-19 sur la premiere version de ce fichier :
#   - l'import etait retente a chaque piege, soit des milliers de fois ;
#   - son avertissement partait dans la boucle et a produit 198 Ko de sortie
#     identique. Un avertissement repete n'informe pas, il ENTERRE le resultat
#     (ici, le verdict de refus se lisait apres 2000 lignes de bruit).
_GENERISEUR: list = []


def _generiseur():
    """Rend la fonction de generisation du depot, ou None — et le dit UNE fois."""
    if _GENERISEUR:
        return _GENERISEUR[0]
    fn = None
    try:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from tools.forge_dist_publish import generiser_texte as _g
        fn = _g
    except Exception as e:  # noqa: BLE001
        print(f"[publier] AVERTISSEMENT : la generisation du dist est indisponible "
              f"({type(e).__name__}) — seules les regles complementaires "
              f"s'appliquent, la couverture est DONC PARTIELLE")
    _GENERISEUR.append(fn)
    return fn


def _generiser(txt: str) -> str:
    """Generisation du depot PUIS complement transcripts. On REUTILISE l'existant.

    L'ordre compte : les regles du depot sont les plus specifiques (chemin
    complet du projet), elles doivent mordre avant la regle generique de profil.
    """
    g = _generiseur()
    if g is not None:
        txt, _ = g(txt)
    for rx, repl in _COMPLEMENT:
        txt = rx.sub(repl, txt)
    return txt


def _lignes(index: dict) -> list[dict]:
    """Une enquete par ligne : symptome, pieges, provenance. Rien d'autre."""
    out = []
    for s in index.get("sessions") or []:
        pieges = [
            {"extrait": _generiser(str(p.get("extrait") or ""))[:400],
             "jetons": [str(j) for j in (p.get("jetons") or [])][:8]}
            for p in (s.get("pieges") or [])
        ]
        pieges = [p for p in pieges if p["extrait"].strip()]
        if not pieges:
            continue  # une enquete sans piege n'apprend rien
        out.append({
            # L'identifiant de session est un HASH court, pas la session brute :
            # il sert a dedupliquer et a fusionner, pas a retrouver un transcript.
            "enquete": str(s.get("session") or "")[:12],
            "date": str(s.get("date") or "")[:10],
            "jetons": sorted({str(j) for j in (s.get("jetons") or [])})[:12],
            "pieges": pieges,
            # Pour l'edge : qui a observe. Surchargeable par les instances.
            "origine": "nokido-amont",
        })
    # TRI STABLE : meme donnee -> meme fichier -> diff lisible.
    out.sort(key=lambda r: (r["date"], r["enquete"]))
    return out


def _residus(texte: str) -> list[str]:
    trouves = []
    for nom, rx in _INTERDITS:
        n = len(rx.findall(texte))
        if n:
            trouves.append(f"{nom} x{n}")
    return trouves


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--source", default=str(SOURCE))
    p.add_argument("--cible", default=str(CIBLE))
    a = p.parse_args()

    src = Path(a.source)
    if not src.is_file():
        print(f"[publier] source absente : {src}")
        return 2
    index = json.loads(src.read_text(encoding="utf-8"))
    lignes = _lignes(index)
    n_pieges = sum(len(r["pieges"]) for r in lignes)
    print(f"[publier] {len(index.get('sessions') or [])} session(s) lue(s) -> "
          f"{len(lignes)} enquete(s) porteuses, {n_pieges} piege(s)")

    corps = "\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in lignes)
    residus = _residus(corps)
    if residus:
        # FAIL-CLOSED : on ne publie pas « presque propre ».
        print(f"[publier] REFUS — donnees personnelles survivantes : {residus}")
        return 1
    print("[publier] controle : aucune donnee personnelle residuelle")

    if not a.apply:
        print(f"[publier] dry-run — --apply pour ecrire {a.cible}")
        return 0
    cible = Path(a.cible)
    cible.parent.mkdir(parents=True, exist_ok=True)
    cible.write_text(corps + "\n", encoding="utf-8")
    relu = cible.read_text(encoding="utf-8")
    if _residus(relu):
        print("[publier] ECHEC : residus detectes APRES ecriture")
        return 1
    print(f"[publier] ECRIT et RELU : {cible.relative_to(ROOT).as_posix()} "
          f"({len(relu)} octets, {len(lignes)} lignes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
