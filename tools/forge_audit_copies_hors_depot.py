"""Audit des EXECUTABLES hors depot — ce que `C:\\tmp` peut piloter en silence.

Demande owner du 2026-09-04 : « une copie figee dans C:\\tmp, il faut auditer, c'est
grave, surtout que je n'en voulais plus ».

POURQUOI C'EST GRAVE. Un script lance depuis un chemin hors depot echappe a TOUS les
gardes du projet a la fois : il n'est pas dans git (donc ni revu, ni versionne, ni
couvert par la CI), le git-gate ne le scanne pas, le gate d'egress ne le voit pas, et
`trusted_script` — qui refuse justement un fichier non suivi par git, au motif que
« privilege = code revu » — ne s'applique pas non plus. Le code qu'on relit et le code
qui s'execute divergent sans que rien ne le signale.

MESURE FONDATRICE (RULES_SHARED, 2026-07-30). `forge_local_pool_wake` lancait
`C:/tmp/wake_llama_native.py` (4 722 o, date du 18 juin) alors que le depot en portait
une version de 11 825 o (26 juillet) : SIX SEMAINES d'ecart. La copie etait ANTERIEURE
au mecanisme d'intention, donc elle allumait un cerveau que la regulation evincait
aussitot. Ce reveilleur a ete corrige depuis ; l'audit du 2026-09-04 a trouve que
`forge_backend_power` pointe TOUJOURS sur cette meme copie.

CE QUE CET OUTIL SEPARE, et pourquoi. Les 248 references a `C:\\tmp` dans le depot ne
sont pas equivalentes :

  EXECUTION  un script (.py/.bat/.ps1/.cmd/.exe) est LANCE depuis C:\\tmp   -> GRAVE
  DONNEES    C:\\tmp sert de repertoire de travail, cache, artefacts        -> normal
  COMMENTAIRE une mention documentaire, souvent le recit d'un incident      -> inerte

Confondre les trois noierait le danger reel dans du bruit. Seule la premiere categorie
justifie une alerte, et pour chacune on cherche le JUMEAU au depot afin de dire si la
copie est perimee, identique, ou sans equivalent connu.

TROIS ETATS, JAMAIS DEUX. Le compte qui execute peut ne pas voir `C:\\tmp` : une
absence de fichier y est alors ILLISIBLE, pas ABSENT. L'outil imprime son denominateur
(fichiers lus / illisibles) et ne conclut jamais d'un silence.

NE SUPPRIME RIEN, ne propose aucune suppression : il SIGNALE. La regle du projet est
que rien ne s'efface, et le capteur ne voit ni les taches planifiees ni les lanceurs
de boot du profil owner.

Usage :
    LAFORGE_PYTHON tools/forge_audit_copies_hors_depot.py
    LAFORGE_PYTHON tools/forge_audit_copies_hors_depot.py --json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).resolve().parent.parent

# Racines hors depot a auditer. `C:\tmp` est la principale (mesure du 2026-07-30),
# mais un chemin hors depot reste hors depot quel que soit son nom OU SON VOLUME —
# `D:\Temp` compris, qui heberge notamment les scratchpads de session des agents.
# Un script de travail y est legitime ; un module du DEPOT qui en LANCE un ne l'est
# pas, et c'est cette asymetrie que l'outil mesure.
RACINES_HORS_DEPOT = (Path("C:/tmp"), Path("C:/temp"),
                      Path("D:/temp"), Path("D:/tmp"))

EXT_EXECUTABLES = (".py", ".bat", ".cmd", ".ps1", ".sh", ".exe", ".ts", ".js")
EXT_SOURCES = (".py", ".ts", ".toml", ".json", ".bat", ".ps1", ".cmd", ".yml", ".yaml")

# Reference a un chemin sous une racine temporaire, sur N'IMPORTE QUEL VOLUME et
# quelle que soit la forme d'echappement. Ne pas coder `C:` en dur : la premiere
# version le faisait et serait passee a cote de `D:\Temp` — un audit qui ne regarde
# qu'un volume rend un « 0 trouve » qui se lit comme « rien a signaler ».
# `re.I` est INDISPENSABLE et a ete perdu une fois en reecrivant ce motif : sans lui,
# `D:\Temp` (T majuscule, la forme reelle sur ce poste) n'etait PAS detecte, et le
# scan de code aurait rendu « 0 reference » sur le volume qu'on venait justement de
# demander d'auditer. Un audit insensible a la casse d'un cote et pas de l'autre
# fabrique un silence rassurant. Le garde `test_le_motif_couvre_tous_les_volumes`
# l'a attrape immediatement — c'est pour ce genre d'oubli qu'il existe.
_REF = re.compile(
    r"""["']?(?P<chemin>[A-Za-z]:[\\/]{1,2}te?mp[\\/]{1,2}[^"'\s,;)\]]+)""", re.I)

# Un lancement : le chemin apparait dans un contexte d'EXECUTION, pas de lecture.
_CONTEXTE_EXEC = re.compile(
    r"Popen|subprocess|run\(|call\(|check_output|startfile|os\.system|"
    r"ShellExecute|cmd\s*/c|powershell|LAFORGE_PYTHON|sys\.executable|\bPY\b",
    re.I)


_INDEX_DEPOT: dict | None = None


def _index_depot() -> dict:
    """{nom_de_fichier: [chemins]} du depot, construit UNE SEULE FOIS.

    La premiere version appelait `ROOT.rglob(nom)` pour CHAQUE executable a
    confronter, soit un balayage complet du depot par fichier teste — le meme motif
    de re-scan que celui corrige ailleurs dans la session (jointure FTS5, dedup par
    expression). Un index construit en une passe rend chaque recherche O(1).
    """
    global _INDEX_DEPOT
    if _INDEX_DEPOT is not None:
        return _INDEX_DEPOT
    # ELAGUER AVANT DE DESCENDRE, et non filtrer apres. `rglob("*")` traverse
    # l'integralite de l'arbre — `sandbox/` (plusieurs Go d'artefacts, de bases et de
    # journaux), `RAG/`, `.git/` — puis jette 99 % de ce qu'il a lu : mesure du
    # 2026-09-04, 13,3 Mo/s d'I/O soutenue pendant plus de cinq minutes pour indexer
    # quelques milliers de scripts. `os.walk` permet de couper les branches lourdes
    # AVANT d'y entrer, en modifiant `dirs` sur place. Meme famille que « ne jamais
    # charger le contenu pour decider de sa pertinence quand un champ etroit suffit ».
    import os as _os  # noqa: PLC0415

    ignores = {"sandbox", "_attic", "node_modules", ".git", "RAG", "__pycache__",
               ".venv", "venv", "dist", "build", ".pytest_cache", "logs"}
    idx: dict = {}
    for racine, dirs, fichiers in _os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in ignores]
        for nom in fichiers:
            if nom.lower().endswith(EXT_EXECUTABLES):
                idx.setdefault(nom, []).append(Path(racine) / nom)
    _INDEX_DEPOT = idx
    return idx


