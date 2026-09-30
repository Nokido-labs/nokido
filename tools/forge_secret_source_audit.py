#!/usr/bin/env python3
"""forge_secret_source_audit — QUI lit un secret sans passer par le coffre.

__FORGE_COLOR__ = "immunitaire/secrets-au-coffre"

COMPLEMENTAIRE de `forge_secret_audit`, qui inspecte le CONTENU du coffre
(placeholders, cles vides). Celui-ci inspecte les LECTURES dans le code : un secret
lu directement dans `os.environ` contourne `forge_secrets` et donc l'ordre de
priorite voulu (DPAPI machine -> WCM -> Nokido.env -> environnement, ce dernier
avec un WARNING).

POURQUOI CE N'EST PAS UNE COQUETTERIE. Mesure du 2026-09-03 : l'environnement est
la couche la MOINS fiable du poste, parce qu'aucune rotation ne la met a jour.
Trois variables persistantes portaient des jetons revoques, et l'une d'elles
(`FORGE_BRIDGE_TOKEN`, cote Claude Desktop) a tenu le pont stdio en 401 pendant des
heures alors que le coffre ET le fichier de config portaient la bonne valeur. Lire
`os.environ` en PREMIER, c'est faire confiance a la seule couche qu'on ne rote pas.

TROIS ETATS, jamais deux :
  HORS COFFRE  lecture directe d'un secret dans l'environnement, sans repli visible
               vers le coffre -> a corriger.
  REPLI        `get_secret()` apparait juste avant sur la meme cle : l'environnement
               n'est alors que le dernier recours, ce qui est le contrat.
  EXEMPT       fichier dont c'est le role (`forge_secrets` est LUI-MEME la couche
               environnement) ou qui ne s'execute pas en production (tests, patches).

CLIQUET. 55 sites existaient au recensement du 2026-09-03 : echouer sur leur seule
presence rendrait le gate rouge en permanence, donc ignore en une semaine. Le gate
refuse ce qui est NOUVEAU par rapport au socle, et signale ce qui a ete resolu sans
jamais l'exiger. Un socle ne remonte pas : une ligne resolue est retiree au prochain
`--ecrire-socle`, jamais reintroduite.

La cle du socle est `fichier::CLE`, sans numero de ligne : un socle indexe sur les
lignes deviendrait faux a la premiere edition et noierait le vrai signal.

Sortie : rc=1 s'il existe une lecture NOUVELLE. Idiome identique a `duplication`
et `golden-rules` (`--ecrire-socle`).
Usage : LAFORGE_PYTHON tools/forge_secret_source_audit.py [--tout] [--ecrire-socle]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Un nom de secret, pas n'importe quelle variable : PATH ou USERNAME ne sont pas
# des secrets, et les confondre noierait le signal.
# `_KEY$` ajoute le 2026-09-20. Le motif attrapait `API_KEY` mais PAS `_KEY`
# terminal : six lectures hors coffre passaient donc sous le radar depuis
# l'origine de l'instrument, dont LAFORGE_DB_KEY -- la cle de chiffrement de la
# base, lue DEUX fois dans l'environnement -- et LAFORGE_HUB_TLS_KEY.
# Mesure de l'elargissement : 54 -> 60 findings, SIX nouveaux, ZERO bruit.
# Un instrument qui ne detecte pas ce qu'il cherche ne mesure pas le depot, il
# mesure son propre motif.
NOM_SECRET = re.compile(r"(TOKEN|API_KEY|_KEY$|SECRET|PASSWORD|PASSWD|_PWD|CREDENTIAL)")
# UN NOM N'EST PAS UNE PREUVE. Le filtre ci-dessus attrape des REGLAGES qui portent
# le mot-cle sans etre des secrets : TOKENIZERS_PARALLELISM (HuggingFace),
# ONNXGENAI_MAX_TOKENS (un entier), LAFORGE_KEY_SECRET_TTL (une duree),
# LAFORGE_ALLOW_SECRETS_READ (un drapeau). Les signaler comme « hors coffre »
# ferait crier l'instrument a faux — et un garde qui crie a faux finit desarme.
# Meme famille que le 64-hex du 2026-09-03 qui etait un userID, pas une cle.
# Un secret est une VALEUR D'AUTHENTIFICATION, pas un parametre de comportement.
NON_SECRET = re.compile(
    # `_MODEL$` ajoute le 2026-09-20 : un NOM DE MODELE est un reglage, au meme
    # titre que `_MODE$` deja present (LMSTUDIO_MODEL, GEMINI_MODEL). Sans
    # effet sur `scanner`, qui teste `NOM_SECRET` AVANT `NON_SECRET` : ce motif
    # ne peut donc que retirer des signalements pour des cles portant deja un
    # marqueur de secret, jamais en ajouter.
    # `_FILE$` et `_DIRECTORY$` ajoutes le 2026-09-28 : `X_TOKEN_FILE` (convention
    # Docker `*_FILE`) et `CREDENTIALS_DIRECTORY` (systemd `LoadCredential`) portent un
    # CHEMIN ; le secret vit dans le fichier, que la rotation met a jour. Meme famille
    # que `_PATH$`/`_DIR$`, et `forge_env_to_vault` les laissait deja passer
    # (test_secret_migration_nr) : l'instrument etait incoherent avec la migration.
    r"(TOKENIZERS?_|_PARALLELISM|MAX_TOKENS|_TTL$|^LAFORGE_ALLOW_|_READ$|"
    r"_ENABLED$|_MODE$|_MODEL$|_TIMEOUT$|_BUDGET$|_LIMIT$|_COUNT$|_PATH$|_DIR$|_URL$|"
    r"_FILE$|_DIRECTORY$)")
LECTURE = re.compile(
    r"""(?:os\.environ\.get|os\.getenv|environ\.get|getenv)\(\s*["']([A-Z0-9_]+)["']"""
    r"""|os\.environ\[\s*["']([A-Z0-9_]+)["']\s*\]""")

# Fichiers dont la lecture directe est LEGITIME.
EXEMPTS = {
    "app/forge_secrets.py",            # il EST la couche environnement
    "app/forge_machine_vault.py",      # couche DPAPI
    "app/forge_env_crypt.py",          # couche fichier chiffre
    "tools/forge_secret_source_audit.py",
}
PREFIXES_EXEMPTS = ("tests/", "tools/patch_", "tools/forge_patch_", "sandbox/",
                    "archive/", "app/_attic/")


def _exempt(rel: str) -> bool:
    r = rel.replace("\\", "/")
    return r in EXEMPTS or r.startswith(PREFIXES_EXEMPTS)


def scanner(tout: bool = False, racine: Path | None = None,
            bases: tuple[str, ...] = ("app", "tools")) -> tuple[list, dict]:
    """`racine`/`bases` : parametres pour que le CLIQUET soit EPROUVABLE.

    Un garde qu'on ne peut pas faire virer au rouge dans un test n'est pas une
    securite, c'est une dette de cablage : on croit protege ce qui ne l'est pas.
    Le defaut reste le depot, les tests passent un dossier jetable.
    """
    base_dir = racine or ROOT
    trouves: list[tuple[str, int, str, str]] = []
    stats = {"fichiers_lus": 0, "illisibles": 0, "exempts": 0}
    for base in bases:
        if not (base_dir / base).is_dir():
            continue
        for f in sorted((base_dir / base).rglob("*.py")):
            rel = str(f.relative_to(base_dir)).replace("\\", "/")
            if _exempt(rel):
                stats["exempts"] += 1
                continue
            try:
                lignes = f.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                # Un fichier qu'on n'a PAS PU lire n'est pas un fichier sain :
                # sans ce compteur, la couverture serait surestimee en silence.
                stats["illisibles"] += 1
                continue
            stats["fichiers_lus"] += 1
            for i, ligne in enumerate(lignes):
                for m in LECTURE.finditer(ligne):
                    cle = m.group(1) or m.group(2) or ""
                    if not NOM_SECRET.search(cle) or NON_SECRET.search(cle):
                        continue
                    fenetre = "\n".join(lignes[max(0, i - 12):i + 3])
                    etat = "REPLI" if ("get_secret" in fenetre or "resolve(" in fenetre) \
                        else "HORS COFFRE"
                    if etat == "HORS COFFRE" or tout:
                        trouves.append((rel, i + 1, cle, etat))
    return trouves, stats


# --- INVENTAIRE DES CLES DEMANDEES AU COFFRE ---------------------------------
#
# Symetrique de `scanner` : celui-la repond « QUI lit un secret SANS passer par
# le coffre », celle-ci repond « que le coffre DOIT-il contenir ». Meme parcours,
# memes exemptions, memes compteurs -- on etend la brique qui porte deja la
# moitie du contrat plutot que d'en poser une seconde a cote.
#
# MESURE QUI LA MOTIVE (2026-09-20) : `forge_secrets.diagnostic()` connait 26
# cles CODEES EN DUR quand le code en demande 74 sur 219 sites. 72 % du coffre
# est invisible a son propre audit -- le meme motif que `health_check` et sa
# table de ports en dur.

# --- NATURE D'UNE CLE (phase 2) ----------------------------------------------
#
# `get_secret` sert a la fois de coffre ET de lecteur de configuration : sur les
# 53 cles de l'angle mort mesurees le 2026-09-20, 9 etaient de simples reglages
# (CACHE_MIN_TOKENS, GEMINI_MODEL, LMSTUDIO_MODEL...). On ne peut pas segmenter
# par organe ce qui n'est meme pas distingue du parametrage : la separation est
# un PREALABLE a la segmentation cryptographique, pas un raffinement ulterieur.
#
# Le classement REUTILISE NOM_SECRET / NON_SECRET ci-dessus. Ecrire une seconde
# heuristique ici, c'est garantir qu'elles divergeront en silence.
#
# CREDENTIAL_INTERNE vs SECRET_EXTERNE n'est pas une nuance de vocabulaire :
# c'est la procedure de rotation (phase 9) qui change. Un jeton emis par le
# corps se roule par un geste LOCAL et se revoque ; une cle de fournisseur ne se
# « roule » qu'en allant sur le site du tiers, et nous ne pouvons pas la
# revoquer -- seulement cesser de l'utiliser. Les confondre, c'est promettre une
# rotation qu'on ne sait pas tenir.
_INTERNE = re.compile(r"^(FORGE_TOKEN_|LAFORGE_)|_(ADMIN|SUPERVISOR|HUB|MCP|BRIDGE)_TOKEN$")
_TROP_GENERIQUE = re.compile(r"^(CLE|NOM_CLE|KEY|TOKEN|SECRET|VALUE|NAME)$")


def nature(cle: str) -> dict:
    """Classe une cle par son NOM. Ne lit aucune valeur.

    Rend `{"nature", "pourquoi", "trancher"}` et jamais une simple etiquette :
    un INDETERMINE qui ne dit pas ce qui le leverait est un cul-de-sac.
    """
    if _TROP_GENERIQUE.match(cle) or len(cle) < 5:
        return {
            "nature": "INDETERMINE",
            "pourquoi": "nom trop generique pour etre classe par son nom seul "
                        "-- litteral de test ou de migration passe par la voie "
                        "de production",
            "trancher": "lire le SITE d'appel (l'inventaire le porte) et "
                        "demander a son proprietaire ; a defaut, retirer l'appel",
        }
    if NON_SECRET.search(cle):
        return {
            "nature": "CONFIG",
            "pourquoi": "parametre de COMPORTEMENT, pas valeur d'authentification",
            "trancher": "",
        }
    if not NOM_SECRET.search(cle):
        return {
            "nature": "INDETERMINE",
            "pourquoi": "ne porte aucun marqueur de secret (KEY/TOKEN/SECRET/PASS) "
                        "ni de reglage connu",
            "trancher": "lire le site d'appel : ce qui transite par get_secret "
                        "sans marqueur est le plus souvent de la CONFIG egaree",
        }
    if _INTERNE.search(cle):
        return {
            "nature": "CREDENTIAL_INTERNE",
            "pourquoi": "jeton emis par le corps -- rotable et REVOCABLE localement",
            "trancher": "",
        }
    return {
        "nature": "SECRET_EXTERNE",
        "pourquoi": "credential d'un tiers -- nous ne pouvons pas le revoquer, "
                    "seulement cesser de l'utiliser",
        "trancher": "",
    }


# --- PROVENANCE : a quel organe appartient une cle ? (phase 3) ---------------
#
# SEARCH BEFORE BUILD : aucun registre de provenance de CLES n'existe
# (`introspect` + sweep ; `forge_session_provenance` trace des SESSIONS). En
# revanche la carte module -> organe EXISTE et est peuplee -- 1755 modules
# classes dans `sandbox/workspace/organ_map_full.json`, regeneree par
# `tools/forge_module_census.py` a partir des declarations `__FORGE_COLOR__`.
#
# On DERIVE donc la provenance de cette carte plutot que d'ouvrir un second
# registre : deux registres du meme fait divergent toujours, et c'est le premier
# qu'on oublie de mettre a jour.
_CARTE_ORGANES = ROOT / "sandbox" / "workspace" / "organ_map_full.json"

# VIDE PAR CHOIX. Declarer qu'une cle est partagee « par conception » RETIRE une
# question de la liste a instruire : c'est une decision de GOUVERNANCE, pas une
# observation d'instrument. L'outil mesure et expose ; il ne s'auto-absout pas.
# Mesure du 2026-09-20, a instruire par l'owner : FORGE_MCP_TOKEN traverse 14
# organes sur 47 sites, FORGE_TOKEN_CLAUDE 6 organes, GITHUB_TOKEN 5.
_PARTAGES_DECLARES: dict = {}


def proprietaires(racine: Path | None = None,
                  bases: tuple[str, ...] = ("app", "tools"),
                  carte: Path | None = None,
                  partages_declares: dict | None = None) -> tuple[dict, dict]:
    """Qui possede quoi -- et surtout, qu'est-ce qu'on ignore.

    Rend `(provenance, stats)`. Le verdict appartient a un ensemble FERME :

        OWNER_PROVEN        tous les sites dans UN seul organe
        SHARED_BY_DESIGN    plusieurs organes, partage DECLARE (avec sa raison)
        SHARED_UNEXPLAINED  plusieurs organes, aucun contrat -- A INSTRUIRE
        OWNER_UNKNOWN       des sites REELS, mais l'organe n'est pas connaissable
        ORPHAN              aucun site : declaree et jamais demandee

    INVARIANT : une carte d'organes illisible rend OWNER_UNKNOWN pour tout le
    monde, JAMAIS ORPHAN. Confondre « je n'ai pas pu lire la carte » avec
    « cette cle n'a pas de proprietaire » fabriquerait des orphelins par panne
    d'instrument -- l'erreur que ce mandat interdit nommement.

    N modules dans UN organe n'est PAS un defaut (directive owner) : seul le
    partage ENTRE organes est une question.

    Aucune valeur de secret n'est lue : on derive de NOMS, de CHEMINS et d'une
    carte de modules.
    """
    import json as _json

    base_dir = racine or ROOT
    chemin_carte = carte or _CARTE_ORGANES
    declares = _PARTAGES_DECLARES if partages_declares is None else partages_declares

    module_organ: dict = {}
    etat_carte = "ABSENTE"
    try:
        brut = _json.loads(Path(chemin_carte).read_text(encoding="utf-8",
                                                        errors="replace"))
        module_organ = brut.get("module_organ") or {}
        etat_carte = "LUE"
    except OSError as exc:
        etat_carte = "ILLISIBLE (%s)" % exc.__class__.__name__
    except ValueError as exc:
        etat_carte = "NON PARSABLE (%s)" % exc.__class__.__name__

    cles, stats_cles = cles_demandees(racine=base_dir, bases=bases)
    stats = dict(stats_cles)
    stats["carte"] = etat_carte
    stats["modules_classes"] = len(module_organ)

    prov: dict = {}
    for nom, fiche in cles.items():
        sites = fiche.get("sites") or []
        organes: dict = {}
        sans: list = []
        for s in sites:
            o = module_organ.get(Path(s).name)
            if o:
                organes.setdefault(o, []).append(s)
            else:
                sans.append(s)

        contrat = declares.get(nom)
        if not sites:
            verdict, instruire = "ORPHAN", ""
        elif not organes:
            verdict = "OWNER_UNKNOWN"
            instruire = ("declarer __FORGE_COLOR__ dans %d module(s), puis "
                         "regenerer le census -- ne PAS inventer un proprietaire"
                         % len(sans))
        elif len(organes) == 1:
            verdict, instruire = "OWNER_PROVEN", ""
        elif contrat:
            verdict, instruire = "SHARED_BY_DESIGN", ""
        else:
            verdict = "SHARED_UNEXPLAINED"
            instruire = ("%d organes consomment cette cle sans contrat : soit "
                         "declarer le partage et sa raison, soit segmenter"
                         % len(organes))

        prov[nom] = {
            "verdict": verdict,
            "nature": fiche.get("nature"),
            # La nature voyage AVEC sa justification : un appelant qui devrait
            # la recalculer produirait un second classement.
            "nature_pourquoi": fiche.get("pourquoi", ""),
            "nature_trancher": fiche.get("trancher", ""),
            "organes": sorted(organes),
            "sites": sites,
            "sites_sans_organe": sans,
            "occurrences": fiche.get("occurrences", 0),
            "contrat": contrat or "",
            "instruire": instruire,
        }
    return prov, stats


def masquer(cle: str, valeur) -> str:
    """Representation AFFICHABLE d'une valeur, commandee par la NATURE de la cle.

    C'est ici que le classement des phases 2 et 3 cesse d'etre une etiquette et
    devient une POLITIQUE. Mesure du 2026-09-21 avant ce maillon : les natures
    etaient exposees et consultees par ZERO site hors des modules qui les
    definissent -- une abstraction qui ne ferme aucune transition est une dette.

        SECRET_EXTERNE / CREDENTIAL_INTERNE -> empreinte publique
        INDETERMINE                         -> empreinte publique (FAIL-CLOSED)
        CONFIG                              -> valeur LISIBLE

    JAMAIS DE FRAGMENT. Ni prefixe, ni suffixe, ni « les quatre premiers ». Un
    fragment revele du materiel ET ne permet pas de comparer deux instances ;
    une empreinte fait exactement l'inverse. Mesure qui motive la regle :
    `forge_secret_audit._mask` rendait `val[:4]` sur stdout, et le CLI de
    `forge_secrets` rendait `val[-4:]` -- corriger l'un n'avait pas corrige
    l'autre.

    CONFIG reste lisible A DESSEIN : le masquer le rendrait « secret par simple
    convention », ce que le mandat interdit, et ferait perdre la lisibilite
    d'un parametre de comportement.

    Le DOUTE PROTEGE : une cle qu'on ne sait pas classer est traitee comme un
    secret. Masquer un reglage gene une lecture ; afficher un secret le publie.
    """
    nat = nature(cle)["nature"]
    if valeur is None or str(valeur) == "":
        return "%s ABSENTE" % nat
    if nat == "CONFIG":
        return "%s %s" % (nat, valeur)
    import hashlib
    brut = str(valeur).encode("utf-8", "replace")
    return "%s empreinte(sha256/12)=%s len=%d" % (
        nat, hashlib.sha256(brut).hexdigest()[:12], len(str(valeur)))


_ALIAS_GS = re.compile(r"import\s+get_secret\s+as\s+(\w+)")
_REQUIRE = re.compile(r'require\(\s*((?:["\'][A-Z][A-Z0-9_]{2,}["\']\s*,?\s*)+)\)')
_NOM_LITTERAL = re.compile(r'["\']([A-Z][A-Z0-9_]{2,})["\']')


def cles_demandees(racine: Path | None = None,
                   bases: tuple[str, ...] = ("app", "tools")) -> tuple[dict, dict]:
    """Noms passes au guichet des secrets, avec leurs sites d'appel.

    Rend `(cles, stats)`. `cles[nom] = {"occurrences": n, "sites": [...]}`.

    AUCUNE VALEUR N'EST LUE : on lit du TEXTE SOURCE et on n'ouvre aucun coffre.
    Un audit qui consommerait des secrets pour les compter serait lui-meme une
    surface d'exposition.

    `stats` porte `fichiers_lus` / `illisibles` / `exempts` : un instrument qui
    ecarte des fichiers sans le dire surestime sa couverture en silence.
    """
    base_dir = racine or ROOT
    cles: dict = {}
    stats = {"fichiers_lus": 0, "illisibles": 0, "exempts": 0}

    def _ajouter(nom: str, rel: str) -> None:
        fiche = cles.setdefault(nom, {"occurrences": 0, "sites": [], **nature(nom)})
        fiche["occurrences"] += 1
        if rel not in fiche["sites"]:
            fiche["sites"].append(rel)

    for base in bases:
        if not (base_dir / base).is_dir():
            continue
        for f in sorted((base_dir / base).rglob("*.py")):
            rel = str(f.relative_to(base_dir)).replace("\\", "/")
            if _exempt(rel):
                stats["exempts"] += 1
                continue
            try:
                txt = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                # Un fichier qu'on n'a PAS PU lire laisse un TROU dans
                # l'inventaire : le taire ferait croire l'audit complet.
                stats["illisibles"] += 1
                continue
            stats["fichiers_lus"] += 1
            # Les alias sont DECLARES dans le fichier : on les lit au lieu de
            # les deviner. `get_secret as _gs` / `_gs_gh` / `_gs_w` sont les
            # formes reelles du depot (forge_llm_router, forge_mcp_registry,
            # forge_embed_router) -- ne chercher que `get_secret(` sous-compte
            # sans que rien ne le signale.
            noms = {"get_secret"} | set(_ALIAS_GS.findall(txt))
            appel = re.compile(
                r"(?:%s)\(\s*[\"']([A-Z][A-Z0-9_]{2,})[\"']"
                % "|".join(sorted(re.escape(n) for n in noms))
            )
            for m in appel.finditer(txt):
                _ajouter(m.group(1), rel)
            for m in _REQUIRE.finditer(txt):
                for k in _NOM_LITTERAL.findall(m.group(1)):
                    _ajouter(k, rel)
    return cles, stats


# Nom SANS « _secrets » : `.gitignore:92` ecarte `*_secrets*`, une protection large
# contre l'ajout accidentel d'un fichier de secrets. Ce socle n'en contient aucun
# (des chemins et des NOMS de variables, zero valeur), mais un cliquet dont le socle
# n'est pas versionne ne rend aucun verdict ailleurs que sur la machine qui l'a
# genere — il serait donc inoperant en CI. Entre forcer `git add -f` contre une regle
# de securite et nommer le fichier pour ce qu'il est, on nomme.
SOCLE = ROOT / "tests" / "nr" / "_socle_lecture_hors_coffre.json"


def _lire_socle() -> set[str] | None:
    """-> l'ensemble gele, ou None si ILLISIBLE/absent.

    None n'est PAS un ensemble vide : sans socle lisible, tout site paraitrait
    nouveau et le gate crierait sur 55 lignes d'un coup. On le DIT et on
    s'abstient de juger, plutot que d'inventer un verdict."""
    import json
    try:
        return set(json.loads(SOCLE.read_text(encoding="utf-8")))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        print("  /!\\ socle ILLISIBLE (%s) : aucun verdict de cliquet rendu."
              % type(e).__name__)
        return None


def main(argv=None) -> int:
    import json

    argv = sys.argv[1:] if argv is None else argv
    trouves, stats = scanner(tout="--tout" in argv)
    hors = [t for t in trouves if t[3] == "HORS COFFRE"]
    cles = {"%s::%s" % (rel, cle) for rel, _l, cle, etat in trouves if etat == "HORS COFFRE"}

    print("=== LECTURES DE SECRETS HORS COFFRE ===")
    print("fichiers lus %d · exempts %d · ILLISIBLES %d"
          % (stats["fichiers_lus"], stats["exempts"], stats["illisibles"]))
    if stats["illisibles"]:
        print("  /!\\ %d fichier(s) non lu(s) : leur etat est INCONNU, pas sain."
              % stats["illisibles"])

    if "--ecrire-socle" in argv:
        SOCLE.parent.mkdir(parents=True, exist_ok=True)
        SOCLE.write_text(json.dumps(sorted(cles), indent=1, ensure_ascii=False),
                         encoding="utf-8")
        print("socle ECRIT : %d site(s) geles dans %s" % (len(cles), SOCLE.name))
        return 0

    socle = _lire_socle()
    for rel, ligne, cle, etat in trouves:
        neuf = socle is not None and "%s::%s" % (rel, cle) not in socle
        print("  %-11s %-52s:%-5d %-24s%s"
              % (etat, rel, ligne, cle, "  <<< NOUVEAU" if neuf else ""))

    if socle is None:
        print("--- %d hors coffre. Socle absent : lancer --ecrire-socle pour armer "
              "le cliquet." % len(hors))
        return 0
    nouveaux = sorted(cles - socle)
    resolus = sorted(socle - cles)
    if resolus:
        print("--- %d site(s) RESOLU(S) depuis le socle — le regeler pour l'acter :"
              % len(resolus))
        for r in resolus[:10]:
            print("      %s" % r)
    if nouveaux:
        print("--- CLIQUET ROUGE : %d lecture(s) NOUVELLE(S) hors coffre :" % len(nouveaux))
        for n in nouveaux:
            print("      %s" % n)
        print("    Passer par forge_secrets.get_secret() — l'environnement est la "
              "seule couche qu'aucune rotation ne met a jour.")
        return 1
    print("--- cliquet OK — aucune lecture nouvelle (%d au socle, %d vue(s))"
          % (len(socle), len(cles)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
