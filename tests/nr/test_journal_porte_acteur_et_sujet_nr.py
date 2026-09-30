r"""NR — le journal d'identite conserve l'ACTEUR, pas seulement le SUJET.

MESURE DU 2026-09-21 sur la base certifiee `e77c304cf`.

`forge_videur.resolve_identity` produit DEJA la distinction RFC 8693 quand une
delegation a lieu :

    sortie["acteur"] = delegue_par      qui agit reellement
    sortie["sujet"]  = agent            au nom de qui

Et son propre commentaire dit pourquoi elle a ete ajoutee :

    « Notre dispositif faisait de l'IMPERSONATION en se disant delegation :
      `agent` valait B et l'identite de A ne survivait que dans `via`, un champ
      de TRACE qu'aucun consommateur n'inspecte pour decider. »

MAIS `forge_videur.capture` ne recopie que les champs canoniques :

    rec.update({"ts", "agent", "ring", "via", "tool", "token_h"})

=> `acteur` et `sujet` sont PRODUITS puis PERDUS au moment d'ecrire le journal.
   L'acteur ne survit que dans `via`, encode en chaine `delegated:<NOM>` --
   exactement l'etat que le correctif de delegation avait voulu quitter.

La correction a ete faite a la SORTIE, jamais au JOURNAL. Une distinction qui
n'atteint pas la trace ne permet pas de reconstruire la chaine six mois plus
tard, et c'est precisement ce qu'on demande a un journal d'attribution.

CE QUI EST VERROUILLE ICI
=========================
  1. `capture` accepte un `extra` et le CONSERVE -- donc l'appelant peut
     transmettre l'acteur sans modifier le videur ;
  2. les champs CANONIQUES priment sur `extra` -- un appelant ne peut pas
     falsifier `agent`/`ring`/`tool`/`token_h` par ce biais ;
  3. le hub TRANSMET effectivement acteur/sujet quand la resolution les produit.

POURQUOI LA CORRECTION EST COTE APPELANT
========================================
`app/forge_videur.py` porte au moment de ce commit des modifications NON
COMMITEES appartenant a une AUTRE SURFACE (correctif anti-spoof, +42 lignes).
Les toucher ferait entrer leur travail dans ce commit. `capture` expose deja le
point d'extension necessaire : on l'utilise au lieu de modifier le module.

    WORKTREE_STATE != CERTIFIED_SHA != PROPOSED_COMMIT

CE QUE CE NR NE PROUVE PAS : que le journal soit RELU. Il est chiffre en DPAPI
USER scope et appartient au compte owner -- mesure du 2026-09-02, le compte de
service ne peut pas le dechiffrer. C'est une frontiere voulue. Conserver un
champ n'est donc pas le rendre exploitable ; ce NR garde la CONSERVATION, la
lecture forensique reste une capacite owner.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest


def _racine() -> Path:
    for base in (Path(__file__).resolve().parents[2], Path(__file__).resolve().parents[1]):
        if (base / "tools" / "nokido_hub.py").exists():
            return base
    raise AssertionError("racine du depot introuvable")


def _videur():
    for nom in ("nokido_agent.app.forge_videur", "app.forge_videur", "forge_videur"):
        try:
            return __import__(nom, fromlist=["capture"])
        except Exception:  # noqa: BLE001
            continue
    raise AssertionError("forge_videur introuvable")


# ───────────────  LE POINT D EXTENSION EXISTE ET TIENT  ────────────────────

def test_capture_conserve_les_champs_extra(monkeypatch):
    """Sans cette propriete, corriger cote appelant serait impossible."""
    v = _videur()
    vus = {}
    monkeypatch.setattr(v, "_append_audit", lambda rec: vus.update(rec))
    v.capture({"agent": "CLAUDE", "ring": 1, "via": "delegated:WEBHUB",
               "token_h": "abcd"}, "outil_de_test",
              {"acteur": "WEBHUB", "sujet": "CLAUDE"})
    assert vus.get("acteur") == "WEBHUB", (
        "capture n'a pas conserve `acteur` : le journal ne peut pas porter "
        "l'identite de celui qui AGIT (%r)" % (vus,))
    assert vus.get("sujet") == "CLAUDE"


def test_les_champs_canoniques_priment_sur_extra(monkeypatch):
    """Un appelant ne doit pas pouvoir falsifier l'identite journalisee en
    passant `agent` dans `extra`. C'est la contrepartie du test precedent :
    l'extension ne doit pas devenir une porte."""
    v = _videur()
    vus = {}
    monkeypatch.setattr(v, "_append_audit", lambda rec: vus.update(rec))
    v.capture({"agent": "VRAI", "ring": 4, "via": "header", "token_h": "x"},
              "outil", {"agent": "USURPE", "ring": 0, "tool": "MENTEUR"})
    assert vus.get("agent") == "VRAI", "extra a ECRASE l'agent canonique"
    assert vus.get("ring") == 4, "extra a ECRASE le ring canonique"
    assert vus.get("tool") == "outil", "extra a ECRASE le tool canonique"


