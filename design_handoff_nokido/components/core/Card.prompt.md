Carte de surface — l'atome réutilisé dans tout Nokido (tuiles du hub, modules, panneaux). Tuile d'icône teintée + titre + sous-titre + pied mono.

```jsx
<Card
  icon={<i data-lucide="route" />}
  iconColor="blue"
  title="Transport"
  subtitle="Trajets, mobilité, logistique perso"
  interactive
  footer="/transport/ → temps réel"
/>
```

- `interactive` ou `href` → survol : fond `bg-3` + halo violet (`shadow-glow`).
- `iconColor` reprend la teinte du domaine de la section.
- Contenu libre via `children` (jauges, listes, badges de provenance…).
