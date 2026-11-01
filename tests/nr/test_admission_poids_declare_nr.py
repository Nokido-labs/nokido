"""NR point 1 de l'homeostasie (owner 29/10) : admission PROPORTIONNEE au poids declare.

Physiologie (OpenStax A&P 2e, m45989 « Homeostasis », CC BY 4.0) : chaque parametre a un POINT DE CONSIGNE et une
PLAGE NORMALE ; une petite deviation dans la plage ne mobilise pas la retroaction. Mesure du 29/10 : une dizaine de
pytest d'environ 200 Mo refuses pour 13 a 74 Mo manquants sous une reserve FIXE de 4 Go (heavy=True pour tout job,
app/forge_job_runner.py). Un job DECLARE leger (`# nokido-poids: leger <Mo>`, <= 1024 Mo) est admis si la RAM
disponible couvre son plafond + 1 Go de marge, sous 92 % ; la declaration devient son plafond RSS REEL (un job qui
ment est tue par le gardien existant, cause PLAFOND_RSS). Sans declaration : admission lourde INCHANGEE.
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _jr():
    nom = "forge_job_runner_nr_poids"
    if nom in sys.modules:
        return sys.modules[nom]
    sys.path[:0] = [str(ROOT.parent), str(ROOT), str(ROOT / "app")]
    spec = importlib.util.spec_from_file_location(nom, ROOT / "app" / "forge_job_runner.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[nom] = m
    spec.loader.exec_module(m)
    return m


class _FauxLa:
    """Admission lourde toujours REFUSEE (machine pres du seuil), lane libre."""
    def __init__(self):
        self.observees = []

    def check_ressources(self, heavy=True):
        return {"ok": False, "reason": "RISQUE EMBOLIE RAM (reserve 4 Go)"}

    def observer_decision(self, res):
        self.observees.append(res)

    def current(self, lane):
        return None


def _script(tmp_path, entete):
    p = tmp_path / "s.py"
    p.write_text(entete + "print('ok')\n", encoding="utf-8")
    return p


def _patch(monkeypatch, m, dispo_go, pct):
    monkeypatch.setattr(m, "_la_module", lambda: _FauxLa())
    monkeypatch.setattr(m, "_ram_instant", lambda: (pct, dispo_go))


def test_poids_declare_lu(tmp_path):
    m = _jr()
    assert m.poids_declare(_script(tmp_path, "# nokido-poids: leger 600\n")) == {"classe": "leger", "rss_max_mb": 600}
    assert m.poids_declare(_script(tmp_path, "")) is None
    assert m.poids_declare(_script(tmp_path, "# nokido-poids: leger 5000\n")) is None  # > 1024 Mo : pas leger


def test_leger_admis_dans_la_plage_normale(tmp_path, monkeypatch):
    m = _jr()
    _patch(monkeypatch, m, dispo_go=3.9, pct=84.0)
    r = m.admettre_lancement(str(_script(tmp_path, "# nokido-poids: leger 600\n")))
    assert r["ok"] is True and r.get("poids", {}).get("rss_max_mb") == 600


def test_admission_legere_nourrit_l_observation_pi(tmp_path, monkeypatch):
    """29/10 soir : 7 observations PI seulement en 2 h -- la voie legere (tous les jobs declares) ne passait jamais par
    check_ressources, seul appelant de l'observateur. Le point 1 privait le point 4 de mesures."""
    m = _jr()
    la = _FauxLa()
    monkeypatch.setattr(m, "_la_module", lambda: la)
    monkeypatch.setattr(m, "_ram_instant", lambda: (84.0, 3.9))
    assert m.admettre_lancement(str(_script(tmp_path, "# nokido-poids: leger 600\n")))["ok"] is True
    assert la.observees and la.observees[-1]["ok"] is True and la.observees[-1]["voie"] == "legere"
    # 29/10 soir : la LANE est la cle de jointure du futur juge de rejeu (observation <-> fiche du job, qualifier_fin)
    assert la.observees[-1]["lane"] == "auto:s.py"


def test_lourd_inchange_refuse(tmp_path, monkeypatch):
    m = _jr()
    _patch(monkeypatch, m, dispo_go=3.9, pct=84.0)
    assert m.admettre_lancement(str(_script(tmp_path, "")))["ok"] is False


def test_leger_refuse_hors_plage(tmp_path, monkeypatch):
    m = _jr()
    _patch(monkeypatch, m, dispo_go=1.2, pct=84.0)   # 0,6 + 1 Go de marge non couverts
    assert m.admettre_lancement(str(_script(tmp_path, "# nokido-poids: leger 600\n")))["ok"] is False
    _patch(monkeypatch, m, dispo_go=3.9, pct=93.0)   # plafond absolu
    assert m.admettre_lancement(str(_script(tmp_path, "# nokido-poids: leger 600\n")))["ok"] is False


def test_la_declaration_devient_le_plafond_rss_reel(tmp_path):
    m = _jr()
    assert m.plafond_effectif(_script(tmp_path, "# nokido-poids: leger 600\n"), None) == 600
    assert m.plafond_effectif(_script(tmp_path, "# nokido-poids: leger 600\n"), 300) == 300
    assert m.plafond_effectif(_script(tmp_path, ""), None) is None
