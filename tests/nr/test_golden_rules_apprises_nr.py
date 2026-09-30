"""NR — regles APPRISES de forge_golden_rules_ast.

La boucle « echec -> garde » demandee par l'owner produit des DONNEES, pas du
Python : une regle distillee d'un correctif reel est une ligne JSON appliquee
par des formes closes (`appel_sans_kwarg`, `appel_interdit`). Deux dangers a
verrouiller ici : qu'une regle apprise s'accorde toute seule le pouvoir de
fermer la CI (severity ERROR), et qu'une regle mal formee soit avalee en
silence — c'est-a-dire qu'on croie proteger un invariant que personne
n'applique.

Tests d'effet : on mesure ce que le scanner TROUVE, jamais qu'il s'importe.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_golden_rules_ast as G  # noqa: E402

SANS_TIMEOUT = {"id": "apprise-subprocess-run-sans-timeout", "forme": "appel_sans_kwarg",
                "cible": "subprocess.run", "kwarg": "timeout", "severity": "WARNING"}


def _scan(tmp_path: Path, code: str, regles: list[dict]) -> list[dict]:
    cible = tmp_path / "cible.py"
    cible.write_text(code, encoding="utf-8")
    return G.scan_file(str(cible), regles)


def test_un_appel_sans_le_kwarg_est_pris(tmp_path):
    trouve = _scan(tmp_path, "import subprocess\nsubprocess.run(['x'])\n", [SANS_TIMEOUT])
    assert [f["rule"] for f in trouve] == ["apprise-subprocess-run-sans-timeout"]
    assert trouve[0]["line"] == 2


def test_le_meme_appel_avec_le_kwarg_est_laisse_tranquille(tmp_path):
    assert _scan(tmp_path, "import subprocess\nsubprocess.run(['x'], timeout=5)\n",
                 [SANS_TIMEOUT]) == []


def test_un_double_etoile_kwargs_n_est_jamais_accuse(tmp_path):
    # Le kwarg PEUT etre dans le dict : accuser ici fabriquerait le faux positif
    # exact que la regle des colonnes interpolees a deja coute une fois.
    assert _scan(tmp_path, "import subprocess\nopts = {}\nsubprocess.run(['x'], **opts)\n",
                 [SANS_TIMEOUT]) == []


def test_la_forme_appel_interdit_mord_sur_la_seule_presence(tmp_path):
    regle = {"id": "apprise-pas-de-os-system", "forme": "appel_interdit",
             "cible": "os.system", "message": "passer par run action=shell"}
    trouve = _scan(tmp_path, "import os\nos.system('dir')\n", [regle])
    assert [f["rule"] for f in trouve] == ["apprise-pas-de-os-system"]
    assert trouve[0]["message"] == "passer par run action=shell"
    assert trouve[0]["severity"] == "WARNING"


def test_une_severity_ERROR_non_promue_retombe_a_WARNING(tmp_path):
    fichier = tmp_path / "apprises.json"
    fichier.write_text(json.dumps({"regles": [{**SANS_TIMEOUT, "severity": "ERROR"}]}),
                       encoding="utf-8")
    regles, rejets = G.charger_apprises(str(fichier))
    assert rejets == []
    assert regles[0]["severity"] == "WARNING", "une regle apprise ne ferme pas la CI seule"


def test_une_severity_ERROR_promue_est_respectee(tmp_path):
    fichier = tmp_path / "apprises.json"
    fichier.write_text(json.dumps({"regles": [{**SANS_TIMEOUT, "severity": "ERROR",
                                               "promue": True}]}), encoding="utf-8")
    assert G.charger_apprises(str(fichier))[0][0]["severity"] == "ERROR"


def test_une_regle_mal_formee_est_NOMMEE_pas_avalee(tmp_path):
    fichier = tmp_path / "apprises.json"
    fichier.write_text(json.dumps({"regles": [
        {"id": "forme-inconnue", "forme": "regexp_libre", "cible": "x"},
        {"id": "sans-kwarg", "forme": "appel_sans_kwarg", "cible": "subprocess.run"},
        SANS_TIMEOUT,
    ]}), encoding="utf-8")
    regles, rejets = G.charger_apprises(str(fichier))
    assert [r["id"] for r in regles] == ["apprise-subprocess-run-sans-timeout"]
    assert sorted(rejets) == ["forme-inconnue", "sans-kwarg"]


def test_une_severity_INFO_est_conservee_telle_quelle(tmp_path):
    # Le plafond ne doit pas tout ramener a WARNING : une regle volontairement
    # discrete resterait alors aussi bruyante que les autres.
    fichier = tmp_path / "apprises.json"
    fichier.write_text(json.dumps({"regles": [{**SANS_TIMEOUT, "severity": "INFO"}]}),
                       encoding="utf-8")
    assert G.charger_apprises(str(fichier))[0][0]["severity"] == "INFO"


def test_une_severity_inventee_retombe_a_WARNING(tmp_path):
    fichier = tmp_path / "apprises.json"
    fichier.write_text(json.dumps({"regles": [{**SANS_TIMEOUT, "severity": "CRITIQUE"}]}),
                       encoding="utf-8")
    assert G.charger_apprises(str(fichier))[0][0]["severity"] == "WARNING"


def test_une_regle_appel_interdit_n_a_pas_besoin_de_kwarg(tmp_path):
    # L'exigence de `kwarg` ne vaut QUE pour la forme appel_sans_kwarg :
    # l'etendre a l'autre forme rejetterait toute regle d'interdiction.
    fichier = tmp_path / "apprises.json"
    fichier.write_text(json.dumps({"regles": [{"id": "apprise-pas-de-os-system",
                                               "forme": "appel_interdit",
                                               "cible": "os.system"}]}), encoding="utf-8")
    regles, rejets = G.charger_apprises(str(fichier))
    assert rejets == []
    assert [r["id"] for r in regles] == ["apprise-pas-de-os-system"]


def test_une_regle_sans_id_ou_sans_cible_est_rejetee(tmp_path):
    fichier = tmp_path / "apprises.json"
    sans_cible = {"id": "sans-cible", "forme": "appel_interdit"}
    sans_id = {"forme": "appel_interdit", "cible": "os.system"}
    fichier.write_text(json.dumps({"regles": [sans_cible, sans_id]}), encoding="utf-8")
    regles, rejets = G.charger_apprises(str(fichier))
    assert regles == []
    assert sorted(rejets) == ["<sans id>", "sans-cible"]


def test_un_fichier_absent_ne_produit_ni_regle_ni_rejet(tmp_path):
    assert G.charger_apprises(str(tmp_path / "jamais_ecrit.json")) == ([], [])


def test_les_regles_fixes_continuent_de_mordre_avec_des_apprises(tmp_path):
    # Une regle apprise s'AJOUTE au socle doctrinal, elle ne le remplace pas.
    trouve = _scan(tmp_path, "import anthropic\nimport subprocess\nsubprocess.run(['x'])\n",
                   [SANS_TIMEOUT])
    assert {f["rule"] for f in trouve} == {"laforge-no-anthropic-api-direct",
                                           "apprise-subprocess-run-sans-timeout"}
