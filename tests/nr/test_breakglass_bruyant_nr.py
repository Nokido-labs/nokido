"""Non-regression : le breakglass est BRUYANT, CONDITIONNEL, et BORNE.

`LAFORGE_AUTHORITY_BYPASS=true` desactive le garde d'autorite. La porte de secours
est legitime -- l'owner doit pouvoir reprendre la main sur son propre systeme.
Ce qui ne l'etait pas : elle rendait `ok` SANS AUCUNE TRACE. On l'a decouverte par
audit, c'est-a-dire trop tard. Un contournement qu'il faut chercher pour voir n'est
pas un contournement surveille.

Trois invariants testes ici, et le troisieme est le plus important :

  1. actif  -> JOURNALISE a chaque appel (qui, et dans quel etat d'exposition) ;
  2. hub expose hors loopback -> REFUSE : une porte de secours locale n'a aucune
     raison d'exister sur un hub joignable depuis le reseau ;
  3. il franchit `_check_authority` et RIEN D'AUTRE. `_require_capability` (jeton
     HMAC) reste exige -- les arguments nomment, le token decide, et un breakglass
     ne renverse pas cette regle.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT / "app"))

mst = pytest.importorskip(
    "mcp_server_tools",
    reason="mcp_server_tools non importable ici : l'essai n'est pas MENE, "
           "ce qui n'est pas la meme chose qu'un succes")
import forge_bind_guard as bg  # noqa: E402


@pytest.fixture()
def journal(monkeypatch):
    """Capte ce que le breakglass ecrit -- c'est l'objet meme du test."""
    lignes = []
    monkeypatch.setattr(mst, "_authority_log",
                        lambda ev, agent, detail="": lignes.append((ev, agent, detail)))
    return lignes


def _expose(monkeypatch, etat):
    monkeypatch.setattr(bg, "verdict",
                        lambda port: {"etat": etat, "adresses": ["0.0.0.0"]
                                      if etat == "EXPOSE" else ["127.0.0.1"]})


# --------------------------------------------------------------------------- #
# 1. Bruyant
# --------------------------------------------------------------------------- #

def test_le_breakglass_actif_laisse_une_trace(monkeypatch, journal):
    """LE defaut d'origine : il rendait ok sans rien dire."""
    monkeypatch.setenv("LAFORGE_AUTHORITY_BYPASS", "true")
    _expose(monkeypatch, "LOOPBACK")
    r = mst._check_authority("VIBE")
    assert r["ok"] is True and r["level"] == "BYPASS"
    assert journal, "le breakglass est passe SANS TRACE"
    ev, agent, _ = journal[-1]
    assert ev == "BREAKGLASS_ACTIF"
    assert agent == "VIBE", "la trace doit nommer l'appelant"


def test_il_trace_a_CHAQUE_appel_pas_une_seule_fois(monkeypatch, journal):
    monkeypatch.setenv("LAFORGE_AUTHORITY_BYPASS", "true")
    _expose(monkeypatch, "LOOPBACK")
    for _ in range(3):
        mst._check_authority("VIBE")
    assert len(journal) == 3, journal


def test_un_appelant_anonyme_est_nomme_UNKNOWN(monkeypatch, journal):
    monkeypatch.setenv("LAFORGE_AUTHORITY_BYPASS", "true")
    _expose(monkeypatch, "LOOPBACK")
    mst._check_authority("")
    assert journal[-1][1] == "UNKNOWN", "un vide ne doit pas effacer l'appelant"


# --------------------------------------------------------------------------- #
# 2. Conditionnel a la topologie
# --------------------------------------------------------------------------- #

def test_le_breakglass_est_REFUSE_si_le_hub_est_expose(monkeypatch, journal):
    """Une porte de secours LOCALE n'a pas lieu d'etre sur un hub joignable."""
    monkeypatch.setenv("LAFORGE_AUTHORITY_BYPASS", "true")
    _expose(monkeypatch, "EXPOSE")
    r = mst._check_authority("VIBE")
    assert r["ok"] is False
    assert r["level"] == "BYPASS_REFUSE"
    assert journal[-1][0] == "BREAKGLASS_REFUSE", "le refus aussi doit se voir"


