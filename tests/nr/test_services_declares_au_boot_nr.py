# -*- coding: utf-8 -*-
"""NR — ce que le proxy mandate, le lanceur ouvre et le superviseur declare : UN seul port.

Defaut paye le 2026-09-18, invisible a la lecture de chaque fichier pris isolement :

    SERVICES['graph']['target']          -> :7474   (ce que /graph/ mandatait)
    launcher.MODULES['graph']            -> :7420   (le seul que le lanceur sache ouvrir,
                                                     et il declare open_path='/graph/')
    services.toml NokidoGraphExplorer    -> :7420

Trois registres, deux ports. Resultat : demarrer « graph » ouvrait :7420 pendant que
/graph/ interrogeait :7474 et restait eteint — un service SAIN derriere une porte qui
donne ailleurs. Aucun geste de l'utilisateur ne pouvait y remedier, et rien ne le
signalait : chaque fichier, lu seul, etait coherent.

:7474 n'etait pas un port mort : il appartient a un SECOND explorateur, `NokidoGraph`
(app/forge_graph_explorer.py), coupe au mode sauvegarde du 2026-09-05. C'est precisement
ce qui rend le defaut discret — deux services legitimes, et la route branchee sur celui
que le lanceur ignore.

MORSURE : reposer 7474 comme cible de /graph fait rougir
`test_la_cible_du_proxy_est_le_port_declare`.

Hermetique : AST + TOML, aucun service demarre, aucun port ouvert.
"""
from __future__ import annotations

import ast
import re
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

APP = ROOT / "app" / "web_hub" / "app.py"
TOML = ROOT / "proxy_deno" / "core" / "services.toml"

# module du lanceur -> service declare au superviseur qui doit servir le MEME port
APPARIEMENT = {
    "graph": "NokidoGraphExplorer",
    "tui_bridge": "NokidoTuiBridge",
}


def _services() -> dict:
    if not TOML.exists():
        pytest.skip("services.toml absent")
    d = tomllib.loads(TOML.read_text(encoding="utf-8"))
    return {s["name"]: s for s in d.get("service", []) if s.get("name")}


def _cible_proxy(cle: str) -> int | None:
    """Port vise par SERVICES[cle]['target'], lu a l'AST (aucun import de l'app)."""
    if not APP.exists():
        pytest.skip("app.py absent")
    arbre = ast.parse(APP.read_text(encoding="utf-8", errors="replace"))
    for n in ast.walk(arbre):
        if not (isinstance(n, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "SERVICES" for t in n.targets)):
            continue
        for k, v in zip(n.value.keys, n.value.values):
            if not (isinstance(k, ast.Constant) and k.value == cle):
                continue
            for kk, vv in zip(v.keys, v.values):
                if (isinstance(kk, ast.Constant) and kk.value == "target"
                        and isinstance(vv, ast.Constant)):
                    m = re.search(r":(\d+)", vv.value)
                    return int(m.group(1)) if m else None
    return None


def _modules_lanceur():
    try:
        from app.web_hub import launcher as LA
    except Exception as exc:  # noqa: BLE001 — illisible n'est pas absent
        pytest.skip("launcher illisible (%s)" % type(exc).__name__)
    return LA.MODULES


@pytest.mark.parametrize("mod,service", sorted(APPARIEMENT.items()))
def test_le_service_du_boot_sert_le_port_du_lanceur(mod, service):
    """Le superviseur et le lanceur doivent ouvrir LE MEME port pour le meme module."""
    svcs = _services()
    assert service in svcs, (
        "%s n'est pas declare dans services.toml : le module ne vivrait que par un "
        "demarrage a la demande, et disparaitrait a chaque redemarrage" % service
    )
    spec = _modules_lanceur().get(mod)
    assert spec is not None, "le lanceur ne connait plus le module %r" % mod
    assert svcs[service].get("port") == spec.default_port, (
        "%s declare le port %s alors que le lanceur ouvre %s pour %r : selon qui demarre "
        "le module, il n'ecoute pas au meme endroit"
        % (service, svcs[service].get("port"), spec.default_port, mod)
    )


@pytest.mark.parametrize("mod,service", sorted(APPARIEMENT.items()))
def test_le_service_du_boot_lance_le_meme_script(mod, service):
    """Meme port ne suffit pas : deux scripts differents sur un port, c'est pire."""
    svcs = _services()
    spec = _modules_lanceur().get(mod)
    if service not in svcs or spec is None:
        pytest.skip("appariement incomplet")
    args = " ".join(svcs[service].get("args") or []).replace("\\", "/")
    attendu = str(spec.script).replace("\\", "/")
    assert attendu in args, (
        "%s lance %r la ou le lanceur lance %r : deux binaires pour un meme port"
        % (service, args, attendu)
    )


