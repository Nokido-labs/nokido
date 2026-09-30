# -*- coding: utf-8 -*-
"""NR — routes d'administration : un ORGANE doit prouver la possession de sa cle TPM.

Chantier d'authentification, 24/09. Contrat :
  - OBSERVATION (defaut) : rien n'est refuse, TOUT est journalise (mesurer avant d'armer) ;
  - APPLIQUE (LAFORGE_ADMIN_TPM_ENFORCE=1, geste owner) : sans preuve LIEE a l'empreinte
    ENREGISTREE -> refus ; preuve liee -> accepte ; empreinte non enregistree -> refus
    (UNKNOWN = DENY) ;
  - le hub appelle cette decision au point ou il accepte le jeton propre d'un organe ;
  - le superviseur pose une preuve NEUVE par appel admin, et son repli sur le maitre
    s'annonce MASTER (AUTH-2).
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT / "app"), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_dpop as d  # noqa: E402

CHEMIN = "/admin/run_job"
JETON = "s" * 64


@pytest.fixture
def cle(monkeypatch, tmp_path):
    from cryptography.hazmat.primitives.asymmetric import ec
    k = ec.generate_private_key(ec.SECP256R1())
    monkeypatch.setattr(d, "_journal_admin_path", lambda: tmp_path / "authz_tpm_admin.jsonl")
    monkeypatch.setattr(d, "jkt_tpm_enregistre", lambda agent: d.thumbprint(d.jwk_public(k)))
    return k


def _journal(tmp_path):
    p = tmp_path / "authz_tpm_admin.jsonl"
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def test_observation_laisse_passer_et_journalise(cle, tmp_path):
    r = d.decision_admin_tpm("", "POST", CHEMIN, "SUPERVISOR", JETON, environ={})
    assert r["autorise"] and r["etat"] == "INVERIFIABLE" and not r["applique"]
    assert _journal(tmp_path)[-1]["etat"] == "INVERIFIABLE"


def test_applique_refuse_sans_preuve(cle):
    r = d.decision_admin_tpm("", "POST", CHEMIN, "SUPERVISOR", JETON,
                             environ={"LAFORGE_ADMIN_TPM_ENFORCE": "1"})
    assert not r["autorise"]


def test_applique_accepte_une_preuve_liee(cle):
    p = d.creer_preuve("POST", "http://127.0.0.1:8766" + CHEMIN, JETON, cle=cle)
    r = d.decision_admin_tpm(p, "POST", CHEMIN, "SUPERVISOR", JETON,
                             environ={"LAFORGE_ADMIN_TPM_ENFORCE": "1"})
    assert r["autorise"] and r["etat"] == "LIEE", r


def test_applique_refuse_une_autre_cle(cle):
    p = d.creer_preuve("POST", "http://127.0.0.1:8766" + CHEMIN, JETON)   # cle logicielle etrangere
    r = d.decision_admin_tpm(p, "POST", CHEMIN, "SUPERVISOR", JETON,
                             environ={"LAFORGE_ADMIN_TPM_ENFORCE": "1"})
    assert not r["autorise"] and r["etat"] == "REFUSEE"


def test_applique_refuse_si_aucune_empreinte_enregistree(monkeypatch, tmp_path):
    monkeypatch.setattr(d, "_journal_admin_path", lambda: tmp_path / "j.jsonl")
    monkeypatch.setattr(d, "jkt_tpm_enregistre", lambda agent: None)
    r = d.decision_admin_tpm("x.y.z", "POST", CHEMIN, "SUPERVISOR", JETON,
                             environ={"LAFORGE_ADMIN_TPM_ENFORCE": "1"})
    assert not r["autorise"] and r["etat"] == "NON_ENREGISTRE"


def _cli():
    if str(ROOT / "tools") not in sys.path:
        sys.path.insert(0, str(ROOT / "tools"))
    import forge_dpop_tpm_cli  # noqa: PLC0415
    return forge_dpop_tpm_cli


def test_cli_sans_credential_n_ecrit_rien(monkeypatch, capsys):
    from nokido_agent.app import forge_secrets as s
    monkeypatch.setattr(s, "get_secret", lambda k: None)
    rc = _cli().main(["--agent", "SUPERVISOR", "--htm", "POST",
                      "--htu", "http://127.0.0.1:8766" + CHEMIN])
    sortie = capsys.readouterr()
    assert rc != 0 and sortie.out == "", "aucune preuve partielle ne doit sortir"


def test_cli_emet_une_preuve_que_le_hub_accepte(cle, monkeypatch, capsys):
    """Effet du CLI par le chemin reel de la decision : sa sortie est une preuve LIEE."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    from nokido_agent.app import forge_persona_tpm as tpm
    from nokido_agent.app import forge_secrets as s

    def _signe(agent, donnees):
        r, t = decode_dss_signature(cle.sign(donnees, ec.ECDSA(hashes.SHA256())))
        return r.to_bytes(32, "big") + t.to_bytes(32, "big")

    monkeypatch.setattr(s, "get_secret", lambda k: JETON if k == "FORGE_TOKEN_SUPERVISOR" else None)
    monkeypatch.setattr(tpm, "sign_as", _signe)
    monkeypatch.setattr(tpm, "cle_publique_jwk_agent", lambda a: (d.jwk_public(cle), ""))
    rc = _cli().main(["--agent", "SUPERVISOR", "--htm", "POST",
                      "--htu", "http://127.0.0.1:8766" + CHEMIN])
    preuve = capsys.readouterr().out
    assert rc == 0 and preuve.count(".") == 2
    r = d.decision_admin_tpm(preuve, "POST", CHEMIN, "SUPERVISOR", JETON,
                             environ={"LAFORGE_ADMIN_TPM_ENFORCE": "1"})
    assert r["autorise"] and r["etat"] == "LIEE", r


