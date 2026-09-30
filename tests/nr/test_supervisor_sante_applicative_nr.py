"""NR -- contrat de sante du superviseur : TRANSPORT_UP n'est PAS APPLICATION_UP.

DEFAUT MESURE le 2026-09-11, en flagrant delit sur la machine de l'owner :

    NokidoWebHub  pid 18644, ne a 15:13:49
    TCP :7400     PASS en 0.00 s
    GET /health   TimeoutError apres 6.05 s
    GET / /hub /auth/login  TimeoutError

Le service est reste dans cet etat plus de CINQ HEURES sans que rien ne le
remarque. Les trois detecteurs du superviseur sont aveugles a ce mode de panne :

  * exit du process   -- le process ne meurt pas, il est FIGE ;
  * heartbeat stale   -- NokidoWebHub n'en declare aucun (state.heartbeat = null) ;
  * port ouvert       -- `isPortOpen()` est un simple TCP connect, et il conclut
                         `state.status = "running"` (supervisor.ts L991-1009).

Le troisieme est le pire : il ne se contente pas d'etre muet, il CONFIRME la
sante d'un mort. Et `objectif = "emis<600 | cpu>0.05 | listen"` ne rattrape rien :
le champ n'est lu NULLE PART dans proxy_deno/core (0 occurrence) -- une
declaration que personne n'evalue, pas un contrat.

CE QUE CE NR FIGE. Quatre niveaux de vitalite qui ne sont jamais synonymes :

    PROCESS_ALIVE  ->  TRANSPORT_UP  ->  APPLICATION_UP  ->  FUNCTIONAL

Un port ouvert ne prouve que le deuxieme. Quand un service porte un contrat de
sante applicatif, c'est LUI qui decide de `running` -- et l'ABSENCE de contrat
donne un etat INCONNU dit comme tel, jamais un `running` par defaut : ranger
l'inconnu du cote sain est precisement ce que la constitution semantique interdit.

PORTEE. La regle vise le SUPERVISEUR, pas un service. Le defaut est de CLASSE :
32 services declarent un port sans heartbeat, et `:8080` presente aujourd'hui le
meme symptome (LISTENING + timeout) -- un second temoin, independant, qui
interdit d'ecrire un garde taille pour le seul `NokidoWebHub`.

INSTRUMENT ET SA LIMITE. Ces tests lisent le SOURCE TypeScript : `deno` rend
`Acces refuse` au compte sandbox (mesure du 2026-09-11), et il n'existe aucun
test .ts dans proxy_deno. C'est le filet que `ci_local` emploie deja ailleurs
(<< Hermetique : lit la source .ts, ne lance pas deno >>), avec sa faiblesse
assumee : il voit du TEXTE, pas un programme. D'ou `_code()`, qui DEPOUILLE les
commentaires avant toute recherche -- une regle citee dans un commentaire n'est
pas une regle appliquee, faute payee cinq fois en trois jours.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SUP = ROOT / "proxy_deno" / "core" / "supervisor.ts"

# Noms acceptes pour la sonde applicative et pour l'etat inconnu. Le NR fixe le
# VOCABULAIRE parce qu'un contrat sans nom stable ne se verifie pas ; il laisse
# le choix de la forme entre plusieurs orthographes raisonnables.
SONDE = ("appHealthy", "isAppHealthy", "appRepond", "checkAppHealth", "probeHealth")
INCONNU = ("HEALTH_UNKNOWN", "health_unknown", "SANTE_INCONNUE")
CONTRAT = ("health_contract", "healthContract", "health_path", "healthPath")

# Les SEULES fonctions autorisees a appeler la sonde applicative. Liste FERMEE :
# c'est ainsi que << ne pas ajouter un second watchdog >> devient verifiable au
# lieu de rester une intention. Un mecanisme neuf qui voudrait surveiller la
# sante devra passer par une de ces trois portes.
APPELANTS_AUTORISES = ("startService", "waitForHealthy", "healthSurfaceLoop")

# La boucle periodique qui DOIT porter la supervision. Elle existe deja (tick
# 20 s), elle sonde deja un /health et publie deja la surface de sante : le
# travail est de la GENERALISER, pas d'en ajouter une seconde a cote.
BOUCLE = "healthSurfaceLoop"


def _corps(code: str, nom: str) -> str:
    """Corps EXACT d'une fonction TS, par equilibrage des accolades.

    Remplace la fenetre de N caracteres qui m'a rendu un faux vert le
    2026-09-11 : bornee a 700 caracteres depuis `waitForPort`, elle debordait
    sur la fonction ajoutee juste apres, dont le `fetch` faisait passer pour
    corrige un `waitForPort` inchange. Une preuve << dans les parages de >>
    n'est pas une preuve DANS.

    LIMITE ASSUMEE : l'equilibrage compte les accolades du texte. Les
    commentaires sont deja retires par `_sans_commentaires`, et les templates
    `${...}` sont equilibres ; une accolade ORPHELINE dans une chaine
    litterale ferait deriver le compte. C'est le meme filet que le reste du
    fichier : il lit du TEXTE, pas un programme.
    """
    m = re.search(r"\bfunction\s+" + re.escape(nom) + r"\b", code)
    if not m:
        pytest.fail(
            "fonction %s introuvable dans %s -- le NR ne peut pas juger ce "
            "qu'il ne trouve pas : ILLISIBLE, ni vrai ni faux" % (nom, SUP.name))
    debut = code.index("{", m.end())
    profondeur = 0
    for j in range(debut, len(code)):
        if code[j] == "{":
            profondeur += 1
        elif code[j] == "}":
            profondeur -= 1
            if profondeur == 0:
                return code[debut:j + 1]
    pytest.fail("accolades non refermees pour %s -- corps ILLISIBLE" % nom)


def _ts() -> str:
    return _sans_commentaires(SUP.read_text(encoding="utf-8", errors="replace"))


def test_l_extracteur_de_corps_mord_et_ne_deborde_pas():
    """Morsure de `_corps`. Une sonde non prouvee rassure d'autant plus qu'elle
    voit moins -- c'est un garde branche sur un signal que personne n'emet."""
    faux = (
        "async function alpha() {\n"
        "  if (x) { return 1; }\n"
        "}\n"
        "async function beta() {\n"
        "  await appHealthy(1);\n"
        "}\n"
    )
    a = _corps(faux, "alpha")
    assert "return 1" in a
    assert "appHealthy" not in a, (
        "l'extracteur DEBORDE sur la fonction suivante : c'est exactement le "
        "defaut qui a rendu un faux vert le 2026-09-11")
    assert "appHealthy" in _corps(faux, "beta")


# --- CAS A : la boucle periodique lit le contrat DECLARE -------------------
def test_A_la_boucle_periodique_lit_le_contrat_declare_de_chaque_service():
    """Sans cela, la sante applicative n'est mesuree QU'AU DEMARRAGE.

    Mesure du 2026-09-11 : apres le correctif de lifecycle, le journal portait
    `APPLICATION_DOWN = 0` alors que le portail etait mort a l'usage. Un
    capteur qui ne regarde qu'une fois ne dit rien du reste de la vie du
    service -- SIGNAL != PREUVE DE VIE dans la duree.
    """
    corps = _corps(_ts(), BOUCLE)
    assert any(c in corps for c in CONTRAT), (
        "%s ne lit AUCUN contrat de sante declare (%s). Elle sonde une URL "
        "ecrite en dur : tout service hors de ce nom reste juge sur son port."
        % (BOUCLE, " / ".join(CONTRAT)))
    assert any(s + "(" in corps for s in SONDE), (
        "%s ne fait AUCUN appel a la sonde applicative (%s). Declarer la sonde "
        "ne la branche pas : c'est l'APPEL qui mesure." % (BOUCLE, " / ".join(SONDE)))


# --- CAS B : la degradation applicative est CONSTATEE ----------------------
def test_B_la_boucle_peut_conclure_degraded_sur_une_application_morte():
    """`running` et `stopped` etaient les deux seules issues, et les deux
    mentent sur un service dont le port ecoute pendant que l'app est figee.
    Le superviseur CONSTATE ; il n'instruit pas et ne tue pas ici."""
    corps = _corps(_ts(), BOUCLE)
    # PIEGE PAYE EN ECRIVANT CE TEST : chercher le MOT `degraded` le rendait
    # vert d'emblee -- la boucle porte deja `degradedEssential`,
    # `_lastDegradedKey` et `_degradedTicks`, qui parlent d'essentiels non
    # demarres et n'ont AUCUN rapport avec la sante applicative. Une MENTION
    # n'est pas une STRUCTURE (5 faux positifs de mes propres gardes le
    # 2026-09-10). Ce qu'il faut exiger, c'est l'AFFECTATION de l'etat.
    assert re.search(r'status\s*=\s*"degraded"', corps), (
        "%s ne POSE jamais l'etat `degraded` sur un service : une application "
        "figee derriere un port ouvert y reste `running`, ce qui est le "
        "mensonge d'origine (5 h de panne invisible le 2026-09-11). "
        "Le mot `degraded` seul ne suffit pas -- la boucle en porte deja trois "
        "occurrences qui parlent d'autre chose." % BOUCLE)


