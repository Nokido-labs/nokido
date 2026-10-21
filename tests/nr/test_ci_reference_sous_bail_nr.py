"""NR -- la CI de reference joue ses etages SOUS BAIL DE PRIORITE, sous son identite propre (16/10).

RED ecrit par Claude. Mesure 16/10 : le bail de priorite est ARME depuis le 14/10 (sandbox/bail_priorite.switch)
mais AUCUN bail n'a jamais ete pris -- la CI de reference, son client prevu par la docstring
(`with bail_priorite("CI de reference ...")`), ne l'appelait pas, et elle n'avait aucune identite d'organe :
arme, le bail exige ring <= 3 et un appel sans nom recoit 403 (mesure 2026-10-06). Decision owner 16/10
(forme a) : identite CI_REFERENCE ring 2, jeton propre au coffre. Le nom passe EXPLICITEMENT a la demande,
jamais par l'environnement : les etages pytest l'heriteraient et parleraient au hub sous l'identite de la CI.
"""
from __future__ import annotations

import contextlib
import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_ci_reference as C  # noqa: E402


def _executeur(journal, rc_ci_local=0):
    def executer(cmd, **_k):
        est_ci = "tools/ci_local.py" in cmd
        journal.append(("exec", "ci_local" if est_ci else "autre"))
        return types.SimpleNamespace(returncode=rc_ci_local if est_ci else 0,
                                     stdout="Tous les gates bloquants passent", stderr="")
    return executer


def _faux_bail(journal):
    @contextlib.contextmanager
    def bail(sha):
        journal.append(("bail+", sha))
        try:
            yield {"ok": True}
        finally:
            journal.append(("bail-", sha))
    return bail


def test_ci_reference_est_une_identite_d_organe_ring_2():
    d = json.loads((ROOT / "config" / "agent_identities.json").read_text(encoding="utf-8"))
    agents = d.get("agents") if isinstance(d.get("agents"), dict) else d
    ent = agents.get("CI_REFERENCE")
    assert ent, "CI_REFERENCE absente du registre : la CI demanderait le bail sans nom -> 403 (bail arme)"
    assert ent.get("ring") == 2, ent.get("ring")


def test_les_etages_se_jouent_sous_le_bail_de_la_ci(tmp_path):
    journal = []
    rc = C.main(["--sha", "abc123", "--dossier", str(tmp_path)], executer=_executeur(journal),
                bail=_faux_bail(journal))
    assert rc == 0
    etages = [i for i, e in enumerate(journal) if e == ("exec", "ci_local")]
    debut, fin = journal.index(("bail+", "abc123")), journal.index(("bail-", "abc123"))
    assert etages and debut < min(etages) and max(etages) < fin, journal


def test_le_bail_est_rendu_meme_si_les_gates_sont_rouges(tmp_path):
    journal = []
    rc = C.main(["--sha", "abc123", "--deux-etages", "--dossier", str(tmp_path)],
                executer=_executeur(journal, rc_ci_local=1), bail=_faux_bail(journal))
    assert rc == 1 and ("bail-", "abc123") in journal, journal


def test_la_demande_de_bail_porte_l_identite_de_la_ci(monkeypatch):
    import nokido_agent.app.forge_resource_manager as rm

    vus = []
    monkeypatch.setattr(rm, "demander_bail",
                        lambda action, agent=None, **ch: vus.append((action, agent, ch)) or {"ok": True, "bail": {"id": "b1"}})
    with C._bail("abc123def456"):
        pass
    assert [a for a, _ag, _ch in vus] == ["acquerir", "liberer"], vus
    assert all(ag == "CI_REFERENCE" for _a, ag, _ch in vus), vus
    assert "abc123def456" in vus[0][2].get("motif", ""), vus


def test_le_journal_du_bail_dit_son_mode_reel():
    """Premier bail reel (16/10, bail_1792179376_d5f27c) : mode ARME sur disque, journal « (observation) » -- la ligne
    lisait un champ `arme` absent ; le bail porte `mode`. Un journal qui ment sur l'etat est pire que pas de journal."""
    assert "ARME" in C._dire_bail({"ok": True, "bail": {"id": "b1", "mode": "ARME"}})
    assert "OBSERVATION" in C._dire_bail({"ok": True, "bail": {"id": "b1", "mode": "OBSERVATION"}})
    assert "INCONNU" in C._dire_bail({"ok": True, "bail": {"id": "b1"}})


def test_demander_bail_presente_le_nom_explicite_et_non_l_environnement(monkeypatch):
    import urllib.request

    import nokido_agent.app.forge_hub_client as hc
    import nokido_agent.app.forge_resource_manager as rm

    noms = []
    monkeypatch.setenv("LAFORGE_AGENT_NAME", "AUTRE_ORGANE")
    monkeypatch.setattr(hc, "entetes_organe", lambda nom: noms.append(nom) or {"Content-Type": "application/json"})

    def _injoignable(*_a, **_k):
        raise OSError("hub coupe pour le test")

    monkeypatch.setattr(urllib.request, "urlopen", _injoignable)
    r = rm.demander_bail("acquerir", agent="CI_REFERENCE", motif="x")
    assert noms == ["CI_REFERENCE"], noms
    assert r.get("ok") is False and "INJOIGNABLE" in str(r.get("error")), r
