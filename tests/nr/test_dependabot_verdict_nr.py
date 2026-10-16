"""NR -- verdict automatique des PR Dependabot, fusion HUMAINE (decision owner du 2026-10-14).

Mesure du jour : #19 (depuis le 23/09), #24 (depuis le 07/10) et #27 avaient leur CI de quarantaine VERTE et
attendaient une revue que rien ne signalait ; le corps de #27 ne detaillait que 6 paquets sur 37 (tronque par
Dependabot). Contrats :
  1. classement : memes regles que `classer` (majeure, 0.x mineure = majeure, >= 5 mineures, paquets LOURDS) ;
  2. le diff complete un corps tronque, et une montee annoncee mais illisible est DITE, jamais comptee sure ;
  3. le chemin CLI reel (hors ligne) rend le commentaire marque ;
  4. le workflow suit la quarantaine, n'execute jamais le code de la PR, et ne fusionne / approuve / ferme rien.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import forge_deps_reconcilier as R  # noqa: E402

WF = ROOT / ".github" / "workflows" / "dependabot-verdict.yml"
OUTIL_IO = ROOT / "tools" / "forge_dependabot_verdict.py"


def test_niveaux_alignes_sur_classer():
    n = R.niveau_montee
    assert n("0.29.2", "0.29.3") == "CORRECTIF"          # #24 pyo3
    assert n("7.6.0", "10.2.0") == "MAJEURE"             # #19 setup-uv
    assert n("0.136.1", "0.143.0") == "MAJEURE"          # 0.x : une mineure casse l'API
    assert n("2.12.5", "2.14.0") == "MINEURE"
    assert n("5.10.1", "5.19.0") == "MAJEURE"            # >= 5 mineures, comme `classer`
    assert n("1.0", "1.0") == "INDETERMINE" and n("abc", "1.0") == "INDETERMINE"


def test_le_diff_complete_un_corps_tronque_et_l_illisible_est_dit():
    titre = "chore(deps): bump the python-racine group across 1 directory with 3 updates"
    corps = "Updates `requests` from 2.33.1 to 2.34.2\n"
    diff = "--- a/requirements.txt\n+++ b/requirements.txt\n-numpy>=1.26.4\n+numpy>=2.5.3\n"
    v = R.verdict_pr(titre, corps, "success", diff)
    paquets = {x["paquet"]: x for x in v["lignes"]}
    assert set(paquets) == {"requests", "numpy"} and v["annoncees"] == 3 and v["illisibles"] == 1
    assert paquets["numpy"]["lourd"] and paquets["numpy"]["niveau"] == "MAJEURE"
    assert v["recommandation"].startswith("A REVOIR")
    assert "ILLISIBLES" in R.texte_verdict(v)


def test_recommandations():
    simple = ("chore(deps): bump pyo3 from 0.29.2 to 0.29.3 in /rust_ext/forge_bm25 in the cargo-bm25 group",
              "Updates `pyo3` from 0.29.2 to 0.29.3\n")
    assert R.verdict_pr(*simple, "success")["recommandation"].startswith("PRET POUR REVUE")
    assert R.verdict_pr(*simple, "failure")["recommandation"].startswith("BLOQUE")
    titre_seul = R.verdict_pr("bump requests from 2.33.1 to 2.33.2", "", "success")
    assert [x["paquet"] for x in titre_seul["lignes"]] == ["requests"], "PR isolee : le titre suffit"


def test_le_chemin_cli_reel_hors_ligne(tmp_path):
    corps = tmp_path / "corps.md"
    corps.write_text("Updates `pyo3` from 0.29.2 to 0.29.3\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(OUTIL_IO),
                        "--titre", "chore(deps): bump pyo3 from 0.29.2 to 0.29.3", "--corps-fichier", str(corps),
                        "--ci", "success"], capture_output=True, text=True, errors="replace", timeout=60)
    assert r.returncode == 0, r.stderr[-500:]
    assert R.MARQUEUR_VERDICT in r.stdout and "PRET POUR REVUE" in r.stdout


def test_le_workflow_suit_la_quarantaine_et_ne_fusionne_rien():
    t = WF.read_text(encoding="utf-8")
    nom = re.search(r"^name:\s*(.+)$", (ROOT / ".github/workflows/ci-dependabot.yml").read_text(encoding="utf-8"),
                    re.M).group(1).strip()
    assert 'workflows: ["%s"]' % nom in t, "workflow_run doit viser %r" % nom
    assert "pull-requests: write" in t and "contents: read" in t
    assert "head_sha }}\n" not in t.split("uses: actions/checkout")[1].split("\n")[0], "jamais le code de la PR"
    assert "ref:" not in t, "le checkout reste sur la branche par defaut"
    assert "head_branch" not in t, "aucune donnee de la PR injectee dans une expression shell"
    assert "forge_dependabot_verdict.py --pr" in t
    io = OUTIL_IO.read_text(encoding="utf-8")
    for interdit in ('"merge"', "--approve", '"close"', "--admin", '"review"'):
        assert interdit not in io, "le verdict ne doit jamais %s" % interdit


def test_la_logique_reste_pure_dans_l_outil_d_analyse():
    """Garde test_l_outil_n_installe_rien : forge_deps_reconcilier ne lance aucun processus ; les appels gh vivent
    dans forge_dependabot_verdict.py, qui importe la logique au lieu de la dupliquer."""
    src = (ROOT / "tools" / "forge_deps_reconcilier.py").read_text(encoding="utf-8")
    assert "subprocess" not in src and '"gh"' not in src
    io = OUTIL_IO.read_text(encoding="utf-8")
    assert "import forge_deps_reconcilier as R" in io and "def niveau_montee" not in io
