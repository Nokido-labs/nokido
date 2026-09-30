"""NR — un login non établi n'est pas un contrat UI violé.

Mesure du 2026-09-12 (run GitHub 34709188586, job `ui-acceptance`) :

    login -> http://127.0.0.1:7400/auth/login
    !!  /dashboard  inter=2/3  txt=89  LOGIN-REDIR
    !!  /maison     inter=2/3  txt=89  LOGIN-REDIR
    ... 17 routes, TOUTES en LOGIN-REDIR, txt=89 identique
    GATE: ROUGE (VIOLÉ — contrat/route en échec sur interface disponible)

Contre-mesure faite le même jour : avec une session correctement établie,
`GET /rag` rend 8 205 octets et les quatre marqueurs exigés par le contrat
(`chunks total`, `vectoris`, `domaines`, `tiktoken`) sont **présents**. Le
contrat est donc TENU ; ce qui a échoué, c'est l'authentification du gate.

`forge_ui_campaign` porte déjà quatre cas de troisième état — `/health`
injoignable, harnais Playwright absent, timeout de navigation, service mort en
cours de passe — tous introduits pour la même raison, écrite dans le module :
« on n'a rien jugé du tout ». Le cinquième manquait : une page de login n'est
pas la page demandée, donc la route n'a pas été jugée.

C'est la faute SYMÉTRIQUE de celle corrigée le 2026-09-11 (« un timeout ne doit
jamais devenir un succès ») : ici un inconnu devient un ÉCHEC. Les deux sens
sont faux — `UNKNOWN` n'est ni `NO`, ni `YES`.

ÉTAT ATTENDU : rouge tant que `_classer_routes` n'existe pas / ne sépare pas.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools"), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _campagne():
    """Import tolérant : le module tire Playwright, absent de certains comptes.
    On saute ALORS EN LE DISANT — jamais un vert silencieux."""
    try:
        import forge_ui_campaign as m
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"forge_ui_campaign non importable ici ({type(e).__name__}: {e})")
    return m


def _rec(route, *, contrat_ok, login_redir, fail=None, txt=89):
    """Forme RÉELLE d'un enregistrement de route, copiée du rapport du 12/09."""
    r = {"route": route, "label": route.strip("/") or "root",
         "contract_ok": contrat_ok, "contract_fail": [] if contrat_ok else ["manque:web hub"],
         "redirected_login": login_redir, "text_len": txt, "empty": False,
         "error_word": False, "console_errors": [], "api_errors": [],
         "n_interactive": 2, "n_interactive_total": 3}
    if fail:
        r["FAIL"] = fail
    return r


def test_la_fonction_de_classement_existe():
    """ROUGE ATTENDU d'abord : la décision était inline dans `run()`, donc
    invérifiable. Une logique de verdict qu'aucun test ne peut atteindre est une
    logique que personne ne garde."""
    m = _campagne()
    assert hasattr(m, "_classer_routes"), (
        "la decision du gate n'est pas extraite : elle reste inline dans run(), "
        "donc non testable")


def test_login_non_etabli_ne_vaut_pas_contrat_viole():
    """ROUGE ATTENDU avant correctif — le cas mesuré du run 34709188586."""
    m = _campagne()
    results = [_rec(p, contrat_ok=False, login_redir=True) for p in
               ("/dashboard", "/maison", "/rag", "/swarm", "/postal", "/vitals", "/mcp_lab")]
    infra, auth, ko = m._classer_routes(results)
    assert not ko, (
        "un echec d'AUTHENTIFICATION du gate est compte comme contrat VIOLE : %r"
        % ([r.get("route") for r in ko],))
    assert len(auth) == 7, "les 7 routes redirigees vers le login doivent etre NON JUGEES"


def test_un_vrai_manque_reste_bloquant():
    """Contrôle négatif : le correctif ne doit pas ouvrir une porte.

    Une route servie (pas de redirection) dont le contrat n'est pas tenu reste
    un échec — sinon on aurait échangé un faux rouge contre un faux vert.
    """
    m = _campagne()
    results = [_rec("/rag", contrat_ok=False, login_redir=False, txt=8205)]
    infra, auth, ko = m._classer_routes(results)
    assert len(ko) == 1, "un contrat non tenu sur une page REELLEMENT servie doit rougir"
    assert not auth


def test_melange_seul_le_non_authentifie_sort():
    """Une route en échec réel et une route non authentifiée ne se confondent pas."""
    m = _campagne()
    results = [_rec("/rag", contrat_ok=False, login_redir=False, txt=8205),
               _rec("/swarm", contrat_ok=False, login_redir=True)]
    infra, auth, ko = m._classer_routes(results)
    assert [r["route"] for r in ko] == ["/rag"]
    assert [r["route"] for r in auth] == ["/swarm"]


# ---------------------------------------------------------------------------
# Le comparateur de données — 6e cas de faux verdict (mesuré 2026-09-14)
# ---------------------------------------------------------------------------
#
# Run du 2026-09-14, gate ROUGE avec une seule route en cause :
#
#     GATE-KO /rag   contrat NON tenu: data:chunks_total(/api/rag/stats.total=2241501)
#
# Or le texte relevé sur la page, dans le rapport du run même :
#
#     "Nokido · RAG Dashboard\nChercher\n2 241 501\nChunks total\n65%\nVectorises..."
#
# La page affichait donc EXACTEMENT la bonne valeur, formatée pour l'humain. Le
# comparateur énumérait deux candidats en dur — la valeur brute et `f"{v:,}"`,
# c'est-à-dire le format ANGLAIS `2,241,501` — sur une interface en FRANÇAIS.
# Le gate accusait l'application d'un défaut qui était le sien.
#
# Même famille que les cinq cas précédents, mais dans l'autre sens : ici ce
# n'est pas un inconnu pris pour un échec, c'est un SUCCÈS pris pour un échec.
# Et la conséquence est celle d'un garde qui crie à faux : il se fait désarmer.

def test_valeur_formatee_en_francais_est_reconnue():
    """Espace fine insécable, insécable, ou normale : trois façons d'écrire le même nombre."""
    m = _campagne()
    for separateur in (" ", " ", " ", " "):
        texte = f"Chunks total{separateur}: 2{separateur}241{separateur}501 indexés"
        assert m.texte_porte_valeur(2241501, texte), (
            f"séparateur U+{ord(separateur):04X} non reconnu — le gate accuserait l'UI"
        )


def test_valeur_formatee_en_anglais_reste_reconnue():
    """Non-régression : le format déjà couvert doit le rester."""
    m = _campagne()
    assert m.texte_porte_valeur(2241501, "total 2,241,501 chunks")


def test_valeur_brute_reconnue():
    m = _campagne()
    assert m.texte_porte_valeur(2241501, "total=2241501")


def test_un_nombre_absent_reste_un_echec():
    """Contrôle négatif : le correctif ne doit pas fabriquer un faux vert.

    C'est la symétrie exigée par la constitution — on a déjà payé l'inverse
    (un timeout devenu succès le 2026-09-11).
    """
    m = _campagne()
    assert not m.texte_porte_valeur(2241501, "Chunks total 1 234 indexés")
    assert not m.texte_porte_valeur(2241501, "aucune donnée")


