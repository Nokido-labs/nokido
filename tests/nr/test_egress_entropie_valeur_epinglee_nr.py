"""NR -- une exception d'entropie du scanner egress est epinglee par VALEUR, jamais par fichier (2026-10-13).

Mesure : chaque push touchant `config/agent_identities.json` levait « token haute entropie » sur SUPERVISOR/tpm_jkt,
une empreinte PUBLIQUE de cle (RFC 7638). Une exception par fichier aurait aussi blanchi tout secret ajoute plus tard
au meme fichier : elle porte donc le chemin ET sha256[:16] de la valeur.

Invariants : la valeur epinglee passe ; une AUTRE valeur du meme fichier reste signalee ; la valeur epinglee dans un
AUTRE fichier reste signalee ; le manifeste reel contient bien l'epingle (chemin reel de lecture du profil).
"""
import base64
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_git_egress as G  # noqa: E402


def _jeton(graine: bytes) -> str:
    """Jeton base64url de 43 caracteres a haute entropie, deterministe."""
    return base64.urlsafe_b64encode(hashlib.sha256(graine).digest()).decode().rstrip("=")


def _ctx(path, contenu, epingle):
    return {"path": path, "content": contenu,
            "profile": {"secret_allow": [{"path": "config/agent_identities.json", "label": "entropy",
                                          "sha256": hashlib.sha256(epingle.encode()).hexdigest()[:16]}]}}


def test_la_valeur_epinglee_passe_une_autre_reste_signalee():
    """Meme fichier : l'empreinte epinglee passe, un autre jeton est toujours jaune."""
    pub, autre = _jeton(b"jkt-public"), _jeton(b"secret-ajoute-plus-tard")
    assert G._sig_entropy(_ctx("config/agent_identities.json", '{"tpm_jkt": "%s"}' % pub, pub)) is None
    f = G._sig_entropy(_ctx("config/agent_identities.json",
                            '{"tpm_jkt": "%s", "x": "%s"}' % (pub, autre), pub))
    assert f is not None and "haute entropie" in f.reason


def test_la_valeur_epinglee_ailleurs_reste_signalee():
    """L'epingle vaut pour SON chemin seulement."""
    pub = _jeton(b"jkt-public")
    assert G._sig_entropy(_ctx("config/autre.json", '{"k": "%s"}' % pub, pub)) is not None


def test_le_manifeste_reel_porte_l_epingle_du_tpm_jkt():
    """Chemin reel : le profil prive du manifeste contient l'epingle entropy de agent_identities.json."""
    regles = json.loads((ROOT / ".git-publish-rules.json").read_text(encoding="utf-8"))
    allow = regles["profiles"]["private"]["secret_allow"]
    assert any(a.get("label") == "entropy" and a.get("path") == "config/agent_identities.json"
               and len(a.get("sha256", "")) == 16 for a in allow)
