"""NR -- isolation locale : qui est au bout de la connexion loopback ?

Point 5 de la revue M2M du 2026-09-02. Ecouter sur `127.0.0.1` protege du
reseau, pas de la machine : tout processus du meme compte peut se connecter.

La recommandation classique -- named pipe ou socket de domaine avec ACL -- est
INAPPLICABLE ici et il faut le dire plutot que de faire semblant : les clients
implementent l'API OpenAI, donc HTTP sur TCP. Changer de transport ne durcirait
rien, ca supprimerait le service. On identifie donc le PROCESSUS au bout de la
connexion, ce qui est l'equivalent d'une ACL au-dessus du transport existant.

Ce que ces tests verrouillent :
1. TROIS etats -- `INDETERMINE` n'est ni un refus ni une autorisation ;
2. la politique VIDE ne refuse RIEN (mesure seule) et n'autorise rien non plus ;
3. l'interdiction PRIME sur l'autorisation ;
4. une identification partielle (chemin illisible) se VOIT.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

import forge_pair_local as pl  # noqa: E402


@pytest.fixture
def vu(monkeypatch):
    """Fait comme si le processus au bout etait identifie."""
    def _poser(nom, **extra):
        base = {"pid": 4242, "process": nom, "chemin": "C:/x/%s" % nom, "raison": ""}
        base.update(extra)
        monkeypatch.setattr(pl, "identifier", lambda _p: base)
    return _poser


# --------------------------------------------------------------------------- #
# Trois etats
# --------------------------------------------------------------------------- #

def test_les_trois_etats_sont_distincts():
    assert len({pl.AUTORISE, pl.REFUSE, pl.INDETERMINE}) == 3


def test_processus_non_identifie_est_indetermine(monkeypatch):
    """« Je n'ai pas pu voir » n'est ni un refus ni une autorisation. Un
    appelant legitime dont la socket s'est fermee entre la requete et la mesure
    serait rejete a tort -- et un garde qui crie a faux se fait desarmer."""
    monkeypatch.setattr(pl, "identifier",
                        lambda _p: {"pid": None, "process": None, "raison": "socket fermee"})
    v = pl.verdict(1234, {"autorises": ["claude.exe"], "interdits": []})
    assert v["etat"] == pl.INDETERMINE
    assert v["motif"]


def test_port_absent_est_indetermine():
    assert pl.verdict(None)["etat"] == pl.INDETERMINE


# --------------------------------------------------------------------------- #
# Politique
# --------------------------------------------------------------------------- #

def test_politique_vide_ne_refuse_rien(vu):
    """Une allowlist devinee refuserait des clients legitimes que personne n'a
    pense a lister, tout en donnant l'illusion d'un controle. Tant que personne
    n'a decide, l'indetermine est le seul etat honnete."""
    vu("nimporte.exe")
    v = pl.verdict(1234, pl.politique_par_defaut())
    assert v["etat"] == pl.INDETERMINE
    assert "non encore decidee" in v["motif"]


def test_politique_par_defaut_est_vide():
    p = pl.politique_par_defaut()
    assert p["autorises"] == [] and p["interdits"] == []


def test_autorise_si_dans_la_liste(vu):
    vu("claude.exe")
    assert pl.verdict(1234, {"autorises": ["claude.exe"], "interdits": []})["etat"] == pl.AUTORISE


def test_refuse_si_hors_liste(vu):
    vu("inconnu.exe")
    v = pl.verdict(1234, {"autorises": ["claude.exe"], "interdits": []})
    assert v["etat"] == pl.REFUSE


def test_interdit_prime_sur_autorise(vu):
    """Devant une contradiction de configuration, la lecture la plus stricte
    l'emporte."""
    vu("claude.exe")
    v = pl.verdict(1234, {"autorises": ["claude.exe"], "interdits": ["claude.exe"]})
    assert v["etat"] == pl.REFUSE


def test_comparaison_insensible_a_la_casse(vu):
    vu("Claude.EXE")
    assert pl.verdict(1234, {"autorises": ["claude.exe"], "interdits": []})["etat"] == pl.AUTORISE