def test_pas_de_match_sur_un_nombre_plus_long():
    """`2 241 501` ne doit pas se reconnaître dans `12241501` ni `22415010`."""
    m = _campagne()
    assert not m.texte_porte_valeur(2241501, "reference 12241501")
    assert not m.texte_porte_valeur(2241501, "reference 22415010")


def test_valeur_absente_n_est_pas_une_valeur_affichee():
    """`None` = l'API n'a pas rendu la clé. UNKNOWN n'est pas une correspondance."""
    m = _campagne()
    assert not m.texte_porte_valeur(None, "2 241 501")


def test_petit_nombre_et_zero():
    """Un nombre sans séparateur passe par le même chemin — pas de cas particulier oublié."""
    m = _campagne()
    assert m.texte_porte_valeur(40, "40 Domaines")
    assert m.texte_porte_valeur(0, "0 erreur")
    assert not m.texte_porte_valeur(40, "400 Domaines")


def test_une_chaine_est_cherchee_telle_quelle():
    """Toutes les données de contrat ne sont pas des nombres."""
    m = _campagne()
    assert m.texte_porte_valeur("ok", "status: ok")
    assert not m.texte_porte_valeur("degraded", "status: ok")


# ---------------------------------------------------------------------------
# LE VERDICT, et plus seulement le CLASSEMENT. Cliquet du 2026-09-16.
#
# `_classer_routes` separait deja les routes non authentifiees des vrais echecs
# depuis le 2026-09-12. Mais la DECISION qui suit vivait encore inline dans
# `run()`, et elle etait en desaccord avec elle-meme. Mesure sur la CI de
# reference du 2026-09-16 (jobs job_f34603d549ba et job_b334189da2bc), 17 routes
# sur 20 redirigees vers /auth/login :
#
#   report.json     -> verdict "INDISPONIBLE"                        (juste)
#   ligne "GATE:"   -> "VERT (CONFORME -- contrats OK) -- livrable"  (faux)
#   code de retour  -> 0                                             (faux)
#
# Le jaune n'etait branche que sur `_mort_en_cours`, et `return 1 if gate_fail
# else 0` ne connaissait que deux etats. Or `ci_local` lit le CODE DE RETOUR
# pendant que `forge_ui_temoin` lit le RAPPORT : deux observateurs du meme fait,
# en desaccord, et c'est le mauvais qui decidait. Un gate vert avec 17 trous.
#
# Meme famille que le classement du 12/09, un cran plus loin : la-bas un inconnu
# devenait un ECHEC, ici un inconnu devient un SUCCES. Les deux sens sont faux.
#
# ETAT ATTENDU : rouge tant que `decider_verdict` n'existe pas.
# ---------------------------------------------------------------------------


def test_la_decision_de_verdict_est_isolable():
    """Une decision qui vit inline dans une coroutine de 500 lignes n'est gardee
    par personne : aucun test ne peut l'atteindre sans Playwright ni serveur."""
    m = _campagne()
    assert hasattr(m, "decider_verdict"), (
        "la decision de verdict est encore inline dans run() : intestable, donc "
        "non gardee"
    )


def test_login_non_etabli_n_est_PAS_un_vert():
    """LE cliquet. Un login qui echoue n'a rien juge -- ni tenu, ni viole."""
    m = _campagne()
    d = m.decider_verdict(gate_fail=False, auth_ko=["/rag", "/vitals"],
                          mort_en_cours=[])
    assert d["verdict"] == "AUTH_FAILURE", d
    assert d["rc"] != 0, "un rc nul se lit CONFORME chez ci_local"
    assert d["livrable"] is False
    assert "CONFORME" not in d["gate"], d["gate"]
    assert "NON livrable" in d["gate"], d["gate"]


def test_auth_failure_ne_se_confond_pas_avec_indisponible():
    """Deux causes distinctes, deux remedes distincts : reparer le login du gate
    n'est pas reparer le service. Les confondre envoie chercher la mauvaise panne."""
    m = _campagne()
    auth = m.decider_verdict(gate_fail=False, auth_ko=["/rag"], mort_en_cours=[])
    mort = m.decider_verdict(gate_fail=False, auth_ko=[], mort_en_cours=["/rag"])
    assert auth["verdict"] == "AUTH_FAILURE"
    assert mort["verdict"] == "INDISPONIBLE"
    assert auth["rc"] != mort["rc"], (
        "un seul code pour deux pannes : le log de CI ne permet plus de les separer"
    )


def test_le_service_mort_en_cours_ne_rend_plus_zero():
    """Meme defaut, meme ligne de code : `report.json` disait INDISPONIBLE et le
    code de retour disait 0. Corriger l'un sans l'autre laisserait un faux calme
    strictement equivalent, un cran a cote."""
    m = _campagne()
    d = m.decider_verdict(gate_fail=False, auth_ko=[], mort_en_cours=["/dashboard"])
    assert d["rc"] != 0, d
    assert d["livrable"] is False


def test_un_contrat_reellement_viole_prime():
    """La reserve du 12/09 tient : une route SERVIE dont le contrat n'est pas tenu
    reste bloquante, meme si d'autres routes n'ont pas pu etre authentifiees.
    Sans cette priorite on echangerait un faux vert contre un autre faux vert."""
    m = _campagne()
    d = m.decider_verdict(gate_fail=True, auth_ko=["/rag"], mort_en_cours=["/feed"])
    assert d["verdict"] == "VIOLÉ", d
    assert d["rc"] == 1, "ci_local traite rc=1 comme le contrat viole"


def test_le_cas_nominal_reste_vert():
    """Symetrie obligatoire : ne pas remplacer une sur-deduction par l'autre.
    Sans rien a signaler, le gate doit toujours pouvoir rendre un vert -- un garde
    qui crie a faux se fait desarmer."""
    m = _campagne()
    d = m.decider_verdict(gate_fail=False, auth_ko=[], mort_en_cours=[])
    assert d["verdict"] == "CONFORME"
    assert d["rc"] == 0
    assert d["livrable"] is True


