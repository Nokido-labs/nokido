"""NR -- la cle Mistral de Vibe n'existe plus en clair sur disque : injectee au lancement (decision owner 24/10).

Faux secret via monkeypatch de get_secret ; assertions BOOLEENNES (aucune valeur de secret affichee).
"""
import inspect
import os
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT), str(_ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_task_executor as T  # noqa: E402
import forge_provision_clients as P  # noqa: E402
import nokido_vibe as L  # noqa: E402
from nokido_agent.app import forge_cli_harness as H  # noqa: E402

FAUX = "faux-secret-mistral-nr"
VAR = "NOKIDO_MISTRAL_API_KEY"


def _coffre(monkeypatch, valeurs):
    from nokido_agent.app import forge_secrets as s
    monkeypatch.setattr(s, "get_secret", lambda k: valeurs.get(k))


def test_env_du_seul_process_vibe_porte_la_cle_sans_toucher_os_environ(monkeypatch):
    _coffre(monkeypatch, {"MISTRAL_API_KEY": FAUX})
    monkeypatch.delenv(VAR, raising=False)
    avant = dict(os.environ)
    env = H.jeton_mcp("vibe")
    assert (env.get(VAR) == FAUX) is True
    assert (dict(os.environ) == avant) is True
    assert (VAR not in os.environ) is True


def test_lanceur_owner_injecte_la_cle_dans_une_copie(monkeypatch):
    _coffre(monkeypatch, {"MISTRAL_API_KEY": FAUX, "FORGE_TOKEN_VIBE_CLI": "t"})
    base = {"PATH": "x"}
    avant_os = dict(os.environ)
    env = L.environnement(base=base)
    assert (env.get("MISTRAL_API_KEY") == FAUX) is True
    assert (env.get(VAR) == FAUX) is True
    assert ("MISTRAL_API_KEY" not in base) is True
    assert (dict(os.environ) == avant_os) is True


def test_lanceur_owner_cle_absente_echec_nomme(monkeypatch):
    _coffre(monkeypatch, {"FORGE_TOKEN_VIBE_CLI": "t"})
    with pytest.raises(RuntimeError) as exc:
        L.environnement(base={})
    assert ("cle Mistral absente du coffre" in str(exc.value)) is True
    assert (L.main(["--help"]) == 2) is True


def test_executeur_cle_absente_echec_nomme_sans_lancement(monkeypatch, tmp_path):
    _coffre(monkeypatch, {})
    wt = tmp_path / "wt"
    (wt / ".git").mkdir(parents=True)
    monkeypatch.setenv("LAFORGE_VIBE_WORKDIR", str(wt))
    monkeypatch.setattr(T, "_HARNESS_JOBS", tmp_path / "jobs")
    monkeypatch.setattr(T, "_modele_hors_quota", lambda *a, **k: None)
    vus = {}
    monkeypatch.setattr(T, "_attendre_harness", lambda *a, **k: vus.setdefault("lance", True))
    monkeypatch.setattr(T, "_clore_delegation", lambda *a, **k: vus.setdefault("clos", a))
    T._delegate_to_vibe({"id": "t1", "description": "x"}, "jeton")
    assert ("lance" not in vus) is True
    assert ("cle Mistral absente du coffre" in str(vus["clos"])) is True
    assert (vus["clos"][2] is False) is True


def test_provision_n_ecrit_plus_la_cle(monkeypatch, tmp_path):
    _coffre(monkeypatch, {"MISTRAL_API_KEY": FAUX})
    P._patch_vibe(home=tmp_path, dry=False)
    ecrits = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert all(FAUX not in p.read_text(encoding="utf-8", errors="ignore") for p in ecrits)
    assert (not (tmp_path / ".vibe" / ".env").exists()) is True
    # Le proxy « le NOM n'apparait pas dans le module » est tombe avec la voie HYBRIDE (owner 24/10) : le module pose
    # desormais la cle dans le trousseau. L'invariant reel : _patch_vibe ne LIT pas la cle (aucune ecriture possible).
    assert ("MISTRAL_API_KEY" not in inspect.getsource(P._patch_vibe)) is True
