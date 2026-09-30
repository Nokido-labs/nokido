"""forge_memory_compactor.py - GC semantique de l'index memoire Claude (.claude/.../MEMORY.md).

MEMORY.md (INDEX, 1 ligne/memoire) grossit car on AJOUTE sans PURGER -> deborde le cap
charge chaque session (24.4KB) -> entrees DROPPEES au load. Architecture 2-tier + gate :
  - MEMORY.md         = INDEX chaud (charge chaque session).
  - MEMORY_ARCHIVE.md = archive FROIDE (jamais chargee ; recall via fichiers-topic).
  - _memory_ledger.db = gate de secours blockchain (forge_memory_ledger) -> rien perdu.

Compaction par AGE : archive les entrees DATEES plus vieilles que le seuil, en EPARGNANT
feedback_/reference_/vision_ (regles/refs timeless) et les entrees sans-date. NON DESTRUCTIF :
le fichier-topic + l'archive froide + le ledger conservent tout (recoverable).

    LAFORGE_PYTHON tools/forge_memory_compactor.py --dry-run --cutoff 2026-06-21
    LAFORGE_PYTHON tools/forge_memory_compactor.py --cutoff 2026-06-21
    LAFORGE_PYTHON tools/forge_memory_compactor.py --keep-days 7
"""
from __future__ import annotations

import argparse
import datetime
import re
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
#
# ELLE DOIT PRECEDER L'IMPORT DU NAMESPACE. Posee APRES, elle est inoperante :
# mesure du 2026-09-11, ce fichier mourait a chaque SessionStart de Claude Code,
# et en SILENCE puisque le hook n'est pas bloquant -- ledger memoire non
# synchronise, MEMORY.md non reingere (le lexical servait la version d'avant),
# aucune compaction. Le codemod de a44b64df6 (migration PyPI de la famille
# `tools`) a remonte l'import en tete des imports sans deplacer l'amorce, que
# `forge_pypi_amorce._point_d_insertion` place « apres le docstring et les
# imports de tete ». NR : tests/nr/test_point_entree_par_chemin_nr.py
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

from nokido_agent.tools.forge_archeo_socle import liens_memoire  # noqa: E402

_DEFAULT_DIR = Path(__import__("os").path.expanduser(r"~/.claude/projects/C--Users-user-Script-python-IA/memory"))

# Timeless -> JAMAIS archiver (regles, feedback, refs de modules, visions).
# MESURE 2026-08-20 : au cutoff 2026-08-19, le compacteur voulait envoyer au froid
# `decision_arene_deux_verdicts_separes` et `politique_lmstudio_allume_quand_utile`
# -- deux ARBITRAGES OWNER, aussi permanents qu'un `feedback_`. Une decision ne se
# perime pas parce qu'elle a ete prise il y a deux jours : ce qui se perime, c'est
# un CONSTAT (incident, mesure, etat). Les prefixes qui portent une volonte de
# l'owner rejoignent donc la liste timeless.
_KEEP = re.compile(r"\]\((feedback_|reference_|vision_|loi_|doctrine_|decision_|politique_)")
# ANNEE NON FIGEE (mesure 2026-08-20). Le motif etait `(2026-\d\d-\d\d)` : au
# 1er janvier 2027, plus aucune date ISO n'aurait ete reconnue -> toute entree
# serait devenue « sans date ». Combine au `_classify` d'alors, qui archivait le
# sans-date, l'index CHAUD se serait vide en une passe, sans un mot. Un moteur de
# memoire durable ne peut pas coder l'annee courante en dur.
_DATE = re.compile(r"(20\d\d-\d\d-\d\d)")
# Lien d'index -> fichier-topic, et reference a un module du depot dans une memoire.
_LIEN = re.compile(r"\]\(([A-Za-z0-9_.-]+\.md)\)")
_MODREF = re.compile(r"\b((?:app|tools)/[A-Za-z0-9_]+\.py)")
# Noms d'EXEMPLE dans la prose (« edite tools/xxx.py ») : ce ne sont pas des references.
# Un garde qui crie a faux se fait desarmer -> on les ecarte, mais on les COMPTE.
_PLACEHOLDER = re.compile(r"^(x{1,3}|[A-Z]|script|some_tool|forge_x|mon_script|foo|bar|test)\.py$")
# Renommages du depot : citer l'ancien nom n'est pas une reference morte, c'est une DETTE.
_RENOMMAGES = (("laforge_", "nokido_"),)
# Plancher de fraicheur : ce qui a moins de N jours ne part JAMAIS au froid, meme
# sous pression de taille. Sans plancher, une passe automatique finirait par
# archiver ce qui vient d'etre appris -- exactement ce qu'on veut garder chaud.
#
# 5 et non 2 (owner, 2026-09-11) : a 2 jours, la boucle de convergence emportait
# 14 entrees dont trois de trois jours marquees cinq etoiles, et elle le faisait
# SANS crier puisqu'elle atteignait sa cible. Le plancher regle le FILET ; il n'est
# pas une permission d'archiver du recent.
_PLANCHER_JOURS = 5

