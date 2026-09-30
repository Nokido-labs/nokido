r"""NR — inventaire GARDE DE ROUTE x CAPACITE DU MODULE ATTEINT.

MESURE DU 2026-09-21. P1-D de la campagne longue.

CE QU'AUCUN DES TROIS OBSERVATEURS EXISTANTS NE VOIT
====================================================
`forge_authz_matrice` croise trois observateurs independants -- statique,
sonde HTTP, runtime -- et nomme l'angle mort de chacun. Les trois regardent la
ROUTE. Aucun ne regarde ce que le handler ATTEINT.

C'est ainsi que `/api/watch/create` avait echappe a tout : le handler n'ecrit
rien lui-meme, il instancie une chaine dont un maillon (`IngestAgent`) ecrit
dans le RAG -- en contournant les trois routes `/ingest/*` qu'on venait de
garder. « Proteger une URL ne protege pas une CAPACITE. »

Ce NR fige le croisement : pour chaque handler relie a une route, la garde
qu'il porte et les capacites des modules qu'il importe.

CE QU'IL MESURE, ET CE QU'IL NE PEUT PAS MESURER
================================================
La capacite est celle du MODULE, pas une preuve que le handler l'exerce. Un
module qui sait ecrire un fichier peut n'offrir au handler qu'une lecture. La
liste ci-dessous est donc une liste d'ENQUETES A MENER, jamais un verdict de
vulnerabilite -- et surtout pas une liste de routes a armer en bloc.

Angles morts, nommes pour qu'aucun silence ne soit lu comme un OK :
  * PROFONDEUR 1 : un module qui en importe un autre est invisible ;
  * APPELS DYNAMIQUES (`getattr`, registre, dispatch par nom) : invisibles ;
  * imports au niveau de `_build_app` et non du handler : non attribues ;
  * un module sans capacite DETECTEE est INCONNU, jamais « inoffensif » --
    la caracterisation des capacites est POSITIVE, donc incomplete par nature.

POURQUOI AUCUNE GARDE N'EST POSEE DANS CE COMMIT
================================================
Armer treize routes sur cette seule base serait « durcir avant de
cartographier » -- l'erreur nommee le matin meme. Chacune demande la mesure
d'appelants qui a deja ramene un perimetre de quatre routes a trois, et qui a
fait EXCLURE `/api/resource/should_spawn` : son gate est `fail-open`, un 401
n'y casserait rien, il rendrait la regulation SILENCIEUSEMENT inoperante.

Deux entrees portent deja une decision prise et mesuree :
  * `/api/resource/should_spawn` -- appelee par `proxy_deno/core/supervisor.ts`
    (autre LANGAGE), gate fail-open. EXCLUE par mesure.
  * `/api/sandbox/runtimes` -- sa docstring declare « pas d'auth, read-only »
    quand l'audit la classe ADMIN. Desaccord entre une decision DOCUMENTEE et
    une classification AUTOMATIQUE : cela s'arbitre, cela ne se tranche pas seul.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

_RACINE_MOD = Path(__file__).resolve().parents[2]
if str(_RACINE_MOD / "tools") not in sys.path:
    sys.path.insert(0, str(_RACINE_MOD / "tools"))

# LE PRODUCTEUR DU VOCABULAIRE EST LA SEULE SOURCE -- ajoute le 2026-09-21
# apres QUATRE faux verdicts. Ce fichier portait sa propre liste `GARDES`,
# plus pauvre que celle du producteur : `swarm_run`, `recon_run`, `ctf_run` et
# `auth_login` portent une garde INLINE (`HUB_TOKEN`, `_AGENT_TOKENS`) que le
# producteur voyait DEJA, et que la copie ne voyait pas.
# Regle ecrite mot pour mot dans `ci_local.py` pour un autre vocabulaire :
# « liste BLANCHE prise chez le producteur, jamais recopiee ».
import forge_route_authz_audit as audit  # noqa: E402

#: Motifs de CAPACITE -- caracterisation POSITIVE. Tout ce qui n'est pas
#: reconnu reste INCONNU ; une liste de motifs « dangereux » absents serait une
#: liste noire, et manquer y signifierait « sans danger ».
CAPACITES = {
    "ecrit_rag": re.compile(r"INSERT\s+INTO\s+rag_chunks|rag_chunks\s*\(", re.I),
    "execute_process": re.compile(r"\bsubprocess\.|\bPopen\(|os\.system\(|os\.execv"),
    "ecrit_fichier": re.compile(r"\.write_text\(|open\([^)]*['\"][wa]b?['\"]"),
    "supprime": re.compile(r"os\.remove\(|shutil\.rmtree\(|\.unlink\("),
    "reseau_sortant": re.compile(r"requests\.(get|post)\(|httpx\.|urlopen\("),
}

#: DERIVE du producteur, jamais recopie. Toute garde ajoutee chez lui est
#: reconnue ici sans edition -- c'est la propriete qui manquait.
_GARDES = audit.GARDES

#: Handlers SANS garde qui atteignent au moins une capacite, avec l'etat de
#: leur instruction. Un handler qui apparait hors de cette table fait rougir le
#: test : soit une route est nee, soit une garde a disparu.
SANS_GARDE_CONNUS = {
    "watch_jobs_api": "chaine d'agents, ecrit RAG -- cf test_ecriture_rag_chemins_connus_nr",
    # watch_create_api RETIRE le 2026-09-24 : garde `_garde_ui` posee a l'enregistrement
    # (session UI du portail + origine locale, ou jeton admin) ; attribution prouvee.
    # Verrouille par tests/nr/test_garde_ui_mutation_nr.py.
    "swarm_health": "resource_manager porte execute_process -- A INSTRUIRE",
    "swarm_stream": "swarm_bus -- A INSTRUIRE",
    # 2026-09-26, DECISION OWNER : inscrite, pas gardee. Handler de juillet, LECTURE SEULE de l'historique
    # reseau (forge_network_logger) ; la page /forge/network l'appelle sans en-tete d'autorisation, la
    # garder la casserait (401). Dette VISIBLE : a garder quand l'appelant portera la session UI.
    "network_history": "lecture seule de l'historique reseau, page /forge/network -- decision owner 26/09",
    # api_ingest / ui_generate / resource_should_spawn RETIRES le 2026-09-24 (cloture) :
    #   api_ingest -> _exiger_identite ; clawhub_bridge et dsl presentent le porteur
    #     d'organe (forge_hub_client.entetes_organe, jamais le maitre) ;
    #   ui_generate -> _garde_ui (session du portail + origine locale, ou jeton admin) ;
    #   resource_should_spawn -> _exiger_identite. La crainte « un 401 rendrait la
    #     regulation silencieusement inoperante » est levee PAR MESURE : 323 appels sur
    #     323 portaient SUPERVISOR (jeton derive, ring 1) au journal d'observation du jour,
    #     et supervisor.ts distingue deja AUTHZ_DENIED d'un hub en panne.
    # Verrouille par tests/nr/test_routes_organes_authentifiees_nr.py.
    "ui_components": "ui_generator -- A INSTRUIRE",
    "resource_state": "resource_manager porte execute_process -- A INSTRUIRE",
    "sandbox_runtimes": "DECIDEE PUBLIC/NONE le 2026-09-24 (forge_authz_shadow.DECLARE) : liste "
                        "statique, non-mutation prouvee par test_routes_organes_authentifiees_nr",
}


def _racine() -> Path:
    for base in (Path(__file__).resolve().parents[2], Path(__file__).resolve().parents[1]):
        if (base / "tools" / "nokido_hub.py").exists():
            return base
    raise AssertionError("racine du depot introuvable")


def _capacites_du_module(racine: Path, mod: str, cache: dict) -> tuple[str, list[str]]:
    if mod in cache:
        return cache[mod]
    court = mod.split(".")[-1]
    chemin = None
    for sous in ("app", "app/web_hub", "tools"):
        p = racine / sous / (court + ".py")
        if p.exists():
            chemin = p
            break
    if chemin is None:
        cache[mod] = ("ILLISIBLE", [])          # illisible != sans capacite
        return cache[mod]
    try:
        t = chemin.read_text(encoding="utf-8", errors="replace")
    except OSError:
        cache[mod] = ("ILLISIBLE", [])
        return cache[mod]
    cache[mod] = (chemin.name, [k for k, rx in CAPACITES.items() if rx.search(t)])
    return cache[mod]


def _carte() -> dict[str, dict]:
    """handler -> {routes, garde, capacites}. Recalcule a chaque execution :
    une table figee mentirait des la premiere route ajoutee."""
    racine = _racine()
    arbre = ast.parse((racine / "tools" / "nokido_hub.py").read_text(encoding="utf-8"))

    routes: dict[str, list[str]] = {}
    for n in ast.walk(arbre):
        if isinstance(n, ast.Call):
            nom = getattr(n.func, "attr", None) or getattr(n.func, "id", None)
            if nom in ("add_route", "Route") and n.args:
                a0 = n.args[0]
                if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
                    for a in n.args[1:]:
                        if isinstance(a, ast.Name):
                            routes.setdefault(a.id, []).append(a0.value)
                            break

    cache: dict = {}
    carte: dict[str, dict] = {}
    for fn in ast.walk(arbre):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if fn.name not in routes:
            continue
        mods = set()
        for n in ast.walk(fn):
            if isinstance(n, ast.ImportFrom) and n.module:
                mods.add(n.module)
            elif isinstance(n, ast.Import):
                for a in n.names:
                    mods.add(a.name)
        appels = {getattr(n.func, "id", None) or getattr(n.func, "attr", None)
                  for n in ast.walk(fn) if isinstance(n, ast.Call)}
        # La garde est classee par COMPORTEMENT (`classer_garde`), pas par la
        # presence d'un NOM : une garde ecrite inline, sans fonction
        # auxiliaire, en est une. Et son exemption locale voyage avec elle.
        _fin = getattr(fn, "end_lineno", fn.lineno + 60)
        _corps_fn = "\n".join(
            (racine / "tools" / "nokido_hub.py").read_text(
                encoding="utf-8", errors="replace").splitlines()[fn.lineno - 1:_fin])
        _etat, _notes = audit.classer_garde(_corps_fn)
        caps: dict[str, list[str]] = {}
        for m in sorted(mods):
            nom_fichier, c = _capacites_du_module(racine, m, cache)
            if c:
                caps[nom_fichier] = c
        carte[fn.name] = {
            "routes": sorted(routes[fn.name]),
            # `garde` reste la liste des motifs vus, pour compatibilite ; le
            # VERDICT est `etat`, et `notes` dit ce qui le nuance.
            "garde": sorted(g for g in _GARDES if g in _corps_fn),
            "etat_garde": _etat,
            "notes_garde": _notes,
            "capacites": caps,
        }
    return carte


# ─────────────────  L INSTRUMENT VOIT QUELQUE CHOSE  ──────────────────────

def test_l_instrument_trouve_des_handlers_et_des_gardes():
    """Controle POSITIF, sans lequel une carte vide serait indistinguable d'un
    hub parfaitement garde. Un detecteur muet n'est pas une bonne nouvelle."""
    carte = _carte()
    assert len(carte) >= 50, (
        "seulement %d handlers relies a une route : l'extraction des routes a "
        "casse, la carte ne mesure plus rien" % len(carte))
    gardes = [h for h, v in carte.items() if v["garde"]]
    assert len(gardes) >= 20, (
        "seulement %d handlers gardes detectes : le detecteur de garde est "
        "aveugle, et toute conclusion d'absence serait fausse" % len(gardes))


