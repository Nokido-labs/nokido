"""NR — le CAPTEUR de changement de depot, branche a la boucle autonome.

PHASE A SEULE, et c'est volontaire. Detecter n'est pas rapatrier : un probleme du
clone ne doit pas detruire la capacite du capteur. Ce pattern ne clone RIEN.

CE QUI EST MESURE ET NON DEDUIT (2026-08-31) :
  - le daemon des boucles tourne, pid 20124, et sa propre sonde d'endpoints
    ecrite 2,1 min plus tot rend des 200 depuis groq/cerebras/sambanova : il a
    donc un reseau sortant ;
  - son COMPTE reste illisible depuis le bac a sable — `sc qc` rend « Acces
    refuse » et `tasklist /v` rend « N/A » sur les 85 process. D'ou le choix : le
    pattern MESURE SON PROPRE CONTEXTE et le rapporte, puisque c'est le seul
    endroit d'ou ce compte est observable ;
  - le registre porte 339 cibles et AUCUNE ne declare de `nom_dump`, alors que 12
    dumps existent dans `docs/`. Le lien n'existe pas encore : on surveille ce qui
    a une identite de dump et on COMPTE le reste.

Tant que le chemin d'execution autorise n'est pas etabli, la recuperation reste
`RECOVERY_UNAVAILABLE`. Une veille qu'on declare fonctionnelle sans l'etre est
pire que pas de veille.

HERMETIQUE : aucun reseau, aucun clone. `head_distant` est injecte.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
for _p in (_ROOT, _ROOT / "app", _ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from app import forge_autonomous_loops as al  # noqa: E402

_SHA1 = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
_SHA2 = "ffeeddccbbaa99887766554433221100aabbccdd"


def _cible(nom="depot", url="https://github.com/org/depot"):
    return {"target_id": "tid_" + nom, "repo": "org/" + nom, "url": url,
            "nom_dump": nom}


def _tete(sha, raison="HEAD lu"):
    def _f(url):
        return sha, raison
    return _f


def _manifeste(docs, nom, commit):
    dump = docs / ("gitingest_veille_%s.txt" % nom)
    dump.write_text("dump", encoding="utf-8")
    Path(str(dump) + ".manifest.json").write_text(
        json.dumps({"repo": "org/" + nom, "commit": commit,
                    "filtre_version": "1"}), encoding="utf-8")
    return dump


@pytest.fixture()
def banc(tmp_path, monkeypatch):
    monkeypatch.setattr(al, "_GH_ETAT", tmp_path / "gh_watch.json")
    # Intention ISOLEE : sans cela un `veille_gh.wanted` pose en production
    # rendrait ces tests non hermetiques, et pire, ferait CLONER pendant la suite.
    monkeypatch.setattr(al, "_GH_INTENTION", tmp_path / "veille_gh.wanted")
    docs = tmp_path / "docs"
    docs.mkdir()
    return docs


def _run(banc, cibles, sha, **kw):
    return al.pat_veille_github_head(cibles=cibles, tete=_tete(sha),
                                     docs=banc, **kw)


# ── 1 : le capteur DIT d'ou il parle ────────────────────────────────────────
def test_1_le_capteur_rapporte_son_propre_contexte(banc):
    """Le compte du daemon n'est pas lisible depuis ailleurs. Un rapport qui ne
    dit pas d'ou il parle ne prouve rien."""
    r = _run(banc, [_cible()], _SHA1)
    assert r["pid"] > 0
    assert isinstance(r["compte"], str) and r["compte"]


# ── 2-4 : aucune recuperation, quel que soit le verdict ─────────────────────
@pytest.mark.parametrize("sha_distant,manifeste,attendu",
                         [(_SHA1, _SHA1, "NO_CHANGE"),
                          (_SHA2, _SHA1, "UPDATED"),
                          (None, _SHA1, "UNKNOWN")])
def test_234_aucun_verdict_ne_declenche_de_recuperation(banc, sha_distant,
                                                        manifeste, attendu):
    _manifeste(banc, "depot", manifeste)
    r = _run(banc, [_cible()], sha_distant)
    assert r[attendu] == 1
    # PHASE B non demandee : le capteur ne recupere rien de lui-meme.
    assert r["recuperation"] == "non demandee"


