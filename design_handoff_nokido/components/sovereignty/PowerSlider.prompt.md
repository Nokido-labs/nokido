Curseur de puissance / souveraineté — contrôle central. Glisser vers la droite alloue plus de puissance → plus de local ; les métriques confidentialité / coût / latence se recalculent en direct.

```jsx
const [p, setP] = React.useState(60);
<PowerSlider value={p} onChange={setP} />
```

Autonome si on omet `onChange`.