#: Handlers qui portent une garde MAIS l'ouvrent a tout appelant local.
#: Ils ont QUITTE `SANS_GARDE_CONNUS` le 2026-09-21 quand le detecteur a cesse
#: de chercher des noms de fonction -- et ce deplacement ne doit RIEN effacer.
#:
#:     « gardee » et « sans garde » sont tous deux FAUX pour ces routes.
#:
#: Condition mesuree, identique aux trois, extraite du hub par AST :
#:     if not valid and client not in ('127.0.0.1', '::1', 'localhost', '')
#: => tout appelant loopback passe SANS porteur, chaine vide comprise. Le
#: compte sandbox du hub atteint le loopback : `LOCAL_ONLY != TRUSTED`.
GARDE_AVEC_EXEMPTION_LOCALE_CONNUS = {
    "swarm_run": "fan-out LLM reel sur 4 providers ; loopback passe sans porteur",
    "recon_run": "lance une recon ; loopback passe sans porteur",
    "ctf_run": "loopback passe sans porteur",
}


def test_une_garde_a_exemption_locale_n_est_pas_comptee_comme_fermee():
    """LE TEST QUI EMPECHE LE FAUX CALME. Quand le detecteur a cesse de
    chercher des NOMS, trois routes ont quitte « sans garde ». Les laisser
    partir sans les reclasser aurait transforme un faux « ouvert » en faux
    « ferme » -- le meme defaut, dans l'autre sens, et plus dangereux."""
    carte = _carte()
    for h, raison in GARDE_AVEC_EXEMPTION_LOCALE_CONNUS.items():
        assert h in carte, "handler %s introuvable : re-mesurer" % h
        assert carte[h]["etat_garde"] == "DETECTED", (
            "%s ne porte plus de garde detectee (%r)" % (h, carte[h]["etat_garde"]))
        assert "EXEMPTION_LOCALE" in carte[h]["notes_garde"], (
            "%s a perdu son exemption locale -- si la garde a ete FERMEE, "
            "tant mieux : le prouver en runtime et retirer l'entree. Sinon, "
            "le detecteur ne la voit plus. %r" % (h, carte[h]["notes_garde"]))
        assert len(raison) > 20, "%s n'explique pas son etat" % h


