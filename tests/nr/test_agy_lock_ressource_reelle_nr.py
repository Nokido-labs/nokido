"""NR — B1 : AGY CLI et AGY M2M se decouplent par RESSOURCE REELLE.

Ecrit ROUGE avant le correctif (methode ancree 2026-09-08 : le NR d'abord, et il
doit echouer pour prouver qu'il mesure quelque chose).

CE QUE CE NR EMPECHE DE REVENIR — quatre defauts MESURES le 2026-09-12, pas
quatre precautions de style :

1. `app/forge_lock_manager.py` n'etait importe par AUCUN module du depot
   (`findstr /s /m /c:"forge_lock_manager"` sur `app/*.py` et `tools/*.py` ne
   rend QUE le fichier lui-meme). Un mecanisme present et non cable n'est pas
   une securite, c'est une dette de cablage.
2. Son `DEFAULT_DB` pointait `ROOT/RAG/embeddings.db`, qui porte la MEME taille
   que `%NOKIDO_DATA%\embeddings.db` (26 519 080 960 octets, table `locks_state` deja
   presente) : le verrou ecrivait dans la base GELEE de 24,7 Go que la roadmap
   sort de la chaine critique.
3. Son `lock()` etait un `asyncio.Lock` IN-PROCESS. Or `forge_agent_proxy.GeminiCLI`
   tourne DANS le hub et `forge_task_executor._delegate_to_agy` dans un service
   SEPARE : l'exclusion entre les deux chemins etait donc strictement NULLE.
   Un verrou qui ne traverse pas les process ne verrouille rien de ce couple-la.
4. `recover_from_db()` passait TOUT `LOCKED` a `RELEASED` des qu'aucun token
   n'existait en memoire. Un holder VIVANT dans un autre process etait donc
   declare relache : `UNKNOWN` lu `NO`, la confusion que la constitution
   semantique interdit.

POURQUOI LE WORKDIR ET PAS L'IDENTITE « AGY ». Les deux chemins lisent la MEME
variable `LAFORGE_AGY_WORKDIR`, avec des defauts DIFFERENTS :
`app/forge_agent_proxy.py:1342` retombe sur `C:\\tmp`, `_delegate_to_agy` retombe
sur la racine du depot. Tous deux lancent agy avec `--add-dir <workdir>` et
`--dangerously-skip-permissions`, c'est-a-dire que agy ECRIT dans ce repertoire.
La ressource disputee est donc le repertoire RESOLU, et rien d'autre :
 - variable absente  -> deux repertoires distincts -> les deux chemins doivent
   tourner EN PARALLELE (c'est le decouplage demande) ;
 - variable posee    -> un seul repertoire -> ils doivent SERIALISER, sinon deux
   agy en `skip-permissions` s'ecrasent dans le meme arbre.
Une cle batie sur l'identite « AGY » se trompe dans les DEUX cas : elle bloque un
`ask` interactif pendant une delegation de 20 minutes, et elle ne dirait rien de
plus quand les repertoires coincident vraiment.

CE QUI N'EST PAS GARDE ICI, et pourquoi. Les deux chemins forcent aussi
`HOME`/`USERPROFILE`/`LOCALAPPDATA` vers le profil owner, donc vers le meme
magasin OAuth agy. Aucune corruption de ce magasin n'a ete MESUREE : y poser un
mutex serait un garde branche sur un signal que personne n'emet. Signal laisse
ouvert et nomme, pas instruit.
"""

from __future__ import annotations

import ast
import importlib
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

lm = importlib.import_module("nokido_agent.app.forge_lock_manager")


# --------------------------------------------------------------------------- #
# outils de test                                                              #
# --------------------------------------------------------------------------- #
def _pid_mort() -> int:
    """Un pid qui n'existe PAS. On le prouve, on ne le suppose pas."""
    import psutil

    for cand in range(999_999, 900_000, -7):
        if not psutil.pid_exists(cand):
            return cand
    pytest.skip("aucun pid libre trouve — mesure impossible, on ne conclut pas")
    raise AssertionError  # pragma: no cover


def _mgr(tmp_path: Path, nom: str = "a.db"):
    return lm.LockManager(db_path=tmp_path / nom)


