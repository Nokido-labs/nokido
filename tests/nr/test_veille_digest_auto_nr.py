"""NR — chaque veille digere SA matiere, et n'est marquee que sur SON resultat.

DEUX MESURES du 2026-08-31 ont motive ce fichier.

1. Le digest n'avait AUCUN consommateur : `findstr /s /m "forge_veille_digest"`
   sur `app/` et `tools/` rendait un seul fichier — lui-meme.
2. Le premier cablage rattachait la matiere par `since = min(created_at)`. Une
   FENETRE DE TEMPS n'est pas un lien de provenance : elle ramene tout ce qui a
   ete ingere dans la meme periode, y compris par d'autres chaines. Et un
   resultat global ne permet pas de savoir QUELLE veille a ete digeree, donc un
   echec partiel faisait passer pour traitee de la matiere qui ne l'etait pas.

La provenance vient de `watch_jobs.refined_json`, metadonnee EXISTANTE. Mesure
de couverture : exploitable sur 43 des 45 jobs, et sur les 31 candidats au
digest. Aucune colonne creee.

Ce que ces tests protegent :
  1. une veille ne digere QUE les documents que sa propre trace designe ;
  2. un document qu'aucune trace ne designe n'est attribue a PERSONNE ;
  3. un echec ne marque jamais comme digeree la matiere qu'il n'a pas traitee ;
  4. rejeu et restart ne produisent aucun doublon.

HERMETIQUE : base construite dans `tmp_path`, filigrane isole, digest INJECTE.
Aucun appel LLM, aucune base reelle, aucun service.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
for _p in (_ROOT, _ROOT / "app", _ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_veille_digest as vd  # noqa: E402
from app import forge_autonomous_loops as al  # noqa: E402

_OK_RES = {"statut": "DIGEST_OK", "docs": 3, "filtered_docs": 3, "documents": 3,
           "batches": 1, "success": 1, "failure": 0,
           "suggestions_generated": 2, "new_suggestions": 2,
           "llm_fails": 0, "suspect": False, "docs_marques": 3}


class _Backfill:
    """Digest INJECTE : retient ses appels, n'appelle aucun LLM.

    `regle` permet de faire echouer UNE veille et pas les autres — c'est le seul
    moyen de tester un echec PARTIEL.
    """

    def __init__(self, res=None, boom=None, regle=None):
        self.appels: list = []
        self._res = dict(res or _OK_RES)
        self._boom = boom
        self._regle = regle

    def __call__(self, limit=400, since="", ids=None, provider="", modele=""):
        ids = list(ids or [])
        self.appels.append({"limit": limit, "since": since, "ids": sorted(ids),
                            "provider": provider, "modele": modele})
        if self._regle is not None:
            return self._regle(ids)
        if self._boom is not None:
            raise self._boom
        return dict(self._res)


def _trace(*urls) -> str:
    return json.dumps({"candidats": [{"t": "titre", "u": u, "rel": 8} for u in urls],
                       "refus": []}, ensure_ascii=False)


def _db(tmp_path, jobs, docs=()) -> Path:
    """jobs = (id, status, n_stored, created_at, refined_json) ; docs = (id, url)."""
    p = tmp_path / "veille.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE watch_jobs (id TEXT PRIMARY KEY, status TEXT, "
              "n_stored INTEGER, created_at TEXT, refined_json TEXT)")
    c.executemany("INSERT INTO watch_jobs VALUES (?,?,?,?,?)", jobs)
    c.execute("CREATE TABLE biblio_raw (id TEXT PRIMARY KEY, url TEXT)")
    c.executemany("INSERT INTO biblio_raw VALUES (?,?)", docs)
    c.commit()
    c.close()
    return p


def _sante(tmp_path, monkeypatch, statut="200", nom="groq", age=0.0, sonde=None):
    """Instantane de sante ISOLE **et** sonde locale ISOLEE.

    DEUX capteurs a neutraliser depuis le contrat provider du 2026-08-31 : le
    releve partage (`endpoint_health_last.json`, qui juge le primaire distant) et
    la sonde locale d'Ollama (le secondaire). En laisser un seul branche sur le
    reel ferait mesurer la MACHINE au lieu du code -- et, pour la sonde locale,
    ferait sortir la suite sur le reseau au milieu d'un test unitaire.

    Le secondaire local est INJOIGNABLE par defaut : un test qui veut le voir
    repondre le declare, plutot que de l'heriter sans le savoir.
    """
    import time as _t
    p = tmp_path / "endpoint_health.json"
    p.write_text(json.dumps({"ts": _t.time() - age,
                             "par_statut": {statut: [nom]}}), encoding="utf-8")
    monkeypatch.setattr(al, "_SANTE_ENDPOINTS", p)
    monkeypatch.setattr(vd, "_SANTE_ENDPOINTS", p)
    monkeypatch.setattr(
        vd, "sonde_ollama",
        lambda *a, **k: (sonde if sonde is not None
                         else {"api": False, "raison": "isole par le test"}))
    return p


@pytest.fixture()
def filigrane(tmp_path, monkeypatch):
    """Filigrane ISOLE : sans cela les tests marqueraient des veilles reelles
    comme digerees et leur feraient perdre leur matiere en production.

    La sante des fournisseurs est isolee AUSSI, et par defaut au vert : sans
    cela chaque test lirait le releve REEL du poste et s'abstiendrait des que le
    LLM local est en panne — la suite mesurerait la machine, pas le code.
    """
    p = tmp_path / "digest_auto.json"
    monkeypatch.setattr(al, "_DIGEST_ETAT", p)
    _sante(tmp_path, monkeypatch)
    return p


def _etat(filigrane) -> dict:
    return json.loads(filigrane.read_text(encoding="utf-8"))


# ── 1 : chaque chaine ne digere QUE sa matiere ──────────────────────────────
def test_1_deux_chaines_digerent_chacune_leur_propre_matiere(tmp_path, filigrane):
    db = _db(tmp_path,
             [("wj_a", "completed", 2, "2026-08-31T10:00:00",
               _trace("http://a1", "http://a2")),
              ("wj_b", "completed", 1, "2026-08-31T11:00:00", _trace("http://b1"))],
             [("doc_a1", "http://a1"), ("doc_a2", "http://a2"),
              ("doc_b1", "http://b1")])
    bf = _Backfill()
    r = al.pat_veille_digest_auto(db=db, backfill=bf)
    assert r["digest"] == "fait"
    assert sorted(r["chain_ids_digeres"]) == ["wj_a", "wj_b"]
    par_ids = sorted(a["ids"] for a in bf.appels)
    assert par_ids == [["doc_a1", "doc_a2"], ["doc_b1"]]
    assert all(a["since"] == "" for a in bf.appels)


# ── 2 : la matiere orpheline n'est attribuee a personne ─────────────────────
def test_2_un_document_qu_aucune_trace_ne_designe_n_est_PAS_attribue(
        tmp_path, filigrane):
    db = _db(tmp_path,
             [("wj_a", "completed", 1, "2026-08-31T10:00:00", _trace("http://a1"))],
             [("doc_a1", "http://a1"), ("doc_orphelin", "http://ailleurs")])
    bf = _Backfill()
    al.pat_veille_digest_auto(db=db, backfill=bf)
    assert bf.appels[0]["ids"] == ["doc_a1"]


def test_2bis_une_veille_SANS_matiere_attribuable_ne_ment_pas(tmp_path, filigrane):
    """Ni digeree (pas dans `jobs_vus`), ni retentee chaque heure pour rien."""
    db = _db(tmp_path,
             [("wj_a", "completed", 5, "2026-08-31T10:00:00", _trace("http://absent"))],
             [("doc_x", "http://autre")])
    bf = _Backfill()
    r = al.pat_veille_digest_auto(db=db, backfill=bf)
    assert bf.appels == []
    assert r["chain_ids_sans_matiere"] == ["wj_a"]
    assert r["chain_ids_digeres"] == []
    e = _etat(filigrane)
    assert e["jobs_vus"] == []
    assert e["jobs_sans_matiere"] == ["wj_a"]
    bf2 = _Backfill()
    r2 = al.pat_veille_digest_auto(db=db, backfill=bf2)
    assert r2["digest"] == "rien a digerer"
    assert bf2.appels == []


def test_2ter_une_trace_illisible_ne_vaut_pas_toute_la_base():
    assert al._urls_du_job(None) == []
    assert al._urls_du_job("{pas du json") == []
    assert al._urls_du_job(json.dumps([1, 2])) == []
    assert al._urls_du_job(_trace("http://x")) == ["http://x"]


# ── 3 : echec PARTIEL ───────────────────────────────────────────────────────
def test_3_un_echec_partiel_ne_marque_que_ce_qui_a_reussi(tmp_path, filigrane):
    db = _db(tmp_path,
             [("wj_a", "completed", 1, "2026-08-31T10:00:00", _trace("http://a1")),
              ("wj_b", "completed", 1, "2026-08-31T11:00:00", _trace("http://b1"))],
             [("doc_a1", "http://a1"), ("doc_b1", "http://b1")])

    def regle(ids):
        if "doc_b1" in ids:
            raise RuntimeError("provider injoignable")
        return dict(_OK_RES)

    r = al.pat_veille_digest_auto(db=db, backfill=_Backfill(regle=regle))
    assert r["chain_ids_digeres"] == ["wj_a"]
    assert r["chain_ids_echoues"] == ["wj_b"]
    assert _etat(filigrane)["jobs_vus"] == ["wj_a"]
    bf2 = _Backfill()
    r2 = al.pat_veille_digest_auto(db=db, backfill=bf2)
    assert r2["chain_ids_digeres"] == ["wj_b"]
    assert [a["ids"] for a in bf2.appels] == [["doc_b1"]]


def test_3bis_tous_les_appels_LLM_echoues_valent_un_echec(tmp_path, filigrane):
    """`backfill` peut RENDRE un resultat sans avoir rien digere : lots traites,
    0 suggestion, llm_fails > 0. Le compter comme fait perdrait la matiere."""
    db = _db(tmp_path,
             [("wj_a", "completed", 1, "2026-08-31T10:00:00", _trace("http://a1"))],
             [("doc_a1", "http://a1")])
    bf = _Backfill(res={"docs": 5, "batches": 2, "new_suggestions": 0,
                        "llm_fails": 2, "suspect": True})
    r = al.pat_veille_digest_auto(db=db, backfill=bf)
    assert r["digest"] == "unavailable"
    assert r["chain_ids_echoues"] == ["wj_a"]
    assert r["jobs_marques_vus"] == 0


def test_3ter_zero_suggestion_SANS_echec_LLM_est_un_digest_legitime(
        tmp_path, filigrane):
    """Rien a suggerer n'est pas rien a faire : la matiere a bien ete lue."""
    db = _db(tmp_path,
             [("wj_a", "completed", 1, "2026-08-31T10:00:00", _trace("http://a1"))],
             [("doc_a1", "http://a1")])
    bf = _Backfill(res={"docs": 5, "batches": 2, "new_suggestions": 0,
                        "llm_fails": 0, "suspect": True})
    r = al.pat_veille_digest_auto(db=db, backfill=bf)
    assert r["digest"] == "fait"
    assert r["chain_ids_digeres"] == ["wj_a"]