# --------------------------------------------------------------------------- #
# Une identification PARTIELLE se voit
# --------------------------------------------------------------------------- #

def test_chemin_illisible_est_signale(vu):
    """Le chemin distingue un binaire legitime d'un homonyme depose ailleurs.
    Ne pas l'avoir affaiblit la mesure : ca doit se voir, pas passer pour une
    identification complete."""
    vu("claude.exe", chemin=None, raison="chemin illisible -- un homonyme ne serait pas distingue")
    v = pl.verdict(1234, {"autorises": ["claude.exe"], "interdits": []})
    assert v["etat"] == pl.AUTORISE
    assert "homonyme" in v["raison"]


# --------------------------------------------------------------------------- #
# Le CHEMIN, pas seulement le nom -- recommandation de la revue M2M
# --------------------------------------------------------------------------- #

def test_le_nom_seul_ne_suffit_plus_si_un_chemin_est_exige(vu):
    """`claude.exe` depose dans un dossier quelconque porte le meme nom que le
    vrai. Des qu'une politique exige des chemins, le nom cesse de suffire."""
    vu("claude.exe", chemin="C:/ailleurs/claude.exe")
    v = pl.verdict(1234, {"autorises": ["claude.exe"], "interdits": [],
                          "chemins_autorises": ["C:/Program Files/Claude"]})
    assert v["etat"] == pl.REFUSE
    assert "hors des chemins" in v["motif"]


def test_le_bon_chemin_autorise(vu):
    vu("claude.exe", chemin="C:/Program Files/Claude/claude.exe")
    v = pl.verdict(1234, {"autorises": [], "interdits": [],
                          "chemins_autorises": ["C:/Program Files/Claude"]})
    assert v["etat"] == pl.AUTORISE


def test_chemin_illisible_avec_politique_de_chemin_est_indetermine(vu):
    """Ne pas pouvoir verifier n'est pas verifier : un chemin illisible ne doit
    ni autoriser (on n'a rien prouve) ni refuser (on couperait a tort)."""
    vu("claude.exe", chemin=None)
    v = pl.verdict(1234, {"autorises": ["claude.exe"], "interdits": [],
                          "chemins_autorises": ["C:/Program Files/Claude"]})
    assert v["etat"] == pl.INDETERMINE
    assert "homonyme" in v["motif"]


def test_separateurs_windows_et_posix_equivalents(vu):
    vu("claude.exe", chemin="C:\\Program Files\\Claude\\claude.exe")
    v = pl.verdict(1234, {"autorises": [], "interdits": [],
                          "chemins_autorises": ["C:/Program Files/Claude"]})
    assert v["etat"] == pl.AUTORISE


def test_un_prefixe_partiel_ne_passe_pas(vu):
    """`C:/ProgramFilesMalveillant` ne doit pas matcher `C:/ProgramFiles`."""
    vu("x.exe", chemin="C:/apps-malveillant/x.exe")
    v = pl.verdict(1234, {"autorises": [], "interdits": [],
                          "chemins_autorises": ["C:/apps"]})
    assert v["etat"] == pl.REFUSE


def test_l_interdiction_prime_meme_sur_un_chemin_valide(vu):
    vu("x.exe", chemin="C:/apps/x.exe")
    v = pl.verdict(1234, {"autorises": [], "interdits": ["x.exe"],
                          "chemins_autorises": ["C:/apps"]})
    assert v["etat"] == pl.REFUSE


# --------------------------------------------------------------------------- #
# PERSPECTIVE EDGE : le garde doit DIRE quand il ne s'applique plus
# --------------------------------------------------------------------------- #