# --------------------------------------------------------------------------- #
# 1. la cle vient du CHEMIN RESOLU, jamais de l'identite                       #
# --------------------------------------------------------------------------- #
def test_cle_derive_du_chemin_resolu_et_pas_de_l_identite_agy():
    a = lm.cle_workdir_agy(r"C:\tmp")
    b = lm.cle_workdir_agy("C:/tmp/")
    c = lm.cle_workdir_agy(r"c:\TMP")
    assert a == b == c, f"chemins equivalents -> cles differentes: {a!r} {b!r} {c!r}"
    assert "agy" in a.lower(), "la cle doit rester lisible dans un audit"
    # L'identite ne doit PAS suffire a fabriquer la cle : deux repertoires
    # distincts pour le meme agent donnent deux ressources distinctes.
    assert lm.cle_workdir_agy(r"C:\tmp") != lm.cle_workdir_agy(str(ROOT))


def test_les_deux_defauts_agy_donnent_deux_ressources_distinctes(monkeypatch):
    """Variable absente = le cas NOMINAL des deux chemins. Ils doivent diverger."""
    monkeypatch.delenv("LAFORGE_AGY_WORKDIR", raising=False)
    wd_cli = os.environ.get("LAFORGE_AGY_WORKDIR", r"C:\tmp")          # forge_agent_proxy:1342
    wd_m2m = os.environ.get("LAFORGE_AGY_WORKDIR", str(ROOT))          # _delegate_to_agy
    assert lm.cle_workdir_agy(wd_cli) != lm.cle_workdir_agy(wd_m2m)


def test_meme_workdir_donne_la_meme_ressource(monkeypatch):
    monkeypatch.setenv("LAFORGE_AGY_WORKDIR", str(ROOT))
    wd_cli = os.environ.get("LAFORGE_AGY_WORKDIR", r"C:\tmp")
    wd_m2m = os.environ.get("LAFORGE_AGY_WORKDIR", str(ROOT))
    assert lm.cle_workdir_agy(wd_cli) == lm.cle_workdir_agy(wd_m2m)


# --------------------------------------------------------------------------- #
# 2. le decouplage est EFFECTIF, et l'exclusion traverse les process           #
# --------------------------------------------------------------------------- #
def test_deux_workdirs_distincts_ne_se_bloquent_pas(tmp_path):
    m = _mgr(tmp_path)
    t1 = m.acquerir(lm.cle_workdir_agy(tmp_path / "cli"), "AGY_CLI", timeout=2)
    t2 = m.acquerir(lm.cle_workdir_agy(tmp_path / "m2m"), "AGY_M2M", timeout=2)
    assert t1 and t2, "deux ressources distinctes doivent etre prises en parallele"


def test_exclusion_traverse_les_process(tmp_path):
    """Deux LockManager sur le MEME fichier = deux process.

    Un `asyncio.Lock` in-process passe ce test a tort s'il n'est pas franchi :
    c'est pourquoi le second manager est un OBJET distinct.
    """
    db = tmp_path / "partage.db"
    a = lm.LockManager(db_path=db)
    b = lm.LockManager(db_path=db)
    assert a is not b
    cle = lm.cle_workdir_agy(tmp_path / "arbre")
    jeton = a.acquerir(cle, "AGY_CLI", timeout=2)
    assert jeton, "le premier doit obtenir le verrou"
    assert b.acquerir(cle, "AGY_M2M", timeout=1) is None, (
        "un verrou tenu par un holder VIVANT d'un autre process a ete accorde "
        "une seconde fois — l'exclusion ne traverse pas les process"
    )
    assert a.liberer(jeton) is True
    assert b.acquerir(cle, "AGY_M2M", timeout=2), "apres liberation, le voisin doit passer"


# --------------------------------------------------------------------------- #
# 3. trois etats du holder : VIVANT / MORT / INCONNU                           #
# --------------------------------------------------------------------------- #
def test_les_trois_etats_existent_et_sont_distincts():
    assert len({lm.ETAT_VIVANT, lm.ETAT_MORT, lm.ETAT_INCONNU}) == 3