def test_4bis_UNKNOWN_ne_devient_JAMAIS_NO_CHANGE(banc):
    """LE verrou du capteur : un HEAD illisible signifie « je ne sais pas »."""
    _manifeste(banc, "depot", _SHA1)
    r = _run(banc, [_cible()], None)
    assert r["UNKNOWN"] == 1
    assert r["NO_CHANGE"] == 0


# ── 5 : premier passage, aucun manifeste ────────────────────────────────────
def test_5_sans_manifeste_le_depot_est_UPDATED(banc):
    r = _run(banc, [_cible()], _SHA1)
    assert r["UPDATED"] == 1
    assert r["detail"][0]["sha_ingere"] is None


# ── 6 : le cap, et le retard qui reste VISIBLE ──────────────────────────────
def test_6_le_cap_borne_le_tour_sans_masquer_le_retard(banc, monkeypatch):
    monkeypatch.setattr(al, "_GH_MAX_PAR_TOUR", 3)
    cibles = [_cible("d%02d" % i) for i in range(7)]
    r = _run(banc, cibles, _SHA1)
    assert r["cibles_examinees"] == 3
    assert r["differees_par_cap"] == 4, "le retard doit etre DIT, pas absorbe"


def test_6bis_les_cibles_sans_identite_de_dump_sont_COMPTEES(banc):
    """Mesure : 339 cibles au registre, 0 avec `nom_dump`. Les surveiller toutes
    reviendrait a declarer UPDATED tout ce que Nokido a cite un jour."""
    doc = {"cibles": {"a": {"repo": "o/a", "url": "u", "target_id": "1"},
                      "b": {"repo": "o/b", "url": "u", "target_id": "2",
                            "nom_dump": "b"}}}
    suivies, sans = al._gh_cibles_suivies(doc)
    assert [c["repo"] for c in suivies] == ["o/b"]
    assert sans == 1


# ── 7 / 9 / 11 : rejeu, echec de recuperation, provenance ───────────────────
def test_7_le_meme_SHA_rejoue_reste_NO_CHANGE(banc):
    _manifeste(banc, "depot", _SHA1)
    for _ in range(3):
        assert _run(banc, [_cible()], _SHA1)["NO_CHANGE"] == 1


def test_9_une_recuperation_qui_n_a_pas_eu_lieu_laisse_le_capteur_UPDATED(banc):
    """Le manifeste n'a pas bouge, donc le depot reste a rapatrier. Un capteur
    qui retomberait a NO_CHANGE ferait oublier la matiere pour toujours."""
    _manifeste(banc, "depot", _SHA1)
    for _ in range(3):
        r = _run(banc, [_cible()], _SHA2)
        assert r["UPDATED"] == 1 and r["NO_CHANGE"] == 0


def test_11_la_provenance_nomme_les_DEUX_sha(banc):
    _manifeste(banc, "depot", _SHA1)
    d = _run(banc, [_cible()], _SHA2)["detail"][0]
    assert d["sha_ingere"] == _SHA1[:12]
    assert d["sha_vu"] == _SHA2[:12]
    assert _SHA1[:12] in d["raison"] and _SHA2[:12] in d["raison"]


# ── 8 / 10 : etat conserve, executions repetees ─────────────────────────────
def test_8_l_etat_de_surveillance_survit_au_restart(banc):
    _manifeste(banc, "depot", _SHA1)
    r = _run(banc, [_cible()], _SHA1)
    assert r["etat_surveillance"] == "ecrit"
    e = json.loads(al._GH_ETAT.read_text(encoding="utf-8"))["tid_depot"]
    assert e["last_head_seen"] == _SHA1
    assert e["last_head_ingested"] == _SHA1
    assert e["last_check"] and e["last_success"]


def test_8bis_une_panne_reseau_n_EFFACE_PAS_le_dernier_head_connu(banc):
    """Un echec ecrit `last_failure`, jamais un HEAD vide : sinon une panne
    effacerait la memoire du capteur."""
    _manifeste(banc, "depot", _SHA1)
    _run(banc, [_cible()], _SHA1)
    r = al.pat_veille_github_head(cibles=[_cible()],
                                  tete=_tete(None, "ls-remote rc=128"), docs=banc)
    assert r["UNKNOWN"] == 1
    e = json.loads(al._GH_ETAT.read_text(encoding="utf-8"))["tid_depot"]
    assert e["last_head_seen"] == _SHA1, "la panne a efface le HEAD connu"
    assert e["last_failure"]
    assert "rc=128" in e["last_failure_raison"]


