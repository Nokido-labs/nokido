"""Non-regression : l'inventaire des routes HTTP et de leurs gardes ne doit pas deriver.

Mesure 2026-09-02 sur le hub en fonctionnement : 81 routes, 27 avec garde detectee.
Sonde REELLE de 40 routes GET sans jeton : 19 refusent (401), 22 repondent 200 --
dont deux ADMIN (`/api/sandbox/runtimes`, `/api/services/list`) et une classee
MUTANTE (`/api/resource/should_spawn`).

CE TEST NE FERME AUCUNE ROUTE et ne sonde RIEN : fermer releve d'une decision
owner, et une sonde reseau rendrait la CI non hermetique. Il fige l'inventaire
STATIQUE pour qu'une route sensible nouvelle, ajoutee sans garde, fasse rougir la
CI au lieu de s'ajouter en silence.

DEUX PRECAUTIONS APPRISES A LEURS DEPENS :

1. « Garde detectee » est un test de PRESENCE DE MOTIF dans le corps du handler, pas
   une preuve de refus. Le 2026-09-01 j'ai annonce « 68 routes sans garde, /admin/run_job
   ouvert » en ayant omis `_admin_tok_ok` de la liste des motifs : la sonde a montre
   que ces routes refusaient bien. Le NOM d'une fonction n'est pas son COMPORTEMENT.
2. « Aucun appelant trouve » ne veut pas dire « personne ne l'appelle » : un client
   externe, un navigateur ou un script hors depot n'apparait dans aucun grep. Ces
   routes sont UNKNOWN, pas mortes -- et on ne supprime pas sur un silence.
"""

from __future__ import annotations

import ast
import re
import sys
from functools import lru_cache
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : parcours du depot : rglob tools+app
#   (py/html/js/ts) + lecture (l.481)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import forge_route_authz_audit as audit  # noqa: E402

# Routes SENSIBLES (ADMIN/MUTANTE) sans garde detectee, au 2026-09-02.
# C'est un CONSTAT date, pas une autorisation.
#
# 2026-09-03 : `/admin/ingest_repo` RETIREE de la liste — elle a recu son garde
# (`if not _admin_tok_ok(request)` dans `tools/nokido_hub.py`, fail-open ferme).
# Le cliquet a exige cette mise a jour, et c'est sa raison d'etre : sans elle,
# la route pourrait perdre son garde demain sans que rien ne le signale.
# 2026-09-24 — CLOTURE : la liste est VIDE. Les sept dernieres routes ont recu :
#   _exiger_identite (identite d'organe prouvee) : /api/services/list, /api/ingest,
#       /api/resource/should_spawn, /nervous_system/emit
#   _garde_ui (session du portail + origine locale, ou jeton admin) : /ui/generate
#   une DECISION explicite `authentication: NONE` (forge_authz_shadow.DECLARE) + NR de
#       non-mutation : /api/rag/tokenize, /api/sandbox/runtimes
# Les commentaires ci-dessous sont l'HISTORIQUE des raisons mesurees, conserve.
#
# 2026-09-26, DECISION OWNER : /api/push sort de la liste PUBLIQUE declaree (une route retiree n'elargit pas
# la surface publique, plafond de 3) et entre ICI, ouverte et SUE : son handler du hub ne porte aucune garde,
# rend 410 `gone`, ne lit ni n'ecrit rien, aucun appelant mesure. Ni garde ni suppression (fichier critique).
SENSIBLES_CONNUES: set = {"/api/push"}
_HISTORIQUE_SENSIBLES = {
    # ── RESTENT SANS GARDE, chacune pour une raison MESUREE ────────────────
    # `/api/sandbox/runtimes` : sa docstring declare « pas d'auth, read-only ».
    #   L'audit la classe ADMIN -- desaccord a ARBITRER, pas a trancher seul.
    "/api/sandbox/runtimes",
    # appelants sans porteur : app/laforge_tui/laforge_tui.py:111
    "/api/services/list",
    # appelants sans porteur : forge_clawhub_bridge:437, forge_dsl:229
    "/api/ingest",
    # 2026-09-24 : `/api/mcp/flags` et `/api/watch/create` RETIREES -- elles ont
    # gagne `_garde_ui` (session UI du portail + origine locale, ou jeton admin),
    # posee a l'enregistrement. L'impasse decrite ci-dessous (« donner un porteur a
    # l'UI sans glisser un jeton dans une page ») est levee par la SESSION : le
    # cookie du portail voyage avec le `fetch` same-origin. Historique conserve.
    #
    # ⚠ GARDE ARMEE PUIS RETIREE LE MEME JOUR, apres mesure RUNTIME.
    # MESURE 2026-09-21 : elle avait ete armee sur l'affirmation « aucun
    # appelant HTTP au depot, verifie en Python, TypeScript, HTML et config ».
    # C'ETAIT FAUX. L'appelant est `tools/nokido_hub.py:2072`, une chaine JS
    # INLINE du hub lui-meme :
    #     async function resetFlags(){ await fetch('/api/mcp/flags',
    #                                   {method:'POST'}); ... }
    # sans en-tete, et SANS condition. La recherche portait sur des EXTENSIONS
    # de fichier ; un `fetch` dans du HTML servi depuis un `.py` n'y entrait
    # pas. La garde cassait donc le bouton « Flags reinitialises » de l'UI.
    #
    # LE RISQUE N'EST PAS EFFACE : la route ECRIT dans la configuration Claude
    # Desktop de l'owner. Elle est ici pour rester COMPTABLE, pas pour etre
    # oubliee. La traiter demande de donner un porteur a l'UI, ce qui ne se
    # fait pas en glissant un jeton dans une page servie -- meme impasse que
    # `/api/watch/create`, plus bas.
    # MESURE 2026-09-21 : `inbox_push` lit le corps et rend `{"ok": True}`.
    # AUCUN effet -- ni ecriture, ni appel, ni relais. C'est un NO-OP que
    # l'audit classe MUTANTE sur son verbe HTTP. La garder ne protegerait
    # RIEN. Reste ici pour que le reclassement soit trace, pas comme dette.
    # (Portee : elle est de toute facon definie au niveau MODULE, alors que
    # `_admin_tok_ok` vit dans `_build_app`.)
    # 2026-09-24 : elle rend desormais 410 `gone` -- un NO-OP qui repondait `ok`
    # mentait a son appelant (REQUESTED != ACHIEVED). Appelants mesures : aucun.
    "/api/push",
    # MESURE 2026-09-21 : `rag_tokenize` compte des tokens sur un texte BORNE
    # a 50 000 caracteres. Calcul pur, aucun effet, aucune donnee touchee.
    # Appelant : app/web_hub/rag_dashboard.html:128 (navigateur, sans porteur).
    "/api/rag/tokenize",
    # appele par proxy_deno/core/supervisor.ts:1163 -- AUTRE LANGAGE, invisible
    # a une recon Python. Le superviseur porte un Bearer mais `if (token)`, et
    # le gate est `fail-open: non-2xx -> allow spawn` : un 401 ne casserait
    # rien, il rendrait la regulation SILENCIEUSEMENT inoperante. Pire qu'un
    # refus visible.
    "/api/resource/should_spawn",
    # ⚠ LA PLUS GRAVE DES NEUF, et elle n'est PAS gardable en l'etat.
    # MESURE 2026-09-21 : `watch_create_api` -> `forge_watch_agent.create_job`
    # insere `watch_jobs` + `agent_chain_context` + SEPT noeuds
    # `agent_chain_nodes` : KeywordAgent, VerifyAgent, SearchAgent,
    # RefineAgent, CrawlAgent, IngestAgent, StoreAgent (ollama, groq/llama-8b,
    # groq/llama-70b). Un appel anonyme declenche donc une CHAINE D'EXECUTION
    # complete qui crawle le web et ECRIT DANS LE RAG.
    #
    # => CHEMIN DE CONTOURNEMENT des gardes posees sur /ingest/* : `IngestAgent`
    #    atteint la base SANS passer par les routes HTTP gardees. Proteger une
    #    URL ne protege pas une CAPACITE.
    #
    # De plus `agent = body.get("agent", "ADMIN_UI")` : l'ATTRIBUTION du job
    # est DECLAREE par l'appelant. Meme faute que `header_agent`, transposee au
    # corps de la requete.
    #
    # NON GARDABLE aujourd'hui : l'UI du hub elle-meme l'appelle en `fetch`
    # inline (nokido_hub.py:2181) SANS en-tete d'autorisation. L'armer
    # casserait l'interface. Traiter l'appelant UI d'abord.
    # (Traite le 2026-09-24 : voir l'en-tete de cette section.)
    # /ingest/url, /ingest/bulk, /ingest/qualify RETIREES le 2026-09-21 : elles
    # ont GAGNE `_admin_tok_ok`. Ce n'est pas un declassement -- ce test demande
    # lui-meme la mise a jour quand une route sort de la liste (« tant mieux,
    # mais il faut mettre a jour l'inventaire pour que le chiffre reste vrai »).
    # Mesure qui a motive la garde, sonde NON mutante et sans jeton :
    #     POST /ingest/bulk {} -> 400 « expected array »  (handler ATTEINT)
    #     POST /ingest/url  {} -> 400 « invalid url »     (handler ATTEINT)
    # Les trois font INSERT + commit() dans RAG/embeddings.db : c'etaient des
    # ecrivains ANONYMES sur la base que l'owner a demande de faire CESSER DE
    # RECEVOIR (19/09). Verrouillees par test_ingestion_exige_un_porteur_nr.
    #
    # appelant sans porteur : tools/forge_dt_router_wire.py:37
    "/nervous_system/emit",
    # appelants sans porteur : app/web_hub/app.py:692,752,771
    "/ui/generate",
}