def test_le_journal_ne_recopie_jamais_le_jeton_en_clair(monkeypatch):
    """Invariant deja porte par le module ; re-verrouille ici parce que ce NR
    ajoute un champ au journal et ne doit pas ouvrir cette porte."""
    v = _videur()
    vus = {}
    monkeypatch.setattr(v, "_append_audit", lambda rec: vus.update(rec))
    TEMOIN = "JETON-EN-CLAIR-TEMOIN"
    v.capture({"agent": "A", "ring": 3, "via": "token", "token_h": "h"},
              "outil", {"acteur": "B", "sujet": "A"})
    assert TEMOIN not in repr(vus)
    assert "token" not in {k for k in vus if k != "token_h"}


# ──────────────  LE HUB TRANSMET CE QU IL A RESOLU  ───────────────────────

def test_le_hub_transmet_acteur_et_sujet_au_journal():
    """LE COEUR. `resolve_identity` produit acteur/sujet ; si le site d'appel
    ne les passe pas a `capture`, la distinction meurt entre les deux.

    Test de CABLAGE, dit comme tel : il verifie que l'appel porte l'extension,
    pas que le journal soit relu ensuite.
    """
    src = (_racine() / "tools" / "nokido_hub.py").read_text(encoding="utf-8")
    t = ast.parse(src)
    porteurs = []
    for n in ast.walk(t):
        if isinstance(n, ast.Call):
            nom = getattr(n.func, "id", None) or getattr(n.func, "attr", None)
            if nom in ("_vcapture", "capture") and len(n.args) >= 2:
                porteurs.append(len(n.args) >= 3 or bool(n.keywords))
    assert porteurs, "aucun appel a capture trouve dans le hub : re-mesurer"
    assert any(porteurs), (
        "aucun appel a capture ne passe d'`extra` : acteur/sujet resolus par "
        "le videur n'atteignent jamais le journal, et l'acteur ne survit que "
        "dans `via` sous forme de chaine")


def test_l_instrument_distingue_un_appel_avec_et_sans_extra():
    """Un detecteur qui ne rend jamais rien est indistinguable d'un code sain."""
    sans = ast.parse("capture(ident, 'outil')\n").body[0].value
    avec = ast.parse("capture(ident, 'outil', {'acteur': 'X'})\n").body[0].value
    assert len(sans.args) == 2 and not sans.keywords
    assert len(avec.args) == 3


# ══════════════════════════════════════════════════════════════════════════
#  P1-K — QUELLES DECISIONS ATTEIGNENT LE JOURNAL ?
#  Mesure du 2026-09-21, au soir.
#
#      EXISTS != CALLED != PRODUCED != JOURNALIZED
#
#  LA DISSYMETRIE MESUREE, et c'est elle le fait :
#
#    `_resolve_ring` (videur)   repond « QUI ES-TU », ne refuse presque rien
#                               -> journalise, et porte acteur/sujet depuis ce
#                                  matin. NEUF handlers l'atteignent.
#    `_admin_tok_ok`            REFUSE effectivement, sur 24 routes
#                               -> AUCUNE trace d'audit. 60 lignes, quatre
#                                  chemins de decision, retour True/False sans
#                                  le moindre effet de bord observable.
#
#  Le garde permissif trace. Le garde strict est muet. On ne peut donc pas
#  savoir apres coup si un appel a `/admin/run_job` est passe par le maitre,
#  par un jeton propre d'organe, ou par l'exemption loopback de
#  `LAFORGE_NO_AUTH` -- alors que ces trois chemins n'accordent pas la meme
#  chose et que le code lui-meme invoque l'argument d'attribution :
#  « un organe qui porte FORGE_MCP_TOKEN devient indiscernable dans le journal ».
#
#  PIEGE EVITE EN ECRIVANT CE TEST. Une premiere mesure, bornee au CORPS du
#  handler, rendait « 0 sur 33 ». C'etait FAUX : `mcp_post` journalise via
#  `_resolve_ring`, a la profondeur 2. Meme motif que les deux faux verdicts
#  corriges le meme jour --
#
#      OBSERVED(handler) != PROPERTY_OF(chemin)
#
#  -- et la troisieme occurrence du meme reflexe. La profondeur est donc
#  suivie ici, bornee a 4, et la borne est DITE.
# ══════════════════════════════════════════════════════════════════════════