def test_10_deux_executions_donnent_le_meme_verdict_et_un_etat_coherent(banc):
    """La detection est en LECTURE seule sur le depot : deux tours simultanes ne
    peuvent pas produire deux recuperations, il n'y en a aucune."""
    _manifeste(banc, "depot", _SHA1)
    r1 = _run(banc, [_cible()], _SHA2)
    r2 = _run(banc, [_cible()], _SHA2)
    assert r1["UPDATED"] == r2["UPDATED"] == 1
    assert json.loads(al._GH_ETAT.read_text(encoding="utf-8"))["tid_depot"][
        "last_head_seen"] == _SHA2


# ── 12 : le manifeste illisible ─────────────────────────────────────────────
def test_12_manifeste_ILLISIBLE_n_est_jamais_lu_comme_NO_CHANGE(banc):
    dump = banc / "gitingest_veille_depot.txt"
    dump.write_text("dump", encoding="utf-8")
    Path(str(dump) + ".manifest.json").write_text("pas du json {", encoding="utf-8")
    r = _run(banc, [_cible()], _SHA1)
    assert r["NO_CHANGE"] == 0
    assert r["UPDATED"] == 1


def test_un_etat_de_surveillance_ILLISIBLE_fait_s_abstenir(banc):
    """Repartir a zero perdrait `last_head_seen` de tous les depots, donc la
    memoire meme du capteur."""
    al._GH_ETAT.write_text("pas du json {", encoding="utf-8")
    r = _run(banc, [_cible()], _SHA1)
    assert "illisible" in r.get("skip", "")
    assert "compte" in r


# ── PHASE B : la recuperation, deleguee au chemin de confiance ──────────────
@pytest.fixture()
def sans_verrou(monkeypatch):
    """Verrou de lane NEUTRALISE : les tests ne doivent toucher aucune base
    reelle. Le comportement du verrou lui-meme est teste separement."""
    import forge_lane_admission as la
    monkeypatch.setattr(la, "acquire", lambda *a, **k: True)
    monkeypatch.setattr(la, "release", lambda *a, **k: None)
    return la


def _appel(effet=None):
    """`HubClient.tool` INJECTE. Rend la liste des appels et joue `effet`."""
    appels: list = []

    def _f(nom, args):
        appels.append({"nom": nom, "args": dict(args)})
        return effet(args) if callable(effet) else "ok"

    _f.appels = appels
    return _f


def _rec(banc, sha_distant, manifeste=None, effet=None, pilote="depot"):
    if manifeste is not None:
        _manifeste(banc, "depot", manifeste)
    ap = _appel(effet)
    r = al.pat_veille_github_head(cibles=[_cible()], tete=_tete(sha_distant),
                                  docs=banc, recuperer=True, pilote=pilote,
                                  appel=ap)
    return r, ap


def test_B1_UPDATED_declenche_la_recuperation_par_le_chemin_de_confiance(
        banc, sans_verrou):
    def effet(args):
        _manifeste(banc, "depot", _SHA2)          # le clone a fait son travail
        return "ok"

    r, ap = _rec(banc, _SHA2, manifeste=_SHA1, effet=effet)
    assert len(ap.appels) == 1
    a = ap.appels[0]
    assert a["nom"] == "run"
    assert a["args"]["action"] == "trusted_script"
    # `path` et NON `script` : mesure du 2026-08-31, le hub refuse l'autre nom
    # (« trusted_script: 'path' requis »). Un test qui injecte l'appel ne peut
    # pas decouvrir ce contrat — il peut seulement le verrouiller une fois paye.
    assert a["args"]["path"] == "tools/forge_veille_clone_ingest.py"
    assert "script" not in a["args"]
    assert "--dump-only" in a["args"]["args"], "le pattern doit DELEGUER, pas cloner"
    assert r["detail"][0]["recuperation"] == al.REC_SUCCESS


def test_B2_NO_CHANGE_ne_declenche_AUCUNE_recuperation(banc, sans_verrou):
    r, ap = _rec(banc, _SHA1, manifeste=_SHA1)
    assert r["NO_CHANGE"] == 1
    assert ap.appels == []


