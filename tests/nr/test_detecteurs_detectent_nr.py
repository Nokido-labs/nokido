"""NR — M1 : les detecteurs du corps sont eprouves sur un chemin NEGATIF.

Chantier M1 de `docs/roadmap_ameliorations_veille.md`, complement direct de E1 :
E1 prouve qu'un garde MORD, M1 prouve qu'un detecteur DETECTE. Un garde refuse,
il AGIT ; un detecteur signale, il OBSERVE. Le patron vit dans `_patron_garde.py`.

POURQUOI. Un detecteur qui n'a jamais vu de defaut ne prouve rien : son silence
peut vouloir dire « tout va bien » comme « je ne regarde pas ». Le depot en porte
plusieurs traces datees — `deno lint` rendait une chaine VIDE quand deno etait
introuvable, ce qui se lisait « 0 erreur » ; `psutil` rendait une cmdline vide
pour 331 process sur 339, lu comme « ce service ne tourne pas » ; `Path.exists()`
rendait False sous le compte sandbox pour un dossier qui EXISTE. Dans les trois
cas l'instrument se taisait, et son silence a ete pris pour une mesure.

La seule facon de distinguer un detecteur qui marche d'un detecteur muet est de
lui PRESENTER ce qu'il doit voir. C'est ce que fait ce fichier, sur trois
detecteurs reels, sans demarrer aucun service ni ecrire nulle part.

⚠️ Et la symetrie compte autant : on verifie aussi qu'ils ne signalent RIEN sur
une entree saine. Un instrument qui crie a faux se fait desarmer, et le vrai
signal se perd avec lui.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : parcours du depot : glob tests/nr + lecture
#   (l.155)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

RACINE = Path(__file__).resolve().parents[2]
for _c in (RACINE, RACINE / "app", RACINE / "tools", Path(__file__).parent):
    if str(_c) not in sys.path:
        sys.path.insert(0, str(_c))

from _patron_garde import (  # noqa: E402
    DetecteurAveugle,
    DetecteurHallucine,
    prouver_que_le_detecteur_detecte,
)


# ── le patron lui-meme doit mordre ───────────────────────────────────────────

def test_le_patron_detecte_un_detecteur_aveugle():
    with pytest.raises(DetecteurAveugle):
        prouver_que_le_detecteur_detecte(
            nom="fictif muet",
            detecter=lambda _e: [],
            entree_fautive="defaut evident",
            entree_saine="rien a signaler",
            a_signale=bool,
        )


def test_le_patron_detecte_un_detecteur_qui_hallucine():
    with pytest.raises(DetecteurHallucine):
        prouver_que_le_detecteur_detecte(
            nom="fictif paniquant",
            detecter=lambda _e: ["alerte"],
            entree_fautive="defaut evident",
            entree_saine="rien a signaler",
            a_signale=bool,
        )


# ── detecteur 1 : les chemins figes de l'ancien nom du depot ────────────────

def test_le_detecteur_de_chemins_figes_voit():
    """Le renommage du depot a laisse des chemins absolus morts."""
    ax = pytest.importorskip("forge_axis_backtest")
    prouver_que_le_detecteur_detecte(
        nom="chemins figes (ax15)",
        detecter=lambda src: ax.ax15_hardcoded_legacy_paths(src, "fixture.py"),
        entree_fautive='RACINE = r"C:\\Users\\x\\Script python IA\\LaForge\\app"\n',
        entree_saine="RACINE = str(Path(__file__).resolve().parent)\n",
        a_signale=bool,
    )


# ── detecteur 2 : le classement anatomique d'un module ──────────────────────

def test_le_classement_d_organe_voit_un_module_non_classable():
    """Un module qu'aucun filet ne place doit ressortir « non classe ».

    C'est le signal qui alimente le gate `anatomie` : s'il ne se declenchait
    jamais, un module neuf sans declaration passerait inapercu.
    """
    census = pytest.importorskip("forge_module_census")

    def classer(cas):
        nom, fichier, rel = cas
        return census.organ(nom, fichier, rel)

    prouver_que_le_detecteur_detecte(
        nom="classement d'organe",
        detecter=classer,
        entree_fautive=("zzz_module_sans_indice_xyz", "zzz_module_sans_indice_xyz.py",
                        "zzz_module_sans_indice_xyz.py"),
        entree_saine=("forge_videur", "forge_videur.py", "app/forge_videur.py"),
        a_signale=lambda organe: "non classe" in str(organe).lower(),
    )


# ── detecteur 3 : le garde anti-exfiltration de secrets ─────────────────────

def test_le_garde_de_secrets_voit_une_lecture_de_secrets(monkeypatch):
    """Le detecteur le plus critique du depot : son aveuglement couterait le plus.

    `sanitize_python_code` rend None quand tout va bien, un message sinon.

    ⚠️ DECOUVERTE DU 2026-09-08, et c'est le resultat le plus utile de ce
    fichier. Sans les deux lignes ci-dessous, ce test ECHOUE — non parce que le
    garde est aveugle, mais parce qu'il tourne en **mode dev** sous pytest :

        WARNING Nokido.SecretGuard: [DEV_MODE] Code Python suspect warn only:
                agent=CLAUDE matches=["open('.env"]

    Il DETECTE parfaitement, puis rend `None` au lieu de bloquer. La chaine :
    `tests/conftest.py` (L43) charge `Nokido.env`, qui porte `LAFORGE_MCP_DEV=true`
    (L110) et `LAFORGE_ENV=dev` (L156). Toute la suite tourne donc avec les
    gardes de securite en warn-only, et AUCUN test ne peut prouver qu'un garde
    BLOQUE — il faut le lui demander explicitement, comme ici.

    On ne corrige pas le conftest : il previent lui-meme qu'une fixture globale
    changerait le comportement de 92 fichiers d'un coup. Le mode reel se force
    au cas par cas, pour les tests qui veulent mesurer un BLOCAGE.
    """
    monkeypatch.delenv("LAFORGE_MCP_DEV", raising=False)
    monkeypatch.setenv("LAFORGE_ENV", "prod")

    guard = pytest.importorskip("forge_secret_guard")
    assert not guard.is_dev_mode(), (
        "le mode dev est encore actif : ce test mesurerait un warn, pas un blocage"
    )

    fautif = "open('.env').read()\n"
    sain = "resultat = sum(x * 2 for x in range(10))\n"

    prouver_que_le_detecteur_detecte(
        nom="garde anti-exfiltration de secrets",
        detecter=lambda code: guard.sanitize_python_code(code, "CLAUDE", 4),
        entree_fautive=fautif,
        entree_saine=sain,
        a_signale=lambda verdict: verdict is not None,
    )


# ── le patron doit etre UTILISE ─────────────────────────────────────────────

def test_le_patron_M1_a_des_appelants():
    """Un patron ecrit et jamais employe serait le defaut qu'il combat."""
    dossier = Path(__file__).parent
    appelants = [
        p.name for p in dossier.glob("test_*_nr.py")
        if "prouver_que_le_detecteur_detecte" in p.read_text(
            encoding="utf-8", errors="replace")
    ]
    assert appelants, "le patron M1 n'est appele par aucun NR"