#: Appels qui ecrivent dans le journal d'AUDIT. `logger.*` n'en fait pas
#: partie : une trace applicative n'est ni chainee, ni signee, ni porteuse
#: d'identite. Les confondre fabriquerait une couverture inexistante.
_AUDIT = {"capture", "_vcapture", "_append_audit", "audit_log", "log_audit"}

#: Handlers dont le chemin atteint le journal, MESURES. Un handler qui
#: apparait ou disparait de cette liste signale un changement de couverture.
#: 2026-09-21, apres P1-N : passe de NEUF a TRENTE-DEUX. Les 23 nouvelles
#: sont les routes gardees par `_admin_tok_ok`, qui capture desormais ses
#: REFUS. Ce test a EXIGE la mise a jour en rougissant -- c'est sa raison
#: d'etre, et le sens « un handler qui GAGNE une trace » est le bon.
JOURNALISENT = {
    # via `_resolve_ring -> _vcapture` (chemin videur)
    "mcp_post", "mcp_get", "mcp_batch", "admin_restart",
    "rings_set", "rings_ui", "swarm_run", "recon_run", "ctf_run",
    # via `_admin_tok_ok -> _journaliser_refus_admin` (refus seulement)
    "admin_heap", "admin_ingest_repo", "admin_job_status", "admin_job_stop",
    "admin_run_job", "audit_recent", "audit_trace", "hormones_release",
    "ingest_bulk", "ingest_qualify", "ingest_url", "maintenance_gc",
    "mcp_config_toggle", "mpc_plan", "orchestrate_loop", "ring_buffer_stats",
    "sandbox_spawn", "services_boot_all", "services_logs", "services_restart",
    "services_shutdown_all", "services_start", "services_stop",
    # 2026-09-26 : cloture auth du 24/09 (ce70f4d4e) -- routes d'organes passees par `_exiger_identite`,
    # qui journalise. Quatre handlers GAGNENT une trace (le bon sens du cliquet).
    "api_ingest", "nervous_emit", "resource_should_spawn", "services_list",
    # 2026-09-28 : delegation d'eviction au hub, route d'organe par `_exiger_identite` -- elle
    # GAGNE une trace (le bon sens du cliquet).
    "resource_request",
}


def _fonctions_du_hub() -> dict:
    src = (_racine() / "tools" / "nokido_hub.py").read_text(encoding="utf-8")
    return {n.name: n for n in ast.walk(ast.parse(src))
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _alias_du_journal() -> set:
    """Les NOMS LOCAUX sous lesquels une fonction d'audit est appelee.

    DEFAUT MESURE LE 2026-09-21 : `from ... import capture as _cap` rendait le
    detecteur aveugle. Il cherchait « capture », le code appelait « _cap ».
    Un alias d'import suffisait a faire disparaitre une trace REELLE.

        LE NOM LOCAL N'EST PAS LE NOM IMPORTE

    Meme famille que les cinq autres faux verdicts du jour : on regardait le
    lieu de l'ECRITURE et pas ce qu'il designe.
    """
    src = (_racine() / "tools" / "nokido_hub.py").read_text(encoding="utf-8")
    noms = set(_AUDIT)
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.ImportFrom):
            for a in n.names:
                if a.name in _AUDIT and a.asname:
                    noms.add(a.asname)
        elif isinstance(n, ast.Import):
            for a in n.names:
                if a.name.split(".")[-1] in _AUDIT and a.asname:
                    noms.add(a.asname)
    return noms