def test_holder_vivant_garde_son_verrou(tmp_path):
    m = _mgr(tmp_path)
    cle = lm.cle_workdir_agy(tmp_path / "arbre")
    assert m.acquerir(cle, "AGY_CLI", timeout=2)
    bilan = m.recover_from_db()
    assert bilan["reclames"] == 0, "un holder VIVANT a ete depossede"
    assert bilan["vivants"] == 1
    assert m.get_state(cle).state == "LOCKED"


def test_holder_mort_est_repris(tmp_path):
    m = _mgr(tmp_path)
    cle = lm.cle_workdir_agy(tmp_path / "arbre")
    jeton = m.acquerir(cle, "AGY_M2M", timeout=2)
    assert jeton
    m._forcer_holder(cle, pid=_pid_mort(), boot=1.0)   # simule le process disparu
    bilan = m.recover_from_db()
    assert bilan["reclames"] == 1, f"un holder MORT n'a pas ete repris: {bilan}"
    assert m.acquerir(cle, "AGY_CLI", timeout=2), "la ressource doit redevenir prenable"


def test_holder_inconnu_psutil_absent_ne_libere_pas(tmp_path, monkeypatch):
    """psutil indisponible -> INCONNU. On ne vole pas un verrou qu'on ne sait pas lire."""
    m = _mgr(tmp_path)
    cle = lm.cle_workdir_agy(tmp_path / "arbre")
    assert m.acquerir(cle, "AGY_CLI", timeout=2)
    m._forcer_holder(cle, pid=_pid_mort(), boot=1.0)
    monkeypatch.setattr(lm, "psutil", None)
    etat, motif = lm.etat_holder(4242, 1.0)
    assert etat == lm.ETAT_INCONNU
    assert motif, "un etat INCONNU sans motif est un silence, pas une mesure"
    bilan = m.recover_from_db()
    assert bilan["reclames"] == 0, "un holder INCONNU a ete libere — UNKNOWN lu NO"
    assert bilan["inconnus"] == 1
    assert m.get_state(cle).state == "LOCKED"


def test_holder_inconnu_acces_refuse_ne_libere_pas(tmp_path, monkeypatch):
    """pid d'un AUTRE compte : psutil le voit exister puis refuse l'identite."""
    psutil = pytest.importorskip("psutil")
    m = _mgr(tmp_path)
    cle = lm.cle_workdir_agy(tmp_path / "arbre")
    assert m.acquerir(cle, "AGY_CLI", timeout=2)

    class _Refus:
        AccessDenied = psutil.AccessDenied
        NoSuchProcess = psutil.NoSuchProcess

        @staticmethod
        def pid_exists(_pid):
            return True

        @staticmethod
        def Process(_pid):
            raise psutil.AccessDenied(_pid)

    monkeypatch.setattr(lm, "psutil", _Refus)
    etat, motif = lm.etat_holder(os.getpid(), None)
    assert etat == lm.ETAT_INCONNU, f"acces refuse doit rendre INCONNU, rendu {etat}"
    assert motif
    assert m.recover_from_db()["reclames"] == 0


def test_pid_recycle_n_est_pas_le_holder(tmp_path):
    """Meme pid, autre `create_time` = autre process. Un pid seul ne prouve rien."""
    etat, motif = lm.etat_holder(os.getpid(), boot=1.0)
    assert etat == lm.ETAT_MORT, f"pid recycle lu {etat} ({motif})"


# --------------------------------------------------------------------------- #
# 3 bis. les BORNES et les CONDITIONS, pas seulement les cas nominaux          #
# --------------------------------------------------------------------------- #
# ⚠️ Ces tests existent parce que le cliquet de mutation a dit ce que les 16
# precedents taisaient : `app/forge_lock_manager.py` 8/12 mutants tues, avec
# deux survivants « comparaison » et deux survivants « booleen ». Des tests qui
# passent sans contraindre une borne rassurent sans garder — meme famille que les
# 14 tests hors SURFACES du 2026-09-12, sauf qu'ici la surface etait inscrite,
# donc la faiblesse s'est VUE.
@pytest.mark.parametrize("pid", [0, -1, -999])
def test_un_pid_non_positif_est_inconnu_jamais_mort(pid):
    """`pid <= 0` : la borne compte. Un pid absurde n'est pas une preuve de mort."""
    etat, motif = lm.etat_holder(pid, boot=1.0)
    assert etat == lm.ETAT_INCONNU, f"pid {pid} lu {etat}"
    assert motif


