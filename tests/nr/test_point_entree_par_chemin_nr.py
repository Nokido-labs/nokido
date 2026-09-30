# -*- coding: utf-8 -*-
"""NR — un point d'entree lance PAR CHEMIN ABSOLU doit pouvoir importer `nokido_agent`.

Defaut mesure le 2026-09-11 : le hook SessionStart de Claude Code lance
`tools/forge_memory_compactor.py` par chemin absolu, et le module meurt a l'import :

    File "...\\tools\\forge_memory_compactor.py", line 24, in <module>
        from nokido_agent.tools.forge_archeo_socle import liens_memoire
    ModuleNotFoundError: No module named 'nokido_agent'

Le fichier PORTAIT deja l'amorce `sys.path` qui repare exactement ca — mais NEUF
LIGNES PLUS BAS que l'import qui en depend (commit a44b64df6, migration PyPI de la
famille `tools`). Le codemod a remonte l'import en tete des imports sans deplacer
l'amorce, que `forge_pypi_amorce._point_d_insertion` pose « apres le docstring et
les imports de tete ». AST valide, parse-check vert, execution morte a tous les coups.

Ce qui rend le defaut couteux, c'est son SILENCE : un hook SessionStart n'est pas
bloquant. Chaque session demarrait normalement pendant que le ledger memoire n'etait
plus synchronise, que `MEMORY.md` n'etait plus reingere (le lexical servait la
version d'avant) et qu'aucune compaction ne tournait.

Pourquoi le NR d'appui existant ne l'a PAS vu : `test_appui_forge_memory_compactor_nr`
insere lui-meme ROOT dans `sys.path` avant d'importer, et importe sous le nom PLAT
(`forge_memory_compactor`). Il FABRIQUE l'environnement qui manque au hook — il ne
pouvait donc que passer. Meme famille que la mesure du 2026-09-10 : un NR qui valide
le contraire de ce qu'il croit.

Deux tests, deux dimensions, volontairement :

  - COMPORTEMENT (`test_le_point_d_entree_se_lance_par_chemin`) : on execute le vrai
    chemin — subprocess, chemin absolu, `PYTHONPATH` retire, cwd neutre. C'est le mode
    qui a casse, donc c'est le mode qu'on mesure.
  - STRUCTURE (`test_l_amorce_precede_l_import_du_namespace`) : l'ordre des lignes.
    Il reste vrai le jour ou `nokido_agent` sera reellement INSTALLE (chantier PyPI) :
    ce jour-la le test de comportement passera meme sans amorce, donc il cessera de
    prouver quoi que ce soit. Le test structurel, lui, tiendra encore.

L'ordre se lit par AST, jamais par `"path.insert" in texte` : une mention dans un
commentaire ou une docstring n'est pas une structure (mesure du 2026-09-10).
"""
import ast
import os
import subprocess
import sys
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus python (l.140)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]

