# -*- coding: utf-8 -*-
"""forge_m2m_emanate.py — Émanation du dictionnaire M2M vers RULES_SHARED.md.

Génère la section entre les marqueurs M2M:BEGIN / M2M:END de RULES_SHARED.md
depuis config/m2m_intents.json (SSoT). Section volontairement COMPACTE :
RULES_SHARED est chargé dans le contexte de CHAQUE session (@import CLAUDE.md
et GEMINI.md) — chaque ligne coûte des tokens à chaque tour.

Idempotent : marqueurs présents -> remplace ; absents -> append en fin.
Re-lancer après chaque bump de version du JSON.

Run : run action=trusted_script path=tools/forge_m2m_emanate.py
"""

__FORGE_COLOR__ = "cerveau/message_frame : emanation du dictionnaire M2M vers RULES_SHARED"  # organe declare le 2026-09-06 (audit de raccordement)
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG = os.path.join(ROOT, "config", "m2m_intents.json")
RULES = os.path.join(ROOT, "RULES_SHARED.md")

BEGIN = "<!-- M2M:BEGIN genere par tools/forge_m2m_emanate.py - NE PAS editer a la main -->"
END = "<!-- M2M:END -->"

cat = json.loads(open(CATALOG, "rb").read().decode("utf-8"))
rules = cat.get("schema_rules", {})
intents = cat.get("intents", {})
by_cat = {}
for code, spec in intents.items():
    by_cat.setdefault(spec.get("category", "autre"), []).append(code)

req = rules.get("required_fields_by_channel", {})
req_line = " · ".join(f"{ch}={{{','.join(fields)}}}" for ch, fields in req.items())
cats_lines = "\n".join(f"- {c}: {', '.join(sorted(codes))}" for c, codes in sorted(by_cat.items()))

# 2026-09-17 -- l'entete enumerait TROIS canaux (notify/postal/task_result) quand
# le catalogue en porte CINQ (+ task_assign, + transient). Doublement fautif : la
# liste etait redondante avec `Champs requis` juste dessous, et elle etait devenue
# FAUSSE. La retirer rend 37 octets sur le poste `kernel_depot`, qui depassait sa
# borne de 29 o apres la campagne transient (gate `test_budget_contexte_nr`).
# Corrige ICI, a la SOURCE : RULES_SHARED.md est genere, une retouche a la main y
# serait ecrasee a la prochaine emanation et le depassement reviendrait.
section = f"""{BEGIN}
## Protocole M2M inter-agents (v{cat.get('version', '?')})

Message M2M = JSON `{{intent, pointer_ref, ...}}`
avec `intent` (alias `intent_code`) du dictionnaire `config/m2m_intents.json` +
`pointer_ref` vers le SSoT (blackboard/commit/RAG) — JAMAIS de lettre littéraire.
Prose libre tolérée ≤ {rules.get('prose_max_words', 15)} mots (au-delà : M2M_WARN_PROSE ;
refus si LAFORGE_M2M_MODE=error). Validateur = `app/forge_m2m_protocol.py`.
Champs requis : {req_line}.
Intents :
{cats_lines}
{END}"""

raw = open(RULES, "rb").read().decode("utf-8")
nl = "\r\n" if "\r\n" in raw else "\n"
text = raw.replace("\r\n", "\n")

if BEGIN in text and END in text:
    head, rest = text.split(BEGIN, 1)
    zone, tail = rest.split(END, 1)
    # GARDE (incident 2026-09-02) : cet outil a detruit 31 775 octets de
    # RULES_SHARED.md -- la table « Capacites d'execution » et « DEJA EN PLACE »,
    # soit la memoire operationnelle de TOUS les agents clients.
    #
    # Le script n'avait pas de bug : il remplacait bien « entre les marqueurs ».
    # Le defaut etait que deux sections ECRITES A LA MAIN se trouvaient DANS une
    # zone estampillee « NE PAS editer a la main » -- BEGIN etait pose 200 lignes
    # trop haut et END sur la derniere ligne du fichier. La bombe etait armee
    # depuis ce jour-la ; une reemanation l'a amorcee.
    #
    # On refuse donc d'ecraser une zone qui contient une AUTRE section que la
    # notre. Un marqueur mal place doit se voir AVANT la perte, pas apres.
    titres = [l for l in zone.splitlines()
              if l.startswith("## ") and "Protocole M2M" not in l]
    if titres:
        print("REFUS : la zone M2M contient %d section(s) qui ne lui appartiennent "
              "pas -- un marqueur est mal place et les ecraser les DETRUIRAIT :"
              % len(titres))
        for t in titres:
            print("   -", t[:90])
        print("Deplacer <!-- M2M:BEGIN --> juste avant '## Protocole M2M', "
              "puis relancer.")
        raise SystemExit(2)
    # Second garde, independant du premier : une emanation ne doit jamais RETIRER
    # de la matiere. Elle remplace une section par une section, pas un fichier par
    # un fragment.
    nouveau = head + section + tail
    if len(nouveau) < len(text) * 0.9:
        print("REFUS : l'ecriture reduirait le fichier de %d a %d octets (-%.0f%%). "
              "Une emanation remplace une SECTION, elle n'ampute pas un fichier."
              % (len(text), len(nouveau), 100 * (1 - len(nouveau) / max(1, len(text)))))
        raise SystemExit(2)
    text = nouveau
    action = "replaced"
else:
    text = text.rstrip("\n") + "\n\n" + section + "\n"
    action = "appended"

# IDEMPOTENCE, ajoutee le 2026-09-17. Ce module s'execute AU MOMENT DE L'IMPORT
# (il n'a aucun bloc `__main__`) : le simple fait de l'importer ECRIVAIT le
# fichier, y compris depuis un compte qui n'a pas le droit d'ecrire a la racine
# du depot -- le test d'appui mourait alors en PermissionError alors qu'il n'y
# avait rien a propager. Meme famille que « l'import ne touche plus le disque »
# (mesure du 2026-08-21). On n'ecrit donc QUE si le contenu CHANGE : le mtime et
# le diff git restent propres, et relancer l'emanation devient sans effet de bord.
_sortie = text.replace("\n", nl).encode("utf-8")
if _sortie == raw.encode("utf-8"):
    print(f"OK: section M2M deja a jour dans RULES_SHARED.md "
          f"(v{cat.get('version', '?')}, {len(intents)} intents) -- aucune ecriture")
else:
    open(RULES, "wb").write(_sortie)
    print(f"OK: section M2M {action} dans RULES_SHARED.md (v{cat.get('version', '?')}, {len(intents)} intents)")
