"""Non-regression de la DEFINITION CANONIQUE du temps mort (`app/forge_temps_mort.py`).

CONTEXTE MESURE (2026-09-03) : trois centres decidaient independamment de ce qu'est un
organe mort, et 29 services sur 36 recevaient des seuils differents selon le juge --
jusqu'a un facteur 108 sur `NokidoHebbian` (600 s cote superviseur contre 64 800 s cote
sentinelle). C'est la cause chiffree de ses 765 relances.

CE QUE CES TESTS PROTEGENT EN PRIORITE : qu'un cycle INCONNU ne durcisse personne. La
premiere version de ce module rendait le plancher faute de cycle -- raisonnement juste
(« le plus strict ne cache pas une mort »), consequence desastreuse : 24 services sur
36 n'ont aucun cycle connu, ils seraient passes de 600 s a 90 s d'un coup, le hub
lui-meme inclus. Armer un durcissement sur une base non mesuree est la faute que ce
fichier rend impossible a re-commettre en silence.
"""
from __future__ import annotations

import sys
from pathlib import Path

_APP = str(Path(__file__).resolve().parents[2] / "app")
if _APP not in sys.path:
    sys.path.insert(0, _APP)

import forge_temps_mort as TM  # noqa: E402

_TOML = """
[[service]]
name = "OrganeDeclare"
heartbeat = "sandbox/a.heartbeat"
cycle_s = 21600

[[service]]
name = "OrganeDerive"
heartbeat = "sandbox/b.heartbeat"
args = ["app/x.py", "--daemon", "--interval", "300"]

[[service]]
name = "OrganeInconnu"
heartbeat = "sandbox/c.heartbeat"
args = ["app/y.py", "--daemon"]

[[service]]
name = "OrganeSansPouls"
args = ["app/z.py"]

[[service]]
name = "OrganeEteint"
heartbeat = "sandbox/d.heartbeat"
cycle_s = 60
disabled = true
"""


def test_la_formule_est_unique_et_bornee():
    assert TM.seuil_mort(21600) == 3.0 * 21600
    assert TM.seuil_mort(300) == 900.0
    # Le PLANCHER borne les cycles COURTS : une mort ne doit pas devenir detectable
    # plus lentement que le temps de reaction le plus court du corps.
    assert TM.seuil_mort(1) == TM.PLANCHER_S
    assert TM.seuil_mort(0) == TM.PLANCHER_S


def test_un_cycle_INCONNU_ne_durcit_personne():
    """LE test de ce fichier. Sans seuil courant offert, on retombe sur le plancher
    -- bon defaut pour un appelant sans contexte. AVEC un seuil courant, on le rend
    INCHANGE : la migration ne touche pas ce qu'elle ne connait pas."""
    assert TM.seuil_mort(None) == TM.PLANCHER_S
    assert TM.seuil_mort(None, seuil_actuel=600.0) == 600.0
    assert TM.seuil_mort(None, seuil_actuel=3600.0) == 3600.0
    # Une valeur illisible se comporte comme une valeur absente, jamais comme zero.
    assert TM.seuil_mort("pas un nombre", seuil_actuel=600.0) == 600.0
    assert TM.seuil_mort(-5, seuil_actuel=600.0) == 600.0


def test_les_sources_sont_nommees_et_jamais_fondues():
    """`declare`, `herite`, `derive`, `inconnu` : quatre provenances distinctes. Les
    confondre ferait passer une deduction pour une declaration."""
    c = TM.cycles(_TOML)
    assert c["OrganeDeclare"] == (21600.0, "declare")
    assert c["OrganeDerive"] == (300.0, "derive")
    assert c["OrganeInconnu"] == (None, "inconnu")
    # Un service sans heartbeat declare n'est pas juge ici : sa mort est silencieuse
    # PAR CONCEPTION, ce que `daemon_heartbeats` signale ailleurs.
    assert "OrganeSansPouls" not in c
    # Un service eteint volontairement ne doit pas battre : l'exiger fabriquerait des
    # organes morts (faux positif deja paye le 2026-07-22).
    assert "OrganeEteint" not in c


def test_le_declare_prime_sur_le_derive():
    """Un argument de lancement dit comment on LANCE un organe, pas ce qu'il EST. Le
    registre fait autorite des qu'il se prononce."""
    toml = """
[[service]]
name = "X"
heartbeat = "sandbox/x.heartbeat"
cycle_s = 7200
args = ["app/x.py", "--interval", "60"]
"""
    assert TM.cycles(toml)["X"] == (7200.0, "declare")


def test_le_rapport_publie_le_denominateur_de_la_migration():
    """Sans ce compte, « tout va bien » ne se distingue pas de « rien n'est declare »."""
    r = TM.rapport(_TOML)
    assert r == {"declare": 1, "derive": 1, "inconnu": 1}
    assert sum(r.values()) == len(TM.cycles(_TOML))


