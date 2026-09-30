"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_batch_forge_intent_parser
#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = (
    "#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
)

"""
app/forge_intent_parser.py
AUTONOMOUS_ORCHESTRATOR_V17 - Step 1 Intent Extraction
"""

import re, sys, json, asyncio, logging, unicodedata
from pathlib import Path
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"

ACTION_VERBS = [
    "creer",
    "create",
    "generer",
    "generate",
    "construire",
    "build",
    "analyser",
    "analyze",
    "auditer",
    "audit",
    "tester",
    "test",
    "deployer",
    "deploy",
    "committer",
    "commit",
    "pousser",
    "push",
    "rechercher",
    "search",
    "indexer",
    "index",
    "optimiser",
    "optimize",
    "refactoriser",
    "refactor",
    "corriger",
    "fix",
    "ecrire",
    "write",
    "executer",
    "execute",
    "run",
    "scanner",
    "scan",
    "verifier",
    "verify",
    "valider",
    "validate",
    "fusionner",
    "merge",
    "comparer",
    "compare",
    "synchroniser",
    "sync",
]

TECH_ENTITIES = [
    "python",
    "github",
    "git",
    "docker",
    "api",
    "json",
    "sql",
    "db",
    "rag",
    "llm",
    "ollama",
    "llamacpp",
    "gemini",
    "claude",
    "groq",
    "pyside6",
    "qt",
    "mcp",
    "hub",
    "mmap",
    "ring",
    "pipeline",
    "workflow",
    "agent",
    "swarm",
    "debate",
    "consensus",
    "test",
    "pytest",
    "ci",
    "cd",
    "lint",
    "ast",
    "fastapi",
    "http",
    "websocket",
    "ssh",
    "embeddings",
    "bge",
    "onnx",
    "npu",
    "vram",
    "gpu",
]

SCHEMA_KEYWORDS = {
    "ci": ["ci", "commit", "test", "lint", "securite", "audit"],
    "debate": ["debat", "compare", "consensus", "avis"],
    "rag": ["rag", "recherche", "document", "index"],
    "workflow": ["tache", "task", "pipeline", "workflow"],
}

# --------------------------------------------------------------------------
# Reconnaissance des verbes — quatre defauts mesures le 2026-09-12 par execution
# reelle (`sandbox/mesure_am1_multi_intention.py`). Sur trois instructions de la
# forme que l'owner emploie vraiment, DEUX capturaient zero verbe : `parse` rendait
# alors `action="executer"` / `target="projet"`, ses valeurs par DEFAUT, et
# l'orchestrateur autonome batissait son DAG la-dessus sans que rien ne signale
# que la demande n'avait pas ete comprise. Un UNKNOWN rendu comme une valeur.
#
#   D1 la normalisation `re.sub("[^a-z0-9 -]", " ", t)` remplacait chaque accent
#      par une ESPACE : « verifie » s'ecrivait « v rifie », mot coupe en deux.
#   D2 le lexique ne liste que des INFINITIFS quand l'owner ecrit a l'IMPERATIF,
#      et le test etait `v in norm` : un infinitif n'est jamais contenu dans sa
#      propre forme conjuguee. Ce qui passait ne passait que par accident, quand
#      la forme ANGLAISE etait prefixe du mot francais (`refactor` dans
#      « refactorise ») — jamais pour `corriger` dans « corrige ».
#   D3 `[v for v in ACTION_VERBS if v in norm]` itere sur la LISTE : `verbs[0]`
#      rendait le verbe le plus haut du LEXIQUE, pas le premier de la PHRASE.
#      « analyse le rag, refactorise le cache et teste » rendait action="test".
#   D4 la recherche par sous-chaine trouvait `run` dans « brunch ».
#
# Le remede ne touche PAS au lexique (aucun verbe ajoute : ce serait inventer un
# vocabulaire owner qu'on n'a pas mesure). Il corrige la RECONNAISSANCE : accents
# deplies, comparaison sur des MOTS, racine verbale, ordre d'apparition.

_SUFFIXES_VERBAUX = ("iser", "er", "ir", "re")
_RACINE_MIN = 4
# Une terminaison conjuguee est courte (e, es, ent, ons, ez, ed, ing...). Au-dela,
# le mot est autre chose : cette borne est ce qui separe « fixe » de « fixture ».
_QUEUE_MAX = 3


