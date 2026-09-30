Bouton d'action principal de Nokido — violet plein par défaut, avec variantes ghost / danger / success et trois tailles.

```jsx
<Button variant="primary" onClick={save}>Enregistrer</Button>
<Button variant="ghost" size="sm">Annuler</Button>
<Button variant="danger" icon={<i data-lucide="trash-2" />}>Révoquer</Button>
```

- `variant`: `primary` (violet souverain), `ghost` (bordure, vire au violet au survol), `danger` (rouge), `success` (vert, texte sombre).
- `size`: `sm` (30px), `md` (36px, défaut), `lg` (44px — cible tactile AA).
- `icon` / `iconRight`: passer un nœud d'icône Lucide ou SVG.