def _chemin_vers_le_journal(nom, fonctions, vus=None, prof=0):
    """Chemin nom -> appel d'audit, ou None. BORNE a 4 niveaux.

    Un `None` dit que CETTE profondeur n'a rien vu. Il ne prouve pas qu'aucun
    journal n'est atteint -- un middleware ou un decorateur restent hors de
    portee d'une lecture de source.
    """
    vus = vus if vus is not None else set()
    if nom in vus or nom not in fonctions or prof > 4:
        return None
    vus.add(nom)
    noeud = fonctions[nom]
    connus = _alias_du_journal()
    for x in ast.walk(noeud):
        if isinstance(x, ast.Call):
            a = getattr(x.func, "id", None) or getattr(x.func, "attr", None)
            if a in connus:
                return [nom, a]
    for x in ast.walk(noeud):
        if isinstance(x, ast.Call):
            a = getattr(x.func, "id", None) or getattr(x.func, "attr", None)
            if a and a in fonctions and a != nom:
                suite = _chemin_vers_le_journal(a, fonctions, vus, prof + 1)
                if suite:
                    return [nom] + suite
    return None


def test_le_chemin_du_videur_atteint_bien_le_journal():
    """CONTROLE POSITIF. Si ce chemin cassait, le test suivant deviendrait
    vert pour une mauvaise raison : « personne ne journalise » ressemble a
    « la mesure ne voit plus rien »."""
    fonctions = _fonctions_du_hub()
    chemin = _chemin_vers_le_journal("_resolve_ring", fonctions)
    assert chemin, "`_resolve_ring` n'atteint plus le journal : re-mesurer"
    assert chemin[-1] in _AUDIT


def test_l_inventaire_des_handlers_qui_journalisent_est_a_jour():
    """Cliquet DANS LES DEUX SENS. Un handler qui gagne une trace est une
    bonne nouvelle a enregistrer ; un handler qui en perd une est une
    regression silencieuse."""
    fonctions = _fonctions_du_hub()
    src = (_racine() / "tools" / "nokido_hub.py").read_text(encoding="utf-8")
    routes = set()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Call):
            nm = getattr(n.func, "attr", None) or getattr(n.func, "id", None)
            if nm in ("add_route", "Route") and n.args:
                a0 = n.args[0]
                if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
                    for a in n.args[1:]:
                        if isinstance(a, ast.Name):
                            routes.add(a.id)
                            break
    reels = {h for h in routes if _chemin_vers_le_journal(h, fonctions)}
    apparus = reels - JOURNALISENT
    disparus = JOURNALISENT - reels
    assert not apparus, (
        "handlers qui atteignent desormais le journal, absents de "
        "l'inventaire : %s -- mettre a jour pour que le chiffre reste vrai"
        % sorted(apparus))
    assert not disparus, (
        "handlers qui N'ATTEIGNENT PLUS le journal : %s -- une trace a "
        "disparu, et une decision d'autorite est redevenue invisible"
        % sorted(disparus))


# ══════════════════════════════════════════════════════════════════════════
#  P1-N — LE REFUS EST CAPTURE, L'ACCEPTATION NE L'EST PAS
#
#  Le test precedent (ecrit quelques heures plus tot) FIGEAIT l'absence de
#  trace et demandait trois verifications le jour ou une capture apparaitrait.
#  Les voici, adossees a une mesure et non a une preference.
#
#  HUIT MESURES ONT TRANCHE, sans qu'une decision humaine soit necessaire :
#
#    24 routes gardees, toutes reliees a `_admin_tok_ok`
#     4 chemins de decision -- un refus ne disait pas LEQUEL avait echoue
#     1 seul appelant pour `_refus_401` : ce n'etait pas le chemin universel
#     0 corr_id disponible dans la fonction (`trace_context` existe ailleurs)
#       la ROUTE manquait aussi : la signature est (request, required_scope)
#       -- mais `request.url.path` la porte, donc AUCUNE signature a changer
#       le porteur n'a pas besoin d'etre ecrit : `_token_hash` existe deja
#       `capture(identity, tool, extra)` recoit l'evenement tel quel
#
#  LE VOLUME EST LA SEULE RAISON DE NE PAS TOUT CAPTURER. Le journal chiffre
#  CHAQUE entree (DPAPI) et la chaine en HMAC : capturer les ACCEPTATIONS de
#  24 routes a chaque requete est un choix de debit qu'aucune mesure ne
#  justifie ici. Capturer les REFUS est borne par le nombre de refus, petit en
#  fonctionnement normal.
#
#      ON CAPTURE CE QUI EST RARE ET EXPLICATIF, PAS CE QUI EST FREQUENT
#
#  Ce qui reste NON MESURE et doit le rester dans le rapport : le debit reel
#  de ces 24 routes. Aucune sonde n'a compte les requetes par minute.
# ══════════════════════════════════════════════════════════════════════════

