"""NR -- etape 2b-2 du correctif du coffre, lot B1 (plan valide par l'owner le 2026-09-28).

Inventaire 2b-0 (noms seuls) : deux cles de signature (MCP_DEV_SECRET, HUB_JWT_SECRET), la
cle du pont privilegie (signe les demandes d'execution owner) et la cle du journal du
pare-feu etaient HORS des noms reserves -- ni coffre reserve, ni recensement. Et plusieurs
lecteurs contournaient le guichet : environnement d'abord (pont privilegie, break-glass,
hub), `vault_get` direct (pare-feu), parseurs maison de `Nokido.env` (routeur JWT,
IntegrityManager) -- alors que le guichet lit deja `Nokido.env` et l'environnement.

Ce que ce NR verrouille :
  - les quatre noms sont reserves ;
  - chaque lecteur passe par `get_secret` : c'est SA valeur qui sert, meme quand
    l'environnement ou un fichier en portent une autre ;
  - le hub lit ses jetons admin et superviseur au guichet d'abord. TRANSITION jusqu'a 2b-7
    (purge de l'environnement, go owner) : la valeur de l'environnement reste acceptee
    (admin) ou rejouee sur 401 (superviseur), et c'est JOURNALISE -- la divergence
    env/guichet devient mesurable au lieu de casser le pilotage.
AUCUNE assertion ne compare en affichant une valeur : chaque comparaison est reduite a un
booleen AVANT l'assert (un vrai secret lu par erreur ne doit jamais finir dans un rapport).
"""
import ast
import base64
import importlib
import importlib.util
import json
import logging
import os
import textwrap
import types
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
NOUVEAUX_RESERVES = ("MCP_DEV_SECRET", "HUB_JWT_SECRET", "LAFORGE_PRIV_BRIDGE_HMAC",
                     "firewall_log_hmac")
G_MAITRE = "maitre-guichet-nr-2b2-" + "g" * 32
G_ADMIN = "admin-guichet-nr-2b2-" + "h" * 32
E_MAITRE = "maitre-environnement-nr-2b2-" + "e" * 32


@pytest.fixture
def fs():
    return importlib.import_module("nokido_agent.app.forge_secrets")


def _guichet(monkeypatch, fs, store):
    monkeypatch.setattr(fs, "get_secret", lambda k, required=False: store.get(k))


def test_les_quatre_noms_sont_reserves(fs):
    manquants = [n for n in NOUVEAUX_RESERVES if n not in fs.NOMS_RESERVES]
    assert not manquants, manquants


# --- lecteurs de bibliotheque ----------------------------------------------------------

def test_break_glass_vient_du_guichet(fs, monkeypatch):
    rbac = importlib.import_module("nokido_agent.app.forge_rbac")
    _guichet(monkeypatch, fs, {"FORGE_MCP_TOKEN": G_MAITRE, "LAFORGE_ADMIN_TOKEN": G_ADMIN})
    monkeypatch.setenv("FORGE_MCP_TOKEN", E_MAITRE)
    jetons = rbac._load_breakglass_tokens()
    ok = set(jetons) == {G_MAITRE, G_ADMIN}
    assert ok, "break-glass lu hors guichet (environnement ou Nokido.env)"


def test_cle_du_journal_du_pare_feu_vient_du_guichet(fs, monkeypatch):
    fw = importlib.import_module("nokido_agent.app.forge_semantic_firewall")
    mv = importlib.import_module("nokido_agent.app.forge_machine_vault")
    cle = b"cle-journal-pare-feu-nr-2b2-" + b"k" * 8
    _guichet(monkeypatch, fs, {"firewall_log_hmac": base64.b64encode(cle).decode()})
    appels = []
    monkeypatch.setattr(mv, "vault_get", lambda *a, **kw: appels.append(1))
    monkeypatch.setattr(fw, "_LOG_HMAC_KEY", None)
    ok = fw._log_hmac_key() == cle
    assert ok, "cle du journal du pare-feu lue hors guichet"
    assert not appels, "vault_get direct : le coffre reserve n'est jamais consulte"


def test_routeur_jwt_ne_relit_pas_nokido_env(monkeypatch, tmp_path):
    jr = importlib.import_module("nokido_agent.app.forge_jwt_router")
    (tmp_path / "Nokido.env").write_text("HUB_JWT_SECRET=valeur-fichier-nr\n",
                                         encoding="utf-8")
    monkeypatch.setattr(jr, "ROOT", tmp_path)
    monkeypatch.setattr(jr, "get_secret", lambda k, required=False: None)
    ok = jr._get_secret() == ""
    assert ok, "parseur maison de Nokido.env : lecture d'un nom reserve hors guichet"


def test_integrity_manager_prend_la_valeur_du_guichet(fs, monkeypatch):
    fi = importlib.import_module("nokido_agent.app.forge_integrity")
    _guichet(monkeypatch, fs, {"MCP_DEV_SECRET": "dev-guichet-nr-2b2-" + "d" * 32})
    attendu = "dev-guichet-nr-2b2-" + "d" * 32
    ok = fi.IntegrityManager.from_env()._secret in (attendu, attendu.encode())
    assert ok, "IntegrityManager ne prend pas la valeur du guichet"