def test_l_exemption_locale_nomme_la_chaine_vide():
    """`client == ''` (quand `request.client` est absent) est range avec les
    hotes locaux. C'est une DECISION, pas un detail de bord."""
    carte = _carte()
    vides = [h for h in GARDE_AVEC_EXEMPTION_LOCALE_CONNUS
             if "CLIENT_VIDE" in carte[h]["notes_garde"]]
    assert vides, (
        "aucune des trois routes ne signale la chaine vide alors que leur "
        "condition la contient : le detecteur ne la voit plus")


def test_les_gardes_posees_ce_jour_sont_vues():
    """Ancrage : si ces handlers perdaient leur garde, ou si le detecteur
    cessait de la voir, les deux cas doivent rougir ici."""
    carte = _carte()
    # `mcp_config_flags` A ETE RETIREE de cette liste le 2026-09-21, apres
    # mesure RUNTIME : sa garde cassait le bouton « Flags reinitialises » de
    # l'UI du hub (`nokido_hub.py:2072`, fetch inline sans en-tete). Ce test a
    # EXIGE la mise a jour en rougissant, et c'est sa raison d'etre -- il
    # surveille les deux sens, pas seulement la perte accidentelle d'un garde.
    # La route reste comptable dans `SENSIBLES_CONNUES` de
    # `test_route_authz_inventaire_nr`, avec sa raison.
    for h in ("ingest_url", "ingest_bulk", "ingest_qualify", "mcp_batch",
              "mpc_plan", "orchestrate_loop", "hormones_release",
              "mcp_config_toggle"):
        assert h in carte, "handler %s introuvable : re-mesurer" % h
        assert carte[h]["garde"], (
            "%s ne porte plus de garde detectee -- soit la garde a ete "
            "retiree, soit le detecteur ne la voit plus" % h)


