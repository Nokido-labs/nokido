"""NR -- option B (owner 30/10) : la veille RSS, en voie d'echange armee, ingere par HubClient (echange RFC 8693 pour
la portee rag:ingest de RSS_WATCHER, DPoP) et ne lit PLUS le coffre.

Journal d'observation du coffre (30/10) : forge_rss_watcher lisait FORGE_TOKEN_RSS_WATCHER par forge_agent_credential
(jeton_pour) puis posait lui-meme un en-tete Bearer -- meme defaut que forge_self_patcher._hub_call. Voie d'echange
desarmee : comportement d'avant (couvert par les NR existants). Faux reseau, aucun secret reel.
"""
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RACINE.parent), str(RACINE)]
from nokido_agent.app import forge_hub_client as HC  # noqa: E402
from nokido_agent.app import forge_rss_watcher as R  # noqa: E402


def _interdit(*a, **k):
    raise AssertionError("coffre lu alors que l'echange de jeton est arme")


def test_en_voie_d_echange_la_veille_ingere_par_hubclient_sans_lire_le_coffre(monkeypatch):
    monkeypatch.setenv("NOKIDO_JOB_SUBJECT_TOKEN", "sujet-factice")
    monkeypatch.setenv("NOKIDO_JOB_ID", "job_factice")
    monkeypatch.setattr(HC, "_echange_arme", lambda: True)
    monkeypatch.setattr(HC, "_resoudre_jeton", _interdit)
    from nokido_agent.app import forge_agent_credential as AC
    from nokido_agent.app import forge_secrets as FS
    monkeypatch.setattr(AC, "jeton_pour", _interdit)
    monkeypatch.setattr(FS, "get_secret", _interdit)
    vus = []

    def appel_outil(self, name, args, timeout=None):
        vus.append((self.agent, name, args.get("action")))
        return {"result": {"content": [{"type": "text", "text": "{}"}]}}
    monkeypatch.setattr(HC.HubClient, "appel_outil", appel_outil)
    verdict = R._ingest("texte", "rss:test", "veille", "doc", "auteur", "resume")
    assert vus == [("RSS_WATCHER", "rag", "ingest")]
    assert isinstance(verdict, tuple) and len(verdict) == 3