# ── 4 : echec TOTAL ─────────────────────────────────────────────────────────
def test_4_un_echec_total_ne_marque_AUCUN_job(tmp_path, filigrane):
    db = _db(tmp_path,
             [("wj_a", "completed", 1, "2026-08-31T10:00:00", _trace("http://a1")),
              ("wj_b", "completed", 1, "2026-08-31T11:00:00", _trace("http://b1"))],
             [("doc_a1", "http://a1"), ("doc_b1", "http://b1")])
    r = al.pat_veille_digest_auto(
        db=db, backfill=_Backfill(boom=RuntimeError("provider injoignable")))
    assert r["digest"] == "unavailable"
    assert r["chain_ids_digeres"] == []
    assert sorted(r["chain_ids_echoues"]) == ["wj_a", "wj_b"]
    assert r["jobs_marques_vus"] == 0
    assert not filigrane.exists()


# ── 5-6 : idempotence, restart ──────────────────────────────────────────────
def test_5_rejouer_le_meme_evenement_ne_produit_AUCUN_doublon(tmp_path, filigrane):
    db = _db(tmp_path,
             [("wj_a", "completed", 1, "2026-08-31T10:00:00", _trace("http://a1"))],
             [("doc_a1", "http://a1")])
    bf = _Backfill()
    assert al.pat_veille_digest_auto(db=db, backfill=bf)["digest"] == "fait"
    r2 = al.pat_veille_digest_auto(db=db, backfill=bf)
    assert r2["digest"] == "rien a digerer"
    assert len(bf.appels) == 1


