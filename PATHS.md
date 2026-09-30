# Chemins & variables d'environnement

Ce depot public est generalise : les chemins specifiques a la machine
d'origine sont remplaces par des variables d'environnement, a definir
pour votre poste.

| Variable | Role | Exemple |
|---|---|---|
| `%NOKIDO_ROOT%` | racine du depot Nokido | `C:\Nokido` ou `~/nokido` |
| `%NOKIDO_WORKSPACE%` | dossier parent (workspace) | `C:\dev` |
| `%NOKIDO_DATA%` | stockage donnees (embeddings, RAG) | `D:\NokidoData` |
| `%USERPROFILE%` | profil utilisateur (natif Windows) | `C:\Users\vous` |

Les lanceurs `.bat`/`.ps1` expansent ces variables au runtime. Dans le
code Python et la doc, ce sont des placeholders a adapter (ou via
`os.path.expandvars`).