# ── SANS PIPE (2026-09-24) : pool bloquant du superviseur sature par ~67 pipes d'enfants ──
def test_cli_sortie_fichier_ecrit_la_preuve_et_rien_sur_stdout(cle, monkeypatch, capsys, tmp_path):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    from nokido_agent.app import forge_persona_tpm as tpm
    from nokido_agent.app import forge_secrets as s

    def _signe(agent, donnees):
        r, t = decode_dss_signature(cle.sign(donnees, ec.ECDSA(hashes.SHA256())))
        return r.to_bytes(32, "big") + t.to_bytes(32, "big")

    monkeypatch.setattr(s, "get_secret", lambda k: JETON if k == "FORGE_TOKEN_SUPERVISOR" else None)
    monkeypatch.setattr(tpm, "sign_as", _signe)
    monkeypatch.setattr(tpm, "cle_publique_jwk_agent", lambda a: (d.jwk_public(cle), ""))
    f = tmp_path / "preuve.tmp"
    rc = _cli().main(["--agent", "SUPERVISOR", "--htm", "POST",
                      "--htu", "http://127.0.0.1:8766" + CHEMIN, "--sortie", str(f)])
    assert rc == 0 and capsys.readouterr().out == ""
    r = d.decision_admin_tpm(f.read_text(encoding="ascii"), "POST", CHEMIN, "SUPERVISOR", JETON,
                             environ={"LAFORGE_ADMIN_TPM_ENFORCE": "1"})
    assert r["etat"] == "LIEE", r


def test_cli_sortie_echec_ecrit_le_motif_et_aucune_preuve(monkeypatch, tmp_path):
    from nokido_agent.app import forge_secrets as s
    monkeypatch.setattr(s, "get_secret", lambda k: None)
    f = tmp_path / "preuve.tmp"
    rc = _cli().main(["--agent", "SUPERVISOR", "--htm", "POST",
                      "--htu", "http://127.0.0.1:8766" + CHEMIN, "--sortie", str(f)])
    assert rc != 0 and not f.exists()
    assert "absent du coffre" in (tmp_path / "preuve.tmp.err").read_text(encoding="utf-8")


def test_cli_sortie_refuse_un_fichier_existant(cle, monkeypatch, tmp_path):
    """Creation EXCLUSIVE : le CLI n'ecrase jamais un fichier qu'il n'a pas cree."""
    from nokido_agent.app import forge_secrets as s
    monkeypatch.setattr(s, "get_secret", lambda k: JETON if k == "FORGE_TOKEN_SUPERVISOR" else None)
    f = tmp_path / "preuve.tmp"
    f.write_text("autrui", encoding="utf-8")
    rc = _cli().main(["--agent", "SUPERVISOR", "--htm", "POST",
                      "--htu", "http://127.0.0.1:8766" + CHEMIN, "--sortie", str(f)])
    assert rc != 0 and f.read_text(encoding="utf-8") == "autrui"


def _corps_ts(nom: str, n: int = 2600) -> str:
    src = (ROOT / "proxy_deno" / "core" / "supervisor.ts").read_text(encoding="utf-8", errors="replace")
    i = src.index("async function %s(" % nom)
    return src[i:i + n]