# RETIREES le 2026-09-21 -- elles ont GAGNE `_admin_tok_ok`, toutes MUTANTE et
# sans AUCUN appelant HTTP au depot (recherche en .py .ts .js .html .json .toml
# .ps1 .sh, sur app/ tools/ proxy_deno/ config/ docs/ .agents/) :
#
#   /ingest/url  /ingest/bulk  /ingest/qualify   ecrivaient dans embeddings.db
#                                                401 PROUVE en runtime
#   /api/mcp/flags  /api/mcp/toggle              ecrivaient la config Claude
#   /api/hormones/release                        injectait un signal endocrinien
#   /mcp/batch                                   EXECUTAIT des appels d'outils
#   /mpc/plan  /orchestrate/loop                 boucles d'execution
#
# La liste passe de 18 a 9. Ce n'est pas un declassement : ce fichier DEMANDE
# sa mise a jour quand une route sort (« tant mieux, mais il faut mettre a jour
# l'inventaire pour que le chiffre reste vrai »). Les 9 qui restent portent
# chacune la raison MESUREE qui empeche de les armer aujourd'hui.


@lru_cache(maxsize=1)
def _audit():
    # `avec_appelants=False` : la recherche d'appelants balaie le depot pour CHAQUE
    # route (29 s mesurees). La CI n'en a pas besoin, et un test lent finit desactive.
    return audit.auditer(avec_appelants=False)


def _sensibles_sans_garde(rapport) -> set:
    # Les clefs REELLES du rapport : `route` et `garde_detectee`. Je les avais
    # supposees (`chemin`, `garde`) au lieu de les lire -- le test a echoue tout de
    # suite, ce qui est le bon comportement, mais l'aller-retour etait evitable.
    # 2026-09-24 : une route DECIDEE `authentication: NONE` chez le producteur
    # (`forge_authz_shadow.DECLARE`) n'est pas une garde OUBLIEE -- c'est une decision,
    # verrouillee par un NR de non-mutation. Une declaration ILLISIBLE n'exempte rien.
    return {r["route"] for r in rapport["routes"]
            if not r.get("garde_detectee") and r.get("classe") in ("ADMIN", "MUTANTE")
            and not (isinstance(r.get("declaration"), dict)
                     and r["declaration"].get("authentication") == "NONE")}


def test_l_inventaire_est_lisible():
    """Un audit qui n'a pas pu lire n'est pas un audit vide."""
    r = _audit()
    assert r["routes"], "aucune route trouvee : le fichier de routes a-t-il bouge ?"
    assert len(r["routes"]) >= 60, len(r["routes"])


def test_aucune_route_sensible_nouvelle_sans_garde():
    """LE garde : une route ADMIN/MUTANTE ajoutee sans authentification doit se voir."""
    vues = _sensibles_sans_garde(_audit())
    nouvelles = vues - SENSIBLES_CONNUES
    assert not nouvelles, (
        "route(s) sensible(s) NOUVELLE(S) sans garde detectee : %s. Soit y poser une "
        "authentification, soit l'inscrire ici en sachant qu'elle est ouverte."
        % sorted(nouvelles))


def test_les_routes_gardees_ne_perdent_pas_leur_garde():
    """Symetrique : une route qui SORT de la liste connue a gagne une garde -- tant
    mieux, mais il faut mettre a jour l'inventaire pour que le chiffre reste vrai."""
    vues = _sensibles_sans_garde(_audit())
    disparues = SENSIBLES_CONNUES - vues
    assert not disparues, (
        "ces routes ne sont plus signalees sans garde (garde ajoutee, ou route "
        "supprimee) : %s. Mettre a jour SENSIBLES_CONNUES." % sorted(disparues))


def test_la_liste_des_motifs_de_garde_couvre_les_gardes_reelles():
    """Le faux negatif paye le 2026-09-01 : `_admin_tok_ok` manquait a la liste, et
    des routes REFUSANTES etaient comptees comme ouvertes."""
    for motif in ("_admin_tok_ok", "_resolve_ring", "HUB_TOKEN", "authorize("):
        assert motif in audit.GARDES, motif


# --------------------------------------------------------------------------- #
# Surface MCP -- l'autre moitie des points d'entree
# --------------------------------------------------------------------------- #

# Tools MCP sans garde detectee au 2026-09-02. CONSTAT date, pas autorisation.
TOOLS_SANS_GARDE_CONNUS = {
    "rag_search", "rag_stats", "swarm_status", "adr_check_drift", "services_status",
    "cyber_ai_task", "events_recent", "sentinel_status", "inspector_status",
    "mesh_status", "autopilot_status", "kaggle_status", "kaggle_competitions",
    "github_status", "github_list_repos", "github_list_issues", "github_search_code",
    "github_mcp_tools", "llm_router_status", "codeberg_status", "check_job_status",
    "_authority_log", "semantic_search", "analyze_graph_topology",
    "get_cai_suggestion", "find_critical_attack_path",
}


@lru_cache(maxsize=1)
def _mcp():
    return audit.auditer_tools_mcp()


def test_la_surface_mcp_est_lisible():
    """L'audit HTTP ne couvrait que 81 points d'entree sur ~570 declares : la surface
    MCP -- celle que tout agent connecte peut appeler -- n'y etait pas."""
    r = _mcp()
    assert r["tools"] >= 50, r["tools"]
    assert not r["illisibles"], r["illisibles"]


def test_aucun_tool_mcp_nouveau_sans_garde():
    """LE garde : un tool ajoute sans authentification doit se voir."""
    vus = set(_mcp()["sans_garde"])
    nouveaux = vus - TOOLS_SANS_GARDE_CONNUS
    assert not nouveaux, (
        "tool(s) MCP NOUVEAU(X) sans garde detectee : %s. Soit y poser une "
        "capability, soit l'inscrire ici en sachant qu'il est ouvert."
        % sorted(nouveaux))


def test_les_gardes_par_CHEMIN_sont_reconnus():
    """Faux negatif paye deux fois : un garde peut ne pas etre une capability.

    `file_read` / `file_write` n'en ont aucune mais sont proteges par `.mcpignore`.
    Les compter comme ouverts aurait produit l'alerte « les tools d'ecriture de
    fichiers sont libres » -- fausse.
    """
    for motif in ("_is_prot", "mcpignore", "_require_capability"):
        assert motif in audit.GARDES_MCP, motif
    vus = set(_mcp()["sans_garde"])
    for protege in ("file_read", "file_write", "file_explore"):
        assert protege not in vus, (
            "%s est compte comme sans garde alors qu'il est protege par chemin" % protege)


def test_une_fonction_interne_exposee_en_tool_est_signalee():
    """`_authority_log` est REELLEMENT decore @mcp.tool() -- verifie en AST, ce
    n'etait pas un artefact de decoupage. Une fonction de journalisation interne
    exposee comme tool est une decision a instruire, pas un detail."""
    noms = {t.get("tool") for t in _mcp()["detail"] if "tool" in t}
    assert "_authority_log" in noms, (
        "si ce tool a disparu, retirer ce test et TOOLS_SANS_GARDE_CONNUS a jour")


def test_le_rapport_distingue_absence_d_appelant_et_absence_d_usage():
    """« Aucun appelant trouve » est un UNKNOWN : un client hors depot est invisible."""
    src = (ROOT / "tools" / "forge_route_authz_audit.py").read_text(
        encoding="utf-8", errors="replace")
    assert "UNKNOWN, pas mortes" in src, (
        "le rapport doit dire qu'une route sans appelant trouve n'est pas morte")