# --- CAS C : l'absence de contrat n'est PAS une bonne sante ----------------
def test_C_l_absence_de_contrat_donne_INCONNU_jamais_sain_ni_mort():
    """Corollaire de la constitution semantique : on classe par liste BLANCHE.
    Les 31 services portes SANS contrat ne doivent basculer ni d'un cote ni de
    l'autre -- ni `degraded` fabrique, ni `running` par defaut."""
    corps = _corps(_ts(), BOUCLE)
    assert any(u in corps for u in INCONNU), (
        "%s ne nomme AUCUN etat inconnu (%s). Sans lui, un service sans "
        "contrat tombe forcement du cote sain ou du cote mort : dans un cas on "
        "fabrique 31 pannes fictives, dans l'autre on rend le faux calme "
        "d'origine." % (BOUCLE, " / ".join(INCONNU)))


def test_la_NEUTRALISATION_est_explicite_datee_et_motivee():
    """CLIQUET -- le contrat est SUSPENDU, et il ne doit pas l'etre en silence.

    Le 2026-09-12, le bloc de supervision periodique a fige healthSurfaceLoop
    la premiere fois qu'il a sonde un porteur (start de NokidoWebHub a
    00:07:43 ; ts et mtime de health.json figes sur 6 releves espaces de 15 s,
    tick attendu 20 s, superviseur vivant et stderr vide). Il a ete neutralise
    en rendant la liste des porteurs vide.

    PROBLEME : les cas A a D ci-dessus restent VERTS sur ce code neutralise --
    ils verifient que le contrat est ECRIT, pas qu'il s'EXECUTE. Un NR vert sur
    du code inerte est precisement le faux calme que tout ce fichier combat.

    Ce test tient les deux bouts. Tant que la neutralisation est la, il exige
    qu'elle soit explicite, datee et motivee -- pas un `false` silencieux que
    personne ne retrouvera. Et le jour ou le bloc sera reactive, il passera au
    ROUGE : impossible de rendre la supervision active sans rouvrir ce fichier
    et re-instruire le contrat.
    """
    corps = _corps(_ts(), BOUCLE)
    neutralise = "filter(() => false)" in corps
    if not neutralise:
        pytest.fail(
            "la supervision periodique semble REACTIVEE. Ce n'est pas un "
            "echec : c'est le cliquet qui demande de rouvrir le contrat.\n"
            "  Avant de retirer ce test, etablir la CAUSE du gel du "
            "2026-09-12 (piste : `appHealthy` fait `await r.body?.cancel()` "
            "APRES la reponse du fetch, donc hors de la portee de son "
            "AbortController -- une attente qui n'est plus bornee), puis "
            "prouver par MESURE que health.json continue de ticker a 20 s "
            "avec un porteur reellement sonde.")
    # La NEUTRALISATION est du CODE : elle se verifie sur le source depouille
    # (ci-dessus). Sa JUSTIFICATION est de la DOCUMENTATION : elle se verifie
    # sur le source BRUT, commentaires compris. Chercher la date dans le
    # depouille etait ma propre confusion -- et c'est exactement la distinction
    # que ce fichier defend partout ailleurs.
    brut = SUP.read_text(encoding="utf-8", errors="replace")
    assert "2026-09-12" in brut, (
        "neutralisation SANS DATE : dans trois mois, personne ne saura si "
        "c'est un choix ou un oubli")
    assert "health.json" in brut and "fige" in brut, (
        "neutralisation sans la MESURE qui l'a motivee : une decision qu'on ne "
        "peut pas re-instruire est une decision perdue")


