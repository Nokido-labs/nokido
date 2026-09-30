<!-- DEPORTE depuis RULES_SHARED.md le 2026-09-19 pour tenir le budget du noyau resident.
     Le contenu n'a pas ete modifie : seul son LIEU a change.
     Mesure : cette section pesait 52% de RULES_SHARED.md, re-facture a chaque tour. -->

# Consulter la cognition AVANT d'agir — mesure, puis CABLE (owner 2026-09-13)

> Section de regles **deportee** hors du noyau resident. Elle n'est plus
> chargee a chaque tour ; elle se consulte a la demande (`rag`, `introspect`,
> ou lecture directe). Les pieges qu'elle decrit restent **EXECUTES** par
> `tools/hook_capability_gate.py`, dont les regles vivent dans SON code :
> deporter la prose ne desarme rien.

## Consulter la cognition AVANT d'agir — mesure, puis CABLE (owner 2026-09-13)

« Tu n'es qu'un client parmi d'autres ; le renforcement par les actions passees doit
agir, sinon on recommence systematiquement a zero. » La regle existait deja partout
dans ce fichier ; ce qui manquait, c'est qu'elle MORDE.

**La mesure qui a decide.** `forge_introspect.bilan()` journalise depuis le 2026-08-31
chaque edition, avec ou sans consultation prealable. Au 2026-09-13 : **2 886 editions,
381 avec consultation, soit 13,2 %** — et les deux agents clients (CLAUDE, ANTIGRAVITY)
sont loges a la meme enseigne. L'avertissement non bloquant pose le 31/08 a donc ete
emis des milliers de fois sans rien changer. Un garde qu'on peut lire et ignorer n'est
pas un garde, c'est une note.

**Ce qui a ete paye le 2026-09-13, en une session :** dix scripts d'instrument crees,
dont TROIS refaisaient un outil existant — `tools/forge_ci_profil.py` (profil de la
suite pure, ecrit sur demande owner le 04/09), `app/forge_service_rss_watch.py`
(capteur de derive memoire) et le profilage scalene, dont la fiche du 20/08 disait
DEJA que ni scalene ni memray n'atteignent la memoire native sous Windows — c'est-a-dire
qu'elle repondait a la question avant qu'elle soit reposee. Plus deux correctifs sans
effet, que le registre d'atteignabilite annoncait (`run_reclaimers` : 0 occurrence en
tests).

**L'ordre de consultation, du plus dense au plus large :**

1. `introspect question="<le probleme>"` — rend en UN appel les symboles, les
   procedures DEJA appliquees (avec leur etat PROUVE/CONSTATE), les enquetes
   anterieures et leurs pieges, et ce qu'il n'a PAS pu consulter.
2. `tools/forge_retrieval_sweep.py <terme>` — 8 surfaces, dont **les outils par leur
   NOM**. C'est l'etape que chercher le seul CONTENU rate : le 13/09, un sweep sur une
   phrase a rendu « presque rien » la ou un glob sur les noms de modules sortait
   immediatement `forge_reachability_ledger`, `forge_ci_profil`, `forge_scalene_*`.
3. `tools/forge_symptom_index.py --ask <symptome>` — les enquetes deja menees. Il rend
   des FAUX NEGATIFS et le DIT : « terrain neuf » n'est jamais une preuve d'absence.
4. Les fiches `memory/*.md` du domaine, en suivant les `[[liens]]`.

**Le garde.** `tools/hook_recon_first.py` refuse UNE fois la creation d'un module du
depot **ou d'un script d'instrument** sans consultation FRAICHE
(`TTL_CONSULTATION_CREATION_S`, 1 h). Le drapeau `__memoire__` etait global a TTL 24 h :
une consultation faite la veille, sur un tout autre sujet, desarmait le garde pour la
journee entiere (mesure : 13,1 h d'anciennete, dix scripts crees, zero blocage). Un
garde dont le signal est trop grossier ne garde rien. NR de comportement :
`tests/nr/test_appui_hook_recon_first_nr.py`.

**Reste une zone d'ombre, et elle est VOULUE.** La promotion de l'avertissement de
`governed_edit` en refus vit dans `app/forge_mcp_registry.py`, un CRITICAL_FILE : un
agent ne peut pas durcir — ni desarmer — le garde qui le contraint. C'est le principe
du 2026-09-13 (« un garde dont l'interrupteur est a portee de ce qu'il contraint ne
garde rien »). Ce geste-la est OWNER, par construction.

<!-- M2M:BEGIN genere par tools/forge_m2m_emanate.py - NE PAS editer a la main -->
