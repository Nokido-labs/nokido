<!-- DEPORTE depuis CLAUDE.md le 2026-09-19 pour tenir le budget du noyau resident.
     Le contenu n'a pas ete modifie : seul son LIEU a change.
     Mesure : cette section pesait 52% de CLAUDE.md, re-facture a chaque tour. -->

# 5. Protocole cadrage des LLMs externes

> Section de regles **deportee** hors du noyau resident. Elle n'est plus
> chargee a chaque tour ; elle se consulte a la demande (`rag`, `introspect`,
> ou lecture directe). Les pieges qu'elle decrit restent **EXECUTES** par
> `tools/hook_capability_gate.py`, dont les regles vivent dans SON code :
> deporter la prose ne desarme rien.

## 5. Protocole cadrage des LLMs externes

Quand Nokido delegue une tache a un LLM externe (cloud ou local) :

```python
from forge_semantic_firewall import get_firewall

fw = get_firewall()
pf = fw.pre_flight(prompt, context=system_prompt, ring=2, provider="auto")

if not pf.ok:
    # Blocage : injection detectee ou ring 0
    raise VetoSecurity(pf.reason)

# ⚠️ CORRIGE 2026-09-12 — MESURE, l'ancienne version de ce bloc etait FAUSSE.
# Elle disait « safe_task et safe_context sont rediges (PII remplacees par
# placeholders) ». `pre_flight` ne redige JAMAIS : il rend `ok=False` et un
# `safe_task` **VIDE** des que le DLP mord, et le prompt ORIGINAL inchange
# sinon. C'est un garde BINAIRE (passe / refuse), pas un redacteur.
# Mesure : une IP, un email ou un chemin Windows donnent tous `ok=False`,
# `dlp_triggered=True`, `len(safe_task) == 0`.
# Suivre l'ancienne consigne envoyait donc un PROMPT VIDE au modele a chaque
# detection — silencieusement.
# Le redacteur reel est `redact_text(texte) -> (texte_redige, mapping)`, et
# pour une sortie d'outil `redact_tool_output(texte, outil)`.
response_brut = await llm_call(pf.safe_task or prompt, pf.safe_context or system_prompt)

# post-flight sur la reponse
pfr = fw.post_flight(response_brut, task=prompt, session_id=session_id)
if not pfr.ok:
    # SSRF / social_eng / canary_leak / hallucination detectee
    return handle_drift(response_brut, pfr.reason)

# Restore : re-traduit les placeholders dans la reponse
clean = fw.restore(response_brut, pf.mapping)
return clean
```

Pour donnees sensibles structurees (configs, dumps, outputs techniques) :

```python
from forge_sovereign_membrane import SovereignMembrane

membrane = SovereignMembrane(mission_id="recon_20260424")
wrapped = membrane.wrap(raw_data)
# wrapped.content contient les alias HMAC persistants (memes par mission)
# wrapped.alias_map et decoy_meta dispo pour audit
response = await cloud_call(wrapped.content, tools=tools)
clean = membrane.unwrap(response, tool_calls=response.get("tool_calls"))
```

---

