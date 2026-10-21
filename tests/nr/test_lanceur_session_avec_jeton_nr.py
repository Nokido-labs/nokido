"""NR -- le lanceur interactif cherche une session QUI A un jeton (racine R6, 17/10).

Mesure 17/10 : veille du poste 05:46 -> reveil 10:11 (journal System, Power-Troubleshooter) ; la relance des 4
executeurs runAs=interactive echoue : « WTSQueryUserToken(sid=3) a echoue (1008, jeton inexistant) et le repli
CreateProcess est REFUSE ». app/forge_sandbox_exec.spawn_as_interactive_jobbed prenait la PREMIERE session active puis,
a defaut, la console ; sans jeton sur celle-la (1008 = ERROR_NO_TOKEN), il echouait sans essayer les autres.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from nokido_agent.app import forge_provider_admin as PA  # noqa: E402
from nokido_agent.app import forge_sandbox_exec as S  # noqa: E402


@pytest.fixture(autouse=True)
def _depot_sous_un_profil_fictif(monkeypatch):
    """CI GitHub 17/10 (run 39064361155, sha 7661a3220) : runner hors C:\\Users\\<compte> -> _compte_owner() = None
    -> 5 rouges, alors que la logique est juste (fail-closed). Le NR fixe un profil FICTIF : il teste la logique, jamais
    la machine qui le joue (meme famille que « le distribuable ne doit pas etre fige sur l'owner »)."""
    monkeypatch.setattr(PA, "__file__", r"C:\Users\proprio\Script python IA\Nokido\app\forge_provider_admin.py")


class FauxTS:
    """win32ts minimal : sessions enumerees + jetons par session (absent = 1008) + proprietaire de chaque session."""

    WTS_CURRENT_SERVER_HANDLE = 0
    WTSUserName = 5

    def __init__(self, sessions, jetons, console=0xFFFFFFFF, comptes=None):
        self._sessions, self._jetons, self._console = sessions, jetons, console
        self._comptes = comptes  # None = tout appartient a l'owner (cas mono-utilisateur des tests d'origine)

    def WTSQuerySessionInformation(self, serveur, sid, classe):
        if self._comptes is None:
            return S._compte_owner()
        if sid not in self._comptes:
            raise OSError(5, "WTSQuerySessionInformation", "acces refuse")
        return self._comptes[sid]

    def WTSEnumerateSessions(self):
        return [{"SessionId": sid, "State": etat} for sid, etat in self._sessions]

    def WTSGetActiveConsoleSessionId(self):
        return self._console

    def WTSQueryUserToken(self, sid):
        if sid not in self._jetons:
            raise OSError(1008, "WTSQueryUserToken", "Tentative de reference a un jeton qui n'existe pas.")
        return self._jetons[sid]


def test_une_session_active_sans_jeton_n_arrete_pas_la_recherche():
    ts = FauxTS(sessions=[(3, 0), (5, 0)], jetons={5: "jeton5"})
    assert S._session_avec_jeton(ts) == (5, "jeton5")


def test_une_session_connectee_sert_quand_aucune_active_n_a_de_jeton():
    ts = FauxTS(sessions=[(3, 0), (4, 1)], jetons={4: "jeton4"})   # 1 = WTSConnected
    assert S._session_avec_jeton(ts) == (4, "jeton4")


def test_la_console_reste_le_dernier_recours():
    ts = FauxTS(sessions=[(0, 4)], jetons={2: "jeton2"}, console=2)  # session 0 = services, deconnectee
    assert S._session_avec_jeton(ts) == (2, "jeton2")


def test_aucun_jeton_nulle_part_leve_en_nommant_les_sessions_essayees():
    ts = FauxTS(sessions=[(3, 0), (4, 1)], jetons={})
    try:
        S._session_avec_jeton(ts)
    except S.SandboxError as e:
        assert "3" in str(e) and "4" in str(e), e
    else:
        raise AssertionError("aucune session n'a de jeton : il fallait lever, pas deviner")


def test_la_session_d_un_autre_compte_n_est_jamais_prise():
    """Revue adverse de Codex (17/10, CONFIRME) : la 1re session avec jeton pouvait etre celle d'un AUTRE compte."""
    owner = S._compte_owner()
    ts = FauxTS(sessions=[(3, 0), (5, 0)], jetons={3: "jeton_autre", 5: "jeton_owner"}, comptes={3: "Autre", 5: owner})
    assert S._session_avec_jeton(ts) == (5, "jeton_owner")


def test_un_proprietaire_illisible_est_ignore():
    ts = FauxTS(sessions=[(3, 0)], jetons={3: "jeton"}, comptes={})
    try:
        S._session_avec_jeton(ts)
    except S.SandboxError:
        pass
    else:
        raise AssertionError("proprietaire illisible : la session ne devait pas etre prise")


def test_le_compte_owner_se_lit_dans_le_chemin_du_depot():
    assert S._compte_owner() == "proprio"


def test_hors_d_un_profil_le_compte_est_illisible_et_le_dit(monkeypatch):
    monkeypatch.setattr(PA, "__file__", r"D:\a\nokido\nokido\app\forge_provider_admin.py")   # runner GitHub
    assert S._compte_owner() is None


def test_le_lanceur_interactif_passe_par_la_recherche_de_jeton():
    """Chemin reel : spawn_as_interactive_jobbed appelle _session_avec_jeton (plus de sid fige en premier)."""
    import inspect
    src = inspect.getsource(S.spawn_as_interactive_jobbed)
    assert "_session_avec_jeton(win32ts)" in src