def test_les_seuils_respectent_les_seuils_actuels_pour_les_inconnus():
    """Bascule complete sur un registre synthetique : seul ce qui est connu bouge."""
    actuels = {"OrganeDeclare": 600.0, "OrganeDerive": 3600.0, "OrganeInconnu": 600.0}
    s = TM.seuils(_TOML, seuils_actuels=actuels)
    assert s["OrganeDeclare"][0] == 64800.0        # etait 600 : fin des relances
    assert s["OrganeDerive"][0] == 900.0           # etait 3600 : devient plus strict
    assert s["OrganeInconnu"][0] == 600.0          # INCHANGE
    assert s["OrganeInconnu"][2] == "inconnu"


def test_le_contrat_lie_heartbeat_max_s_a_cycle_s_dans_LES_DEUX_SENS():
    """`heartbeat_max_s` est une valeur DERIVEE materialisee pour que le TypeScript
    la lise au lieu de la recalculer. Une derivee qu'on peut modifier seule n'est
    plus une derivee : c'est une seconde configuration, et on retombe sur le defaut
    que tout ce module corrige."""
    ok = """
[[service]]
name = "Bon"
heartbeat = "sandbox/a.heartbeat"
cycle_s = 21600
heartbeat_max_s = 64800
"""
    assert TM.incoherences(ok) == []

    sans_derivee = """
[[service]]
name = "Manque"
heartbeat = "sandbox/a.heartbeat"
cycle_s = 21600
"""
    assert len(TM.incoherences(sans_derivee)) == 1

    orpheline = """
[[service]]
name = "Orpheline"
heartbeat = "sandbox/a.heartbeat"
heartbeat_max_s = 90
"""
    faute = TM.incoherences(orpheline)
    assert len(faute) == 1 and "seconde configuration" in faute[0][1]

    divergente = """
[[service]]
name = "Divergente"
heartbeat = "sandbox/a.heartbeat"
cycle_s = 300
heartbeat_max_s = 3600
"""
    faute = TM.incoherences(divergente)
    assert len(faute) == 1 and "diverge" in faute[0][1]


def test_aucun_service_SANS_cycle_ne_porte_de_seuil_synthetique():
    """LE garde-fou anti-recidive. Mesure du 2026-09-03 : 24 services sur 36 n'ont
    aucun cycle connu. Leur inventer un seuil les ferait passer de 600 s a 90 s d'un
    coup, `NokidoMCP` -- le hub -- inclus. Ce test tombe si quelqu'un decide un jour
    que « pas de cycle connu » vaut « 90 secondes par defaut »."""
    inconnus = """
[[service]]
name = "Inconnu"
heartbeat = "sandbox/a.heartbeat"
heartbeat_tier = "normal"
"""
    seuil, source = TM.temps_mort("Inconnu", seuil_actuel=600.0, texte=inconnus)
    assert source == "inconnu"
    assert seuil == 600.0, "un cycle inconnu ne doit JAMAIS etre durci"
    # Et sans seuil courant offert, on ne fabrique pas non plus une valeur : on rend
    # None, ce que l'appelant doit traiter comme « je ne sais pas ».
    assert TM.temps_mort("Inconnu", texte=inconnus)[0] is None


def test_la_valeur_materialisee_prime_car_c_est_celle_que_lit_le_typescript():
    """Les consommateurs Python doivent voir EXACTEMENT ce que voit le TS. Preferer
    la formule a la valeur ecrite recreerait deux verites."""
    toml = """
[[service]]
name = "X"
heartbeat = "sandbox/x.heartbeat"
cycle_s = 21600
heartbeat_max_s = 64800
"""
    assert TM.temps_mort("X", texte=toml) == (64800.0, "materialise")


def test_le_registre_REEL_respecte_le_contrat():
    """Sur le vrai `services.toml`. Aujourd'hui le contrat est tenu trivialement --
    aucun service ne declare encore de cycle. Ce test devient mordant des la premiere
    migration, et c'est exactement a ce moment-la qu'on en a besoin."""
    fautes = TM.incoherences()
    assert fautes == [], "contrat du temps mort viole : %s" % (fautes,)


def test_la_table_de_migration_reste_un_relais_et_non_un_registre():
    """`CYCLES_HERITES` existe pour que la bascule ne perde pas la connaissance
    acquise, pas pour devenir une seconde verite -- c'est exactement ce qu'etait
    `HB_INTERVAL_S`. Chaque entree deplacee dans services.toml doit en sortir : ce
    test garde la table PETITE et la rend visible quand elle grossit."""
    assert len(TM.CYCLES_HERITES) <= 4, (
        "la table de migration grossit : ces cycles doivent etre DECLARES dans "
        "services.toml, pas accumules ici")
    # Et une entree heritee ne doit jamais masquer une declaration explicite.
    toml = """
[[service]]
name = "NokidoHebbian"
heartbeat = "sandbox/hebbian_linker.heartbeat"
cycle_s = 1234
"""
    assert TM.cycles(toml)["NokidoHebbian"] == (1234.0, "declare")