# ══════════════════════════════════════════════════════════════════════════
#  L APPELANT PEUT VIVRE DANS UNE CHAINE INLINE, EN UN AUTRE LANGAGE
#  Ajoute le 2026-09-21, apres une regression payee EN RUNTIME.
#
#  La precaution n°2 du docstring de ce fichier disait deja : « aucun appelant
#  trouve » ne veut pas dire « personne ne l'appelle ». J'ai LU et EDITE ce
#  fichier le matin meme, puis arme `/api/mcp/flags` en ecrivant « aucun
#  appelant HTTP au depot, verifie en Python, TypeScript, HTML et config ».
#  L'appelant etait a `tools/nokido_hub.py:2072`, dans une chaine JavaScript
#  INLINE de ce hub :
#      async function resetFlags(){ await fetch('/api/mcp/flags',
#                                    {method:'POST'}); ... }
#  La garde a casse le bouton de l'UI et a du etre RETIREE.
#
#  La regle existait, a l'endroit exact, et n'a pas mordu -- parce qu'elle
#  etait un COMMENTAIRE. Elle devient un TEST.
#
#      EXTENSION DU FICHIER != LANGAGE DU CODE
#
#  Variante mesuree le meme jour : cinq appelants LinkGopher construisent leur
#  URL par interpolation -- fetch(`${LAFORGE_HUB}/ingest/url`) -- invisibles a
#  un grep sur l'URL litterale. Ils posent un porteur, mais CONDITIONNELLEMENT
#  (`if (LAFORGE_TOKEN)`), meme motif que `wired_routes.py:536` (`if tok:`) :
#  jeton illisible => appel sans porteur => 401. DEPEND_DE_LA_CONFIGURATION,
#  ce qui n'est ni « casse » ni « sur ».
# ══════════════════════════════════════════════════════════════════════════

#: Appel dont la cible porte un chemin de route. CHAQUE branche est ancree sur
#: un VERBE d'appel : c'est ce qui separe un appel d'une declaration. Elargi le
#: 2026-09-21 apres mesure -- la version precedente ne voyait que `fetch` et
#: rendait 41 routes sur 193.
#:
#: Motifs repris de `forge_js_endpoint_extractor` et `audit_ui_endpoints`, qui
#: les portaient deja. NON repris : la « chaine /api/ nue », qui ajoutait 357
#: sites dont la plupart sont des DECLARATIONS de routes.
#:
#:     TEXT_OCCURRENCE != DECLARATION != CALL
_APPEL_ROUTE = re.compile(
    r"""(?:
          (?P<w>\b[\w$]*[Ff]etch|\bfetch)\(\s*[`'"]\s*(?:\$\{[^}]*\}\s*)?(?P<a>/[\w/{}.-]+)
        | \bEventSource\(\s*[`'"]\s*(?:\$\{[^}]*\}\s*)?(?P<b>/[\w/{}.-]+)
        | \baxios\.\w+\(\s*[`'"]\s*(?:\$\{[^}]*\}\s*)?(?P<c>/[\w/{}.-]+)
        | \.open\(\s*[`'"][A-Z]+[`'"]\s*,\s*[`'"](?P<d>/[\w/{}.-]+)
        | \b(?:requests|httpx)\.\w+\(\s*[`'"]https?://[^`'"\s/]+(?P<e>/[\w/{}.-]+)
        | \burlopen\(\s*[`'"]https?://[^`'"\s/]+(?P<f>/[\w/{}.-]+)
    )""", re.X)

#: Conserve pour les tests de forme historiques : la branche `fetch` seule.
_FETCH = re.compile(
    r"""\b([a-zA-Z_$][\w$]*[Ff]etch|fetch)\(\s*[`'"]\s*(?:\$\{[^}]*\}\s*)?(/[a-z0-9_/{}.-]+)""")

#: Marqueurs d'un porteur, cherches dans la fenetre voisine.
_PORTEUR = re.compile(r"Authorization|Bearer|headers\s*:|X-Agent-Name", re.I)

#: Porteur OU jeton transporte autrement. Un `EventSource` ne peut PAS porter
#: d'en-tete -- l'API du navigateur ne l'expose pas -- donc son authentification
#: passe forcement ailleurs : jeton en query, cookie, ou wrapper. Le classer
#: « sans auth » parce qu'il n'a pas d'en-tete serait le faux positif `hubFetch`
#: repete sur un autre transport.
_PORTEUR_OU_JETON = re.compile(
    r"Authorization|Bearer|headers\s*:|X-Agent-Name"
    r"|[?&](?:token|access_token|api_key|auth)=|withCredentials|credentials\s*:",
    re.I)

#: LE PORTEUR EST-IL POSE SOUS CONDITION ? Septieme faux positif du
#: 2026-09-21, et le plus consequent : l'UI du swarm ecrit
#:
#:     ...(TOK ? {"Authorization": "Bearer " + TOK} : {})
#:
#: Le detecteur voyait `Authorization` et concluait PROUVE_AUTHENTIFIE. Or
#: quand `TOK` est vide, l'appel part NU -- et c'est precisement ce cas qui
#: fait dependre l'UI de l'exemption loopback.
#:
#:     AUTHENTIFIE_SOUS_CONDITION != PROUVE_AUTHENTIFIE
#:
#: Meme forme que `if (LAFORGE_TOKEN)` chez LinkGopher et `if tok:` dans
#: `wired_routes`. Trois occurrences, trois langages, un seul motif.
_PORTEUR_CONDITIONNEL = re.compile(
    r"""\.\.\.\(\s*\w+\s*\?                      # spread ternaire JS
      | \?\s*\{[^}]*Authorization                # ternaire -> objet d'en-tetes
      | if\s*\(\s*\w*[Tt]ok\w*\s*\)              # if (TOK) / if (token)
      | if\s+\w*tok\w*\s*:                       # if tok:  (Python)
      | if\s+\w+\s*:\s*\n?\s*\w*\[?['"]?Authorization
    """, re.X)


def classer_credential(voisinage: str) -> str:
    """PROUVE_AUTHENTIFIE · AUTHENTIFIE_SOUS_CONDITION · ANONYME.

    La conditionnalite PRIME : un porteur pose seulement `if token` laisse
    passer l'appel NU quand le jeton manque. Dire « authentifie » serait
    exact la moitie du temps, ce qui est la pire des reponses.
    """
    if _PORTEUR_CONDITIONNEL.search(voisinage):
        return "AUTHENTIFIE_SOUS_CONDITION"
    if _PORTEUR_OU_JETON.search(voisinage):
        return "PROUVE_AUTHENTIFIE"
    return "ANONYME"


def _route_de(m) -> str:
    """Le chemin capture, quelle que soit la branche qui a mordu."""
    for g in ("a", "b", "c", "d", "e", "f"):
        v = m.group(g)
        if v:
            return v
    return ""

#: Fenetre de lignes avant/apres le `fetch`. La borne DIT combien : au-dela,
#: l'appel est classe SANS PORTEUR VISIBLE -- ce qui n'est pas « sans porteur ».
_FENETRE = 6

#: Fenetre de lecture du CORPS d'un wrapper, a partir de sa definition.
#: `hubFetch` pose son en-tete en 7 lignes ; 24 laisse de la marge sans
#: aspirer la fonction suivante.
_FENETRE_WRAPPER = 24


def _wrapper_pose_un_porteur(nom: str, lignes: list) -> bool:
    """Le wrapper `nom` pose-t-il un porteur dans SA definition ?

    MESURE 2026-09-21 : `hubFetch` (LinkGopher, deux definitions) fait
        if (token) headers['Authorization'] = 'Bearer ' + token;
    sept lignes apres sa signature. Un detecteur qui ne regarde que le SITE
    D'APPEL le declare « sans porteur » et signale cinq appels en regle.

        CALL_SITE != DECISION_SITE

    Rend False si la definition est introuvable -- un wrapper importe d'un
    autre fichier n'est pas lu ici, et cela reste un SIGNALEMENT a instruire,
    jamais une accusation.
    """
    if nom == "fetch":
        return False
    definition = re.compile(
        r"(?:function\s+%s\s*\(|(?:const|let|var)\s+%s\s*=)" % (re.escape(nom), re.escape(nom)))
    for i, ligne in enumerate(lignes):
        if definition.search(ligne):
            corps = "\n".join(lignes[i:min(len(lignes), i + _FENETRE_WRAPPER)])
            if _PORTEUR.search(corps):
                return True
    return False

#: Appels inline sans porteur VISIBLE, connus et acceptes, avec leur raison.
INLINE_SANS_PORTEUR_CONNUS = {
    "/api/mcp/flags": "UI du hub, resetFlags() : porteur = cookie de SESSION du portail "
                      "(fetch same-origin), garde `_garde_ui` depuis le 2026-09-24",
    "/api/watch/create": "UI du hub, createJob() : porteur = cookie de SESSION du portail "
                         "(fetch same-origin), garde `_garde_ui` depuis le 2026-09-24",
    "/api/network/history": "UI du hub, lecture seule",
    "/api/rag/stats": "UI et dashboard, lecture seule",
    "/api/rag/tokenize": "dashboard, calcul pur borne a 50 000 caracteres",
}


@lru_cache(maxsize=1)
def _routes_gardees() -> frozenset:
    """Routes dont le handler appelle `_admin_tok_ok`. LU, jamais recopie."""
    arbre = ast.parse((ROOT / "tools" / "nokido_hub.py").read_text(encoding="utf-8"))
    par_handler: dict = {}
    for n in ast.walk(arbre):
        if isinstance(n, ast.Call):
            nom = getattr(n.func, "attr", None) or getattr(n.func, "id", None)
            if nom in ("add_route", "Route") and n.args:
                a0 = n.args[0]
                if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
                    for a in n.args[1:]:
                        if isinstance(a, ast.Name):
                            par_handler.setdefault(a.id, []).append(a0.value)
                            break
    gardees = set()
    for fn in ast.walk(arbre):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if fn.name not in par_handler:
            continue
        appels = {getattr(n.func, "id", None) or getattr(n.func, "attr", None)
                  for n in ast.walk(fn) if isinstance(n, ast.Call)}
        if "_admin_tok_ok" in appels:
            gardees.update(par_handler[fn.name])
    return frozenset(gardees)


