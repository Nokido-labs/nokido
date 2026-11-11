"""NR : l'alerte claude_code.mcp nomme le serveur et le champ modifies, jamais une valeur.

5/11 : trois changements de claude_code.mcp en 30 min, un hash pour tout detail, et ~/.claude.json interdit de lecture aux
jobs (il peut porter des jetons). Personne ne pouvait dire ce qui bougeait. L'empreinte globale reste celle d'avant :
la changer aurait fait lever une fausse alerte a la relance du service.
"""
import hashlib
import importlib.util
import json
import pathlib

_CHEMIN = pathlib.Path(__file__).resolve().parents[2] / "tools" / "forge_comm_watch.py"
_spec = importlib.util.spec_from_file_location("fcw_nom_nr", _CHEMIN)
fcw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fcw)

SECRET = "-".join(["jeton", "tres", "secret", "42"])


def _conf(chemin, globaux, projets=None):
    chemin.write_text(json.dumps({
        "numStartups": 1, "mcpServers": globaux,
        "projects": {k: {"mcpServers": v} for k, v in (projets or {}).items()},
    }), encoding="utf-8")
    return fcw._fingerprint(chemin, "json_mcp")


def _detail(avant, apres):
    changements = fcw.diff({"b": avant}, {"b": apres})
    assert len(changements) == 1
    return changements[0]["detail"]


def test_serveur_modifie_nomme_avec_son_champ_sans_valeur(tmp_path):
    f = tmp_path / ".claude.json"
    avant = _conf(f, {"hub": {"url": "http://x", "headers": {"Authorization": SECRET}}, "autre": {"url": "http://z"}})
    apres = _conf(f, {"hub": {"url": "http://x", "headers": {"Authorization": SECRET + "b"}}, "autre": {"url": "http://z"}})
    detail = _detail(avant, apres)
    assert "hub(headers)" in detail
    assert "autre" not in detail
    assert SECRET not in detail and "http://" not in detail


def test_serveur_ajoute_et_retire_nommes(tmp_path):
    f = tmp_path / ".claude.json"
    avant = _conf(f, {"ancien": {"url": "http://a"}})
    apres = _conf(f, {"neuf": {"url": "http://b"}})
    detail = _detail(avant, apres)
    assert "+['neuf']" in detail and "-['ancien']" in detail


def test_serveur_de_projet_distingue_du_global(tmp_path):
    f = tmp_path / ".claude.json"
    avant = _conf(f, {"hub": {"url": "1"}}, {"C:/p": {"hub": {"command": "a"}}})
    apres = _conf(f, {"hub": {"url": "1"}}, {"C:/p": {"hub": {"command": "b"}}})
    detail = _detail(avant, apres)
    assert "C:/p::hub(command)" in detail


def test_aucune_valeur_dans_l_empreinte_persistee(tmp_path):
    f = tmp_path / ".claude.json"
    fp = _conf(f, {"hub": {"url": "http://x", "headers": {"Authorization": SECRET}}})
    texte = json.dumps(fp)
    assert SECRET not in texte and "http://x" not in texte
    assert set(fp["serveurs"]["hub"]) == {"url", "headers"}


def test_empreinte_globale_inchangee_pas_de_fausse_alerte_a_la_relance(tmp_path):
    f = tmp_path / ".claude.json"
    fp = _conf(f, {"hub": {"url": "1"}})
    attendu = json.dumps({"global": {"hub": {"url": "1"}}, "projets": {}}, sort_keys=True).encode("utf-8")
    assert fp["hash"] == hashlib.sha256(attendu).hexdigest()[:16]
    etat_d_avant = {"exists": True, "hash": fp["hash"], "entries": None}
    assert fcw.diff({"b": etat_d_avant}, {"b": fp}) == []


def test_etat_d_avant_sans_detail_le_dit(tmp_path):
    f = tmp_path / ".claude.json"
    avant = {"exists": True, "hash": "ancien", "entries": None}
    detail = _detail(avant, _conf(f, {"hub": {"url": "1"}}))
    assert "hash ancien ->" in detail
    assert "non nomme" in detail


def test_json_illisible_reste_visible(tmp_path):
    f = tmp_path / ".claude.json"
    avant = _conf(f, {"hub": {"url": "1"}})
    f.write_text("{pas du json", encoding="utf-8")
    apres = fcw._fingerprint(f, "json_mcp")
    assert apres["hash"].startswith("ILLISIBLE:")
    assert "ILLISIBLE:" in _detail(avant, apres)