# Deux perimetres, parce que les deux tests n'ont pas le meme prix.
#
# CIBLES_HELP : lancement REEL. Reserve aux points d'entree qui ont un argparse,
# donc ou `--help` paie tous les imports de tete puis sort en 0 SANS executer la
# moindre logique metier. `forge_vitalite_inscrire` n'en a pas : `--help` y
# lancerait `main()`, qui ECRIT dans tests/nr/. Un NR ne declenche pas l'effet
# qu'il est cense surveiller.
#
# CIBLES_STRUCTURE : lecture AST seule, aucun lancement — donc ouvrable a tout
# point d'entree, argparse ou pas.
#
# 33 autres modules portent la meme inversion (mesure du 2026-09-11) ; ils demandent
# un tri (lance par chemin ? importe seulement ?) et non une correction en lot. Les
# ajouter ici sans ce tri fabriquerait des rouges sur des modules qui vont tres bien.
CIBLES_HELP = (
    "tools/forge_memory_compactor.py",
    # Casse MESUREE le 2026-09-12 en voulant simplement lire son `--help` :
    #     ModuleNotFoundError: No module named 'nokido_agent'
    # C'est le PILOTE DE CLOTURE U1 (commit 3739d3132) — il ne demarrait donc pas
    # par son point d'entree. Cause : son amorce insere `RACINE/app` et
    # `RACINE/tools` mais PAS `RACINE`, alors que la ligne suivante importe sous
    # la forme NAMESPACEE (`from nokido_agent.tools import ...`), qui exige la
    # racine. L'amorce servait la convention PLATE, le code utilisait l'autre.
    # Son voisin `forge_veille_u1_run.py` inserait bien ROOT, et s'importait :
    # deux lanceurs du meme chantier, deux conventions, un seul marchait.
    "tools/forge_veille_u1_boucle.py",
    # Casse MESUREE le 2026-09-26 par l'owner, prefixe `!` (cwd = superrepo) :
    #     forge_skill_sync.py --preview -> ModuleNotFoundError: No module named 'nokido_agent'
    # Aucune amorce du tout avant l'import L52 ; sa docstring demande pourtant ce lancement.
    "tools/forge_skill_sync.py",
)
CIBLES_STRUCTURE = (
    "tools/forge_memory_compactor.py",
    "tools/forge_veille_u1_boucle.py",
    "tools/forge_skill_sync.py",
    # Casse PROUVE le 2026-09-11, pas deduit : `trusted_script` le lance par chemin
    # en fin de CI pour inscrire le registre de vitalite (seul compte qui ecrit dans
    # tests/nr/) et il mourait en ModuleNotFoundError. Trouve par usage normal cinq
    # minutes apres le premier correctif — la meme inversion, un autre organe.
    "tools/forge_vitalite_inscrire.py",
    # Les HOOKS Claude Code qui importent le namespace (audit du 2026-09-11 : sur 17
    # hooks declares, ces 5 sont les seuls concernes ; les 12 autres n'importent pas
    # `nokido_agent`, l'inversion ne peut pas les atteindre). Ils sont TOUS lances par
    # chemin absolu, sans PYTHONPATH ni cwd du depot -- exactement le contexte qui a
    # tue le compacteur 24 h en SILENCE, puisqu'un hook non bloquant qui meurt laisse
    # la session demarrer normalement.
    #
    # Ils sont ici au perimetre STRUCTUREL seulement, jamais au perimetre `--help` :
    # `session_anchor` n'a meme pas de `__main__` et agit A L'IMPORT (ancre de fin de
    # session, relance de daemons). Un NR ne declenche pas l'effet qu'il surveille.
    "tools/claude_inbox_tick.py",
    "tools/claude_precompact.py",
    "tools/claude_session_start.py",
    "tools/session_anchor.py",
    # TRI fait le 2026-09-25 (epreuve « medecin ») : deux PRODUCTEURS D'EXAMENS du corps, lances
    # par chemin, morts a l'import -- la meme inversion (import L32/L27, amorce L38/L33, et
    # l'amorce n'inserait que app/ et tools/, pas la racine). `execution_trace` : lance par
    # forge_capability_freshness au circadien NREM1, ERREUR_OUTIL dans son artefact, produit
    # vieux de 359 h. `provider_reachability` : ModuleNotFoundError reproduit (sys.path[0]=tools/,
    # PYTHONPATH vide), examen « fournisseurs » fige depuis 28 jours. Pas d'argparse : un
    # `--help` lancerait main(), qui ECRIT l'examen -- perimetre STRUCTURE seulement.
    "tools/forge_capability_execution_trace.py",
    "tools/forge_provider_reachability.py",
)


def _env_sans_chemin_herite() -> dict:
    """Environnement d'un point d'entree lance par un TIERS (hook, tache planifiee).

    Un hook Claude Code ne passe ni `PYTHONPATH` ni cwd du depot. Herite-les du
    processus pytest et le test mesure l'environnement du testeur, pas celui du hook
    — c'est le defaut paye deux fois en une semaine (gate `anatomie` vert en local et
    rouge sur le runner, `modules_depot()` rendant 0 en CI de reference).
    """
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONPATH", "PYTHONUTF8", "PYTHONIOENCODING")}
    env["PYTHONNOUSERSITE"] = "1"  # un user-site qui porterait le paquet masquerait le defaut
    # Console de l'owner (prefixe `!`) : cp1252 strict. Le testeur herite PYTHONUTF8=1 et
    # PYTHONIOENCODING=utf-8 (mesure 2026-09-26) : forge_skill_sync passait `--help` ici et
    # mourait chez l'owner en UnicodeEncodeError sur un caractere de son aide hors cp1252.
    env["PYTHONIOENCODING"] = "cp1252"
    return env


def _lancer(chemin: Path, tmp_path: Path) -> subprocess.CompletedProcess:
    """`--help` : traverse `__main__` et argparse, n'execute AUCUNE logique metier.

    Le compacteur ECRIT (`MEMORY.md`, ledger, RAG) : un NR ne doit declencher aucun
    de ces chemins. `--help` sort en 0 apres avoir paye tous les imports de tete,
    c'est-a-dire exactement ce qu'on veut mesurer et rien d'autre.
    """
    return subprocess.run(
        [sys.executable, str(chemin), "--help"],
        cwd=str(tmp_path),  # cwd NEUTRE : depuis la racine du depot, l'import passerait
        env=_env_sans_chemin_herite(),
        # `errors="replace"` : sans lui, `text=True` decode en strict et le thread
        # lecteur de subprocess CRASHE sur une sortie non decodable — or c'est
        # justement une TRACEBACK qu'on lit ici, avec des chemins accentues sous une
        # console cp1252. Le NR mourrait alors sur le cas qu'il doit mesurer.
        capture_output=True, text=True, errors="replace", timeout=120,
    )


