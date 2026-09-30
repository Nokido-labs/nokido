"""NR 2026-09-09 — le passeur de generations inscrit ce qui manque et n'ecrase RIEN.

POURQUOI CE PASSEUR EXISTE. `docs/generations/` n'est pas inscriptible par les
comptes sandbox, sous lesquels tourne `run_job`. La CI mesure donc sa generation,
la juge STABLE, et ne peut pas l'inscrire : elle depose dans
`sandbox/generations_en_attente/` et le DIT. Mais personne ne venait chercher — la
vitalite avait son passeur depuis le 2026-09-07, la generation n'en avait aucun.
Mesure du jour : GEN-00011, STABLE sur le sha 45a601ea5, restee en attente. Le
critere de sortie de la phase 0 (statut FERME PAR COMMIT) etait donc inatteignable
non pas faute de mesure, mais faute de PASSEUR. Un depot qui mesure et n'inscrit
pas produit exactement le meme silence qu'un depot qui ne mesure pas.

LE GARDE PROUVE ICI. Une generation est un objet IMMUABLE : elle date un sha et un
verdict. Le passeur doit donc MORDRE sur une generation deja inscrite dont le depot
diverge (il refuse, il nomme, il ne tranche pas tout seul) et LAISSER PASSER une
generation absente. Les deux assertions sont exigees par `_patron_garde` : la
premiere seule ne prouverait rien d'un passeur qui refuse tout, la seconde seule
rien d'un passeur qui ecrase tout.

Zero service externe : tout se joue dans tmp_path, aucun git, aucun reseau.
"""

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(Path(__file__).resolve().parent), str(RACINE / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_generation_inscrire as passeur  # noqa: E402
from _patron_garde import prouver_que_le_garde_mord  # noqa: E402


def _gen(nom="GEN-09999", statut="STABLE", sha="a" * 40, note="temoin"):
    return {"generation": nom, "statut": statut, "note": note,
            "cree_le": "2026-09-09T00:00:00+00:00", "depot": {"sha": sha, "branche": "alpha"}}


def _bac(tmp_path, depots=(), cibles=()):
    d, c = tmp_path / "attente", tmp_path / "inscrites"
    d.mkdir(parents=True, exist_ok=True)
    c.mkdir(parents=True, exist_ok=True)
    for g in depots:
        (d / (g["generation"] + ".json")).write_text(json.dumps(g), encoding="utf-8")
    for g in cibles:
        (c / (g["generation"] + ".json")).write_text(json.dumps(g), encoding="utf-8")
    return d, c


def test_une_generation_absente_est_inscrite_et_RELUE(tmp_path):
    """Le cas nominal — et la conclusion se prend sur la RELECTURE de la cible."""
    g = _gen()
    d, c = _bac(tmp_path, depots=[g])
    bilan = passeur.inscrire(d, c)
    assert [n for n, _s, _sha in bilan["inscrites"]] == ["GEN-09999.json"]
    assert not bilan["non_relues"], "inscrite sans relecture concluante"
    relu = json.loads((c / "GEN-09999.json").read_text(encoding="utf-8"))
    assert relu["depot"]["sha"] == "a" * 40
    assert relu["statut"] == "STABLE"


def test_le_passeur_mord_sur_une_generation_divergente(tmp_path):
    """Garde append-only, prouve des DEUX cotes par le patron canonique.

    Refuse : le depot contredit une generation deja inscrite (sha different) —
    reecrire choisirait en silence laquelle des deux versions est la vraie.
    Admis : la generation n'est pas encore inscrite.
    """
    def exercer(cas):
        depots, cibles = cas
        d, c = _bac(tmp_path / str(id(cas)), depots=depots, cibles=cibles)
        return passeur.inscrire(d, c)

    inscrite = _gen(sha="a" * 40)
    contredite = _gen(sha="b" * 40)  # meme nom, sha DIFFERENT

    prouver_que_le_garde_mord(
        nom="append-only des generations",
        exercer=exercer,
        entree_refusee=([contredite], [inscrite]),
        entree_admise=([_gen(nom="GEN-09998")], []),
        est_un_refus=lambda bilan: bool(bilan["divergentes"]) and not bilan["inscrites"],
    )


def test_une_generation_deja_inscrite_a_l_identique_n_est_pas_reecrite(tmp_path):
    """Un depot residuel se CONSTATE, il ne se rejoue pas."""
    g = _gen()
    d, c = _bac(tmp_path, depots=[g], cibles=[g])
    avant = (c / "GEN-09999.json").read_text(encoding="utf-8")
    bilan = passeur.inscrire(d, c)
    assert bilan["identiques"] == ["GEN-09999.json"]
    assert not bilan["inscrites"]
    assert (c / "GEN-09999.json").read_text(encoding="utf-8") == avant


def test_un_depot_illisible_est_NOMME_et_n_inscrit_rien(tmp_path):
    """Trois etats, jamais deux : ce qu'on n'a pas su lire se DIT."""
    d, c = _bac(tmp_path)
    (d / "GEN-09997.json").write_text("{ ceci n est pas du json", encoding="utf-8")
    bilan = passeur.inscrire(d, c)
    assert not bilan["inscrites"]
    assert any(n == "GEN-09997.json" for n, _e in bilan["illisibles"]), (
        "un depot illisible avale en silence est indiscernable d'un depot absent")
    assert not (c / "GEN-09997.json").exists()


def test_sans_depot_le_passeur_ne_pretend_rien(tmp_path):
    """Contre-epreuve : rien a faire n'est pas un echec, et pas un succes non plus."""
    d, c = _bac(tmp_path)
    bilan = passeur.inscrire(d, c)
    assert not any(bilan[k] for k in bilan)


def test_le_point_d_entree_traverse_les_drapeaux(tmp_path):
    """Le CLI, pas seulement la fonction.

    Regle du depot, payee : `check()` passait ses tests pendant que `--check` mourait
    en NameError. `--depuis` sert a REMONTER une generation produite dans le worktree
    de reference (T0) ; si le drapeau ne traversait pas, la preuve resterait prisonniere
    de l'endroit ou elle a ete produite.
    """
    g = _gen(nom="GEN-09996")
    d, c = _bac(tmp_path, depots=[g])
    rc = passeur.main(["--depuis", str(d), "--vers", str(c)])
    assert rc == 0, "le point d'entree rend %s" % rc
    assert (c / "GEN-09996.json").is_file(), "le drapeau --vers n'a pas ete honore"


def test_une_source_absente_est_DITE_et_ne_vaut_pas_succes(tmp_path):
    """ABSENT se nomme : un repertoire introuvable n'est pas un repertoire vide."""
    rc = passeur.main(["--depuis", str(tmp_path / "nulle_part"),
                       "--vers", str(tmp_path / "cible")])
    assert rc == 0
    assert not (tmp_path / "cible").exists()