# --- CAS D : aucun second watchdog ----------------------------------------
def test_D_la_sonde_applicative_n_a_que_des_appelants_autorises():
    """Ordre owner : reutiliser la boucle existante, ne pas en ajouter une.
    Une intention ne se verifie pas ; une liste fermee d'appelants, si."""
    code = _ts()
    nom_sonde = next((s for s in SONDE if s + "(" in code), None)
    assert nom_sonde, "aucune sonde applicative (%s) dans %s" % (" / ".join(SONDE), SUP.name)

    corps_autorises = "".join(_corps(code, f) for f in APPELANTS_AUTORISES)
    total = len(re.findall(r"\b" + re.escape(nom_sonde) + r"\s*\(", code))
    # La definition de la sonde compte pour une occurrence : on la retire.
    definis = len(re.findall(
        r"\bfunction\s+" + re.escape(nom_sonde) + r"\s*\(", code))
    dedans = len(re.findall(r"\b" + re.escape(nom_sonde) + r"\s*\(", corps_autorises))
    assert total - definis == dedans, (
        "%d appel(s) a `%s` HORS des appelants autorises (%s). Un surveillant "
        "de plus n'ajoute pas de la surete : il ajoute une seconde autorite "
        "sur le meme etat, et deux autorites qui se contredisent valent moins "
        "qu'une." % (total - definis - dedans, nom_sonde,
                     ", ".join(APPELANTS_AUTORISES)))


