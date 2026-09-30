#!/usr/bin/env python3
"""forge_wiki_modules.py — reference des modules, GENEREE depuis le code.

Une definition ecrite a la main derive du code des la semaine suivante ; c'est
la meme maladie que le catalogue de regulation qui a survecu a son
implementation six semaines. Cette page est donc DERIVEE : chaque definition
est la docstring reelle du module, relue a chaque generation.

Regle absolue : on n'INVENTE aucune definition. Un module sans docstring est
liste comme tel, dans une section a part qui se veut inconfortable — c'est un
trou de documentation mesure, pas un detail a masquer par une paraphrase du
nom de fichier.

Source d'organes : `sandbox/workspace/organ_map_full.json` produit par
`tools/forge_module_census.py` (deja en place, cf. CLAUDE.md section 10). On le
REUTILISE ; en son absence on classe en "non classe" plutot que de deviner.

Sortie : docs/wiki/20-Modules-Reference.md
"""
from __future__ import annotations

__FORGE_COLOR__ = "observabilite/anatomy : reference des modules generee depuis le code"  # organe declare le 2026-09-06 (audit de raccordement)

import ast
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARTE = ROOT / "sandbox" / "workspace" / "organ_map_full.json"
OUT = ROOT / "docs" / "wiki" / "20-Modules-Reference.md"
# Cible des fiches, DECLAREE AU NIVEAU MODULE comme `OUT` et `RATCHET`.
#
# Elle etait calculee en local dans deux fonctions, et c'est ce qui a refuse la
# capture de la CI du 2026-09-22 : `test_wiki_origine_et_peremption_nr` substitue
# `OUT` depuis toujours, donc le generateur n'ecrivait rien dans l'arbre. La
# persistance L2 ajoutee le matin meme a introduit une SECONDE ecriture, dans un
# chemin que ce test empruntait deja — et qu'il ne pouvait pas isoler, faute de
# point de substitution. Le test n'a pas change ; son EFFET, si.
#
#     UNE ECRITURE AJOUTEE DANS UN CHEMIN DEJA TESTE DOIT ETRE ISOLABLE
#     COMME CELLES QUI Y ETAIENT DEJA.
#
# Consequence mesuree : `process_state=CAPTURE_REFUSED`, malgre 11 646 tests a
# zero echec et 21 gates verts. Un juge qui refuse de certifier un arbre que le
# run a modifie a raison : l'identite du sujet n'est plus etablie.
CARDS = ROOT / "tools" / "forge_card_summaries.json"

# PAIRE EN/FR (owner 2026-09-29 : « pourquoi 20-Modules-Reference.md n'est pas traduit
# en fr ? »). Toutes les pages du wiki vont par paire `X.md` / `X.fr.md`, sauf la seule
# GENEREE : Home.fr.md envoyait le lecteur francophone vers un habillage francais SANS
# accents, sous un titre anglais. Les noms servent aux LIENS entre jumelles ; le chemin
# de la page FR, lui, se DERIVE de `OUT` (voir `cible_fr`) -- jamais une seconde
# constante : un test qui substitue `OUT` isole du meme geste la page FR, sinon la
# generation ecrirait dans l'arbre juge (meme lecon que `CARDS` ci-dessus).
NOM_EN = "20-Modules-Reference.md"
NOM_FR = "20-Modules-Reference.fr.md"

ZONES = ("app", "tools", "forge_desktop")


# En-tete MACHINE laisse par d'anciens enrichisseurs AST, en tete de docstring :
# `FORGE INTELLIGENCE [BLUE]`, `DATE:2026-06-02 | VER:v_x`, `#FORGE:[score:94|...]`.
_RE_ENTETE_MACHINE = re.compile(
    r"^\s*(FORGE INTELLIGENCE\b.*|DATE\s*:.*|VER\s*:.*|#FORGE:\[.*|\[(RED|GREEN|BLUE|YELLOW|WHITE)\]\s*)$",
    re.IGNORECASE)


def sans_entete_machine(doc: str) -> str:
    """La docstring SANS ses lignes d'en-tete machine initiales ; "" s'il n'y a que l'en-tete.

    Mesure du 2026-09-29 : 181 modules comptes « sans docstring » en avaient une VRAIE derriere cet
    en-tete (ex. forge_db_path, importe par 140 modules). Trois lecteurs se trompaient de la meme
    facon : ce wiki (module non documente), `introspect` (resume = « DATE:... | VER:... ») et les
    fiches RAG (`DOC:` = « FORGE INTELLIGENCE [BLUE] »). Une seule regle, ici, pour les trois.
    Seules les lignes de TETE sont retirees : un « DATE: » au milieu du texte est du contenu.
    """
    lignes = (doc or "").splitlines()
    i = 0
    while i < len(lignes) and (not lignes[i].strip() or _RE_ENTETE_MACHINE.match(lignes[i])):
        i += 1
    return "\n".join(lignes[i:]).strip()


def definition_du_module(source: str, nom: str = "") -> str:
    """Premiere phrase de la docstring d'un module (en-tete machine retire) ; "" si aucune ou illisible."""
    try:
        doc = ast.get_docstring(ast.parse(source))
    except (SyntaxError, ValueError):
        return ""
    return _premiere_phrase(doc or "", nom)


def _premiere_phrase(doc: str, nom: str = "") -> str:
    """Premiere phrase de la docstring : la definition que l'auteur a donnee.

    Trois nettoyages, tous constates sur le corpus reel :
      * le prefixe redondant (`tools/forge_x.py — vraie definition`) : garder le
        nom de fichier en tete de sa propre ligne de tableau n'apprend rien ;
      * les EN-TETES MACHINE laisses par d'anciens enrichisseurs AST
        (`FORGE INTELLIGENCE v3 [GREEN] #FORGE:[score:94|...]`) : ce n'est pas
        une definition, et l'afficher comme telle serait mentir sur l'etat de
        la documentation. Le module est alors compte comme NON documente ;
      * la coupe a la premiere phrase, faite APRES le reste (sinon le separateur
        du prefixe coupe la definition au lieu du prefixe).
    """
    doc = " ".join(sans_entete_machine(doc or "").split())
    if not doc:
        return ""
    if "#FORGE:[" in doc or doc.upper().startswith("FORGE INTELLIGENCE"):
        return ""
    for base in filter(None, (nom, nom.replace(".py", ""))):
        for prefixe in (base, "app/" + base, "tools/" + base):
            if doc.lower().startswith(prefixe.lower()):
                doc = doc[len(prefixe):].lstrip(" —-:·|").strip()
                break
    for sep in (". ", " — ", " - "):
        if sep in doc:
            doc = doc.split(sep)[0]
            break
    return doc[:260].rstrip(" .")