def _pont():
    spec = importlib.util.spec_from_file_location(
        "forge_privileged_bridge_nr_2b2", ROOT / "tools" / "forge_privileged_bridge.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_cle_du_pont_privilegie_vient_du_guichet(fs, monkeypatch):
    monkeypatch.setenv("LAFORGE_PRIV_BRIDGE_HMAC", "cle-pont-environnement-nr")
    pb = _pont()
    _guichet(monkeypatch, fs, {"LAFORGE_PRIV_BRIDGE_HMAC": "cle-pont-guichet-nr"})
    ok = pb._bridge_key() == b"cle-pont-guichet-nr"
    assert ok, "l'environnement passe avant le guichet pour la cle du pont privilegie"


# --- le hub : fonctions extraites de sa source, liees a des doublures -----------------

def _fonction_du_hub(nom: str, espace: dict):
    """Construit la fonction imbriquee `nom` de `nokido_hub.py` a partir de son objet
    code, dans l'espace de noms `espace` (doublures). Le hub n'est PAS importe."""
    src = (ROOT / "tools" / "nokido_hub.py").read_text(encoding="utf-8")
    for noeud in ast.walk(ast.parse(src)):
        if isinstance(noeud, ast.FunctionDef) and noeud.name == nom:
            module = compile(textwrap.dedent(ast.get_source_segment(src, noeud)),
                             f"nokido_hub.py::{nom}", "exec")
            code = next(c for c in module.co_consts
                        if isinstance(c, types.CodeType) and c.co_name == nom)
            defauts = tuple(ast.literal_eval(d) for d in noeud.args.defaults)
            espace.setdefault("__builtins__", __builtins__)
            return types.FunctionType(code, espace, nom, defauts or None)
    raise AssertionError(f"{nom} introuvable dans nokido_hub.py")


class _Requete:
    def __init__(self, jeton):
        self.headers = {"authorization": f"Bearer {jeton}"}
        self.client = None
        self.method = "POST"
        self.scope = {"path": "/admin/nr"}


def _admin_tok_ok(refus):
    return _fonction_du_hub("_admin_tok_ok", {
        "_journaliser_refus_admin": lambda req, tok, motif, scope: refus.append(motif),
        "_ADMIN_ORGANES": frozenset(),
    })


def test_admin_accepte_le_maitre_du_guichet(fs, monkeypatch):
    refus = []
    f = _admin_tok_ok(refus)
    _guichet(monkeypatch, fs, {"FORGE_MCP_TOKEN": G_MAITRE})
    monkeypatch.setenv("FORGE_MCP_TOKEN", E_MAITRE)
    assert f(_Requete(G_MAITRE)) is True
    assert f(_Requete("inconnu-nr")) is False


def test_admin_transition_environnement_accepte_et_journalise(fs, monkeypatch, caplog):
    refus = []
    f = _admin_tok_ok(refus)
    _guichet(monkeypatch, fs, {"FORGE_MCP_TOKEN": G_MAITRE})
    monkeypatch.setenv("FORGE_MCP_TOKEN", E_MAITRE)
    with caplog.at_level(logging.WARNING):
        assert f(_Requete(E_MAITRE)) is True
    assert "ENVIRONNEMENT" in caplog.text, "accord par l'environnement seul non journalise"


def test_admin_sans_aucun_maitre_refuse_le_jeton_vide(fs, monkeypatch):
    refus = []
    f = _admin_tok_ok(refus)
    _guichet(monkeypatch, fs, {})
    monkeypatch.delenv("FORGE_MCP_TOKEN", raising=False)
    monkeypatch.delenv("LAFORGE_NO_AUTH", raising=False)
    assert f(_Requete("")) is False


class _Reponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return b"{}"


def _sup_call_sync(acceptes, vus):
    def _urlopen(req, timeout=0):
        porteur = (req.get_header("Authorization") or "")[len("Bearer "):]
        vus.append({G_MAITRE: "guichet", E_MAITRE: "env"}.get(porteur, "?"))
        if porteur in acceptes:
            return _Reponse()
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)

    faux_urlreq = types.SimpleNamespace(Request=urllib.request.Request, urlopen=_urlopen)
    return _fonction_du_hub("_sup_call_sync", {
        "_SUPERVISOR_URL": "http://127.0.0.1:9", "_urlreq": faux_urlreq,
        "_urlerr": urllib.error, "json": json, "os": os})


def test_superviseur_recoit_le_jeton_du_guichet(fs, monkeypatch):
    vus = []
    f = _sup_call_sync({G_MAITRE}, vus)
    _guichet(monkeypatch, fs, {"LAFORGE_SUPERVISOR_TOKEN": G_MAITRE})
    monkeypatch.setenv("LAFORGE_SUPERVISOR_TOKEN", E_MAITRE)
    assert f("GET", "/nr")["ok"] is True
    assert vus == ["guichet"]


def test_superviseur_rejoue_l_environnement_sur_401_et_le_dit(fs, monkeypatch, caplog):
    vus = []
    f = _sup_call_sync({E_MAITRE}, vus)
    _guichet(monkeypatch, fs, {"LAFORGE_SUPERVISOR_TOKEN": G_MAITRE})
    monkeypatch.setenv("LAFORGE_SUPERVISOR_TOKEN", E_MAITRE)
    with caplog.at_level(logging.WARNING):
        assert f("GET", "/nr")["ok"] is True
    assert vus == ["guichet", "env"]
    assert "divergence" in caplog.text