def _sha(p: Path) -> str | None:
    """Empreinte d'un fichier — DELEGUEE a `forge_code_identity.snapshot()`.

    Ce module existe deja et traite la MEME famille de question : « le code sur le
    disque est-il celui qui s'execute ? » (mesure 2026-08-02 : apres un revert, le
    keeper publiait encore `daemon_up: true` parce qu'il executait l'ancien code
    charge en memoire). Ici on compare un artefact hors depot a son jumeau versionne
    — c'est le meme invariant vu d'un autre angle, donc la meme empreinte.

    Le cliquet de duplication a signale ce clone des le premier commit : il avait
    raison, la fonction etait copiee a l'identique. Repli local uniquement si le
    module est indisponible, et l'echec rend None (jamais une empreinte fausse).
    """
    try:
        from nokido_agent.tools.forge_code_identity import snapshot as _snap  # noqa: PLC0415

        return _snap(str(p))
    except Exception:
        try:
            return hashlib.sha256(p.read_bytes()).hexdigest()[:12]
        except Exception:
            return None


MARQUEUR_REPLI = "repli-hors-depot-ok"


def lignes_de_docstring(src: str) -> set:
    """Numeros de lignes couverts par une docstring (module, classe, fonction).

    POURQUOI. Le filtre de commentaires ne reconnaissait que `#`, `//` et `*`.
    Une reference citee DANS une docstring -- un exemple d'usage, la provenance
    d'un artefact, le recit d'un incident -- etait donc classee « LANCE ».
    TROIS des cinq faux positifs du 2026-09-14 venaient de la
    (`forge_vendor_place` documente son usage CLI, `forge_module_census` cite la
    provenance d'une carte, `forge_pty_widget` mentionne un PoC valide).
    Une citation n'est pas une execution.

    Un fichier non parsable n'ecarte RIEN : on ne devine pas, et un doute se
    range du cote du signalement, jamais du silence.
    """
    import ast
    try:
        arbre = ast.parse(src)
    except SyntaxError:
        return set()
    lignes: set = set()
    porteurs = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, porteurs):
            continue
        corps = getattr(noeud, "body", None)
        if not corps:
            continue
        prem = corps[0]
        if (isinstance(prem, ast.Expr) and isinstance(prem.value, ast.Constant)
                and isinstance(prem.value.value, str)):
            lignes.update(range(prem.lineno, (prem.end_lineno or prem.lineno) + 1))
    return lignes