def test_run_delegue_la_decision_au_lieu_de_la_refaire():
    """Deux endroits qui decident du meme verdict finissent par diverger -- c'est
    exactement ce qui vient d'etre paye entre le rapport, la ligne GATE et le rc."""
    import ast
    source = (RACINE / "tools" / "forge_ui_campaign.py").read_text(encoding="utf-8")
    arbre = ast.parse(source)
    appels = {
        n.func.id
        for n in ast.walk(arbre)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "decider_verdict" in appels, (
        "run() n'appelle pas la decision extraite : elle serait morte, et le NR "
        "garderait une fonction que la production n'emprunte pas"
    )
    # ON LIT LE CODE, PAS LA PROSE. Premiere version de ce test : `assert
    # "return 1 if gate_fail else 0" not in source`. Il est passe au ROUGE des
    # que la docstring de `decider_verdict` a CITE l'ancienne ligne pour
    # expliquer ce qu'elle remplace. Un instrument ne lit jamais son propre
    # vocabulaire (RULES_SHARED, reflexes de developpement) -- et une recherche
    # textuelle ne distingue pas un commentaire d'une instruction.
    fonction_run = next(
        n for n in ast.walk(arbre)
        if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == "run"
    )
    retours = [n for n in ast.walk(fonction_run) if isinstance(n, ast.Return)]
    assert retours, "run() ne retourne plus de code de sortie"
    assert not any(isinstance(r.value, ast.IfExp) for r in retours), (
        "run() decide encore son code de retour par un ternaire a deux branches : "
        "quatre etats n'entrent pas dans deux issues, et le quatrieme sort a 0"
    )


def test_ci_local_interprete_le_code_auth_failure():
    """Cliquet du chemin REEL : la campagne peut bien rendre 3, si l'appelant ne
    connait pas ce code il tombe dans son `else` -- qui vaut FAIL ou vaut vert
    selon la branche, les deux etant faux."""
    source = (RACINE / "tools" / "ci_local.py").read_text(encoding="utf-8")
    assert "rc == 3" in source, (
        "ci_local ne connait pas AUTH_FAILURE : le code tombe dans une branche "
        "prevue pour autre chose"
    )
    # La fenetre couvre la BRANCHE, pas un nombre de caracteres devine : la
    # premiere version en bornait 1200, soit moins que le commentaire qui motive
    # la branche -- elle rougissait sur la longueur d'une explication.
    debut = source.index("rc == 3")
    suite = source.find("elif ", debut + 1)
    fenetre = source[debut:suite if suite > debut else debut + 3000]
    assert "_INCONCLUS.append" in fenetre, (
        "AUTH_FAILURE n'est pas enregistre comme inconclusion : un non-juge qui "
        "ne laisse aucune trace redevient un vert"
    )
    assert "NON JUGE" in fenetre, (
        "le resultat n'est pas marque NON JUGE dans la liste des gates"
    )


# ---------------------------------------------------------------------------
# LES SIGNAUX PROMIS ET JAMAIS COMPTES. Cliquet du 2026-09-16 (second).
#
# `forge_ui_campaign` DECLARE, dans le commentaire qui a elargi son perimetre le
# 2026-08-29 : « Les dix routes ajoutees n'ont pas de `must` [...] Elles sont
# jugees sur ce qui se mesure sans convention -- la page rend, elle n'est pas
# vide, aucune exception JS, aucune API en 4xx/5xx, et ses boutons surs font
# quelque chose. »
#
# MESURE : rien de cela n'entre dans le verdict.
#   rec["contract_ok"] = (not c_fail) if contract else None
# Sans contrat declare, `contract_ok` vaut None -- et `_classer_routes` retient
# `contract_ok is False`, que None ne satisfait jamais. `empty`, `error_word`,
# `console_errors` et `api_errors` sont collectes, AFFICHES en drapeaux, puis
# jetes. Une page qui rend « Traceback » sort donc CONFORME.
#
# C'est le motif « ne jamais confondre l'existence d'un mecanisme avec son effet
# reel » : ici la doctrine du fichier promet un jugement que son code ne rend
# pas, et 10 routes sur 20 ne sont jugees sur RIEN.
#
# Corrobore par la CI du 2026-09-16 : /llm_dashboard, /forge/feed et /anatomy
# portaient JS-ERR ou API>=400 et comptaient parmi les 3 routes « jugees » du
# verdict CONFORME.
#
# ETAT ATTENDU : rouge tant que `_routes_degradees` n'existe pas.
# ---------------------------------------------------------------------------


def _degrade(m, results):
    """Applique le classement complet, dans l'ordre reel de `run()`."""
    infra, auth_ko, ko = m._classer_routes(results)
    return m._routes_degradees(results, infra, auth_ko, ko)


def test_le_classement_des_degradees_existe():
    m = _campagne()
    assert hasattr(m, "_routes_degradees"), (
        "les signaux collectes ne sont rattaches a aucune decision : ils sont "
        "affiches puis jetes"
    )


def test_une_exception_JS_ne_passe_plus_pour_conforme():
    m = _campagne()
    r = _rec("/llm_dashboard", contrat_ok=None, login_redir=False)
    r["console_errors"] = ["TypeError: e.data is undefined"]
    d = _degrade(m, [r])
    assert [x.get("route") for x in d] == ["/llm_dashboard"], d


def test_une_erreur_JS_BENIGNE_ne_degrade_PAS():
    """Symetrie obligatoire. `_is_benign_err` ecarte deja les coupures de SSE en
    fin de page ; les recompter ici ferait crier le garde a faux, et un garde qui
    crie a faux se fait desarmer."""
    m = _campagne()
    r = _rec("/vitals", contrat_ok=None, login_redir=False)
    r["console_errors"] = []
    r["console_benign"] = ["connection interrupted while page loading"]
    assert _degrade(m, [r]) == []


def test_une_api_en_4xx_ou_5xx_degrade():
    m = _campagne()
    r = _rec("/forge/feed", contrat_ok=None, login_redir=False)
    r["api_errors"] = ["GET /api/feed -> 500"]
    assert [x.get("route") for x in _degrade(m, [r])] == ["/forge/feed"]


def test_un_mot_d_erreur_rendu_par_la_page_degrade():
    """`error_word` capte traceback / unauthorized / 500 internal. Une page qui
    AFFICHE sa propre panne n'est pas une page qui marche."""
    m = _campagne()
    r = _rec("/anatomy", contrat_ok=None, login_redir=False)
    r["error_word"] = True
    assert [x.get("route") for x in _degrade(m, [r])] == ["/anatomy"]


def test_une_page_vide_degrade():
    m = _campagne()
    r = _rec("/organs", contrat_ok=None, login_redir=False, txt=3)
    r["empty"] = True
    assert [x.get("route") for x in _degrade(m, [r])] == ["/organs"]


def test_une_route_deja_classee_n_est_pas_comptee_deux_fois():
    """Un non-jugement reste un non-jugement : une route dont on n'a vu que le
    formulaire de login ne devient pas « degradee » parce qu'elle porte aussi une
    erreur JS. Sinon un meme defaut se compte dans deux categories et les
    denombrements du resume deviennent faux."""
    m = _campagne()
    auth = _rec("/rag", contrat_ok=None, login_redir=True)
    auth["console_errors"] = ["ReferenceError"]
    casse = _rec("/swarm", contrat_ok=False, login_redir=False)
    casse["api_errors"] = ["GET /api/swarm -> 502"]
    assert _degrade(m, [auth, casse]) == []


def test_le_verdict_degrade_dit_la_verite_sur_les_trois_sorties():
    m = _campagne()
    d = m.decider_verdict(gate_fail=False, auth_ko=[], mort_en_cours=[],
                          degrade=[{"route": "/anatomy"}])
    assert d["verdict"] == "DEGRADE", d
    assert d["rc"] != 0, "un rc nul se lit CONFORME chez ci_local"
    assert d["livrable"] is False
    assert "CONFORME" not in d["gate"], d["gate"]


def test_degrade_ne_prime_sur_aucun_non_jugement():
    """Le plus faible des quatre : une page degradee a au moins ete VUE, la ou un
    login non etabli n'a rien vu du tout."""
    m = _campagne()
    d = m.decider_verdict(gate_fail=False, auth_ko=["/rag"], mort_en_cours=[],
                          degrade=[{"route": "/anatomy"}])
    assert d["verdict"] == "AUTH_FAILURE", d


def test_le_vert_reste_atteignable_sans_degradation():
    m = _campagne()
    d = m.decider_verdict(gate_fail=False, auth_ko=[], mort_en_cours=[], degrade=[])
    assert d["verdict"] == "CONFORME"
    assert d["rc"] == 0


def test_ci_local_observe_la_degradation_avant_de_l_enforcer():
    """Un gate neuf s'observe avant de bloquer -- meme discipline que le gate
    `anatomie`. Mais il OBSERVE un signal VRAI : la campagne rend bien un code
    distinct et un « NON livrable », c'est l'appelant qui differe l'enforcement.
    Promouvoir ne doit donc rien reecrire, seulement lever l'interrupteur."""
    source = (RACINE / "tools" / "ci_local.py").read_text(encoding="utf-8")
    assert "rc == 4" in source, "ci_local ne connait pas le code DEGRADE"
    debut = source.index("rc == 4")
    suite = source.find("elif ", debut + 1)
    fenetre = source[debut:suite if suite > debut else debut + 3000]
    assert "OBSERVATION" in fenetre, (
        "la degradation n'est pas annoncee comme une observation : on ne saura "
        "pas si son silence vaut absence de defaut ou absence de mesure"
    )
    assert "LAFORGE_UI_DEGRADE_BLOQUANT" in fenetre, (
        "aucun interrupteur de promotion : un gate qu'on ne peut pas promouvoir "
        "reste une observation pour toujours"
    )


# ---------------------------------------------------------------------------
# POURQUOI LE LOGIN N'ETAIT PAS ETABLI. Cliquet du 2026-09-16 (troisieme).
#
# `ui-acceptance` est ANERGIQUE depuis toujours -- « aucun verdict reel depuis
# jamais » sur un domaine declare CRITIQUE. On a longtemps soupconne Playwright ou
# l'IP interne. MESURE de la CI de reference de ce jour : Playwright s'execute tres
# bien, il a visite 20 routes. C'est le LOGIN qui n'a pas eu lieu.
#
#   [nokido_web_hub] LAFORGE_ADMIN_TOKEN set after load: False
#   login -> http://<hote>:7400/auth/login        <- l'URL finale EST la page de login
#   HORS COFFRE tools/nokido_web_hub.py:44  LAFORGE_ADMIN_TOKEN
#
# ⚠️ ET UNE CAUSE QUE J'AI CRU TENIR, PUIS MESUREE FAUSSE. J'ai d'abord ecrit que
# `AuthConfig.from_env()` lisait l'ENVIRONNEMENT SEUL. C'est faux : il importe
# `forge_secrets.get_secret` et consulte DEJA le coffre. Mesure sous le compte du
# hub : `admin_token` present (64 caracteres) alors que la variable
# d'environnement est VIDE, et deux appels rendent la MEME valeur.
# La cause de l'echec du login reste donc NON ETABLIE : le client a un jeton, et
# les routes voient quand meme le formulaire. Restent a departager -- serveur qui
# attend un autre secret, champ de formulaire change, ou compte du job qui n'ouvre
# pas le coffre. `resoudre_credential` est un FILET, pas le correctif.
#
# ET LE DEFAUT QUI REND CELA INDIAGNOSTICABLE : `login_state` ne contient qu'une
# URL. « login tente et refuse » et « login JAMAIS TENTE faute de jeton » s'y
# ecrivent pareil. Encore un troisieme etat manquant.
#
# ETAT ATTENDU : rouge tant que le credential ne consulte pas le coffre et que le
# non-lancement du login ne se nomme pas.
# ---------------------------------------------------------------------------


def test_le_credential_consulte_le_COFFRE_a_defaut_de_l_environnement():
    m = _campagne()
    assert m.resoudre_credential(depuis_env="", depuis_coffre="jeton-du-coffre") == (
        "jeton-du-coffre", "coffre"), "le coffre n'est pas consulte quand l'env est vide"


def test_l_environnement_reste_prioritaire_quand_il_porte_le_jeton():
    """Ne pas casser le chemin qui marche deja sur le poste owner."""
    m = _campagne()
    assert m.resoudre_credential(depuis_env="jeton-env",
                                 depuis_coffre="jeton-coffre") == ("jeton-env", "env")


def test_aucune_source_rend_une_SOURCE_NOMMEE_et_pas_une_chaine_vide():
    m = _campagne()
    cred, source = m.resoudre_credential(depuis_env="", depuis_coffre="")
    assert cred == ""
    assert source == "aucune", source


def test_un_login_JAMAIS_TENTE_ne_se_confond_pas_avec_un_login_REFUSE():
    """C'est toute la difference entre « repare le jeton » et « repare le
    formulaire ». Une URL seule ne les distingue pas."""
    m = _campagne()
    assert m.etat_login(auth_active=True, cred="", url_finale="http://h/auth/login") \
        == "NON_TENTE_CREDENTIAL_ABSENT"
    assert m.etat_login(auth_active=False, cred="x", url_finale="http://h/auth/login") \
        == "NON_TENTE_AUTH_DESACTIVEE"
    assert m.etat_login(auth_active=True, cred="x", url_finale="http://h/auth/login") \
        == "TENTE_ET_REFUSE"
    assert m.etat_login(auth_active=True, cred="x", url_finale="http://h/dashboard") \
        == "ETABLI"


# ---------------------------------------------------------------------------
# L'ERREUR DOIT NOMMER SON SCRIPT. Cliquet du 2026-09-16 (quatrieme).
#
# Le gate a enfin juge, et il a trouve : 20 routes DEGRADE, dont 19 portant la
# MEME erreur -- `Cannot read properties of null (reading 'appendChild')`. Un seul
# script commun a toutes les pages. Mais IMPOSSIBLE de dire lequel :
#
#     br.page.on("pageerror", lambda e: errs.append("pageerror: " + str(e)))
#
# `str(e)` sur une Error Playwright rend le MESSAGE seul. L'objet porte pourtant
# `.stack`, qui nomme le fichier et la ligne. La pile est disponible et JETEE --
# exactement le defaut des quatre signaux collectes puis abandonnes que ce meme
# fichier vient de corriger, un etage plus loin.
#
# Consequence concrete : j'ai un suspect (`sidebar.html`, `m.appendChild` sans
# garde) et aucune preuve. Un instrument qui dit « quelque chose a casse quelque
# part » oblige a deviner, et deviner est ce qui a coute le plus cher aujourd'hui.
#
# ETAT ATTENDU : rouge tant que la pile est jetee.
# ---------------------------------------------------------------------------


class _ErreurAvecPile:
    """Forme REELLE d'une Error Playwright : message + name + stack."""
    message = "Cannot read properties of null (reading 'appendChild')"
    name = "TypeError"
    stack = ("TypeError: Cannot read properties of null (reading 'appendChild')\n"
             "    at addMsg (http://h:7400/sidebar.js:94:5)\n"
             "    at http://h:7400/sidebar.js:12:3")

    def __str__(self):
        return self.message


def test_l_erreur_de_page_garde_la_PILE_qui_nomme_le_fichier():
    m = _campagne()
    texte = m._texte_erreur_page(_ErreurAvecPile())
    assert "sidebar.js:94" in texte, (
        "la pile est jetee : l'erreur ne dit pas QUEL script, donc il faut deviner"
    )


def test_sans_pile_le_message_reste_rendu():
    """Trois etats : avec pile, sans pile, et jamais vide."""
    m = _campagne()
    assert "boom" in m._texte_erreur_page("boom")


def test_la_borne_de_la_pile_DIT_qu_elle_tronque():
    """Une borne doit dire COMBIEN, pas seulement TROP -- motif `borne_trop_serree`,
    paye le 2026-07-25 quand `text[:3000]` a detruit 377 documents en silence."""
    class _Longue:
        stack = "x" * 5000

        def __str__(self):
            return "court"

    texte = m_txt = _campagne()._texte_erreur_page(_Longue())
    assert len(m_txt) < 5000, "aucune borne : un dump de pile noiera le rapport"
    assert "tronqu" in texte.lower() or "..." in texte, (
        "la pile est coupee sans le dire : on ne saura pas qu'il manque des cadres"
    )


def test_le_collecteur_de_page_emprunte_bien_cette_fonction():
    """Une fonction correcte que le collecteur n'appelle pas ne repare rien."""
    import inspect

    src = inspect.getsource(_campagne())
    i = src.find('page.on("pageerror"')
    assert i > 0, "le collecteur d'erreurs de page a disparu"
    assert "_texte_erreur_page" in src[i:i + 300], (
        "le collecteur construit encore son texte a la main : la pile sera jetee"
    )


# ---------------------------------------------------------------------------
# LA SONDE NE DOIT PAS S'ACCUSER ELLE-MEME. Cliquet du 2026-09-16 (cinquieme).
#
# Premiere passe reelle du verdict DEGRADE : 20 routes en defaut, dont 19 avec la
# MEME erreur, `Cannot read properties of null (reading 'appendChild')`. J'ai
# soupconne `sidebar.html`, commun a toutes les pages. C'ETAIT FAUX.
#
# La pile, une fois conservee, ne montre AUCUN fichier du site :
#     at <anonymous>:2:211
#     at <anonymous>:2:229
# `<anonymous>` designe du code injecte par `page.add_init_script()` -- c'est-a-dire
# la sonde de la campagne ELLE-MEME. `_DISABLE_ANIM` fait
# `(document.head||document.documentElement).appendChild(s)`, et un init script
# s'execute AVANT tout script de la page, a un instant ou les DEUX peuvent etre
# null. La sonde plante, la page recolte l'erreur, et le gate accuse le site.
#
# LES 20 ROUTES DEGRADE ETAIENT DONC UN FAUX POSITIF DE L'INSTRUMENT. C'est la
# regle « un capteur neuf est un SUSPECT, pas un temoin » payee en direct -- et la
# justification de l'avoir pose en OBSERVATION : bloquant, il aurait arrete la CI
# sur un bug de ma propre sonde.
#
# ETAT ATTENDU : rouge tant que la sonde n'attend pas le document.
# ---------------------------------------------------------------------------


def test_la_sonde_injectee_attend_le_document_avant_d_y_ecrire():
    m = _campagne()
    js = m._DISABLE_ANIM
    assert ("readyState" in js) or ("DOMContentLoaded" in js), (
        "la sonde ecrit dans le document des l'init script : head ET "
        "documentElement peuvent etre null a cet instant, elle plante et le gate "
        "impute son propre crash au site"
    )


def test_la_sonde_ne_desarme_pas_sa_garde_existante():
    """Ne pas remplacer un faux positif par une sonde qui n'ecrit jamais : la
    desactivation des animations sert a stabiliser les captures."""
    m = _campagne()
    assert "appendChild" in m._DISABLE_ANIM, "la sonde n'injecte plus rien"
    assert "animation-duration" in m._DISABLE_ANIM


# ---------------------------------------------------------------------------
# NOMMER SANS DEGRADER DAVANTAGE. Cliquet du 2026-09-16 (sixieme).
#
# Verdict de reference apres correction de la sonde : 2 routes en defaut au lieu
# de 20. L'une, `/maison`, rend parfaitement sa page (434 caracteres, flotte
# affichee) mais une ressource repond 404. PROBLEME : on sait qu'il y a un 404,
# on ne sait pas LEQUEL. Le collecteur de reponses filtre sur `"/api/" in r.url`,
# donc un 404 sur une ressource STATIQUE n'entre jamais dans `api_errors` ; il
# n'apparait qu'en console, sans son URL.
#
# C'est la troisieme fois de la journee que l'instrument voit un defaut sans
# pouvoir le nommer -- apres les quatre signaux jetes, et apres la pile d'erreur.
#
# MAIS ELARGIR LE FILTRE SERAIT PIRE. Compter toute reponse >= 400 comme un
# defaut capterait les favicons et les sondes optionnelles : on remplacerait un
# angle mort par du bruit, juste apres avoir passe la journee a supprimer 18 faux
# positifs. La forme juste separe les deux roles : NOMMER tout ce qui echoue,
# DEGRADER seulement sur `/api/`.
#
# ETAT ATTENDU : rouge tant que le classement n'existe pas.
# ---------------------------------------------------------------------------


def test_une_api_en_echec_est_classee_api():
    m = _campagne()
    assert m.classer_reponse(500, "http://h:7400/api/services") == "api"
    assert m.classer_reponse(404, "http://h:7400/api/x?y=1") == "api"


def test_une_ressource_statique_en_echec_est_NOMMEE_mais_pas_api():
    """Elle doit etre visible -- sinon on ne saura jamais QUELLE ressource manque --
    sans pour autant faire basculer le verdict."""
    assert _campagne().classer_reponse(404, "http://h:7400/static/x.js") == "ressource"


def test_une_reponse_saine_n_est_classee_nulle_part():
    m = _campagne()
    assert m.classer_reponse(200, "http://h:7400/api/ok") is None
    assert m.classer_reponse(304, "http://h:7400/static/a.css") is None


def test_le_collecteur_emprunte_ce_classement():
    # Ce test lisait une FENETRE de 320 caracteres apres `page.on("response"`.
    # Il est passe ROUGE le 2026-09-16 quand le collecteur est devenu une
    # fonction nommee, DEFINIE AVANT l'abonnement : le code etait juste,
    # l'instrument non. Deuxieme fenetre devinee payee dans la journee — on
    # interroge la STRUCTURE, jamais un nombre de caracteres.
    import ast
    import inspect

    arbre = ast.parse(inspect.getsource(_campagne()))
    rep = [n for n in ast.walk(arbre)
           if isinstance(n, ast.FunctionDef) and n.name == "_reponse"]
    assert rep, "le collecteur de reponses a disparu"
    appels = {n.func.id for n in ast.walk(rep[0])
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "classer_reponse" in appels, (
        "le collecteur refait son tri a la main : la ressource restera anonyme"
    )


def test_les_ressources_en_echec_remontent_au_rapport():
    """Collecte puis jetee, c'est le defaut que ce fichier corrige depuis ce matin.
    Ce qui est mesure doit arriver jusqu'au rapport."""
    import inspect

    src = inspect.getsource(_campagne())
    assert "ressources_ko" in src, (
        "les ressources en echec ne sont portees nulle part : mesurees puis perdues"
    )


def test_le_contrat_utilise_bien_ce_comparateur():
    """Un comparateur juste que la vérification n'appelle pas ne garde rien.

    Lecture AST : la boucle `contract.get("data", ...)` doit passer par
    `texte_porte_valeur`, et ne plus fabriquer ses candidats en dur.
    """
    import ast
    source = (RACINE / "tools" / "forge_ui_campaign.py").read_text(encoding="utf-8")
    arbre = ast.parse(source)
    appels = {
        n.func.id
        for n in ast.walk(arbre)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "texte_porte_valeur" in appels, (
        "la verification de contrat n'appelle pas le comparateur : il serait mort"
    )
    assert "_cands" not in source, (
        "l'ancienne enumeration de formats subsiste — deux comparateurs qui "
        "divergeront"
    )


# ---------------------------------------------------------------------------
# NOMMER LA RESSOURCE EN ECHEC — et savoir si le collecteur a seulement REGARDE
#
# MESURE 2026-09-16, APRES le correctif `classer_reponse`. `/maison` sortait
# DEGRADE pour un 404 et `ressources_ko` etait VIDE. Deux lectures tenaient dans
# ce vide et rien ne les separait : le collecteur n'a rien vu, ou il a vu et
# filtre. C'est la confusion RIEN TROUVE / JE N'AI PAS PU REGARDER, et un
# rapport qui ne la tranche pas se lit comme rassurant.
#
# Deux instruments, pas un, et aucun des deux n'elargit ce qui DEGRADE :
#  * la LOCATION du message console porte DEJA l'URL fautive ; on la jetait des
#    que le texte etait non vide, donc precisement pour ce message-la ;
#  * un DENOMINATEUR (reponses vues) tranche les deux lectures du vide.
# ---------------------------------------------------------------------------

_MSG_404 = "Failed to load resource: the server responded with a status of 404 (Not Found)"


def test_un_message_de_ressource_en_echec_recoit_l_url_de_sa_location():
    m = _campagne()
    texte = m.enrichir_texte_console(
        "error", _MSG_404,
        {"url": "http://hote:7400/static/absent.css", "lineNumber": 0, "columnNumber": 0},
    )
    assert "absent.css" in texte, (
        "le 404 reste anonyme alors que le navigateur en donne l'URL dans la "
        "location du message : on sait qu'il y a un defaut, jamais lequel"
    )


def test_un_message_qui_porte_DEJA_son_url_n_est_pas_double():
    m = _campagne()
    texte = m.enrichir_texte_console(
        "error", "TypeError: Failed to fetch http://hote:7400/forge/feed",
        {"url": "http://hote:7400/forge/feed", "lineNumber": 93, "columnNumber": 35},
    )
    assert texte.count("http://hote:7400/forge/feed") == 1, (
        "l'URL est repetee : le rapport devient illisible sans rien apprendre"
    )


def test_sans_location_exploitable_le_texte_reste_INTACT():
    m = _campagne()
    assert m.enrichir_texte_console("error", _MSG_404, {}) == _MSG_404, (
        "une location absente ajoute un ornement vide ; ne rien savoir se dit "
        "en ne rien ajoutant"
    )


def test_le_cas_JSHandle_garde_son_comportement():
    m = _campagne()
    texte = m.enrichir_texte_console(
        "error", "JSHandle@object",
        {"url": "http://hote:7400/static/nokido.js", "lineNumber": 12, "columnNumber": 3},
    )
    assert "nokido.js" in texte and "12" in texte, (
        "la ligne et la colonne du cas JSHandle ont ete perdues au passage"
    )


def test_un_message_qui_n_est_pas_une_erreur_est_IGNORE():
    m = _campagne()
    assert m.enrichir_texte_console("log", "bonjour", {"url": "http://h/x"}) is None, (
        "un simple log entrerait dans les erreurs de console et degraderait"
    )


def test_le_collecteur_console_emprunte_cette_fonction():
    import ast
    import inspect
    m = _campagne()
    arbre = ast.parse(inspect.getsource(m))
    console = [n for n in ast.walk(arbre)
               if isinstance(n, ast.FunctionDef) and n.name == "_console"]
    assert console, "le collecteur console a disparu"
    appels = {n.func.id for n in ast.walk(console[0])
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "enrichir_texte_console" in appels, (
        "la fonction est testee mais le chemin reel ne l'appelle pas — un vert "
        "qui ne prouve rien sur la campagne"
    )


def test_le_collecteur_de_reponses_compte_TOUT_avant_de_filtrer():
    import ast
    import inspect
    m = _campagne()
    arbre = ast.parse(inspect.getsource(m))
    rep = [n for n in ast.walk(arbre)
           if isinstance(n, ast.FunctionDef) and n.name == "_reponse"]
    assert rep, (
        "le collecteur de reponses est reste une lambda : il ne peut pas tenir "
        "de denominateur"
    )
    corps = [n for n in rep[0].body
             if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
    assert corps and not isinstance(corps[0], ast.If), (
        "le comptage est sous une condition : il compterait les defauts, pas "
        "les reponses — un denominateur filtre n'est pas un denominateur"
    )


def test_le_rapport_porte_le_denominateur_des_reponses_vues():
    import inspect
    m = _campagne()
    assert '"n_responses"' in inspect.getsource(m), (
        "le rapport ne dit pas combien de reponses ont ete vues : "
        "`ressources_ko: []` restera indistinguable d'un collecteur muet"
    )


# ---------------------------------------------------------------------------
# DEUX FAUX POSITIFS DU GATE, NOMMES PAR LA PASSE DU 2026-09-16 (job f7177800d282)
#
# Une fois les messages NOMMES, deux des trois routes DEGRADE se sont revelees
# etre des defauts de l'INSTRUMENT, pas de l'interface :
#
#   /maison        404 @ http://<hote>:7400/favicon.ico
#   /forge/feed    « Nokido Event Feed (Audit Trail) », 24 961 caracteres,
#                  mot d'erreur trouve DANS le journal qu'elle affiche
#
# C'est la suite de 20 -> 2 : nommer un defaut permet de le DISQUALIFIER. Tant
# que le 404 etait anonyme, il paraissait serieux ; il manquait une icone.
#
# ⚠️ Le coup de force a NE PAS faire : rendre benin tout 404, ou retirer la
# detection de mot d'erreur. On perdrait le signal pour supprimer le bruit. Les
# deux correctifs sont donc ETROITS et structurels — l'icone de l'onglet n'est
# pas une ressource de l'interface ; une page qui EST une erreur l'annonce en
# tete, une page qui AFFICHE des erreurs les porte dans son corps.
# ---------------------------------------------------------------------------

_404 = "Failed to load resource: the server responded with a status of 404 (Not Found)"


def test_un_404_de_favicon_est_BENIN():
    m = _campagne()
    assert m._is_benign_err(_404 + " @ http://hote:7400/favicon.ico"), (
        "une icone d'onglet manquante rend l'interface NON LIVRABLE : le gate "
        "crie a faux, et un gate qui crie a faux se fait desarmer"
    )


def test_un_404_sur_une_VRAIE_ressource_reste_un_defaut():
    m = _campagne()
    assert not m._is_benign_err(_404 + " @ http://hote:7400/static/app.js"), (
        "le correctif du favicon a ete elargi a tout 404 : on a supprime le "
        "bruit en supprimant le signal"
    )


def test_les_erreurs_benignes_deja_reconnues_le_restent():
    m = _campagne()
    assert m._is_benign_err("NS_BINDING_ABORTED: interrupted while page loading"), (
        "une regression sur les cas benins historiques"
    )


def test_une_page_qui_EST_une_erreur_est_detectee():
    m = _campagne()
    tete, _hors = m.mot_d_erreur("Traceback (most recent call last): ...")
    assert tete, "un traceback rendu par la page n'est plus vu — signal perdu"


def test_un_JOURNAL_qui_AFFICHE_des_erreurs_n_est_pas_une_page_en_erreur():
    m = _campagne()
    texte = "Nokido Event Feed (Audit Trail)\nLive polling\n" + ("evenement banal " * 2000) + " exception: quelque chose"
    tete, hors = m.mot_d_erreur(texte)
    assert not tete, (
        "le flux d'evenements degrade le gate parce qu'il fait son METIER : "
        "afficher des erreurs passees"
    )
    assert hors, (
        "l'occurrence a ete jetee en silence — on n'ecarte jamais une donnee "
        "sans la nommer"
    )


def test_une_page_COURTE_est_scannee_ENTIEREMENT():
    m = _campagne()
    tete, _hors = m.mot_d_erreur("Nokido\nmenu\n" + "x" * 500 + "\n500 Internal Server Error")
    assert tete, (
        "une page courte qui finit en erreur passe pour saine : la fenetre de "
        "tete ne doit pas s'appliquer a ce qui tient d'un coup d'oeil"
    )


def test_le_rapport_emprunte_ce_detecteur_et_garde_le_hors_tete():
    import inspect
    m = _campagne()
    source = inspect.getsource(m)
    assert "mot_d_erreur(" in source, (
        "le detecteur est teste mais le rapport refait le test a la main"
    )
    assert '"mots_erreur_hors_tete"' in source, (
        "les occurrences hors tete ne remontent nulle part : ecartees en silence"
    )


# ---------------------------------------------------------------------------
# QUELLE COUCHE SERT LE JETON — l'etiquette `credential=env` ne dit RIEN
#
# MESURE 2026-09-16. En local le login est ETABLI ; en CI (run 35112068168) il
# est TENTE_ET_REFUSE. Les deux passes impriment `credential=env`, donc
# l'instrument ne permet pas de les distinguer — l'etiquette est posee des que
# `from_env()` rend quelque chose, alors que `get_secret` a QUATRE couches :
# coffre DPAPI, WCM, fichier .env, puis `os.environ` en dernier recours.
#
# Mesure sous le compte du hub : coffre=64 c., les trois autres ABSENTES. Et le
# secret GitHub `LAFORGE_ADMIN_TOKEN` date du 2026-07-03, jamais renouvele.
# Rien de tout cela ne prouve encore laquelle sert en CI : c'est justement ce
# que l'instrument doit dire, au lieu qu'on le devine.
#
# ANTI-DUP : `forge_secrets.diagnostic()` classe DEJA les cles par couche et ne
# divulgue aucune valeur. On le reutilise. Son angle mort est nomme : il ne
# teste pas `os.environ`, donc une cle servie en dernier recours tombe dans
# `missing` — et c'est precisement le cas qu'on cherche a reconnaitre.
# ---------------------------------------------------------------------------


def test_la_couche_du_coffre_est_nommee():
    m = _campagne()
    diag = {"in_vault": ["LAFORGE_ADMIN_TOKEN"], "in_wcm": [], "in_env_only": [], "missing": []}
    assert m.couche_du_credential(diag, "LAFORGE_ADMIN_TOKEN", True) == "coffre"


def test_le_fichier_env_ne_se_confond_pas_avec_le_coffre():
    m = _campagne()
    diag = {"in_vault": [], "in_wcm": [], "in_env_only": ["LAFORGE_ADMIN_TOKEN"], "missing": []}
    assert m.couche_du_credential(diag, "LAFORGE_ADMIN_TOKEN", True) == "fichier .env"


def test_un_jeton_obtenu_SANS_couche_connue_vient_de_l_environnement():
    m = _campagne()
    diag = {"in_vault": [], "in_wcm": [], "in_env_only": [], "missing": ["LAFORGE_ADMIN_TOKEN"]}
    assert m.couche_du_credential(diag, "LAFORGE_ADMIN_TOKEN", True) == "environnement", (
        "le cas CI reste indiscernable : un jeton servi par os.environ doit se "
        "distinguer du coffre, sinon on ne saura jamais lequel le serveur refuse"
    )


def test_aucun_jeton_ne_se_declare_pas_comme_une_source():
    m = _campagne()
    diag = {"in_vault": [], "in_wcm": [], "in_env_only": [], "missing": ["LAFORGE_ADMIN_TOKEN"]}
    assert m.couche_du_credential(diag, "LAFORGE_ADMIN_TOKEN", False) == "aucune"


# ---------------------------------------------------------------------------
# CLIQUET : STABLE ≠ INTERMITTENT — la dimension TEMPS du verdict
#
# MESURE 2026-09-16, cinq passes de la campagne, CINQ compositions du verdict :
#   20 routes (faux positif de ma sonde) · /maison+/ui-auto-services-status ·
#   /maison+/anatomy · /maison+/forge-feed+/ui-auto-services-status · /anatomy
# `/ui/auto/services-status` rend tantot 17 caracteres, tantot 127, tantot un
# contenu normal. Un verdict d'UNE passe ne caracterise donc pas ces defauts —
# « un fait TEMPOREL se refute par un LOG, JAMAIS par une lecture a l'instant t ».
#
# ⚠️⚠️ LE PIEGE A NE PAS TENDRE, ET C'EST TOUT L'ENJEU DU CLIQUET : se servir de
# N passes pour faire DISPARAITRE un defaut (« il ne s'est pas reproduit, donc
# vert »). Ce serait echanger un faux rouge contre un faux vert, exactement la
# reserve du 2026-09-12. INTERMITTENT est un etat A PART, NON livrable, qui
# porte son TAUX (k sur n). Le vert reste reserve a ce qui n'a rien a signaler.
#
# ⚠️ ASYMETRIE DE L'ECHANTILLONNAGE, a dire et non a cacher : on ne re-teste que
# ce qui a DEJA echoue. On mesure donc la PERSISTANCE d'un defaut, jamais sa
# frequence d'apparition — une route saine a la premiere passe n'est pas
# re-visitee, et son intermittence eventuelle reste invisible.
# ---------------------------------------------------------------------------


def test_un_defaut_present_a_toutes_les_passes_est_STABLE():
    m = _campagne()
    assert m.classer_persistance(3, 3) == "STABLE"


def test_un_defaut_present_a_certaines_passes_est_INTERMITTENT():
    m = _campagne()
    assert m.classer_persistance(1, 3) == "INTERMITTENT"
    assert m.classer_persistance(2, 3) == "INTERMITTENT"


def test_un_defaut_jamais_reproduit_le_DIT_au_lieu_de_disparaitre():
    m = _campagne()
    assert m.classer_persistance(0, 3) == "NON_REPRODUIT", (
        "un defaut qui ne se reproduit pas doit se NOMMER : le faire taire "
        "reviendrait a se servir des passes pour fabriquer du vert"
    )


def test_sans_passe_supplementaire_la_persistance_n_est_pas_MESUREE():
    m = _campagne()
    assert m.classer_persistance(1, 0) == "NON_MESURE", (
        "zero passe rendrait un verdict de persistance jamais mesure — "
        "UNKNOWN n'est ni STABLE ni INTERMITTENT"
    )


def test_INTERMITTENT_n_est_PAS_livrable_et_a_son_propre_code():
    m = _campagne()
    d = m.decider_verdict(0, (), False, degrade=(), intermittent=("/anatomy",))
    assert d["verdict"] == "INTERMITTENT"
    assert d["rc"] == 5, "un code de retour distinct, sinon ci_local ne peut pas le traiter a part"
    assert d["livrable"] is False, (
        "un defaut intermittent redevient livrable : c'est le faux vert que le "
        "cliquet doit empecher"
    )


def test_un_defaut_STABLE_prime_sur_un_INTERMITTENT():
    m = _campagne()
    d = m.decider_verdict(0, (), False, degrade=("/x",), intermittent=("/y",))
    assert d["verdict"] == "DEGRADE" and d["rc"] == 4


def test_l_authentification_prime_encore_sur_l_intermittence():
    m = _campagne()
    d = m.decider_verdict(0, ("/a",), False, degrade=(), intermittent=("/y",))
    assert d["verdict"] == "AUTH_FAILURE", (
        "une route non jugee ne se compare pas a une route vue par intermittence"
    )


def test_le_vert_reste_atteignable_quand_il_n_y_a_rien_a_signaler():
    m = _campagne()
    d = m.decider_verdict(0, (), False, degrade=(), intermittent=())
    assert d["verdict"] == "CONFORME" and d["rc"] == 0 and d["livrable"] is True


def test_le_gate_NOMME_le_taux_et_pas_seulement_l_etat():
    m = _campagne()
    d = m.decider_verdict(0, (), False, degrade=(), intermittent=("/anatomy (2/3)",))
    assert "2/3" in d["gate"], (
        "sans son taux, INTERMITTENT ne se distingue pas d'un aveu d'ignorance"
    )


def test_ci_local_traite_le_code_intermittent_a_part():
    import pathlib
    src = pathlib.Path(RACINE / "tools" / "ci_local.py").read_text(encoding="utf-8")
    assert "rc == 5" in src or "rc==5" in src, (
        "ci_local ne connait pas le code INTERMITTENT : il retomberait dans la "
        "branche par defaut, donc dans un traitement qui n'est pas le sien"
    )


# ---------------------------------------------------------------------------
# LE TROU DU CLIQUET PRECEDENT — un CONFORME d'UNE SEULE passe (2026-09-16)
#
# MESURE, job_141decba05a9 : verdict CONFORME, `occurrences: {}`, zero page
# portant le moindre signal. Vert HONNETE — le cliquet n'avait requalifie
# personne, il n'avait meme pas ete sollicite. Mais c'etait la SIXIEME
# composition en six passes, et la passe precedente rendait `/anatomy` en
# defaut sans qu'une ligne du web_hub ait bouge.
#
# 💥 LA CONSEQUENCE QUE JE N'AVAIS PAS TIREE, alors que je l'avais ECRITE dans
# la docstring : on ne rejoue que les routes DEJA en defaut. Si la premiere
# passe est propre, rien n'est revisite — et le gate rend CONFORME sur une
# interface qui casse une fois sur deux. C'est un FAUX CALME, precisement ce
# que le chantier doit supprimer. « Ne jamais confondre l'existence d'un
# mecanisme avec son effet reel » vaut aussi pour le mecanisme qu'on vient
# d'ecrire.
#
# Remede : une route qui a DEJA ete en defaut est rejouee meme quand elle
# parait saine. Le registre est la forme ECRITE du log que reclame un fait
# temporel — sans lui, chaque passe repart sans memoire.
# ---------------------------------------------------------------------------


def test_une_route_DEJA_vue_en_defaut_est_rejouee_meme_si_elle_parait_saine():
    m = _campagne()
    a_rejouer = m.routes_a_rejouer(en_defaut=(), registre={"/anatomy": 2})
    assert "/anatomy" in a_rejouer, (
        "une route connue pour ses defauts n'est pas revisitee quand la "
        "premiere passe est propre : le gate rendra CONFORME sur une interface "
        "qui casse une fois sur deux"
    )


def test_les_routes_en_defaut_du_jour_restent_rejouees():
    m = _campagne()
    a_rejouer = m.routes_a_rejouer(en_defaut=("/maison",), registre={})
    assert "/maison" in a_rejouer


def test_une_route_jamais_vue_en_defaut_n_est_PAS_rejouee():
    m = _campagne()
    a_rejouer = m.routes_a_rejouer(en_defaut=(), registre={})
    assert a_rejouer == [], (
        "rejouer les 20 routes triplerait la campagne pour rien : le registre "
        "cible ce qui a DEJA montre un defaut"
    )


def test_le_registre_ne_condamne_personne_par_sa_seule_presence():
    m = _campagne()
    # inscrite au registre, mais saine a chacune des 3 passes
    assert m.classer_persistance(0, 3) == "NON_REPRODUIT", (
        "une route inscrite qui passe toutes ses passes serait declaree en "
        "defaut sur son seul passe : le registre serait une condamnation"
    )


def test_le_registre_retient_ce_qui_a_ete_en_defaut():
    m = _campagne()
    maj = m.maj_registre({"/a": 1}, ("/a", "/b"))
    assert maj["/a"] == 2 and maj["/b"] == 1, (
        "le registre n'accumule pas : il perdrait la memoire des routes "
        "instables d'une passe a l'autre"
    )


def test_un_vert_DIT_sur_combien_de_passes_il_porte():
    m = _campagne()
    d = m.decider_verdict(0, (), False, degrade=(), intermittent=(), passes=1)
    assert "1 passe" in d["gate"], (
        "un CONFORME qui tait son nombre de passes se lit comme une preuve de "
        "stabilite alors qu'il n'est qu'un instantane"
    )


def test_la_campagne_RE_TESTE_les_routes_en_defaut():
    import inspect
    m = _campagne()
    source = inspect.getsource(m)
    assert "classer_persistance(" in source, (
        "la fonction est testee mais la campagne ne la traverse pas : le "
        "verdict resterait celui d'une passe unique"
    )
    assert '"passes"' in source and '"occurrences"' in source, (
        "le rapport ne porte ni le nombre de passes ni le compte des "
        "occurrences : le taux serait invérifiable"
    )


def test_la_campagne_NOMME_la_couche_au_lieu_de_l_etiquette_env():
    import inspect
    m = _campagne()
    assert "couche_du_credential(" in inspect.getsource(m), (
        "la campagne imprime toujours une etiquette qui ne distingue pas les "
        "quatre couches : le diagnostic CI restera une supposition"
    )
