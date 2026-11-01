"""NR -- worker ACP : un job non authentifie NE S'EXECUTE PAS. JWS EdDSA, cle GENEREE, faux agent, tmp_path."""
from __future__ import annotations

import base64
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import acp_worker_faux as F  # noqa: E402


@pytest.fixture
def env(tmp_path):
    rt = F.routeur(tmp_path)
    yield tmp_path, rt, F.worker(tmp_path, rt)
    F.fermer_tout(rt)


def _res(tmp_path, jid):
    return json.loads((tmp_path / "jobs" / f"{jid}.result.json").read_text(encoding="utf-8"))


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _fabriquer(tmp_path, header, corps, priv=F.PRIV, jid=None):
    """JWS compact maison (pour fabriquer les cas hostiles) ; ecrit le fichier job."""
    jid = jid or corps["id"]
    h = _b64(json.dumps(header, separators=(",", ":")).encode())
    p = _b64(json.dumps(corps, sort_keys=True, separators=(",", ":")).encode())
    sig = priv.sign((h + "." + p).encode()) if priv is not None else b""
    d = tmp_path / "jobs"
    d.mkdir(exist_ok=True)
    (d / f"{jid}.json").write_text(h + "." + p + "." + _b64(sig), encoding="utf-8")
    return jid


def _corps(jid="b" * 32, **kw):
    c = {"id": jid, "op": "lister", "params": {}, "ts": time.time(), "nonce": "n-" + jid[:6]}
    c.update(kw)
    return c


def test_color():
    assert F.W.__FORGE_COLOR__


def test_job_valide_accepte(env):
    tmp_path, rt, wk = env
    jid = F.deposer(tmp_path, "lister")
    txt = (tmp_path / "jobs" / f"{jid}.json").read_text(encoding="utf-8")
    assert txt.count(".") == 2
    assert json.loads(_unb64(txt.split(".")[0])) == {"alg": "EdDSA", "kid": F.KID}
    F.attendre(tmp_path, wk, jid)
    assert _res(tmp_path, jid)["ok"] is True


def test_resultat_sans_hmac(env):
    tmp_path, rt, wk = env
    jid = F.deposer(tmp_path, "lister")
    F.attendre(tmp_path, wk, jid)
    assert "sig" not in _res(tmp_path, jid)


def test_job_non_signe_refuse(env):
    tmp_path, rt, wk = env
    jid = "a" * 32
    (tmp_path / "jobs").mkdir()
    (tmp_path / "jobs" / f"{jid}.json").write_text(json.dumps(_corps(jid)), encoding="utf-8")
    wk.scan()
    r = _res(tmp_path, jid)
    assert r["ok"] is False and r["refus"]
    assert F.resultat(tmp_path, jid)["etat"] == "ACHIEVED"


def test_mauvaise_cle_refusee(env):
    tmp_path, rt, wk = env
    autre, _, _ = F.nouvelle_cle()
    jid = F.deposer(tmp_path, "ouvrir", cle=(autre, F.KID), agent="codex")
    wk.scan()
    assert _res(tmp_path, jid)["ok"] is False
    assert rt.lister() == []


def test_kid_inconnu_refuse(env):
    tmp_path, rt, wk = env
    jid = F.deposer(tmp_path, "ouvrir", cle=(F.PRIV, "autre-kid"), agent="codex")
    wk.scan()
    assert _res(tmp_path, jid)["ok"] is False
    assert rt.lister() == []


def test_alg_none_refuse(env):
    tmp_path, rt, wk = env
    jid = _fabriquer(tmp_path, {"alg": "none", "kid": F.KID}, _corps(op="ouvrir", params={"agent": "codex"}), priv=None)
    wk.scan()
    assert _res(tmp_path, jid)["ok"] is False
    assert rt.lister() == []


def test_alg_hs256_refuse(env):
    tmp_path, rt, wk = env
    import hashlib
    import hmac
    corps = _corps(op="ouvrir", params={"agent": "codex"})
    h = _b64(json.dumps({"alg": "HS256", "kid": F.KID}).encode())
    p = _b64(json.dumps(corps).encode())
    pub = F.EPINGLE[F.KID]  # confusion d'algorithme : HMAC avec la cle publique comme secret
    sig = hmac.new(pub, (h + "." + p).encode(), hashlib.sha256).digest()
    (tmp_path / "jobs").mkdir()
    (tmp_path / "jobs" / f"{corps['id']}.json").write_text(h + "." + p + "." + _b64(sig), encoding="utf-8")
    wk.scan()
    assert _res(tmp_path, corps["id"])["ok"] is False
    assert rt.lister() == []