def test_un_etat_d_exposition_INCONNU_ne_bloque_pas_la_porte_de_secours(monkeypatch, journal):
    """Choix ASSUME : si l'on ne sait pas, on laisse passer et on le DIT.

    Refuser sur INCONNU condamnerait l'owner a rester dehors le jour ou la sonde
    est aveugle -- or une porte de secours doit fonctionner justement quand le
    reste va mal. La trace porte l'etat, donc la cecite reste visible.
    """
    monkeypatch.setenv("LAFORGE_AUTHORITY_BYPASS", "true")
    _expose(monkeypatch, "INCONNU")
    r = mst._check_authority("VIBE")
    assert r["ok"] is True
    assert "INCONNU" in journal[-1][2]


def test_la_sonde_qui_leve_ne_casse_pas_le_breakglass(monkeypatch, journal):
    monkeypatch.setenv("LAFORGE_AUTHORITY_BYPASS", "true")

    def _boum(port):
        raise RuntimeError("psutil hs")

    monkeypatch.setattr(bg, "verdict", _boum)
    r = mst._check_authority("VIBE")
    assert r["ok"] is True, "la porte de secours doit survivre a une sonde cassee"


# --------------------------------------------------------------------------- #
# 3. Borne : il ne franchit PAS la capability
# --------------------------------------------------------------------------- #

def test_le_breakglass_ne_franchit_PAS_la_capability(monkeypatch):
    """L'invariant central. `_require_capability` verifie un jeton HMAC ; le
    breakglass n'y touche pas, meme actif."""
    monkeypatch.setenv("LAFORGE_AUTHORITY_BYPASS", "true")
    r = mst._require_capability("jeton-invente", "system", "audit_view", "VIBE")
    assert r.get("ok") is not True, (
        "le breakglass a franchi la verification capability : "
        "les arguments nomment, le token decide -- cette regle ne se contourne pas")


def test_le_bypass_n_existe_qu_a_UN_endroit():
    """S'il se duplique, chaque copie devient un contournement a surveiller."""
    src = (ROOT / "app" / "mcp_server_tools.py").read_text(encoding="utf-8",
                                                           errors="replace")
    assert src.count('os.environ.get("LAFORGE_AUTHORITY_BYPASS"') == 1, (
        "le breakglass est teste a plusieurs endroits : un seul point de "
        "contournement, sinon la surveillance est incomplete")


def test_sans_la_variable_le_garde_normal_s_applique(monkeypatch, journal):
    """Le chemin normal est DOUBLE, et ce n'est pas du confort.

    MESURE 2026-09-02 : appeler le vrai `check_write_permission` fige le test sur
    `forge_agent_authority.get_level()`, ligne `with self._lock:` -- un verrou
    tenu. Un test qui attend un verrou de production n'est pas hermetique, et il
    bloquerait la CI entiere. Le fait est CONSIGNE comme dette a instruire : si
    ce verrou peut retenir un test, il peut retenir un appel de tool.
    """
    monkeypatch.delenv("LAFORGE_AUTHORITY_BYPASS", raising=False)
    # Le double se pose sur le MODULE SOURCE, pas sur `mst` : `_check_authority`
    # fait `from forge_agent_authority import check_write_permission` DANS la
    # fonction, donc un double pose sur l'appelant n'est jamais celui qu'il
    # resout. Piege deja paye deux fois cette nuit (forge_cli_swarm._one,
    # mcp_server_tools.router_call) -- un test qui n'atteint pas sa source ne
    # valide rien, et ici il FIGEAIT sur un verrou de production.
    import forge_agent_authority as faa
    monkeypatch.setattr(faa, "check_write_permission",
                        lambda agent: {"ok": False, "level": "READ_ONLY",
                                       "reason": "double de test"})
    r = mst._check_authority("VIBE")
    assert r.get("level") != "BYPASS"
    assert not [j for j in journal if j[0].startswith("BREAKGLASS")], (
        "aucune trace de breakglass ne doit apparaitre quand il est inactif")