@lru_cache(maxsize=1)
def _fetchs_sans_porteur() -> tuple:
    """((route, "fichier:ligne"), ...) des `fetch` sans porteur VISIBLE.

    Balaie les `.py` INCLUS : c'est tout l'objet -- le JavaScript vit dans des
    chaines de fichiers Python.
    """
    trouves = []
    for sous in ("tools", "app"):
        base = ROOT / sous
        if not base.is_dir():
            continue
        for chemin in base.rglob("*"):
            if chemin.suffix not in (".py", ".html", ".js", ".ts"):
                continue
            parties = set(chemin.parts)
            if parties & {"__pycache__", "node_modules", "static", "_attic"}:
                continue
            try:
                lignes = chemin.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue                      # illisible != absent
            for i, ligne in enumerate(lignes):
                for m in _APPEL_ROUTE.finditer(ligne):
                    appelant, route = (m.group("w") or "fetch"), _route_de(m)
                    if not route:
                        continue
                    voisinage = "\n".join(
                        lignes[max(0, i - _FENETRE):min(len(lignes), i + _FENETRE + 1)])
                    if _PORTEUR_OU_JETON.search(voisinage):
                        continue
                    # CALL_SITE != DECISION_SITE : l'en-tete peut etre pose par
                    # le wrapper, pas au site d'appel.
                    if _wrapper_pose_un_porteur(appelant, lignes):
                        continue
                    trouves.append((route,
                                    "%s:%d" % (chemin.relative_to(ROOT).as_posix(), i + 1)))
    return tuple(trouves)


def test_le_detecteur_d_appels_inline_voit_quelque_chose():
    """Controle POSITIF. Un detecteur muet rendrait « aucun appelant » partout
    -- exactement l'affirmation qui a coute la regression."""
    assert _fetchs_sans_porteur(), (
        "aucun `fetch` inline sans porteur trouve dans tout le depot : le "
        "detecteur est aveugle, et son silence ne vaut rien")


def test_le_detecteur_voit_la_forme_interpolee():
    """La forme `${VAR}/chemin` est CELLE qui a echappe au premier grep.
    Verifiee sur des sources construites : un depot qui change ne doit pas
    faire disparaitre le cas en silence."""
    assert _FETCH.search("await fetch(`${LAFORGE_HUB}/ingest/url`, {")
    assert _FETCH.search("await fetch('/api/mcp/flags',{method:'POST'})")
    assert _FETCH.search('fetch("/api/rag/stats")')
    assert _FETCH.search("const r = await hubFetch('/ingest/bulk', {")
    assert not _FETCH.search("Route('/api/mcp/flags', mcp_config_flags)")


def test_le_detecteur_lit_le_wrapper_et_ne_crie_pas_a_faux():
    """FAUX POSITIF MESURE puis corrige le 2026-09-21 : cinq appels LinkGopher
    passent par `hubFetch`, qui pose l'en-tete SEPT lignes apres sa signature.
    Les compter « sans porteur » aurait desarme ce garde des sa naissance."""
    avec = [
        "async function hubFetch(path, init) {",
        "  const token = await getToken();",
        "  const headers = Object.assign({ 'Content-Type': 'application/json' },",
        "    (init && init.headers) || {});",
        "  if (token) headers['Authorization'] = 'Bearer ' + token;",
        "  return fetch(`${HUB}${path}`, Object.assign({}, init, { headers }));",
        "}",
    ]
    sans = [
        "async function nuFetch(path, init) {",
        "  return fetch(`${HUB}${path}`, init);",
        "}",
    ]
    assert _wrapper_pose_un_porteur("hubFetch", avec) is True
    assert _wrapper_pose_un_porteur("nuFetch", sans) is False
    # `fetch` nu n'est JAMAIS un wrapper : sinon toute la mesure s'annule.
    assert _wrapper_pose_un_porteur("fetch", avec) is False


def test_aucune_route_gardee_n_a_un_appelant_inline_sans_porteur():
    """LE TEST QUI M AURAIT ARRETE. Une garde dont un appelant inline n'envoie
    rien est une REGRESSION en attente : « un 401 inattendu sur une route
    legitime est une regression, pas une victoire securitaire »."""
    gardees = _routes_gardees()
    assert gardees, "aucune route gardee detectee : re-mesurer avant de conclure"
    casses = {}
    for route, ou in _fetchs_sans_porteur():
        if route in gardees and route not in INLINE_SANS_PORTEUR_CONNUS:
            casses.setdefault(route, []).append(ou)
    assert not casses, (
        "routes GARDEES appelees par un `fetch` inline SANS porteur visible : "
        "%s -- chacune rendra 401 a son propre appelant. Mesurer AVANT "
        "d'armer, ou retirer la garde et l'inscrire a SENSIBLES_CONNUES."
        % casses)


def test_le_porteur_conditionnel_n_est_pas_un_porteur_prouve():
    """P1-P, septieme faux positif du jour. Trois formes reelles, trois
    langages, un seul motif -- et chacune laisse passer l'appel NU quand le
    jeton manque."""
    conditionnels = (
        # UI du swarm (app/web_hub/swarm.html:172)
        '...(TOK ? {"Authorization":"Bearer "+TOK} : {})',
        # LinkGopher (tools/linkgopher_nokido/background.js:21)
        "if (token) headers['Authorization'] = 'Bearer ' + token;",
        # wired_routes (app/web_hub/wired_routes.py:536)
        "if tok:\n    headers['Authorization'] = 'Bearer %s' % tok",
    )
    for src in conditionnels:
        assert classer_credential(src) == "AUTHENTIFIE_SOUS_CONDITION", (
            "porteur CONDITIONNEL classe autrement : %r -> %r"
            % (src[:50], classer_credential(src)))


def test_le_porteur_inconditionnel_reste_prouve():
    """CONTRE-EPREUVE. Un detecteur qui rendrait CONDITIONNEL partout
    effacerait la distinction au lieu de l'etablir."""
    assert classer_credential(
        "headers = {'Authorization': 'Bearer ' + tok}") == "PROUVE_AUTHENTIFIE"
    assert classer_credential(
        "fetch('/api/x', {method:'POST'})") == "ANONYME"


def test_les_exemptions_inline_portent_leur_raison():
    """Une liste de chemins sans raison se relit comme une liste d'oublis a
    « nettoyer » -- et l'un d'eux est un recul mesure, pas un oubli."""
    for route, raison in INLINE_SANS_PORTEUR_CONNUS.items():
        assert len(raison) > 20, "%s n'explique pas pourquoi il est exempte" % route


# ══════════════════════════════════════════════════════════════════════════
#  P1-E / P1-F — ROUTE GUARD != FUNCTION GUARD, et LOOPBACK != TRUST
#  Ajoute le 2026-09-21. NR de l'INSTRUMENT, pas du corps.
#
#  LE FAUX VERDICT, REPRODUIT ICI. `test_capacite_atteinte_sans_garde_nr`
#  cherchait des NOMS de fonction (`_admin_tok_ok`, `authorize`, ...) et a
#  declare « GARDE : AUCUNE » sur quatre handlers qui en portent une, ecrite
#  INLINE sans fonction auxiliaire :
#
#      swarm_run · recon_run · ctf_run · auth_login
#
#  Or `GARDES`, dans CE module, les voyait DEJA (`HUB_TOKEN`, `_AGENT_TOKENS`,
#  `compare_digest`, `Authorization`). Le defaut n'est donc pas dans le corps :
#  j'ai RECOPIE un vocabulaire en le perdant, depuis un module que j'avais lu
#  le matin meme.
#
#  La regle existait, ecrite mot pour mot dans `ci_local.py` a propos d'un
#  autre vocabulaire :
#      « Liste BLANCHE prise chez le producteur du vocabulaire, jamais
#        recopiee : une copie en dur ecrasait SUITE_PARTIELLE ... »
#
#      LE PRODUCTEUR DU VOCABULAIRE EST LA SEULE SOURCE
#
#  Et une seconde distinction, qui elle n'existait NULLE PART : une garde qui
#  exempte le loopback n'est pas une garde fermee.
#
#      client not in ("127.0.0.1", "::1", "localhost", "")
#
#  `LOCAL_ONLY != TRUSTED` -- le compte sandbox du hub atteint le loopback, et
#  la chaine VIDE y est assimilee. Directive owner du 2026-09-18, retrouvee
#  ici dans du code.
# ══════════════════════════════════════════════════════════════════════════