def _sans_commentaires(ts: str) -> str:
    """Retire les commentaires TypeScript (// ... et /* ... */).

    Sans cela, tout ce NR se laisserait berner par un commentaire qui NOMME la
    regle sans que le code l'applique -- et un commentaire est precisement ce
    qu'on ecrit quand on a remis la correction a plus tard.
    """
    ts = re.sub(r"/\*.*?\*/", " ", ts, flags=re.S)
    return re.sub(r"(?m)//.*$", " ", ts)


@pytest.fixture(scope="module")
def src() -> str:
    assert SUP.exists(), (
        "superviseur introuvable : sans lui, chacun des tests suivants passerait "
        "sur du vide et le NR rassurerait sans rien mesurer")
    return SUP.read_text(encoding="utf-8", errors="replace")


@pytest.fixture(scope="module")
def code(src: str) -> str:
    return _sans_commentaires(src)


def _zone_start_service(code: str) -> str:
    """Corps de `startService`, la ou se decide l'adoption d'un port deja ouvert."""
    i = code.find("function startService")
    assert i > 0, "startService introuvable : le contrat ne peut pas etre situe"
    suite = code.find("\nasync function ", i + 10)
    return code[i:suite if suite > 0 else i + 6000]


# --------------------------------------------------------------------------
# 0. L'INSTRUMENT AVANT LA MESURE
# --------------------------------------------------------------------------

