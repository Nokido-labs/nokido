"""NR — l'inbox DIT l'age d'un message et si son sha cible est encore HEAD.

MESURE DU 2026-09-20 sur `agent_messages` (21 852 lignes) :

    status     n        plus vieux
    archived   11 656   30,0 j
    read        6 596   30,0 j
    unread      3 571   16,5 j      <- des non-lus de plus de deux semaines
    pending        17   139,2 j     <- 4,5 mois
    done           12    81,8 j

AUCUNE PEREMPTION : un message non lu le reste indefiniment. C'est ainsi qu'un
`ERR_TEST_FAIL` pointant `gh_run:35513864663` / sha `dc7556e03` (13:33, failure)
restait depilable alors que `c9e0da8ea` etait vert depuis 14:28 -- 55 minutes
plus tard. Un agent qui le dépile ouvre un chantier DEJA RESOLU.

CE QUE CE NR N EXIGE PAS, et c'est la consigne : aucune suppression, aucun
marquage automatique en « obsolete ». Un sha different de HEAD ne signifie PAS
que la mission est caduque -- le commit peut etre sans rapport avec son perimetre.
La peremption doit rester SEMANTIQUE, donc humaine ou raisonnee.

CE QUE CE NR EXIGE : que l'information soit DISPONIBLE au moment de la decision.
L'inbox affichait `[sender @ created_at]` -- une date brute, jamais un age, et
jamais la comparaison avec HEAD. Le lecteur devait faire le calcul de tete, et ne
le faisait pas.

C'est un HOOK : il tire a chaque tour et ne coute aucun token. « Travail
repetitif -> cabler en hook. »

PORTEE DITE : ce NR garde l'ANNOTATION. Il ne juge ni la pertinence d'un message,
ni son intent, ni le drain.
"""
from __future__ import annotations

import time

import pytest


def _module():
    import importlib
    for nom in ("nokido_agent.tools.claude_inbox_tick", "tools.claude_inbox_tick",
                "claude_inbox_tick"):
        try:
            return importlib.import_module(nom)
        except Exception:  # noqa: BLE001
            continue
    pytest.skip("claude_inbox_tick introuvable sous ses trois noms d'import")


def test_le_helper_d_annotation_existe():
    """Garde l'instrument d'abord."""
    mod = _module()
    assert hasattr(mod, "_annoter_peremption"), (
        "_annoter_peremption absent : l'inbox affiche une date brute et le "
        "lecteur doit calculer l'age de tete -- ce qu'il ne fait pas")


def test_l_age_est_DIT_en_clair():
    """Une date ISO n'est pas un age. 139 jours doivent se LIRE comme tels."""
    mod = _module()
    vieux = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 139 * 86400))
    note = mod._annoter_peremption("{}", vieux)
    assert note, "aucune annotation pour un message de 139 jours"
    assert "139" in note or "4 mois" in note or "j" in note, (
        f"l'age n'est pas lisible dans l'annotation : {note!r}")


def test_un_message_FRAIS_n_est_pas_bruyant():
    """Un garde qui crie a faux se fait desarmer : pas d'annotation d'age sur du frais."""
    mod = _module()
    frais = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 60))
    note = mod._annoter_peremption("{}", frais)
    assert not note or "j" not in note, (
        f"un message d'une minute est annote comme vieux : {note!r}")


def test_un_sha_DIFFERENT_de_HEAD_est_signale_SANS_conclure():
    """Le coeur : informer, jamais decider.

    Le mot « obsolete » ou « perime » ne doit PAS apparaitre -- un commit peut
    etre sans rapport avec le perimetre de la mission.
    """
    mod = _module()
    frais = time.strftime("%Y-%m-%dT%H:%M:%S")
    payload = '{"intent":"ERR_TEST_FAIL","pointer_ref":"gh_run:35513864663",' \
              '"sha":"dc7556e0391cebcc8e07175952a61704df1f0f9b"}'
    note = mod._annoter_peremption(payload, frais)
    assert note, "un sha cible n'a produit aucune annotation"
    bas = note.lower()
    assert "head" in bas or "sha" in bas, f"le sha n'est pas mentionne : {note!r}"
    # MOTS ENTIERS, jamais des sous-chaines. Premiere version de ce test : je
    # cherchais « perime » par `in`, et « perimetre » le contient -- mon propre
    # garde criait au faux sur une annotation correcte. Une sonde non
    # discriminante est exactement ce que ce depot passe sa vie a corriger, et
    # je viens de l'ecrire dans le garde cense s'en proteger.
    import re as _re
    for interdit in ("obsolete", "obsolète", "perime", "périmé", "perimee",
                     "périmée", "caduc", "caduque"):
        assert not _re.search(r"\b" + _re.escape(interdit) + r"\b", bas), (
            f"l'annotation CONCLUT a l'obsolescence ({interdit!r}) alors qu'un "
            f"commit peut etre etranger au perimetre de la mission : {note!r}")


