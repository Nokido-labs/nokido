"""NR — le protocole M2M valide l'IDENTITE et porte l'INCARNATION.

CE QUE LA MESURE DU 2026-09-20 A ETABLI :

  * `agent_messages` (21 852 lignes) porte `from_agent TEXT, to_agent TEXT` et
    RIEN d'autre : aucune signature, aucun instance_id, aucun nonce.
  * 24 sites distincts font `INSERT INTO agent_messages` -- il n'existe AUCUN
    poseur commun ou brancher une validation.
  * `forge_m2m_protocol.validate(channel, payload)` -- le validateur designe par
    CLAUDE.md -- ne recoit NI expediteur NI destinataire. Il ne PEUT donc pas
    juger l'identite : elle ne lui est pas passee.
  * Consequence mesuree : `agt_agt_gemini` (DOUBLE prefixe `agt_`) a accumule
    25 messages, `ANTIGRAVITY` 11 `pending` vieux de 89 jours pendant que
    `agt_antigravity` etait drainee normalement. >= 48 messages non delivrables.

L'ASYMETRIE QUE CE NR ADRESSE :

    a la PORTE (:8766)   TPM · DPoP (RFC 9449 §6) · bail 30 min · ring · fail-closed
    a l'INTERIEUR (M2M)  une ligne SQL avec un nom en texte libre

Le hub authentifie fort QUI ENTRE, puis un message inter-agents n'est qu'une
etiquette. Une etiquette n'est pas une identite.

DEUX NIVEAUX, VOLONTAIREMENT DISTINGUES (directive owner : « agy autonome n'est
pas pareil qu'agy CLI ») :

    identite LOGIQUE     AGY_CLI, AGY_HEADLESS -- stable, declaree au SSoT
    INCARNATION          instance_id + generation -- CETTE execution-ci

« agy tourne » et « CETTE instance d'agy » sont deux affirmations differentes.
Sans incarnation, deux processus concurrents du meme agent sont indiscernables
dans le journal.

OBSERVER AVANT D'ENFORCER. Le verdict par defaut est un AVERTISSEMENT, jamais un
refus : 24 chemins d'ecriture existent et un gate bloquant d'emblee les casserait
tous. RULES_SHARED : « un gate neuf est non bloquant le temps de mesurer son
bruit ». Le refus n'arrive que si `LAFORGE_M2M_MODE=error` -- le meme
interrupteur que la prose, deja en place.

PORTEE DITE : ce NR ne signe rien (point 3, separe) et ne touche aucun des
24 chemins d'ecriture. Il garde le VALIDATEUR.
"""
from __future__ import annotations

import pytest


def _module():
    for nom in ("nokido_agent.app.forge_m2m_protocol", "app.forge_m2m_protocol",
                "forge_m2m_protocol"):
        try:
            mod = __import__(nom, fromlist=["validate"])
        except Exception:  # noqa: BLE001
            continue
        if hasattr(mod, "validate"):
            return mod
    pytest.skip("forge_m2m_protocol introuvable sous ses trois noms d'import")


# ─────────────────────────────  IDENTITE  ─────────────────────────────

def test_le_validateur_d_identite_existe():
    """Garde l'instrument d'abord."""
    mod = _module()
    assert hasattr(mod, "valider_identites"), (
        "`validate(channel, payload)` ne recoit ni expediteur ni destinataire : "
        "l'identite d'un message M2M n'est validee NULLE PART")


def test_une_identite_DECLAREE_passe():
    mod = _module()
    v = mod.valider_identites("agt_claude", "agt_antigravity")
    assert v.get("code", "").startswith("M2M_OK"), f"identites declarees refusees : {v}"


def test_le_DOUBLE_PREFIXE_agt_agt_est_signale():
    """Le cas reel : 25 messages accumules sur une identite que nul ne draine."""
    mod = _module()
    v = mod.valider_identites("agt_agt_gemini", "agt_claude")
    assert v.get("code") != "M2M_OK", "l'identite fantome passe sans un mot"
    assert "agt_agt_gemini" in str(v.get("violations") or v), (
        f"le nom fautif n'est pas nomme dans le verdict : {v}")


