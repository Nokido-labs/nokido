# Réflexes de développement — ils vivent dans le corps, pas dans l'agent (owner 2026-09-06)

Déportée VERBATIM de `RULES_SHARED.md` le 2026-11-04 (owner : « 16 % de contexte au démarrage »).

« Tes bonnes pratiques de dev doivent être des réflexes de Nokido. » Une pratique qui ne
vit que dans la session d'un agent disparaît avec elle et se re-paie ; chacune ci-dessous
a une forme EXÉCUTABLE dans le corps, et une session n'est pas close tant qu'une pratique
appliquée n'a pas la sienne.

| réflexe | forme dans le corps |
|---|---|
| Un état partagé par N processus (scripts, hooks, hub, daemons) bascule par un **interrupteur global** lu à chaque appel, jamais site par site : un site bascule seul = un hub qui écrit d'un côté et lit de l'autre | `forge_db_path.m2m_path()` + `sandbox/m2m.switch` ; les sites migrent SANS changement de comportement, vérifié par import réel (chaque module résout le même chemin qu'avant) ; NR `test_m2m_hors_embeddings_nr` |
| Un NR emprunte le **chemin réel** (point d'entrée, `__main__`, drapeau CLI), pas seulement la fonction : `check()` passait ses tests pendant que `--check` mourait en `NameError` | NR `test_le_point_d_entree_check_a_ses_imports` ; tout nouveau drapeau CLI a un test qui le traverse |
| Un instrument **ne lit jamais son propre vocabulaire** : sa source, ses commentaires, la doctrine qui le documente (5 fois payé en trois jours — audit lisant sa table INSTRUITS, `DB_PATH` pris pour la grosse base, un commentaire de migration citant l'ancien env) | l'audit exclut sa propre source du scan ; question à poser avant tout commit : « que verra-t-il en se lisant lui-même ? » puis vérifier APRÈS le commit |
| Observer avant d'enforcer : un gate neuf est **non bloquant** le temps de mesurer son bruit | gate `anatomie (0 module non classé)` ; à promouvoir bloquant sur mesure, jamais d'emblée |
| Un capteur neuf est un **suspect**, pas un témoin : croiser avec le log de l'organe ou une seconde sonde avant d'agir | section « Avant d'AGIR sur un diagnostic » ; `hook_recon_first` |
