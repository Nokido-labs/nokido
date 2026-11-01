"""NR 28/10 (recette reelle) : l'outil hub `acp` et le worker parlent le MEME vocabulaire.

Mesure : l'outil hub expose `sid`/`prompt` (schema du registre) et les transmet tels quels ; le worker n'acceptait
que `session`/`texte` -> « session/texte manquants » au premier vrai tour. Chaque cote etait teste avec un faux de
l'autre : le contrat entre eux n'etait verifie par personne.
"""
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "tools", ROOT / "app"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import forge_acp_worker as W  # noqa: E402


class _Routeur:
    def __init__(self):
        self.appels = []

    def envoyer(self, sid, texte, timeout=None):
        self.appels.append(("envoyer", sid, texte))
        return "ok"

    def fermer(self, sid):
        self.appels.append(("fermer", sid))


def _worker(rt):
    return types.SimpleNamespace(router=rt)


def test_envoyer_accepte_sid_et_prompt_de_l_outil_hub():
    rt = _Routeur()
    r = W.AcpWorker.executer(_worker(rt), "envoyer", {"agent": "claude", "sid": "claude-1", "prompt": "bonjour"})
    assert r["ok"] and rt.appels == [("envoyer", "claude-1", "bonjour")]


def test_fermer_accepte_sid():
    rt = _Routeur()
    assert W.AcpWorker.executer(_worker(rt), "fermer", {"sid": "claude-1"})["ok"]
    assert rt.appels == [("fermer", "claude-1")]


def test_les_noms_historiques_marchent_encore():
    rt = _Routeur()
    W.AcpWorker.executer(_worker(rt), "envoyer", {"session": "s", "texte": "t"})
    assert rt.appels == [("envoyer", "s", "t")]