def test_un_payload_SANS_sha_ne_fabrique_rien():
    """Pas de sha, pas d'affirmation sur le sha. `UNKNOWN` reste `UNKNOWN`."""
    mod = _module()
    frais = time.strftime("%Y-%m-%dT%H:%M:%S")
    note = mod._annoter_peremption('{"intent":"COLLAB_PING"}', frais)
    assert "sha" not in (note or "").lower(), (
        f"une annotation de sha sur un message qui n'en porte aucun : {note!r}")


def test_un_payload_ILLISIBLE_ne_casse_jamais_le_hook():
    """Un hook qui leve prive l'agent de TOUTE son inbox."""
    mod = _module()
    for mauvais in ("{ pas du json", "", None, "[]"):
        mod._annoter_peremption(mauvais, "pas-une-date")   # ne doit pas lever


def test_la_SURFACE_de_l_expediteur_est_distinguee():
    """Directive owner du 2026-09-20 : « agy autonome n'est pas pareil qu'agy CLI ».

    Le SSoT `config/agent_identities.json` porte deja la distinction
    (`surface=interactive` vs `autonomous`), mais rien ne la REMONTAIT au lecteur.
    Deux surfaces du meme agent sont deux interlocuteurs differents, avec deux
    drains differents -- confondre les deux, c'est repondre au mauvais.
    """
    mod = _module()
    frais = time.strftime("%Y-%m-%dT%H:%M:%S")
    intera = mod._annoter_peremption("{}", frais, sender="AGY_CLI")
    autono = mod._annoter_peremption("{}", frais, sender="AGY_HEADLESS")
    assert intera != autono, (
        f"AGY_CLI et AGY_HEADLESS produisent la MEME annotation : "
        f"{intera!r} == {autono!r}")
    assert "autonom" in (autono or "").lower(), (
        f"la surface autonome n'est pas dite : {autono!r}")


def test_un_destinataire_INCONNU_du_registre_est_SIGNALE():
    """Mesure du jour : `agt_agt_gemini` porte 25 messages unread -- un DOUBLE
    prefixe `agt_`, donc une identite que personne ne draine.

    Une identite absente du SSoT n'est pas « probablement untel » : elle est
    NON DECLAREE, et le dire est la seule facon de voir le defaut.
    """
    mod = _module()
    frais = time.strftime("%Y-%m-%dT%H:%M:%S")
    note = mod._annoter_peremption("{}", frais, sender="agt_agt_gemini")
    assert note, "aucune annotation pour une identite inconnue du registre"
    assert "non declar" in note.lower() or "inconnu" in note.lower(), (
        f"l'identite fantome n'est pas signalee : {note!r}")


def test_un_expediteur_CONNU_et_FRAIS_ne_fait_pas_de_bruit():
    """Un garde qui crie a chaque message se fait desarmer."""
    mod = _module()
    frais = time.strftime("%Y-%m-%dT%H:%M:%S")
    note = mod._annoter_peremption("{}", frais, sender="agt_claude")
    bas = (note or "").lower()
    assert "non declar" not in bas and "inconnu" not in bas, (
        f"une identite parfaitement declaree est signalee : {note!r}")


def test_sender_ABSENT_ne_casse_rien():
    """Retro-compatible : les appels a deux arguments doivent continuer."""
    mod = _module()
    mod._annoter_peremption("{}", time.strftime("%Y-%m-%dT%H:%M:%S"))


def test_l_annotation_est_REELLEMENT_APPELEE_par_l_inbox():
    """Un durcissement non appele est une panne en attente (paye le 2026-09-18).

    Definir le helper sans le brancher ferait passer tous les tests ci-dessus
    sans qu'aucune ligne d'inbox ne porte jamais l'information.
    """
    import inspect
    mod = _module()
    src = inspect.getsource(mod._inbox)
    assert "_annoter_peremption" in src, (
        "le helper existe mais `_inbox` ne l'appelle pas : aucune ligne affichee "
        "ne portera l'age ni le sha")
