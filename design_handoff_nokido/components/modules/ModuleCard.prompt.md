Carte de section/module — l'unité de la grille du hub. Filet d'accent par domaine, bascule activer/désactiver, provenance, statut, état « bientôt ».

```jsx
<ModuleCard domain="sante" title="Santé" desc="Local forcé — confidentialité maximale"
  icon={<i data-lucide="heart-pulse" />} provenance="local" enabled onToggle={setOn} />
<ModuleCard domain="jeux" title="Jeux vidéo" comingSoon icon={<i data-lucide="gamepad-2" />} />
```

Domaines : transport, sante, finance, loisir, achat, creation, jeux, dev, domotique.