# DEUX grandeurs distinctes, et les confondre coute dans les deux sens.
#   _SEUIL_DEFAUT_KB  : au-dela, l'index MERITE un repli editorial (confort).
#   _CAP_CHARGEMENT_KB: au-dela, des entrees sont DROPPEES AU LOAD (perte reelle,
#                       silencieuse) -- c'est la raison d'etre du compacteur.
# Crier au seuil comme au cap fabrique du bruit ; ne crier qu'au seuil laisse la
# perte arriver sans un mot. Le signal est donc GRADUE.
_SEUIL_DEFAUT_KB = 17.0
_CAP_CHARGEMENT_KB = 24.4


def _index_liens(p: Path) -> set:
    """Fichiers-topic cites par un index (chaud ou froid). Absent -> ensemble vide."""
    return liens_memoire(p)


def audit(memory_dir: Path = _DEFAULT_DIR, repo_root: Path | None = None) -> dict:
    """Ce que la compaction par AGE ne voit pas (mesure 2026-08-02).

    Le compacteur trie par DATE : une memoire de mai qui affirme un etat revolu reste
    donc aussi « chaude » qu'une mesure du jour, et un fichier jamais indexe n'existe
    pour aucun des deux tiers. Deux detections, toutes deux DETERMINISTES — aucun LLM,
    donc aucune peremption inventee :

      - `orphelins`  : fichier present sur disque, absent de l'index chaud ET de
        l'archive froide. Il n'est ni charge en session ni rattrapable par un index.
      - `a_reviser`  : la memoire cite un module qui vit desormais dans `_attic/`. Le
        deplacement est un FAIT du depot, pas une opinion — c'est le signal FORT.

    Un module simplement introuvable sort a part (`citations_introuvables`) : absence
    n'est pas archivage, et un nom peut etre generique, futur ou mal orthographie.
    Depot illisible depuis ce compte -> `INDETERMINE`, jamais un verdict.
    """
    memory_dir = Path(memory_dir)
    # `is_dir()` rend False pour un dossier ABSENT **et** pour un dossier dont l'ACL
    # refuse l'acces : confondre les deux fabrique un faux negatif (mesure 2026-08-02,
    # LaForgeTrusted n'a pas le profil owner). On force l'erreur a se nommer.
    try:
        next(memory_dir.iterdir(), None)
    except PermissionError:
        return {"INDETERMINE": f"{memory_dir} : acces REFUSE a ce compte — le dossier "
                               "existe peut-etre, relancer sous le compte owner"}
    except FileNotFoundError:
        return {"error": f"{memory_dir} : ABSENT"}
    except OSError as exc:
        return {"INDETERMINE": f"{memory_dir} : illisible ({type(exc).__name__})"}
    chauds = _index_liens(memory_dir / "MEMORY.md")
    froids = _index_liens(memory_dir / "MEMORY_ARCHIVE.md")
    fichiers = {p.name for p in memory_dir.glob("*.md")} - {"MEMORY.md", "MEMORY_ARCHIVE.md"}
    indexes = chauds | froids
    res = {
        "memoires": len(fichiers),
        "indexees_chaud": len(chauds & fichiers),
        "indexees_froid": len(froids & fichiers),
        "orphelins": sorted(fichiers - indexes),
        # L'index pointe sur un fichier absent. La GRAVITE depend de l'index qui le porte :
        # dans le CHAUD la ligne est chargee chaque session et promet une memoire qui
        # n'existe pas ; dans le FROID elle n'est jamais chargee, c'est cosmetique.
        # Mesure 2026-08-02 : les 3 liens morts etaient tous en froid, et le ledger ne
        # pouvait rien rendre — il ne protege qu'a partir de sa mise en service.
        # Un filtre qui ecarte des donnees le DIT, sinon la couverture est surestimee en
        # silence. Ici : tout ce qui n'est pas un `.md` analyse — dont `MEMORY.md.bak`,
        # ancien index au format 1 ligne/memoire, qui conserve les hooks descriptifs de
        # memoires aujourd'hui disparues. Il n'est pas suivi, il n'est pas perdu non plus.
        "hors_perimetre": sorted(p.name for p in memory_dir.iterdir()
                                 if p.is_file() and p.suffix != ".md"),
        "liens_morts": [{"fichier": f,
                         "index": "chaud" if f in chauds and f not in froids
                         else ("froid" if f in froids and f not in chauds else "les deux")}
                        for f in sorted(indexes - fichiers)],
    }
    root = Path(repo_root) if repo_root else Path(__file__).resolve().parent.parent
    res["repo_root"] = str(root)
    if not (root / "app").is_dir() or not (root / "tools").is_dir():
        res["a_reviser"] = "INDETERMINE : depot illisible depuis ce compte"
        return res
    attic: dict = {}
    for sous in ("app", "tools"):
        base_dir = root / sous
        if not base_dir.is_dir():
            continue
        for p in base_dir.rglob("*.py"):
            if "_attic" in p.parts:
                attic.setdefault(p.name, str(p.relative_to(root)).replace("\\", "/"))
    # Un module peut avoir DEMENAGE hors des dossiers indexes. Mesure 2026-08-16 :
    # les trois « citations introuvables » recurrentes du chantier memoire
    # (`tools/laforge_ctf_server.py`, `tools/laforge_recon_server.py`,
    # `tools/recon_master.py`) vivent en realite sous `ctf/tools/` — dossier
    # GITIGNORE, donc invisible a qui ne regarde que `app/` et `tools/`.
    # « Absent de tools/ » n'est pas « absent du depot » : les declarer perdus
    # envoyait chercher un fichier qui est la, et faisait passer une capacite
    # dormante pour une capacite morte.
    ailleurs: dict = {}
    for sous in ("ctf", "app", "tools"):
        base_dir = root / sous
        if not base_dir.is_dir():
            continue
        for p in base_dir.rglob("*.py"):
            if "_attic" in p.parts:
                continue
            ailleurs.setdefault(p.name, str(p.relative_to(root)).replace("\\", "/"))
    a_reviser, renommes, introuvables, n_placeholders = [], [], [], 0
    for nom in sorted(fichiers):
        try:
            txt = (memory_dir / nom).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            introuvables.append({"memoire": nom, "INDETERMINE": type(exc).__name__})
            continue
        for ref in sorted(set(_MODREF.findall(txt))):
            if (root / ref).exists():
                continue
            sous, base = ref.split("/", 1)[0], ref.rsplit("/", 1)[-1]
            if _PLACEHOLDER.match(base):
                n_placeholders += 1
                continue
            if base in attic:
                a_reviser.append({"memoire": nom, "cite": ref, "desormais": attic[base]})
                continue
            neuf = ""
            for vieux_p, neuf_p in _RENOMMAGES:
                if base.startswith(vieux_p) and (root / sous / (neuf_p + base[len(vieux_p):])).exists():
                    neuf = f"{sous}/{neuf_p}{base[len(vieux_p):]}"
                    break
            if neuf:
                renommes.append({"memoire": nom, "cite": ref, "desormais": neuf})
            elif base in ailleurs:
                a_reviser.append({"memoire": nom, "cite": ref, "desormais": ailleurs[base]})
            else:
                introuvables.append({"memoire": nom, "cite": ref})
    res["a_reviser"] = a_reviser
    res["renommes"] = renommes
    res["citations_introuvables"] = introuvables
    res["placeholders_ignores"] = n_placeholders  # ecartes, mais JAMAIS en silence
    return res