def test_la_tolerance_de_create_time_a_une_borne_des_DEUX_cotes():
    """L'ecart tolere est de 1 s. En-deca on reconnait le holder, au-dela non."""
    import psutil

    vrai = psutil.Process(os.getpid()).create_time()
    proche, _ = lm.etat_holder(os.getpid(), boot=vrai + 0.5)
    loin, _ = lm.etat_holder(os.getpid(), boot=vrai + 5.0)
    assert proche == lm.ETAT_VIVANT, "un ecart sous la tolerance doit rester VIVANT"
    assert loin == lm.ETAT_MORT, "un ecart au-dela de la tolerance doit rendre MORT"


def test_create_time_illisible_est_inconnu():
    """Une valeur enregistree non numerique ne se compare pas : INCONNU, pas MORT."""
    etat, motif = lm.etat_holder(os.getpid(), boot="pas-un-nombre")
    assert etat == lm.ETAT_INCONNU, f"lu {etat}"
    assert motif


def test_le_refus_est_DIT_et_pas_seulement_rendu(tmp_path):
    """`acquerir` qui rend None doit laisser un motif lisible, sinon le refus est
    indistinguable d'une panne."""
    db = tmp_path / "x.db"
    a, b = lm.LockManager(db_path=db), lm.LockManager(db_path=db)
    cle = lm.cle_workdir_agy(tmp_path / "arbre")
    assert a.acquerir(cle, "AGY_CLI", timeout=2)
    assert b.acquerir(cle, "AGY_M2M", timeout=0.2) is None
    assert b.dernier_refus, "un refus muet ne se distingue pas d'une panne"
    assert lm.ETAT_VIVANT in b.dernier_refus, f"le motif doit nommer l'etat: {b.dernier_refus!r}"


def test_liberer_un_jeton_inconnu_rend_faux(tmp_path):
    m = _mgr(tmp_path)
    assert m.liberer("lk_inexistant") is False
    jeton = m.acquerir(lm.cle_workdir_agy(tmp_path / "a"), "AGY_CLI", timeout=2)
    assert m.liberer(jeton) is True
    assert m.liberer(jeton) is False, "un jeton deja rendu ne libere pas deux fois"


def test_une_ressource_jamais_prise_est_FREE(tmp_path):
    m = _mgr(tmp_path)
    e = m.get_state(lm.cle_workdir_agy(tmp_path / "jamais"))
    assert e.state == "FREE"
    assert e.owner_agent is None
    assert e.motif, "meme FREE doit dire pourquoi"


# 3ᵉ passe sur le cliquet (9/12 tues apres la 2ᵉ, 3 survivants : 1 comparaison,
# 2 booleens). L'outil ne nomme que des CATEGORIES, jamais le mutant : on vise
# donc les bornes et les conditions encore non contraintes, et on le DIT plutot
# que de pretendre cibler un mutant precis.
# --------------------------------------------------------------------------- #
# 4ᵉ passe — sur les sites REELLEMENT mutes, plus par deduction                #
# --------------------------------------------------------------------------- #
# Les passes 2 et 3 ont tue 1 mutant sur 4 puis 0 sur 3 : deviner ne marche pas.
# Le recenseur de `forge_mutation_test` (`_Recenseur`, lecture seule, aucun droit
# d'ecriture requis) rend les sites REELS avec leur genre et leur ligne. Mesure :
# la surface est capee a 12 mutants et les 12 premiers sites en parcours prefixe
# tiennent TOUS dans les 236 premieres lignes — `_db_defaut`, `etat_holder`,
# `__init__`, `_init_schema`. Mes tests de la passe 3 visaient `acquerir`,
# `liberer` et `get_state`, tous HORS du cap : ils ne pouvaient rien tuer.
#
# Autre surprise de la mesure : le genre « booleen » ne designe pas une condition
# mais un LITTERAL `True`/`False` dans le code (`_genre` : `ast.Constant` dont la
# valeur est un bool). D'ou les deux sites sur la meme ligne `mkdir(parents=True,
# exist_ok=True)`.
def test_le_registre_cree_son_dossier_parent_absent(tmp_path):
    """`mkdir(parents=True)` : la base peut viser un dossier qui n'existe pas
    encore — c'est le cas d'un worktree neuf, ou `sandbox/` n'est pas cree."""
    cible = tmp_path / "pas" / "encore" / "la" / "locks.db"
    assert not cible.parent.exists()
    m = lm.LockManager(db_path=cible)
    assert cible.parent.exists(), "le dossier parent n'a pas ete cree"
    jeton = m.acquerir(lm.cle_workdir_agy(tmp_path / "a"), "AGY_CLI", timeout=2)
    assert jeton, "le registre doit etre utilisable apres creation du chemin"