def test_sur_un_service_expose_le_controle_est_declare_inapplicable(monkeypatch):
    """Le fail-open le plus couteux : identifier « le processus au bout » n'a
    de sens que si le pair est sur cette machine. Sur un service expose, le
    module rendait INDETERMINE -- que l'appelant ne traite pas -- donc
    isolation armee + service expose = TOUT PASSE, sans un mot. Le garde
    s'eteignait exactement quand il devenait necessaire."""
    import forge_bind_guard as bg

    monkeypatch.setattr(bg, "verdict", lambda p: {"etat": "EXPOSE",
                                                  "adresses": ["0.0.0.0"]})
    v = pl.verdict(65000, {"autorises": ["x.exe"]}, port_ecoute=7777)
    assert v["etat"] == pl.INAPPLICABLE
    assert "TLS" in v["motif"] or "transport" in v["motif"], (
        "le motif doit dire ce qu'il faut A LA PLACE, pas seulement que ca ne "
        "s'applique plus")


def test_exposition_illisible_ne_conclut_pas(monkeypatch):
    """Trois etats jusqu'au bout : ne pas savoir si le service est expose ne
    doit ni autoriser ni declarer le controle applicable."""
    import forge_bind_guard as bg

    monkeypatch.setattr(bg, "verdict", lambda p: {"etat": "INCONNU"})
    assert pl.portee(7777)["applicable"] is None
    assert pl.verdict(65000, {"autorises": ["x.exe"]},
                      port_ecoute=7777)["etat"] == pl.INDETERMINE


def test_portee_locale_laisse_le_controle_operer(monkeypatch):
    import forge_bind_guard as bg

    monkeypatch.setattr(bg, "verdict", lambda p: {"etat": "LOOPBACK",
                                                  "adresses": ["127.0.0.1"]})
    assert pl.portee(7777)["applicable"] is True


def test_les_quatre_etats_sont_distincts():
    assert len({pl.AUTORISE, pl.REFUSE, pl.INDETERMINE, pl.INAPPLICABLE}) == 4


def test_la_decision_de_ne_pas_faire_de_tls_est_ecrite():
    """« Ne pas faire » doit etre une DECISION lisible dans le code, pas un
    oubli qu'on redecouvre en audit. La revue l'a explicitement demande."""
    src = (ROOT / "tools" / "forge_openai_proxy.py").read_text(
        encoding="utf-8", errors="replace")
    i = src.find("DECISION ACTEE")
    assert i > 0, "la decision de ne pas chiffrer le loopback n'est ecrite nulle part"
    zone = src[i:i + 1600]
    for mot in ("loopback", "SYSTEM", "delegue"):
        assert mot.lower() in zone.lower(), mot


def test_le_verdict_porte_toujours_un_motif(vu):
    vu("x.exe")
    for pol in ({"autorises": [], "interdits": []},
                {"autorises": ["x.exe"], "interdits": []},
                {"autorises": [], "interdits": ["x.exe"]}):
        assert pl.verdict(1234, pol)["motif"].strip()


# --------------------------------------------------------------------------- #
# Cablage cote passerelle : mesure d'abord, refus seulement si arme
# --------------------------------------------------------------------------- #

def test_la_passerelle_mesure_par_defaut_et_ne_bloque_pas():
    src = (ROOT / "tools" / "forge_openai_proxy.py").read_text(
        encoding="utf-8", errors="replace")
    assert "_PAIR_LOCAL_ACTIF" in src and "_PAIR_LOCAL_BLOQUANT" in src, (
        "observer et bloquer doivent etre deux decisions distinctes")
    i = src.find("_PAIR_LOCAL_BLOQUANT =")
    assert 'os.environ.get("LAFORGE_PROXY_PAIR_LOCAL_BLOQUANT", "")' in src[i:i + 200], (
        "le refus doit defaulter a DESARME")


def test_le_tls_absent_ne_demarre_pas_en_clair_en_silence():
    """Demander du TLS et demarrer en clair sans le dire ferait croire a un
    canal chiffre -- c'est la faute la plus couteuse possible ici."""
    src = (ROOT / "tools" / "forge_openai_proxy.py").read_text(
        encoding="utf-8", errors="replace")
    i = src.find("LAFORGE_PROXY_TLS_CERT")
    assert i > 0
    zone = src[i:i + 1400]
    assert "DEMARRAGE EN CLAIR" in zone


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
