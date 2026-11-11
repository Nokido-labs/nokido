# Reparation tests/nr/test_supervisor_ctl_via_hub_2b5_nr.py (2026-10-30)
- Quoi : adaptation de test_supervisor_ctl_via_hub_2b5_nr.py sans toucher au code de production.
- Pourquoi : commit 305711086 (28/10) ajoute une lecture prealable d'etat (_etat_service via GET /supervisor/status) et verification d'effet (_verifier_effet) pour stop, rendant le mock "ok" obsolete (code 4).
- Quelles attentes changent (mock) : faux _call renvoie un JSON plausible pour /supervisor/status (NokidoNR arrete, port 9999 libre) et _port_ouvert est neutralise.
- Quelles attentes changent (directs) : appel d'etat prealable ('GET', '/supervisor/status') integre aux attentes d'appels directs pour stop (hors SYSTEM, repli transition directe, sous SYSTEM direct).