def test_B3_UNKNOWN_ne_declenche_AUCUNE_recuperation(banc, sans_verrou):
    r, ap = _rec(banc, None, manifeste=_SHA1)
    assert r["UNKNOWN"] == 1
    assert ap.appels == []


def test_B4_hub_injoignable_rend_UNAVAILABLE_sans_rien_falsifier(banc, sans_verrou):
    r, ap = _rec(banc, _SHA2, manifeste=_SHA1, effet=lambda a: None)
    assert r["detail"][0]["recuperation"] == al.REC_UNAVAILABLE
    e = json.loads(al._GH_ETAT.read_text(encoding="utf-8"))["tid_depot"]
    assert e["last_head_ingested"] == _SHA1, "un echec a avance le SHA ingere"
    assert e["last_head_seen"] == _SHA2, "un echec a efface ce que le capteur savait"


def test_B5_clone_sans_dump_est_un_ECHEC(banc, sans_verrou):
    """Aucun manifeste prealable : le dump n'existe pas apres l'appel."""
    r, _ = _rec(banc, _SHA2, effet=lambda a: "ok")
    assert r["detail"][0]["recuperation"] == al.REC_FAILED
    assert "aucun dump" in r["detail"][0]["recuperation_raison"]


def test_B6_dump_VIDE_n_est_pas_une_recuperation(banc, sans_verrou):
    def effet(args):
        (banc / "gitingest_veille_depot.txt").write_text("", encoding="utf-8")
        return "ok"

    r, _ = _rec(banc, _SHA2, effet=effet)
    assert r["detail"][0]["recuperation"] == al.REC_FAILED
    assert "vide" in r["detail"][0]["recuperation_raison"]


def test_B7_dump_SANS_manifeste_n_est_pas_une_recuperation(banc, sans_verrou):
    """Interruption entre le clone et l'ecriture du manifeste : la provenance
    est invérifiable, donc la recuperation n'est pas acquise."""
    def effet(args):
        (banc / "gitingest_veille_depot.txt").write_text("x" * 50, encoding="utf-8")
        return "ok"

    r, _ = _rec(banc, _SHA2, effet=effet)
    assert r["detail"][0]["recuperation"] == al.REC_FAILED
    assert "manifeste" in r["detail"][0]["recuperation_raison"]


def test_B8_manifeste_au_MAUVAIS_sha_est_refuse(banc, sans_verrou):
    """LE verrou : on n'ecrit JAMAIS un SHA suppose. Le clone a pu rapatrier un
    autre commit (course, branche par defaut differente, cache)."""
    def effet(args):
        _manifeste(banc, "depot", "0000000000000000000000000000000000000000")
        return "ok"

    r, _ = _rec(banc, _SHA2, manifeste=_SHA1, effet=effet)
    assert r["detail"][0]["recuperation"] == al.REC_FAILED
    e = json.loads(al._GH_ETAT.read_text(encoding="utf-8"))["tid_depot"]
    assert e["last_head_ingested"] == _SHA1


def test_B9_succes_complet_fait_avancer_le_SHA_ingere(banc, sans_verrou):
    def effet(args):
        _manifeste(banc, "depot", _SHA2)
        return "ok"

    _rec(banc, _SHA2, manifeste=_SHA1, effet=effet)
    e = json.loads(al._GH_ETAT.read_text(encoding="utf-8"))["tid_depot"]
    assert e["last_head_ingested"] == _SHA2
    assert e["last_recovery_etat"] == al.REC_SUCCESS


def test_B10_le_cycle_complet_retombe_en_NO_CHANGE(banc, sans_verrou):
    """UPDATED -> recuperation -> manifeste SHA2 -> NO_CHANGE, sans second clone."""
    def effet(args):
        _manifeste(banc, "depot", _SHA2)
        return "ok"

    r1, ap1 = _rec(banc, _SHA2, manifeste=_SHA1, effet=effet)
    assert r1["detail"][0]["recuperation"] == al.REC_SUCCESS
    r2, ap2 = _rec(banc, _SHA2)
    assert r2["NO_CHANGE"] == 1
    assert ap2.appels == [], "un depot inchange a ete re-clone"


