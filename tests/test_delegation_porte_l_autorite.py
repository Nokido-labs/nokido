"""TDD — une delegation transporte une AUTORITE, pas seulement un nom.

MESURE DU 2026-09-12. La table `tasks` de `sandbox/tasks.db` porte :

    id, description, agent, status, result, created_at, updated_at,
    job_id, from_agent, scorecard_json, lease_until, attempt,
    checkpoint, progress_at

`from_agent` est le NOM du delegant. Aucune colonne ne porte son AUTORITE.
Or un nom est une declaration, pas une autorite — c'est la raison d'etre du
plancher anti-spoof a ring 4 sur les identites d'en-tete.

CONSEQUENCE : l'enfant s'execute plus tard, dans un autre processus, sous sa
propre identite et avec SON ring. `C ⊆ P` n'est pas seulement non verifie, il
est INVERIFIABLE : la capacite du parent n'existe nulle part au moment ou
l'enfant agit.

CE QUE CE BLOC LIVRE, ET CE QU'IL NE LIVRE PAS :
  - il fait TRANSPORTER l'autorite (colonne `from_ring`, ecrite a l'assign,
    rendue au claim). Un consommateur existe : le claim la restitue a l'agent
    qui prend la tache.
  - il n'IMPLEMENTE PAS l'attenuation. L'enfant continue d'agir avec son
    propre ring ; borner ses appels a l'autorite du parent demande une notion
    de contexte d'execution qui n'existe pas dans le hub. Transporter n'est
    pas contraindre, et ce fichier ne pretend pas le contraire.

LE PIEGE QUI COMPTE : une autorite ABSENTE (ligne ancienne, NULL, valeur
illisible) ne doit jamais se lire `0` — ce serait MASTER. Elle vaut le ring
le MOINS privilegie. C'est la regle « UNKNOWN n'est pas NO », appliquee dans
le seul sens qui ne fabrique pas de privilege.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
for _p in (str(RACINE.parent), str(RACINE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

REG = pytest.importorskip("nokido_agent.app.forge_mcp_registry")

UNTRUSTED = 4


@pytest.fixture
def registre_isole(tmp_path, monkeypatch):
    """`_task_db` derive son chemin de `self.root` : on l'isole.

    La base de taches de production est partagee avec d'autres surfaces
    (Gemini autonome, Antigravity, agt_task_executor) — un test n'y touche pas.
    """
    reg = REG.get_registry()
    (tmp_path / "sandbox").mkdir()
    monkeypatch.setattr(reg, "root", tmp_path, raising=False)
    return reg


def test_la_table_des_taches_porte_l_autorite_du_delegant(registre_isole):
    conn = registre_isole._task_db()
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()}
    finally:
        conn.close()
    assert "from_agent" in cols, "la provenance par NOM a disparu"
    assert "from_ring" in cols, (
        "la table des taches porte le NOM du delegant mais pas son AUTORITE : "
        "l'enfant ne peut pas etre borne a ce que le parent avait. "
        "Colonnes: %s" % sorted(cols))


@pytest.mark.parametrize("valeur", [None, "", "   ", "abc", [], {}, "None"])
def test_une_autorite_absente_vaut_le_moins_privilegie(valeur):
    """LE PIEGE. NULL lu comme 0 donnerait MASTER a toute ligne ancienne."""
    assert hasattr(REG.ToolRegistry, "_ring_delegant"), (
        "aucune fonction ne convertit l'autorite stockee en ring : chaque "
        "lecteur inventera sa propre regle, et la plus permissive gagnera")
    r = REG.ToolRegistry._ring_delegant(valeur)
    assert r == UNTRUSTED, (
        "autorite %r lue comme ring %r : une autorite absente ou illisible "
        "doit valoir le MOINS privilegie, jamais le plus" % (valeur, r))


@pytest.mark.parametrize("valeur,attendu", [(0, 0), (1, 1), (4, 4), ("2", 2),
                                            (-1, -1)])
def test_controle_positif_une_autorite_lisible_est_rendue_telle_quelle(valeur,
                                                                       attendu):
    """Sans lui, une fonction qui rendrait toujours 4 passerait le test
    precedent tout en detruisant l'information."""
    assert REG.ToolRegistry._ring_delegant(valeur) == attendu


def _poser_tache(reg, tid, from_ring, agent="WORKER"):
    """Insere une tache directement, pour maitriser `from_ring` a la source."""
    conn = reg._task_db()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO tasks(id,description,agent,status,result,"
            "created_at,updated_at,job_id,from_agent,from_ring) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (tid, "desc", agent, "pending", None, "2026-09-12", "2026-09-12",
             None, "DELEGANT", from_ring))
        conn.commit()
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_le_claim_restitue_l_autorite_du_delegant(registre_isole):
    """Le consommateur EXISTE : sans lui la colonne serait un champ mort."""
    import json
    _poser_tache(registre_isole, "t_avec_autorite", from_ring=3)
    rep = json.loads(await registre_isole.handle_task_claim(
        {"agent": "WORKER"}, "NR_TEST", 1))
    assert rep.get("ok") is True, rep
    assert rep.get("from_ring") == 3, (
        "le claim ne restitue pas l'autorite du delegant : %r" % rep)
    assert "attenuation" in rep, (
        "le claim ne DIT pas que l'autorite est transportee sans etre imposee : "
        "un lecteur croira que l'enfant est borne")


@pytest.mark.asyncio
async def test_une_tache_ancienne_se_claime_au_moins_privilegie(registre_isole):
    """LE PIEGE, sur le chemin reel.

    Toute ligne anterieure au 2026-09-12 a `from_ring` NULL. Si le claim la
    rendait telle quelle, un lecteur faisant `int(x or 0)` obtiendrait MASTER.
    """
    import json
    _poser_tache(registre_isole, "t_ancienne", from_ring=None)
    rep = json.loads(await registre_isole.handle_task_claim(
        {"agent": "WORKER"}, "NR_TEST", 1))
    assert rep.get("ok") is True, rep
    assert rep.get("from_ring") == UNTRUSTED, (
        "une tache sans autorite enregistree est rendue avec %r : elle doit "
        "valoir le ring le MOINS privilegie" % rep.get("from_ring"))


def test_une_autorite_hors_echelle_est_refusee(registre_isole):
    """Un ring hors de l'echelle declaree n'est pas une autorite, c'est du bruit.

    Meme famille que la sentinelle `99` mesuree le meme jour : une valeur hors
    echelle ne se lit pas, et dans le doute elle ne doit pas privilegier.
    """
    for hors in (-2, 5, 99, -99):
        assert REG.ToolRegistry._ring_delegant(hors) == UNTRUSTED, (
            "ring hors echelle %r accepte tel quel" % hors)
