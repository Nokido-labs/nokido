"""NR -- lot 1 du chantier SECU (bb:active_bugs/secu_secrets_cloud_lus_dans_env_37_fichiers_geles_20261016) :
les CLES FOURNISSEURS se lisent au coffre d'abord (forge_key_rotation.resolve / forge_secrets.get_secret), l'env
n'est qu'un repli DIT. Oracle : la regle laforge-cloud-secret-from-env de tools/forge_golden_rules_ast.py, qui
accepte deja un repli lu APRES le coffre (_repli_apres_coffre) -- c'est le motif de forge_rag_engine (COHERE).
RED de Claude (16/10), code par AGY (partage valide par l'owner).
"""
import os
import sys

_DEPOT = os.environ.get("NOKIDO_DEPOT") or os.path.join(os.path.dirname(__file__), "..", "..")
_TOOLS = os.path.join(_DEPOT, "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import forge_golden_rules_ast as g  # noqa: E402

# Famille 2 (cles fournisseurs) -- sites mesures le 16/10 :
LOT = (
    "app/forge_swarm_team.py",        # LITELLM_API_KEY l.911, MISTRAL_API_KEY l.1092
    "app/forge_task_router.py",       # HF_TOKEN l.93, PERPLEXITY_API_KEY l.113
    "tools/claude_precompact.py",     # GROQ_API_KEY l.59
    "tools/evolutionary_engine.py",   # ANTHROPIC_API_KEY l.772/774, GEMINI_API_KEY l.1567/1571
    "tools/forge_cve_nvd_download.py",  # NVD_API_KEY l.29
    "tools/forge_reindex_deport.py",  # HF_TOKEN, NVIDIA_NIM_API_KEY, NVIDIA_API_KEY, CLOUDFLARE_AI_API_KEY
    "tools/multi_llm_daemon.py",      # GROQ_API_KEY l.284
)
FOURNISSEURS = ("GROQ", "MISTRAL", "COHERE", "ANTHROPIC", "GEMINI", "NVIDIA", "CLOUDFLARE", "HF_TOKEN",
                "OPENROUTER", "PERPLEXITY", "LITELLM", "NVD", "LANGFUSE")


def test_le_lot_fournisseurs_lit_le_coffre_d_abord():
    restants = []
    for rel in LOT:
        for f in g.scan_file(os.path.join(_DEPOT, rel)):
            if f["rule"] == "laforge-cloud-secret-from-env" and any(p in f["message"] for p in FOURNISSEURS):
                restants.append("%s:%s %s" % (rel, f["line"], f["message"][:60]))
    assert not restants, "\n".join(restants)
