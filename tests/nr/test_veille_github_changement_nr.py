"""NR — savoir si un depot a bouge, SANS le cloner, et en trois etats.

POURQUOI. Mesure 2026-08-31 : `forge_veille_clone_ingest` et
`forge_veille_github_direct` n'ont AUCUN importateur. La voie depot n'est pas une
veille, c'est une commande qu'un humain lance. Pour la rendre recurrente sans
re-cloner chaque heure, il faut d'abord savoir si le depot a change.

Le dernier HEAD ingere est deja persiste dans le manifeste de dump (`commit`,
ecrit depuis `b4310266f`). Aucun schema n'est cree ici.

CE QUE CES TESTS PROTEGENT, et c'est un seul principe applique deux fois :
un HEAD distant qu'on n'a PAS PU lire ne prouve pas qu'un depot n'a pas bouge, et
un manifeste illisible ne prouve pas qu'un depot n'a jamais ete ingere. Confondre
l'un ou l'autre avec une certitude donne, dans un sens, une veille qui se croit a
jour pendant toute une panne reseau ; dans l'autre, un clone complet a chaque
tour. Les deux erreurs sont silencieuses.

HERMETIQUE : aucun reseau, aucun clone, aucune base. `git ls-remote` est injecte.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
for _p in (_ROOT, _ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from tools import forge_veille_registre as reg  # noqa: E402

_SHA1 = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
_SHA2 = "ffeeddccbbaa99887766554433221100aabbccdd"


class _Git:
    """`git ls-remote` INJECTE : les tests ne joignent aucun reseau."""

    def __init__(self, stdout="", rc=0, stderr="", boom=None):
        self.stdout, self.returncode, self.stderr = stdout, rc, stderr
        self._boom = boom
        self.appels: list = []

    def __call__(self, cmd):
        self.appels.append(list(cmd))
        if self._boom is not None:
            raise self._boom
        return self


def _manifeste(tmp_path, commit, nom="depot.md") -> Path:
    dump = tmp_path / nom
    dump.write_text("contenu du dump", encoding="utf-8")
    reg.chemin_manifeste(dump).write_text(
        json.dumps({"repo": "org/depot", "url": "https://github.com/org/depot",
                    "target_id": "abcdef0123456789", "commit": commit,
                    "filtre_version": "1", "fichiers_retenus": 12}),
        encoding="utf-8")
    return dump


# ── le dernier HEAD ingere se lit dans le manifeste EXISTANT ────────────────
def test_le_sha_ingere_vient_du_manifeste(tmp_path):
    assert reg.sha_ingere(_manifeste(tmp_path, _SHA1)) == _SHA1


def test_manifeste_ABSENT_rend_None_pas_une_chaine_vide(tmp_path):
    assert reg.sha_ingere(tmp_path / "jamais_dumpe.md") is None


def test_manifeste_ILLISIBLE_rend_None_lui_aussi(tmp_path):
    """Corrompu ou absent, on ne SAIT pas : c'est a l'appelant de trancher."""
    dump = tmp_path / "d.md"
    dump.write_text("x", encoding="utf-8")
    reg.chemin_manifeste(dump).write_text("pas du json {", encoding="utf-8")
    assert reg.sha_ingere(dump) is None


def test_commit_note_inconnu_ne_vaut_pas_un_sha(tmp_path):
    """`inconnu` est deja la valeur que `etat_dump` refuse : meme lecture ici."""
    assert reg.sha_ingere(_manifeste(tmp_path, "inconnu")) is None


# ── 1 / 4 : depot inchange, et rejeu du meme commit ─────────────────────────
def test_1_depot_INCHANGE(tmp_path):
    etat, raison = reg.etat_cible(_SHA1, reg.sha_ingere(_manifeste(tmp_path, _SHA1)))
    assert etat == reg.NO_CHANGE
    assert _SHA1[:12] in raison


def test_4_rejouer_le_MEME_commit_reste_NO_CHANGE(tmp_path):
    dump = _manifeste(tmp_path, _SHA1)
    for _ in range(3):
        assert reg.etat_cible(_SHA1, reg.sha_ingere(dump))[0] == reg.NO_CHANGE


# ── 2 / 3 : depot change, nouveau commit ────────────────────────────────────
def test_23_un_nouveau_HEAD_est_UPDATED(tmp_path):
    etat, raison = reg.etat_cible(_SHA2, reg.sha_ingere(_manifeste(tmp_path, _SHA1)))
    assert etat == reg.UPDATED
    assert _SHA1[:12] in raison and _SHA2[:12] in raison


def test_jamais_ingere_est_UPDATED_pas_UNKNOWN():
    """La seule asymetrie voulue : rien en local et un HEAD connu = tout est neuf."""
    etat, raison = reg.etat_cible(_SHA1, None)
    assert etat == reg.UPDATED
    assert "aucun dump" in raison


# ── 6 : le HEAD distant illisible ───────────────────────────────────────────
def test_6_HEAD_distant_ILLISIBLE_est_UNKNOWN_jamais_NO_CHANGE(tmp_path):
    """LE verrou. Confondre « je n'ai pas pu lire » avec « rien n'a bouge » fait
    une veille qui se croit a jour pendant toute une panne reseau."""
    local = reg.sha_ingere(_manifeste(tmp_path, _SHA1))
    for distant in (None, "", "   "):
        etat, raison = reg.etat_cible(distant, local)
        assert etat == reg.UNKNOWN, "distant=%r a rendu %s" % (distant, etat)
        assert "pas declare a jour" in raison


def test_UNKNOWN_prime_meme_quand_rien_n_est_ingere():
    assert reg.etat_cible(None, None)[0] == reg.UNKNOWN


# ── la lecture du HEAD distant, sans clone ──────────────────────────────────
def test_head_distant_lit_le_sha_sans_cloner():
    g = _Git(stdout="%s\tHEAD\n" % _SHA1)
    sha, raison = reg.head_distant("https://github.com/org/depot", lanceur=g)
    assert sha == _SHA1
    cmd = g.appels[0]
    assert cmd[:2] == ["git", "ls-remote"]
    assert "clone" not in cmd, "la detection ne doit RIEN cloner"


def test_head_distant_ignore_les_autres_refs():
    """`ls-remote` rend aussi les branches : ne pas prendre la premiere ligne."""
    g = _Git(stdout="%s\trefs/heads/main\n%s\tHEAD\n" % (_SHA2, _SHA1))
    assert reg.head_distant("u", lanceur=g)[0] == _SHA1


def test_head_distant_en_echec_rend_None_et_DIT_pourquoi():
    sha, raison = reg.head_distant("u", lanceur=_Git(rc=128, stderr="not found"))
    assert sha is None
    assert "rc=128" in raison


def test_head_distant_qui_leve_rend_None_et_DIT_pourquoi():
    sha, raison = reg.head_distant("u", lanceur=_Git(boom=OSError("reseau")))
    assert sha is None
    assert "OSError" in raison


def test_une_sortie_SANS_ligne_HEAD_n_invente_pas_de_sha():
    sha, raison = reg.head_distant("u", lanceur=_Git(stdout="%s\trefs/tags/v1\n" % _SHA2))
    assert sha is None
    assert "sans ligne HEAD" in raison


# ── le scenario principal demande ───────────────────────────────────────────
def test_scenario_HEAD1_puis_HEAD1_puis_HEAD2(tmp_path):
    """HEAD1 -> a ingerer ; HEAD1 rejoue -> NO_CHANGE, rien a faire ;
    HEAD2 -> UPDATED, matiere neuve."""
    dump = tmp_path / "depot.md"
    # Premier passage : rien n'a jamais ete ingere.
    assert reg.etat_cible(_SHA1, reg.sha_ingere(dump))[0] == reg.UPDATED
    # L'ingestion a eu lieu : le manifeste porte HEAD1.
    _manifeste(tmp_path, _SHA1)
    assert reg.etat_cible(_SHA1, reg.sha_ingere(dump))[0] == reg.NO_CHANGE
    # Le depot avance.
    assert reg.etat_cible(_SHA2, reg.sha_ingere(dump))[0] == reg.UPDATED


def test_une_panne_reseau_au_milieu_ne_efface_pas_l_etat_connu(tmp_path):
    """Reprise apres interruption : le manifeste est la seule memoire, et une
    panne ne doit ni la perdre ni la faire mentir."""
    dump = _manifeste(tmp_path, _SHA1)
    assert reg.etat_cible(None, reg.sha_ingere(dump))[0] == reg.UNKNOWN
    assert reg.etat_cible(_SHA1, reg.sha_ingere(dump))[0] == reg.NO_CHANGE


def test_les_trois_etats_sont_bien_DISTINCTS():
    assert len({reg.NO_CHANGE, reg.UPDATED, reg.UNKNOWN}) == 3
