"""Charge les personas YAML de config/personas et assemble le system prompt d'une persona.

Entrées : PersonaEngine (get_persona, build_system_prompt, route_intent,
generate_probe_query, route_by_probe), le singleton get_persona_engine() et
nokido_system(), qui rend la voix canonique (persona canonical, alias laforge/nokido).
Le prompt ajoute des exemples domain=dialogue_win lus dans rag_chunks
(RAG/embeddings.db, lecture seule, chemins hôte masqués par _scrub_host_paths) et des
directives selon les hormones CORTISOL_QUOTA_CLOUD, DOPAMINE_SUCCESS et
CORTISOL_FRUSTRATION (forge_endocrine). Signature TPM si FORGE_PERSONA_SIGN=1.
Utilisé par forge_llm_router, forge_agent_proxy, forge_agents, forge_metier_dispatch.
"""
import yaml
import os
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)


class PersonaEngine:
    def __init__(self, config_dir=None):
        # Défaut module-relatif (robuste, plus de chemin user hardcodé)
        if config_dir is None:
            config_dir = Path(__file__).resolve().parent.parent / "config" / "personas"
        self.config_dir = Path(config_dir)
        self.personas = {}
        self.load_all()

    def load_all(self):
        for f in self.config_dir.glob("*.yaml"):
            with open(f, "r", encoding="utf-8") as stream:
                config = yaml.safe_load(stream)
                self.personas[config["name"]] = config
                # Rename LaForge->Nokido a moitie : le yaml canonique declare
                # name="nokido" mais tout le code appelle get_persona("laforge")
                # (defaut historique) -> None -> fallback string generique, la
                # persona riche AXE 8 ne se chargeait JAMAIS (audit ZCode 2026-07-23).
                # On alias la persona canonique sous les deux cles = les appels
                # existants "laforge" ET "nokido" resolvent vers la vraie voix.
                if config.get("canonical"):
                    self.personas.setdefault("laforge", config)
                    self.personas.setdefault("nokido", config)

    def get_persona(self, name):
        return self.personas.get(name)

    def route_intent(self, task_description):
        """
        Analyse simplifiée de l'intention pour choisir le modèle.
        """
        complex_keywords = ["analyse", "architecture", "refactor", "complexe", "pourquoi", "audit", "plan"]
        is_complex = any(k in task_description.lower() for k in complex_keywords)

        if is_complex:
            return "gemini-3.1-pro-preview"
        return "gemini-2.5-flash-lite"

    def generate_probe_query(self, task):
        """
        Génère une question pour tester si le modèle se sent capable.
        """
        return f"Concernant la tâche : '{task}', identifie tes limitations techniques réelles dans l'environnement Nokido. Peux-tu utiliser run_shell_command ou icacls si nécessaire ? Réponds par CAPABLE ou LIMITED suivi d'une courte raison."

    def route_by_probe(self, probe_response):
        """
        Analyse la réponse à la sonde pour décider de l'escalade.
        """
        if "LIMITED" in probe_response.upper() or "NE PEUX PAS" in probe_response.upper():
            return "gemini-3.1-pro-preview"  # Escalade
        return "gemini-2.5-flash-lite"  # Exécution économique

    def _pull_dialogue_exemplars(self, max_lessons=2):
        """AXE ÉCRIT : pull les échanges RÉUSSIS récents (domain=dialogue_win,
        persistés par forge_dialogue_outcome.score_session_turns) comme exemplars
        few-shot écrits. Skippé sous pression coût (éco-tokens = trait persona).
        Best-effort, ne crashe jamais."""
        try:
            if _read_cost_pressure() >= TOKEN_PRESSURE_THRESHOLD:
                return ""  # budget serré : pas de few-shot
            import sqlite3
            from pathlib import Path

            db = Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db"
            con = sqlite3.connect(str(db), timeout=5)
            rows = con.execute(
                "SELECT text FROM rag_chunks WHERE domain='dialogue_win' "
                "ORDER BY ingested_at DESC LIMIT ?",
                (int(max_lessons),),
            ).fetchall()
            con.close()
            if not rows:
                return ""
            ex = "\n".join("- " + (r[0] or "")[:280].replace("\n", " ") for r in rows)
            return f"\nEXEMPLES D'ÉCHANGES RÉUSSIS (style écrit à imiter) :\n{ex}\n"
        except Exception:
            return ""

    def _token_budget_directive(self):
        """Gestion intelligente des tokens — volet DYNAMIQUE de la persona.

        Lit la pression coût cloud (hormone CORTISOL_QUOTA_CLOUD, 0-1) émise par
        forge_token_monitor. Sous pression → injecte une directive d'économie
        (caveman, local-first, déport). Best-effort, jamais bloquant."""
        try:
            pressure = _read_cost_pressure()
        except Exception:
            pressure = 0.0
        if pressure >= TOKEN_PRESSURE_THRESHOLD:
            return (
                f"\n[BUDGET TOKENS SOUS PRESSION ({pressure:.0%})] Mode économie strict : "
                "réponses caveman/concises, local-first (Ollama), déporte les tâches longues "
                "(1 job détaché), lecture fenêtrée jamais brute, pas de relecture inutile.\n"
            )
        return ""

    def _mood_directive(self):
        """Conditionnement de la VOIX par l'issue succès/échec du dialogue (AXE 8).

        Lit l'état endocrinien (DOPAMINE_SUCCESS / CORTISOL_FRUSTRATION) alimenté par
        forge_dialogue_outcome.record_outcome → forge_motivation. Succès récents →
        voix assurée ; échecs récents → prudence + exploration. Best-effort."""
        try:
            dopa, cort = _read_mood()
        except Exception:
            dopa, cort = 0.0, 0.0
        if cort >= MOOD_THRESHOLD and cort >= dopa:
            return (
                f"\n[ÉTAT: FRUSTRATION ({cort:.0%})] Échecs récents sur ce type d'échange. "
                "Sois prudent : clarifie avant d'agir, vérifie tes hypothèses, "
                "envisage une approche différente plutôt que répéter.\n"
            )
        if dopa >= MOOD_THRESHOLD and dopa > cort:
            return (
                f"\n[ÉTAT: CONFIANCE ({dopa:.0%})] Approche récemment fructueuse. "
                "Reste direct et concis, capitalise sur ce qui marche.\n"
            )
        return ""

    def build_system_prompt(
        self,
        persona_name="laforge",
        *,
        ring=1,
        turn=0,
        session_id="",
        role_overlay="",
        pull_lessons=True,
        max_lessons=3,
    ):
        """Construit le system prompt d'une persona.

        AXE 8 — la persona « nokido » (canonical: true) est la VOIX du système :
        elle est préfixée du marqueur idempotent [LAFORGE_PERSONA], englobe le
        `role_overlay` (rôle spécialisé APRÈS la voix), et reçoit l'identity_anchor
        en FIN (recency bias, gate turn>=3). Persona inconnue → fallback nokido.
        """
        # RETIREE le 2026-09-26 (accord owner) : une « INSTRUCTION DE SECOURS » ajoutee a CHAQUE
        # system prompt ordonnait « En cas de PermissionError ou de blocage, utilise icacls ou
        # nssm restart immediatement ». Elle partait avec toute persona -- vers le cloud compris --
        # et poussait n'importe quel modele a modifier des ACL ou relancer un service, deux gestes
        # que la doctrine reserve a l'owner (« Confirmer l'irreversible »). Un blocage se DIT.

        p = self.get_persona(persona_name)
        if not p:
            # Fallback vers la persona canonique si dispo, sinon agent générique.
            if persona_name != "laforge" and self.get_persona("laforge"):
                return self.build_system_prompt(
                    "laforge",
                    ring=ring,
                    turn=turn,
                    session_id=session_id,
                    role_overlay=role_overlay,
                    pull_lessons=pull_lessons,
                    max_lessons=max_lessons,
                )
            return "Tu es un agent Nokido."

        head = "[LAFORGE_PERSONA]\n" if p.get("canonical") else ""
        prompt = head + f"Tu es {p['name']}, un {p['role']}.\n"
        prompt += f"STYLE: {p['style']}.\n"
        prompt += f"CONTRAINTES: {', '.join(p.get('constraints', []))}.\n"
        prompt += f"CAPACITÉS: {', '.join(p.get('capabilities', []))}.\n"
        if p.get("values"):
            prompt += f"VALEURS: {p['values']}.\n"

        if role_overlay:
            prompt += f"\nRÔLE SPÉCIALISÉ:\n{role_overlay}\n"

        if pull_lessons:
            try:
                exemplars = self._pull_dialogue_exemplars(max_lessons)
                if exemplars:
                    # Redaction OBLIGATOIRE avant injection : les lecons sont
                    # ecrites par anchor_solution() avec des exemples de commande,
                    # donc truffees de chemins absolus de la machine hote. Injectees
                    # telles quelles, elles faisaient echouer le DLP de
                    # forge_semantic_firewall.pre_flight() sur le PROMPT SYSTEME —
                    # et comme _ensure_persona est inbypassable, c'etait TOUT
                    # l'egress cloud de Nokido qui tombait, pour tous les agents et
                    # quel que soit le message (diagnostic 2026-08-11).
                    prompt += _scrub_host_paths(exemplars)
            except Exception:
                pass

        # Gestion intelligente des tokens — directive dynamique selon pression budget.
        prompt += self._token_budget_directive()

        # Conditionnement voix par succès/échec du dialogue (état endocrinien).
        prompt += self._mood_directive()

        # (plus d'instruction de secours : voir le commentaire en tete de la fonction)

        # Identity anchor en FIN (recency bias, gate turn>=3 géré dans la fonction).
        try:
            from nokido_agent.app.forge_prompt_guard import identity_anchor

            prompt += identity_anchor(role=p["name"], ring=ring, turn=turn, session_id=session_id)
        except Exception:
            pass

        # Racine de confiance matérielle (AXE 8 PR-6) — preuve d'origine TPM-signée
        # de l'identité. Opt-in (FORGE_PERSONA_SIGN=1) pour éviter la latence TPM
        # par construction. Fallback HMAC. Best-effort.
        if turn >= 3 and os.environ.get("FORGE_PERSONA_SIGN") == "1":
            try:
                from nokido_agent.app.forge_persona_tpm import sign_identity

                prompt += f"\n[ANCHOR_SIG:{sign_identity(prompt)}]\n"
            except Exception:
                pass

        return prompt


