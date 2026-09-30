"""tools/forge_generer_appui.py — genere les tests d'APPUI qui rendent le gain mesurable.

Chantier arrete par l'owner le 2026-09-08. Mesure de depart (tools/forge_couverture_perimetre) :
`perimetre non vide` = 448 / 2272 (19,7 %), donc 1824 modules sur lesquels
`juger_module_avec_gain` ne peut rendre que GAIN_INDECIDABLE — il n'a rien a jouer.

Un test d'APPUI n'est pas un test de comportement. Il importe le module et verifie
qu'il se charge. C'est peu, et c'est dit dans le fichier genere lui-meme. Mais ce peu
suffit a deux choses :
  - donner au gain gate un perimetre a mesurer (baseline vs candidat) ;
  - attraper la classe d'erreurs la plus frequente sur un chemin jamais execute —
    NameError et ImportError, exactement ce qui a fait mourir `ci_local` en pleine
    fermeture le jour meme ou ce fichier a ete ecrit.

TROIS GARDES, chacun paye ailleurs dans ce depot :

  1. Le test genere PORTE UN MARQUEUR (`GENERE-APPUI`). Il compte pour `perimetre non
     vide`, JAMAIS pour `couverture prouvee`. Fusionner les deux ferait passer la
     couverture a ~100 % en une nuit sans que rien ne soit mieux teste : Goodhart sur
     la metrique meme que la veille designe comme la plus dangereuse pour un systeme
     qui s'auto-mesure.
  2. On ne genere QUE pour un module qui s'importe VRAIMENT, sonde en SOUS-PROCESSUS.
     Importer a des effets de bord ici : lecture du coffre a l'import, WORKSPACE_GUARD
     sur la pile torch (la reassignation de `sys.stdout` a l'import a ete deplacee dans
     `__main__` le 2026-09-29). Generer a l'aveugle casserait la suite pure.
  3. Un module non importable est NOMME avec son motif. C'est une MESURE, pas un
     dechet : un module du corps qui ne s'importe pas est deja une pathologie.

Usage :
  run action=run_job script=tools/forge_generer_appui.py script_args="--limit 30"
  (ajouter --apply pour ecrire ; sans lui, dry-run qui nomme ce qu'il ferait)
"""

from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/appui : genere les tests qui rendent le gain mesurable"

import argparse
import concurrent.futures as cf
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))

MARQUEUR = "GENERE-APPUI"
PY = sys.executable

# Memoire des modules qui n'ont PAS pu etre instrumentes. Sans elle, l'ordre de la
# liste etant stable, les memes reviennent en TETE de chaque lot et se font re-sonder
# indefiniment — piege deja paye sur le backfill de veille (`veille_backfill_ignorees`).
# Mesure du 2026-09-08 : quatre modules re-sondes a chaque lot, dont un import de 9 s.
IGNOREES = ROOT / "sandbox" / "appui_non_importables.json"
TTL_IGNOREES_S = 7 * 24 * 3600


def _fichier_ignorees(racine=None) -> Path:
    """La memoire SUIT la racine. Sans ca elle ecrit dans le sandbox REEL meme quand
    l'appelant travaille en tmp_path : un test polluait alors le suivant (mesure
    2026-09-08, attrapee par le NR). Un etat global qui ignore la racine injectee
    n'est pas isolable."""
    return (Path(racine) / "sandbox" / "appui_non_importables.json") if racine else IGNOREES


def _ignorees_vivantes(chemin=None) -> dict:
    """Modules ecartes recemment. Un fichier illisible est DIT, pas avale."""
    p = Path(chemin) if chemin is not None else IGNOREES
    if not p.exists():
        return {}
    try:
        brut = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        print("[appui] memoire des ignorees ILLISIBLE (%s) — tout sera re-sonde"
              % type(e).__name__, flush=True)
        return {}
    maintenant = time.time()
    return {k: v for k, v in brut.items()
            if isinstance(v, dict) and maintenant - float(v.get("ts", 0)) < TTL_IGNOREES_S}


