# -*- coding: utf-8 -*-
"""NR — le suppleant de `pip-audit` a enfin un PRODUCTEUR.

MESURE QUI L'IMPOSE (2026-09-17). Le gate `pip-audit` ne mesure pas lui-meme :
il JUGE la fraicheur d'un rapport depose dans `sandbox/pip_audit_history/`
(TTL 7 j). Ce rapport n'avait AUCUN producteur declare — ni service, ni tache
planifiee, ni workflow :

    pip_audit_2026-09-07.json    |  qui LIT   : tools/ci_local.py
    pip_audit_2026-09-09.json    |  qui LANCE : personne
    pip_audit_2026-09-16.json    |

Trois rapports en dix jours, chacun produit parce qu'un agent y a pense. Entre
le 09/09 et le 16/09 il s'est ecoule EXACTEMENT 7 jours, soit le TTL : sans un
passage manuel la veille, le suppleant serait perime et un domaine CRITIQUE
n'aurait plus aucune mesure, sans que rien ne le signale.

C'est le motif « un garde branche sur un signal que PERSONNE n'emet » :
consommateur present, emetteur absent. Un mecanisme present n'est pas un effet
reel.

⚠️ ET CE N'ETAIT PAS UN DEFAUT D'OUTIL. `pypi.org` est refuse par POLITIQUE DE
COMPTE, pas par panne : mesure du 2026-09-17, meme machine, meme instant —
`laforgesbxoffline` rend HTTP 000 en 0,03 s (refus LOCAL immediat) et
`laforgesbxonline` rend HTTP 200 en 0,33 s. Seul le compte change.
`DISABLED_BY_POLICY != RESOURCE_UNAVAILABLE`. L'hermeticite de la CI est VOULUE,
donc la mesure part en job online plutot que de donner l'egress a la CI.
"""

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_circadian as C  # noqa: E402


def _sans_garde_pytest(monkeypatch):
    """Neutralise les DEUX gardes de production pour pouvoir observer le corps.

    Ces gardes sont justes — une tache de production ne part jamais d'un
    harnais de test — mais ils rendent le handler inerte, donc intestable tel
    quel. On les leve explicitement, jamais en les supprimant du code.
    """
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(C, "current_phase", lambda: C.Phase.NREM1)


def test_un_verrou_humain_ILLISIBLE_refuse_le_restart(monkeypatch):
    """Le garde de corrigibilite est FAIL-CLOSED, pas fail-open.

    PAYE LE 2026-09-17. `_restart_service` faisait :

        try:
            from ...forge_opsec import is_human_locked
            if is_human_locked(): return {...}
        except Exception:
            pass                      # <- et le restart PARTAIT

    Donc des que le capteur du verrou cassait — module absent, base
    verrouillee, ACL — le verrou humain se contournait TOUT SEUL, sans une
    ligne de journal. Un garde dont la panne autorise le geste qu'il interdit
    ne garde rien.

    `UNKNOWN != NO` : ne pas pouvoir lire le verrou doit RETENIR le geste. Le
    cout des deux erreurs n'est pas symetrique — un restart de trop contre un
    verrou humain est exactement ce que ce garde existe pour empecher.
    """
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_opsec", None)
    appels = []
    monkeypatch.setattr(C.urllib.request, "urlopen",
                        lambda *a, **k: appels.append(a) or (_ for _ in ()).throw(
                            AssertionError("le restart est PARTI malgre un verrou illisible")))
    res = C._restart_service("NokidoTest")
    assert res["ok"] is False
    assert res["skipped"] == "verrou_humain_illisible"
    assert not appels, "un appel de restart a ete emis"


def test_la_tache_est_DECLAREE_en_NREM1():
    """Un handler qu'aucune phase n'appelle est un mecanisme sans effet.

    ⚠️ La table s'appelle `PHASE_PROGRAM`. Ma premiere version avait DEVINE
    `PHASE_ACTIONS` — et pour verifier le nom j'ai importe le module dans un
    `action=python`, dont l'import a depasse 120 s et A TUE LE HUB. Le nom se
    lit dans la source (`findstr`), jamais en chargeant l'organe.
    """
    actions = C.PHASE_PROGRAM[C.Phase.NREM1]
    noms = {a.name for a in actions}
    assert "audit_dependances" in noms, (
        "tache absente de NREM1 : le producteur ne tournerait jamais (%s)" % sorted(noms))
    cible = next(a for a in actions if a.name == "audit_dependances")
    assert cible.handler is C._mesurer_dependances_vulnerables, (
        "la tache est declaree mais pointe un autre handler")


def test_sous_pytest_la_tache_de_production_ne_part_PAS():
    """Etre APPELE n'est pas etre en situation : un harnais de test ne doit
    pas declencher un job reel."""
    os.environ["PYTEST_CURRENT_TEST"] = "marqueur"
    res = C._mesurer_dependances_vulnerables()
    assert res["pip_audit"] == "sous pytest"