def test_le_classement_de_garde_rend_trois_etats_et_pas_deux():
    """`NOT_DETECTED` ne vaut JAMAIS `NO_GUARD` : un troisieme etat est exige
    pour ce que l'analyse statique ne peut pas trancher."""
    assert hasattr(audit, "classer_garde"), (
        "`forge_route_authz_audit.classer_garde` n'existe pas : le classement "
        "des gardes se fait encore par presence de NOM, et rend deux etats la "
        "ou il en faut trois")
    etats = set(getattr(audit, "ETATS_GARDE", ()))
    assert {"DETECTED", "NOT_DETECTED", "UNKNOWN"} <= etats, (
        "les trois etats obligatoires ne sont pas declares : %s" % sorted(etats))


def test_le_classement_voit_la_garde_inline_sans_fonction():
    """CAS POSITIF construit. Un handler qui refuse en 401 apres avoir compare
    un porteur porte une garde, meme sans appeler la moindre fonction nommee."""
    inline = (
        "async def h(request):\n"
        "    auth = request.headers.get('authorization', '')\n"
        "    tok = auth[7:].strip() if auth.lower().startswith('bearer ') else ''\n"
        "    valid = bool(tok) and tok in set(_AGENT_TOKENS.values())\n"
        "    if not valid:\n"
        "        return JSONResponse({'ok': False}, status_code=401)\n"
        "    return JSONResponse({'ok': True})\n")
    etat, _ = audit.classer_garde(inline)
    assert etat == "DETECTED", (
        "une garde INLINE n'est pas vue : c'est exactement le faux verdict du "
        "2026-09-21 sur swarm_run/recon_run/ctf_run (%r)" % etat)


def test_le_classement_ne_voit_pas_de_garde_la_ou_il_n_y_en_a_pas():
    """CAS NEGATIF construit. Sans lui, un detecteur qui rend toujours
    DETECTED passerait le test precedent sans rien mesurer."""
    nu = (
        "async def h(request):\n"
        "    body = await request.json()\n"
        "    return JSONResponse({'ok': True, 'echo': body})\n")
    etat, _ = audit.classer_garde(nu)
    assert etat == "NOT_DETECTED", (
        "le detecteur voit une garde dans un handler qui n'en a aucune : il "
        "est satisfait par sa propre presence textuelle (%r)" % etat)


def test_une_garde_qui_exempte_le_loopback_est_classee_a_part():
    """P1-F. `LOCAL_ONLY != TRUSTED`. Une garde qui laisse passer 127.0.0.1
    sans porteur n'est pas fermee, et la compter comme DETECTED tout court
    fabrique du faux calme -- le compte sandbox du hub atteint le loopback."""
    avec_exemption = (
        "async def h(request):\n"
        "    auth = request.headers.get('authorization', '')\n"
        "    tok = auth[7:].strip() if auth.lower().startswith('bearer ') else ''\n"
        "    valid = bool(tok) and tok in set(_AGENT_TOKENS.values())\n"
        "    client = (request.client.host if request.client else '') or ''\n"
        "    if not valid and client not in ('127.0.0.1', '::1', 'localhost', ''):\n"
        "        return JSONResponse({'ok': False}, status_code=401)\n")
    etat, notes = audit.classer_garde(avec_exemption)
    assert etat == "DETECTED"
    assert "EXEMPTION_LOCALE" in notes, (
        "l'exemption loopback n'est pas signalee : la garde sera lue comme "
        "fermee alors qu'elle laisse passer tout appelant local SANS porteur "
        "-- chaine vide comprise (%r)" % (notes,))


def test_la_chaine_vide_est_nommee_dans_l_exemption():
    """`client == ""` arrive quand `request.client` est absent. L'assimiler au
    loopback est une decision, pas un detail : elle doit etre VISIBLE."""
    avec_vide = (
        "async def h(request):\n"
        "    valid = tok in _AGENT_TOKENS\n"
        "    if not valid and client not in ('127.0.0.1', '::1', 'localhost', ''):\n"
        "        return JSONResponse({'ok': False}, status_code=401)\n")
    _, notes = audit.classer_garde(avec_vide)
    assert "CLIENT_VIDE" in notes, (
        "la chaine vide assimilee au local n'est pas signalee : %r" % (notes,))


def test_l_inventaire_de_capacites_derive_le_vocabulaire_au_lieu_de_le_copier():
    """LA REGLE QUI M AURAIT ARRETE. Une liste de gardes recopiee diverge de
    son producteur, et la divergence reste invisible tant qu'elle n'a pas
    coute -- ici quatre faux « AUCUNE garde »."""
    autre = ROOT / "tests" / "nr" / "test_capacite_atteinte_sans_garde_nr.py"
    src = autre.read_text(encoding="utf-8", errors="replace")

    # PIEGE EVITE : la premiere version de ce test cherchait la SOUS-CHAINE
    # `forge_route_authz_audit` -- et passait au VERT parce que le nom
    # apparaissait dans un COMMENTAIRE. Un test satisfait par une mention est
    # exactement le defaut qu'il pretend interdire. On exige un IMPORT REEL,
    # verifie en AST.
    arbre_autre = ast.parse(src)
    importe = any(
        (isinstance(n, ast.Import) and any("forge_route_authz_audit" in a.name
                                           for a in n.names))
        or (isinstance(n, ast.ImportFrom) and "forge_route_authz_audit" in (n.module or ""))
        for n in ast.walk(arbre_autre))
    assert importe, (
        "test_capacite_atteinte_sans_garde_nr ne DERIVE pas son vocabulaire de "
        "gardes : il le redefinit. C'est la recopie qui a produit quatre faux "
        "« AUCUNE garde » le 2026-09-21 (swarm_run, recon_run, ctf_run, "
        "auth_login), alors que le producteur les voyait deja.")

    # Et la recopie elle-meme doit avoir DISPARU, pas coexister avec l'import :
    # deux vocabulaires dont un seul est lu, c'est la divergence en attente.
    assert "GARDES = (" not in src, (
        "une liste de gardes locale subsiste a cote de l'import : le prochain "
        "ajout chez le producteur ne l'atteindra pas")


# ══════════════════════════════════════════════════════════════════════════
#  P1-G — UN APPELANT N EST PAS TOUJOURS UN `fetch`
#  Ajoute le 2026-09-21, apres mesure du detecteur contre trois briques
#  existantes du depot.
#
#  MESURE : sur 2542 fichiers, `_FETCH` voyait 41 routes sur 193. Les motifs
#  qu'il ne portait pas, repris de `forge_js_endpoint_extractor` et de
#  `audit_ui_endpoints` :
#
#      EventSource(...)        5 sites REELS, dont /api/swarm/stream
#      axios.<verbe>(...)      1
#      XMLHttpRequest .open    0 sur ce depot -- le motif reste, son absence
#                              ici est une MESURE, pas une raison de l'omettre
#      URL absolue vers :8766  25, tous en PYTHON -- le hub s'appelle lui-meme
#      base + '/chemin'        16, formes mixtes
#
#  Et un chiffre a NE PAS reprendre tel quel : le motif « chaine /api/ nue »
#  ajoutait 357 sites. Ce ne sont PAS 357 appelants : il capture aussi les
#  DECLARATIONS de routes (`@router.get("/api/x")`). C'est pourquoi il n'est
#  pas retenu ici.
#
#      TEXT_OCCURRENCE != DECLARATION != CALL
#
#  Un detecteur qui confond les trois transforme une carte d'appelants en
#  liste de tout ce qui mentionne une route.
# ══════════════════════════════════════════════════════════════════════════

def test_le_detecteur_couvre_les_transports_autres_que_fetch():
    """CAS POSITIFS construits, un par transport. Ecrits ICI et non tires du
    depot : la couverture ne doit pas dependre de ce que le corps contient
    aujourd'hui."""
    formes = {
        "fetch": "await fetch('/api/x', {method:'POST'})",
        "fetch interpole": "await fetch(`${HUB}/api/x`, {})",
        "wrapper": "await hubFetch('/api/x', {})",
        "EventSource": "const es = new EventSource('/api/swarm/stream');",
        "axios": "axios.post('/api/x', body)",
        "XHR": "xhr.open('GET', '/api/x');",
        "requests py": "requests.post('http://127.0.0.1:8766/api/x', json=d)",
        "httpx py": "httpx.get('http://127.0.0.1:8766/api/x')",
        "urllib py": "urllib.request.urlopen('http://127.0.0.1:8766/api/x')",
    }
    manquants = [nom for nom, ligne in formes.items()
                 if not _APPEL_ROUTE.search(ligne)]
    assert not manquants, (
        "le detecteur ne voit pas ces transports : %s -- un garde qui ne "
        "couvre que `fetch` ne tient qu'une porte sur trois" % manquants)


def test_le_detecteur_ne_prend_pas_une_declaration_pour_un_appel():
    """CAS NEGATIFS construits. Sans eux, elargir le detecteur revient a
    compter toute mention d'une route comme un appelant -- 357 faux sur ce
    depot."""
    declarations = (
        'Route("/api/x", handler, methods=["GET"])',
        '@router.get("/api/x")',
        'app.add_route("/api/x", handler)',
        '# la route /api/x est gardee depuis le 2026-09-21',
        'SENSIBLES_CONNUES = {"/api/x"}',
    )
    vus = [d for d in declarations if _APPEL_ROUTE.search(d)]
    assert not vus, (
        "le detecteur compte des DECLARATIONS comme des appels : %s" % vus)