# ──────────────  L INVENTAIRE DES NON GARDES EST A JOUR  ─────────────────

def test_l_inventaire_des_handlers_sans_garde_est_a_jour():
    """LE COEUR, et il mord DANS LES DEUX SENS : un handler qui apparait
    signale une route nee ou une garde disparue ; un handler qui disparait
    signale une garde gagnee -- tant mieux, mais l'inventaire doit le dire
    pour que le chiffre reste vrai."""
    carte = _carte()
    reels = {h for h, v in carte.items() if not v["garde"] and v["capacites"]}
    connus = set(SANS_GARDE_CONNUS)

    apparus = reels - connus
    disparus = connus - reels
    assert not apparus, (
        "handlers SANS garde atteignant une capacite, absents de l'inventaire : "
        "%s -- une route est nee ou une garde a disparu" % sorted(apparus))
    assert not disparus, (
        "handlers de l'inventaire qui n'y sont plus : %s -- ils ont gagne une "
        "garde (tant mieux) ou changent de nom : mettre a jour la table"
        % sorted(disparus))


def test_chaque_entree_de_l_inventaire_porte_sa_raison():
    """Une liste de noms sans raison se relit comme une liste de defauts. Or
    deux de ces entrees portent une decision MESUREE, pas un oubli."""
    for h, raison in SANS_GARDE_CONNUS.items():
        assert len(raison) > 20, "%s n'explique pas son etat" % h
    # 2026-09-24 : les deux exclusions mesurees (api_ingest, resource_should_spawn) ont
    # GAGNE une garde a la cloture du chantier d'authentification -- elles sortent de
    # l'inventaire, verrouillees par test_routes_organes_authentifiees_nr. L'intention
    # reste : une DECISION (exclusion ou declaration publique) doit nommer sa preuve,
    # sinon elle se relit comme un oubli.
    for h, r in SANS_GARDE_CONNUS.items():
        if "EXCLUE" in r or "DECIDEE" in r:
            assert "mesure" in r.lower() or "prouvee" in r.lower(), (
                "%s porte une decision sans dire sur quelle mesure elle repose" % h)


def test_l_instrument_ne_confond_pas_capacite_du_module_et_capacite_du_handler():
    """La limite la plus importante de cet outil, verrouillee pour qu'aucun
    lecteur n'en tire un verdict de vulnerabilite : la capacite mesuree est
    celle du MODULE. Le docstring du NR doit continuer de le dire."""
    assert "PROFONDEUR 1" in __doc__
    assert "jamais un verdict" in __doc__