def corriger_renommages(memory_dir: Path = _DEFAULT_DIR, repo_root: Path | None = None,
                        dry_run: bool = True) -> dict:
    """Remplace dans les memoires les chemins rendus FAUX par un renommage du depot.

    Mesure 2026-08-02 : 33 memoires citaient encore un module disparu au renommage vers
    Nokido du 08-07. Elles ne sont pas « vieilles », elles sont FAUSSES : un agent qui les
    lit va chercher un fichier qui n'existe plus. C'est une reecriture de memoire, donc
    elle est bornee au maximum — substitution du chemin EXACT rendu par `audit`, jamais
    une regex large — et le ledger est synchronise AVANT, pour que chaque version d'avant
    reste recuperable.
    """
    memory_dir = Path(memory_dir)
    a = audit(memory_dir, repo_root)
    cibles = a.get("renommes")
    if not isinstance(cibles, list):
        return a
    if not dry_run:
        try:  # filet : chaque version d'avant reste dans la chaine
            from nokido_agent.tools import forge_memory_ledger as _ml

            _ml.sync(memory_dir)
        except Exception as exc:
            return {"ARRET": f"ledger indisponible ({type(exc).__name__}) — rien reecrit"}
    par_fichier: dict = {}
    for c in cibles:
        par_fichier.setdefault(c["memoire"], []).append((c["cite"], c["desormais"]))
    faits, echecs, contextes_ignores = [], [], []
    for nom, paires in sorted(par_fichier.items()):
        p = memory_dir / nom
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            echecs.append({"memoire": nom, "err": type(exc).__name__})
            continue
        lignes = txt.splitlines(keepends=True)
        n, ignores = 0, 0
        for i, ligne in enumerate(lignes):
            for vieux, remplacant in paires:
                if vieux not in ligne:
                    continue
                # Garde anti-faux-positif (mesure 2026-08-16) : quand la ligne cite DEJA
                # le nom NEUF, elle documente le renommage lui-meme -- « laforge_hub.py
                # cite 724x = nokido_hub.py ». Y substituer le neuf detruit le sens de la
                # phrase au lieu de la reparer. Une reecriture de memoire ne doit jamais
                # rendre une memoire VRAIE illisible.
                if remplacant in ligne:
                    ignores += ligne.count(vieux)
                    continue
                n += ligne.count(vieux)
                ligne = ligne.replace(vieux, remplacant)
                lignes[i] = ligne
        neuf = "".join(lignes)
        if ignores:
            contextes_ignores.append({"memoire": nom, "occurrences": ignores})
        if neuf == txt:
            continue
        faits.append({"memoire": nom, "occurrences": n,
                      "remplacements": [f"{v} -> {r}" for v, r in paires]})
        if not dry_run:
            try:
                p.write_text(neuf, encoding="utf-8")
            except OSError as exc:
                faits.pop()
                echecs.append({"memoire": nom, "ECRITURE_REFUSEE": type(exc).__name__})
    return {"memoires_corrigees": len(faits), "occurrences": sum(f["occurrences"] for f in faits),
            "dry_run": dry_run, "echecs": echecs, "detail": faits[:10],
            "ignores_contexte_renommage": contextes_ignores}


