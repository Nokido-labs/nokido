# Dossier — Nokido au répertoire de connecteurs d'Anthropic

Décision owner 3/11 ~4 h 40 (choix multiple) : **préparer le dossier, ne rien soumettre**. Soumettre = geste owner
(portail `claude.ai/directory/manage`, compte payant). Sources lues au RAG (ingérées le 3/11, job_98d874dfbc1c,
281 pages) : `claude_docs:claude.com/docs/connectors/building/{submission,review-criteria,authentication}.md`,
`claude_docs:claude.com/docs/connectors/building/directory-vs-custom.md`, `claude_docs:claude.com/docs/directory/publish.md`.

## Ce qui serait listé

Le **connecteur des pairs** (`tools/forge_pair_mcp.py`, port 8793, Funnel) — jamais le `/mcp` du hub. Une instance
Nokido est auto-hébergée : chaque utilisateur a SON URL → listing à **motif d'URL** (ex.
`^https://[a-z0-9-]+\.[a-z0-9-]+\.ts\.net/mcp$`), publiable seulement avec le label **Verified**, revue plus longue.
Cible réaliste : la version distribuable (plan OAuth E8), pas l'instance de l'owner. D'ici là, distribution par
**lien d'installation de connecteur personnalisé** (aucune revue) :
`https://claude.ai/customize/connectors?modal=add-custom-connector&connectorName=Nokido&connectorUrl=<URL encodée>`.

## Écarts mesurés (3/11)

| Exigence (source) | Nokido | État | Réparation |
|---|---|---|---|
| Serveur distant HTTPS (submission) | Funnel `https://<machine>.<tailnet>.ts.net` → 8793 ; gardien au tray 7df545570 | OK (instance owner) | motif d'URL pour la version distribuable |
| OAuth 2.0, DCR ou CIMD, PKCE S256, 401 + `resource_metadata` (authentication) | pont : autorité locale + appariement ; hub : DCR + PKCE + ES256 TPM ; P1 9c5ad8429 admet le redirect claude.ai | PARTIEL | lot P2-P5 (pont sur l'autorité du hub) ; P6 CIMD (`client_id_metadata_document_supported` + `none`) — recommandé pour un fort trafic de répertoire (DCR = un client par connexion) |
| `title` + `readOnlyHint`/`destructiveHint` sur CHAQUE outil (review-criteria, submission) | **0/14** outils annotés (mesure `construire_serveur().list_tools()`) | ÉCART | annoter les 14 : lecture (`etat_corps`, `point_ssot`, `recherche_rag`, `journal_commits`, `derniere_capsule`, `lire_document`, `suivre`, `lire_reponses`, `lire_annexe`, `lire_vivant`) `readOnlyHint` ; dépôts (`proposer_fait`, `deposer_fragment`, `envoyer_message`, `soumettre_tache`) `destructiveHint=false` + non lecture seule. Gain immédiat : claude.ai exécute les lectures sans confirmation à chaque appel |
| Noms ≤ 64 caractères (review-criteria) | 14 noms courts | OK | — |
| Descriptions exactes, sans motif d'injection (« appelle tel outil », « n'utilise pas les autres ») (review-criteria) | non audité | À AUDITER | relecture des 14 descriptions contre la liste de rejet |
| Politique de confidentialité HTTPS (collecte, usage, stockage, tiers, rétention, contact) — absence = rejet immédiat (submission) | aucune | ÉCART | rédiger : données sur la machine de l'utilisateur ; ce que claude.ai transmet à Anthropic ; journaux d'audit locaux ; rétention ; contact |
| URL de documentation, contact de support, icône (submission) | README PyPI (nokido-agent) ; icône Nokido (`nokido_tray._icone_bureau`) ; contact non décidé | PARTIEL | page « connecteur claude.ai » dans la doc distribuée ; contact = décision owner |
| Compte de test peuplé pour les relecteurs (submission) | aucun : instance personnelle | ÉCART STRUCTUREL | instance de démonstration à données factices (hors corps de l'owner), jamais l'instance réelle |
| Testé dans Claude comme connecteur personnalisé (submission) | claude.ai Nokido connecté le 3/11 04:28 | OK | rejouer après P5 |
| Conditions : maintenir la sécurité, répondre aux incidents (submission) | — | ENGAGEMENT | décision owner au moment de soumettre |
| Plan payant (publish) | Max | OK | — |

## Ordre proposé

1. Annotations des 14 outils (petit, utile tout de suite) — NR : chaque outil de `list_tools()` a `title` et une
   indication.
2. Lot P2-P5 (pont sur l'autorité du hub, ring au jeton, ring 1 sans quarantaine).
3. P6 CIMD.
4. Audit des descriptions + politique de confidentialité + page de doc.
5. Instance de démonstration (E8 distribuable) → soumission par l'owner, motif d'URL, label Community puis Verified.