def test_le_superviseur_ne_lit_plus_la_preuve_par_un_pipe():
    corps = _corps_ts("_preuveDpopTpm")
    assert '"--sortie"' in corps and 'stdout: "null"' in corps and 'stderr: "null"' in corps
    assert ".output()" not in corps, "un pipe lu occupe le pool bloquant sature"
    assert "readTextFileSync" in corps and "removeSync" in corps


def test_l_etat_circadien_s_ecrit_en_synchrone_et_atomique():
    corps = _corps_ts("saveCircadianState", 900)
    assert "writeTextFileSync" in corps and "renameSync" in corps
    assert "await Deno.writeTextFile(" not in corps, "ecriture asynchrone : fichier tronque puis suspendu"


def test_un_etat_circadien_illisible_n_est_pas_un_etat_vierge():
    corps = _corps_ts("loadCircadianState", 1400)
    assert "ILLISIBLE" in corps and "neutralisee" in corps


def test_le_hub_appelle_la_decision_au_point_d_acceptation():
    src = (ROOT / "tools" / "nokido_hub.py").read_text(encoding="utf-8", errors="replace")
    i = src.find("def _admin_tok_ok(")
    corps = src[i:i + 9000]
    assert "decision_admin_tpm" in corps, "le hub n'appelle pas la politique TPM sur les routes admin"
    assert 'request.scope["path"]' in corps, "le chemin doit venir du scope (CVE-2026-48710)"


def test_le_superviseur_prouve_chaque_appel_admin():
    src = (ROOT / "proxy_deno" / "core" / "supervisor.ts").read_text(encoding="utf-8", errors="replace")
    assert src.count('_entetesAdminAvecPreuve("POST", "/admin/run_job")') >= 2
    assert 'h["LaForge-Agent-Name"] = "MASTER"' in src, "repli maitre non annonce MASTER"


def test_chaque_appel_du_superviseur_vers_une_route_admin_porte_la_preuve():
    """EXHAUSTIF (2026-09-24) : toute route du hub gardee par `_admin_tok_ok` que le
    superviseur appelle doit etre precedee de `_entetesAdminAvecPreuve`. Mesure qui l'exige :
    `/api/maintenance/gc` partait SANS preuve (INVERIFIABLE a 17:01:09) -- avec
    LAFORGE_ADMIN_TPM_ENFORCE=1 le GC glymphatique aurait pris 401, sans qu'un test
    ne le dise, puisque le precedent ne comptait que les appels deja prouves."""
    import re

    sys.path.insert(0, str(ROOT / "tools"))
    import forge_route_authz_audit as audit  # noqa: PLC0415

    src_hub = audit.HUB.read_text(encoding="utf-8", errors="replace")
    idx, lignes = audit._handlers(src_hub)
    admin = {r["route"] for r in audit.auditer(avec_appelants=False)["routes"]
             if "_admin_tok_ok" in (audit._corps(r["handler"], idx, lignes) or "")}
    assert "/admin/run_job" in admin and "/api/maintenance/gc" in admin, sorted(admin)[:10]
    sup = (ROOT / "proxy_deno" / "core" / "supervisor.ts").read_text(encoding="utf-8").splitlines()
    fautes, vus = [], 0
    for i, ligne in enumerate(sup):
        m = re.search(r":8766(/[A-Za-z0-9_/\-]+)", ligne)
        if not m or ligne.strip().startswith("//") or m.group(1) not in admin:
            continue
        vus += 1
        if "_entetesAdminAvecPreuve(" not in "\n".join(sup[max(0, i - 4):i]):
            fautes.append("supervisor.ts:%d %s" % (i + 1, m.group(1)))
    assert vus >= 3, "moins d'appels admin vus que mesure (3) : le detecteur ne lit plus le fichier"
    assert not fautes, "appel(s) admin SANS preuve TPM : %s" % fautes


def test_la_preuve_tpm_du_superviseur_est_bornee_dans_le_temps():
    """Regression mesuree le 2026-09-24 : sans `signal`, le CLI de preuve pouvait ne jamais
    rendre la main et suspendait les appels admin de NREM1 SANS une ligne de journal
    (0 appel en 35 min apres deux declenchements). La borne rend l'echec VISIBLE."""
    src = (ROOT / "proxy_deno" / "core" / "supervisor.ts").read_text(encoding="utf-8", errors="replace")
    i = src.index("async function _preuveDpopTpm(")
    corps = src[i:i + 1600]
    assert "signal: AbortSignal.timeout(" in corps, "preuve TPM sans borne de temps"
    assert 'stdin: "null"' in corps, "le CLI pourrait attendre une entree qui ne viendra jamais"
    assert "delai depasse" in corps, "un depassement doit se dire, pas se confondre avec un refus"