def test_6_un_restart_ne_double_pas_le_traitement(tmp_path, filigrane):
    """Le filigrane est un FICHIER : il survit au process. C'est la seule chose
    qui distingue deja digere de pas encore digere apres un restart."""
    db = _db(tmp_path,
             [("wj_a", "completed", 1, "2026-08-31T10:00:00", _trace("http://a1"))],
             [("doc_a1", "http://a1")])
    al.pat_veille_digest_auto(db=db, backfill=_Backfill())
    assert _etat(filigrane)["jobs_vus"] == ["wj_a"]
    bf = _Backfill()
    assert al.pat_veille_digest_auto(db=db, backfill=bf)["digest"] == "rien a digerer"
    assert bf.appels == []


def test_6bis_une_veille_NEUVE_apres_restart_est_bien_digeree(tmp_path, filigrane):
    """Le filigrane retient les veilles vues, pas la capacite a en digerer."""
    db = _db(tmp_path,
             [("wj_a", "completed", 1, "2026-08-31T10:00:00", _trace("http://a1")),
              ("wj_b", "completed", 1, "2026-08-31T12:00:00", _trace("http://b1"))],
             [("doc_a1", "http://a1"), ("doc_b1", "http://b1")])
    filigrane.write_text(json.dumps({"jobs_vus": ["wj_a"]}), encoding="utf-8")
    bf = _Backfill()
    r = al.pat_veille_digest_auto(db=db, backfill=bf)
    assert r["chain_ids_digeres"] == ["wj_b"]
    assert [a["ids"] for a in bf.appels] == [["doc_b1"]]