def test_B11_un_depot_HORS_pilote_n_est_pas_recupere(banc, sans_verrou):
    """Le premier tour des 12 provoquerait 12 clones : le pilote borne."""
    r, ap = _rec(banc, _SHA2, manifeste=_SHA1, pilote="un_autre_depot")
    assert r["UPDATED"] == 1
    assert ap.appels == []
    assert r["detail"][0].get("recuperation") is None


def test_B12_une_recuperation_deja_en_cours_fait_S_ABSTENIR(banc, monkeypatch):
    """Deux tours simultanes sur le meme target_id : le second ne clone pas.
    Le verrou de lane EXISTANT est reutilise, aucun second systeme de lock."""
    import forge_lane_admission as la
    monkeypatch.setattr(la, "acquire", lambda *a, **k: False)
    monkeypatch.setattr(la, "release", lambda *a, **k: None)
    r, ap = _rec(banc, _SHA2, manifeste=_SHA1)
    assert r["detail"][0]["recuperation"] == al.REC_OCCUPE
    assert ap.appels == [], "deux recuperations concurrentes ont ete lancees"


# ── l'INTENTION : le seul canal que le daemon peut lire ─────────────────────
def test_B14_sans_intention_le_daemon_ne_recupere_RIEN(banc, sans_verrou):
    """`run_due_patterns` appelle les patterns SANS argument : si l'opt-in
    n'existe que comme parametre, il est inatteignable depuis le daemon."""
    _manifeste(banc, "depot", _SHA1)
    ap = _appel()
    r = al.pat_veille_github_head(cibles=[_cible()], tete=_tete(_SHA2),
                                  docs=banc, appel=ap)
    assert r["UPDATED"] == 1
    assert ap.appels == []
    assert "aucune intention" in r["intention"]


def test_B15_une_intention_POSEE_suffit_a_declencher_la_phase_B(banc, sans_verrou):
    """Aucun argument passe : c'est le drapeau qui parle, comme docker.wanted."""
    def effet(args):
        _manifeste(banc, "depot", _SHA2)
        return "ok"

    _manifeste(banc, "depot", _SHA1)
    al._GH_INTENTION.write_text("pilote", encoding="utf-8")
    ap = _appel(effet)
    r = al.pat_veille_github_head(cibles=[_cible()], tete=_tete(_SHA2),
                                  docs=banc, pilote="depot", appel=ap)
    assert len(ap.appels) == 1
    assert r["detail"][0]["recuperation"] == al.REC_SUCCESS
    assert "posee il y a" in r["intention"]


def test_B16_une_intention_PERIMEE_n_est_pas_une_absence(banc, sans_verrou):
    """Trois etats : posee / perimee / absente. Une intention perimee dit que
    quelqu'un l'a voulue puis ne l'a pas renouvelee — ce n'est pas la meme chose
    que personne ne l'a jamais demandee, et le rapport doit les distinguer."""
    import os
    al._GH_INTENTION.write_text("vieux", encoding="utf-8")
    vieux = time.time() - (al._GH_TTL_INTENTION + 3600)
    os.utime(al._GH_INTENTION, (vieux, vieux))
    voulu, raison = al._gh_intention()
    assert voulu is False
    assert "PERIMEE" in raison
    _manifeste(banc, "depot", _SHA1)
    ap = _appel()
    r = al.pat_veille_github_head(cibles=[_cible()], tete=_tete(_SHA2),
                                  docs=banc, appel=ap)
    assert ap.appels == []
    assert "PERIMEE" in r["intention"]


def test_B17_un_booleen_explicite_court_circuite_le_drapeau(banc, sans_verrou):
    _manifeste(banc, "depot", _SHA1)
    ap = _appel()
    r = al.pat_veille_github_head(cibles=[_cible()], tete=_tete(_SHA2),
                                  docs=banc, recuperer=False, appel=ap)
    assert ap.appels == []
    assert r["intention"] == "force par l'appelant"


def test_B13_une_cible_sans_identite_de_dump_ne_peut_pas_etre_recuperee(sans_verrou):
    r = al._gh_recuperer({"target_id": "t", "repo": "o/r"}, _SHA2, ".",
                         appel=_appel())
    assert r["etat"] == al.REC_FAILED
    assert "identite de dump" in r["raison"]


