# -*- coding: utf-8 -*-
"""NR — consommer la boite d'un agent devrait exiger d'ETRE cet agent.

CE QUE CE FICHIER FAIT, ET CE QU'IL NE FAIT PAS
    Il ENREGISTRE un etat mesure et une condition bloquante. Il n'arme AUCUN
    refus : le durcissement demande une decision d'identite qui n'est pas
    prise ici.

        observer avant d'enforcer -- et dire ce qui manque pour enforcer

LA MESURE (2026-09-22)
    `GET /inbox/{agent_id}` appelle `_INBOX.pop(agent_id)`. `pop` RETIRE le
    message de la file : ce n'est pas une lecture, c'est une CONSOMMATION.
    Qui connait un `agent_id` prend les messages destines a cet agent, qui ne
    les recevra jamais.

    Six verifications cherchees dans le handler, ZERO trouvee : resolution
    d'identite, lecture d'un porteur, comparaison avec `agent_id`, garde
    declaree, borne d'origine -- rien ne s'interpose avant le `pop()`.

        CLASSEE LECTURE PAR SA METHODE, C'EST UNE MUTATION PAR SON EFFET

    Et ce n'est pas une decouverte : la memoire du corps porte le meme fait
    depuis le 2026-04-24 sous le nom de « fan-out issue » -- un consommateur
    vide la file au detriment des autres. La cause primaire est ARCHITECTURALE
    (file a consommateur unique la ou plusieurs ecoutent), pas un vol
    d'identite. Les deux se traitent, mais pas par le meme geste.

CE QUI REND LE DURCISSEMENT POSSIBLE
    L'appelant reel PORTE DEJA de quoi se prouver :

        headers={"Authorization": f"Bearer {token}", "X-Agent-Name": "GEMINI"}

    (`tools/gemini_poll_daemon.py`, listener SSE sur `/inbox/agt_gemini`)
    Personne ne le lui demande. Le credential existe, la decision manque.

CE QUI L'EN EMPECHE AUJOURD'HUI
    Lier « appelant » et `agent_id` exige de resoudre les deux vers UNE
    identite. Le registre ne le permet pas pour la famille concernee :

        gemini      -> AGY, ANTIGRAVITY, GEMINI
        agt_gemini  -> ANTIGRAVITY, GEMINI
        agy         -> AGY, ANTIGRAVITY

    7 alias sur 294 designent plusieurs agents, et TOUS sont dans cette seule
    famille -- precisement celle du consommateur mesure. Armer un refus sur
    une base ambigue couperait le daemon ou laisserait passer un tiers.

        UNKNOWN = REFUSE dit la politique du corps ; encore faut-il que
        « qui es-tu » ait UNE reponse.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

_RACINE = Path(__file__).resolve().parents[2]
_HUB = _RACINE / "tools" / "nokido_hub.py"
_REGISTRE = _RACINE / "config" / "agent_identities.json"


def _handler(nom: str):
    src = _HUB.read_text(encoding="utf-8", errors="replace")
    lignes = src.splitlines()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom:
            return "\n".join(lignes[n.lineno - 1:getattr(n, "end_lineno", n.lineno + 60)])
    raise AssertionError("handler %s introuvable -- re-mesurer" % nom)


def _alias_ambigus() -> dict:
    """alias -> agents qui le revendiquent, quand ils sont PLUSIEURS.

    Un `set` par alias : sans lui, un agent dont le nom egale l'un de ses
    propres alias se compte deux fois et fabrique des ambiguites. Mesure du
    2026-09-22 : cette faute annoncait 148 collisions la ou il y en a 7.
    """
    ag = json.loads(_REGISTRE.read_text(encoding="utf-8", errors="replace"))["agents"]
    inv: dict = {}
    for k, v in ag.items():
        if not isinstance(v, dict):
            continue
        for a in [k] + list(v.get("aliases") or []):
            inv.setdefault(str(a).lower(), set()).add(k)
    return {a: sorted(ks) for a, ks in inv.items() if len(ks) > 1}


_MOTIFS_LIAISON = (
    ("resolution d'identite", r"_resolve_ring|resolve_identity|_identite_inbox"),
    ("lecture d'un porteur", r"authorization|Bearer|laforge-agent-name"),
    # Les DEUX sens et les DEUX operateurs. La premiere version ne lisait que
    # `agent_id ==` et `== agent_id` : elle ratait `qui["agent"] != agent_id`,
    # soit la forme la plus naturelle d'un refus. La contre-epreuve l'a dit.
    ("comparaison a agent_id", r"agent_id\s*[!=]=|[!=]=\s*agent_id"),
    # `peut_consommer_boite` MANQUAIT, et son absence a produit un FAUX VERT :
    # le 2026-09-22, la route a ete armee et ce fichier a continue d'affirmer
    # « aucune liaison ». La sonde cherchait des SYMBOLES connus d'avance ; la
    # decision est passee par un nom qu'elle ignorait.
    #
    #     CALL_SITE != DECISION_SITE — un test qui lit le SYMBOLE casse (ou
    #     ment) quand le code change autour ; seul celui qui lit la PROPRIETE tient.
    #
    # C'est pourquoi la preuve qui COMPTE vit desormais dans
    # `test_inbox_ownership_route_nr` : elle appelle la route et compte les
    # `pop()`. Ici on ne garde qu'une vigie STATIQUE, et on l'a retournee.
    ("garde declaree", r"_admin_tok_ok|authorize\(|peut_consommer_boite"),
)


def _liaisons(corps: str) -> list:
    """Ce que le handler fait pour savoir A QUI il donne les messages."""
    return [q for q, m in _MOTIFS_LIAISON if re.search(m, corps, re.I)]


# ── L'ETAT MESURE, fige pour qu'il ne se perde pas ───────────────────────

def test_la_liaison_d_identite_est_POSEE_avant_le_pop():
    """RETOURNE le 2026-09-22, apres armement.

    Ce test enregistrait l'ABSENCE de liaison. La liaison existe desormais :
    laisser l'assertion d'absence en aurait fait un garde qui certifie le
    contraire de ce qui est vrai. On ne le supprime pas -- on lui donne le sens
    que l'etat mesure impose : la garde doit RESTER.

    Il rougit si quelqu'un retire le durcissement de `/inbox/{agent_id}`.
    """
    corps = _handler("inbox_stream")
    assert ".pop(" in corps, "le handler ne consomme plus la file : re-mesurer"
    trouvees = _liaisons(corps)
    assert trouvees, (
        "AUCUNE liaison d'identite avant le `pop()` : le durcissement a disparu, "
        "et qui connait un `agent_id` reprend le courrier d'un autre")
    # `await _INBOX.pop(` et non `.pop(` : la DOCSTRING du handler explique le
    # defaut et cite `_INBOX.pop()`. Chercher `.pop(` trouvait donc la PROSE
    # avant le CODE, et la sonde comparait une position de commentaire.
    #
    #     UN INSTRUMENT NE LIT JAMAIS SON PROPRE VOCABULAIRE
    #
    # Mesure du 2026-09-22 : le motif s'est paye SIX fois dans la journee.
    i_dec = corps.find("peut_consommer_boite")
    i_pop = corps.find("await _INBOX.pop(")
    assert i_pop > 0, "l'appel `await _INBOX.pop(` est introuvable : re-mesurer"
    assert 0 <= i_dec < i_pop, (
        "la decision d'ownership est posee APRES le `pop()` : elle ne peut plus "
        "empecher l'effet qu'elle est censee gouverner")


def test_la_sonde_de_liaison_voit_une_liaison_quand_il_y_en_a_une():
    """CONTRE-EPREUVE. Sans elle, le test precedent serait vert PARCE QUE la
    sonde ne sait rien voir -- un vert qui ne mesure rien.

    Cas CONSTRUIT : un handler qui, lui, lie l'appelant a la boite.
    """
    faux = (
        'async def inbox_stream(request):\n'
        '    agent_id = request.path_params["agent_id"]\n'
        '    qui = _resolve_ring(request)\n'
        '    if qui["agent"] != agent_id:\n'
        '        return JSONResponse({"error": "forbidden"}, status_code=403)\n'
        '    frame = await _INBOX.pop(agent_id, timeout=25.0)\n'
    )
    vues = _liaisons(faux)
    assert len(vues) >= 2, (
        "la sonde ne voit pas une liaison POURTANT ECRITE : elle ne mesure "
        "rien, et le vert du test precedent ne vaut rien. Vues : %s" % vues)


def test_l_appelant_reel_porte_deja_de_quoi_se_prouver():
    """Le credential EXISTE ; c'est la decision qui manque.

    Si ce test rougit, le durcissement devient plus couteux : il faudrait
    d'abord donner un credential a l'appelant.
    """
    p = _RACINE / "tools" / "gemini_poll_daemon.py"
    if not p.exists():
        pytest.skip("daemon absent de ce depot -- etat UNKNOWN, pas 'sans porteur'")
    t = p.read_text(encoding="utf-8", errors="replace")
    i = t.find("/inbox/")
    assert i > 0, "le daemon n'appelle plus /inbox/ : re-mesurer les consommateurs"
    voisinage = t[i:i + 900]
    assert "Authorization" in voisinage and "X-Agent-Name" in voisinage, (
        "l'appelant ne porte plus son credential ET son nom : le durcissement "
        "exigerait d'abord de le lui redonner")


# ── LA CONDITION BLOQUANTE, nommee ───────────────────────────────────────

def test_la_famille_gemini_reste_ambigue_dans_le_registre():
    """CE QUI EMPECHE D'ARMER. Ce test rougit quand l'ambiguite est levee --
    signal que le durcissement redevient decidable."""
    amb = _alias_ambigus()
    bloquants = {a: amb[a] for a in ("gemini", "agt_gemini", "agy") if a in amb}
    assert bloquants, (
        "la famille GEMINI/AGY/ANTIGRAVITY n'est plus ambigue : le durcissement "
        "de `/inbox/{agent_id}` redevient decidable, l'instruire")


def test_l_ambiguite_reste_circonscrite():
    """Elle doit rester une exception nommee, pas s'etendre au registre.

    7 alias sur 294 au 2026-09-22, TOUS dans une seule famille. Si ce nombre
    grandit, c'est la table d'identites qui derive -- et ce n'est plus un cas
    particulier a arbitrer, c'est un probleme de fond.
    """
    amb = _alias_ambigus()
    assert len(amb) <= 12, (
        "l'ambiguite du registre s'etend : %d alias designent plusieurs agents "
        "(7 mesures le 2026-09-22). Resoudre « qui es-tu » devient alors "
        "impossible bien au-dela de l'inbox : %s" % (len(amb), sorted(amb)[:12]))


def test_le_detecteur_d_ambiguite_ne_compte_pas_les_doublons():
    """CONTRE-EPREUVE de l'instrument lui-meme.

    Compter `[nom] + aliases` dans une LISTE fait qu'un agent dont un alias
    egale son nom se compte deux fois. Mesure : 148 annonces, 7 reels.
    """
    faux = {"CLAUDE": {"aliases": ["claude", "CLAUDE"]}}
    inv: dict = {}
    for k, v in faux.items():
        for a in [k] + list(v.get("aliases") or []):
            inv.setdefault(str(a).lower(), set()).add(k)
    assert not {a: ks for a, ks in inv.items() if len(ks) > 1}, (
        "un agent seul produit une ambiguite : l'instrument compte des doublons")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