def test_par_DEFAUT_c_est_un_AVERTISSEMENT_jamais_un_refus(monkeypatch):
    """24 chemins d'ecriture : un gate bloquant d'emblee les casserait tous."""
    mod = _module()
    monkeypatch.delenv("LAFORGE_M2M_MODE", raising=False)
    v = mod.valider_identites("agt_agt_gemini", "agt_claude")
    assert "WARN" in v.get("code", ""), (
        f"le gate refuse alors qu'il n'a jamais mesure son bruit : {v}")


def test_en_mode_ERROR_le_refus_devient_explicite(monkeypatch):
    """Le meme interrupteur que la prose, deja en place -- on n'en cree pas un second."""
    mod = _module()
    monkeypatch.setenv("LAFORGE_M2M_MODE", "error")
    v = mod.valider_identites("agt_agt_gemini", "agt_claude")
    assert "ERR" in v.get("code", ""), f"mode error sans refus : {v}"


def test_la_SURFACE_est_rendue_et_distingue_CLI_d_AUTONOME():
    """Directive owner : agy autonome n'est pas pareil qu'agy CLI."""
    mod = _module()
    a = mod.valider_identites("AGY_CLI", "agt_claude")
    b = mod.valider_identites("AGY_HEADLESS", "agt_claude")
    assert a.get("surface_from") != b.get("surface_from"), (
        f"AGY_CLI et AGY_HEADLESS rendent la meme surface : "
        f"{a.get('surface_from')!r} == {b.get('surface_from')!r}")
    assert b.get("surface_from") == "autonomous"


def test_le_validateur_ne_CASSE_JAMAIS_un_canal():
    """fail-open, comme `validate` juste a cote : un validateur qui leve coupe
    la communication qu'il protege."""
    mod = _module()
    for mauvais in (None, "", 42, {"pas": "une chaine"}):
        v = mod.valider_identites(mauvais, mauvais)   # ne doit pas lever
        assert isinstance(v, dict)


# ─────────────────────────────  INCARNATION  ──────────────────────────

def test_l_incarnation_existe_et_porte_les_TROIS_champs():
    mod = _module()
    assert hasattr(mod, "incarnation"), (
        "aucune incarnation : « agy tourne » et « CETTE instance d'agy » sont "
        "indiscernables dans le journal")
    i = mod.incarnation("AGY_CLI")
    for champ in ("agent_id", "instance_id", "generation"):
        assert champ in i, f"champ d'incarnation manquant : {champ} ({i})"


def test_l_instance_id_est_STABLE_dans_un_meme_processus():
    """Une incarnation qui change a chaque appel n'identifie rien."""
    mod = _module()
    a = mod.incarnation("AGY_CLI")["instance_id"]
    b = mod.incarnation("AGY_CLI")["instance_id"]
    assert a, "instance_id vide : il n'incarne rien"
    assert a == b, f"l'instance_id change entre deux appels du MEME processus : {a} != {b}"


def test_l_agent_id_est_le_nom_CANONIQUE_pas_l_alias():
    """L'identite logique est stable : `agt_claude` et `CLAUDE` sont le meme agent."""
    mod = _module()
    assert mod.incarnation("agt_claude")["agent_id"] == \
           mod.incarnation("CLAUDE")["agent_id"]


def test_deux_agents_DIFFERENTS_ont_des_agent_id_differents():
    """Le symetrique : sans lui, tout resoudre vers une constante passerait."""
    mod = _module()
    assert mod.incarnation("AGY_CLI")["agent_id"] != \
           mod.incarnation("agt_claude")["agent_id"]


def test_une_incarnation_d_agent_INCONNU_le_DIT():
    """`UNKNOWN` reste `UNKNOWN` : on ne fabrique pas une identite canonique."""
    mod = _module()
    i = mod.incarnation("agt_agt_gemini")
    assert i.get("agent_id") is None or i.get("declare") is False, (
        f"une identite fantome recoit une incarnation comme si de rien : {i}")
