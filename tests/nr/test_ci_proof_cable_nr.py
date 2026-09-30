"""NR — le manifeste est REELLEMENT ecrit par le juge, et il suit le verdict.

Un mecanisme present et non cable est une dette de cablage, jamais une securite :
c'est la formule du depot, et elle a deja coute (le worktree de preuve existait et
rien ne le consommait, mesure du 2026-09-11). Ces tests gardent le CABLAGE de
`forge_ci_proof` dans `ci_local`, pas la logique pure — elle a ses propres NR.

Le piege evite ici, et qui merite son test : `_ETAT_SUITE` doit etre assigne
APRES l'ecrasement `SUITE_PARTIELLE` du mode `--impacte`. Assigne avant, un run
reduit ecrirait `SUITE_COMPLETE` dans un artefact destine a autoriser une
promotion.
"""
import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
cl = importlib.import_module("ci_local")
fcp = importlib.import_module("forge_ci_proof")

CTX = {"proof_root": "/un/worktree", "head": "e5ab874eb3afeb55", "entrees": 0}


def _ecrire(monkeypatch, tmp_path, etat, process_state="CAPTURED", ctx=CTX):
    # `NOKIDO_PROOF_DIR` PRIME sur `_PROOF_DIR` dans le juge : sans ce retrait,
    # un environnement de CI qui la pose ferait ecrire le manifeste ailleurs et
    # le test lirait un fichier absent — panne fantome, jamais un faux vert.
    monkeypatch.delenv("NOKIDO_PROOF_DIR", raising=False)
    monkeypatch.setattr(cl, "_PROOF_DIR", str(tmp_path))
    monkeypatch.setattr(cl, "_ETAT_SUITE", etat)
    cl._ecrire_ci_proof(process_state, ctx=ctx, target_sha="e5ab874eb3afeb55",
                        execution_id="ci-reference-abc")
    cible = tmp_path / "ci_proof.json"
    assert cible.is_file(), "aucun manifeste ecrit"
    return json.loads(cible.read_text(encoding="utf-8"))


def test_une_suite_COMPLETE_produit_un_manifeste_certifiant(monkeypatch, tmp_path):
    m = _ecrire(monkeypatch, tmp_path, "SUITE_COMPLETE")
    ok, motif = fcp.certifie(m)
    # Le seul refus TOLERE ici est la reconciliation du lock : elle depend de
    # l'interpreteur qui joue le test, pas du juge. Mesure 2026-09-19 : le lock
    # decrit `laforge_py314` (celui des run_job, ou la reconciliation rend
    # CONFORME 43/0/0/0) et ce fichier se joue aussi a la main sous miniforge3
    # 3.12 — 5 ecarts, 21 manquants. Asserter CONFORME ferait de ce NR une
    # SONDE SUR LA MACHINE ; tout AUTRE motif de refus reste une regression.
    if not ok:
        assert m["dependency_match"] != "CONFORME" and "lock" in motif, motif
    assert m["target_sha"] == "e5ab874eb3afeb55"
    assert m["observed_head"] == "e5ab874eb3afeb55", \
        "le sujet MESURE doit venir du contexte de capture, pas du sha demande"
    assert m["process_state"] == "CAPTURED"
    assert m["execution_id"] == "ci-reference-abc"
    assert len(m["test_plan_hash"]) == 64 and len(m["ci_contract_hash"]) == 64
    assert len(m["environment_fingerprint"]) == 64, \
        "l'empreinte d'environnement doit REJOINDRE la preuve, pas seulement etre imprimee"


@pytest.mark.parametrize("etat", ["SUITE_PARTIELLE", "SUITE_INCOMPLETE", None])
def test_un_verdict_non_complet_ne_certifie_JAMAIS(monkeypatch, tmp_path, etat):
    """Le manifeste est tout de meme ECRIT : une preuve qui dit pourquoi elle ne
    certifie pas vaut mieux qu'une absence de preuve."""
    m = _ecrire(monkeypatch, tmp_path, etat)
    assert not fcp.certifie(m)[0]
    assert m["certification_state"] == (etat or "NON_CERTIFIANT")


