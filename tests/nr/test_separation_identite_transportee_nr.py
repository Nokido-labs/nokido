"""Le garde de separation TRANSPORTE l'identite prouvee, il ne la RECALCULE pas.

MESURE 2026-09-07. `enforce_separation` refusait une edition avec ce message :

    Agent 'CLAUDE' (ring 4) is forbidden from editing judge module

Or l'identite reelle de cet agent est **ring 1, PROUVEE par jeton a bail** :
`forge_agent_credential.etat()` rend `{"CLAUDE": {"mode": "COURT", "expire_dans_s":
1800}}` (courts 1, replis 0), et `nokido_hub._resolve_ring` REFUSE en `bad_token`
(ring -1) tout jeton non apparie avant meme d'appeler le videur. Un appel qui aboutit
est donc, par construction, un appel authentifie.

LA CAUSE. Le garde re-resolvait l'identite a partir du seul NOM :

    ident = resolve_identity(actor_agent, local=True)   # ni token, ni agent_tokens

Or `resolve_identity` n'accorde `via="token"` que si on lui passe le jeton ET le
magasin (`if agent and token and agent_tokens`). Sans eux, `via` reste `"header"` et
le plancher anti-spoof (`_HEADER_FLOOR_RING = 4`) s'applique -- **pour tout agent,
toujours, quelle que soit la qualite de son authentification**. Le chiffre affiche ne
mesurait donc pas l'appelant : il mesurait la pauvrete de l'appel.

C'est le motif « TRANSPORTER, JAMAIS RECALCULER » deja paye ce jour meme sur le statut
de certification du graphe de cablage, et la veille sur `forge_tool_gate` (un ring
recalcule dans le garde au lieu d'etre porte par la requete).

CE QUE CE FICHIER NE CHANGE PAS -- et c'est essentiel. La regle de fond reste
`ring > 0` : meme un ring 1 PROUVE ne peut pas editer un module juge, seul le ring 0
le peut. Corriger la mesure ne desserre AUCUN droit ; ca rend seulement le refus
honnete. Un garde qui accuse a faux se fait desarmer -- c'est pour ca qu'un faux
positif se corrige tout de suite.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

JUGE = "app/forge_scorecard.py"


def test_un_ring_TRANSPORTE_est_utilise_tel_quel():
    """PROPRIETE 1. L'identite deja resolue par le hub n'est pas recalculee.

    Le hub a fait le travail : jeton valide, videur consulte avec le magasin. Le garde
    doit s'en servir, sinon deux organes repondent differemment a la meme question.
    """
    from forge_separation import enforce_separation  # noqa: PLC0415

    ok, motif = enforce_separation("CLAUDE", "governed_edit", JUGE, ring=1)
    assert not ok, "un agent de ring 1 ne peut toujours pas editer son juge"
    assert "ring 1" in motif, (
        "le motif doit citer le ring TRANSPORTE (1), pas un plancher recalcule : %r"
        % motif)
    assert "ring 4" not in motif, "le plancher anti-spoof n'a rien a faire ici"


def test_sans_ring_transporte_le_garde_n_INVENTE_pas_de_chiffre():
    """PROPRIETE 2. Trois etats : un ring inconnu se DIT, il ne se fabrique pas.

    Afficher « ring 4 » quand on n'a pas pu mesurer, c'est presenter un defaut par
    defaut comme une mesure -- exactement `UNKNOWN` lu comme `NO`.
    """
    from forge_separation import enforce_separation  # noqa: PLC0415

    ok, motif = enforce_separation("CLAUDE", "governed_edit", JUGE)
    assert not ok, "sans identite transmise, le refus reste (fail-closed)"
    assert "ring 4" not in motif, (
        "le garde affiche un plancher recalcule comme s'il avait mesure l'appelant : "
        "%r" % motif)
    assert ("non transmis" in motif or "INCONNU" in motif), (
        "un ring qu'on n'a pas recu doit etre NOMME comme tel : %r" % motif)


def test_le_ring_0_reste_le_SEUL_a_pouvoir_editer_un_juge():
    """PROPRIETE 3. Non-regression : la separation ne se desserre pas d'un cran."""
    from forge_separation import enforce_separation  # noqa: PLC0415

    ok, _ = enforce_separation("SYSTEM", "governed_edit", JUGE, ring=0)
    assert ok, "le ring 0 (MASTER/local) doit pouvoir maintenir un juge"

    for r in (1, 2, 3, 4):
        refus, motif = enforce_separation("CLAUDE", "governed_edit", JUGE, ring=r)
        assert not refus, "ring %d ne doit PAS pouvoir editer un juge (%s)" % (r, motif)


def test_un_module_ORDINAIRE_reste_editable():
    """PROPRIETE 4. Le garde ne mord que sur les modules JUGES.

    Sans cette borne, durcir la mesure reviendrait a bloquer la maintenance normale --
    le faux positif deja paye sur `forge_alignment_invariants`, retire de la liste
    parce que c'est un DASHBOARD et non un module qui SCORE.
    """
    from forge_separation import enforce_separation  # noqa: PLC0415

    ok, motif = enforce_separation("CLAUDE", "governed_edit", "app/forge_db_path.py",
                                   ring=1)
    assert ok, "un module ordinaire doit rester editable par un agent : %r" % motif