def test_le_detecteur_distingue_eventsource_authentifie_ou_non():
    """P1-I, cas EventSource. `CALL_SITE != DECISION_SITE` vaut aussi ici :
    un EventSource ne porte JAMAIS d'en-tete (l'API du navigateur ne le
    permet pas), donc son authentification passe forcement par une autre
    voie -- jeton en query, cookie, ou wrapper. L'absence d'en-tete AU SITE
    D'APPEL ne prouve donc rien, et le classer « sans auth » serait le meme
    faux positif que `hubFetch`."""
    direct = "new EventSource('/api/swarm/stream')"
    avec_jeton = "new EventSource('/api/swarm/stream?token=' + t)"
    assert _APPEL_ROUTE.search(direct)
    assert _APPEL_ROUTE.search(avec_jeton)
    # La distinction porte sur la PRESENCE d'un porteur dans la voisinage,
    # pas sur le transport : c'est `_PORTEUR` qui tranche, et il doit voir
    # une forme de jeton en query.
    assert _PORTEUR_OU_JETON.search(avec_jeton), (
        "un jeton passe en query n'est pas reconnu comme porteur : tout "
        "EventSource authentifie sera compte comme anonyme")
    assert not _PORTEUR_OU_JETON.search(direct)


# ══════════════════════════════════════════════════════════════════════════
#  UN FICHIER QUI DECLARE UNE ROUTE PEUT AUSSI L'APPELER
#  Mesure du 2026-09-22.
#
#  `_OBSERVATEURS` ecarte `nokido_hub.py` de la recherche d'appelants, avec ce
#  commentaire :
#
#      "nokido_hub.py",   # declare les routes, ne les appelle pas
#
#  C'EST FAUX, et la mesure le dit. Quatre occurrences de `/api/mcp/flags` y
#  vivent, et elles ne se valent pas :
#
#      L2141  fetch('/api/mcp/flags',{method:'POST'})   <- APPELANT REEL (JS inline)
#      L3209  commentaire
#      L3281  commentaire citant le JS
#      L6060  Route("/api/mcp/flags", ...)              <- DECLARATION
#
#  Ecarter le FICHIER pour eviter l'auto-reference ecarte donc aussi l'appelant.
#  L'audit rend « AUCUN appelant trouve » sur une route qui en a un.
#
#  CE N'EST PAS UNE COQUETTERIE : la garde posee le 2026-09-21 sur cette route
#  exacte, au motif qu'elle n'avait « aucun appelant », a CASSE un bouton de
#  l'interface. Le meme raisonnement, appuye sur le meme instrument, produirait
#  la meme regression.
#
#      EXTENSION DU FICHIER != LANGAGE DU CODE
#      DECLARER UNE ROUTE != NE PAS L'APPELER
#
#  Le remede n'est pas de retirer `nokido_hub.py` des observateurs -- on
#  recolterait alors la ligne `Route(...)` et les commentaires, donc un
#  appelant fantome sur les 83 routes. On garde l'exclusion du VOCABULAIRE
#  (declarations, commentaires) et on lit les APPELS.
# ══════════════════════════════════════════════════════════════════════════

def test_un_appelant_js_inline_du_hub_est_vu():
    """LA MESURE. `/api/mcp/flags` est appelee par `resetFlags()`, en JS inline
    dans le fichier qui la declare."""
    trouves = audit._appelants("/api/mcp/flags")
    assert any("nokido_hub" in a for a in trouves), (
        "l'appelant JS inline du hub est invisible : une garde posee sur "
        "« aucun appelant » casserait l'interface, comme le 2026-09-21. "
        "Trouves : %r" % (trouves,))


def test_le_filtre_distingue_appel_declaration_et_commentaire():
    """CONTRE-EPREUVE, sans laquelle le correctif rendrait `nokido_hub.py`
    appelant de TOUTES les routes -- 83 faux positifs au lieu d'un faux negatif.

    Eprouvee sur la PRIMITIVE et sur des cas CONSTRUITS. Ma premiere version
    prenait `/api/watch/create` comme temoin « declaree mais jamais appelee en
    JS » : elle a rougi, et la mesure a montre que c'etait LE TEST qui se
    trompait -- cette route porte bien un `fetch` inline, ligne 2275.

        un test qui echoue sur une hypothese fausse ne mesure rien
    """
    declaration = 'Route("/api/temoin", h, methods=["POST"]),'
    commentaire = "# voir /api/temoin pour la bascule"
    appel = "const r=await fetch('/api/temoin',{method:'POST'});"
    assert not audit._appel_dans_observateur(declaration, "/api/temoin")
    assert not audit._appel_dans_observateur(commentaire, "/api/temoin")
    assert not audit._appel_dans_observateur(
        declaration + "\n" + commentaire, "/api/temoin")
    assert audit._appel_dans_observateur(
        declaration + "\n" + commentaire + "\n" + appel, "/api/temoin"), (
        "un appel noye au milieu du vocabulaire n'est pas vu")


def test_une_route_admin_sans_fetch_inline_ne_cite_pas_le_hub():
    """Le meme controle, sur le DEPOT et avec un temoin verifie.

    `/admin/heap` est declaree dans le hub et n'y est appelee par aucun
    `fetch` : si elle citait `nokido_hub.py`, le filtre laisserait passer une
    declaration.
    """
    trouves = audit._appelants("/admin/heap")
    assert not any("nokido_hub" in a for a in trouves), (
        "la DECLARATION d'une route est comptee comme un appel : l'instrument "
        "s'auto-designe appelant. Trouves : %r" % (trouves,))


def test_les_appelants_hors_observateurs_ne_regressent_pas():
    """NON-REGRESSION : le correctif ne doit rien retirer aux autres zones."""
    trouves = audit._appelants("/api/watch/create")
    assert trouves, "plus aucun appelant trouve : la recherche a ete cassee"
    assert any("ci_local" in a or "watch_agent" in a for a in trouves), (
        "les appelants connus hors observateurs ont disparu : %r" % (trouves,))


def test_l_interface_du_hub_consomme_des_routes_NUES():
    """CE QUE LE CORRECTIF REND VISIBLE, et qui decide d'une politique.

    Mesure du 2026-09-22 : ONZE routes sont appelees par le JS inline du hub,
    et NEUF d'entre elles n'ont aucune garde -- dont deux MUTANTE
    (`/api/mcp/flags`, `/api/watch/create`).

    Leur nudite n'est donc pas un oubli : c'est la contrepartie d'un
    consommateur qui n'envoie aucun porteur. Y poser une garde sans traiter
    l'appelant casse l'interface -- mesure du 2026-09-21, bouton `resetFlags`.

    Ce test ENREGISTRE le fait. Il rougira le jour ou l'une de ces routes sera
    gardee, et ce sera le bon moment pour verifier que l'appelant porte enfin
    un credential.
    """
    # `audit.HUB` est la source que l'instrument lit LUI-MEME : on mesure le
    # meme fichier que lui, jamais un chemin reconstruit a cote.
    # 2026-09-24 : LE JOUR ANNONCE EST ARRIVE. Les deux routes sont gardees, et
    # l'appelant porte enfin un credential : la SESSION du portail, envoyee par le
    # navigateur avec un `fetch` same-origin. Le test garde sa fonction en changeant
    # d'objet : la SEULE garde compatible avec cet appelant est `_garde_ui` (un
    # `_admin_tok_ok` seul rendrait 401 au bouton -- la regression du 2026-09-21), et
    # l'appel ne doit JAMAIS retirer le cookie (`credentials:'omit'`).
    src = audit.HUB.read_text(encoding="utf-8", errors="replace")
    attendues = ("/api/mcp/flags", "/api/watch/create")
    for route in attendues:
        assert audit._appel_dans_observateur(src, route), (
            "%s n'est plus appelee par le JS inline du hub -- tant mieux si "
            "l'appelant a ete deplace ; re-mesurer la garde" % route)
        for ligne in src.splitlines():
            if "fetch('%s'" % route in ligne:
                assert "credentials:'omit'" not in ligne.replace(" ", ""), (
                    "%s : l'appel retire le cookie de session -> 401 a son propre "
                    "appelant" % route)
    gardes = {r["route"]: r["garde_detectee"]
              for r in audit.auditer(avec_appelants=False)["routes"]}
    for route in attendues:
        assert gardes.get(route) == "_garde_ui", (
            "%s : garde %r -- seule `_garde_ui` accepte la session d'une page ; toute "
            "autre casse l'interface, aucune rouvre une mutation anonyme"
            % (route, gardes.get(route)))