@pytest.mark.parametrize("process_state", ["NO_CAPTURE", "CAPTURE_REFUSED"])
def test_sans_capture_le_juge_ECRIT_quand_meme_et_ne_certifie_PAS(
        monkeypatch, tmp_path, process_state):
    """Le chemin ROUGE est celui qui n'ecrivait rien : 90 executions, 0 preuve.

    Sur un echec avant capture, le sujet est INCONNU — le manifeste doit le
    dire (`observed_head` a None) au lieu de recopier le sha demande, et il
    doit exister malgre tout : une preuve NEGATIVE reste une preuve.
    """
    m = _ecrire(monkeypatch, tmp_path, "SUITE_COMPLETE", process_state=process_state,
                ctx={"proof_root": None})
    assert m["process_state"] == process_state
    assert m["observed_head"] is None, "sans capture, le sujet ne se devine pas"
    assert m["certification_state"] == "NON_CERTIFIANT", \
        "une suite ne peut pas etre complete si la capture n'a pas abouti"
    assert not fcp.certifie(m)[0]


def test_le_plan_est_celui_REELLEMENT_declare(monkeypatch, tmp_path):
    """Le hash doit venir de PURE_TESTS/BLOCS_ISOLES du moteur, pas d'une copie."""
    m1 = _ecrire(monkeypatch, tmp_path, "SUITE_COMPLETE")
    monkeypatch.setattr(cl, "PURE_TESTS", list(cl.PURE_TESTS) + ["tests/nr/test_zz_nr.py"])
    m2 = _ecrire(monkeypatch, tmp_path, "SUITE_COMPLETE")
    assert m1["test_plan_hash"] != m2["test_plan_hash"], \
        "une entree de plus dans le plan doit changer l'empreinte du plan"


def test_le_contrat_couvre_le_moteur_ET_le_selecteur():
    for c in ("tools/ci_local.py", "tools/forge_ci_selection.py",
              "tools/forge_ci_proof.py"):
        assert c in cl._CONTRAT_CI, c
    empreinte, illisibles = fcp.hash_contrat([ROOT / c for c in cl._CONTRAT_CI])
    assert illisibles == [], "le contrat doit etre LISIBLE dans le depot : %s" % illisibles
    assert len(empreinte) == 64