# ── le contrat de declenchement (H4/H3 en amont) ────────────────────────────
@pytest.mark.parametrize("statut", ["completed_empty", "completed_dedup",
                                    "failed", "indetermine", "en_cours"])
def test_les_verdicts_sans_matiere_ne_declenchent_rien(tmp_path, filigrane, statut):
    db = _db(tmp_path,
             [("wj_x", statut, 5, "2026-08-31T10:00:00", _trace("http://a1"))],
             [("doc_a1", "http://a1")])
    bf = _Backfill()
    r = al.pat_veille_digest_auto(db=db, backfill=bf)
    assert r["digest"] == "rien a digerer"
    assert bf.appels == []


def test_un_completed_SANS_retention_ne_declenche_pas():
    """Ne jamais deduire la presence de matiere du seul statut."""
    assert al._digest_a_faire([{"id": "a", "status": "completed", "n_stored": 0}],
                              []) == []
    assert al._digest_a_faire([{"id": "a", "status": "completed", "n_stored": 1}],
                              []) != []


def test_completed_partial_avec_matiere_est_un_candidat():
    """Une chaine incomplete qui a QUAND MEME retenu quelque chose porte de la
    matiere reelle : la refuser perdrait ce qui a survecu."""
    assert al._digest_a_faire(
        [{"id": "a", "status": "completed_partial", "n_stored": 4}], []) != []
    assert al._digest_a_faire(
        [{"id": "a", "status": "completed_partial", "n_stored": 0}], []) == []