# ─────────────────────────────────────────────────────────────────────────────
# Singleton + helper unique (point d'entrée tous clients — AXE 8)
# ─────────────────────────────────────────────────────────────────────────────

_ENGINE_SINGLETON = None

# Seuil de pression coût cloud au-delà duquel la persona bascule en économie stricte.
TOKEN_PRESSURE_THRESHOLD = 0.5

# Seuil d'humeur (dopamine/cortisol) au-delà duquel la voix est modulée.
MOOD_THRESHOLD = 0.4


def _read_mood():
    """Lit (DOPAMINE_SUCCESS, CORTISOL_FRUSTRATION) — état succès/échec du dialogue.
    Alimenté par forge_dialogue_outcome → forge_motivation. (0.0, 0.0) si indispo."""
    try:
        from nokido_agent.app.forge_endocrine import read

        return float(read("DOPAMINE_SUCCESS")), float(read("CORTISOL_FRUSTRATION"))
    except Exception:
        return 0.0, 0.0


def _read_cost_pressure():
    """Lit l'hormone CORTISOL_QUOTA_CLOUD (pression coût cloud 0-1, decay demi-vie).
    Émise par forge_token_monitor quand cost_usd_today/daily_budget > 0.8.
    Retourne 0.0 si endocrine indispo (best-effort)."""
    try:
        from nokido_agent.app.forge_endocrine import read

        return float(read("CORTISOL_QUOTA_CLOUD"))
    except Exception:
        return 0.0