def rattacher(memory_dir: Path = _DEFAULT_DIR, dry_run: bool = True) -> dict:
    """Remet les orphelines dans un index : timeless -> CHAUD, le reste -> FROID.

    Une memoire que personne n'index n'est chargee par rien : elle ne depend plus que
    d'un rappel opportuniste. Mesure 2026-08-02 : 39 orphelines, dont des `feedback_`,
    des `reference_` et une `vision_` — soit exactement les categories que la compaction
    par age EPARGNE le plus. Le hook de chaque ligne est la `description:` du frontmatter
    du fichier : deterministe, ecrite par l'auteur de la memoire, jamais reformulee ici.
    """
    memory_dir = Path(memory_dir)
    a = audit(memory_dir)
    if "orphelins" not in a:
        return a
    chaud, froid = [], []
    for nom in a["orphelins"]:
        desc = ""
        try:
            for ligne in (memory_dir / nom).read_text(encoding="utf-8", errors="replace").splitlines()[:12]:
                if ligne.startswith("description:"):
                    desc = ligne.split(":", 1)[1].strip().strip('"').strip("'")
                    # L'index vit sous un cap de chargement : un hook de 150 caracteres
                    # le fait deborder, ce qui RE-CREE l'amnesie qu'on repare (mesure
                    # 2026-08-02 : 6 entrees = 1,1 Ko a elles seules). On coupe court,
                    # au premier separateur de sens quand il y en a un.
                    for sep in (" — ", " - ", " ; ", ". "):
                        if 0 < desc.find(sep) <= 70:
                            desc = desc[:desc.find(sep)]
                            break
                    if len(desc) > 70:
                        desc = desc[:70].rsplit(" ", 1)[0]  # jamais au milieu d'un mot
                    desc = desc.rstrip(" ,;:—-")
                    break
        except OSError as exc:
            desc = f"(frontmatter illisible : {type(exc).__name__})"
        entree = f"- [{desc or nom[:-3]}]({nom})"
        (chaud if _KEEP.search(f"]({nom}") else froid).append(entree)
    res = {"orphelins": len(a["orphelins"]), "vers_chaud": len(chaud),
           "vers_froid": len(froid), "dry_run": dry_run,
           "apercu_chaud": chaud[:6], "apercu_froid": froid[:4]}
    if dry_run:
        return res
    if chaud:
        with (memory_dir / "MEMORY.md").open("a", encoding="utf-8") as f:
            f.write("- **♻️ rattachees (etaient orphelines)** : " +
                    " · ".join(c[2:] for c in chaud) + "\n")
    if froid:
        with (memory_dir / "MEMORY_ARCHIVE.md").open("a", encoding="utf-8") as f:
            f.write("\n".join(froid) + "\n")
    return res


