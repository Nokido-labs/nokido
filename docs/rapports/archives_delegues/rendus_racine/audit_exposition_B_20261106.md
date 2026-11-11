# Audit Exposition B (2026-11-06)

## Objectif

Vérifier que les outils natifs des clients CLI ne contournent pas le filtre souverain.

## Résultats

| Client       | Accès                     | Passe par le filtre ? | Preuve (fichier:ligne)                                                                 | Gravité | Correctif minimal                                                                 |
|--------------|---------------------------|---------------------------|----------------------------------------------------------------------------------|----------|---------------------------------------------------------------------------------|
| Claude Code  | Lecture locale sans hub     | NON                       | tools/forge_task_executor.py:3915                                              | ÉLEVÉE   | Ajouter un filtre dans `_delegate_to_opencode` pour les lectures locales.       |
| AGY          | Écriture directe           | NON                       | app/forge_rag_engine.py:161                                                     | ÉLEVÉE   | Implémenter un hook d'écriture dans `RAGEngine`.                                 |
| OpenCode     | Accès réseau sans proxy     | NON                       | tests/nr/test_rerank_cloud_par_membrane_nr.py:31                                | ÉLEVÉE   | Forcer l'utilisation de `forge_openai_proxy.py` pour toutes les requêtes réseau. |
| Mistral Vibe | Lecture de fichiers privés | ILLISIBLE                | app/forge_sovereign_membrane.py:134                                            | ÉLEVÉE   | Implémenter un contrôle d'accès dans `agent_expose`.                             |
| Codex        | Exécution de commandes     | NON                       | app/forge_prompt_guard.py:289                                                   | ÉLEVÉE   | Ajouter une vérification dans `detect_injection`.                                |
| Cline        | Accès à la base RAG        | NON                       | app/forge_rag_engine.py:161                                                     | ÉLEVÉE   | Implémenter un contrôle d'accès dans `requete_fts`.                             |
| Copilot      | Lecture de sessions        | ILLISIBLE                | app/forge_sovereign_membrane.py:134                                            | ÉLEVÉE   | Implémenter un contrôle d'accès dans `agent_expose`.                             |

## Conclusion

Tous les clients CLI ont des accès non gouvernés qui doivent être filtrés par le hub Nokido.