def test_le_point_d_entree_se_lance_par_chemin(tmp_path):
    echecs = []
    for rel in CIBLES_HELP:
        chemin = ROOT / rel
        assert chemin.exists(), "cible hors perimetre : %s" % rel
        p = _lancer(chemin, tmp_path)
        if p.returncode != 0 or "ModuleNotFoundError" in p.stderr:
            echecs.append("%s : rc=%s\n    %s"
                          % (rel, p.returncode, (p.stderr or "").strip()[-400:]))
    assert not echecs, (
        "point(s) d'entree qui mourront des qu'un hook ou une tache planifiee les "
        "lance par chemin :\n  " + "\n  ".join(echecs))


def _alias_de_sys(arbre: ast.Module) -> tuple:
    """Noms qui designent le module `sys`, et noms qui designent `sys.path` directement.

    On RESOUT l'alias au lieu de chercher la sous-chaine « sys » dans le nom de la
    variable. Mesure du 2026-09-11 : ce NR, premiere version, cherchait
    `"sys" in cible` — il voyait l'amorce reelle (alias `_sys_amorce`, qui contient
    « sys ») et ratait `import sys as _s`. Un garde qui depend de l'orthographe d'un
    alias est un faux negatif en attente ; c'est la forme exacte de « une mention n'est
    pas une structure » (2026-09-10). L'angle mort vit aussi dans
    `test_heartbeat_amorce_syspath_nr._mute_syspath`, a corriger a son tour.
    """
    mods, chemins = set(), set()
    for n in ast.walk(arbre):
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.name == "sys":
                    mods.add(a.asname or "sys")
        elif isinstance(n, ast.ImportFrom) and n.module == "sys":
            for a in n.names:
                if a.name == "path":
                    chemins.add(a.asname or "path")
    return mods, chemins


def _premieres_lignes(source: str) -> tuple:
    """(ligne de l'amorce sys.path, ligne du 1er import `nokido_agent`), au niveau MODULE.

    Niveau module SEULEMENT : une amorce enfouie dans une fonction ne s'execute pas a
    l'import, donc elle ne repare rien (leçon `test_heartbeat_amorce_syspath_nr`, ou
    `forge_docker_keeper` PORTAIT son insertion... dans une branche jamais atteinte).
    """
    arbre = ast.parse(source)
    mods, chemins = _alias_de_sys(arbre)
    corps = [n for n in arbre.body
             if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    amorce = importe = None
    for noeud in corps:
        for x in ast.walk(noeud):
            if amorce is None and isinstance(x, ast.Call):
                f = x.func
                if isinstance(f, ast.Attribute) and f.attr in ("insert", "append", "extend"):
                    cible = ast.unparse(f.value)
                    if cible in chemins or (cible.endswith(".path") and cible[:-5] in mods):
                        amorce = x.lineno
            if importe is None and isinstance(x, (ast.Import, ast.ImportFrom)):
                noms = ([a.name for a in x.names] if isinstance(x, ast.Import)
                        else [x.module or ""])
                if any(n.split(".")[0] == "nokido_agent" for n in noms):
                    importe = x.lineno
    return amorce, importe


def test_l_amorce_precede_l_import_du_namespace():
    fautifs = []
    for rel in CIBLES_STRUCTURE:
        amorce, importe = _premieres_lignes(
            (ROOT / rel).read_text(encoding="utf-8", errors="replace"))
        if importe is None:
            continue  # n'importe pas le namespace : l'amorce ne le concerne pas
        if amorce is None:
            fautifs.append("%s : importe nokido_agent (L%d) SANS amorce sys.path"
                           % (rel, importe))
        elif amorce > importe:
            fautifs.append("%s : amorce L%d APRES l'import L%d — inoperante"
                           % (rel, amorce, importe))
    assert not fautifs, "\n  ".join([""] + fautifs)


def test_une_amorce_posee_apres_l_import_est_bien_vue_comme_fautive():
    """Garde du garde : sans lui, le test structurel pourrait ne rien lire du tout.

    C'est la forme EXACTE du fichier tombe le 2026-09-11, mais ecrite avec l'alias
    COURT `_s` — deliberement : c'est ce cas qui a pris la premiere version de ce
    garde en defaut. Si ce test casse, le garde est redevenu aveugle et le prochain
    codemod repassera sans bruit.
    """
    src = ("from nokido_agent.tools.forge_archeo_socle import liens_memoire\n"
           "import sys as _s\n"
           "from pathlib import Path as _P\n"
           "_R = str(_P(__file__).resolve().parent.parent)\n"
           "if _R not in _s.path:\n"
           "    _s.path.insert(0, _R)\n")
    amorce, importe = _premieres_lignes(src)
    assert importe == 1 and amorce == 6, (amorce, importe)
    assert amorce > importe, "l'inversion payee n'est plus detectee"

    sain = ("import sys as _s\n"
            "from pathlib import Path as _P\n"
            "_R = str(_P(__file__).resolve().parent.parent)\n"
            "if _R not in _s.path:\n"
            "    _s.path.insert(0, _R)\n"
            "from nokido_agent.tools.forge_archeo_socle import liens_memoire\n")
    amorce, importe = _premieres_lignes(sain)
    assert amorce < importe, "la forme SAINE est declaree fautive (garde qui crie a faux)"
