Marqueur de provenance — montre OÙ vit le calcul (local / hybride / distant) et l'anneau d'intégrité de la donnée. À apposer sur chaque réponse, donnée et action.

```jsx
<ProvenanceBadge origin="local" ring="gold" detail="ollama · 612ms" />
<ProvenanceBadge origin="remote" ring="verified" detail="groq" />
<ProvenanceBadge origin="hybrid" />
```

- `origin`: `local` (vert), `hybrid` (cyan), `remote` (violet).
- `ring`: `draft` (cercle pointillé gris), `verified` (cyan), `gold` (jaune lumineux).
