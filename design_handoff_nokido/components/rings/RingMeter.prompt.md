Le **Ring-O-Meter** : le modèle d'intégrité à 11 anneaux de Nokido. Ring 0 (Lois absolues) au centre → Ring 10 (Corrections de Cap) à l'extérieur. Sert à montrer sur quelle couche un agent/une donnée est placé et ce que ça implique.

```jsx
<RingMeter
  states={{ 0: "ok", 2: "alert", 9: "block" }}
  selected={sel}
  onSelect={setSel}
/>
```

- Dégradé sémantique : centre **vert** (souverain/core) → extérieur **violet** (système/externe).
- États : `ok` (couleur du ring), `alert` (jaune pulsé), `block` (rouge), `inactive` (gris).
- `RingMeter.RING_META` expose les 11 labels + descriptions ; `RingMeter.ringColor(i)` la couleur d'un ring.
