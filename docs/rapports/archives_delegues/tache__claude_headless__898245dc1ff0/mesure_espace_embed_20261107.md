# Mesure de l'espace vectoriel commun (2026-11-07)

## Statut : NON EXECUTEE. Aucun chiffre.

`run action=run_job online=true rss_cap_mb=1500` a refuse le script :
`script must be under C:/tmp ou Nokido root`.
Le script est sous le worktree `nokido_worktrees/taches/claude_headless_898245dc1ff0/mesure_embed/`, qui n'est ni sous `C:/tmp` ni sous la racine Nokido pour ce garde.

Je n'ai pas contourne le refus. Copier le script sous `C:/tmp` aurait contredit la consigne « sous ton worktree ». Aucune mesure n'a donc ete lancee.

Verdict par paire :
- local-Modal : ILLISIBLE (non mesure)
- local-Cloudflare : ILLISIBLE (non mesure)
- Modal-Cloudflare : ILLISIBLE (non mesure)

## Ce qui est pret
- `mesure_embed/lot_public.txt` : 100 textes publics FR/EN, aucun texte de la base. Il est ecrit, mais son hash n'est pas encore note, car le script le calcule au lancement (`lot_sha256` dans la sortie).
- `mesure_embed/mesure_espace.py` : client HTTP seul.
  - local par `_llama8099_call`, avec `embed.wanted` et jusqu'a 10 essais espaces de 20 s ;
  - Modal avec un appel de chauffe de 2 textes non compte, puis 3 essais au plus ;
  - Cloudflare avec un lot toutes les 65 s, 4 essais au plus, et trace de la presence de « 429 » dans les logs.
  - Sortie : dimensions, normes, cosinus min / mediane / max, voisin de rang 1, temoin de textes differents, verdict (min >= 0,9990, mediane >= 0,9995, rang 1 partout).
  - Aucune ecriture en base ni dans Qdrant, pas de `RAGEngine`, pas de configuration touchee, `LAFORGE_EMBED_MODAL_VALIDE` non pose.
  - Les secrets passent par les fonctions du routeur, par leur nom, jamais par leur valeur.
- Limite connue : le script n'ecrit rien dans un log en dehors du JSON final.

## Decision requise de l'owner
Autoriser l'un de ces deux chemins :
1. lancer ce script depuis `C:/tmp` (copie du fichier et du lot) ;
2. ajouter le worktree aux chemins admis par `run_job`.

{"intent":"ERR_INTERNAL","pointer_ref":"mesure_espace_embed_20261107.md","commit_message":"chore(mesure): script et lot public de mesure d'espace embed, non execute (run_job refuse le chemin)"}
