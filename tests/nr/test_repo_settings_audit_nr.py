"""NR -- l'audit des reglages serveur ne doit jamais conclure 'sur' par defaut.

POURQUOI. Cet audit decide si `main` peut disparaitre sans casser une dependance
invisible (branche par defaut, protection, PR, webhook). Le danger n'est pas de
lire un mauvais fait -- c'est de rendre 'aucun bloqueur' quand la mesure a
ECHOUE (token absent, protection illisible). On verrouille donc la table :
    * default_branch == la branche auditee            -> bloqueur
    * protection classique OU ruleset visant la branche -> bloqueur
    * PR ouverte de base OU tete == branche            -> bloqueur
    * 404 sur la protection                            -> PAS un bloqueur (= absente)
    * token absent                                     -> ok False (ne PAS conclure)
    * panne reseau sur un GET critique                 -> ok False
Aucun appel reseau : on fabrique les reponses (`_api` monkeypatche).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _zone in ("tools", "app"):
    _p = str(ROOT / _zone)
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _mod():
    chemin = ROOT / "tools" / "forge_repo_settings_audit.py"
    assert chemin.exists(), "module absent : %s" % chemin
    spec = importlib.util.spec_from_file_location("forge_repo_settings_audit", chemin)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["forge_repo_settings_audit"] = mod
    sys.modules["nokido_agent.tools.forge_repo_settings_audit"] = mod
    spec.loader.exec_module(mod)
    return mod


def _fake_api(table):
    """table : dict {endpoint_suffix: payload}. Le match est par SUFFIXE (plus
    longue cle gagnante), pas par substring : sinon la cle du repo racine
    ('repos/user/nokido') capturerait TOUS les sous-chemins (/hooks, /pulls...)
    et rendrait le mauvais payload -- exactement le faux du 1er jet. Un chemin
    sans cle -> HTTPError 404 simule (comme GitHub sur une protection absente)."""
    class _HTTP404(Exception):
        code = 404

    def _api(path, _cred):
        p = path.split("?")[0]
        best = None
        for frag in table:
            if p == frag or p.endswith("/" + frag):
                if best is None or len(frag) > len(best):
                    best = frag
        if best is None:
            raise _HTTP404("404 %s" % path)
        payload = table[best]
        if isinstance(payload, Exception):
            raise payload
        return payload
    return _api


def _base(default="alpha"):
    # repo endpoint doit matcher AVANT 'repos/x/...' -> on cible le chemin exact.
    return {"repos/user/nokido": {"default_branch": default}}


def test_main_branche_par_defaut_est_un_bloqueur(monkeypatch):
    m = _mod()
    monkeypatch.setattr(m, "_creds", lambda: "jeton")
    monkeypatch.setattr(m, "_api", _fake_api(_base(default="main")))
    a = m.audit("user/nokido", "main")
    assert a["ok"] and a["faits"]["est_branche_par_defaut"] is True
    assert any("BRANCHE PAR DEFAUT" in b for b in a["bloqueurs"])


def test_protection_absente_404_n_est_pas_un_bloqueur(monkeypatch):
    m = _mod()
    monkeypatch.setattr(m, "_creds", lambda: "jeton")
    # default=alpha, aucune protection/ruleset/PR/hook -> tout 404/vide.
    table = _base(default="alpha")
    table["rulesets"] = []
    table["pulls"] = []
    table["hooks"] = []
    monkeypatch.setattr(m, "_api", _fake_api(table))
    a = m.audit("user/nokido", "main")
    assert a["ok"]
    assert a["faits"]["protection_classique"] is False
    assert a["bloqueurs"] == [], a["bloqueurs"]


def test_ruleset_visant_la_branche_est_un_bloqueur(monkeypatch):
    m = _mod()
    monkeypatch.setattr(m, "_creds", lambda: "jeton")
    table = _base(default="alpha")
    table["rulesets"] = [{"id": 7, "name": "main-protection", "enforcement": "active", "target": "branch"}]
    table["rulesets/7"] = {"conditions": {"ref_name": {"include": ["refs/heads/main"]}}}
    table["pulls"] = []
    table["hooks"] = []
    monkeypatch.setattr(m, "_api", _fake_api(table))
    a = m.audit("user/nokido", "main")
    assert any("PROTEGE" in b for b in a["bloqueurs"]), a["bloqueurs"]
    assert a["faits"]["rulesets_visant_branche"][0]["id"] == 7


def test_PR_ouverte_sur_la_branche_est_un_bloqueur(monkeypatch):
    m = _mod()
    monkeypatch.setattr(m, "_creds", lambda: "jeton")
    table = _base(default="alpha")
    table["rulesets"] = []
    table["pulls"] = [{"number": 42, "title": "wip", "base": {"ref": "main"}, "head": {"ref": "feat"}}]
    table["hooks"] = []
    monkeypatch.setattr(m, "_api", _fake_api(table))
    a = m.audit("user/nokido", "main")
    assert any("PR ouverte" in b for b in a["bloqueurs"]), a["bloqueurs"]
    assert a["faits"]["pr_liees_a_branche"][0]["num"] == 42


def test_token_absent_ne_conclut_pas(monkeypatch):
    m = _mod()
    monkeypatch.setattr(m, "_creds", lambda: None)
    a = m.audit("user/nokido", "main")
    assert a["ok"] is False and "token" in a["motif"].lower()


def test_panne_reseau_sur_le_repo_ne_conclut_pas(monkeypatch):
    m = _mod()
    monkeypatch.setattr(m, "_creds", lambda: "jeton")
    monkeypatch.setattr(m, "_api", _fake_api({"repos/user/nokido": OSError("reseau coupe")}))
    a = m.audit("user/nokido", "main")
    assert a["ok"] is False


def test_webhook_illisible_est_signale_pas_avale(monkeypatch):
    m = _mod()
    monkeypatch.setattr(m, "_creds", lambda: "jeton")

    class _HTTP403(Exception):
        code = 403

    table = _base(default="alpha")
    table["rulesets"] = []
    table["pulls"] = []
    table["hooks"] = _HTTP403("403 forbidden")
    monkeypatch.setattr(m, "_api", _fake_api(table))
    a = m.audit("user/nokido", "main")
    assert isinstance(a["faits"]["webhooks"], str) and "illisible" in a["faits"]["webhooks"]


# ── Pose de protection (ecriture) ────────────────────────────────────────────

def test_protection_est_anti_accident_sans_PR_ni_signatures(monkeypatch):
    """La forme POSTee doit bloquer suppression + force-push, et RIEN de plus :
    un pull_request ou un required_signatures casserait le push direct mono-dev."""
    m = _mod()
    monkeypatch.setattr(m, "_creds", lambda: "jeton")
    monkeypatch.setattr(m, "_get", lambda p, c: (True, []))  # aucun ruleset existant
    captured = {}

    def _post(path, cred, payload):
        captured["path"] = path
        captured["payload"] = payload
        return True, {"id": 99, "name": payload["name"], "enforcement": payload["enforcement"]}

    monkeypatch.setattr(m, "_post", _post)
    r = m.protect_branch("user/nokido", "alpha")
    assert r["ok"] and r["deja_present"] is False and r["ruleset"]["id"] == 99
    types = {rule["type"] for rule in captured["payload"]["rules"]}
    assert types == {"deletion", "non_fast_forward"}, types
    assert "pull_request" not in types and "required_signatures" not in types
    assert captured["payload"]["conditions"]["ref_name"]["include"] == ["refs/heads/alpha"]
    assert captured["payload"]["enforcement"] == "active"


def test_protection_est_idempotente(monkeypatch):
    """Un ruleset du meme nom deja pose -> pas de second POST (sinon doublons)."""
    m = _mod()
    monkeypatch.setattr(m, "_creds", lambda: "jeton")
    monkeypatch.setattr(m, "_get",
                        lambda p, c: (True, [{"id": 7, "name": "alpha-protection-antiaccident"}]))

    def _post_interdit(*a, **k):
        raise AssertionError("POST ne doit PAS etre appele si le ruleset existe deja")

    monkeypatch.setattr(m, "_post", _post_interdit)
    r = m.protect_branch("user/nokido", "alpha")
    assert r["ok"] and r["deja_present"] is True and r["ruleset"]["id"] == 7


def test_protection_POST_refuse_ne_conclut_pas_au_succes(monkeypatch):
    m = _mod()
    monkeypatch.setattr(m, "_creds", lambda: "jeton")
    monkeypatch.setattr(m, "_get", lambda p, c: (True, []))
    monkeypatch.setattr(m, "_post", lambda p, c, payload: (False, "HTTPError: 422 rule invalide"))
    r = m.protect_branch("user/nokido", "alpha")
    assert r["ok"] is False and "422" in r["motif"]


def test_protection_token_absent_ne_pose_rien(monkeypatch):
    m = _mod()
    monkeypatch.setattr(m, "_creds", lambda: None)

    def _post_interdit(*a, **k):
        raise AssertionError("POST ne doit PAS partir sans token")

    monkeypatch.setattr(m, "_post", _post_interdit)
    r = m.protect_branch("user/nokido", "alpha")
    assert r["ok"] is False and "token" in r["motif"].lower()


def test_meta_token_absent_ne_conclut_pas(monkeypatch):
    m = _mod()
    monkeypatch.setattr(m, "_creds", lambda: None)
    r = m.meta("user/nokido")
    assert r["ok"] is False and "token" in r["motif"].lower()


def test_set_meta_token_absent_ne_conclut_pas(monkeypatch):
    m = _mod()
    monkeypatch.setattr(m, "_creds", lambda: None)
    r = m.set_meta("user/nokido", description="x")
    assert r["ok"] is False and "token" in r["motif"].lower()