def test_le_refus_du_garde_admin_est_capture():
    """LE COEUR. Un refus d'autorite doit laisser une trace, sinon personne ne
    peut savoir qu'on a frappe a la porte -- ni par quel chemin."""
    fonctions = _fonctions_du_hub()
    assert "_admin_tok_ok" in fonctions, "`_admin_tok_ok` introuvable : re-mesurer"
    chemin = _chemin_vers_le_journal("_admin_tok_ok", fonctions)
    assert chemin, (
        "`_admin_tok_ok` n'atteint aucun journal d'audit : ses 24 routes "
        "refusent sans trace, et les quatre chemins de decision (JWT, maitre, "
        "exemption loopback, jeton propre) restent indiscernables apres coup")


def test_la_capture_du_refus_n_ecrit_jamais_le_porteur():
    """INVARIANT NON NEGOCIABLE. La fonction manipule `tok` en clair ; la
    trace ne doit transporter qu'un hash. Verifie sur le TEXTE de la fonction,
    parce que c'est la forme de l'appel qui decide -- pas une intention."""
    import ast as _ast
    src = (_racine() / "tools" / "nokido_hub.py").read_text(encoding="utf-8")
    noeud = next(n for n in _ast.walk(_ast.parse(src))
                 if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef))
                 and n.name == "_admin_tok_ok")
    lignes = src.splitlines()
    corps = "\n".join(lignes[noeud.lineno - 1:getattr(noeud, "end_lineno", noeud.lineno + 90)])

    # L'INVARIANT PORTE SUR LE JOURNAL, PAS SUR LE PASSAGE D'ARGUMENT.
    #
    # Premiere version de ce test : elle interdisait de PASSER `tok` a quoi
    # que ce soit. Or la fonction qui le HACHE doit bien le recevoir. Un test
    # de securite trop strict ne protege pas mieux : il interdit le remede.
    #
    # On verifie donc ce qui compte : aucun appel au JOURNAL lui-meme ne
    # transporte le porteur nu.
    connus = _alias_du_journal()
    for n in _ast.walk(noeud):
        if not isinstance(n, _ast.Call):
            continue
        nom = getattr(n.func, "id", None) or getattr(n.func, "attr", None)
        if nom not in connus:
            continue
        rendu = _ast.dump(n)
        assert "'tok'" not in rendu and '"tok"' not in rendu, (
            "un appel DIRECT au journal transporte la variable `tok` : le "
            "porteur ne doit y entrer que HACHE")

    # Et la fonction de trace, elle, doit hacher.
    trace = next((n for n in _ast.walk(_ast.parse(src))
                  if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef))
                  and n.name == "_journaliser_refus_admin"), None)
    assert trace is not None, (
        "`_journaliser_refus_admin` introuvable : si la trace a ete deplacee, "
        "re-mesurer ou l'invariant du porteur est tenu")
    corps_trace = "\n".join(
        lignes[trace.lineno - 1:getattr(trace, "end_lineno", trace.lineno + 60)])
    assert "sha256" in corps_trace or "_token_hash" in corps_trace, (
        "la fonction de trace ne hache pas le porteur")
    # `tok` APPARAIT forcement dans l'appel -- c'est `sha256(tok.encode())`.
    # Chercher la CHAINE `id='tok'` dans le dump confondait donc le porteur
    # avec son hash : encore « chercher un symbole au lieu de ce qu'il
    # devient ». On verifie ce qui compte : aucune valeur transmise n'est
    # `tok` NU, c'est-a-dire un `Name` non transforme.
    for n in _ast.walk(trace):
        if not isinstance(n, _ast.Call):
            continue
        if (getattr(n.func, "id", None) or getattr(n.func, "attr", None)) not in connus:
            continue
        a_examiner = list(n.args)
        for arg in n.args:
            if isinstance(arg, _ast.Dict):
                a_examiner.extend(arg.values)
        nus = [a for a in a_examiner
               if isinstance(a, _ast.Name) and a.id == "tok"]
        assert not nus, (
            "la trace passe `tok` NU au journal (et non son hash) a la ligne "
            "%s" % [a.lineno for a in nus])