_DATE_JM = re.compile(r"\b(0[1-9]|[12]\d|3[01])/(0[1-9]|1[0-2])\b")


def _date_libelle(txt: str, annee: str | None = None) -> str:
    """Date ecrite a la main dans le LIBELLE (« 16/08 »), rendue au format ISO.

    Mesure 2026-08-16 : l'index date ses entrees lui-meme — « 16/08 (REGRESSION)
    ... ](docker_..._2026-08-06.md) ». Ne lire que la date du NOM DE FICHIER
    revient a dater la lecon du jour ou le fichier a ete cree, donc a envoyer en
    froid une lecon apprise AUJOURD'HUI sur un fichier ancien. Meme piege que
    `st_mtime` cote `forge_memory_staleness` : la date du support n'est pas la
    date de la connaissance.
    """
    # Annee COURANTE par defaut, jamais 2026 en dur : « 14/01 » lu en 2027
    # devenait « 2026-01-14 », soit une entree vieillie d'un an par son lecteur.
    annee = annee or str(datetime.date.today().year)
    m = _DATE_JM.search(txt)
    return "%s-%s-%s" % (annee, m.group(2), m.group(1)) if m else ""


def _date_entree(txt: str, plancher: str = "") -> str:
    """La plus RECENTE des dates portees par une entree : libelle, nom de fichier,
    et date de la ligne-theme qui la contient. Le plus recent gagne — une memoire
    re-touchee aujourd'hui n'est pas ancienne."""
    # `findall` et non `search` (mesure 2026-08-20) : une entree porte souvent
    # PLUSIEURS fichiers dates sur la meme ligne, et `search` n'en rendait que le
    # premier -- donc la plus ANCIENNE date gagnait, en contradiction avec cette
    # docstring. Une memoire re-touchee aujourd'hui etait datee de sa naissance.
    cands = [d for d in (_DATE.findall(txt) + [_date_libelle(txt), plancher]) if d]
    return max(cands) if cands else ""


def _classify(line: str, cutoff: str) -> bool:
    """True = archiver (entree DATEE plus ancienne que `cutoff`).

    Epargne les intemporelles (feedback/reference/vision/loi/doctrine/decision/
    politique) ET les entrees SANS DATE.
    """
    if not line.lstrip().startswith("- ["):
        return False
    if _KEEP.search(line):
        return False
    d = _date_entree(line)
    if not d:
        # SANS DATE = PAS DE DECISION (mesure 2026-08-20). Le code rendait `True`
        # ici : il traduisait « je ne sais pas quand ceci a ete appris » en
        # « c'est assez vieux pour partir au froid ». C'est une absence
        # d'information convertie en verdict negatif -- exactement ce qu'on
        # traque partout ailleurs. La docstring promettait deja l'inverse : c'est
        # le code qu'on aligne sur le contrat, pas le contrat sur le code.
        return False
    if d >= cutoff:
        return False  # datee recente -> garder
    return True  # datee ET plus ancienne que le seuil -> froid (recuperable)