def test_l_instrument_lit_un_superviseur_reel(src):
    """Un fichier vide ou tronque rendrait tous les tests suivants verts."""
    assert len(src) > 100_000, (
        "supervisor.ts fait %d caracteres : trop court pour etre le vrai fichier"
        % len(src))
    assert "function startService" in src


def test_le_depouillage_des_commentaires_mord(src):
    """Sinon la regle pourrait etre satisfaite par un simple commentaire.

    Prouve sur un temoin fabrique ET sur le fichier reel : le superviseur porte
    de longs commentaires, les retirer doit le RACCOURCIR de facon mesurable.
    """
    temoin = "const a = 1; // HEALTH_UNKNOWN\n/* appHealthy */ const b = 2;"
    net = _sans_commentaires(temoin)
    assert "HEALTH_UNKNOWN" not in net and "appHealthy" not in net
    assert "const a = 1;" in net and "const b = 2;" in net
    assert len(_sans_commentaires(src)) < len(src) * 0.95, (
        "le depouillage n'a presque rien retire : l'instrument est inerte")


# --------------------------------------------------------------------------
# 1. LE COEUR : un port ouvert ne vaut pas un service vivant
# --------------------------------------------------------------------------

def test_un_port_ouvert_ne_suffit_plus_a_declarer_running(code):
    """LE defaut du 2026-09-11, celui qui a laisse un mort passer pour vivant.

    supervisor.ts L991-1009 : `isPortOpen(def.port)` puis, sans rien d'autre,
    `state.status = "running"; return;`. Un zombie qui tient son socket est
    adopte comme sain.
    """
    zone = _zone_start_service(code)
    i = zone.find("isPortOpen")
    assert i > 0, "startService ne consulte plus le port : contrat a re-instruire"
    apres = zone[i:i + 1800]
    if 'status = "running"' not in apres:
        return  # la branche d'adoption a disparu : le defaut est impossible
    avant_running = apres[:apres.find('status = "running"')]
    assert any(n in avant_running for n in SONDE), (
        "`status = \"running\"` est ecrit apres un simple `isPortOpen`, sans "
        "qu'aucune sonde applicative (%s) ne soit consultee.\n"
        "  -> TRANSPORT_UP est pris pour APPLICATION_UP : c'est exactement ce "
        "qui a laisse :7400 mort et declare vivant pendant cinq heures."
        % ", ".join(SONDE))


def test_une_sonde_de_sante_applicative_existe_et_parle_http(code):
    """TCP ne prouve rien de l'application : il faut une requete APPLICATIVE."""
    presentes = [n for n in SONDE if n in code]
    assert presentes, (
        "aucune sonde de sante applicative (%s) dans le superviseur : il ne "
        "dispose que de `isPortOpen`, qui est un connect TCP" % ", ".join(SONDE))
    i = code.find(presentes[0])
    assert "fetch" in code[i:i + 1500], (
        "la sonde %s ne fait aucune requete HTTP : une sonde qui ne parle pas "
        "a l'application ne mesure pas l'application" % presentes[0])


def test_un_service_sans_contrat_est_INCONNU_jamais_running(code):
    """UNKNOWN ne se range JAMAIS du cote sain (constitution semantique).

    32 services declarent un port sans heartbeat. Leur absence de contrat doit
    produire un etat DIT, pas un `running` par defaut qui les ferait tous
    passer pour sains sans qu'on l'ait jamais decide.
    """
    assert any(n in code for n in CONTRAT), (
        "aucune notion de contrat de sante (%s) : impossible de distinguer "
        "<< ce service n'a pas de sonde >> de << ce service va bien >>"
        % ", ".join(CONTRAT))
    assert any(n in code for n in INCONNU), (
        "aucun etat inconnu nomme (%s) : sans lui, un service sans contrat "
        "retombe silencieusement dans `running`" % ", ".join(INCONNU))


# --------------------------------------------------------------------------
# 2. RESTART : le compteur ne doit pas gouverner la verification
# --------------------------------------------------------------------------