# ── le cap par tour ─────────────────────────────────────────────────────────
def test_le_tour_est_BORNE_le_reste_passe_au_tour_suivant(tmp_path, filigrane):
    """Sans cap, le premier tour reel rattrapait un MOIS d'arriere d'un coup :
    31 veilles candidates mesurees le 2026-08-31."""
    jobs = [("wj_%02d" % i, "completed", 1, "2026-08-31T%02d:00:00" % i,
             _trace("http://u%02d" % i)) for i in range(8)]
    docs = [("doc_%02d" % i, "http://u%02d" % i) for i in range(8)]
    db = _db(tmp_path, jobs, docs)
    bf = _Backfill()
    r = al.pat_veille_digest_auto(db=db, backfill=bf)
    assert len(bf.appels) == al._DIGEST_MAX_PAR_TOUR == 5
    assert len(r["chain_ids_digeres"]) == 5
    bf2 = _Backfill()
    r2 = al.pat_veille_digest_auto(db=db, backfill=bf2)
    assert len(r2["chain_ids_digeres"]) == 3
    assert len(_etat(filigrane)["jobs_vus"]) == 8


# ── l'etat ILLISIBLE, une fois de plus ──────────────────────────────────────
def test_un_filigrane_ILLISIBLE_fait_s_abstenir_pas_tout_redigerer(
        tmp_path, filigrane):
    """Repartir d'un filigrane vide redigererait tout l'historique et
    depenserait le LLM sur de la matiere deja traitee. ABSENT n'est pas VIDE."""
    filigrane.write_text("pas du json du tout {", encoding="utf-8")
    db = _db(tmp_path,
             [("wj_a", "completed", 1, "2026-08-31T10:00:00", _trace("http://a1"))],
             [("doc_a1", "http://a1")])
    bf = _Backfill()
    r = al.pat_veille_digest_auto(db=db, backfill=bf)
    assert r["digest"] == "non tente"
    assert "illisible" in r["skip"]
    assert bf.appels == []


def test_watch_jobs_illisible_ne_declenche_rien(tmp_path, filigrane):
    bf = _Backfill()
    r = al.pat_veille_digest_auto(db=tmp_path / "base_absente.db", backfill=bf)
    assert r["digest"] == "non tente"
    assert bf.appels == []


class _FiligraneKO:
    """LISIBLE mais non ECRIVABLE. Un dossier ne conviendrait pas : la lecture
    echouerait d'abord et l'on testerait la mauvaise branche."""

    def __init__(self, contenu: str):
        self._c = contenu
        self.parent = self

    def read_text(self, encoding=None):
        return self._c

    def mkdir(self, parents=False, exist_ok=False):
        return None

    def write_text(self, *a, **k):
        raise PermissionError("chemin hors ACL du compte")


def test_filigrane_non_ECRIVABLE_le_dit_et_ne_compte_aucun_marquage(
        tmp_path, monkeypatch):
    """Branche TIREE EN REEL le 2026-08-31, filigrane detourne hors ACL du compte
    sandbox. Le digest a tourne, le filigrane non : le dire, ne rien compter
    comme marque, et laisser le dedup md5 tenir le second rideau."""
    monkeypatch.setattr(al, "_DIGEST_ETAT",
                        _FiligraneKO(json.dumps({"jobs_vus": []})))
    _sante(tmp_path, monkeypatch)      # sans cela le test lirait le releve REEL
    db = _db(tmp_path,
             [("wj_a", "completed", 1, "2026-08-31T10:00:00", _trace("http://a1"))],
             [("doc_a1", "http://a1")])
    r = al.pat_veille_digest_auto(db=db, backfill=_Backfill())
    assert r["digest"] == "fait"
    assert r["filigrane"].startswith("NON ecrit")
    assert r["jobs_marques_vus"] == 0
    assert r["chain_ids_digeres"] == ["wj_a"]


# ── LA REGRESSION DE SCHEDULING : un pattern ne monopolise pas le tick ──────
class _BackfillLent:
    """Digest qui BLOQUE. Il ne doit jamais etre appele quand le fournisseur est
    connu indisponible — s'il l'est, la boucle est affamee."""

    def __init__(self):
        self.appels = 0

    def __call__(self, limit=400, since="", ids=None, provider="", modele=""):
        self.appels += 1
        raise AssertionError("le digest a ete appele alors que le LLM est KO : "
                             "c'est exactement la regression du 2026-08-31")