# ── LE CAP DE RECUPERATION, distinct du cap d'EXAMEN ────────────────────────
def test_C1_douze_examinees_une_seule_recuperee(banc, sans_verrou):
    """Examiner coute un `ls-remote` ; recuperer coute un CLONE. Ouvrir les 12
    d'un coup ferait douze clones dans un tick de 60 s."""
    cibles = [_cible("d%02d" % i) for i in range(12)]
    for c in cibles:
        (banc / ("gitingest_veille_%s.txt" % c["nom_dump"])).write_text(
            "x" * (100 + int(c["nom_dump"][1:]) * 10), encoding="utf-8")
    al._GH_INTENTION.write_text("go", encoding="utf-8")
    ap = _appel()
    r = al.pat_veille_github_head(cibles=cibles, tete=_tete(_SHA2), docs=banc,
                                  appel=ap)
    assert r["cibles_examinees"] == 12
    assert r["UPDATED"] == 12
    assert len(ap.appels) == 1, "plus d'une recuperation dans le meme tour"
    assert r["recuperations_differees"] == 11
    assert r["cap_recuperations"] == 1


def test_C2_l_ordre_suit_la_taille_MESUREE_du_dump(banc):
    """La taille du dump sur disque dit ce que la derniere recuperation a
    reellement coute — ce n'est pas une heuristique."""
    petit, gros = _cible("petit"), _cible("gros")
    (banc / "gitingest_veille_petit.txt").write_text("x" * 10, encoding="utf-8")
    (banc / "gitingest_veille_gros.txt").write_text("x" * 100000, encoding="utf-8")
    assert [c["nom_dump"] for c in al._gh_ordre_recuperation([gros, petit], banc)] \
        == ["petit", "gros"]


def test_C3_un_depot_jamais_dumpe_passe_en_DERNIER(banc):
    """Cout INCONNU n'est pas cout NUL : on ne suppose pas qu'il est petit."""
    connu, inconnu = _cible("connu"), _cible("inconnu")
    (banc / "gitingest_veille_connu.txt").write_text("x" * 999999, encoding="utf-8")
    assert [c["nom_dump"] for c in al._gh_ordre_recuperation([inconnu, connu], banc)] \
        == ["connu", "inconnu"]


def test_C4_les_prioritaires_passent_avant_la_taille(banc, monkeypatch):
    monkeypatch.setattr(al, "_GH_PRIORITAIRES", ("gros",))
    petit, gros = _cible("petit"), _cible("gros")
    (banc / "gitingest_veille_petit.txt").write_text("x" * 10, encoding="utf-8")
    (banc / "gitingest_veille_gros.txt").write_text("x" * 100000, encoding="utf-8")
    assert [c["nom_dump"] for c in al._gh_ordre_recuperation([petit, gros], banc)] \
        == ["gros", "petit"]


def test_C5_les_differees_ne_sont_PAS_declarees_a_jour(banc, sans_verrou):
    """« Il ne faut jamais declarer le depot a jour pour eviter le backlog. »"""
    cibles = [_cible("d%02d" % i) for i in range(3)]
    al._GH_INTENTION.write_text("go", encoding="utf-8")
    al.pat_veille_github_head(cibles=cibles, tete=_tete(_SHA2), docs=banc,
                              appel=_appel())
    etat = json.loads(al._GH_ETAT.read_text(encoding="utf-8"))
    differes = [v for v in etat.values() if not v.get("last_recovery_etat")]
    assert len(differes) == 2
    for v in differes:
        assert v["last_head_seen"] == _SHA2
        assert v.get("last_head_ingested") is None


# ── le budget de recuperation ───────────────────────────────────────────────
def test_C6_le_budget_est_transmis_au_hub(banc, sans_verrou):
    """Sans `timeout` explicite, le hub applique 120 s et le client HTTP 5 s :
    le client abandonnerait AVANT le serveur, et l'on inscrirait UNAVAILABLE sur
    une recuperation peut-etre reussie."""
    _manifeste(banc, "depot", _SHA1)

    def _effet(args):
        _manifeste(banc, "depot", _SHA2)
        return "ok"

    ap = _appel(_effet)
    al.pat_veille_github_head(cibles=[_cible()], tete=_tete(_SHA2), docs=banc,
                              recuperer=True, pilote="depot", appel=ap)
    assert ap.appels[0]["args"]["timeout"] == al._GH_BUDGET_RECUPERATION_S


