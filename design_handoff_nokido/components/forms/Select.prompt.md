Menu déroulant — chevron custom, focus violet. Options en chaînes ou `{ value, label }`.

```jsx
<Select label="Fournisseur" value={p} onChange={e=>setP(e.target.value)}
  options={["Ollama (local)", "Groq", "Gemini", "Mistral"]} />
```