def _lire(p: Path) -> dict:
    src = p.read_text(encoding="utf-8", errors="replace")
    fiche = {
        "chemin": str(p.relative_to(ROOT)).replace("\\", "/"),
        "nom": p.stem,
        "loc": src.count("\n") + 1,
        "octets": len(src.encode("utf-8", "replace")),
        "doc": "",
        "couleur": "",
        "publics": [],
    }
    try:
        arbre = ast.parse(src)
    except SyntaxError:
        # Un fichier qui ne parse pas est un fait, pas une exception a taire.
        fiche["doc"] = ""
        fiche["erreur"] = "SyntaxError"
        return fiche
    fiche["doc"] = _premiere_phrase(ast.get_docstring(arbre) or "", p.name)
    for n in arbre.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not n.name.startswith("_"):
                fiche["publics"].append(n.name)
        elif isinstance(n, ast.Assign):
            for c in n.targets:
                if isinstance(c, ast.Name) and c.id == "__FORGE_COLOR__":
                    if isinstance(n.value, ast.Constant):
                        fiche["couleur"] = str(n.value.value)
    return fiche


def collecter() -> list[dict]:
    fiches = []
    for zone in ZONES:
        for p in sorted((ROOT / zone).glob("**/*.py")):
            motif = _est_jetable(p)
            if motif:
                ECARTES.append("%s (%s)" % (p, motif))
                continue
            try:
                fiches.append(_lire(p))
            except OSError as exc:
                # Ce `continue` etait MUET : le fichier disparaissait du
                # denominateur sans laisser de trace. ILLISIBLE != ABSENT.
                ILLISIBLES.append("%s (%s)" % (p, type(exc).__name__))
    return fiches