def get_persona_engine():
    """Retourne le singleton PersonaEngine (comme get_firewall)."""
    global _ENGINE_SINGLETON
    if _ENGINE_SINGLETON is None:
        _ENGINE_SINGLETON = PersonaEngine()
    return _ENGINE_SINGLETON


def _scrub_host_paths(text: str) -> str:
    """Remplace les chemins absolus de la machine hote par un marqueur, en
    conservant le nom de fichier (seule partie porteuse de sens pour la lecon).

    Pourquoi ici et pas ailleurs :
    - a l'ECRITURE (anchor_solution) ne reparerait pas les lecons deja en base ;
    - dans le pare-feu, la detection sur le prompt systeme est FATALE et non
      redactible : `_firewall_pre` ne rattrape que le message (safe_task), jamais
      le contexte. C'est cette asymetrie qui rendait le blocage definitif.

    L'arborescence de l'hote n'apporte rien a un modele distant : elle ne sert
    qu'a l'execution locale, ou le chemin reel est de toute facon reconstruit.
    """
    import re

    pattern = r"(?:[A-Za-z]:[\\/]|/(?:home|Users)/)[^\s\"'`,;)\]}]*"

    def _repl(m):
        leaf = re.split(r"[\\/]", m.group(0))[-1]
        return f"<chemin local: {leaf}>" if leaf else "<chemin local>"

    return re.sub(pattern, _repl, text or "")


def nokido_system(role_overlay="", *, ring=1, turn=0, session_id="", pull_lessons=True):
    """Voix canonique Nokido prête à injecter. Point d'entrée unique pour
    forge_llm_router / forge_agent_proxy / forge_agents (PR-3/4)."""
    return get_persona_engine().build_system_prompt(
        "laforge",
        role_overlay=role_overlay,
        ring=ring,
        turn=turn,
        session_id=session_id,
        pull_lessons=pull_lessons,
    )


if __name__ == "__main__":
    engine = PersonaEngine()
    print("--- TEST DE SONDE ---")
    probe = engine.generate_probe_query("Modifier les permissions du dossier logs")
    print(f"Sonde envoyée au modèle : {probe}")
    # Simulation d'une réponse de modèle faible
    sim_response = "LIMITED: En tant qu'IA, je ne peux pas modifier les fichiers système."
    model = engine.route_by_probe(sim_response)
    print(f"Décision du Router après sonde : {model}")
