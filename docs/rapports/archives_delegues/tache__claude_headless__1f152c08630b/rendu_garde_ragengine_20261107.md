# Garde RAGEngine (7/11)

## Code
`RAGEngine._load_embeddings` (app/forge_rag_engine.py, appele en fin de `__init__` ~312) leve desormais RuntimeError
(message : outil `rag` du hub ou `POST :8098/search`) si AUCUNE de ces variables n'est posee :
- `LAFORGE_VEC_SIDECAR_PORT` (existant : le hub, deja lu par skip_emb),
- `LAFORGE_SERVICE_SELF` (existant : services supervises),
- `LAFORGE_RAG_FULL_LOAD=1` (nouveau, autorisation explicite).
NR : tests/nr/test_garde_ragengine_chargement_complet_nr.py (rouge vu, puis vert ; _db_connect monkeypatche, %NOKIDO_DATA%\embeddings.db jamais ouvert).

## Instanciations `RAGEngine(` (grep app/, tools/)
- app/forge_rag_engine.py:2425 `get_rag()` singleton : charge tout (hub, et tous les appelants de get_rag : agentic_engine, dispatchers, handler_*, silo_engine, full_reindex_core, tmp_ingest_core...). AUTORISE seulement si env ci-dessus.
- app/forge_mixin_ui.py:533, app/Nokido.py:3345 : TUI, charge tout (commentaires disent deja interdit hors hub) -> refuse desormais sans env.
- tools/bench_fixtures/gd_019_rag_search.py:6, forge_bench_engine.py:78, forge_golden_rappel.py:147, forge_retrieval_baseline.py:197, forge_source_discovery.py:706, ingest_ami_repos.py:72 : scripts, chargent tout -> refuses sans env (si lances depuis le hub avec env heritee, passent).
- Mentions en commentaire seulement : forge_hot_ingest.py:157, forge_rag_via_hub.py:7, Nokido.py:3338, ci_local.py:2732, forge_anchor_swebench.py:17, forge_swebench_runner.py:695, forge_golden_rappel.py:204, forge_tui_sonde.py:363.

## Doutes signales
- Je n'ai pas verifie que chaque service appelant `get_rag` (full_reindex_core, tmp_ingest_core, sidecars) porte `LAFORGE_SERVICE_SELF` ou le port sidecar : pose `LAFORGE_RAG_FULL_LOAD=1` dans leur environnement si besoin prouve. `full_reindex_core.py` pose seulement LAFORGE_ENV=test : probablement refuse.
- Tests existants qui construisent RAGEngine sans mock ni env : non executes (seul le NR concerne lance).

## Relance
Aucune pour le code des scripts. Le hub doit etre relance pour prendre le garde (il porte LAFORGE_VEC_SIDECAR_PORT, donc comportement inchange). Aucun redemarrage effectue.

{"intent":"OK_DONE","pointer_ref":"rendu_garde_ragengine_20261107.md"}