def repli_declare(ligne: str) -> bool:
    """Un repli LEGITIME se DECLARE, comme `# muet-ok` pour un chemin d'erreur.

    Le depot d'abord, la copie hors depot en dernier recours, et elle le DIT --
    c'est la forme que RULES_SHARED exige deja. Deux modules la respectaient
    (`forge_local_pool_wake` essaie le depot puis nomme la copie dans son retour ;
    `forge_ui_vitals_cover` replie son ECRITURE quand le compte sandbox ne peut
    pas ecrire dans le depot, et journalise la cause) -- et l'audit les accusait
    tout de meme. On reutilise le patron du depot plutot que d'inventer une
    seconde convention que personne ne connaitrait.
    """
    return MARQUEUR_REPLI in (ligne or "")


def code_de_sortie(executions) -> int:
    """1 si une EXECUTION averee subsiste, 0 sinon.

    L'outil rendait TOUJOURS 0 : cable comme gate, il n'aurait rien garde --
    c'est la « dette de cablage » deja consignee, un mecanisme sans effet
    observable n'est pas une securite. Les references seulement CITEES ne
    comptent pas : elles sont suspectes, pas prouvees, et un gate qui rougit sur
    un soupcon se fait desarmer.
    """
    return 1 if any(e.get("certitude") == "LANCE" for e in executions) else 0


def scanner_references() -> dict:
    """Toute reference a un chemin hors depot, classee par NATURE.

    Rend aussi le denominateur : sans lui, « 0 execution trouvee » ne se distingue
    pas de « je n'ai pas pu lire les fichiers ».
    """
    executions: list[dict] = []
    donnees = 0
    commentaires = 0
    declares = 0
    lus = 0
    illisibles: list[str] = []

    for dossier in ("app", "tools", "proxy_deno", ".github", "config"):
        base = ROOT / dossier
        if not base.is_dir():
            continue
        for f in base.rglob("*"):
            if f.suffix.lower() not in EXT_SOURCES:
                continue
            if "_attic" in f.parts or "node_modules" in f.parts:
                continue
            try:
                src = f.read_text(encoding="utf-8", errors="strict")
            except Exception as exc:
                illisibles.append("%s (%s)" % (f.relative_to(ROOT), type(exc).__name__))
                continue
            lus += 1
            doc = lignes_de_docstring(src) if f.suffix.lower() == ".py" else set()
            for num, ligne in enumerate(src.split("\n"), 1):
                m = _REF.search(ligne)
                if not m:
                    continue
                nu = ligne.strip()
                if nu.startswith("#") or nu.startswith("//") or nu.startswith("*"):
                    commentaires += 1
                    continue
                if num in doc:
                    commentaires += 1
                    continue
                if repli_declare(ligne):
                    declares += 1
                    continue
                chemin = m.group("chemin").replace("\\\\", "/").replace("\\", "/")
                if not chemin.lower().endswith(EXT_EXECUTABLES):
                    donnees += 1
                    continue
                if not _CONTEXTE_EXEC.search(ligne):
                    # Un chemin d'executable cite hors contexte d'execution reste
                    # suspect (il peut etre passe a une variable), mais il n'est pas
                    # une preuve de lancement : on le dit au lieu de le classer.
                    executions.append({"fichier": str(f.relative_to(ROOT)),
                                       "ligne": num, "chemin": chemin,
                                       "certitude": "cite (contexte d'execution non vu)",
                                       "extrait": nu[:120]})
                    continue
                executions.append({"fichier": str(f.relative_to(ROOT)), "ligne": num,
                                   "chemin": chemin, "certitude": "LANCE",
                                   "extrait": nu[:120]})
    return {"executions": executions, "n_donnees": donnees,
            "n_commentaires": commentaires, "n_replis_declares": declares,
            "fichiers_lus": lus, "illisibles": illisibles}


