"""NR P2_disque_coagulation : soin CIBLE (lesion -> remede) + cliquet anti-COUNT sur rag_chunks."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

PRODUCTEURS = {"forge_memory_availability.py", "forge_embed_backfill_cool.py"}
COUNT_RAG = re.compile(r"count\s*\(\s*(\*|1)\s*\)\s*from\s+rag_chunks", re.I)


def _fabrique(appels, nom):
    def chk(armed):
        appels.append(nom)
        return {}
    chk.__name__ = nom
    return chk


def test_une_lesion_ne_lance_que_son_remede(monkeypatch):
    import forge_remediation as mod
    appels = []
    noms = ["check_embed_backlog", "check_db_contention", "check_orphans", "check_stale"]
    monkeypatch.setattr(mod, "CHECKS", [_fabrique(appels, n) for n in noms])
    monkeypatch.setattr("nokido_agent.app.forge_heartbeat.beat_daemon", lambda *a, **k: None)
    mod.run_remediation_cycle(armed=False, lesions=["db_lock_contention"])
    assert appels == ["check_db_contention"]


def test_sans_lesion_connue_tous_les_controles():
    import forge_remediation as mod
    assert mod.controles_pour(["truc_inconnu"]) is None
    assert mod.controles_pour(None) is None
    assert mod.controles_pour(["embed_consolidation_debt", "orphan_debris"]) == {
        "check_embed_backlog", "check_orphans"}


def test_la_coagulation_transmet_les_lesions():
    src = (ROOT / "tools" / "forge_coagulation.py").read_text(encoding="utf-8")
    assert "lesions=" in src


# Dette HISTORIQUE (outils ponctuels / reparation) : gelee. Le cliquet n'admet aucun NOUVEAU venu ;
# un module de cette liste qui s'assainit doit en sortir (test_baseline_ne_contient_que_des_fautifs).
BASELINE = frozenset("""audit_rfc_compliance build_bge_m3_embeddings check_gitingest_rag ci_local diag_emb
evolutionary_engine forge_anatomy_state forge_auto_compact forge_bench_sample forge_circadian
forge_clawhub_autoinstall forge_cold_tier_cleanup forge_db_check forge_db_clean_install forge_db_instant_swap
forge_db_merge_final forge_db_recover forge_db_recover_chunks forge_db_restore_chunks forge_db_swap
forge_embed_backfill forge_embed_backfill_brain forge_embed_backfill_hybrid forge_embed_backfill_jina
forge_embed_backfill_voyage forge_embed_corpus_audit forge_embed_modal_bench
forge_embed_modal_campagne forge_embed_voyage_echantillon forge_faiss_sidecar forge_fix_null_ids forge_fts_repair
forge_guarded_change forge_health_diagnostic forge_hot_ingest forge_index_travail_embed
forge_ingest_ai_prompts_landscape forge_introspect forge_inventaire_docs_rag forge_mcp_registry
forge_mesure_journaux forge_meta_evolution forge_meta_tools forge_orchestrator_scaller forge_proprioception
forge_rag_coverage_audit forge_rag_embed_daemon forge_rag_index_app forge_rebuild_embeddings forge_rebuild_local
forge_reindex_deport forge_reingest_gitingest forge_research_agent forge_retier_corpus
forge_retrieval_baseline forge_retrieval_sweep forge_rss_watcher forge_sandbox_guard forge_self_correction
forge_skill_rag_bridge forge_stack_presence_audit forge_tui forge_vec_coverage forge_vector_index
forge_veille_audit forge_veille_backfill forge_veille_backlog_github forge_veille_depollute
forge_veille_intake_filter forge_veille_purge forge_watch_agent forge_web_service hub_live_patch
mcp_server_tools migrate_embedding_model_col nokido_core nokido_cutover_migrate nokido_hub patch
rag_archive_gitingest rag_purge_polluted_veille rag_status_report reembed_rag_bge relance_25_bruit_weak
watch_jobs_reset_truly_empty""".split())


def _suivis(sub):
    """Fichiers SUIVIS par git (24/10 : dans l'arbre partage, 6 brouillons tmp_*.py non suivis faisaient rougir le
    cliquet, vert dans le worktree propre du delegue -- un instrument juge le depot, pas les fichiers qui trainent)."""
    import subprocess
    try:
        r = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(ROOT), "ls-files", "--", "%s/*.py" % sub],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError):
        return list((ROOT / sub).glob("*.py"))   # git illisible : repli sur le disque, comportement d'avant
    if r.returncode != 0:
        return list((ROOT / sub).glob("*.py"))
    return [ROOT / p for p in r.stdout.splitlines() if p.count("/") == 1]


def _fautifs():
    out = set()
    for sub in ("app", "tools"):
        for f in _suivis(sub):
            if f.name in PRODUCTEURS:
                continue
            txt = f.read_text(encoding="utf-8", errors="ignore")
            if COUNT_RAG.search(txt):
                out.add(f.stem)
    return out


def test_cliquet_aucun_nouveau_count_rag_chunks_hors_producteur():
    nouveaux = _fautifs() - BASELINE
    assert not nouveaux, "COUNT sur rag_chunks hors producteur (lit la table) : %s" % sorted(nouveaux)


def test_baseline_ne_contient_que_des_fautifs():
    assainis = BASELINE - _fautifs()
    assert not assainis, "retirer de BASELINE (assainis) : %s" % sorted(assainis)


def test_les_organes_du_soin_sont_propres():
    assert not {"forge_remediation", "forge_coagulation"} & _fautifs()