def _segments(corps: str) -> list:
    """Decoupe une ligne thematique en entrees SANS couper dans un libelle de lien.

    Mesure 2026-08-10 : `corps.split(" · ")` coupait toute entree dont le LIBELLE
    contient « · » — `[a · b](x.md)` devenait `[a` (fragment SANS url, markdown mort,
    garde car sans date) et `b](x.md)` (archive). Deux lignes de l'index owner ont ete
    mutilees ainsi, dont une entierement videe de ses liens. Le separateur ne vaut donc
    qu'a profondeur de crochets NULLE.
    """
    out, buf, prof, i = [], [], 0, 0
    while i < len(corps):
        c = corps[i]
        if c == "[":
            prof += 1
        elif c == "]":
            prof = max(0, prof - 1)
        if prof == 0 and corps.startswith(" · ", i):
            out.append("".join(buf))
            buf, i = [], i + 3
            continue
        buf.append(c)
        i += 1
    if buf:
        out.append("".join(buf))
    return out


def _compacter_theme(line: str, cutoff: str) -> tuple:
    """Ligne THEMATIQUE (« - **Theme** : [a](a.md) · [b](b.md) ») -> (ligne_gardee, froids).

    Mesure 2026-08-02 : `_classify` ne traite que les lignes commencant par `- [`, or
    l'index a evolue vers UN THEME par ligne portant N memoires. Le garde anti-debordement
    etait donc INOPERANT — il rendait `archived: 0` en silence pendant que l'index montait
    a 20,7 Ko, jusqu'a friser le cap de chargement. Un garde branche sur un format qui
    n'existe plus ne crie pas : il se tait.

    L'unite d'archivage est la MEMOIRE, pas le sommaire : on ne retire que les entrees
    datees anciennes, la ligne survit avec le reste, et les timeless sont epargnees comme
    partout ailleurs. Une ligne entierement videe part en froid avec son titre.
    """
    tete, sep, corps = line.partition(" : ")
    if not sep or not corps.strip():
        return line, []
    gardes, froids = [], []
    titre = tete.lstrip("- ").strip()
    d_tete = _date_libelle(tete)  # la ligne-theme date ses propres entrees
    for seg in _segments(corps):
        s = seg.strip()
        if not s:
            continue
        if _KEEP.search(s):
            gardes.append(s)
            continue
        d = _date_entree(s, d_tete)
        if not d or d >= cutoff:
            gardes.append(s)
        else:
            froids.append(f"- {titre} {s}")  # le titre suit l'entree : contexte conserve
    if not gardes:
        return "", froids
    return f"{tete} : " + " · ".join(gardes), froids


def compact(memory_dir: Path = _DEFAULT_DIR, cutoff: str = "2026-06-20", dry_run: bool = False) -> dict:
    mem = memory_dir / "MEMORY.md"
    arch = memory_dir / "MEMORY_ARCHIVE.md"
    if not mem.exists():
        return {"error": f"{mem} absent"}
    lines = mem.read_text(encoding="utf-8").splitlines()
    keep, cold = [], []
    for ln in lines:
        if _classify(ln, cutoff):
            cold.append(ln)
        elif ln.lstrip().startswith("- **") and _LIEN.search(ln):
            gardee, froids = _compacter_theme(ln, cutoff)
            cold.extend(froids)
            if gardee:
                keep.append(gardee)
        else:
            keep.append(ln)
    before_kb = round(len(mem.read_text(encoding="utf-8").encode("utf-8")) / 1024, 1)
    new_index = "\n".join(keep).rstrip() + "\n"
    after_kb = round(len(new_index.encode("utf-8")) / 1024, 1)
    res = {"before_kb": before_kb, "after_kb": after_kb, "cutoff": cutoff,
           # compte les MEMOIRES, pas les lignes : sur l'index thematique l'ancien
           # compteur affichait 0 garde alors que tout etait conserve.
           "kept": sum(len(_LIEN.findall(k)) for k in keep),
           "archived": sum(len(_LIEN.findall(c)) for c in cold), "dry_run": dry_run}
    if dry_run:
        res["would_archive"] = [c[:90] for c in cold[:8]]
        return res
    mem.write_text(new_index, encoding="utf-8")
    if cold:
        header = "" if arch.exists() else (
            "# MEMORY_ARCHIVE - index FROID (jamais charge en session ; recall via "
            "fichiers-topic + _memory_ledger.db)\n\n")
        with arch.open("a", encoding="utf-8") as f:
            f.write(header + "\n".join(cold) + "\n")
    return res