# ══════════════════════════════════════════════════════════════════════════
#  UNE BORNE LOOPBACK EST UNE GARDE — « NU » N'EST PAS « EXEMPTE »
#  Mesure du 2026-09-22.
#
#  `/debug/stacks` refuse tout appelant non local :
#
#      ch = (request.client.host if request.client else "") or ""
#      if ch not in ("127.0.0.1", "::1", "localhost"):
#          return JSONResponse({"error": "localhost only"}, status_code=403)
#
#  L'audit la classait NUE, parce que `GARDES` ne contient que des noms de
#  fonctions (`_admin_tok_ok`, `_resolve_ring`, ...) et aucun motif de borne
#  d'origine. Le compte des routes sans garde etait donc surestime.
#
#      NU != VOLONTAIREMENT EXEMPTE
#
#  L'ampleur est UNE route sur 47 -- mesuree, pas supposee. Ce qui compte
#  n'est pas le nombre mais la CATEGORIE : une route qui refuse hors loopback
#  a une politique ; une route nue n'en a aucune. Les confondre fait travailler
#  sur la mauvaise.
#
#  ET LA PRIMITIVE EXISTAIT DEJA : `classer_garde()` vit dans ce meme module et
#  sait reconnaitre une exemption locale -- `auditer()` ne l'appelait pas.
#  PRODUCED != CONSUMED, a l'interieur d'un seul fichier.
# ══════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════
#  MENTIONNER UN CREDENTIAL N'EST PAS LE COMPARER — ET PEUT ETRE L'EMETTRE
#  Mesure du 2026-09-22.
#
#  `GARDES` cherche des motifs TEXTUELS dans le corps du handler. `HUB_TOKEN`
#  en fait partie. Or trois routes le mentionnent pour l'INJECTER, pas pour le
#  verifier :
#
#      tok = _AGENT_TOKENS.get("CLAUDE", "") or HUB_TOKEN or ""
#      html = html.replace("__LAFORGE_BEARER__", tok)
#      return HTMLResponse(html)
#
#  L'audit les comptait GARDEES. Elles sont exactement l'inverse : elles
#  SERVENT le porteur a qui demande la page, et les trois repondent 200 sans
#  jeton (mesure runtime du jour).
#
#      TEXT_OCCURRENCE != COMPARAISON
#      et un credential MENTIONNE peut etre un credential EMIS
#
#  Ce test ne verifie PAS la valeur du jeton -- il ne la lit pas, ne
#  l'affiche pas et ne l'ecrit nulle part. Il verifie la FORME du code : une
#  affectation suivie d'un `replace` n'est pas une garde.
# ══════════════════════════════════════════════════════════════════════════

_ROUTES_QUI_EMETTENT = ("/forge/debate", "/forge/graph", "/forge/recon")


def test_une_route_qui_EMET_le_porteur_n_est_pas_gardee():
    """LA MESURE. Ces trois routes injectent le porteur dans la page servie."""
    routes = {r["route"]: r for r in audit.auditer(avec_appelants=False)["routes"]}
    fautes = []
    for c in _ROUTES_QUI_EMETTENT:
        r = routes.get(c)
        if r is None:
            continue          # route retiree : rien a verifier
        if r["garde_detectee"] == "HUB_TOKEN":
            fautes.append(c)
    assert not fautes, (
        "routes comptees GARDEES alors qu'elles EMETTENT le porteur dans leur "
        "reponse : %s -- l'inventaire annonce une protection la ou il y a une "
        "distribution" % fautes)


def test_une_route_qui_COMPARE_le_porteur_reste_gardee():
    """CONTRE-EPREUVE, sans laquelle le correctif desarmerait l'inventaire.

    `/api/ctf/run` et `/api/recon/run` comparent bien le porteur :
        valid = bool(tok) and tok in set(... + [HUB_TOKEN])
    """
    routes = {r["route"]: r for r in audit.auditer(avec_appelants=False)["routes"]}
    for c in ("/api/ctf/run", "/api/recon/run"):
        r = routes.get(c)
        assert r is not None, "%s a disparu de l'inventaire : re-mesurer" % c
        assert r["garde_detectee"], (
            "%s compare le porteur et n'est plus comptee gardee : le correctif "
            "a desarme l'inventaire" % c)


def test_le_detecteur_distingue_emission_et_comparaison():
    """Eprouve sur la PRIMITIVE, avec des cas construits -- pas sur le depot,
    qui pourrait changer et rendre ce test muet au lieu de le faire rougir."""
    emet = ('tok = _AGENT_TOKENS.get("CLAUDE", "") or HUB_TOKEN or ""\n'
            'html = html.replace("__LAFORGE_BEARER__", tok)\n')
    compare = ('valid = bool(tok) and tok in set([HUB_TOKEN])\n'
               'if not valid:\n    return JSONResponse({}, status_code=401)\n')
    assert not audit._credential_compare(emet, "HUB_TOKEN"), (
        "une AFFECTATION suivie d'un `replace` passe pour une comparaison")
    assert audit._credential_compare(compare, "HUB_TOKEN")


# ══════════════════════════════════════════════════════════════════════════
#  « SECRET NE SORT JAMAIS » — UNE REGLE ECRITE QUE RIEN NE CONSULTAIT
#
#  `config/share_policy.json` classe les jetons en SECRET :
#      « Secrets, cles, JETONS, certificats prives, journal DPAPI.
#        Ne sort JAMAIS de la machine. »
#
#  Cette politique gouverne l'EGRESS vers les providers. Aucun garde ne
#  l'appliquait a une reponse HTTP -- et trois routes du hub servent un
#  porteur a un appelant anonyme.
#
#      la regle etait ecrite, et aucune porte ne la consultait
#
#  Meme motif que la frontiere d'autorite du 2026-09-21 : une serrure prouvee,
#  consommee par personne. Ce test la CABLE sur les routes.
#
#  Les trois routes connues sont NOMMEES : le test enregistre la dette au lieu
#  de la masquer, et rougit sur toute route NOUVELLE qui ferait la meme chose.
#  Une liste blanche, jamais une exemption silencieuse.
# ══════════════════════════════════════════════════════════════════════════

_EMETTRICES_CONNUES = frozenset({"/forge/debate", "/forge/graph", "/forge/recon"})


# ══════════════════════════════════════════════════════════════════════════
#  CLASSER CE QU'UNE REPONSE EXPOSE — AVEC LE VOCABULAIRE DU CORPS
#
#  `config/share_policy.json` definit PUBLIC / INTERNAL / CONFIDENTIAL /
#  SECRET. On ne fabrique pas un second vocabulaire : une seconde verite se
#  maintient deux fois et diverge une fois.
#
#  L'instrument ne rend QUE des compteurs et une classe. Il ne renvoie, ne
#  journalise et n'ecrit AUCUNE valeur -- c'est la regle owner, et c'est aussi
#  ce qui permet de le faire tourner sans transformer l'audit en canal de
#  divulgation (motif paye le 2026-09-21).
#
#  L'invariant du corps s'applique tel quel :
#      UNKNOWN = REFUSE. Ne pas savoir n'est pas une autorisation.
#  Une reponse vide ou illisible ne devient donc jamais PUBLIC par defaut.
# ══════════════════════════════════════════════════════════════════════════

def test_classer_exposition_rend_le_vocabulaire_du_corps():
    """Les quatre classes viennent de share_policy.json, pas d'une invention."""
    r = audit.classer_exposition('{"status": "ok"}')
    assert r["classe"] in ("PUBLIC", "INTERNAL", "CONFIDENTIAL", "SECRET", "UNKNOWN")


def test_une_topologie_est_CONFIDENTIAL():
    """« configuration, TOPOLOGIE » -- definition citee de CONFIDENTIAL.

    Mesure du 2026-09-22 : `/api/services/list` rend 59 services, 91 pid et
    24 port. Ce n'est pas un secret, c'est une carte -- et la carte est
    exactement ce que la classe CONFIDENTIAL nomme.
    """
    corps = '{"services": [{"name": "x", "pid": 1234, "port": 8766}]}'
    r = audit.classer_exposition(corps)
    assert r["classe"] == "CONFIDENTIAL"
    assert r["marqueurs"]["pid"] >= 1 and r["marqueurs"]["port"] >= 1


def test_un_credential_dans_la_reponse_est_SECRET():
    """Le cas qui doit primer sur tous les autres."""
    corps = 'const T = "' + "a" * 64 + '"; fetch(u, {headers:{Authorization:"Bearer "+T}})'
    r = audit.classer_exposition(corps)
    assert r["classe"] == "SECRET", (
        "une reponse portant un porteur n'est pas classee SECRET : le garde "
        "de `SECRET ne sort jamais` ne mordrait pas sur le contenu")


def test_l_instrument_ne_rend_AUCUNE_valeur():
    """INVARIANT DE SECURITE. Il compte, il ne recopie pas.

    Sans ce test, l'audit deviendrait lui-meme un canal de divulgation --
    exactement la faute commise le 2026-09-21 en envoyant une valeur de cle
    dans une sortie de mesure.
    """
    temoin = "MARQUEUR" + "-" + "a" * 48
    corps = '{"secret_de_test": "%s", "pid": 42}' % temoin
    r = audit.classer_exposition(corps)
    serialise = json.dumps(r, ensure_ascii=False) if "json" in dir() else str(r)
    assert temoin not in serialise, "l'instrument RECOPIE le contenu qu'il mesure"
    assert temoin[:16] not in serialise


