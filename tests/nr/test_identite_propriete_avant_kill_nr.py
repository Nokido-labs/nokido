"""NR -- tuer exige une PROPRIETE prouvee, jamais un port tenu ni une sous-chaine (CONTROL != OWNERSHIP).

Owner 16/10 : « si tu respectes bien les RFC d'identification, tu devrais etre sur des identites ? ». Mesure 16/10
(lecture du code) : (1) forge_body_world_model.guard rendait allowed=True pour un pid HORS registre du superviseur
(verdict 'unknown', « non gouverne ») -- l'inconnu range du cote autorise, la liste noire que la constitution
interdit ; le precedent du 07/09 (doublon Ollama squattant 11434) a ete tue SUR AUTORISATION owner, pas d'office.
(2) forge_llama_keeper._is_coder qualifiait un pid par SOUS-CHAINE de port dans sa ligne de commande : '18080'
contient '8080'.
"""
import os
import sys

_TOOLS = os.path.join(os.path.dirname(__file__), "..", "..", "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import forge_llama_keeper as K  # noqa: E402
from nokido_agent.app import forge_body_world_model as W  # noqa: E402


def _hors_registre(monkeypatch):
    monkeypatch.delenv("LAFORGE_LIFECYCLE_FORCE", raising=False)
    monkeypatch.setattr(W, "_resolve_pid", lambda pid: (None, None))


def test_un_pid_hors_registre_n_est_pas_tuable_sans_force(monkeypatch):
    _hors_registre(monkeypatch)
    g = W.guard(424242, "kill")
    assert g["allowed"] is False, g
    assert "propri" in g["impact"]["reason"].lower(), g


def test_force_reste_le_seul_passage_pour_un_pid_hors_registre(monkeypatch):
    _hors_registre(monkeypatch)
    assert W.guard(424242, "kill", force=True)["allowed"] is True


def test_une_action_non_destructive_reste_permise(monkeypatch):
    _hors_registre(monkeypatch)
    assert W.guard(424242, "status")["allowed"] is True


def test_le_keeper_ne_qualifie_pas_un_coder_par_sous_chaine_de_port(monkeypatch):
    import psutil

    port = K._MANAGED_PORTS[0]
    cmd = [["llama-server.exe", "--port", "1%s0" % port]]

    class _P:
        def __init__(self, pid):
            self.pid = pid

        def cmdline(self):
            return cmd[0]

    monkeypatch.setattr(K, "_serving_pids", lambda: set())
    monkeypatch.setattr(psutil, "Process", _P)
    assert K._is_coder(1) is False, "port %s pris dans '1%s0'" % (port, port)
    cmd[0] = ["llama-server.exe", "--port", port]
    assert K._is_coder(1) is True