def test_le_detenteur_du_port_est_verifie_meme_au_premier_passage(code):
    """`restartCount > 0` ne doit plus etre le seul garde de l'auto-guerison.

    supervisor.ts L993 : `if (holder && state.restartCount > 0)`. Or ce compteur
    repart a ZERO quand le superviseur lui-meme redemarre -- mesure du
    2026-09-11 : superviseur ne a 10:05:19, web_hub zombie depuis 15:13:49,
    jamais repris. Un superviseur qui vient de demarrer ADOPTE donc un mort.
    """
    zone = _zone_start_service(code)
    m = re.search(r"restartCount\s*>\s*0", zone)
    if m is None:
        return  # la garde a ete retiree ou remplacee : propriete obtenue
    contexte = zone[max(0, m.start() - 400):m.start() + 400]
    assert any(n in contexte for n in SONDE), (
        "l'auto-guerison (kill du detenteur du port) reste gardee par le SEUL "
        "`restartCount > 0`, sans consulter la sante applicative.\n"
        "  -> au premier passage, restartCount vaut 0 et un service "
        "applicativement mort est adopte comme `running`.")


def test_apres_le_spawn_on_attend_la_sante_pas_seulement_le_port(code):
    """`waitForPort` est un connect TCP en boucle : il ne prouve pas l'application.

    Un `spawn reussi` n'est pas un `restart reussi`. La condition de succes doit
    etre APPLICATION_UP.
    """
    i = code.find("function waitForPort")
    assert i > 0, "waitForPort introuvable"

    # FAUX VERT PAYE LE 2026-09-11, le second de la session : la version
    # precedente lisait `code[i:i+700]`, une fenetre FIXE qui debordait sur les
    # fonctions suivantes. Il a suffi d'ajouter `appHealthy` juste apres
    # waitForPort pour que son `fetch` rende le test vert -- sur un
    # `waitForPort` rigoureusement inchange. On borne desormais au CORPS.
    fin = code.find("\n}", i)
    assert fin > i, "corps de waitForPort non delimitable"
    corps = code[i:fin]
    assert "isPortOpen" in corps, "ce n'est pas le corps attendu"

    # La propriete n'est PAS que waitForPort change : c'est qu'une attente de
    # SANTE existe **et soit APPELEE**. Un mecanisme present mais non cable est
    # une dette de cablage, jamais une securite -- et il se relit comme un
    # garde tout en ne gardant rien.
    definitions = len(re.findall(r"function\s+waitForHealthy", code))
    appels = len(re.findall(r"waitForHealthy\s*\(", code)) - definitions
    assert definitions >= 1, (
        "aucune attente de sante applicative apres le spawn : `waitForPort` est "
        "un connect TCP en boucle, donc un `spawn reussi` serait pris pour un "
        "`restart reussi` des la reapparition du socket")
    assert appels >= 1, (
        "`waitForHealthy` est DEFINI mais jamais APPELE (%d definition(s), "
        "%d appel(s)) : le superviseur conclut toujours ses demarrages sur le "
        "seul port." % (definitions, appels))


# --------------------------------------------------------------------------
# 3. GENERALITE : un garde taille pour un seul service n'est pas un contrat
# --------------------------------------------------------------------------

def test_la_regle_de_sante_n_est_pas_ecrite_en_dur_pour_le_webhub(code):
    """`:8080` presente le MEME symptome : la regle doit valoir pour la classe.

    Ce test est vert aujourd'hui et doit le RESTER apres la correction : il
    interdit de resoudre le cas du jour par un `if (port === 7400)`.
    """
    for litteral in ("7400", "NokidoWebHub"):
        for m in re.finditer(re.escape(litteral), code):
            fenetre = code[max(0, m.start() - 200):m.start() + 200]
            assert not any(n in fenetre for n in SONDE + INCONNU + CONTRAT), (
                "la logique de sante cite le litteral %r : un garde ecrit pour "
                "un seul service laisse les 31 autres dans l'angle mort"
                % litteral)
