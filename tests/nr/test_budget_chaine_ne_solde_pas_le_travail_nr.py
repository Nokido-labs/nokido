"""Un palier de duree ne solde JAMAIS ce qui tourne ni ce qui est deja fait.

DIRECTIVE OWNER 2026-09-07 : « pas de palier de duree si pas fini ».

CE QUI A ETE MESURE. La veille `wj_fc7e31285b` porte, sur son etape `ingest` :

    status=completed, error="budget de chaine epuise : 2679 s > 1800 s
                             -- les etapes restantes n'ont pas ete jouees"

Les deux se contredisent, et c'est le second qui ment. Chronologie relevee :
`ingest` demarre a 16:05:28 et se termine a 16:34:19 -- il a bien tourne 29 minutes
et rendu **369 chunks**. Le budget (1800 s depuis `created_at` 15:37) a expire PENDANT
ce travail ; `_marquer_stalled` a alors ecrit son motif sur **TOUS** les noeuds de la
chaine, y compris ceux deja `completed` et celui qui etait en train de travailler.
L'etape a fini normalement et a ecrit `completed` par-dessus -- en gardant l'`error`.

Les 7 etapes de cette chaine sont `completed`. **Aucune n'a ete sautee.** Le message
« les etapes restantes n'ont pas ete jouees » etait donc faux, et il m'a fait annoncer
a l'owner une ingestion partielle qui n'existait pas. Un marquage qui salit un travail
REUSSI coute deux fois : il cache le succes, et il envoie la session suivante chercher
une perte imaginaire.

🔴 MON PREMIER DIAGNOSTIC ETAIT FAUX, et le NR existant l'a demasque. J'avais accuse
`_marquer_stalled` de salir des noeuds `completed`. Impossible : son appelant charge
`SELECT * FROM agent_chain_nodes WHERE status IN ('pending','retry_pending')` -- il ne
voit JAMAIS un noeud termine ou en cours. Mes trois premieres proprietes testaient donc
une situation qui ne se produit pas, exactement le piege de la fixture incapable de
produire le defaut (deja paye le meme soir sur le verrou SQLite).

LA VRAIE CAUSE, elle, est a l'ecriture du SUCCES : `run_node` faisait
`SET status=?, result_json=?, done_at=?` **sans toucher a `error`**. Un noeud solde
pendant qu'il attendait, puis repris et abouti, gardait donc le motif de son solde.
Deux affirmations contradictoires sur la meme ligne, et c'est la fausse qui se lit.

LE CONTRAT tenu ici :
  - un noeud qui ABOUTIT efface la trace de son echec precedent ;
  - le budget ne solde que ce qui ATTEND, et il DIT combien sur combien ;
  - un statut ABSENT vaut « en attente » : c'est ce que l'appelant reel fournit, et
    l'inverse desarmerait le solde des chaines reellement bloquees.

Meme famille que « une abstention n'est pas un acte » et que le kill-watchdog du
2026-09-05 : un seuil qui frappe un travail en cours mesure la duree, pas la sante.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : SQLite timeout=30 + busy_timeout=30000 sur la
#   VRAIE base (code appele) (l.86)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

DDL = """
CREATE TABLE agent_chain_nodes (
    id TEXT PRIMARY KEY, chain_id TEXT, step_index INTEGER, step_name TEXT,
    agent_role TEXT, status TEXT, error TEXT, created_at TEXT);
CREATE TABLE watch_jobs (
    id TEXT PRIMARY KEY, step TEXT, status TEXT, error TEXT,
    n_stored INTEGER, updated_at TEXT);
"""


def _chaine(tmp_path, statuts):
    """Base fabriquee au schema REEL, une chaine dont on choisit l'etat par etape."""
    base = tmp_path / "chain.db"
    conn = sqlite3.connect(base)
    conn.executescript(DDL)
    for i, st in enumerate(statuts):
        conn.execute(
            "INSERT INTO agent_chain_nodes VALUES (?,?,?,?,?,?,?,?)",
            ("n%d" % i, "wj_test", i, "etape%d" % i, "role", st,
             "resultat propre" if st == "completed" else None,
             "2026-09-07T15:00:00+00:00"))
    conn.execute("INSERT INTO watch_jobs VALUES (?,?,?,?,?,?)",
                 ("wj_test", "ingest", "en_cours", None, 5, ""))
    conn.commit()
    conn.close()
    return base


def _executeur(monkeypatch, base):
    from forge_chain_executor import ChainExecutor  # noqa: PLC0415

    ex = ChainExecutor()
    monkeypatch.setattr(ex, "_get_conn", lambda: sqlite3.connect(base), raising=False)
    return ex


def _noeuds(base):
    conn = sqlite3.connect(base)
    conn.row_factory = sqlite3.Row
    r = [dict(x) for x in conn.execute(
        "SELECT id, chain_id, step_index, status, error, created_at "
        "FROM agent_chain_nodes ORDER BY step_index")]
    conn.close()
    return r