def normaliser(texte: str) -> str:
    """Deplie les accents au lieu de les detruire (D1).

    `unicodedata.normalize("NFD")` separe la lettre de son diacritique ; on retire
    le diacritique et la lettre SURVIT. L'ancienne version remplacait le caractere
    accentue entier par une espace, ce qui coupait le mot en deux.
    """
    plat = unicodedata.normalize("NFD", texte or "")
    plat = "".join(c for c in plat if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 -]", " ", plat.lower())


def racine_verbe(verbe: str) -> str:
    """Radical d'un verbe du lexique, jamais plus court que `_RACINE_MIN`.

    `corriger` -> `corrig` ; `pousser` -> `pouss` ; `creer` -> `cree` (la borne
    empeche `cre`, qui matcherait « credit » et « creve »).
    """
    for suff in _SUFFIXES_VERBAUX:
        if verbe.endswith(suff) and len(verbe) - len(suff) >= _RACINE_MIN:
            return verbe[: -len(suff)]
    return verbe


def _table_racines() -> list[tuple[str, str]]:
    """[(racine, verbe canonique)] du lexique, une seule entree par racine.

    Le lexique porte des doublons FR/EN (`tester`/`test`, `corriger`/`fix`). Deux
    entrees de MEME racine ne doivent produire qu'UNE intention : la premiere du
    lexique fait foi. Des racines differentes restent deux verbes distincts.
    Tri par racine decroissante : la plus specifique est essayee d'abord.
    """
    vues: dict[str, str] = {}
    for v in ACTION_VERBS:
        vues.setdefault(racine_verbe(v), v)
    return sorted(vues.items(), key=lambda kv: -len(kv[0]))


def verbes_ordonnes(norm: str) -> list[str]:
    """Verbes canoniques presents, dans l'ordre d'apparition dans la PHRASE (D3).

    Compare des MOTS, pas des suites de lettres (D4) : un token matche une racine
    s'il lui est egal, ou s'il la prolonge d'au plus `_QUEUE_MAX` caracteres —
    la longueur d'une terminaison conjuguee.
    """
    table = _table_racines()
    trouves: dict[str, int] = {}
    position = 0
    for token in norm.split():
        position += 1
        for racine, canonique in table:
            if token == racine or (
                token.startswith(racine) and len(token) - len(racine) <= _QUEUE_MAX
            ):
                trouves.setdefault(canonique, position)
                break
    return [v for v, _ in sorted(trouves.items(), key=lambda kv: kv[1])]


# 2026-09-12 : `@dataclass` etait empile SIX fois ici (trace probable de l'injecteur
# de headers cite en tete du fichier). L'empilement etait INVISIBLE tant que le
# dernier champ portait un defaut SIMPLE : `dataclass` conserve `confidence = 0.0`
# comme attribut de classe, donc le 2e passage le revoit. Un champ a
# `default_factory` est au contraire RETIRE des attributs de classe au 1er passage ;
# au 2e il parait sans defaut, d'ou `TypeError: non-default argument 'intentions'
# follows default argument 'confidence'` — a l'IMPORT, donc tout le module tombe.
# Le defaut dormait ici depuis l'ecriture du fichier ; ajouter `intentions` l'a
# revele. Un seul decorateur.
@dataclass
class ParsedIntent:
    """Represents a parsed user intent with extracted semantic information.

    Attributes:
        raw: The original raw text input from the user.
        verbs: list of action verbs extracted from the intent.
        entities: list of extracted entities (objects, parameters, etc.).
        target: Primary target of the action (e.g., a file, device, or resource).
        action: Canonical action verb representing the intended operation.
        priority: Priority level of the intent (e.g., "high", "normal", "low").
        schema_hint: Suggested schema type for workflow generation.
        confidence: Confidence score between 0.0 and 1.0 for the parsing result.
    """

    raw: str
    verbs: list[str] = field(default_factory=list)
    entities: list[object] = field(default_factory=list)
    target: str | None = None
    action: str | None = None
    priority: str = "normal"
    schema_hint: str = "workflow"
    confidence: float = 0.0
    # Les intentions de la demande, ORDONNEES par leur position dans la phrase.
    # `verbs` les portait deja, mais la mesure du 2026-09-12 montre qu'il n'etait
    # lu par PERSONNE hors de ce module quand `action` l'etait par deux autres :
    # un champ conserve et jamais consomme est perdu tout autant. `intentions`
    # est le nom que lit un appelant qui cherche « que m'a-t-on demande de faire »,
    # et `action` en est la premiere — jamais une autre.
    intentions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        """Converts the ParsedIntent instance to a dictionary representation.

        Returns:
            A dictionary containing all attributes of the ParsedIntent.
        """
        return {
            "raw": self.raw,
            "verbs": self.verbs,
            "entities": self.entities,
            "target": self.target,
            "action": self.action,
            "priority": self.priority,
            "schema_hint": self.schema_hint,
            "confidence": self.confidence,
            "intentions": self.intentions,
        }


