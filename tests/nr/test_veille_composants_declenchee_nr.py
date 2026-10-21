"""NR -- la veille des composants a un DECLENCHEUR et couvre Vibe et OpenCode (owner 20/08 + 17/10).

Owner 20/08 : « a chaque mise a jour de claude je veux que tu check s'il y a du neuf, pareil pour tous les cli ! » ;
17/10 : « veille introspective de chacun de tes composants », « absorber les changelog lors de maj de composant ».
Mesure 17/10 : tools/forge_cli_version_watch.py n'avait plus tourne depuis le 24/09 (sandbox/cli_versions.json) --
la lecon du 24/09 « une veille sans declencheur n'est pas une veille » n'avait pas ete cablee ; et ses cibles ignoraient
Mistral Vibe et OpenCode, les deux surfaces branchees les 16-17/10. Mesures d'URL du 17/10 : docs.mistral.ai/llms.txt
= 200 (376 pages, dont Vibe) ; opencode.ai n'a PAS de llms.txt (404) -- ses notes de version (le changelog) sont les
releases GitHub d'anomalyco/opencode, suivies par leur flux Atom, jamais passees a l'ingesteur de llms.txt.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_cli_version_watch as W  # noqa: E402

SUP = ROOT / "proxy_deno" / "core" / "supervisor.ts"


def _cible(cle):
    return next((c for c in W.CIBLES if c[0] == cle), None)


def test_vibe_et_opencode_sont_des_cibles_de_la_veille():
    vibe, oc = _cible("mistral_vibe"), _cible("opencode")
    assert vibe and vibe[1] == "vibe" and vibe[2] == "https://docs.mistral.ai/llms.txt" and vibe[3], vibe
    assert oc and oc[1] == "opencode" and oc[2].endswith("anomalyco/opencode/releases.atom"), oc


def test_une_cible_sans_llms_txt_n_est_jamais_passee_a_l_ingesteur():
    """Le flux de releases d'OpenCode n'est pas un llms.txt : domain None, et l'ingestion le saute."""
    assert _cible("opencode")[3] is None
    src = (ROOT / "tools" / "forge_cli_version_watch.py").read_text(encoding="utf-8")
    i = src.index("if a.ingest_si_neuf and changements and not premier:")
    assert "not domain" in src[i:i + 400], "une cible sans domain RAG serait envoyee a forge_ingest_llms_txt"


def test_la_phase_nrem1_declenche_la_veille_en_ligne():
    src = SUP.read_text(encoding="utf-8")
    i = src.index('if (phase === "NREM1") {')
    bloc = src[i:i + 9000]
    assert '"forge_cli_version_watch.py"' in bloc, "aucun declencheur de la veille des composants"
    j = bloc.index('"forge_cli_version_watch.py"')
    assert "online: true" in bloc[j:j + 700], "la veille lit des docs en ligne : online: true"