def test_ouvrir_deux_fois_le_meme_registre_ne_leve_pas(tmp_path):
    """`mkdir(exist_ok=True)` : le second manager trouve le dossier DEJA la.
    Sans ce drapeau, tout co-acces au meme registre echouerait a l'ouverture."""
    db = tmp_path / "dossier" / "locks.db"
    a = lm.LockManager(db_path=db)
    b = lm.LockManager(db_path=db)  # ne doit pas lever
    cle = lm.cle_workdir_agy(tmp_path / "arbre")
    assert a.acquerir(cle, "AGY_CLI", timeout=2)
    assert b.acquerir(cle, "AGY_M2M", timeout=0.3) is None


def test_mon_boot_rend_None_quand_psutil_manque(monkeypatch):
    """`_mon_boot` : sans psutil, on n'invente pas un create_time.

    C'est ce qui fait qu'un verrou pose sans preuve d'identite se relit ensuite
    en UNKNOWN plutot qu'en VIVANT — la chaine entiere depend de ce None.
    """
    monkeypatch.setattr(lm, "psutil", None)
    assert lm._mon_boot() is None


def test_mon_boot_rend_un_create_time_quand_psutil_est_la():
    import psutil

    v = lm._mon_boot()
    assert isinstance(v, float)
    assert abs(v - psutil.Process(os.getpid()).create_time()) < 1.0


def test_un_registre_ANCIEN_recoit_les_colonnes_de_holder(tmp_path):
    """Migration de schema : une table `locks_state` d'avant le 2026-09-12 n'a ni
    `holder_pid`, ni `holder_boot`, ni `holder_host`. Elles doivent etre AJOUTEES
    sans perdre les lignes — sinon le registre existant devient illisible et
    toute la detection de holder tombe."""
    import sqlite3

    db = tmp_path / "ancien.db"
    c = sqlite3.connect(str(db))
    c.execute("""CREATE TABLE locks_state (
        resource TEXT PRIMARY KEY, state TEXT NOT NULL, owner_agent TEXT,
        owner_token TEXT, locked_at REAL, released_at REAL, timeout_s REAL,
        queue_size INTEGER DEFAULT 0)""")
    c.execute("INSERT INTO locks_state VALUES ('vieux','RELEASED',NULL,NULL,1.0,2.0,30.0,0)")
    c.commit(); c.close()

    lm.LockManager(db_path=db)  # doit migrer sans lever

    c = sqlite3.connect(str(db))
    cols = {r[1] for r in c.execute("PRAGMA table_info(locks_state)")}
    reste = c.execute("SELECT COUNT(*) FROM locks_state WHERE resource='vieux'").fetchone()[0]
    c.close()
    for attendu in ("holder_pid", "holder_boot", "holder_host"):
        assert attendu in cols, f"colonne {attendu} non ajoutee : {sorted(cols)}"
    assert reste == 1, "la migration a perdu une ligne existante"


def test_une_ligne_RELEASED_n_est_pas_une_ligne_LOCKED(tmp_path):
    """Le registre garde la ligne apres liberation. Une ressource RELEASED doit
    etre reprenable ET se lire comme telle — sinon `if row and row[0]=="LOCKED"`
    n'est contraint que du cote « pas de ligne »."""
    m = _mgr(tmp_path)
    cle = lm.cle_workdir_agy(tmp_path / "arbre")
    jeton = m.acquerir(cle, "AGY_CLI", timeout=2)
    assert m.liberer(jeton) is True
    e = m.get_state(cle)
    assert e.state == "RELEASED", f"etat lu {e.state!r}"
    assert e.owner_agent is None, "un verrou relache ne garde pas son proprietaire"
    assert e.holder_etat == lm.ETAT_MORT, "une ligne non LOCKED n'a pas de holder vivant"
    assert e.motif, "meme RELEASED doit dire pourquoi"
    assert m.acquerir(cle, "AGY_M2M", timeout=2), "une ligne RELEASED doit etre reprenable"