def test_C7_un_depassement_de_budget_est_un_ECHEC_pas_un_succes(banc, sans_verrou):
    """Le hub represente le depassement par `timed_out=True`. Sans cette
    lecture, le dump PRECEDENT serait pris pour le resultat du clone."""
    _manifeste(banc, "depot", _SHA1)
    ap = _appel(lambda a: "[trusted_script x exit=1 timed_out=True user=T]\n")
    r = al.pat_veille_github_head(cibles=[_cible()], tete=_tete(_SHA2), docs=banc,
                                  recuperer=True, pilote="depot", appel=ap)
    assert r["detail"][0]["recuperation"] == al.REC_FAILED
    assert "budget" in r["detail"][0]["recuperation_raison"]
    e = json.loads(al._GH_ETAT.read_text(encoding="utf-8"))["tid_depot"]
    assert e["last_head_ingested"] == _SHA1, "un depassement a fait avancer le SHA"
    assert e["last_head_seen"] == _SHA2


# ── UN REFUS DU HUB N'EST PAS UNE REPONSE ───────────────────────────────────
@pytest.mark.parametrize("refus", [
    "GATE_DENIED: ring:ring 4 <= requis 3",
    "ERR: trusted_script: reserve ring<=2 (ring=4)",
    "ERR: trusted_script: 'path' requis (relatif au repo, sous tools/ ou app/)",
    "[Hub] Erreur: {'code': -32601}",
])
def test_C8_un_refus_du_hub_est_DIT_pas_maquille(banc, sans_verrou, refus):
    """MESURE 2026-08-31 : le hub a rendu `GATE_DENIED: ring 4 <= requis 3`, le
    code l'a pris pour une sortie normale, a verifie le dump — inchange,
    forcement — et a rapporte « dump sans manifeste ». Une raison fausse envoie
    la session suivante chercher un defaut de manifeste la ou il y a un probleme
    d'identite."""
    _manifeste(banc, "depot", _SHA1)
    ap = _appel(lambda a: refus)
    r = al.pat_veille_github_head(cibles=[_cible()], tete=_tete(_SHA2), docs=banc,
                                  recuperer=True, pilote="depot", appel=ap)
    d = r["detail"][0]
    assert d["recuperation"] == al.REC_UNAVAILABLE
    assert "REFUSE" in d["recuperation_raison"]
    assert "manifeste" not in d["recuperation_raison"]
    e = json.loads(al._GH_ETAT.read_text(encoding="utf-8"))["tid_depot"]
    assert e["last_head_ingested"] == _SHA1


def test_C9_les_cibles_non_retenues_sont_DIFFEREES_pas_hors_pilote(banc,
                                                                   sans_verrou):
    """Une cible que le cap ecarte est DIFFEREE ; une cible qui n'a pas bouge est
    SANS OBJET. Les confondre ferait lire un backlog la ou il n'y a rien."""
    bouge, stable = _cible("bouge"), _cible("stable")
    _manifeste(banc, "stable", _SHA2)
    for n in ("bouge",):
        (banc / ("gitingest_veille_%s.txt" % n)).write_text("x", encoding="utf-8")
    al._GH_INTENTION.write_text("go", encoding="utf-8")

    def _tete_mixte(url):
        return _SHA2, "HEAD lu"

    r = al.pat_veille_github_head(cibles=[bouge, stable], tete=_tete_mixte,
                                  docs=banc, appel=_appel())
    etats = r["recuperation"]
    assert etats["org/stable"] == "sans objet"
    assert etats["org/bouge"] in (al.REC_FAILED, al.REC_SUCCESS,
                                  al.REC_UNAVAILABLE, "differee")


# ── EQUITE : un depot tres vivant n'affame pas les autres ───────────────────
def test_F1_une_cible_JAMAIS_tentee_passe_avant_une_deja_servie(banc):
    """C'est la propriete d'equite : chaque cible suivie passe une fois avant
    qu'aucune ne repasse."""
    servie, neuve = _cible("servie"), _cible("neuve")
    (banc / "gitingest_veille_servie.txt").write_text("x", encoding="utf-8")
    (banc / "gitingest_veille_neuve.txt").write_text("x" * 99999, encoding="utf-8")
    etat = {"tid_servie": {"last_recovery": "2026-08-31T20:00:00+00:00"}}
    ordre = al._gh_ordre_recuperation([servie, neuve], banc, etat)
    assert [c["nom_dump"] for c in ordre] == ["neuve", "servie"], \
        "la cible deja servie repasse avant une cible jamais tentee"