def _noter_ignorees(nouvelles: dict, chemin=None) -> None:
    p = Path(chemin) if chemin is not None else IGNOREES
    memoire = _ignorees_vivantes(p)
    ts = time.time()
    for rel, motif in nouvelles.items():
        memoire[rel] = {"motif": motif[:300], "ts": ts}
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(memoire, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as e:
        print("[appui] memoire des ignorees NON ecrite (%s) — elles reviendront"
              % type(e).__name__, flush=True)


def chemin_test_appui(rel: str) -> str:
    stem = str(rel).replace("\\", "/").rsplit("/", 1)[-1]
    stem = stem[:-3] if stem.endswith(".py") else stem
    return "tests/nr/test_appui_%s_nr.py" % stem


_DEP_ABSENTE = re.compile(r"ModuleNotFoundError: No module named ['\"]([\w.]+)['\"]")


def dependance_tierce_absente(motif: str, racine=None) -> str | None:
    """Le module echoue-t-il faute d'une dependance TIERCE, ou est-il casse ?

    Distinction posee le 2026-09-08 : `zmq` absent de l'environnement n'est pas un
    module casse, c'est un environnement INCOMPLET — UNKNOWN, pas NO. Le faire
    echouer accuserait le module a tort ; ne rien generer le laisserait sans
    perimetre. Il SKIP, en nommant la dependance.

    Un nom qui correspond a un fichier du DEPOT n'est pas tiers : la, c'est bien un
    defaut de chaine d'imports, et aucun test n'est genere.
    """
    m = _DEP_ABSENTE.search(motif or "")
    if not m:
        return None
    nom = m.group(1).split(".")[0]
    r = Path(racine) if racine is not None else ROOT
    for d in ("app", "tools"):
        if (r / d / (nom + ".py")).is_file() or (r / d / nom).is_dir():
            return None  # module du depot : defaut reel, pas une dependance tierce
    return nom


def contenu_test_appui(rel: str, dep_absente: str | None = None) -> str:
    r = str(rel).replace("\\", "/")
    stem = r.rsplit("/", 1)[-1][:-3]
    if dep_absente:
        return (
            '# -*- coding: utf-8 -*-\n'
            '"""Test d\'APPUI %s — genere, pas ecrit.\n'
            '\n'
            'Couvre `%s`. TROISIEME ETAT : ce module importe `%s`, ABSENT de cet\n'
            'environnement. Le module n\'est pas casse, l\'environnement est incomplet —\n'
            'UNKNOWN, pas NO. Echouer accuserait le module a tort, passer mentirait :\n'
            'il SKIP en nommant ce qui manque.\n'
            '"""\n'
            '\n'
            'import importlib\n'
            'import sys\n'
            'from pathlib import Path\n'
            '\n'
            'import pytest\n'
            '\n'
            'ROOT = Path(__file__).resolve().parents[2]\n'
            'for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):\n'
            '    if _p not in sys.path:\n'
            '        sys.path.insert(0, _p)\n'
            '\n'
            '\n'
            'def test_le_module_se_charge():\n'
            '    pytest.importorskip("%s", reason="dependance TIERCE absente de cet "\n'
            '                        "environnement : le module n\'est pas en cause")\n'
            '    assert importlib.import_module("%s") is not None\n'
        ) % (MARQUEUR, r, dep_absente, dep_absente, stem)
    return (
        '# -*- coding: utf-8 -*-\n'
        '"""Test d\'APPUI %s — genere, pas ecrit.\n'
        '\n'
        'Couvre `%s`. Il verifie que le module se CHARGE, rien de plus.\n'
        '\n'
        'Ce qu\'il apporte : un perimetre de mesure, sans lequel `juger_module_avec_gain`\n'
        'ne peut rendre que GAIN_INDECIDABLE sur ce module ; et la detection des erreurs\n'
        'de chargement (NameError, ImportError) sur un chemin que personne n\'execute.\n'
        '\n'
        'Ce qu\'il NE prouve PAS : aucun comportement. Il ne compte donc jamais dans la\n'
        'metrique `couverture prouvee` — le marqueur en tete sert exactement a l\'en\n'
        'exclure. Le remplacer par un vrai test de comportement est un progres ; le\n'
        'supprimer sans le remplacer rend le module non mesurable.\n'
        '"""\n'
        '\n'
        'import importlib\n'
        'import sys\n'
        'from pathlib import Path\n'
        '\n'
        'ROOT = Path(__file__).resolve().parents[2]\n'
        'for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):\n'
        '    if _p not in sys.path:\n'
        '        sys.path.insert(0, _p)\n'
        '\n'
        '\n'
        'def test_le_module_se_charge():\n'
        '    assert importlib.import_module("%s") is not None\n'
    ) % (MARQUEUR, r, stem)


def sonder_import(rel: str, racine=None) -> tuple[bool, str]:
    """L'import se fait-il, VRAIMENT ? En SOUS-PROCESSUS : les effets de bord restent dehors."""
    r = Path(racine) if racine is not None else ROOT
    stem = str(rel).replace("\\", "/").rsplit("/", 1)[-1][:-3]
    # La RACINE doit etre au chemin, pas seulement app/ et tools/ : beaucoup de modules
    # font `from app.x import y`. Sans elle la sonde rend « ModuleNotFoundError: No
    # module named 'app' » et classe comme CASSE un module qui va tres bien — mesure du
    # 2026-09-08 : 4 faux negatifs sur un lot pilote de 20. Le chemin de la sonde doit
    # etre EXACTEMENT celui du test genere, sinon les deux ne mesurent pas la meme chose.
    code = (
        "import sys;"
        "sys.path.insert(0, r'%s');"
        "sys.path.insert(0, r'%s');"
        "sys.path.insert(0, r'%s');"
        "import importlib; importlib.import_module('%s')"
    ) % (str(r / "tools"), str(r / "app"), str(r), stem)
    try:
        p = subprocess.run([PY, "-c", code], capture_output=True, text=True, timeout=60,
                           errors="replace", env={**os.environ, "PYTHONNOUSERSITE": "1"})
    except subprocess.TimeoutExpired:
        return False, "TimeoutExpired: l'import ne rend pas la main en 60 s"
    except Exception as e:  # noqa: BLE001 — la sonde ne doit jamais tuer la campagne
        return False, "%s: %s" % (type(e).__name__, str(e)[:200])
    if p.returncode == 0:
        return True, ""
    err = (p.stderr or "").strip().splitlines()
    return False, (err[-1][:300] if err else "rc=%d sans message" % p.returncode)


def valider_test(chemin: str, racine=None) -> tuple[bool, str]:
    """Le test genere PASSE-T-IL vraiment, la ou il tournera ?

    La sonde ne suffit pas. Mesure du 2026-09-08 : elle a tourne sous un compte
    privilegie et le test sous celui de la CI ; `app/brain_ping.py` s'importait pour
    l'une et pas pour l'autre (`No module named 'zmq'`), et un test ROUGE est parti
    dans la suite pure. Deux environnements, deux verdicts — seul le test JOUE fait foi.
    """
    r = Path(racine) if racine is not None else ROOT
    try:
        p = subprocess.run([PY, "-m", "pytest", str(r / chemin), "-q", "--no-header",
                            "-p", "no:cacheprovider"],
                           capture_output=True, text=True, timeout=120, cwd=str(r),
                           errors="replace", env={**os.environ, "PYTHONNOUSERSITE": "1"})
    except Exception as e:  # noqa: BLE001
        return False, "%s: %s" % (type(e).__name__, str(e)[:200])
    if p.returncode == 0:
        return True, ""
    lignes = [x for x in (p.stdout or "").splitlines() if x.startswith("E ")]
    return False, (lignes[-1][:300] if lignes else "pytest rc=%d" % p.returncode)


def generer(rels, racine=None, sonde=None, appliquer: bool = False, valider=None,
            redo: bool = False, workers: int = 6) -> dict:
    """Genere pour les modules donnes. Rend un rapport qui porte son denominateur.

    Deux filtres, et le second est le juge : la SONDE ecarte ce qui ne s'importe pas,
    la VALIDATION ecarte ce qui ne passe pas une fois ecrit — un test genere rouge est
    pire que pas de test, il rougit la suite de tout le monde.
    """
    r = Path(racine) if racine is not None else ROOT
    sonde = sonde or sonder_import
    valider = valider or valider_test
    from nokido_agent.app.forge_mutation_judge import perimetre_mesure

    connues = {} if redo else _ignorees_vivantes(_fichier_ignorees(r))
    ecrits, deja, non_imp, sautes = [], [], {}, []

    a_traiter = []
    for rel in rels:
        rel = str(rel).replace("\\", "/")
        if rel in connues:
            sautes.append(rel)
        elif perimetre_mesure(rel, racine=r):
            deja.append(rel)
        else:
            a_traiter.append(rel)

    def _un(rel):
        """Sonde, ecrit, valide UN module. Chaque cible a son propre fichier :
        aucun etat partage, donc parallelisable sans verrou."""
        ok, motif = sonde(rel, r)
        dep = None if ok else dependance_tierce_absente(motif, r)
        if not ok and not dep:
            return rel, None, motif
        cible = chemin_test_appui(rel)
        if not appliquer:
            return rel, cible, None
        p = r / cible
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(contenu_test_appui(rel, dep), encoding="utf-8")
        ok_test, motif_test = valider(cible, r)
        if not ok_test:
            try:
                p.unlink()
            except OSError:
                pass
            return rel, None, motif_test
        return rel, cible, None

    # PARALLELE : sonde et validation sont deux SOUS-PROCESSUS par module, donc de
    # l'attente d'I/O — les enchainer en serie laissait le processeur inoccupe.
    # Meme patron que `forge_veille_backfill --workers`. Les resultats sont ensuite
    # ORDONNES sur `a_traiter` : le parallelisme ne doit pas rendre la sortie instable.
    resultats = {}
    if a_traiter:
        with cf.ThreadPoolExecutor(max_workers=max(1, int(workers))) as ex:
            for rel, cible, motif in ex.map(_un, a_traiter):
                resultats[rel] = (cible, motif)
    for rel in a_traiter:
        cible, motif = resultats.get(rel, (None, "non traite"))
        if cible:
            ecrits.append(cible)
        else:
            non_imp[rel] = motif
    if non_imp and appliquer:
        _noter_ignorees(non_imp, _fichier_ignorees(r))
    return {"vus": len(rels), "ecrits": ecrits, "deja_couverts": deja,
            "non_importables": non_imp, "sautes_deja_connus": sautes}


def synchroniser_socle(racine=None, appliquer: bool = False) -> dict:
    """Inscrit les tests d'APPUI presents dans `_socle_suite_pure.json`.

    C'est la responsabilite du GENERATEUR : il cree des NR qui ne sont pas dans la
    suite pure, et le cliquet `test_suite_pure_ratchet_nr` exige que tout NR hors
    suite soit soit inscrit au socle, soit ajoute a PURE_TESTS. Le laisser a un geste
    manuel garantit une CI rouge entre la generation et l'inscription — mesure du
    2026-09-08, paye deux fois.

    Retire aussi du socle les appuis qui n'existent plus (nettoyes) : un socle qui
    accumule des noms morts ne dit plus ce qu'il couvre.
    """
    r = Path(racine) if racine is not None else ROOT
    socle_p = r / "tests" / "nr" / "_socle_suite_pure.json"
    if not socle_p.exists():
        return {"ok": False, "motif": "socle introuvable : %s" % socle_p}
    try:
        socle = json.loads(socle_p.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "motif": "socle ILLISIBLE (%s) — on n'ecrase pas l'illisible"
                                      % type(e).__name__}
    presents = sorted(p.name for p in (r / "tests" / "nr").glob("test_appui_*_nr.py"))
    anciens = [f for f in socle.get("fichiers", []) if not f.startswith("test_appui_")]
    morts = [f for f in socle.get("fichiers", [])
             if f.startswith("test_appui_") and f not in presents]
    ajoutes = [f for f in presents if f not in socle.get("fichiers", [])]
    socle["fichiers"] = sorted(anciens + presents)
    if appliquer:
        socle_p.write_text(json.dumps(socle, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"ok": True, "appuis": len(presents), "ajoutes": len(ajoutes),
            "morts_retires": len(morts), "total": len(socle["fichiers"])}


def nettoyer(racine=None, appliquer: bool = False, valider=None) -> dict:
    """Rejoue les tests d'APPUI existants et retire ceux qui sont rouges.

    Un test d'appui n'est utile que s'il passe : rouge, il rougit la suite de tout le
    monde pour un module qu'il ne protege pas. Cette passe existe parce qu'un test peut
    devenir rouge APRES coup — une dependance retiree de l'environnement, un module
    modifie — et parce que la sonde peut s'etre trompee (comptes differents, 2026-09-08).
    """
    r = Path(racine) if racine is not None else ROOT
    valider = valider or valider_test
    base = r / "tests" / "nr"
    retires, gardes = {}, []
    if not base.is_dir():
        return {"retires": retires, "gardes": gardes}
    for p in sorted(base.glob("test_appui_*_nr.py")):
        rel = str(p.relative_to(r)).replace("\\", "/")
        ok, motif = valider(rel, r)
        if ok:
            gardes.append(rel)
            continue
        if appliquer:
            try:
                p.unlink()
            except OSError as e:
                retires[rel] = "SUPPRESSION REFUSEE (%s) — %s" % (type(e).__name__, motif)
                continue
        retires[rel] = motif
    return {"retires": retires, "gardes": gardes}


def main() -> int:
    ap = argparse.ArgumentParser(prog="forge_generer_appui")
    ap.add_argument("--limit", type=int, default=30, help="modules par lot (defaut 30)")
    ap.add_argument("--apply", action="store_true", help="ecrire (defaut: dry-run)")
    ap.add_argument("--nettoyer", action="store_true",
                    help="rejoue les tests d'appui existants et retire les rouges")
    ap.add_argument("--redo", action="store_true",
                    help="re-sonde meme les modules deja notes non importables")
    ap.add_argument("--workers", type=int, default=6,
                    help="sondes/validations en parallele (defaut 6, travail I/O)")
    a = ap.parse_args()

    if a.nettoyer:
        n = nettoyer(appliquer=a.apply)
        print("[appui] nettoyage : %d garde(s), %d retire(s)%s"
              % (len(n["gardes"]), len(n["retires"]), "" if a.apply else " (DRY-RUN)"))
        for rel, motif in n["retires"].items():
            print("   RETIRE %s -> %s" % (rel, motif[:160]))
        return 0

    from nokido_agent.tools.forge_couverture_perimetre import mesurer_couverture

    cible = mesurer_couverture()["sans_perimetre"]
    lot = cible[: max(0, a.limit)]
    print("[appui] %d modules sans perimetre ; lot de %d%s"
          % (len(cible), len(lot), "" if a.apply else " (DRY-RUN)"), flush=True)
    r = generer(lot, appliquer=a.apply, redo=a.redo, workers=a.workers)
    print("[appui] ecrits: %d · deja couverts: %d · NON IMPORTABLES: %d · "
          "sautes (deja connus): %d"
          % (len(r["ecrits"]), len(r["deja_couverts"]), len(r["non_importables"]),
             len(r.get("sautes_deja_connus", []))))
    for rel, motif in list(r["non_importables"].items())[:15]:
        print("   KO %s -> %s" % (rel, motif[:150]))
    if len(r["non_importables"]) > 15:
        print("   ... %d autres NON affiches (tous dans le rapport)"
              % (len(r["non_importables"]) - 15))
    _s = synchroniser_socle(appliquer=a.apply)
    if _s.get("ok"):
        print("[appui] socle : %d appui(s) inscrit(s) (+%d, -%d morts), %d entrees"
              % (_s["appuis"], _s["ajoutes"], _s["morts_retires"], _s["total"]))
    else:
        print("[appui] socle NON synchronise : %s" % _s.get("motif"))

    sortie = ROOT / "sandbox" / "appui_generation.json"
    try:
        sortie.parent.mkdir(parents=True, exist_ok=True)
        sortie.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
        print("[appui] rapport : %s" % sortie)
    except OSError as e:
        print("[appui] rapport NON ecrit (%s) — la mesure ci-dessus reste valide" % type(e).__name__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
