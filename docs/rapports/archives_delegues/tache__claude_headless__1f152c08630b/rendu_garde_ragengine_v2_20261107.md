# Garde RAGEngine v2 — 2026-11-07

## Fait
- `_load_embeddings` (app/forge_rag_engine.py) : sans `LAFORGE_RAG_FULL_LOAD` ni `LAFORGE_VEC_SIDECAR_PORT` -> aucun SELECT, `self.chunks=[]`, `self._degraded=True`, warning (outil `rag`, `POST :8098/search`, `LAFORGE_RAG_FULL_LOAD=1`). Plus d'exception a l'instanciation.
- `search()` en mode degrade : `RuntimeError` explicite. Pas de FTS seul : `_scores_lexicaux` rattache ses hits a `self.chunks` via `_lex_map` et dimensionne `_bm` sur `len(self.chunks)` ; avec 0 chunk il ne rendrait rien. Jamais de `[]` pris pour « rien trouve ».
- `LAFORGE_SERVICE_SELF` retire des autorisations. Il est pose par forge_autonomous_loops.py:4721 (veto de sommeil, lu par forge_mutation_controller) : sans lien avec le chargement. Aucun service prouve en avoir besoin ; un service qui en a besoin pose `LAFORGE_RAG_FULL_LOAD=1`.
- NR : tests/nr/test_garde_ragengine_chargement_complet_nr.py (rouge d'abord : 3 echecs, `_db_connect` simule), 5 verts. tests/test_rag_injection_filter.py : `_load_embeddings` simule, vert. %NOKIDO_DATA%\embeddings.db jamais ouvert.

## Point 4 — skip_emb (verifie par lecture, rien execute)
AGY a raison sur le code : avec `LAFORGE_VEC_SIDECAR_PORT`, `skip_emb=True` retire seulement la colonne `embedding` du SELECT (+ une sonde `LIMIT 1`), mais execute `SELECT id,text,source,domain,role_hint,meta,quality_score FROM rag_chunks WHERE active...` et itere TOUT le curseur en construisant un dict par ligne dans `self.chunks`. Le commentaire du code chiffre ce cout a ~3,4 Go (texte 2,63 + dicts 0,74), coherent avec le « ~3,5 Go » d'AGY (qui n'est pas « sans vecteurs = leger »).
Le `__init__` appelle `_load_embeddings()` sans condition. Donc si le hub instancie `RAGEngine` (ou `get_rag()`), il balaie. Sa RSS mesuree, loin de 3,5 Go, ne se concilie qu'ainsi : le hub n'instancie pas le moteur local dans ce chemin (je n'ai pas prouve lequel, pas de mesure autorisee), ou la charge est faite ailleurs. A trancher par l'owner. Comportement du hub NON modifie ; le balayage skip_emb est signale ici.

## Point 5 — outils de banc devant poser `LAFORGE_RAG_FULL_LOAD=1`
Instancient `RAGEngine()` : tools/forge_bench_engine.py:78, tools/forge_golden_rappel.py:147, tools/forge_retrieval_baseline.py:197 (via `search`). forge_source_discovery.py ne fait que citer forge_rag_engine (L683) : a verifier, pas de pose imposee. TUI (Nokido.py:3345, forge_mixin_ui.py:533) : seulement opt-in `LAFORGE_TUI_RAG_LOCAL=1` ; sinon `RAGViaHub`. Je n'ai pas modifie ces outils (pose a faire par l'appelant/l'owner). Preuve : sans la variable ils obtiennent un moteur degrade et `search` leve.