def main():
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # muet-ok : confort d'affichage, sans effet sur le resultat
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--memory-dir", default=str(_DEFAULT_DIR))
    ap.add_argument("--cutoff", default=None, help="date AAAA-MM-JJ : archive les entrees datees AVANT")
    ap.add_argument("--keep-days", type=int, default=8, help="si --cutoff absent : archive > N jours")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--audit", action="store_true",
                    help="orphelins (ni chaud ni froid) + memoires dementies par le depot")
    ap.add_argument("--repo-root", default=None, help="racine Nokido (defaut : parent de tools/)")
    ap.add_argument("--rattacher", action="store_true",
                    help="remet les orphelines dans un index (timeless -> chaud, reste -> froid)")
    ap.add_argument("--corriger-renommages", action="store_true",
                    help="remplace les chemins rendus faux par un renommage (ledger sync avant)")
    ap.add_argument("--auto", action="store_true", help="hook SessionStart : ledger + compaction si deborde")
    ap.add_argument("--sans-compaction", action="store_true",
                    help="--auto : ledger + reingestion SEULS, l'index n'est jamais reecrit")
    # 17.0 et non 22.0 : le cap de LECTURE de l'index est 24.4 Ko, mais le harness
    # reclame une compaction des 17.1 Ko -- viser 22 laissait l'index deborder la
    # cible en se croyant en regle (mesure 2026-08-20, index a 23.8 Ko).
    ap.add_argument("--threshold-kb", type=float, default=_SEUIL_DEFAUT_KB)
    args = ap.parse_args()
    import json
    mdir = Path(args.memory_dir)
    mem = mdir / "MEMORY.md"
    cutoff = args.cutoff or (datetime.date.today() - datetime.timedelta(days=args.keep_days)).isoformat()
    if args.audit:
        root = Path(args.repo_root) if args.repo_root else None
        print(json.dumps(audit(mdir, root), ensure_ascii=False, indent=1))
        return
    if args.rattacher:
        print(json.dumps(rattacher(mdir, dry_run=args.dry_run), ensure_ascii=False, indent=1))
        return
    if args.corriger_renommages:
        root = Path(args.repo_root) if args.repo_root else None
        print(json.dumps(corriger_renommages(mdir, root, dry_run=args.dry_run),
                         ensure_ascii=False, indent=1))
        return
    if args.auto:
        # SessionStart : silencieux + tolerant. .claude inaccessible (compte non-user) => no-op.
        try:
            if not mem.exists():
                return
            # Gate de secours BLOCKCHAIN : ledger append-only de la memoire (rien perdu).
            try:
                from nokido_agent.tools import forge_memory_ledger as _ml
                # rapide : ne rouvre pas les 975 fiches a chaque demarrage (6 s a
                # froid, hook tue a 8 s -- mesure 2026-09-26).
                _lr = _ml.sync(mdir, rapide=True)
                if _lr.get("appended"):
                    print(f"[memory_ledger] +{_lr['appended']} versions chainees")
                _ml.prune()  # borne la croissance (garde chaine+sha, vide vieux contenu)
            except Exception as _le:
                print(f"[memory_ledger] skip ({_le})")
            # L'index vient peut-etre d'etre REECRIT par la session precedente :
            # sans reingestion, le lexical continue de servir la version d'avant.
            # C'est le defaut repare le 2026-09-04 (chemin VOLATIL de
            # `forge_memory_ingest`), et il se RE-CREERAIT a chaque session si
            # personne ne rebranchait la chaine ici.
            #
            # L'appel est AVANT le test de seuil, et non apres la compaction :
            # l'index change a chaque session sans forcement franchir les 17 Ko,
            # donc le cas le PLUS FREQUENT est justement celui ou l'on ne
            # compacte pas. L'ingestion est idempotente (id par position,
            # empreinte sur le texte entier) : si rien n'a bouge, elle n'ecrit
            # rien.
            try:
                import io as _io
                from contextlib import redirect_stdout as _rs

                from nokido_agent.tools import forge_memory_ingest as _mi

                _buf = _io.StringIO()
                with _rs(_buf):  # l'ingestion est bavarde ; le hook ne doit pas l'etre
                    _mi.ingerer(appliquer=True, fichier="MEMORY.md")
                for _ligne in _buf.getvalue().splitlines():
                    if "chunks ecrits" in _ligne and not _ligne.strip().endswith(": 0"):
                        print("[memory_ingest] index reingere —%s"
                              % _ligne.split(":", 1)[1].rstrip())
                    elif "volatil" in _ligne or "[!]" in _ligne:
                        print("[memory_ingest]%s" % _ligne.split("]", 1)[-1])
            except Exception as _ie:
                # Jamais fatal : le hook SessionStart ne doit pas mourir pour ca.
                # Mais jamais MUET non plus — un lexical perime qui se tait est
                # exactement ce qu'on vient de corriger.
                print("[memory_ingest] reingestion IMPOSSIBLE (%s: %s) — le lexical "
                      "sert encore la version precedente" % (type(_ie).__name__, _ie))

            # OCTETS DISQUE, pas le texte reencode (mesure 2026-09-11).
            # `read_text()` normalise CRLF -> LF : sur cet index l'ecart etait de
            # 21,7 Ko reels contre 20,5 Ko mesures. Un garde de capacite qui
            # sous-estime de 1,2 Ko crie TROP TARD, c'est-a-dire quand les entrees
            # sont deja droppees. La grandeur qui compte est celle que le lecteur
            # charge : la taille du fichier.
            kb = mem.stat().st_size / 1024
            # GARDE DE CAPACITE — il MESURE et SIGNALE, il ne deplace RIEN.
            #
            # Arbitrage owner du 2026-09-11, en deux temps. D'abord desarmer la
            # compaction automatique : a 21,6 Ko elle descendait au plancher, y
            # atteignait sa cible (15,2 <= 17) et emportait donc 14 entrees SANS
            # emettre « CIBLE NON ATTEINTE ». Puis corriger ce desarmement, juge trop
            # agressif : le compacteur etait AUSSI le seul garde contre le
            # depassement du plafond de chargement, au-dela duquel des entrees sont
            # DROPPEES AU LOAD, en silence. Le retirer laissait 2,7 Ko de marge.
            #
            # Le contrat retenu : mesurer, dire, ne rien deplacer. La consigne de
            # MEMORY.md du 2026-09-06 (« COMPACTER CET INDEX = A LA MAIN ») prime sur
            # toute automatisation -- une passe auto avait duplique un en-tete et
            # TRONQUE une entree.
            #
            # Le defaut du CODE est non destructif, et non pas le drapeau du hook :
            # une surete qui vit dans un fichier de configuration EXTERNE disparait
            # des que quelqu'un edite ce fichier. `--sans-compaction` reste accepte,
            # sans effet, pour ne pas casser le SessionStart deja configure.
            #
            # Le signal est GRADUE : au seuil c'est un confort, au CAP c'est une perte.
            if kb >= _CAP_CHARGEMENT_KB:
                print("[memory_compactor] CAP DE CHARGEMENT ATTEINT — index a %.1fKB "
                      "pour un cap de %.1fKB : des entrees de l'index sont DROPPEES au "
                      "load, en silence. Repli editorial REQUIS (carte "
                      "index_chantiers_<date>.md). Rien n'a ete deplace."
                      % (kb, _CAP_CHARGEMENT_KB))
            elif kb > args.threshold_kb:
                print("[memory_compactor] index a %.1fKB (seuil %.1fKB, cap de load "
                      "%.1fKB, marge %.1fKB) — repli editorial a la main recommande. "
                      "Rien n'a ete deplace."
                      % (kb, args.threshold_kb, _CAP_CHARGEMENT_KB, _CAP_CHARGEMENT_KB - kb))
            return
            # NOTE (2026-09-11) : la boucle de CONVERGENCE et la reingestion
            # post-compaction vivaient ici. Elles sont retirees avec la compaction
            # automatique, et non commentees : du code inatteignable sous un `return`
            # se relit comme actif et ment au prochain lecteur. La capacite n'est pas
            # perdue -- `compact()` reste appelable, et le mode par defaut de ce CLI
            # (sans `--auto`) la traverse toujours, cutoff et convergence compris.
        except Exception as e:
            print(f"[memory_compactor] skip ({e})")
        return
    print(json.dumps(compact(mdir, cutoff=cutoff, dry_run=args.dry_run), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
