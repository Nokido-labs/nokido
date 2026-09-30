#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""app/forge_self_mutation.py — boucle d'auto-amelioration, remise en service.

HISTOIRE. `LocalMutationManager.py` (LOCAL_SAFE_MUTATION_V1 — Headless
Self-Improvement) et `ParallelMutationWorker.py` ont ete perdus le 2026-03-26
par `chore: clean hackathon branch — remove 651 non-essential files`. Ils
n'ont pas ete abandonnes : ils ont ete balayes. Le census Phase 7 les a
retrouves (140 et 54 reprises), `forge_capability_recovery` les a remontes.

CE QUI EST CONSERVE de la version de mars : le validateur. Ses regles ne font
pas doublon avec les gardes actuels — `governed_write` verifie la syntaxe et
les secrets, il ne detecte NI la troncation, NI les fonctions inventees, NI la
derive semantique. C'est exactement ce qu'un LLM rate en refactorant.

CE QUI CHANGE : plus rien n'ecrit ni n'appelle en direct.
  - ecriture  -> `governed_write` (AST + secrets + fichiers critiques + locks)
  - LLM       -> injectable, defaut `forge_llm_router.router_call` (local d'abord)
  - portee    -> `fichier_protege` interdit de reecrire ce qui surveille, et
                 le module lui-meme
  - defaut    -> dry_run : rien n'est applique sans demande explicite

REGLE DE SURETE. Une regle que le garde n'a pas pu executer est DECLAREE
NON_EXECUTEE dans `rapport`, jamais silencieuse : un garde vert sans mesure
vaut un garde absent.
"""
from __future__ import annotations

import ast
import asyncio
import difflib
import inspect
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Ce que le systeme ne doit jamais se donner le droit de reecrire.
PROTEGES = (
    "bash_guard", "hook_", "guard", "firewall", "laforge_hub", "hub_",
    "governed_edit", "rbac", "mcp_security", "self_mutation", "trust_score",
    "semantic_firewall", "capability_gate",
)

SEUIL_TRONCATION = 0.80      # perdre plus de 20 % des lignes = troncation
SEUIL_CROISSANCE = 1.20      # gagner plus de 20 % = derive, pas un refactor
SEUIL_SIMILARITE = 0.60      # sous ce cosinus, le sens a change


def fichier_protege(chemin: str) -> bool:
    """Vrai si ce fichier surveille le systeme (ou est cette boucle elle-meme)."""
    base = os.path.basename(chemin.replace("\\", "/")).lower()
    return any(motif in base for motif in PROTEGES)


def _cosinus(a, b) -> float:
    num = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return 0.0 if not na or not nb else num / (na * nb)


def _fonctions(arbre):
    return {n.name: n for n in ast.walk(arbre)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _classes(arbre):
    return {n.name: n for n in ast.walk(arbre) if isinstance(n, ast.ClassDef)}


class MutationGuard:
    """Valide une mutation proposee par un LLM. Refuse par defaut.

    `rapport` liste chaque regle avec son etat : PASS, REJET ou NON_EXECUTEE.
    """

    def __init__(self, embedder=None, autoriser_nouvelles_definitions: bool = False):
        self.embedder = embedder
        self.autoriser_nouvelles = autoriser_nouvelles_definitions
        self.rapport: list = []

    def _note(self, regle: str, etat: str, detail: str = "") -> None:
        self.rapport.append({"regle": regle, "etat": etat, "detail": detail})

    def _rejet(self, regle: str, motif: str):
        self._note(regle, "REJET", motif)
        return False, motif

    def valider(self, original: str, mute: str):
        """-> (accepte, motif). Toute regle non executee reste visible."""
        self.rapport = []

        try:
            vieux = ast.parse(original)
            neuf = ast.parse(mute)
        except SyntaxError as exc:
            return self._rejet("syntaxe", "REJET: syntaxe cassee: %s" % exc)
        self._note("syntaxe", "PASS")

        cls_vieux, cls_neuf = _classes(vieux), _classes(neuf)
        perdues = set(cls_vieux) - set(cls_neuf)
        if perdues:
            return self._rejet("classes_perdues",
                               "REJET: classes disparues: %s" % ", ".join(sorted(perdues)))
        self._note("classes_perdues", "PASS")

        n_vieux = len(original.splitlines())
        n_neuf = len(mute.splitlines())
        if n_vieux and n_neuf < n_vieux * SEUIL_TRONCATION:
            return self._rejet(
                "troncation",
                "REJET: troncation %sL -> %sL (perte %s%%)"
                % (n_vieux, n_neuf, 100 - n_neuf * 100 // n_vieux))
        self._note("troncation", "PASS")

        for nom, noeud in cls_vieux.items():
            if len(noeud.body) <= 1:
                continue
            cible = cls_neuf.get(nom)
            if cible is None:
                continue
            methodes = [n for n in ast.walk(cible)
                        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            if not methodes and len(cible.body) <= 1:
                return self._rejet("classe_videe",
                                   "REJET: classe %s redefinie vide" % nom)
        self._note("classe_videe", "PASS")

        fn_vieux, fn_neuf = _fonctions(vieux), _fonctions(neuf)
        if not self.autoriser_nouvelles:
            inventees = set(fn_neuf) - set(fn_vieux)
            if inventees:
                return self._rejet(
                    "fonctions_inventees",
                    "REJET: fonctions inventees: %s" % ", ".join(sorted(inventees)))
        self._note("fonctions_inventees", "PASS")

        croissance = len(mute) / max(1, len(original))
        if croissance > SEUIL_CROISSANCE:
            return self._rejet(
                "croissance",
                "REJET: croissance suspecte +%d%%" % round((croissance - 1) * 100))
        self._note("croissance", "PASS")

        imports = [l.strip() for l in mute.splitlines()
                   if l.strip().startswith(("import ", "from "))]
        if len(imports) != len(set(imports)):
            doublons = sorted({i for i in imports if imports.count(i) > 1})
            return self._rejet("imports_dupliques",
                               "REJET: imports dupliques: %s" % ", ".join(doublons[:3]))
        self._note("imports_dupliques", "PASS")

        for nom, noeud in fn_neuf.items():
            ancien = fn_vieux.get(nom)
            if ancien is None:
                continue
            if ast.get_docstring(ancien) and not ast.get_docstring(noeud):
                return self._rejet("docstring_perdue",
                                   "REJET: docstring perdue dans %s()" % nom)
        self._note("docstring_perdue", "PASS")

        for nom, noeud in fn_neuf.items():
            ancien = fn_vieux.get(nom)
            if ancien is None:
                continue
            annotes = {a.arg for a in ancien.args.args if a.annotation is not None}
            manquants = [a.arg for a in noeud.args.args
                         if a.arg in annotes and a.annotation is None]
            if manquants:
                return self._rejet(
                    "type_hints",
                    "REJET: type hints perdus dans %s(): %s" % (nom, ", ".join(manquants)))
        self._note("type_hints", "PASS")

        # Derive semantique : la seule regle qui juge le SENS, pas la forme.
        if self.embedder is None or not getattr(self.embedder, "available", False):
            self._note("derive_semantique", "NON_EXECUTEE",
                       "embedder indisponible (politique RAM : OFF au boot)")
        else:
            try:
                vecteurs = self.embedder.encode([original, mute])
                sim = _cosinus(vecteurs[0], vecteurs[1])
            except Exception as exc:  # l'embedder est optionnel, jamais bloquant
                self._note("derive_semantique", "NON_EXECUTEE", "echec: %s" % exc)
            else:
                if sim < SEUIL_SIMILARITE:
                    return self._rejet(
                        "derive_semantique",
                        "REJET: derive semantique (%.2f < %.2f)" % (sim, SEUIL_SIMILARITE))
                self._note("derive_semantique", "PASS", "similarite %.2f" % sim)

        return True, "VALIDE"

    def diff(self, original: str, mute: str) -> str:
        return "".join(difflib.unified_diff(
            original.splitlines(keepends=True), mute.splitlines(keepends=True),
            fromfile="avant", tofile="apres"))


CLES_TEXTE = ("text", "content", "response", "output", "message")
MODELE_CODE = os.environ.get("NOKIDO_CODE_MODEL", "qwen2.5-coder:7b-instruct-q4_K_M")


def _texte(reponse) -> str:
    if isinstance(reponse, str):
        return reponse
    if isinstance(reponse, dict):
        for cle in CLES_TEXTE:
            valeur = reponse.get(cle)
            if isinstance(valeur, str) and valeur.strip():
                return valeur
    raise RuntimeError("reponse sans texte exploitable : %s"
                       % (sorted(reponse.keys()) if isinstance(reponse, dict) else type(reponse)))


def _appel_llm_defaut(prompt: str) -> str:
    """LOCAL impose, avec chargement a froid assume en dernier ressort.

    `router_call` passe par la chaine `general`, cloud-first : muter du code
    local n'a pas a sortir de la machine. `call_cascade` accepte `force_local`,
    mais il exclut tout slot local sans modele RESIDENT -- politique anti-wedge
    justifiee pour un appel interactif. Or l'hote tourne en
    `OLLAMA_MAX_LOADED_MODELS=1` avec `OLLAMA_KEEP_ALIVE=30s` : l'embedder du
    RAG evince en continu tout modele generatif, donc AUCUN slot local n'est
    jamais eligible. La cascade seule ne peut pas aboutir ici.

    Une mutation est une tache DEPORTEE : quinze secondes de chargement y sont
    acceptables. On tente donc la cascade, puis on appelle le backend souverain
    en direct plutot que de sortir vers le cloud.
    """
    from nokido_agent.app.forge_llm_router import get_router
    reponse = get_router().call_cascade(
        prompt, use_case="code_mutation", max_tokens=4000,
        force_local=True, timeout=180)
    if isinstance(reponse, dict) and reponse.get("ok"):
        return _texte(reponse)

    motif = reponse.get("error") if isinstance(reponse, dict) else "reponse inattendue"
    print("[mutation] cascade locale indisponible (%s) -> appel direct, "
          "chargement a froid assume" % motif)
    from nokido_agent.app.forge_ollama import ollama_call
    sortie = ollama_call(MODELE_CODE, [{"role": "user", "content": prompt}],
                         max_tokens=4000)
    if inspect.isawaitable(sortie):
        # ollama_call est une coroutine ; le cycle tourne dans un thread sans
        # boucle d'evenements, asyncio.run y est donc legitime.
        sortie = asyncio.run(sortie)
    return _texte(sortie)


def _code_seul(reponse: str) -> str:
    """Extrait le code d'une reponse LLM (bloc markdown ou texte nu)."""
    bloc = re.search(r"```(?:python)?\n(.*?)```", reponse, re.S)
    return (bloc.group(1) if bloc else reponse).strip() + "\n"


class MutationCycle:
    """Un cycle : lire -> proposer -> valider -> tester -> (appliquer)."""

    def __init__(self, appel_llm=None, guard=None, agent: str = "SELF_MUTATION"):
        self.appel_llm = appel_llm or _appel_llm_defaut
        self.guard = guard or MutationGuard()
        self.agent = agent

    def run_cycle(self, cible: str, tache: str, dry_run: bool = True) -> dict:
        """dry_run=True par defaut : rien n'est ecrit sans demande explicite."""
        if fichier_protege(cible):
            return {"ok": False, "etape": "portee",
                    "motif": "%s surveille le systeme : mutation interdite" % cible}

        chemin = cible if os.path.isabs(cible) else os.path.join(ROOT, cible)
        if not os.path.isfile(chemin):
            return {"ok": False, "etape": "lecture", "motif": "%s introuvable" % cible}
        original = open(chemin, encoding="utf-8").read()

        prompt = ("Ameliore ce module Python. Tache : %s\n"
                  "Contraintes ABSOLUES : conserve toutes les classes et fonctions "
                  "existantes, leurs docstrings et leurs annotations de type ; "
                  "n'invente aucune fonction ; ne raccourcis rien.\n\n"
                  "```python\n%s```\n" % (tache, original))
        try:
            mute = _code_seul(self.appel_llm(prompt))
        except Exception as exc:
            return {"ok": False, "etape": "llm", "motif": "appel LLM echoue: %s" % exc}

        accepte, motif = self.guard.valider(original, mute)
        resultat = {"cible": cible, "tache": tache, "rapport": self.guard.rapport,
                    "motif": motif, "diff": self.guard.diff(original, mute)}
        if not accepte:
            resultat.update({"ok": False, "etape": "garde"})
            return resultat

        if dry_run:
            resultat.update({"ok": True, "etape": "dry_run", "applique": False})
            return resultat

        # Chemin FERME et MESURE (Codex 2026-08-27) : APPLIQUER NE SUFFIT PAS. On route
        # par le juge a GAIN -- une mutation n'est CONSERVEE que si elle SURVIT (tests)
        # ET AMELIORE (gain vs baseline) ; sinon revert git HEAD, tests verts ou non.
        # Pas de test cible => GAIN_INDECIDABLE => NON gardee. L'absence de mesure est
        # un REFUS, pas un passe-droit -- et depuis le 2026-09-08 elle porte enfin son
        # nom : le juge ne la confond plus avec un gain NUL (« NEUTRE »), ce qui aurait
        # envoye chercher un meilleur patch la ou il manque un TEST.
        # L'applicateur AUTONOME reste desarme : ce chemin ne s'emprunte que sur
        # dry_run=False explicite (humain / agent mandate).
        rel = os.path.relpath(chemin, ROOT).replace("\\", "/")
        from nokido_agent.app.forge_mutation_judge import juger_module_avec_gain, perimetre_mesure

        # Perimetre de mesure PARTAGE (extrait d'ici le 2026-09-08) : les quatre
        # conventions vivaient en ligne a cet endroit, donc `forge_autonomous_loops`
        # ne pouvait pas s'en servir et empruntait le chemin SANS gain.
        tests = perimetre_mesure(rel)
        jr = juger_module_avec_gain(rel, mute, tests)
        garde = jr.get("verdict") == "AMELIORE"
        resultat.update({"ok": garde, "etape": "juge_gain", "applique": garde,
                         "verdict_juge": jr.get("verdict"), "gain": jr.get("gain"),
                         "tests_cibles": tests, "note": jr.get("note")})
        return resultat