def test_un_SUCCES_efface_la_trace_de_l_echec_precedent(tmp_path):
    """PROPRIETE 1 -- LE DEFAUT REELLEMENT PAYE.

    `status=completed` et `error="budget epuise"` ne peuvent pas etre vrais ensemble.
    Le noeud a ete solde pendant qu'il attendait, puis repris et abouti : l'ecriture
    du succes DOIT effacer le motif, sinon la ligne se contredit et c'est la fausse
    moitie qu'on lit. Verifie sur la source du chemin reel (`run_node`), qui ecrit ce
    statut -- une base fabriquee ne prouverait pas que c'est CETTE requete-la.
    """
    src = (ROOT / "app" / "forge_chain_executor.py").read_text(
        encoding="utf-8", errors="replace")
    i = src.find("SET status=?, result_json=?, done_at=?")
    assert i > 0, "le site d'ecriture du succes a change de forme"
    fenetre = src[i:i + 160]
    assert "error=NULL" in fenetre, (
        "l'ecriture du succes ne remet pas `error` a NULL : un noeud repris et "
        "abouti garde le motif de son echec precedent (mesure wj_fc7e31285b : "
        "completed + « budget de chaine epuise » sur la meme ligne)")


def test_un_statut_ABSENT_vaut_EN_ATTENTE(monkeypatch, tmp_path):
    """PROPRIETE 2. Le solde ne se desarme pas sur une clef manquante.

    L'appelant reel (`execute_pending`) ne charge que des noeuds en attente et ne
    garantit pas la presence de `status` dans les dicts transmis. Exiger la clef
    ferait taire le solde des chaines VRAIMENT bloquees -- une regression que le NR
    `test_veille_verdict_chaine_nr` a attrapee.
    """
    base = _chaine(tmp_path, ["pending", "pending"])
    ex = _executeur(monkeypatch, base)
    sans_statut = [{k: v for k, v in n.items() if k != "status"} for n in _noeuds(base)]
    ex._marquer_stalled(sans_statut, 2679.0)

    assert all(n["status"] == "stalled" for n in _noeuds(base)), (
        "un dict sans clef `status` doit rester soldable")


def test_seules_les_etapes_EN_ATTENTE_sont_soldees(monkeypatch, tmp_path):
    """PROPRIETE 3. Ce qui n'a pas commence, et cela seul, porte le motif du budget."""
    base = _chaine(tmp_path, ["completed", "running", "pending", "pending"])
    ex = _executeur(monkeypatch, base)
    ex._marquer_stalled(_noeuds(base), 2679.0)

    apres = _noeuds(base)
    soldes = [n for n in apres if n["status"] == "stalled"]
    assert len(soldes) == 2, "seules les 2 etapes en attente doivent etre soldees"
    assert apres[0]["status"] == "completed" and apres[1]["status"] == "running", (
        "defense en profondeur : un termine ou un en-cours transmis par erreur "
        "ne doit pas etre solde")
    for n in soldes:
        assert n["error"] and "budget" in n["error"], "le motif doit etre NOMME"


def test_le_motif_DIT_combien_d_etapes_sont_reellement_soldees(monkeypatch, tmp_path):
    """PROPRIETE 4. Un dénominateur honnete : « N sur M », pas « les restantes ».

    Sans le compte, « les etapes restantes n'ont pas ete jouees » se lit comme une
    perte totale meme quand il n'en reste aucune -- c'est ce qui m'a fait annoncer une
    ingestion partielle inexistante.
    """
    base = _chaine(tmp_path, ["completed", "running", "pending"])
    ex = _executeur(monkeypatch, base)
    ex._marquer_stalled(_noeuds(base), 2679.0)

    motif = [n["error"] for n in _noeuds(base) if n["status"] == "stalled"][0]
    assert "1" in motif and "3" in motif, (
        "le motif doit porter le compte reel des etapes soldees sur le total : %r" % motif)


def test_une_chaine_SANS_etape_en_attente_n_est_pas_declaree_stalled(monkeypatch, tmp_path):
    """PROPRIETE 5. Rien a solder = rien a dire. Le cas exact de wj_fc7e31285b.

    Ses 7 etapes etaient terminees : la chaine n'avait aucune dette, et le budget n'a
    fait que la salir.
    """
    base = _chaine(tmp_path, ["completed", "completed", "completed"])
    ex = _executeur(monkeypatch, base)
    ex._marquer_stalled(_noeuds(base), 2679.0)

    apres = _noeuds(base)
    assert not [n for n in apres if n["status"] == "stalled"], (
        "une chaine entierement terminee ne doit rien avoir de solde")

    conn = sqlite3.connect(base)
    job = conn.execute("SELECT status, error FROM watch_jobs WHERE id='wj_test'").fetchone()
    conn.close()
    assert not (job[1] or ""), (
        "le job d'une chaine terminee ne doit pas porter un motif de budget : %r" % (job,))