def test_F2_entre_deux_deja_servies_la_PLUS_ANCIENNE_passe(banc):
    a, b = _cible("recente"), _cible("ancienne")
    for n in ("recente", "ancienne"):
        (banc / ("gitingest_veille_%s.txt" % n)).write_text("x", encoding="utf-8")
    etat = {"tid_recente": {"last_recovery": "2026-08-31T20:30:00+00:00"},
            "tid_ancienne": {"last_recovery": "2026-08-31T09:00:00+00:00"}}
    assert [c["nom_dump"] for c in al._gh_ordre_recuperation([a, b], banc, etat)] \
        == ["ancienne", "recente"]


def test_F3_LA_FAMINE_un_depot_tres_actif_ne_monopolise_plus(banc, sans_verrou):
    """SCENARIO DEMANDE : A, B, C tous UPDATED, cap=1, A reste UPDATED a chaque
    tour. Sans equite, A prenait le slot indefiniment — c'est ce que faisait
    `_GH_PRIORITAIRES`, et c'est pourquoi il a ete vide."""
    cibles = [_cible("a_actif"), _cible("b"), _cible("c")]
    for c in cibles:
        (banc / ("gitingest_veille_%s.txt" % c["nom_dump"])).write_text(
            "x", encoding="utf-8")
    al._GH_INTENTION.write_text("go", encoding="utf-8")
    servis: list = []
    for _ in range(3):                      # trois tours, A toujours UPDATED
        ap = _appel()
        al.pat_veille_github_head(cibles=cibles, tete=_tete(_SHA2), docs=banc,
                                  appel=ap)
        etat = json.loads(al._GH_ETAT.read_text(encoding="utf-8"))
        servis.append(sorted(k for k, v in etat.items() if v.get("last_recovery")))
    # Au troisieme tour, LES TROIS ont ete tentees au moins une fois.
    assert len(servis[-1]) == 3, "apres 3 tours, seules %s ont ete servies" % servis[-1]


def test_F4_le_compteur_de_famine_monte_pour_les_ecartees(banc, sans_verrou):
    """« differee » ne dit pas depuis COMBIEN de tours. Sans compteur, une cible
    ecartee dix fois se lit comme une cible ecartee une fois."""
    cibles = [_cible("x"), _cible("y")]
    for c in cibles:
        (banc / ("gitingest_veille_%s.txt" % c["nom_dump"])).write_text(
            "x", encoding="utf-8")
    al._GH_INTENTION.write_text("go", encoding="utf-8")
    al.pat_veille_github_head(cibles=cibles, tete=_tete(_SHA2), docs=banc,
                              appel=_appel())
    etat = json.loads(al._GH_ETAT.read_text(encoding="utf-8"))
    ecartees = [v for v in etat.values() if v.get("deferred_count")]
    assert len(ecartees) == 1 and ecartees[0]["deferred_count"] == 1


def test_F5_un_succes_remet_le_compteur_de_famine_a_zero(banc, sans_verrou):
    def _effet(args):
        _manifeste(banc, "depot", _SHA2)
        return "ok"

    _manifeste(banc, "depot", _SHA1)
    al.pat_veille_github_head(cibles=[_cible()], tete=_tete(_SHA2), docs=banc,
                              recuperer=True, pilote="depot", appel=_appel(_effet))
    e = json.loads(al._GH_ETAT.read_text(encoding="utf-8"))["tid_depot"]
    assert e["deferred_count"] == 0
    assert e["last_recovery_success"], "le succes n'est pas date separement"
    assert e["last_recovery"], "la tentative n'est pas datee"


def test_F6_l_ordre_force_est_VIDE(banc):
    """Sa raison est consommee : codex a ete recupere et porte son manifeste.
    Le garder aurait classe le depot le plus actif rang 0 a chaque tour."""
    assert al._GH_PRIORITAIRES == ()


# ── le pattern est REELLEMENT enregistre ────────────────────────────────────
def test_le_capteur_est_branche_dans_la_boucle_autonome():
    assert "veille_github_head" in al.PATTERNS
    assert al.PATTERNS["veille_github_head"].interval_sec == 3600
