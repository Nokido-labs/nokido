"""NR — une table protegee en LECTURE ne peut pas rester librement EFFACABLE.

AUDIT SECURITE 2026-09-18, classe AI-AND-LLM. `sanitize_sql` n'inspectait que
les SELECT — sa propre docstring le disait, et personne n'avait tire le fil.
Mesure sur le chemin reel du hub, sans modifier une seule ligne de donnee :

    SELECT rowid FROM system_rules LIMIT 1          -> SECRET GUARD: SQL bloque
    UPDATE system_rules SET rowid=rowid WHERE 0=1   -> Mutation OK

LIRE une table sensible etait interdit, l'ECRIRE etait permis. `event_log` est
dans cette liste : le journal d'audit pouvait etre efface par la route meme dont
il refusait la lecture. Une protection qui couvre la confidentialite et laisse
l'integrite ouverte garde le secret d'une donnee que n'importe qui peut detruire.

La sonde qui a tranche merite d'etre notee, parce que la PREMIERE ne prouvait
rien : `UPDATE <table_absente>` rend « no such table » sur une connexion en
lecture seule COMME sur une connexion en ecriture — SQLite resout le schema
avant le droit d'ecrire. Ce qui discrimine, c'est une table REELLE avec un
`WHERE 0=1` : zero ligne touchee, et pourtant le droit d'ecriture est exige.

Deux defauts jumeaux fermes dans la meme passe, l'un et l'autre mesures :

  - FAUX NEGATIF (preexistant, sur la LECTURE) : `SELECT * FROM "system_rules"`
    passait. Le garde n'acceptait qu'un `\\w+` nu, donc une paire de guillemets
    suffisait a le franchir — sans aucune injection.
  - FAUX POSITIF (introduit par l'extension, puis ferme) : un verbe d'ecriture
    dans un litteral de CHAINE declenchait un refus. Un garde qui crie a faux se
    fait desarmer ; les chaines sont donc neutralisees avant le scan, et elles
    SEULES — en SQLite `"..."` est un identifiant, le vider rouvrirait le
    contournement ci-dessus.

PORTEE, dite franchement : ces motifs lisent du TEXTE. Ce test verrouille la fin
d'une INVERSION, il ne pretend pas faire de `sanitize_sql` le garde ultime de
l'integrite. Gouverner l'ecriture pour de bon passera par l'AUTORITE de
l'appelant (ring, agent), pas par un motif plus long.
"""

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (RACINE, RACINE / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

G = pytest.importorskip("app.forge_secret_guard")


def _verdict(sql):
    return G.sanitize_sql(sql, "NR", 2)


# Le defaut EXACT mesure le 2026-09-18, en tete de liste.
ECRITURES_INTERDITES = [
    "UPDATE system_rules SET rowid = rowid WHERE 0 = 1",
    "DELETE FROM event_log",
    "DROP TABLE system_rules",
    "drop table if exists event_log",
    "INSERT INTO shared_prompt_log VALUES (1)",
    "INSERT OR REPLACE INTO promotion_queue VALUES (1)",
    "ALTER TABLE event_log ADD COLUMN x",
]

# Le meme contournement, ecrit avec des identifiants CITES.
ECRITURES_CITEES = [
    'UPDATE "system_rules" SET x = 1',
    "DELETE FROM [event_log]",
    "DELETE FROM `event_log`",
]

LECTURES_INTERDITES = [
    "SELECT * FROM system_rules",
    'SELECT * FROM "system_rules"',
    "SELECT * FROM [system_rules]",
]

# Ce qui doit continuer de passer — un garde trop large est un garde qu'on retire.
AUTORISE = [
    "SELECT id FROM rag_chunks LIMIT 5",
    "UPDATE task_queue SET status = 'done' WHERE id = 1",
    "DELETE FROM watch_jobs WHERE id = 2",
    "INSERT INTO agent_messages VALUES (1)",
    # nom VOISIN d'une table protegee, mais distinct
    "CREATE TABLE event_log_archive_2026 (x)",
    # le verbe vit dans une CHAINE : c'est du texte, pas une intention
    "SELECT 'update system_rules' AS texte",
    "SELECT x FROM notes WHERE t = 'delete from event_log'",
]


@pytest.mark.parametrize("sql", ECRITURES_INTERDITES)
def test_ecrire_une_table_sensible_est_refuse(sql):
    v = _verdict(sql)
    assert v is not None, (
        f"ECRITURE non gardee sur une table sensible : {sql!r}. C'est l'inversion "
        "du 2026-09-18 — lecture interdite, ecriture permise."
    )


@pytest.mark.parametrize("sql", ECRITURES_CITEES)
def test_un_identifiant_cite_ne_franchit_pas_le_garde(sql):
    assert _verdict(sql) is not None, (
        f"garde franchi par une simple paire de guillemets : {sql!r}"
    )


@pytest.mark.parametrize("sql", LECTURES_INTERDITES)
def test_la_lecture_reste_gardee(sql):
    """NON-REGRESSION — l'extension ne doit rien retirer au garde d'origine."""
    assert _verdict(sql) is not None, f"la lecture sensible n'est plus gardee : {sql!r}"


@pytest.mark.parametrize("sql", AUTORISE)
def test_aucun_faux_positif_sur_le_trafic_ordinaire(sql):
    v = _verdict(sql)
    assert v is None, (
        f"refus a tort de {sql!r} -> {v}. Un garde qui crie a faux se fait desarmer."
    )


def test_le_refus_nomme_le_verbe():
    """Un refus qui ne distingue pas une lecture d'un effacement se lit comme une
    gene de confort. Le message doit dire LEQUEL des deux a ete tente."""
    ecriture = _verdict("DELETE FROM event_log")
    lecture = _verdict("SELECT * FROM event_log")
    assert "ECRITURE" in ecriture, f"le refus d'ecriture ne se nomme pas : {ecriture}"
    assert "ECRITURE" not in lecture, f"une lecture est rapportee comme ecriture : {lecture}"


def test_les_chaines_sont_neutralisees_sans_vider_les_identifiants():
    """Les deux moities de la meme decision, verifiees ensemble.

    Vider les quotes SIMPLES tue le faux positif ; vider les DOUBLES rouvrirait
    le contournement par identifiant cite. Tester l'une sans l'autre laisserait
    passer une correction qui echange un defaut contre son symetrique.
    """
    assert _verdict("SELECT 'drop table system_rules' AS t") is None, (
        "un verbe dans une chaine declenche encore un refus"
    )
    assert _verdict('DROP TABLE "system_rules"') is not None, (
        "les identifiants cites ne sont plus vus : les quotes doubles ont ete "
        "neutralisees a tort"
    )
