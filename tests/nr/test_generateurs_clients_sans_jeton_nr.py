# -*- coding: utf-8 -*-
"""NR (owner 3/11, « nettoie les variables FORGE_TOKEN restantes » + « corriger + NR ») : aucun generateur de
config cliente n'ecrit plus de jeton, et rien ne repose les FORGE_TOKEN_* dans HKCU.

Les clients HTTP passent en OAuth (`nokido-oauth`, URL seule) ; les ponts stdio lisent le coffre
(`LAFORGE_AGENT` seul dans `env`). Avant ce correctif : `forge_connect_clients` ecrivait l'en-tete
d'autorisation avec le jeton dans 6 configs et le jeton CLAUDE_DESKTOP en clair dans
claude_desktop_config.json ; `forge_provision_clients --apply` reposait les 9 variables HKCU retirees
le 3/11 ; `forge_freetier_probe` relisait le jeton CLAUDE dans l'environnement.
"""
import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_connect_clients as C  # noqa: E402
import forge_provision_clients as P  # noqa: E402

MARQUE = "VALEUR-TEMOIN-DU-NR-"


def _faux_coffre(monkeypatch):
    m = types.ModuleType("nokido_agent.app.forge_secrets")
    m.get_secret = lambda k, required=False: MARQUE + k
    m.set_secret = lambda k, v: True
    for nom in ("nokido_agent", "nokido_agent.app"):
        monkeypatch.setitem(sys.modules, nom, sys.modules.get(nom) or types.ModuleType(nom))
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_secrets", m)


def test_blocs_emis_ne_portent_aucun_jeton():
    sortie = P._cfg_blocks({a: MARQUE + a for a in P.AGENTS})
    assert MARQUE not in sortie
    assert "Bearer" not in sortie
    assert "FORGE_TOKEN_" not in sortie
    assert "nokido-oauth" in sortie  # la forme OAuth est bien emise


def test_connect_clients_n_ecrit_aucun_jeton(monkeypatch, tmp_path):
    _faux_coffre(monkeypatch)
    ecrits = []

    def capture(path, root_key, entry_key, entry, dry):
        ecrits.append((entry_key, json.dumps(entry)))
        return "[capture]"

    monkeypatch.setattr(C, "_merge_json", capture)
    monkeypatch.setattr(C, "HOME", tmp_path)
    monkeypatch.setattr(C, "APPDATA", tmp_path / "AppData" / "Roaming")
    monkeypatch.setattr(sys, "argv", ["forge_connect_clients.py", "--dry-run", "--home", str(tmp_path)])
    C.main()
    assert ecrits, "le chemin reel n'a ecrit aucune entree : le NR passerait a vide"
    for cle, texte in ecrits:
        assert MARQUE not in texte, cle
        assert "Bearer" not in texte, cle
        assert "FORGE_TOKEN_" not in texte, cle


def test_sources_sans_entete_ni_env_en_clair():
    for f in ("forge_connect_clients.py", "forge_provision_clients.py"):
        src = (ROOT / "tools" / f).read_text(encoding="utf-8")
        assert "Bearer {tok(" not in src and "Bearer {tok[" not in src, f
        assert '"FORGE_TOKEN_CLAUDE_DESKTOP": tok' not in src, f
    probe = (ROOT / "tools" / "forge_freetier_probe.py").read_text(encoding="utf-8")
    assert 'os.environ.get("FORGE_TOKEN_' not in probe


def test_apply_et_patch_codex_ne_reposent_plus_rien(monkeypatch, tmp_path):
    _faux_coffre(monkeypatch)
    appels = []
    monkeypatch.setattr(P, "_sync_env", lambda tok, dry: appels.append("sync") or [])
    monkeypatch.setattr(P, "_patch_codex", lambda j, dry: appels.append("codex") or [])
    monkeypatch.setattr(P, "OUT", str(tmp_path / "out.txt"))
    for drapeau in ("--apply", "--patch-codex"):
        monkeypatch.setattr(sys, "argv", ["forge_provision_clients.py", drapeau])
        P.main()
    assert appels == [], appels