def test_hors_phase_la_tache_s_abstient(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(C, "current_phase", lambda: C.Phase.NREM3)
    res = C._mesurer_dependances_vulnerables()
    assert res["pip_audit"] == "hors phase"


def test_un_rapport_FRAIS_ne_relance_rien(tmp_path, monkeypatch):
    """Ne pas POMPER : relancer chaque nuit un rapport de la veille brulerait
    du reseau pour rien. Le seuil (3 j) reste SOUS le TTL du gate (7 j), pour
    qu'une nuit ratee ne suffise pas a perimer le suppleant."""
    _sans_garde_pytest(monkeypatch)
    (tmp_path / "pip_audit_2026-09-17.json").write_text("{}", encoding="utf-8")
    lance = []
    res = C._mesurer_dependances_vulnerables(
        hist=tmp_path, lanceur=lambda *a, **k: lance.append((a, k)))
    assert res["pip_audit"] == "frais"
    assert not lance, "un rapport frais a quand meme declenche un job"


def test_un_rapport_PERIME_declenche_le_job_online(tmp_path, monkeypatch):
    _sans_garde_pytest(monkeypatch)
    vieux = tmp_path / "pip_audit_2026-09-01.json"
    vieux.write_text("{}", encoding="utf-8")
    os.utime(vieux, (time.time() - 10 * 86400, time.time() - 10 * 86400))
    lance = []

    def _faux_lanceur(script, **kw):
        lance.append((script, kw))
        return {"job_id": "job_test"}

    res = C._mesurer_dependances_vulnerables(hist=tmp_path, lanceur=_faux_lanceur)
    assert res["pip_audit"] == "REQUESTED"
    assert lance, "aucun job lance sur un rapport perime"
    script, kw = lance[0]
    assert "forge_pip_audit_mesure" in script
    assert kw.get("online") is True, (
        "job lance SANS egress : il echouerait exactement comme la CI")
    assert kw.get("lane"), "job sans lane — c'est ainsi que la machine a sature"
    # ⚠️ PAYE LE 2026-09-17, en forcant ce job a la main. Sans `--sortie`, le
    # script ecrit `sandbox/pip_audit_<date>.json` (la ou `forge_deps_reconcilier`
    # cherche) alors que le GATE lit `sandbox/pip_audit_history/`. Le job rendait
    # donc rc=0 avec « 226 paquets audites » et le gate restait ANERGIQUE : un
    # producteur qui depose hors de portee de son consommateur est un mecanisme
    # sans effet. Et `sandbox/*.json` etant gitignore, le rapport etait en plus
    # invisible depuis un worktree detache.
    assert "pip_audit_history" in (kw.get("script_args") or ""), (
        "le rapport ne serait pas depose la ou le gate le lit : %r"
        % kw.get("script_args"))


def test_le_handler_rend_REQUESTED_jamais_ACHIEVED(tmp_path, monkeypatch):
    """`REQUESTED != ACCEPTED != ACHIEVED`. Lancer un job prouve le SPAWN, pas
    l'execution : un handler qui rendrait « OK » ferait croire a une mesure."""
    _sans_garde_pytest(monkeypatch)
    res = C._mesurer_dependances_vulnerables(
        hist=tmp_path, lanceur=lambda *a, **k: {"job_id": "x"})
    assert res["pip_audit"] == "REQUESTED"
    assert res["pip_audit"] not in ("OK", "ACHIEVED", "MESURE")


def test_un_lanceur_indisponible_est_DIT(tmp_path, monkeypatch):
    """Un producteur qu'on ne peut pas lancer ne doit pas echouer en silence :
    sinon le suppleant se perime et le gate criera ANERGIQUE sans cause."""
    _sans_garde_pytest(monkeypatch)

    def _casse(*a, **k):
        raise RuntimeError("lane occupee")

    res = C._mesurer_dependances_vulnerables(hist=tmp_path, lanceur=_casse)
    assert res["pip_audit"] == "lancement refuse"
    assert "lane occupee" in res["erreur"]


def test_un_historique_illisible_est_DIT_et_non_traite_en_vide(monkeypatch):
    """ILLISIBLE != ABSENT : un dossier qu'on ne peut pas lire ne prouve pas
    qu'aucun rapport n'existe."""
    _sans_garde_pytest(monkeypatch)

    class _Casse:
        """Un dossier present mais non lisible (ACL) — cas reel sous un compte
        de service, et qu'un `Path` inexistant ne simule PAS : `glob` sur un
        chemin absent rend un iterateur vide, pas une erreur."""

        def glob(self, _motif):
            raise OSError("acces refuse")

    res = C._mesurer_dependances_vulnerables(hist=_Casse())
    assert res["pip_audit"] == "historique ILLISIBLE"