def test_un_create_time_NON_ENREGISTRE_sur_un_pid_VIVANT_rend_INCONNU():
    """`boot is None` : le process existe, mais son identite n'est pas prouvee.

    C'est le cas d'un verrou pose par un chemin qui n'a pas pu lire son propre
    create_time. Rendre VIVANT serait fabriquer une preuve qu'on n'a pas ;
    rendre MORT depossederait un process bien vivant. Donc INCONNU.
    """
    etat, motif = lm.etat_holder(os.getpid(), boot=None)
    assert etat == lm.ETAT_INCONNU, f"pid vivant sans create_time lu {etat}"
    assert "create_time" in motif, f"le motif doit nommer ce qui manque : {motif!r}"


def test_la_tolerance_vaut_AUSSI_dans_le_passe():
    """L'ecart se mesure en valeur absolue : un create_time enregistre plus ANCIEN
    de 0,9 s reste le meme process, plus ancien de 5 s ne l'est plus."""
    import psutil

    vrai = psutil.Process(os.getpid()).create_time()
    proche, _ = lm.etat_holder(os.getpid(), boot=vrai - 0.9)
    loin, _ = lm.etat_holder(os.getpid(), boot=vrai - 5.0)
    assert proche == lm.ETAT_VIVANT, "un ecart NEGATIF sous la tolerance reste VIVANT"
    assert loin == lm.ETAT_MORT


def test_un_timeout_NUL_refuse_sans_attendre(tmp_path):
    """`timeout=0` : la borne est franchie des le premier tour, donc un seul essai
    et aucun recul. Sans ce test, la comparaison de la boucle d'attente n'est
    contrainte que par le haut."""
    import time as _t

    db = tmp_path / "z.db"
    a, b = lm.LockManager(db_path=db), lm.LockManager(db_path=db)
    cle = lm.cle_workdir_agy(tmp_path / "arbre")
    assert a.acquerir(cle, "AGY_CLI", timeout=2)
    t0 = _t.time()
    assert b.acquerir(cle, "AGY_M2M", timeout=0) is None
    assert _t.time() - t0 < 1.5, "un timeout nul ne doit pas attendre"
    assert b.dernier_refus


def test_liberer_ne_casse_pas_si_le_verrou_asyncio_n_est_pas_pris(tmp_path):
    """`liberer` touche aussi le verrou in-process. Il n'est pris que par le
    chemin async ; sur le chemin SYNC il ne l'est jamais, et le relacher
    leverait. La condition qui l'evite doit rester contrainte."""
    m = _mgr(tmp_path)
    cle = lm.cle_workdir_agy(tmp_path / "arbre")
    jeton = m.acquerir(cle, "AGY_CLI", timeout=2)
    assert cle not in m._locks or not m._locks[cle].locked()
    assert m.liberer(jeton) is True


def test_list_locked_voit_le_voisin_pas_seulement_soi(tmp_path):
    """`list_locked` lisait la memoire de CE process : elle etait aveugle au voisin."""
    db = tmp_path / "y.db"
    a, b = lm.LockManager(db_path=db), lm.LockManager(db_path=db)
    cle = lm.cle_workdir_agy(tmp_path / "arbre")
    assert a.acquerir(cle, "AGY_CLI", timeout=2)
    vus = b.list_locked()
    assert [s.resource for s in vus] == [cle], f"le voisin ne voit pas le verrou: {vus}"
    assert vus[0].owner_agent == "AGY_CLI"
    assert vus[0].holder_etat == lm.ETAT_VIVANT


# --------------------------------------------------------------------------- #
# 4. la base par defaut n'est pas la base gelee                               #
# --------------------------------------------------------------------------- #
def test_db_par_defaut_n_est_pas_la_base_gelee():
    d = str(lm.DEFAULT_DB).replace("\\", "/").lower()
    assert not d.endswith("rag/embeddings.db"), (
        f"le verrou ecrirait dans la base gelee de 24,7 Go: {lm.DEFAULT_DB}"
    )
    assert "embeddings.db" not in d, f"DEFAULT_DB = {lm.DEFAULT_DB}"