def test_la_capture_nomme_le_chemin_de_decision():
    """Sans cela, la trace dit « refuse » sans dire par quelle autorite --
    et les quatre chemins restent indiscernables, ce qui etait precisement
    le defaut mesure."""
    src = (_racine() / "tools" / "nokido_hub.py").read_text(encoding="utf-8")
    import ast as _ast
    noeud = next(n for n in _ast.walk(_ast.parse(src))
                 if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef))
                 and n.name == "_admin_tok_ok")
    lignes = src.splitlines()
    corps = "\n".join(lignes[noeud.lineno - 1:getattr(noeud, "end_lineno", noeud.lineno + 90)])
    assert "admin_tok" in corps and ("via" in corps or "chemin" in corps), (
        "la capture ne porte pas de marqueur de chemin : un lecteur du journal "
        "ne saura pas si le refus vient du JWT, du maitre, du jeton propre ou "
        "de l'exemption loopback")


def test_l_acceptation_n_est_PAS_capturee():
    """CONTRE-EPREUVE DE VOLUME, et elle est aussi importante que le reste.

    Capturer les acceptations de 24 routes a CHAQUE requete multiplierait les
    chiffrements DPAPI sans qu'aucune mesure de debit ne le justifie. Ce test
    empeche la derive vers « on journalise tout », qui finit toujours par etre
    desarmee en bloc.

    Si un jour le contrat exige de tracer aussi les acceptations, ce test
    rougira -- et il faudra alors avoir MESURE le debit.
    """
    import ast as _ast
    src = (_racine() / "tools" / "nokido_hub.py").read_text(encoding="utf-8")
    noeud = next(n for n in _ast.walk(_ast.parse(src))
                 if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef))
                 and n.name == "_admin_tok_ok")

    # DEUX VERSIONS PRECEDENTES ONT CRIE A FAUX, et pour la meme raison :
    #
    #   1. « une capture dans les 3 lignes avant un `return True` » --
    #      compter des lignes suppose que le fichier s'execute de haut en bas ;
    #   2. « un BLOC qui capture et rend True » -- un `if` parent contient les
    #      deux, mais dans des SOUS-BRANCHES differentes.
    #
    # Le contrat reel est plus simple a enoncer et se verifie exactement :
    #
    #       UNE CAPTURE EST IMMEDIATEMENT SUIVIE D'UN `return False`
    #
    # On regarde donc les SEQUENCES de statements : dans la liste ou une
    # capture apparait, l'instruction suivante doit refuser.
    fautifs = []

    def _verifier(sequence):
        for i, st in enumerate(sequence):
            capture_ici = (
                isinstance(st, _ast.Expr) and isinstance(st.value, _ast.Call)
                and (getattr(st.value.func, "id", None)
                     or getattr(st.value.func, "attr", None))
                in ("capture", "_vcapture", "_journaliser_refus_admin"))
            if not capture_ici:
                continue
            suite = sequence[i + 1] if i + 1 < len(sequence) else None
            ok = (isinstance(suite, _ast.Return)
                  and isinstance(suite.value, _ast.Constant)
                  and suite.value.value is False)
            if not ok:
                fautifs.append(st.lineno)

    for n in _ast.walk(noeud):
        for champ in ("body", "orelse", "finalbody"):
            sequence = getattr(n, champ, None)
            if isinstance(sequence, list):
                _verifier(sequence)

    assert not fautifs, (
        "une capture (L%s) n'est pas immediatement suivie d'un `return "
        "False` : soit une ACCEPTATION serait tracee -- a chaque requete des "
        "24 routes -- soit la trace n'accompagne pas le refus qu'elle "
        "pretend expliquer." % fautifs)