def test_un_REFUS_n_est_pas_une_absence_d_exposition():
    """Mesure du 2026-09-22, sur le premier passage de l'instrument.

    `/admin/heap`, `/api/audit/recent` et `/api/ring_buffer/stats` -- trois
    routes GARDEES qui rendent 401 -- ressortaient « INTERNAL : aucun marqueur
    sensible detecte ». Elles n'ont rien montre parce qu'elles ont REFUSE, et
    l'instrument les rangeait du cote rassurant.

        UN REFUS N'EST PAS UNE ABSENCE D'EXPOSITION

    Le statut se lit donc AVANT le corps. Ce test garde la propriete sur la
    fonction de sondage, la ou elle est decidee.
    """
    import inspect
    src = inspect.getsource(audit.sonder_exposition)
    assert "NON_MESUREE" in src, (
        "la fonction de sondage ne distingue plus un refus d'une absence "
        "d'exposition : une route gardee serait classee sur le corps de son 401")
    # et la classe doit exister dans l'affichage, sinon elle serait muette
    assert "NON_MESUREE" in inspect.getsource(audit.main)


def test_une_reponse_vide_reste_UNKNOWN():
    """`UNKNOWN = REFUSE` (invariant cite de share_policy.json).

    Une reponse vide ou illisible ne prouve pas l'innocuite : elle prouve
    qu'on n'a pas pu juger. La ranger en PUBLIC serait la classer du cote
    rassurant par defaut -- ce que la constitution interdit.
    """
    for vide in ("", "   ", None):
        assert audit.classer_exposition(vide)["classe"] == "UNKNOWN"


def test_un_statut_simple_n_est_pas_CONFIDENTIAL():
    """CONTRE-EPREUVE : sans elle, tout serait classe sensible et la mesure
    ne distinguerait plus rien."""
    r = audit.classer_exposition('{"ok": true, "status": "healthy"}')
    assert r["classe"] != "CONFIDENTIAL"
    assert r["marqueurs"]["pid"] == 0 and r["marqueurs"]["port"] == 0


def test_la_classe_est_justifiee_par_un_marqueur_NOMME():
    """Un verdict sans raison n'est pas instruit : on doit pouvoir dire
    POURQUOI une route est classee, sans relire son contenu."""
    r = audit.classer_exposition('{"services": [{"pid": 7, "port": 80}]}')
    assert r.get("raison"), "la classe ne nomme pas ce qui l'a declenchee"
    assert "pid" in r["raison"] or "port" in r["raison"]


def test_aucune_route_NOUVELLE_ne_sert_un_credential():
    """Le garde qui manquait. Il ne casse rien : il enregistre et surveille."""
    routes = audit.auditer(avec_appelants=False)["routes"]
    src = audit.HUB.read_text(encoding="utf-8", errors="replace")
    idx, lignes = audit._handlers(src)
    nouvelles = []
    vues = 0
    for r in routes:
        corps = audit._corps(r["handler"], idx, lignes)
        if corps is None:
            continue          # handler illisible : UNKNOWN, pas « sain »
        vues += 1
        if audit._credential_emis(corps) and r["route"] not in _EMETTRICES_CONNUES:
            nouvelles.append(r["route"])
    assert vues, "aucun handler lu : le garde ne couvre rien"
    assert not nouvelles, (
        "route(s) servant un credential dans leur reponse : %s.\n"
        "`config/share_policy.json` classe les jetons SECRET et ecrit qu'ils "
        "NE SORTENT JAMAIS. Soit retirer l'injection, soit inscrire la route "
        "ici en sachant qu'elle distribue une autorite." % nouvelles)


def test_les_trois_emettrices_connues_le_sont_TOUJOURS():
    """CONTRE-EPREUVE. Si elles cessaient d'emettre, ce fichier devrait le
    dire -- sans quoi la liste blanche protegerait des routes devenues saines
    et masquerait la prochaine."""
    src = audit.HUB.read_text(encoding="utf-8", errors="replace")
    idx, lignes = audit._handlers(src)
    routes = {r["route"]: r for r in audit.auditer(avec_appelants=False)["routes"]}
    encore = []
    for c in sorted(_EMETTRICES_CONNUES):
        r = routes.get(c)
        if r is None:
            continue
        corps = audit._corps(r["handler"], idx, lignes)
        if corps is not None and audit._credential_emis(corps):
            encore.append(c)
    assert encore, (
        "AUCUNE des routes connues n'emet plus de credential -- tant mieux : "
        "retirer `_EMETTRICES_CONNUES` et laisser le garde strict")


def test_le_detecteur_d_emission_distingue_deux_cas_construits():
    """Sans contre-epreuve, un detecteur qui rend toujours vrai bloquerait
    toute route manipulant un jeton, y compris pour le VERIFIER."""
    emet = ('tok = _AGENT_TOKENS.get("CLAUDE", "") or HUB_TOKEN or ""\n'
            'html = html.replace("__LAFORGE_BEARER__", tok)\n'
            'return HTMLResponse(html)\n')
    verifie = ('valid = tok in set([HUB_TOKEN])\n'
               'if not valid:\n    return JSONResponse({}, status_code=401)\n')
    assert audit._credential_emis(emet)
    assert not audit._credential_emis(verifie), (
        "une route qui VERIFIE un porteur est accusee de le distribuer")


def test_une_verification_DELEGUEE_reste_une_garde():
    """FAUX NEGATIF introduit par le correctif d'a cote, et attrape le jour meme.

    `/api/login` ne compare rien SUR PLACE : il passe le credential a son juge.

        token = login_agent(role_id=..., agent_tokens=_AGENT_TOKENS, ...)

    `login_agent` compare et leve `ValueError` -> 401. Exiger une comparaison
    locale rangeait donc cette route parmi les « sans garde », et un NR
    existant l'a dit aussitot.

        CALL_SITE != DECISION_SITE -- le credential voyage vers son juge.
    """
    delegue = ("token = login_agent(role_id=role_id, secret_id=secret_id,\n"
               "                    agent_tokens=_AGENT_TOKENS)\n")
    assert audit._credential_compare(delegue, "_AGENT_TOKENS"), (
        "une verification deleguee est comptee comme une absence de garde")
    # et la contre-epreuve tient toujours : l'EMISSION n'est pas une delegation
    emis = 'tok = _AGENT_TOKENS.get("CLAUDE", "") or HUB_TOKEN or ""\n'
    assert not audit._credential_compare(emis, "_AGENT_TOKENS")


def test_une_borne_loopback_compte_comme_une_garde():
    """LA MESURE. `/debug/stacks` refuse 403 hors loopback."""
    routes = {r["route"]: r for r in audit.auditer(avec_appelants=False)["routes"]}
    r = routes.get("/debug/stacks")
    assert r is not None, "/debug/stacks a disparu de l'inventaire : re-mesurer"
    assert r["garde_detectee"], (
        "une borne loopback qui rend 403 n'est pas comptee comme garde : la "
        "route est rangee avec celles qui n'ont AUCUNE politique")


def test_la_borne_loopback_est_nommee_pour_ce_qu_elle_est():
    """Elle ne doit pas etre confondue avec une garde de porteur.

    Une borne d'ORIGINE et une preuve d'IDENTITE ne sont pas la meme chose --
    `LOCAL_ONLY != TRUSTED` (directive owner du 2026-09-18). L'inventaire doit
    donc les distinguer, sinon on croit 26 routes authentifiees la ou 25 le
    sont.
    """
    routes = {r["route"]: r for r in audit.auditer(avec_appelants=False)["routes"]}
    g = routes["/debug/stacks"]["garde_detectee"]
    assert "loopback" in str(g).lower() or "local" in str(g).lower(), (
        "la borne d'origine est rangee sous un nom de garde de porteur (%r) : "
        "elle serait comptee comme une authentification" % (g,))


def test_lire_client_host_sans_refuser_n_est_PAS_une_garde():
    """CONTRE-EPREUVE. Sans elle, toute route qui journalise l'adresse de son
    appelant serait declaree protegee -- un faux calme sur des routes nues."""
    sans_refus = ("ch = request.client.host\n"
                  "logger.info('appel depuis %s', ch)\n"
                  "return JSONResponse({'ok': True})\n")
    avec_refus = ("ch = request.client.host\n"
                  "if ch not in ('127.0.0.1', '::1'):\n"
                  "    return JSONResponse({'e': 1}, status_code=403)\n")
    assert not audit._borne_loopback(sans_refus), (
        "lire l'adresse de l'appelant suffit a passer pour une garde")
    assert audit._borne_loopback(avec_refus)


def test_un_commentaire_ne_fait_pas_un_appelant():
    """Le vocabulaire d'un fichier n'est pas son comportement.

    Verifie sur la primitive, pas sur le depot : un depot qui changerait
    rendrait ce test muet au lieu de le faire rougir.
    """
    assert not _APPEL_ROUTE.search("# voir /api/mcp/flags pour la bascule")
    assert not _APPEL_ROUTE.search('Route("/api/mcp/flags", h, methods=["POST"])')
    assert _APPEL_ROUTE.search("await fetch('/api/mcp/flags',{method:'POST'})")
