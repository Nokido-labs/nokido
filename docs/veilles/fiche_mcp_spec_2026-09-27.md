# Fiche de sortie — Veille « orch_mcp_spec » : schéma MCP 2025-06-18 (2026-09-27)

Corpus : `watch:orch_mcp_spec:` — 1 page (`modelcontextprotocol/…/specification/2025-06-18/schema.mdx`), 17 chunks,
32 055 caractères de corps une fois retiré le préfixe rédigé à l'ingestion.
**CAPTURE PARTIELLE, MESURÉE le 27/09** : le sujet rédigé annonce « outputSchema, annotations readOnlyHint/destructiveHint/
idempotentHint/openWorldHint (hints non garantis) ». Le CORPS contient `readOnlyHint` (2), `ToolAnnotations` (2),
`structuredContent` (1), `isError` (1), `elicitation` (3), `_meta` (76) — mais `outputSchema`, `destructiveHint`,
`idempotentHint`, `openWorldHint` : **0**. C'est le piège du témoin hors sujet (26/09) : le sujet ne prouve pas la source.

## 1. PATTERNS (lus dans le corps)
| # | Pattern | Source |
|---|---|---|
| M1 | JSON-RPC : notification sans réponse, requête avec réponse, erreur avec un message court d'une phrase | schema.mdx |
| M2 | `_meta` réservé aux métadonnées | schema.mdx (76 occurrences) |
| M3 | Annotations de contenu : `audience` (`["user", "assistant"]`), `priority` de 0 à 1, `lastModified` ISO 8601 | schema.mdx |
| M4 | Progression hors bande par jeton opaque ; « The receiver is not obligated to provide these notifications » | schema.mdx |
| M5 | Pagination par curseur opaque | schema.mdx |
| M6 | Niveaux de log = sévérités syslog de la RFC 5424 | schema.mdx |
| M7 | Annotations d'outil (`ToolAnnotations`, `readOnlyHint`) ; « non garanties » selon le SUJET, non vérifié au corps | schema.mdx (partiel) |
| M8 | Élicitation : le serveur demande une information à l'utilisateur | schema.mdx |

## 2. NOKIDO_EXISTING
| Pattern | fichier:ligne | Constat |
|---|---|---|
| M7 | `app/forge_tool_annotations.py:29` | sémantique des annotations AVEC leurs défauts (`readOnlyHint` false, `destructiveHint` **true**) : PRÉSENT. |
| version | `app/forge_mcp_protocole.py:8`, `:49` | l'écho aveugle de `protocolVersion` a été corrigé : version rendue si supportée, sinon la première de `VERSIONS_SUPPORTEES` avec un motif. PRÉSENT. |
| version | `tools/forge_mcp_http.py:397` rend `2025-03-26` ; `app/forge_docker_supervisor.py:211` demande `2024-11-05` | versions hétérogènes ; `2025-06-18` (celle lue) non annoncée. |
| M1 | `app/forge_mcp_federation.py:176` lit `isError` ; `app/nokido_proxy_guard.py:133` l'émet | PRÉSENT. |
| M4, M5, `outputSchema`, `structuredContent` | — | non vus dans les 20 extraits montrés sur 45 par la recon : NON ÉTABLI. |

## 3. EVIDENCE
- **MEASURED** : comptes de termes dans le corps capté (ci-dessus).
- **PRÉSENT** : section 2, lue en recon, non exécutée.

## 4. GAPS
1. **Spec captée en partie** : toute décision sur `outputSchema` ou sur les trois autres hints exige de re-sourcer la page entière.
2. **Trois versions du protocole** dans le code (`2024-11-05`, `2025-03-26`, négociée) ; qui sert réellement `:8766` : à vérifier.
3. **Annotations** : un garde qui s'y FIE délègue sa sécurité à ce que le serveur déclare.

## 5. MINIMAL_EXPERIMENT (lecture seule)
Re-capture complète de la page (veille par URL) et comparaison champ à champ ; lecture de `VERSIONS_SUPPORTEES` et du
handshake réel (`tools/test_hub_mcp_handshake.py` existe).

## 6. NR
`test_annotation_absente_vaut_destructive` : un outil sans annotation est traité `destructiveHint = true` (défaut de la
spec, déjà écrit dans `forge_tool_annotations`) — existence dans `tests/` à vérifier avant d'en écrire un.

## 7. DECISION
- **ADOPT** : re-sourcer la spec complète AVANT toute décision sur `outputSchema` / `structuredContent`.
- **ADOPT (vérifier d'abord)** : aligner la version annoncée par `forge_mcp_http` sur la négociation de `forge_mcp_protocole`.
- **DEFER** : `outputSchema`, `structuredContent`, progression, pagination.
- **REJECT** : se fier aux annotations comme garde — le garde reste côté hub (videur, firewall, exec_tier).
