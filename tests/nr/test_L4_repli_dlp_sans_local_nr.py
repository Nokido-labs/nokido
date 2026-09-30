"""Non-regression L4 : un secret ne part jamais au cloud EN CLAIR, meme sans local.

Item de veille L4 (`google/adk-python`, live callbacks / Model Armor) : « inspecter
ET bloquer le contenu sur une session vivante ; filtrage entree ET sortie ».
Justification inscrite : « la membrane semantique est cablee dans 1 provider sur 39 ».

⚠️ CE CHIFFRE ETAIT FAUX, ET LA QUESTION MAL POSEE.
Registre canonique lu le 2026-09-12 (`forge_llm_router.PROVIDERS`) : **33 declares,
7 perimes, 26 ACTIFS** — ni 39, ni les 86 qu'une heuristique de nom de fichier
m'avait d'abord rendus. Et surtout, les providers n'ont pas a filtrer un par un :
le ROUTEUR est leur point de passage commun. La couverture par provider n'est donc
pas la bonne unite de mesure.

LE DEFAUT REEL, mesure sur le code du routeur :

    if not pf.ok or pf.dlp_triggered:
        local_only = [s for s in chain if s in ("ollama_local", "llamacpp_local")]
        if local_only:
            chain = local_only
        # <- et SINON, rien. `chain` reste CLOUD.

Un prompt dont le DLP vient de mordre partait au cloud EN CLAIR quand aucun slot
local n'etait dans la chaine, sans une ligne de journal. Ce n'est pas un cas rare :
les backends locaux sont mesures hors service (`:11434` LISTEN mais `/api/tags`
expire, `:8091` / `:8099` / `:1234` fermes). C'est le cas NOMINAL.

🪤 LE PIEGE QUI A FAILLI ME FAIRE EMPIRER LES CHOSES. Le protocole documente
(`CLAUDE.md` §5) affirmait : « safe_task et safe_context sont rediges (PII
remplacees par placeholders) ». **FAUX.** Mesure :

    prompt anodin          -> ok=True   dlp=False  safe_task = l'original
    IP / email / chemin    -> ok=False  dlp=True   safe_task = "" (VIDE)

`pre_flight` est un garde BINAIRE, pas un redacteur. Cabler `llm_call(pf.safe_task)`
comme la doc l'indiquait aurait envoye un PROMPT VIDE au modele a chaque detection,
silencieusement. La doc a ete corrigee dans le meme commit.

Le redacteur reel est `redact_text`, qui substitue vraiment — c'est lui qu'on
emploie en repli. Rediger DEGRADE la requete ; l'envoyer en clair PERD le secret.

Ecrit apres le correctif pour empecher son retour.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent.parent
for _d in (RACINE, RACINE / "app", RACINE / "tools"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

ROUTEUR = RACINE / "app" / "forge_llm_router.py"


def _bloc_firewall() -> str:
    """Le bloc du routeur qui consulte le firewall, extrait par AST."""
    src = ROUTEUR.read_text(encoding="utf-8", errors="replace")
    arbre = ast.parse(src)
    for n in ast.walk(arbre):
        if not isinstance(n, ast.Call):
            continue
        fn = getattr(n.func, "attr", None)
        if fn != "pre_flight":
            continue
        # remonte au bloc englobant
        for p in ast.walk(arbre):
            if isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if n.lineno >= p.lineno and n.lineno <= (p.end_lineno or p.lineno):
                    return ast.unparse(p)
    raise AssertionError("aucun appel a pre_flight dans le routeur — le filtrage "
                         "d'entree a disparu")


def test_le_routeur_consulte_toujours_le_firewall_en_entree():
    assert "pre_flight" in _bloc_firewall()


def test_le_DLP_sans_slot_local_ne_laisse_plus_partir_le_prompt_en_clair():
    """Le coeur. Sans branche `else`, un prompt sensible partait au cloud intact
    des qu'aucun backend local n'etait disponible — c'est-a-dire, en pratique,
    presque toujours."""
    bloc = _bloc_firewall()
    assert "redact_text" in bloc, (
        "le routeur n'a AUCUN repli quand le DLP mord et qu'aucun slot local "
        "n'est disponible : le prompt part au cloud en clair. Les backends locaux "
        "etant mesures hors service, c'est le cas nominal."
    )


def test_le_repli_n_est_pas_muet():
    """Un envoi cloud degrade doit laisser une trace : sans elle, il est
    indiscernable d'un envoi protege.

    ⚠️ CE TEST A VERROUILLE LE DEFAUT QU'IL CROYAIT EMPECHER (mesure 2026-09-12,
    trouvee par le cliquet golden-rules en CI de reference). Il exigeait le
    litteral `logger.warning` / `logger.error` — or ce module n'a PAS de `logger`
    global (il utilise `_lg` local). Les trois appels ecrits avec `logger`
    levaient donc un NameError au moment precis ou le garde devait dire qu'une
    donnee sensible partait au cloud non protegee, et le `except ImportError`
    englobant ne rattrape pas un NameError : le garde ne se taisait pas, il
    CASSAIT l'appel. Mon test, lui, etait VERT — il validait le nom du journal,
    c'est-a-dire exactement le bug.

    On teste donc l'EFFET, en deux temps : un appel de journalisation existe, et
    le nom qu'il porte est REELLEMENT LIE. Le second point n'est pas re-implemente
    ici : on emprunte le garde du depot (`forge_golden_rules_ast`), qui sait deja
    le mesurer — un NR qui refait son propre matcher refait aussi ses angles morts.
    """
    bloc = _bloc_firewall()
    assert ".warning(" in bloc or ".error(" in bloc, (
        "le repli DLP ne journalise rien — un prompt redige et un prompt en clair "
        "produiraient la meme trace, c'est-a-dire aucune"
    )

    import forge_golden_rules_ast as _golden  # type: ignore

    violations = [
        v for v in _golden.scan_file(str(RACINE / "app" / "forge_llm_router.py"))
        if v.get("rule") == "laforge-chemin-erreur-nom-non-lie"
    ]
    assert not violations, (
        "le repli journalise avec un nom qui n'est lie NULLE PART : au lieu de "
        "tracer l'envoi degrade, le handler levera un NameError. %s" % violations
    )


def test_pre_flight_ne_REDIGE_pas_et_on_ne_compte_pas_dessus():
    """Verrouille la mesure qui a corrige la documentation. Si un jour
    `pre_flight` se met a rediger, ce test tombe et il faudra relire le repli —
    pas l'inverse."""
    from forge_semantic_firewall import get_firewall  # type: ignore

    fw = get_firewall()
    pf = fw.pre_flight("le serveur repond sur localhost", context="", ring=3,
                       provider="auto")
    assert pf.dlp_triggered is True, "le DLP ne mord plus sur une IP interne"
    assert not (pf.safe_task or ""), (
        "`safe_task` n'est plus vide quand le DLP mord : `pre_flight` redige "
        "peut-etre desormais — relire le repli du routeur, qui suppose l'inverse"
    )