@pytest.mark.parametrize("mod,service", sorted(APPARIEMENT.items()))
def test_le_service_est_actif_au_boot(mod, service):
    """Demande owner du 2026-09-18 : disponibles au demarrage, sans qu'une page n'agisse.

    Le proxy ne reveille plus rien ; si ces services etaient `disabled`, la capacite
    disparaitrait a chaque redemarrage sans que rien ne le dise.
    """
    svcs = _services()
    if service not in svcs:
        pytest.skip("%s absent" % service)
    assert not svcs[service].get("disabled"), (
        "%s est disabled : le reveil automatique ayant ete retire du proxy, plus rien "
        "ne le demarrerait" % service
    )


def test_la_cible_du_proxy_est_le_port_declare():
    """MORSURE — c'est l'incoherence exacte qui a rendu /graph/ inatteignable."""
    port_proxy = _cible_proxy("graph")
    assert port_proxy is not None, "SERVICES['graph']['target'] illisible"
    spec = _modules_lanceur().get("graph")
    assert port_proxy == spec.default_port, (
        "/graph mandate :%s alors que le module que le lanceur ouvre ecoute :%s — "
        "demarrer le service laisserait la page eteinte" % (port_proxy, spec.default_port)
    )


@pytest.mark.parametrize("mod,service", sorted(APPARIEMENT.items()))
def test_un_service_du_boot_a_un_pouls_ET_un_emetteur(mod, service):
    """Un pouls DECLARE sans emetteur fait lire une mort permanente -> respawn en boucle.

    C'est le piege symetrique de celui que ce depot documente depuis le 2026-07-30
    (« un garde branche sur un signal que personne n'emet ») : ici, c'est le RECEPTEUR
    qu'on declare dans le vide. Le superviseur ne verrait jamais de battement et tuerait
    un service parfaitement sain, indefiniment.

    On verifie donc les DEUX bouts : la cle `heartbeat` au TOML, et le fait que le script
    lance par ce service arme reellement un pouls.
    """
    svcs = _services()
    if service not in svcs:
        pytest.skip("%s absent" % service)
    s = svcs[service]
    hb = s.get("heartbeat")
    assert hb, "%s n'a pas de cle heartbeat : sa mort serait silencieuse" % service

    # La derivation du depot, rappelee dans services.toml : max(90, 3 x cycle_s).
    cycle = s.get("cycle_s")
    assert cycle, "%s declare un heartbeat sans cycle_s : la peremption est arbitraire" % service
    assert s.get("heartbeat_max_s") == max(90, 3 * cycle), (
        "%s rompt la derivation heartbeat_max_s = max(90, 3 x cycle_s)" % service
    )

    # L'EMETTEUR : le script doit armer un pouls, et sur le MEME nom que la cle declaree.
    script = ROOT / str(_modules_lanceur()[mod].script)
    if not script.exists():
        pytest.skip("script %s introuvable" % script)
    source = script.read_text(encoding="utf-8", errors="replace")
    assert "demarrer_pouls_service_http" in source, (
        "%s declare `heartbeat` mais %s n'arme aucun pouls : le superviseur lirait une "
        "mort permanente" % (service, script.name)
    )
    nom_attendu = Path(hb).stem  # sandbox/<nom>.heartbeat
    assert '"%s"' % nom_attendu in source, (
        "le TOML attend `%s` mais le script n'emet pas sous ce nom : le pouls serait "
        "ecrit ailleurs et le service compte pour mort" % nom_attendu
    )


def test_le_second_explorateur_reste_hors_route():
    """Contre-epreuve : :7474 existe, il est juste coupe — et plus personne ne le vise.

    Si `NokidoGraph` etait reactive un jour, ce test rappellerait qu'il faut trancher
    lequel des deux sert /graph/, plutot que de laisser deux explorateurs se disputer
    la meme tuile.
    """
    svcs = _services()
    autre = svcs.get("NokidoGraph")
    if autre is None:
        pytest.skip("NokidoGraph n'existe plus")
    if not autre.get("disabled"):
        assert autre.get("port") != _cible_proxy("graph"), (
            "NokidoGraph est reactive ET vise par /graph : deux explorateurs pour une "
            "seule route, il faut trancher lequel la sert"
        )
