"""L'attente sur verrou d'un test de la suite PURE doit tenir SOUS le budget de la suite.

MESURE DU 2026-09-07 (CI locale job_90ceb5e760eb, rc=1). La suite pure lance pytest
avec `--timeout=30` ; `forge_self_correction.anchor_solution` ouvre sa connexion avec
`busy_timeout=30000`. **30 n'est pas strictement superieur a 30.** Le garde d'abstention
de `test_self_correction_roundtrip_nr` (5 reprises + jitter, qui rend un `skip` en
disant « ecriture INDETERMINEE ») ne peut donc JAMAIS s'executer : la premiere attente
consomme deja tout le budget. Resultat mesure : pytest tue en plein test, **aucun
rapport JUnit ecrit**, et le gate refuse a raison de racheter un rc non nul sans preuve.
Un `UNKNOWN` est devenu la mort de toute la suite -- 8603 tests perdus pour un verrou.

Etat de la base au meme instant (sonde `BEGIN IMMEDIATE` a busy_timeout=0, 48 sondes
sur 12 s) : **47 verrouillees, taux 0,98, plus longue serie 8,5 s**. Le verrou n'est
donc pas une hypothese, et il ne disparaitra pas : la base est partagee avec les
daemons.

C'EST LE MOTIF DU KILL-WATCHDOG DU 2026-09-05, A L'IDENTIQUE : un seuil de kill pose a
la MEME valeur que le plus long blocage synchrone tolere. L'invariant deja paye une
fois : **le seuil de kill doit etre STRICTEMENT superieur au plus long blocage tolere**.
Ici on tient l'autre bout : on BORNE le blocage, sous le seuil.

Le remede suit le reflexe inscrit le 2026-09-06 (« un etat partage par N processus
bascule par un INTERRUPTEUR GLOBAL lu a chaque appel, jamais site par site ») : le
budget d'attente vit dans `forge_db_path`, l'organe qui porte deja le contrat
d'ecriture (`open_writer`, `write_retry`, `m2m_path`). Pas de systeme parallele.

TROIS ETAGES, comme la methode l'impose (owner 2026-09-07) :
  UNITAIRE     `busy_ms()` existe, lit la config, borne, et NOMME l'illisible.
  SIMULATION   base fabriquee + un voisin qui TIENT le verrou -> l'ecriture rend la
               main sous le budget, au lieu d'attendre 30 s.
  INTEGRATION  le lanceur reel de la suite pure pose un budget STRICTEMENT inferieur
               a son propre `--timeout`.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : SQLite timeout=30 (code appele) (l.145)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# Marge exigee entre le blocage tolere et le seuil de kill. 1/3, pour que les reprises
# avec recul + jitter du test appelant tiennent DANS le budget restant -- une marge de
# 1 ms serait « strictement inferieure » et ne laisserait la place a aucune reprise.
_MARGE = 3.0


# --------------------------------------------------------------------------- UNITAIRE
# Fonction pure, aucune base, aucun service : on interroge la config, rien d'autre.

def test_le_budget_d_attente_est_un_INTERRUPTEUR_lu_a_chaque_appel(monkeypatch):
    """PROPRIETE 1. Le budget se lit A CHAQUE APPEL, pas au chargement du module.

    Une constante figee a l'import ne peut pas etre baissee par le lanceur de la suite :
    les daemons deja demarres garderaient l'ancienne valeur (meme piege que la migration
    d'import « invisible jusqu'au redemarrage », mesure le 2026-09-05).
    """
    import forge_db_path as fdp  # noqa: PLC0415

    assert hasattr(fdp, "busy_ms"), (
        "forge_db_path.busy_ms() absent : le budget d'attente sur verrou n'a pas "
        "d'interrupteur global, il est en dur sur chaque site (30000 x 3 dans "
        "forge_self_correction) -- donc imbornable par le lanceur de la suite pure")
    monkeypatch.setenv("LAFORGE_SQLITE_BUSY_MS", "4000")
    assert fdp.busy_ms() == 4000, "la valeur doit etre relue a CHAQUE appel"
    monkeypatch.setenv("LAFORGE_SQLITE_BUSY_MS", "7000")
    assert fdp.busy_ms() == 7000, "un second appel doit voir la NOUVELLE valeur"


def test_un_budget_ILLISIBLE_retombe_sur_le_defaut_et_le_DIT(monkeypatch, capsys):
    """PROPRIETE 2. Trois etats : lu / absent / illisible -- jamais un zero silencieux.

    Un budget lu `0` mettrait `busy_timeout=0` : toute collision leverait aussitot, ce
    qui transformerait une attente normale en panne. `UNKNOWN != NO`.
    """
    import forge_db_path as fdp  # noqa: PLC0415

    monkeypatch.delenv("LAFORGE_SQLITE_BUSY_MS", raising=False)
    defaut = fdp.busy_ms()
    assert defaut > 0, "sans configuration, un DEFAUT positif, jamais 0"

    monkeypatch.setenv("LAFORGE_SQLITE_BUSY_MS", "pas-un-nombre")
    assert fdp.busy_ms() == defaut, "valeur illisible -> DEFAUT, pas 0, pas une exception"
    assert "LAFORGE_SQLITE_BUSY_MS" in capsys.readouterr().out, (
        "un repli doit se DIRE : un budget silencieusement ignore est indiscernable "
        "d'un budget applique")

    monkeypatch.setenv("LAFORGE_SQLITE_BUSY_MS", "0")
    assert fdp.busy_ms() > 0, "0 est refuse : ce serait 'lever a la premiere collision'"


# ------------------------------------------------------------------------- SIMULATION
# Base FABRIQUEE au schema reel (cree par Nokido lui-meme), voisin qui tient le verrou
# pour de vrai. Aucun service, aucune base de production touchee.

class _ConnexionEspionnee:
    """Proxy qui NOTE les PRAGMA emis, et delegue tout le reste a la vraie connexion.

    POURQUOI PAS UN VRAI VERROU (mesure 2026-09-07, premiere version de ce NR). Un
    voisin qui tient `BEGIN IMMEDIATE` DANS LE MEME PROCESSUS ne reproduit PAS le
    defaut : SQLite n'invoque pas son busy handler quand le conflit vient d'une autre
    connexion du meme process (ce serait un deadlock garanti), il rend SQLITE_BUSY
    immediatement. Le test passait donc au VERT sur un corps encore malade -- une
    fixture incapable de produire le defaut qu'elle pretend garder.

    On epingle donc la CAUSE, qui est deterministe et observable : la valeur de
    `busy_timeout` REELLEMENT posee sur la connexion. Le blocage de 30 s en est la
    consequence arithmetique, et il n'a pas besoin d'etre rejoue pour etre evite.
    """

    def __init__(self, vraie, journal: list):
        self._vraie, self._journal = vraie, journal

    def execute(self, sql, *a, **k):
        self._journal.append(str(sql))
        return self._vraie.execute(sql, *a, **k)

    def __getattr__(self, nom):
        return getattr(self._vraie, nom)


def test_l_attente_REELLEMENT_posee_est_celle_de_l_interrupteur(monkeypatch, tmp_path):
    """PROPRIETE 3. Le coeur du defaut mesure : 30 s d'attente sous un seuil de 30 s.

    Base FABRIQUEE (aucune base de production touchee), schema cree par le chemin REEL,
    et un espion sur la connexion : ce qui compte est le `busy_timeout` applique.
    """
    import forge_self_correction as fsc  # noqa: PLC0415

    base = tmp_path / "embeddings.db"
    monkeypatch.setattr(fsc, "_DB", base)
    monkeypatch.setenv("LAFORGE_SQLITE_BUSY_MS", "2000")

    journal: list = []
    vrai_connect = sqlite3.connect
    monkeypatch.setattr(
        sqlite3, "connect",
        lambda *a, **k: _ConnexionEspionnee(vrai_connect(*a, **k), journal))

    fsc.anchor_solution(problem="NR budget probe", solution="amorce",
                        example="n/a", domain="ci_smoke")

    # Sans cette garde, une ancre qui echouerait AVANT toute connexion rendrait le
    # test vert sur un journal vide : « rien vu » lu comme « rien a redire ».
    assert base.exists() and base.stat().st_size > 0, (
        "le chemin d'ecriture doit fonctionner sur base neuve, sinon la mesure ne "
        "porte sur rien")
    poses = [ln for ln in journal if "busy_timeout" in ln.replace(" ", "")]
    assert poses, "aucun busy_timeout pose : l'attente n'est pas gouvernee du tout"

    for ligne in poses:
        valeur = int(ligne.replace(" ", "").split("=")[-1].rstrip(";"))
        assert valeur == 2000, (
            "busy_timeout pose a %d ms alors que l'interrupteur demande 2000 : "
            "l'attente est en dur et ignore le budget de la suite. C'est ce qui a "
            "tue la suite pure du 2026-09-07 sans laisser de JUnit." % valeur)


def test_write_retry_ne_propage_JAMAIS_None_a_son_collaborateur(monkeypatch, tmp_path):
    """PROPRIETE 3bis. Une valeur « a decider » se resout AVANT la frontiere.

    MESURE 2026-09-07, regression du cycle 1 rattrapee par la CI complete. En rendant
    le budget configurable, `write_retry` s'est mis a appeler `open_writer(timeout=None)`
    -- le vrai `open_writer` resout `None`, mais les DOUBLURES de test ecrites contre le
    contrat d'avant (`lambda timeout=30.0: sqlite3.connect(...)`) recevaient `None`
    explicite, qui ECRASE leur defaut, et le passaient a `sqlite3.connect` :
    `TypeError: must be real number, not NoneType`. **8 tests casses, une seule cause**,
    dans deux fichiers qui n'avaient rien demande.

    La lecon n'est pas « corriger les doublures » : c'est qu'un `None` signifiant
    « decide toi-meme » ne doit pas TRAVERSER une frontiere. On le resout la ou on le
    connait ; le collaborateur ne recoit qu'un nombre. La fixture ci-dessous reproduit
    exactement la doublure qui a casse.
    """
    import forge_db_path as fdp  # noqa: PLC0415

    base = tmp_path / "t.db"
    vus: list = []

    def _doublure_contrat_d_avant(timeout=30.0, path=None):
        vus.append(timeout)
        return sqlite3.connect(str(base), timeout=timeout, isolation_level=None)

    monkeypatch.setattr(fdp, "open_writer", _doublure_contrat_d_avant)
    monkeypatch.setenv("LAFORGE_SQLITE_BUSY_MS", "5000")

    fdp.write_retry(lambda c: c.execute("CREATE TABLE t (x)"))

    assert vus, "write_retry doit passer par open_writer"
    assert vus[0] is not None, (
        "write_retry a propage None a son collaborateur : toute doublure ecrite "
        "contre le contrat precedent le donne a sqlite3.connect et leve "
        "TypeError (8 tests casses le 2026-09-07, deux fichiers FTS)")
    assert abs(float(vus[0]) - 5.0) < 0.01, (
        "le budget resolu doit venir de l'interrupteur (5000 ms), pas d'un defaut fige")


# ------------------------------------------------------------------------ INTEGRATION
# Le chemin REEL : le lanceur de la suite pure, tel qu'il tourne en CI.

def test_le_lanceur_de_la_suite_pure_BORNE_l_attente_sous_son_propre_timeout():
    """PROPRIETE 4. Le lanceur pose le budget, et la marge est REELLE.

    Verrouille les DEUX valeurs ensemble : lire `--timeout=30` seul ne dit rien, lire
    le budget seul non plus. C'est leur RAPPORT qui est la propriete -- exactement ce
    que le kill-watchdog du 05/09 avait laisse a deux endroits differents.
    """
    src = (ROOT / "tools" / "ci_local.py").read_text(encoding="utf-8", errors="replace")
    assert "--timeout=30" in src, "le seuil de kill par test de la suite pure a change"
    assert "LAFORGE_SQLITE_BUSY_MS" in src, (
        "le lanceur de la suite pure ne pose AUCUN budget d'attente : les tests "
        "heritent des 30 s en dur, egaux a leur propre timeout")

    import re  # noqa: PLC0415
    m = re.search(r'LAFORGE_SQLITE_BUSY_MS["\']\s*[:=]\s*["\']?(\d+)', src)
    assert m, "le budget pose par le lanceur doit etre une valeur LISIBLE dans la source"
    budget_s = int(m.group(1)) / 1000.0
    assert budget_s * _MARGE <= 30.0, (
        "budget d'attente %.1f s pour un timeout de 30 s : marge insuffisante. "
        "Une reprise avec recul et jitter doit tenir DANS le temps restant, sinon "
        "l'abstention reste inatteignable." % budget_s)


def test_le_socle_d_apprentissage_n_a_plus_d_attente_EN_DUR():
    """PROPRIETE 5. Cliquet : aucun site ne rejoue l'attente de 30 s en litteral.

    Trois sites portaient `busy_timeout=30000` en dur dans le socle. Un interrupteur
    global qui laisse des litteraux derriere lui ne gouverne rien -- c'est la « dette
    de cablage » deja nommee : l'existence d'un mecanisme n'est pas son effet.
    """
    src = (ROOT / "app" / "forge_self_correction.py").read_text(
        encoding="utf-8", errors="replace")
    restants = [ln for ln in src.splitlines()
                if "busy_timeout=30000" in ln.replace(" ", "")
                and not ln.lstrip().startswith("#")]
    assert not restants, (
        "%d site(s) gardent l'attente de 30 s en dur, hors de l'interrupteur : %r"
        % (len(restants), restants[:3]))


def test_l_ecrivain_gouverne_lit_le_MEME_interrupteur():
    """PROPRIETE 6. Une politique gouverne TOUS les chemins d'une capacite.

    `open_writer` est l'autre porte d'ecriture. Si elle garde son propre defaut, deux
    chemins de la meme capacite obeissent a deux budgets -- le defaut mesure le 06/09
    sur `embed()` / `embed_batch_fast`, ou un seul des deux lisait la politique.
    """
    src = (ROOT / "app" / "forge_db_path.py").read_text(encoding="utf-8", errors="replace")
    assert "def busy_ms" in src, "l'interrupteur vit dans forge_db_path"
    i_ow = src.find("def open_writer")
    assert i_ow > 0, "open_writer introuvable"
    assert "busy_ms(" in src[i_ow:i_ow + 2000], (
        "open_writer n'appelle pas busy_ms() : l'ecrivain gouverne garderait un budget "
        "different de celui du reste du corps")