class IntentParser:
    def parse(self, text: str, use_llm: bool = False) -> ParsedIntent:
        """Parse.

        Args:
            text: Description.
            use_llm: Description.
        """
        intent = ParsedIntent(raw=text)
        norm = normaliser(text)
        intent.verbs = verbes_ordonnes(norm)
        intent.intentions = list(intent.verbs)
        intent.action = intent.verbs[0] if intent.verbs else "executer"
        intent.entities = [e for e in TECH_ENTITIES if e in norm]
        intent.target = intent.entities[0] if intent.entities else "projet"
        critical_words = ["urgent", "critique", "bloque", "erreur", "fail"]
        high_words = ["important", "prioritaire", "vite"]
        if any(w in norm for w in critical_words):
            intent.priority = "critical"
        elif any(w in norm for w in high_words):
            intent.priority = "high"
        best_hint = "workflow"
        best_score = 0
        for hint, kws in SCHEMA_KEYWORDS.items():
            score = sum(1 for k in kws if k in norm)
            if score > best_score:
                best_score = score
                best_hint = hint
        intent.schema_hint = best_hint
        intent.confidence = min(1.0, len(intent.verbs) * 0.3 + len(intent.entities) * 0.2 + 0.2)
        if use_llm and intent.confidence < 0.6:
            intent = self._enrich_llm(intent)
        return intent

    def _enrich_llm(self, intent: ParsedIntent) -> ParsedIntent:
        """Enrich llm.

        Args:
            intent: Description.
        """
        try:
            if str(APP) not in sys.path:
                sys.path.insert(0, str(APP))
            from nokido_agent.app.forge_swarm_team import _default_team, LeadOrchestrator

            # Construire le prompt sans f-string multi-ligne
            instruction = intent.raw
            prompt = (
                "Analyse cette instruction, reponds en JSON uniquement:\n"
                "Instruction: " + instruction + "\n"
                'Format: {"verbs":[],"entities":[],"action":"",'
                '"target":"","priority":"normal","schema_hint":"workflow"}'
            )
            team = _default_team()
            team.activate("laforge")
            orc = LeadOrchestrator()
            loop = asyncio.new_event_loop()
            res = loop.run_until_complete(orc.run(prompt, team))
            loop.close()
            turns = res.get("results", [])
            raw = str(turns[0].get("response", "")) if turns else "{}"
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                d = json.loads(raw[start:end])
                intent.verbs = d.get("verbs", intent.verbs)
                intent.entities = d.get("entities", intent.entities)
                intent.action = d.get("action", intent.action)
                intent.target = d.get("target", intent.target)
                intent.priority = d.get("priority", intent.priority)
                intent.schema_hint = d.get("schema_hint", intent.schema_hint)
                intent.confidence = 0.9
        except Exception as e:  # noqa: BLE001
            # 2026-09-12 : ce chemin etait MUET (signale 74x depuis mai par le gate
            # recidive). Un appelant qui passe `use_llm=True` obtient alors le
            # resultat REGEX en croyant tenir un intent enrichi : l'echec de
            # l'enrichissement est indiscernable d'un enrichissement qui n'avait
            # rien a ajouter. Trois etats confondus en un, dans la fonction meme
            # qui sert a lever un doute.
            logger.warning(
                "[intent] enrichissement LLM indisponible (%s: %s) — intent rendu "
                "tel quel par le NLU regex | consequence: `use_llm=True` n'a eu "
                "AUCUN effet et rien ne le disait", type(e).__name__, str(e)[:80])
        return intent


_parser = IntentParser()


# Context:


def parse_intent(text: str, use_llm: bool = False) -> ParsedIntent:
    """Parse l'intention  partir du texte donn.

    Args:
        text (str): Le texte  analyser pour en extraire l'intention.
        use_llm (bool, optional): Indique si l'analyse doit utiliser un modle de langage (LLM).
            Par dfaut False.

    Returns:
        ParsedIntent: L'objet contenant l'intention parse et les informations associes.

    Raises:
        ValueError: Si le texte d'entre est vide ou invalide.
        ParsingError: Si l'analyse choue pour une raison quelconque.
    """
    return _parser.parse(text, use_llm)