def test_db_par_defaut_ne_depend_d_aucun_fichier_non_versionne(monkeypatch):
    """⚠️ Ce test existe parce que le precedent a PASSE a tort.

    Premiere version du correctif : `_db_defaut()` appelait
    `forge_db_path.m2m_path()`. Vert dans l'arbre principal, ROUGE dans le
    worktree detache de la CI de reference, sur
    `.../worktree/rag/embeddings.db` — parce que `m2m_path()` ne rend
    `sandbox/m2m.db` QUE si `sandbox/m2m.switch` existe, et que ce fichier n'est
    pas versionne. Un registre dont l'emplacement depend d'un fichier absent du
    depot change de cible selon le checkout : c'est la CI qui l'a dit, pas la
    relecture.
    """
    monkeypatch.delenv("LAFORGE_LOCKS_DB", raising=False)
    p = str(lm._db_defaut()).replace("\\", "/").lower()
    assert "embeddings.db" not in p, f"_db_defaut() vise la base du RAG: {p}"
    assert p.endswith("locks.db"), f"le registre doit avoir son fichier dedie: {p}"


def test_db_par_defaut_reste_surchargeable(monkeypatch, tmp_path):
    cible = tmp_path / "ailleurs.db"
    monkeypatch.setenv("LAFORGE_LOCKS_DB", str(cible))
    assert lm._db_defaut() == cible


# --------------------------------------------------------------------------- #
# 5. le cablage est PROUVE par l'AST, pas par une MENTION                      #
# --------------------------------------------------------------------------- #
def _corps(src: str, classe: str | None, fonction: str):
    """Le noeud de la fonction visee, ou None. On ne cherche PAS dans tout le
    fichier : `ask` existe sur une quarantaine de providers."""
    arbre = ast.parse(src)
    portee = arbre
    if classe:
        portee = next(
            (n for n in ast.walk(arbre) if isinstance(n, ast.ClassDef) and n.name == classe),
            None,
        )
        if portee is None:
            return None
    for n in ast.walk(portee):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == fonction:
            return n
    return None


def _appelle(noeud, nom: str) -> bool:
    for n in ast.walk(noeud):
        if isinstance(n, ast.Call):
            f = n.func
            if getattr(f, "id", None) == nom or getattr(f, "attr", None) == nom:
                return True
    return False


@pytest.mark.parametrize(
    "relatif,classe,fonction,prise,liberation",
    [
        ("app/forge_agent_proxy.py", "GeminiCLI", "ask", "lock", "release"),
        ("tools/forge_task_executor.py", None, "_delegate_to_agy", "acquerir", "liberer"),
    ],
)
def test_les_deux_sites_agy_prennent_le_verrou(relatif, classe, fonction, prise, liberation):
    """Le defaut d'origine : AUCUN site n'appelait ce module.

    ⚠️ Ce test lisait d'abord `"cle_workdir_agy" in src`. C'est une MENTION, pas
    une structure — un commentaire, une docstring ou une ligne morte l'auraient
    satisfait, et mes propres commentaires de cablage citent justement ce nom.
    Meme famille que les 5 faux positifs mesures le 2026-09-10. On tranche donc
    sur l'AST, dans la portee EXACTE, et on exige la paire : un verrou pris sans
    etre relache est pire que pas de verrou.
    """
    f = ROOT / relatif
    if not f.exists():
        pytest.skip(f"{relatif} illisible depuis ce compte — INDETERMINE, pas absent")
    noeud = _corps(f.read_text(encoding="utf-8", errors="replace"), classe, fonction)
    assert noeud is not None, f"{relatif}: {classe or ''}.{fonction} introuvable — cible deplacee"
    assert _appelle(noeud, "cle_workdir_agy"), (
        f"{relatif}: {fonction} lance agy sans deriver la cle de son workdir — "
        "mecanisme present et non cable"
    )
    assert _appelle(noeud, prise), f"{relatif}: {fonction} ne prend aucun verrou ({prise})"
    assert _appelle(noeud, liberation), f"{relatif}: {fonction} ne relache jamais le verrou ({liberation})"
