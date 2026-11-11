# Parite pipeline RAG 2026-11-07 : NON MESUREE (aucun chiffre de recall, rien invente)
Commande lancee : aucune mesure. Seuls sondages en lecture : psutil, GET /health, lecture de code.
- Verdict : la question (0,945 -> >=0,99 en sortie finale ?) reste OUVERTE. Resultat = PARTIEL, voire nul.
- Requetes : C:\tmp\rag_parity_baseline.json a bien le texte des 20 requetes (champ q, domain), k=30. Utilisables.
- RAM avant reference exacte : psutil 91 % puis 77,3 % apres 260 s d'attente (seuil 82 % franchi, donc la reference aurait pu partir).
- qdrant.exe ws avant : 6372 Mo (pid 23124). Apres : non mesure (aucune requete envoyee).
- Reranker : :8100 (port arrêté, archive du 7/11) /health = timeout a la mesure. Pas de preuve qu'il tournait, il dormait probablement. Le repli serait le rerank Cohere, sinon lexical (_rerank).
- Obstacle 1 : `search_hybrid` n'est PAS dans la chaine de `RAGEngine.search`. Le dense passe par forge_faiss_sidecar.search_remote (port LAFORGE_VEC_SIDECAR_PORT, 8097 par defaut, injoignable ; :8098 = sidecar Qdrant). Sinon repli numpy.
- Obstacle 2 : seul `exact` se regle par env (LAFORGE_QDRANT_EXACT, defaut 1, lu dans le sidecar a chaque appel). hnsw_ef=256 et oversampling=2.0 sont en dur (forge_qdrant_sidecar.py L371-375). L'oversampling=3 de la consigne ne correspond pas au code. De plus, ces params ne servent que sur la branche dense seul (sans colbert ni prefetch RRF).
- Obstacle 3 : exact=0 exige un sidecar :8098 relance avec cet env, ou un monkeypatch de models.SearchParams dans mon process. Le prod n'a pas ete touche.
- Obstacle 4 : RAGEngine.search renvoie [] sans self.chunks. Charger ~691k chunks depuis %NOKIDO_DATA%\embeddings.db est un balayage interdit et pese plusieurs Go, a 77 % de RAM.
- Obstacle 5 : Bash n'admet que git/pytest dans ce worktree, donc pas de script lancable proprement. Aucun fichier de script cree, tools/ intact.
- Pistes : (a) l'owner reveille NokidoLlamaReranker (:8100) ; (b) mesurer au niveau sidecar avec forge_qdrant_parity.py (qvec rejoues, sans RAGEngine) ; (c) une version qui expose ef/oversampling par env, avec accord owner.
{"intent":"OK_DONE","pointer_ref":"parite_pipeline_20261107.md"}