def test_le_redacteur_reel_substitue_vraiment():
    """Contre-epreuve du porteur choisi pour le repli : lui, il redige."""
    from forge_semantic_firewall import redact_text  # type: ignore

    redige, mapping = redact_text("le serveur repond sur localhost")
    assert mapping, "redact_text n'a rien substitue"
    assert "localhost" not in redige


def test_le_registre_des_providers_reste_la_source_du_denominateur():
    """L'entree de veille annoncait « 1 sur 39 ». Le registre en declare 33 dont
    7 perimes. Un denominateur invente rend tout taux faux — et une heuristique
    de nom de fichier m'en avait rendu 86."""
    from forge_llm_router import PROVIDERS  # type: ignore

    assert len(PROVIDERS) >= 20, f"registre anormalement court : {len(PROVIDERS)}"
    perimes = [n for n, c in PROVIDERS.items() if (c or {}).get("perime")]
    actifs = len(PROVIDERS) - len(perimes)
    assert actifs > 0
    # Le champ `perime` est ce qui distingue declare de disponible : sans lui,
    # tout comptage de couverture surestime le denominateur.
    assert perimes, (
        "aucun provider marque `perime` : soit le registre a change, soit le "
        "champ a disparu — dans les deux cas les taux de couverture bougent"
    )