def confronter(chemin: str) -> dict:
    """La copie existe-t-elle, et que vaut-elle face a son jumeau du depot ?"""
    p = Path(chemin)
    out: dict = {"chemin": chemin}
    try:
        existe = p.exists()
    except OSError as exc:
        out["etat"] = "ILLISIBLE (%s)" % type(exc).__name__
        return out
    if not existe:
        # ABSENT n'est pas rassurant en soi : un lanceur qui pointe un fichier
        # inexistant echoue silencieusement si personne ne verifie son code retour.
        out["etat"] = "ABSENT du disque — le lanceur pointe dans le vide"
        return out
    try:
        st = p.stat()
        out["taille"] = st.st_size
        out["age_j"] = round((time.time() - st.st_mtime) / 86400, 1)
        out["sha"] = _sha(p)
    except OSError as exc:
        out["etat"] = "ILLISIBLE (%s)" % type(exc).__name__
        return out

    jumeaux = _index_depot().get(p.name, [])
    if not jumeaux:
        out["etat"] = "HORS DEPOT SANS JUMEAU — aucun equivalent versionne connu"
        return out
    j = jumeaux[0]
    try:
        js, jt = j.stat().st_size, j.stat().st_mtime
    except OSError:
        out["etat"] = "jumeau ILLISIBLE"
        return out
    out["jumeau"] = str(j.relative_to(ROOT))
    out["jumeau_taille"] = js
    out["jumeau_age_j"] = round((time.time() - jt) / 86400, 1)
    out["jumeau_sha"] = _sha(j)
    if out.get("sha") and out["sha"] == out["jumeau_sha"]:
        out["etat"] = "IDENTIQUE au depot (copie inutile mais inoffensive)"
    else:
        ecart = round((jt - st.st_mtime) / 86400, 1)
        out["etat"] = ("DIVERGENTE du depot — %+.1f j d'ecart, %d o contre %d o"
                       % (ecart, out["taille"], js))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    ref = scanner_references()
    for e in ref["executions"]:
        e.update({k: v for k, v in confronter(e["chemin"]).items() if k != "chemin"})

    inventaire = []
    racines_illisibles = []
    for racine in RACINES_HORS_DEPOT:
        try:
            if not racine.is_dir():
                continue
            for f in sorted(racine.rglob("*")):
                if f.suffix.lower() in EXT_EXECUTABLES and f.is_file():
                    inventaire.append(confronter(str(f).replace("\\", "/")))
        except OSError as exc:
            racines_illisibles.append("%s (%s)" % (racine, type(exc).__name__))

    if a.json:
        print(json.dumps({"references": ref, "inventaire": inventaire,
                          "racines_illisibles": racines_illisibles},
                         indent=2, ensure_ascii=False))
        return code_de_sortie(ref["executions"])

    print("=== EXECUTABLES REFERENCES HORS DEPOT ===")
    print("perimetre lu : %d fichiers source, %d illisibles%s"
          % (ref["fichiers_lus"], len(ref["illisibles"]),
             (" -> %s" % ref["illisibles"][:3]) if ref["illisibles"] else ""))
    print("references ecartees : %d en donnees/repertoire de travail, %d en "
          "commentaire ou docstring, %d repli(s) DECLARE(s)"
          % (ref["n_donnees"], ref["n_commentaires"],
             ref.get("n_replis_declares", 0)))
    lances = [e for e in ref["executions"] if e["certitude"] == "LANCE"]
    cites = [e for e in ref["executions"] if e["certitude"] != "LANCE"]
    print("\n-- LANCES depuis un chemin hors depot (%d) --" % len(lances))
    for e in lances:
        print("  %s:%d" % (e["fichier"], e["ligne"]))
        print("     %s" % e["chemin"])
        print("     etat : %s" % e.get("etat", "?"))
        if e.get("jumeau"):
            print("     jumeau depot : %s" % e["jumeau"])
        print("     %s" % e["extrait"])
    print("\n-- CITES sans contexte d'execution visible (%d) --" % len(cites))
    for e in cites[:15]:
        print("  %s:%d  %s  [%s]" % (e["fichier"], e["ligne"], e["chemin"],
                                     e.get("etat", "?")))

    print("\n=== INVENTAIRE DES EXECUTABLES PRESENTS HORS DEPOT ===")
    if racines_illisibles:
        print("  racines ILLISIBLES : %s" % racines_illisibles)
        print("  (une racine illisible n'est pas une racine vide — couverture partielle)")
    if not inventaire:
        print("  aucun executable trouve dans %s"
              % ", ".join(str(r) for r in RACINES_HORS_DEPOT))
    for i in sorted(inventaire, key=lambda x: x.get("age_j") or 0, reverse=True)[:40]:
        print("  %-52s %s" % (i["chemin"][:52], i.get("etat", "?")))

    divergents = [i for i in inventaire if "DIVERGENTE" in str(i.get("etat"))]
    print("\n=== VERDICT ===")
    print("  lances depuis hors depot        : %d   <- le seul chiffre engageant"
          % len(lances))
    # Le compte des divergences additionne CHAQUE fichier des environnements
    # virtuels et des arbres de build presents hors depot. Il a rendu 95 789 le
    # 2026-09-14 : un nombre qui alarme sans informer, parce qu'il ne distingue
    # pas un module Nokido d'une dependance tierce. Il reste affiche -- c'est une
    # mesure -- mais il est DIT pour ce qu'il est.
    print("  copies divergentes du depot     : %d   (venv et arbres de build "
          "compris : a lire comme un volume, pas comme un defaut)" % len(divergents))
    print("  RIEN n'est supprime par cet outil : il signale, l'arbitrage est owner.")
    print("  Un repli hors depot LEGITIME se declare par `%s: <raison>`." % MARQUEUR_REPLI)
    return code_de_sortie(ref["executions"])


if __name__ == "__main__":
    raise SystemExit(main())
