# -*- coding: utf-8 -*-
"""NR — les erreurs RECURRENTES doivent etre servies, pas seulement archivees.

Owner, 2026-09-05 : « il faudrait cabler TOUTES tes erreurs recurrentes », apres
m'avoir vu reproposer `nssm restart` alors que la lecon existait dans une fiche
ecrite le matin meme. Le reproche exact portait sur la FORME du souvenir :

    une fiche  = ATTEIGNABLE si on la cherche -> suppose de deja soupconner l'erreur
    une regle  = SERVIE avant le geste, sans etre demandee, sans consommer de tokens

`forge_recurrence_audit` DECLARE douze motifs recidivants avec leur garde. Aucun
n'etait servi au moment du geste. Ce garde verrouille le cablage des quatre qui se
manifestent par une commande reconnaissable, ET la limite de portee des huit autres
-- parce qu'un garde dont on croit la portee plus large qu'elle n'est vaut moins
que pas de garde du tout.

⚠️ Les motifs sont ASSEMBLES par concatenation dans ce fichier. Un test qui ecrit
en clair le motif qu'il traque se declenche lui-meme : mesure du 2026-09-04, un
test « ce motif est INTROUVABLE » l'ecrivait en clair, donc `git grep` le trouvait
des le commit -- vert avant, rouge apres, sans qu'une ligne change.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

g = pytest.importorskip("hook_capability_gate")


def _declenche(cmd: str) -> list:
    return [m for rx, m in g._COMPILED if rx.search(cmd)]


@pytest.mark.parametrize("motif,attendu", [
    (["nssm", " restart laforge-master"], "LANCEUR DU BUREAU"),
    (["hub_restart", ".trigger"], "consomme"),
    (["job", "_status jb1"], "STATUT DECLARE"),
    (["psutil.cpu", "_percent(0.2)"], "WRAPPER"),
    (["supervisor", "/restart"], "ACHIEVED"),
    (["c = text[:", "3000]"], "BORNE"),
])
def test_le_geste_declenche_son_reflexe(motif, attendu):
    """Chaque motif recidivant doit etre SERVI au moment du geste."""
    hits = _declenche("".join(motif))
    assert hits, "aucun reflexe servi pour %r" % ("".join(motif),)
    assert any(attendu in h for h in hits), \
        "reflexe servi mais sans le geste correct : %s" % hits[0][:90]


@pytest.mark.parametrize("cmd", [
    "git -c safe.directory=* -C repo commit -m x",
    'findstr /n /c:"def foo" fichier.py',
    "SELECT source FROM rag_chunks WHERE source GLOB 'http*'",
    "python.exe -m pytest tests/nr/test_a.py -q",
    "for i in range(0, len(content), 500)",
    "lignes[-22:]",
    "print(json.dumps(r, indent=1))",
])
def test_aucun_faux_positif_sur_les_gestes_courants(cmd):
    """La capacite PROUVEE de ce gate est « 0 faux positif » (2026-08-30). Un garde
    qui crie a faux se fait desarmer, et on perd alors les vrais avec."""
    hits = _declenche(cmd)
    assert not hits, "faux positif sur une commande legitime : %s" % (hits[0][:90] if hits else "")


def test_une_borne_de_FIN_n_est_pas_une_troncature():
    """`lignes[-22:]` lit la fin d'un journal ; `text[:3000]` ampute un contenu. Le
    motif ne doit viser que le second, sinon il crie sur chaque lecture de log."""
    assert not _declenche("t.split(chr(10))[-8:]")
    assert _declenche("".join(["body = html[:", "4000]"]))


@pytest.mark.parametrize("cmd", ["print(L[i][:150])", "src[:200]", "msg[:90]",
                                 "ligne[:64] + '...'"])
def test_un_slice_d_AFFICHAGE_ne_declenche_pas(cmd):
    """FAUX POSITIF MESURE le 2026-09-05, dans l'heure suivant l'ajout de la regle :
    la version a 3 chiffres criait sur `L[i][:150]`, un simple affichage. Les
    troncatures qui ont coute portent sur des MILLIERS de caracteres ; un slice
    d'affichage tient en centaines. Sans ce cas, le garde se fait desarmer."""
    assert not _declenche(cmd)


def test_la_portee_reelle_du_gate_est_DECLAREE():
    """Le gate ne voit que les appels `run`. Un tool distinct passe a cote --
    incident du 2026-09-01. Cette limite doit rester ECRITE dans le fichier :
    croire couvert un chemin qui ne l'est pas est pire que l'absence de garde."""
    src = (ROOT / "tools" / "hook_capability_gate.py").read_text(
        encoding="utf-8", errors="replace")
    assert "ne voit QUE les appels" in src
    assert "trusted_script" in src


def test_les_motifs_non_cablables_sont_NOMMES():
    """Huit des douze motifs sont des erreurs de JUGEMENT sur une sortie, hors de
    portee d'un regex. Les nommer empeche de croire la couverture complete."""
    src = (ROOT / "tools" / "hook_capability_gate.py").read_text(
        encoding="utf-8", errors="replace")
    for motif in ("capteur_neuf_pris_pour_temoin", "seuil_invente",
                  "sonde_ponctuelle_fait_temporel", "cause_commune_vs_chemin"):
        assert motif in src, "motif non cablable passe sous silence : %s" % motif


def test_chaque_reflexe_donne_le_geste_QUI_MARCHE():
    """Une note qui dit seulement ce qui echoue laisse reproposer la commande
    inutile -- c'est precisement ce qui est arrive avec `nssm restart`."""
    for motif in (["nssm", " restart x"], ["job", "_status jb1"],
                  ["psutil.cpu", "_percent(0)"]):
        msg = _declenche("".join(motif))[0]
        assert "->" in msg, "reflexe sans geste alternatif : %s" % msg[:80]