def test_sans_repertoire_de_preuve_on_le_DIT_sans_ecrire(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("NOKIDO_PROOF_DIR", raising=False)
    monkeypatch.setattr(cl, "_PROOF_DIR", None)
    monkeypatch.setattr(cl, "_ETAT_SUITE", "SUITE_COMPLETE")
    cl._ecrire_ci_proof("CAPTURED", ctx={"proof_root": None}, target_sha="abc")
    assert "NON ECRIT" in capsys.readouterr().out
    assert not (tmp_path / "ci_proof.json").exists()


def test_le_lock_est_RECONCILIE_par_le_juge_pas_seulement_hache(monkeypatch, tmp_path):
    """B2 cable : le manifeste doit porter les DEUX affirmations."""
    m = _ecrire(monkeypatch, tmp_path, "SUITE_COMPLETE")
    assert "dependency_lock_hash" in m and "dependency_match" in m
    assert m["dependency_match"] in ("CONFORME", "DIVERGENT", "ILLISIBLE"), \
        "trois etats, jamais un booleen ni None silencieux : %r" % m["dependency_match"]
    if m["dependency_lock_hash"]:
        # Le hash n'a de sens que si la reconciliation l'accompagne.
        ok, motif = fcp.certifie(m)
        if m["dependency_match"] != "CONFORME":
            assert not ok and m["dependency_match"] in motif


def test_la_couverture_d_ATTEIGNABILITE_est_DECLAREE_donc_jouee():
    """Ce test remplace un `assert "_ecrire_ci_proof(_ctx," in src`.

    Celui-la gardait un CABLAGE par une CHAINE DE CARACTERES : la signature a
    change le 2026-09-19 et l'assertion est devenue fausse sans que le cablage
    bouge — un garde qui casse quand le code s'ameliore se fait desarmer. La
    couverture reelle se fait par AST dans le NR d'atteignabilite ; reste a
    garantir qu'il est JOUE, sinon c'est la dette de cablage qu'on repete.
    """
    assert "tests/nr/test_ci_proof_reachability_nr.py" in cl.PURE_TESTS, \
        "le NR d'atteignabilite doit etre DECLARE, sinon il ne tourne jamais"
    assert (ROOT / "tests" / "nr" / "test_ci_proof_reachability_nr.py").is_file()


def test_l_etat_de_suite_est_fige_APRES_l_ecrasement_partiel():
    """Le piege : assigne AVANT l'ecrasement `--impacte`, un run reduit ecrirait
    SUITE_COMPLETE dans l'artefact qui autorise une promotion.
    """
    src = (ROOT / "tools" / "ci_local.py").read_text(encoding="utf-8")
    i_partiel = src.index('_bp["etat"] = "SUITE_PARTIELLE"')
    i_fige = src.index("_ETAT_SUITE = _bp[\"etat\"]")
    assert i_partiel < i_fige, \
        "l'etat doit etre fige APRES la bascule SUITE_PARTIELLE, sinon elle est perdue"


def test_l_environnement_qui_JUGE_est_NOMME_dans_la_preuve(monkeypatch):
    """B2 ne doit pas seulement etre APPELE : il doit etre EXECUTE dans le
    runtime auquel la certification pretend s'appliquer (owner 2026-09-19).

    Sans identite d'environnement, deux runs de MEME VERSION sous deux envs
    differents portent la meme empreinte, et `dependency_match` devient une
    sonde sur l'interpreteur qui a lance pytest au lieu d'une mesure du
    substrat juge. Mesure du jour : ces memes NR rendent DIVERGENT sous
    miniforge3 3.12 (5 ecarts, 21 manquants) et CONFORME sous laforge_py314 —
    le lock est une CONSTANTE du depot, `fermeture()` lit un environnement
    VARIABLE.
    """
    ctx = cl.empreinte_contexte()
    assert ctx["env"] and ctx["env"] != "INCONNU"
    assert len(ctx["env_empreinte"]) == 16
    assert "\\" not in ctx["env"] and "/" not in ctx["env"], \
        "le NOM de l'env, jamais son chemin : un manifeste est destine a etre publie"
    # CONTRE-EPREUVE : sans elle, un champ constant passerait les assertions
    # ci-dessus en ne distinguant rien du tout.
    avant = ctx["env_empreinte"]
    monkeypatch.setattr(sys, "prefix", sys.prefix + "_un_autre_env")
    assert cl.empreinte_contexte()["env_empreinte"] != avant, \
        "deux environnements distincts doivent porter DEUX empreintes"


def test_la_telemetrie_ne_publie_JAMAIS_une_charge_nulle_inventee(monkeypatch):
    """`cpu_percent(interval=None)` rend 0.0 au PREMIER appel par construction.

    Le publier ferait lire « charge nulle » la ou rien n'a ete mesure -- c'est
    le piege du snapshot a froid (defauts = zeros = « charge nulle » = garde
    ouvert en silence). La sonde doit DIRE qu'elle s'amorce.
    """
    monkeypatch.setattr(cl, "_TELEMETRIE", [])
    monkeypatch.setattr(cl._telemetrie, "_amorce", False, raising=False)
    premier = cl._telemetrie("avant: bidon")
    assert str(premier["cpu_pct"]).startswith("ILLISIBLE"), \
        "le premier echantillon n'est pas une mesure : il doit le dire"
    second = cl._telemetrie("apres: bidon")
    assert not str(second["cpu_pct"]).startswith("ILLISIBLE(amorce"), \
        "une fois amorcee, la sonde doit mesurer"
    assert second["NON_COUVERT"], "une sonde muette sur ses angles morts se lit exhaustive"


def test_une_sonde_qui_TOMBE_n_est_jamais_une_cause(monkeypatch):
    """Un instrument ne doit pas pouvoir faire echouer ce qu'il observe.

    Contre-epreuve du principe : psutil rendu inimportable, la sonde rend un
    etat ILLISIBLE NOMME et ne leve pas.
    """
    monkeypatch.setattr(cl, "_TELEMETRIE", [])
    monkeypatch.setitem(sys.modules, "psutil", None)   # -> ImportError a l'import
    snap = cl._telemetrie("avant: psutil absent")
    assert str(snap["etat"]).startswith("ILLISIBLE("), snap
    # `type(e).__name__` rend le nom CONCRET (ModuleNotFoundError), pas sa base
    # ImportError : asserter la base ferait echouer un motif pourtant juste.
    assert snap["etat"] in ("ILLISIBLE(ImportError)",
                            "ILLISIBLE(ModuleNotFoundError)"), \
        "la sonde doit NOMMER son motif d'illisibilite : %s" % snap["etat"]


def test_la_borne_de_telemetrie_est_DITE_pas_silencieuse(monkeypatch):
    """Un ecart ecarte en silence fait surestimer la couverture. Une borne dit
    COMBIEN, elle ne dit pas seulement « trop »."""
    monkeypatch.setattr(cl, "_TELEMETRIE", [{"x": i} for i in range(cl._TELEMETRIE_MAX)])
    monkeypatch.setattr(cl._telemetrie, "_amorce", True, raising=False)
    cl._telemetrie("apres: un de trop")
    dernier = cl._TELEMETRIE[-1]
    assert dernier.get("etiquette") == "BORNE ATTEINTE"
    assert str(cl._TELEMETRIE_MAX) in dernier["note"], \
        "la borne doit porter son DENOMINATEUR"


def test_la_telemetrie_VOYAGE_avec_la_preuve(monkeypatch, tmp_path):
    """Un journal affiche puis perdu ne permet pas de comparer deux runs du
    MEME sha -- c'est precisement ce qui manquait pour attribuer les timeouts."""
    monkeypatch.setattr(cl, "_TELEMETRIE", [{"etiquette": "avant: suite pure",
                                             "cpu_pct": 12.5}])
    m = _ecrire(monkeypatch, tmp_path, "SUITE_COMPLETE")
    assert m["extra"]["telemetrie"][0]["etiquette"] == "avant: suite pure"


def test_sans_telemetrie_le_manifeste_ne_PORTE_pas_un_extra_vide(monkeypatch, tmp_path):
    """Contre-epreuve : un `extra` toujours present ferait croire a une mesure
    la ou il n'y en a aucune."""
    monkeypatch.setattr(cl, "_TELEMETRIE", [])
    m = _ecrire(monkeypatch, tmp_path, "SUITE_COMPLETE")
    assert "extra" not in m


def test_l_angle_mort_des_dependances_n_est_PLUS_declare_a_tort():
    """Un denominateur qui se trompe DANS L'AUTRE SENS trompe aussi.

    `NON_COUVERT` annoncait aveugle « les versions des dependances installees »
    alors que B2 les reconcilie desormais. Declarer aveugle ce qu'on mesure fait
    chercher une couverture qui existe — et masque le trou REEL, plus etroit :
    ce que la fermeture du lock n'atteint pas.
    """
    non_couvert = cl.empreinte_contexte()["NON_COUVERT"]
    assert not any("versions des dependances installees" in x for x in non_couvert), \
        "B2 reconcilie les versions installees : les declarer aveugles est FAUX"
    assert any("fermeture du lock" in x for x in non_couvert), \
        "le trou REEL doit etre nomme, pas simplement retire"