def test_S1_fournisseur_INDISPONIBLE_abstention_rapide(tmp_path, monkeypatch):
    """Mesure du 2026-08-31 : le digest a appele un Ollama fige, 120 s par lot,
    et a monopolise le tick de 15:39 a 15:43+. `veille_github_head` n'a jamais
    eu son tour. Le tick est SERIEL : un pattern qui attend affame les suivants."""
    monkeypatch.setattr(al, "_DIGEST_ETAT", tmp_path / "filigrane.json")
    # `-` = la sonde du primaire a echoue ; le secondaire local est injoignable.
    # AUCUN des deux n'est pret, donc aucun appel ne doit partir.
    _sante(tmp_path, monkeypatch, statut="-")
    db = _db(tmp_path, [("wj_a", "completed", 1, "2026-08-31T10:00:00",
                         _trace("http://a1"))], [("doc_a1", "http://a1")])
    lent = _BackfillLent()
    r = al.pat_veille_digest_auto(db=db, backfill=lent)
    assert r["digest"] == "unavailable"
    assert lent.appels == 0
    assert r["jobs_marques_vus"] == 0
    assert r["statut"] == "SKIPPED_PROVIDER_UNAVAILABLE"
    # Le repli est TRACE : les trois fournisseurs consultes figurent au resultat.
    assert [e["provider"] for e in r["essais"]] == ["groq", "openrouter_free",
                                                    "ollama"]
    assert "NON SONDE" in r["essais"][0]["raison"]


def test_S2_aucun_job_n_est_consomme_par_une_abstention(tmp_path, monkeypatch):
    """« Aucun job ne doit entrer dans jobs_vus si le digest n'a pas traite sa
    matiere. » L'abstention precede toute ecriture de filigrane."""
    fil = tmp_path / "filigrane.json"
    monkeypatch.setattr(al, "_DIGEST_ETAT", fil)
    _sante(tmp_path, monkeypatch, statut="-")
    db = _db(tmp_path, [("wj_a", "completed", 1, "2026-08-31T10:00:00",
                         _trace("http://a1"))], [("doc_a1", "http://a1")])
    al.pat_veille_digest_auto(db=db, backfill=_BackfillLent())
    assert not fil.exists(), "une abstention a consomme le filigrane"
    # Le tour suivant, fournisseur revenu : la matiere est TOUJOURS la.
    _sante(tmp_path, monkeypatch, statut="200")
    bf = _Backfill()
    r = al.pat_veille_digest_auto(db=db, backfill=bf)
    assert r["chain_ids_digeres"] == ["wj_a"]
    assert len(bf.appels) == 1


def test_S3_sante_INCONNUE_ou_PERIMEE_vaut_abstention(tmp_path, monkeypatch):
    """Trois etats. INCONNU n'est pas PRET : tenter sur un etat inconnu risque
    de rejouer la panne, alors que s'abstenir ne coute qu'un cycle differe."""
    monkeypatch.setattr(al, "_DIGEST_ETAT", tmp_path / "filigrane.json")
    db = _db(tmp_path, [("wj_a", "completed", 1, "2026-08-31T10:00:00",
                         _trace("http://a1"))], [("doc_a1", "http://a1")])
    # (a) instantane absent — et le MOTIF le distingue des deux autres cas, parce
    #     qu'un releve jamais ecrit ne se repare pas comme un releve qui a cesse.
    _sante(tmp_path, monkeypatch)          # isole la sonde locale
    monkeypatch.setattr(vd, "_SANTE_ENDPOINTS", tmp_path / "jamais_ecrit.json")
    r = al.pat_veille_digest_auto(db=db, backfill=_BackfillLent())
    assert r["digest"] == "unavailable" and "ABSENT" in r["sante_motif"]
    # (b) instantane perime
    _sante(tmp_path, monkeypatch, statut="200", age=vd._SANTE_TTL_S + 60)
    r = al.pat_veille_digest_auto(db=db, backfill=_BackfillLent())
    assert r["digest"] == "unavailable" and "PERIME" in r["sante_motif"]
    # (c) fournisseur absent du releve : le releve est FRAIS, c'est le nom qui manque
    _sante(tmp_path, monkeypatch, statut="200", nom="un_autre")
    r = al.pat_veille_digest_auto(db=db, backfill=_BackfillLent())
    assert r["digest"] == "unavailable" and r["sante_motif"] == ""
    assert "absent du releve" in r["essais"][0]["raison"]


