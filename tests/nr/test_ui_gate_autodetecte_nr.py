"""NR 2026-09-09 — le contrat de l'interface web se mesure DES QUE l'interface repond.

LE DEFAUT. `ui-acceptance` figure dans `_DOMAINES_CRITIQUES` de ci_local, et il est
pourtant garde derriere `if a.ui_gate:` — un drapeau opt-in que la CI standard ne
passe jamais. Il ne tourne donc JAMAIS : le domaine le plus visible du systeme, celui
que l'owner regarde, n'est mesure par personne. C'est l'ANERGIE que le registre de
vitalite est cense crier, et il la signale bien (`perimetre=PARTIAL`) sans bloquer.

Un vert par absence est pire qu'un rouge : il ressemble a un verdict.

CE QUI NE MANQUAIT PAS. Le gate lui-meme est bon — trois etats, avec un `UNKNOWN`
(rc=2) qui ne vaut PAS un succes depuis le 2026-08-26 (« l'owner signalait une UI
cassee pendant que ce gate affichait vert : il n'avait rien juge »), et une passe de
clic activee pour verifier qu'un bouton FASSE quelque chose. Il ne manquait que son
declenchement.

MESURE DU JOUR : le service repond. `:7400` LISTENING (pid 5292), `GET /health` rend
200 en 18 ms, `GET /` rend 401 — l'AuthMiddleware ASGI fait son travail, ce n'est pas
une panne. Le gate POUVAIT donc tourner ; rien ne le demandait.

PRUDENCE DELIBEREE : en auto-detection le gate est NON BLOQUANT. Il a un historique
(« 4 runs rouges sur 8, checkout en echec »), et on observe avant d'enforcer — meme
protocole que le gate `anatomie`, promu bloquant seulement apres mesure de son bruit.
Avec `--ui-gate` explicite, il reste bloquant comme avant : la demande explicite
engage, l'auto-detection observe.

Zero service externe : la sonde est exercee sur un port FERME, aucun webhub requis.
"""

import socket
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE / "tools"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ci_local  # noqa: E402


def _port_libre() -> int:
    """Un port que personne n'ecoute — pour prouver que la sonde sait dire NON."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def test_la_sonde_du_webhub_existe():
    assert hasattr(ci_local, "_webhub_repond"), (
        "ci_local n'expose pas _webhub_repond : le gate ui-acceptance reste donc "
        "derriere un drapeau opt-in, et un domaine declare CRITIQUE n'est mesure "
        "par personne")


def test_la_sonde_dit_NON_sur_un_port_ferme():
    """Contre-epreuve : une sonde qui repond toujours oui ne mesure rien."""
    ok, motif = ci_local._webhub_repond(port=_port_libre(), timeout=1.0)
    assert ok is False
    assert motif, "un refus SANS motif doit etre re-instruit a chaque run"


def test_la_sonde_NOMME_ce_qu_elle_n_a_pas_pu_voir():
    """ABSENT et INJOIGNABLE se disent, ils ne se devinent pas."""
    _ok, motif = ci_local._webhub_repond(port=_port_libre(), timeout=1.0)
    bas = motif.lower()
    assert any(m in bas for m in ("injoignable", "refus", "connexion", "timeout", "erreur")), (
        "le motif ne nomme pas la panne : %r" % motif)


def test_le_gate_reste_declare_critique():
    """Non-regression : c'est ce qui rend l'anergie inacceptable."""
    crit = getattr(ci_local, "_DOMAINES_CRITIQUES", ())
    assert any("ui-acceptance" in str(c) for c in crit), (
        "ui-acceptance n'est plus declare critique : l'argument de ce NR tombe, "
        "et il faut alors decider explicitement si ce domaine compte")


def test_l_auto_detection_est_NON_bloquante_et_le_dit():
    """Observer avant d'enforcer — et que le code le dise, pas seulement moi.

    Le gate a un historique de rougeur ; le promouvoir bloquant d'emblee le ferait
    desarmer. La distinction demande explicite / auto-detection doit etre lisible
    dans la source, sinon la prochaine session la supprimera en croyant simplifier.
    """
    src = (RACINE / "tools" / "ci_local.py").read_text(encoding="utf-8", errors="replace")
    assert "_webhub_repond" in src

    # CONTRE-EPREUVE D'ANCRE, apprise ici meme le 2026-09-09 : la premiere version de
    # ce test cherchait « ui-acceptance (BLOQUANT », texte que le correctif venait de
    # supprimer. `find` rendait -1, donc `src[-1:]` = "\n" -- et si l'ancre avait
    # rendu 0, la « zone » aurait ete le fichier ENTIER et le test serait passe pour
    # de mauvaises raisons. Une ancre qui ne matche pas doit ECHOUER en le disant.
    i = src.find("ui-acceptance : contrat forge_ui_campaign")
    assert i > 0, "ancre du gate introuvable : ce test ne mesure plus rien"
    zone = src[i:i + 4000]

    assert "auto-detection" in zone.lower(), (
        "l'auto-detection n'est pas nommee pres du gate : la prochaine session la "
        "supprimera en croyant simplifier")
    assert "non bloquant" in zone.lower(), (
        "la distinction demande explicite / observation n'est pas ecrite")
    assert "--ui-gate" in zone, "le regime engageant n'est plus nomme"