def test_corps_altere_apres_signature_refuse(env):
    tmp_path, rt, wk = env
    jid = F.deposer(tmp_path, "ouvrir", agent="codex")
    p = tmp_path / "jobs" / f"{jid}.json"
    h, c, s = p.read_text(encoding="utf-8").split(".")
    corps = json.loads(_unb64(c))
    corps["params"]["agent"] = "claude"
    p.write_text(h + "." + _b64(json.dumps(corps, sort_keys=True, separators=(",", ":")).encode()) + "." + s,
                 encoding="utf-8")
    wk.scan()
    assert _res(tmp_path, jid)["ok"] is False
    assert rt.lister() == []


def test_rejeu_refuse_meme_apres_redemarrage(env):
    tmp_path, rt, wk = env
    jid = F.deposer(tmp_path, "lister")
    copie = (tmp_path / "jobs" / f"{jid}.json").read_text(encoding="utf-8")
    wk.scan()
    F.attendre(tmp_path, wk, jid)
    assert _res(tmp_path, jid)["ok"] is True
    for suf in (".started", ".done", ".result.json"):
        (tmp_path / "jobs" / f"{jid}{suf}").unlink()
    (tmp_path / "jobs" / f"{jid}.json").write_text(copie, encoding="utf-8")
    wk2 = F.worker(tmp_path, rt)  # nouveau processus : le registre de nonces est persiste
    wk2.scan()
    r = _res(tmp_path, jid)
    assert r["ok"] is False and "rejeu" in r["refus"]


def test_job_perime_refuse(tmp_path):
    rt = F.routeur(tmp_path)
    wk = F.worker(tmp_path, rt, now=lambda: time.time() + 1000.0)
    jid = F.deposer(tmp_path, "lister")
    wk.scan()
    r = _res(tmp_path, jid)
    assert r["ok"] is False and "perime" in r["refus"]


def test_sans_epingle_tout_est_refuse(tmp_path):
    rt = F.routeur(tmp_path)
    jid = F.deposer(tmp_path, "lister")
    wk = F.worker(tmp_path, rt, epingle=None)
    wk.scan()
    assert _res(tmp_path, jid)["ok"] is False


def test_aucun_get_secret_cote_worker(env, monkeypatch):
    tmp_path, rt, wk = env
    appels = []
    import types
    faux = types.ModuleType("forge_secrets")
    faux.get_secret = lambda *a, **k: appels.append(a) or None
    for nom in ("forge_secrets", "nokido_agent.app.forge_secrets"):
        monkeypatch.setitem(sys.modules, nom, faux)
    jid = F.deposer(tmp_path, "lister")
    F.attendre(tmp_path, wk, jid)
    assert _res(tmp_path, jid)["ok"] is True
    assert appels == []
    assert "get_secret" not in Path(F.W.__file__).read_text(encoding="utf-8")


def test_epingle_lue_au_coffre_personnel(monkeypatch):
    pin = {"kid": F.KID, "x": _b64(F.EPINGLE[F.KID])}
    monkeypatch.setattr(F.W, "_lire_coffre_personnel", lambda nom: json.dumps(pin))
    assert F.W.epingle_coffre() == F.EPINGLE
    monkeypatch.setattr(F.W, "_lire_coffre_personnel", lambda nom: None)
    assert F.W.epingle_coffre() is None
    monkeypatch.setattr(F.W, "_lire_coffre_personnel", lambda nom: "pas du json")
    assert F.W.epingle_coffre() is None


def test_cwd_hors_worktree_refuse(env):
    tmp_path, rt, wk = env
    jid = F.deposer(tmp_path, "ouvrir", agent="codex", cwd=str(tmp_path / "ailleurs"))
    wk.scan()
    F.attendre(tmp_path, wk, jid)
    r = _res(tmp_path, jid)
    assert r["ok"] is False and "cwd" in r["refus"]
    assert rt.lister() == []


def test_cwd_du_worktree_accepte_et_impose(env):
    tmp_path, rt, wk = env
    jid = F.deposer(tmp_path, "ouvrir", agent="codex", cwd=rt._route("codex"))
    F.attendre(tmp_path, wk, jid)
    r = _res(tmp_path, jid)
    assert r["ok"] is True
    assert "acp_codex" in rt.lister()[0]["cwd"]


def test_mode_non_sur_refuse(env):
    tmp_path, rt, wk = env
    jid = F.deposer(tmp_path, "ouvrir", agent="codex", mode="full-access")
    F.attendre(tmp_path, wk, jid)
    r = _res(tmp_path, jid)
    assert r["ok"] is False and "mode" in r["refus"]
    assert rt.lister() == []


def test_op_inconnue_refusee_et_cle_jamais_ecrite(env):
    tmp_path, rt, wk = env
    jid = F.deposer(tmp_path, "supprimer_tout")
    F.attendre(tmp_path, wk, jid)
    assert _res(tmp_path, jid)["ok"] is False
    brut = F.PRIV.private_bytes(F.serialization.Encoding.Raw, F.serialization.PrivateFormat.Raw,
                                F.serialization.NoEncryption())
    for p in (tmp_path / "jobs").iterdir():
        assert _b64(brut) not in p.read_text(encoding="utf-8")