def organes() -> dict:
    if not CARTE.exists():
        return {}
    try:
        brut = json.loads(CARTE.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(brut, dict):
        return {}
    # Forme reelle produite par forge_module_census :
    # {"module_organ": {"forge_rag_engine.py": "Memoire (...)"}, "tally": ...}
    # Les cles portent l'EXTENSION — chercher le stem ne trouve rien.
    table = brut.get("module_organ") if isinstance(brut.get("module_organ"), dict) else brut
    premiere = next(iter(table.values()), None)
    if isinstance(premiere, list):
        return {m: org for org, mods in table.items() for m in mods}
    return {str(k): str(v) for k, v in table.items()}


# ── Origine d'un artefact genere ─────────────────────────────────────────────
# MESURE 2026-09-16 : la page decrivait un corps vieux de 17 jours (1204 des
# 1765 modules modifies depuis sa generation) et RIEN ne le signalait. Elle
# nommait bien son outil, mais pas l'ETAT du code qu'elle decrit. Faute de
# quoi, quelqu'un a colle une rustine manuelle en tete le 2026-08-30 plutot
# que de regenerer : un artefact dont la fraicheur demande une annotation
# humaine est un artefact dont la fraicheur n'est pas mesurable.
_MARQUEUR = "nokido:genere"
_RE_ORIGINE = re.compile(r"<!--\s*nokido:genere\b[^>]*?\bsha=([0-9a-fA-F]+|INCONNU)")
_RE_EMPREINTE = re.compile(r"<!--\s*nokido:genere\b[^>]*?\bempreinte=([0-9a-f]+|INCONNUE)")
_RACINE = Path(__file__).resolve().parent.parent

# Rempli par `collecter()`, lu par `main()` et `rendre()`. Un fichier qu'on n'a
# PAS PU LIRE n'est pas un fichier sans docstring : le confondre ferait dire a
# la page « N modules » sans dire combien lui ont echappe. Un filtre qui ecarte
# des donnees le DIT, sinon la couverture est surestimee en silence.
ILLISIBLES: list = []

# Ce qui n'est PAS un module du corps, et qu'on comptait pourtant comme tel.
# MESURE 2026-09-16 : `app/backups/` portait CINQ copies du meme fichier de
# 4902 lignes, comptees comme cinq modules sans docstring. 52 entrees sur 923
# relevaient de ce bruit -- pas de quoi expliquer le vide (871 modules vivants
# restent sans docstring), mais assez pour fausser un denominateur.
# ⚠️ Ecarter n'autorise pas a se taire : les ecartes sont COMPTES et dits.
_DOSSIERS_ECARTES = ("_attic", "node_modules", "backups", "archive", "vendor",
                     "third_party", "site-packages")
_PREFIXES_ECARTES = ("tmp_",)
ECARTES: list = []


def _est_jetable(p) -> str:
    """Rend le MOTIF de l'ecart, ou une chaine vide si le fichier compte."""
    for d in _DOSSIERS_ECARTES:
        if d in p.parts:
            return "dossier:%s" % d
    for pre in _PREFIXES_ECARTES:
        if p.name.startswith(pre):
            return "prefixe:%s" % pre
    return ""


def _maintenant_utc() -> str:
    """UTC, suffixe `Z` explicite.

    Piege paye DEUX fois sur ce depot : un horodatage local relu comme UTC
    (« 17:31 » pour 19:31) a failli faire conclure qu'aucun run ne tournait.
    Le `Z` n'est pas decoratif, c'est ce qui rend l'heure comparable.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha_du_depot(racine=None):
    """Le sha de HEAD, lu DANS `.git` — jamais par un sous-processus.

    `action=python` du hub refuse `Popen` (`WORKSPACE_GUARD`) : un lecteur de
    sha qui passerait par un shell ne tournerait pas la ou on en a besoin.

    Rend `None` quand il ne sait pas — un depot sans `.git`, un `HEAD`
    illisible. Ne devine JAMAIS : `UNKNOWN != NO`, et un sha invente ferait
    passer une page perimee pour fraiche.
    """
    racine = Path(racine) if racine is not None else _RACINE
    g = racine / ".git"
    try:
        if g.is_file():
            # Worktree detache (la CI de reference en cree un) : `.git` est un
            # FICHIER « gitdir: <chemin> », pas un dossier.
            brut = g.read_text(encoding="utf-8", errors="replace").strip()
            if not brut.startswith("gitdir:"):
                return None
            g = Path(brut.split(":", 1)[1].strip())
            if not g.is_absolute():
                g = (racine / g).resolve()
        head = (g / "HEAD").read_text(encoding="utf-8", errors="replace").strip()
    except OSError:  # muet-ok : l'absence de sha EST le signal, rendu en INCONNU
        return None
    if not head.startswith("ref:"):
        return head or None          # HEAD detache : le sha est ecrit tel quel
    ref = head.split(":", 1)[1].strip()
    try:
        return (g / ref).read_text(encoding="utf-8", errors="replace").strip() or None
    except OSError:  # muet-ok : ref non deballee -> le repli packed-refs suit
        pass
    try:                              # repli : la ref peut etre empaquetee
        for ligne in (g / "packed-refs").read_text(
                encoding="utf-8", errors="replace").splitlines():
            morceaux = ligne.split()
            if len(morceaux) == 2 and morceaux[1] == ref:
                return morceaux[0]
    except OSError:  # muet-ok : on rend None, et `main()` le DIT a l'ecran
        pass
    return None


def empreinte_du_corpus(fiches: list[dict]) -> str:
    """Empreinte de CE QUE LA PAGE PUBLIE — pas de l'arbre entier.

    ⚠️ POURQUOI PAS LE SHA (defaut vu AVANT de poser le gate, 2026-09-16).
    Juger la fraicheur sur « sha inscrit == HEAD » rend PERIME des le commit
    SUIVANT, meme s'il ne touche aucun module : la page serait perimee une
    seconde apres avoir ete ecrite. Un garde qui crie a faux se fait desarmer,
    et on aurait perdu le cliquet au premier agacement.

    On hache donc ce que la page REFLETE reellement : chemin, docstring, API
    publique, taille. Deux commits qui ne changent aucune de ces donnees
    laissent la page FRAICHE, ce qui est vrai.
    """
    h = hashlib.sha256()
    for f in sorted(fiches, key=lambda x: x["chemin"]):
        h.update(("%s\x1f%s\x1f%s\x1f%s\x1e" % (
            f["chemin"], f.get("doc") or "",
            ",".join(f.get("publics") or ()), f.get("loc") or 0)
        ).encode("utf-8"))
    return h.hexdigest()[:16]


def empreinte_du_corps(source: str):
    """Empreinte du CODE SEUL, docstrings exclues. `None` si illisible.

    C'est la PREUVE a laquelle une docstring est adossee : si elle bouge sans
    que la prose bouge, la description ne decrit plus ce qu'elle pretend.

    POURQUOI EXCLURE LES DOCSTRINGS, ET POURQUOI CA COMPTE
        Hacher le fichier entier rendrait « suspect » tout module dont on a
        seulement reformule une phrase. Le signal crierait sur des
        clarifications, et un garde qui crie a faux se fait desarmer.

    POURQUOI `ast.dump` ET NON LE TEXTE
        Un commentaire, une indentation ou un saut de ligne ne changent pas ce
        que le code FAIT. L'arbre syntaxique, lui, ne bouge que si le
        comportement decrit peut avoir change.

    `None`, jamais une chaine vide : deux fichiers casses rendraient sinon la
    meme empreinte et passeraient pour identiques.

        ILLISIBLE != VIDE

    STABLE ENTRE INTERPRETEURS (mesure 2026-09-29) : depuis Python 3.13, `ast.dump`
    omet par defaut les champs vides (`show_empty=False`). Les empreintes vues ont ete
    ecrites sous 3.12 ; le hub tourne sous 3.14 : sous 3.14, 2419 modules sortaient
    SUSPECTE au lieu de 229 -- l'instrument mesurait la version de Python, pas le code.
    `show_empty=True` rend le format de 3.12 : meme source, meme empreinte, partout.
    """
    try:
        arbre = ast.parse(source)
    except Exception:  # noqa: BLE001 — muet-ok : l'appelant recoit None et le DIT
        return None
    for noeud in ast.walk(arbre):
        corps = getattr(noeud, "body", None)
        if not isinstance(corps, list) or not corps:
            continue
        if not isinstance(noeud, (ast.Module, ast.FunctionDef,
                                  ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        tete = corps[0]
        if (isinstance(tete, ast.Expr) and isinstance(tete.value, ast.Constant)
                and isinstance(tete.value.value, str)):
            corps.pop(0)                    # la docstring n'est pas la preuve
    options = {"include_attributes": False}
    if sys.version_info >= (3, 13):
        options["show_empty"] = True        # le format de 3.12, ou les empreintes vues sont nees
    return hashlib.sha256(ast.dump(arbre, **options).encode("utf-8")).hexdigest()[:16]


def verdict_docstring(doc_actuelle, doc_vue, corps_actuel, corps_vu) -> str:
    """ALIGNE / SUSPECTE / INCONNU — trois etats, jamais deux.

        ALIGNE    le corps n'a pas bouge depuis la derniere docstring vue,
                  OU la docstring a ete reecrite avec lui (un `confirm`).
        SUSPECTE  le corps a change et la docstring NON : la description
                  decrit un code qui n'existe plus.
        INCONNU   jamais observe, ou source illisible.

    `INCONNU` n'est PAS `ALIGNE`. Un module jamais mesure ne se range pas du
    cote sain : on classe par liste BLANCHE, n'est sain que ce qui est PROUVE
    sain. Une liste NOIRE laisserait toute valeur inattendue tomber du bon
    cote par defaut.
    """
    if corps_actuel is None or corps_vu is None or doc_vue is None:
        return "INCONNU"
    if corps_actuel == corps_vu:
        return "ALIGNE"
    return "ALIGNE" if doc_actuelle != doc_vue else "SUSPECTE"


def frontmatter_okf(titre: str, sha, empreinte: str, type_: str = "reference",
                    status: str = "stable", horodatage: str = None, resource: str = "repo://docs/wiki/20-Modules-Reference.md") -> str:
    """Bloc de provenance OKF v0.2 — ce que `entete_origine` dit, EN LISIBLE MACHINE.

    Nokido posait deja sa provenance dans un commentaire HTML. Un commentaire
    se lit a l'oeil et se parse a la regex ; un frontmatter se VALIDE -- et
    `valider_frontmatter_okf`, juste en dessous, est ce qui le verifie.

        LE PRODUCTEUR ET LE VALIDATEUR SE FONT FACE. Un producteur qui ecrit
        ce que notre propre validateur refuse serait deux moities d'un meme
        contrat qui divergent ; un NR les confronte.

    `generated.by` NOMME l'acteur : sans lui, la provenance ne distingue pas un
    artefact du corps d'un fichier depose a la main. Le sha du depot y est
    accroche, l'empreinte du corpus reste un champ a nous -- OKF ignore ce
    qu'il ne connait pas, et on ne dilue pas son vocabulaire.

    L'instant porte un OFFSET EXPLICITE : sans lui ce n'est pas un instant,
    c'est une heure sans lieu, et deux fuseaux n'y lisent pas le meme moment.
    """
    from datetime import datetime as _dt, timezone as _tz
    quand = horodatage or _dt.now(_tz.utc).isoformat(timespec="seconds")
    acteur = "forge_wiki_modules@%s" % (sha or "INCONNU")
    return "\n".join([
        "---",
        "type: %s" % type_,
        "title: %s" % titre,
        "status: %s" % status,
        "resource: %s" % resource,
        "generated: {by: %s, at: %s}" % (acteur, quand),
        "empreinte: %s" % (empreinte or "INCONNUE"),
        "---",
    ])


_OKF_STATUS = ("draft", "stable", "deprecated")
_OKF_CHAINES = ("type", "title", "description", "resource")


def _instant_okf(brut: str, champ: str, issues: list) -> None:
    """Valide un instant ISO 8601 : OFFSET EXPLICITE et CALENDRIER REEL.

    Sans offset, `2026-09-22T13:57:14` n'est pas un instant : c'est une heure
    sans lieu. Deux corps qui la relisent dans deux fuseaux ne lisent pas le
    meme moment, et la fraicheur devient une opinion.

    Et `2026-02-30T00:00:00+00:00` a la bonne FORME sans exister. On delegue
    donc a `datetime.fromisoformat`, qui connait le calendrier -- une regex ne
    valide qu'une silhouette.
    """
    from datetime import datetime as _dt
    try:
        quand = _dt.fromisoformat(brut.strip())
    except Exception:  # noqa: BLE001 — on RAPPORTE, on ne leve pas
        issues.append({"code": "invalid_datetime", "champ": champ, "valeur": brut})
        return
    if quand.tzinfo is None:
        issues.append({"code": "missing_offset", "champ": champ, "valeur": brut})


def valider_frontmatter_okf(texte: str) -> list:
    """Valide un frontmatter OKF v0.2. Rend une LISTE d'issues, jamais d'exception.

    IL RAPPORTE, IL NE LEVE PAS. Un validateur qui explose a la premiere
    anomalie ne dit qu'UN defaut ; celui qui rend une liste les dit TOUS.
    Mesure du 2026-09-22 : un gate annoncait 12 sites muets quand il y en
    avait 22 -- une borne doit dire COMBIEN.

    Vocabulaire repris d'OKF v0.2 tel que `langchain-ai/openwiki` l'implemente
    (ingere en RAG le meme jour) : `type` est le SEUL champ requis ; `generated`
    et `verified` sont des evenements d'acteur ; `status` est ferme.

    Un `status` inconnu est REFUSE et non tolere : une valeur inattendue ne
    doit pas tomber du cote sain par defaut. Liste BLANCHE, jamais noire.
    """
    issues: list = []
    lignes = (texte or "").splitlines()
    if not lignes or lignes[0].strip() != "---":
        issues.append({"code": "missing_frontmatter"})
        return issues
    fin = next((i for i in range(1, len(lignes)) if lignes[i].strip() == "---"), None)
    if fin is None:
        issues.append({"code": "unterminated_frontmatter"})
        return issues

    champs: dict = {}
    for ligne in lignes[1:fin]:
        if not ligne.strip() or ligne.lstrip() != ligne:
            continue                      # imbrique : hors de ce contrat minimal
        if ":" not in ligne:
            continue
        cle, _, val = ligne.partition(":")
        champs[cle.strip()] = val.strip()

    if "type" not in champs:
        issues.append({"code": "missing_type"})
    for cle in _OKF_CHAINES:
        if cle in champs and not champs[cle]:
            issues.append({"code": "empty_string", "champ": cle})
    if "status" in champs and champs["status"] not in _OKF_STATUS:
        issues.append({"code": "invalid_status", "champ": "status",
                       "valeur": champs["status"], "attendu": list(_OKF_STATUS)})
    for cle in ("generated", "verified"):
        if cle not in champs:
            continue
        trouve = re.search(r"\bat\s*:\s*([^,}\s]+)", champs[cle])
        if trouve:
            _instant_okf(trouve.group(1), cle, issues)
        elif not re.search(r"\bby\s*:", champs[cle]):
            issues.append({"code": "invalid_actor_event", "champ": cle})
    if "stale_after" in champs:
        _instant_okf(champs["stale_after"], "stale_after", issues)
    return issues


def entete_origine(sha, horodatage: str = None, empreinte: str = None) -> str:
    """Le marqueur machine-lisible place en tete de page."""
    return ("<!-- %s outil=tools/forge_wiki_modules.py sha=%s le=%s empreinte=%s -->"
            % (_MARQUEUR, sha or "INCONNU", horodatage or _maintenant_utc(),
               empreinte or "INCONNUE"))


def etat_de_fraicheur(texte: str, sha_actuel, empreinte_actuelle: str = None) -> str:
    """`FRAIS` · `PERIME` · `INCONNU` — classes par liste BLANCHE.

    N'est FRAIS que ce qui est PROUVE frais. Une page sans marqueur (toutes
    celles d'avant ce cliquet) rend INCONNU, jamais FRAIS : c'est la meme
    regle que pour un registre de vitalite sans date, ou un gate dont
    l'artefact est absent.

    Et un HEAD illisible rend INCONNU, pas PERIME : ne pas savoir quel est le
    commit courant n'est pas la preuve d'une derive. Crier au perime dans ce
    cas ferait desarmer le gate au premier faux positif.
    """
    trouve = _RE_ORIGINE.search(texte or "")
    if not trouve:
        return "INCONNU"
    # L'EMPREINTE prime quand les deux cotes en ont une : elle dit si le
    # CONTENU publie a bouge, la ou le sha ne dit que si l'arbre a bouge.
    if empreinte_actuelle:
        sur_page = _RE_EMPREINTE.search(texte or "")
        if sur_page and sur_page.group(1) != "INCONNUE":
            return ("FRAIS" if sur_page.group(1) == empreinte_actuelle
                    else "PERIME")
        return "INCONNU"        # page d'avant ce cliquet : on ne sait pas
    sha_page = trouve.group(1)
    if sha_page == "INCONNU" or not sha_actuel:
        return "INCONNU"
    a, b = sha_page.lower(), str(sha_actuel).lower()
    n = min(len(a), len(b))           # un sha court se compare par prefixe
    return "FRAIS" if a[:n] == b[:n] else "PERIME"


# Habillage localise. Les DEFINITIONS, elles, restent dans les deux pages telles que
# leur auteur les a ecrites (en francais le plus souvent) : les traduire ici ferait une
# seconde source qui divergerait du code -- exactement ce que cette page refuse d'etre.
HABILLAGE = {
    "en": {
        "titre_okf": "Modules Reference",
        "nom": NOM_EN,
        "h1": "# 20 — Modules Reference",
        "langues": "> 🌐 **English** · [Français](%s)" % NOM_FR,
        "avertissement": [
            "> **GENERATED page** — produced by `tools/forge_wiki_modules.py`. Do",
            "> not edit by hand: any correction goes into the **module docstring**,",
            "> the single source of truth. A definition copied here would drift",
            "> from the code within a week.",
        ],
        "origine": ("> Generated from commit `{sha}` on {h}. If this commit is not "
                    "the current HEAD, this page describes an EARLIER state of the "
                    "code: regenerate rather than annotate."),
        "intro": [
            "Each definition is the first sentence of the module docstring, as",
            "written by its author — never a paraphrase of the file name. It is",
            "quoted verbatim, in the language it was written in (mostly French):",
            "a translation here would be a second source, drifting from the code.",
            "Modules **without a docstring** are listed at the end of the page:",
            "they are measured documentation gaps, not display omissions.",
        ],
        "compte": ("**{total} modules** scanned in `app/`, `tools/`, `forge_desktop/` "
                   "(excluding `_attic`) — **{doc} defined ({pct}%)**, "
                   "**{sans} without a docstring**."),
        "api": [
            "The public symbols listed are the API the module exposes (top-level",
            "functions and classes without a leading underscore): what a caller",
            "can use without reading the implementation.",
        ],
        "non_classe": "unclassified",
        "organe": "*{n} modules · {loc} lines*",
        "milliers": ",",
        "virgule": ".",
        "entete": "| Module | Definition | Public API | LOC |",
        "sans_titre": "## Modules without a docstring — measured gaps",
        "sans_texte": [
            "These modules expose no definition. Nothing is invented for them:",
            "adding a module docstring will make its definition appear here at",
            "the next generation.",
        ],
        "sans_entete": "| Module | Public API | LOC |",
    },
    "fr": {
        "titre_okf": "Référence des modules",
        "nom": NOM_FR,
        "h1": "# 20 — Référence des modules",
        "langues": "> 🌐 [English](%s) · **Français**" % NOM_EN,
        "avertissement": [
            "> **Page GÉNÉRÉE** par `tools/forge_wiki_modules.py`. Ne pas éditer à",
            "> la main : toute correction se fait dans la **docstring du module**,",
            "> seule source de vérité. Une définition recopiée ici divergerait du",
            "> code dès la semaine suivante.",
        ],
        "origine": ("> Générée depuis le commit `{sha}` le {h}. Si ce commit n'est pas "
                    "le HEAD courant, cette page décrit un état ANTÉRIEUR du code : "
                    "régénérer plutôt qu'annoter."),
        "intro": [
            "Chaque définition est la première phrase de la docstring du module,",
            "telle qu'écrite par son auteur — jamais une paraphrase du nom de fichier.",
            "Les modules **sans docstring** sont listés en fin de page : ce sont des",
            "trous de documentation mesurés, pas des oublis d'affichage.",
        ],
        "compte": ("**{total} modules** scannés dans `app/`, `tools/`, `forge_desktop/` "
                   "(hors `_attic`) — **{doc} définis ({pct} %)**, "
                   "**{sans} sans docstring**."),
        "api": [
            "Les symboles publics cités sont l'API que le module expose (fonctions et",
            "classes de premier niveau sans soulignement initial) : c'est ce qu'un",
            "appelant peut utiliser sans lire l'implémentation.",
        ],
        "non_classe": "non classé",
        "organe": "*{n} modules · {loc} lignes*",
        "milliers": " ",
        "virgule": ",",
        "entete": "| Module | Définition | API publique | LOC |",
        "sans_titre": "## Modules sans docstring — trous mesurés",
        "sans_texte": [
            "Ces modules n'exposent aucune définition. Rien n'est inventé pour",
            "eux : ajouter une docstring au module fera apparaître sa définition",
            "ici à la prochaine génération.",
        ],
        "sans_entete": "| Module | API publique | LOC |",
    },
}


def cible_fr(out: Path) -> Path:
    """Chemin de la page FR jumelle de `out` : `X.md` -> `X.fr.md`, dans le meme dossier.

    Derivee a chaque appel, jamais figee a l'import : c'est ce qui la rend isolable par
    la seule substitution de `OUT`.
    """
    return out.with_name(out.stem + ".fr" + out.suffix)


def _note_de_date(iso: str, fr: bool) -> str:
    """La note « Mise à jour : » de `forge_docs_datation` -- EMPRUNTEE, jamais recopiee.

    Sans elle, chaque regeneration effacait la note que la datation avait posee. Et si
    ce generateur ecrivait son propre format, lui et `forge_docs_datation --apply` se
    corrigeraient l'un l'autre a chaque passage : deux producteurs, un fichier (meme
    couplage que la note des ports arretes, plus bas dans `main`).
    """
    try:
        from forge_docs_datation import note
    except ImportError:
        from nokido_agent.tools.forge_docs_datation import note
    return note(iso, fr=fr).rstrip("\n")


def rendre(fiches: list[dict], carte: dict,
           sha: str = None, horodatage: str = None, lang: str = "en") -> str:
    """Page de reference dans la langue `lang` (`en` | `fr`) ; une autre langue -> KeyError.

    Les deux langues partagent la collecte, l'empreinte et l'origine : un gate qui
    juge l'une juge l'autre, et seules les phrases de l'habillage different.
    """
    H = HABILLAGE[lang]
    par_organe: dict[str, list[dict]] = {}
    sans_doc: list[dict] = []
    for f in fiches:
        if not f["doc"]:
            sans_doc.append(f)
            continue
        org = (carte.get(f["chemin"].rsplit("/", 1)[-1])
               or carte.get(f["nom"]) or carte.get(f["chemin"]) or H["non_classe"])
        par_organe.setdefault(org, []).append(f)

    total = len(fiches)
    documentes = total - len(sans_doc)
    pct = (100.0 * documentes / total) if total else 0.0

    horodatage = horodatage or _maintenant_utc()
    empreinte = empreinte_du_corpus(fiches)
    L = [
        # PROVENANCE EN DOUBLE, et c'est voulu : le frontmatter OKF pour la
        # machine, le commentaire HTML pour ce qui le lit deja. On AJOUTE, on
        # ne retire rien d'un artefact que d'autres outils consomment peut-etre.
        frontmatter_okf(H["titre_okf"], sha, empreinte,
                        resource="repo://docs/wiki/%s" % H["nom"]),
        entete_origine(sha, horodatage, empreinte),
        "",
        H["h1"],
        "",
        # Meme place que dans les pages ecrites a la main : apres le H1, puis le
        # lien vers la jumelle -- `forge_docs_datation` relit la page INCHANGEE.
        _note_de_date(horodatage[:10], fr=(lang == "fr")),
        "",
        H["langues"],
        "",
        *H["avertissement"],
        ">",
        H["origine"].format(sha=sha or "INCONNU", h=horodatage),
        "",
        *H["intro"],
        "",
        H["compte"].format(total=total, doc=documentes,
                           pct=("%.1f" % pct).replace(".", H["virgule"]),
                           sans=len(sans_doc)),
        "",
        *H["api"],
        "",
    ]

    for org in sorted(par_organe, key=lambda o: (-len(par_organe[o]), o)):
        mods = sorted(par_organe[org], key=lambda f: f["chemin"])
        loc = sum(m["loc"] for m in mods)
        L += [f"## {org}", "",
              H["organe"].format(n=len(mods),
                                 loc=f"{loc:,}".replace(",", H["milliers"])), "",
              H["entete"],
              "|---|---|---|---|"]
        for m in mods:
            api = ", ".join(f"`{s}`" for s in m["publics"][:4]) or "—"
            if len(m["publics"]) > 4:
                api += f" *(+{len(m['publics']) - 4})*"
            doc = m["doc"].replace("|", "\\|")
            L.append(f"| `{m['chemin']}` | {doc} | {api} | {m['loc']} |")
        L.append("")

    if sans_doc:
        L += [H["sans_titre"], "", *H["sans_texte"], "",
              H["sans_entete"], "|---|---|---|"]
        for m in sorted(sans_doc, key=lambda f: -f["loc"]):
            api = ", ".join(f"`{s}`" for s in m["publics"][:4]) or "—"
            L.append(f"| `{m['chemin']}` | {api} | {m['loc']} |")
        L.append("")

    return "\n".join(L)


def verifier() -> int:
    """`--check` — LECTURE SEULE : n'ecrit AUCUN artefact.

    Rend 1 seulement sur `PERIME`, c'est-a-dire quand le contenu a publier a
    reellement change. `INCONNU` rend 0 en le DISANT : ne pas savoir n'est pas
    une faute, mais ce n'est pas un succes non plus — et taire l'ignorance
    ferait exactement le faux calme qu'on corrige ici.

    ⚠️ Le gate ne lit aucun artefact non versionne : `docs/wiki/*.md` est dans
    l'arbre. C'est la lecon du gate `anatomie`, vert 3x en local puis rouge au
    premier passage sur le runner parce qu'il lisait un fichier genere.
    """
    fiches = collecter()
    empreinte = empreinte_du_corpus(fiches)
    sha = sha_du_depot()
    rc = 0
    # Les DEUX pages sont jugees : une jumelle FR perimee sous une page EN fraiche
    # serait le meme faux calme que celui que ce gate a ete pose pour tuer.
    for page in (OUT, cible_fr(OUT)):
        try:
            texte = page.read_text(encoding="utf-8", errors="replace")
        except OSError:
            print("[wiki] page ABSENTE (%s) — NON MESURE, ce n'est pas un succes. "
                  "La produire : tools/forge_wiki_modules.py" % page)
            continue
        etat = etat_de_fraicheur(texte, sha, empreinte_actuelle=empreinte)
        if etat == "FRAIS":
            print("[wiki] FRAIS — %s decrit le corps courant (%d modules)."
                  % (page.name, len(fiches)))
            continue
        if etat == "PERIME":
            print("[wiki] PERIME — %s : le contenu a publier a change depuis la "
                  "generation de la page. Regenerer : tools/forge_wiki_modules.py"
                  % page.name)
            print("[wiki] (empreinte attendue %s ; %d modules scannes)"
                  % (empreinte, len(fiches)))
            rc = 1
            continue
        print("[wiki] INCONNU — %s ne porte pas d'empreinte (generee avant le "
              "cliquet du 2026-09-16), ou le depot est illisible. NON MESURE : "
              "ce n'est ni un succes ni une derive prouvee." % page.name)
    return rc


RATCHET = ROOT / "tests" / "nr" / "docstring_ratchet.json"


def _graver_plafond(sans: int, total: int) -> None:
    """Ecrit le plafond. Seul endroit qui touche `RATCHET` — un fichier de
    reference ecrit depuis deux sites finit par diverger de lui-meme."""
    RATCHET.parent.mkdir(parents=True, exist_ok=True)
    RATCHET.write_text(json.dumps({
        "_doc": "Plafond du nombre de modules SANS docstring. Ne remonte "
                "jamais : `--ratchet` echoue si le vide grandit. S'abaisse "
                "explicitement par `--ratchet --abaisser`.",
        "plafond_sans_docstring": sans,
        "total_au_gel": total,
        "observe_le": _maintenant_utc(),
        "sha": sha_du_depot() or "INCONNU",
    }, indent=2) + "\n", encoding="utf-8")


def verifier_ratchet(abaisser: bool = False) -> int:
    """`--ratchet` — le nombre de modules SANS docstring ne doit pas augmenter.

    POURQUOI UN CLIQUET ET PAS UNE CIBLE (2026-09-16). 871 modules vivants sont
    sans docstring. Exiger de tout combler d'un coup produirait soit un gate
    rouge en permanence (donc desarme), soit des docstrings INVENTEES depuis le
    nom du fichier — le filet essaye le 2026-07-25 puis RETIRE, parce qu'une
    etiquette inventee se propage en RAG et dans l'atlas ou plus rien ne la
    distingue d'une mesure.

    Le cliquet ne demande donc pas de combler : il interdit d'AGGRAVER. Meme
    forme que `forge_mutation_ratchet` et `test_nr_coverage_ratchet_nr`.

    LECTURE SEULE par defaut. L'abaissement du plafond est un geste EXPLICITE
    (`--abaisser`) : un fichier de reference qui se reecrit a chaque run
    salirait l'arbre, et un arbre sale empeche la CI de capturer un sha.
    """
    fiches = collecter()
    sans = sum(1 for f in fiches if not f["doc"])
    try:
        ref = json.loads(RATCHET.read_text(encoding="utf-8"))
        plafond = int(ref.get("plafond_sans_docstring"))
    except (OSError, ValueError, TypeError):
        if abaisser:
            # ⚠️ DEFAUT CORRIGE ICI (2026-09-16, trouve sur le chemin REEL).
            # Cette branche rendait 0 SANS ecrire, alors que son propre message
            # disait « L'initialiser : --ratchet --abaisser ». Le message
            # promettait donc un geste que le code ne faisait pas — meme
            # famille que le commentaire qui promet un garde absent, paye le
            # meme jour sur le gate UI. Un mode d'emploi qui ne marche pas est
            # pire qu'une absence de mode d'emploi.
            _graver_plafond(sans, len(fiches))
            print("[ratchet] INITIALISE a %d sans docstring sur %d modules."
                  % (sans, len(fiches)))
            return 0
        print("[ratchet] plafond ABSENT ou illisible — NON MESURE, ce n'est pas "
              "un succes. L'initialiser : forge_wiki_modules.py --ratchet --abaisser")
        print("[ratchet] etat courant : %d sans docstring sur %d" % (sans, len(fiches)))
        return 0
    if sans > plafond:
        print("[ratchet] REGRESSION — %d modules sans docstring, plafond %d "
              "(+%d). Un module NEUF doit porter sa docstring : elle est la "
              "seule source de sa definition au wiki."
              % (sans, plafond, sans - plafond))
        return 1
    if sans < plafond and abaisser:
        _graver_plafond(sans, len(fiches))
        print("[ratchet] ABAISSE %d -> %d (sur %d modules)"
              % (plafond, sans, len(fiches)))
        return 0
    if sans < plafond:
        print("[ratchet] PROGRES — %d sans docstring, plafond %d. Graver ce "
              "gain : --ratchet --abaisser" % (sans, plafond))
        return 0
    print("[ratchet] STABLE — %d sans docstring sur %d (plafond tenu)."
          % (sans, len(fiches)))
    return 0


def verifier_bruit() -> int:
    """`--bruit` — LECTURE SEULE : produit le comptage réel (L3)."""
    cards_path = CARDS
    if not cards_path.exists():
        print("[bruit] INCONNU : forge_card_summaries.json absent.")
        return 0
    try:
        data = json.loads(cards_path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        print("[bruit] INCONNU : forge_card_summaries.json illisible.")
        return 0
        
    fiches = collecter()
    aligne = suspecte = inconnu = 0
    
    for f in fiches:
        chemin = f["chemin"]
        doc_actuelle = f.get("doc", "")
        try:
            source = (ROOT / chemin).read_text(encoding="utf-8", errors="replace")
            corps_actuel = empreinte_du_corps(source)
        except OSError:
            corps_actuel = None
            
        if chemin in data:
            doc_vue = data[chemin].get("docstring_vue")
            corps_vu = data[chemin].get("empreinte_vue")
            if corps_vu == "INCONNUE":
                corps_vu = None
        else:
            doc_vue = corps_vu = None
            
        verdict = verdict_docstring(doc_actuelle, doc_vue, corps_actuel, corps_vu)
        if verdict == "ALIGNE":
            aligne += 1
        elif verdict == "SUSPECTE":
            suspecte += 1
        else:
            inconnu += 1
            
    print(f"[bruit] {len(fiches)} modules mesures :")
    print(f"        ALIGNE   : {aligne}")
    print(f"        SUSPECTE : {suspecte}")
    print(f"        INCONNU  : {inconnu}")
    return 0

def _annoter_ports(cible: Path) -> None:
    """Chaine la note des ports arretes sur `cible` (une page de la paire)."""
    # ⚠️ COUPLAGE MESURE LE 2026-09-17, et paye dans la foulee.
    # `forge_docs_port_annotate` insere apres le H1 une note de peremption qui
    # nomme les ports ARRETES cites dans la page (`:5557` est mort depuis le
    # 2026-06-03, `:7474` et `:8100` depuis le 2026-08-10). Cette note a ete
    # prise pour une rustine bricolee et EFFACEE par la premiere regeneration
    # du jour -- aussitot, le gate BLOQUANT `capacites (README vs code)` a
    # rougi : « 5557 cite comme vivant ». Ce n'etait donc pas du bruit, c'etait
    # une mesure que ce generateur ne produit pas.
    # Deux producteurs ecrivant le meme fichier, l'un effacant l'autre. On
    # CHAINE ici, au lieu de compter sur un agent pour y penser apres coup.
    try:
        try:
            from forge_docs_port_annotate import traiter as _annoter
        except ImportError:
            from nokido_agent.tools.forge_docs_port_annotate import traiter as _annoter
        _annoter(cible, True)
        # MESURER l'effet, ne pas annoncer l'intention : la premiere version de
        # cette ligne imprimait « reappliquee » meme quand rien n'avait ete
        # ecrit. Un message qui decrit ce qu'on a TENTE fait croire a un effet.
        _pose = "ports-arretes" in cible.read_text(encoding="utf-8", errors="replace")
        print("[wiki] note des ports arretes (%s) : %s"
              % (cible.name, "POSEE" if _pose else "aucun port arrete cite — rien a annoter"))
    except Exception as exc:   # noqa: BLE001
        # Ne JAMAIS avaler : sans la note, la page cite un port mort comme
        # vivant, et c'est un gate bloquant qui le decouvrira a la CI.
        print("[wiki] annotation des ports arretes IMPOSSIBLE sur %s (%s: %s) — la "
              "page peut citer un port ARRETE comme vivant ; lancer "
              "tools/forge_docs_port_annotate.py --apply"
              % (cible.name, type(exc).__name__, exc))


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--bruit" in argv:
        return verifier_bruit()
    if "--ratchet" in argv:
        return verifier_ratchet(abaisser="--abaisser" in argv)
    if "--check" in argv:
        return verifier()
    fiches = collecter()
    carte = organes()
    if not carte:
        print("[wiki] carte des organes absente ou illisible -> tout en 'non classe' "
              "(regenerer via tools/forge_module_census.py)")
    sha = sha_du_depot()
    if ECARTES:
        print("[wiki] %d fichier(s) ECARTE(S) du corpus (backups, archives, "
              "tmp_, vendored) — comptes, pas caches." % len(ECARTES))
    if ILLISIBLES:
        print("[wiki] %d fichier(s) ILLISIBLE(S) — comptes, pas caches :"
              % len(ILLISIBLES))
        for c in ILLISIBLES[:10]:
            print("         %s" % c)
        if len(ILLISIBLES) > 10:
            print("         ... (%d autres)" % (len(ILLISIBLES) - 10))
    if sha is None:
        print("[wiki] sha de HEAD ILLISIBLE -> la page sortira en 'INCONNU'. "
              "Ce n'est pas un echec, mais sa fraicheur ne sera pas mesurable.")
    # UN horodatage pour la paire : les deux pages decrivent le meme instant du corps.
    horodatage = _maintenant_utc()
    for cible, lang in ((OUT, "en"), (cible_fr(OUT), "fr")):
        texte = rendre(fiches, carte, sha=sha, horodatage=horodatage, lang=lang)
        cible.parent.mkdir(parents=True, exist_ok=True)
        cible.write_text(texte, encoding="utf-8")
        _annoter_ports(cible)
        print(f"[wiki] {len(fiches)} modules -> {cible}")
        print(f"[wiki] {len(texte.encode('utf-8'))} octets ecrits ({lang})")
    sans = sum(1 for f in fiches if not f["doc"])
    print(f"[wiki] definis: {len(fiches) - sans} | sans docstring: {sans}")
    # (le chainage de la note des ports arretes vit dans `_annoter_ports`, appele
    # pour CHAQUE page de la paire : la page FR cite les memes ports.)
    
    # L2 : persister l'empreinte du corps et la docstring
    cards_path = CARDS
    if cards_path.exists():
        try:
            cards_data = json.loads(cards_path.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError:
            cards_data = {}
    else:
        cards_data = {}
        
    now = _maintenant_utc()
    from forge_wiki_modules import empreinte_du_corps
    for f in fiches:
        chemin = f["chemin"]
        if chemin not in cards_data:
            cards_data[chemin] = {}
        
        cards_data[chemin]["docstring_vue"] = f.get("doc", "")
        
        # We need the original source for empreinte_du_corps since f only has parsed doc
        try:
            source = (ROOT / chemin).read_text(encoding="utf-8", errors="replace")
            empreinte = empreinte_du_corps(source)
            cards_data[chemin]["empreinte_vue"] = empreinte if empreinte is not None else "INCONNUE"
        except OSError:
            cards_data[chemin]["empreinte_vue"] = "INCONNUE"
            
        cards_data[chemin]["vu_le"] = now
        
    if "--check" not in argv: # ne pas ecrire si LECTURE SEULE
        cards_path.write_text(json.dumps(cards_data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    return 0


if __name__ == "__main__":
    sys.exit(main())