def test_S4_le_fournisseur_RETENU_est_celui_qui_sera_appele(tmp_path, monkeypatch):
    """Sonder un fournisseur SUPPOSE ne prouve rien.

    Avant le contrat, le pattern devinait le fournisseur depuis une variable
    d'environnement pendant que le module en appelait un autre. Desormais une
    seule autorite tranche, et le fournisseur retenu est RENDU dans le resultat :
    il est verifiable, au lieu d'etre suppose.
    """
    monkeypatch.setattr(al, "_DIGEST_ETAT", tmp_path / "filigrane.json")
    db = _db(tmp_path, [("wj_a", "completed", 1, "2026-08-31T10:00:00",
                         _trace("http://a1"))], [("doc_a1", "http://a1")])
    # (a) primaire distant sain -> c'est lui, et la sonde locale n'est pas payee
    _sante(tmp_path, monkeypatch, statut="200", nom="groq")
    bf = _Backfill()
    r = al.pat_veille_digest_auto(db=db, backfill=bf)
    assert (r["provider"], r["model"]) == ("groq", vd.MODELE_GROQ)
    assert [e["provider"] for e in r["essais"]] == ["groq"]
    # (b) primaire KO, secondaire local charge -> repli EXPLICITE sur ollama
    monkeypatch.setattr(al, "_DIGEST_ETAT", tmp_path / "filigrane2.json")
    _sante(tmp_path, monkeypatch, statut="401", nom="groq",
           sonde={"api": True, "catalogue": [vd.DIGEST_MODEL],
                  "residents": [vd.DIGEST_MODEL]})
    r = al.pat_veille_digest_auto(db=db, backfill=_Backfill())
    assert (r["provider"], r["model"]) == ("ollama", vd.DIGEST_MODEL)
    assert [e["provider"] for e in r["essais"]] == ["groq", "openrouter_free",
                                                    "ollama"]


def test_S5_ollama_joignable_mais_modele_ABSENT_n_est_pas_pret(tmp_path, monkeypatch):
    """SERVICE_UP + API_READY ne valent pas MODEL_READY.

    Mesure du 2026-08-31 : service lance, port ouvert, `/api/tags` a 200, et
    `laforge-qwen` absent des douze modeles servis. Trois signaux verts pour un
    chemin mort — et la cause nommee doit designer le MODELE, pas le service.
    """
    monkeypatch.setattr(al, "_DIGEST_ETAT", tmp_path / "filigrane.json")
    _sante(tmp_path, monkeypatch, statut="401", nom="groq",
           sonde={"api": True, "catalogue": ["un_autre_modele"], "residents": []})
    db = _db(tmp_path, [("wj_a", "completed", 1, "2026-08-31T10:00:00",
                         _trace("http://a1"))], [("doc_a1", "http://a1")])
    lent = _BackfillLent()
    r = al.pat_veille_digest_auto(db=db, backfill=lent)
    assert r["statut"] == "SKIPPED_MODEL_UNAVAILABLE"
    assert lent.appels == 0
    # L'essai vise est designe par son NOM, jamais par son rang : un maillon
    # insere dans la cascade (openrouter_free, 2026-09-01) decale les index et
    # rend rouge un test dont le contrat n'a pas bouge.
    ollama = [e for e in r["essais"] if e["provider"] == "ollama"]
    assert ollama and ollama[0]["etat"] == "MODEL_UNAVAILABLE"


# ── le pattern est REELLEMENT enregistre dans la boucle ─────────────────────
def test_le_pattern_est_branche_dans_la_boucle_autonome():
    """Un declencheur qu'aucune boucle n'appelle est un garde sans emetteur."""
    assert "veille_digest_auto" in al.PATTERNS
    assert al.PATTERNS["veille_digest_auto"].interval_sec == 3600
