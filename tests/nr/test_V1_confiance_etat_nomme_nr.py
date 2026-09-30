"""Non-régression V1 : la confiance est un ÉTAT NOMMÉ, pas un nombre par défaut.

Item de veille V1 : « remplacer le score de `forge_memory_gate` par un état
nommé ». La mesure montre que ce n'était pas une préférence de style — le score
par défaut **ouvrait le portail en silence**.

CE QUI SE PASSAIT, mesuré dans `should_ingest` :

    try:
        meta = qualify_for_ingest(...)
    except Exception:
        pass                      # ← muet : absent, cassé, ou qui lève

    def _trust_of(meta):
        if not isinstance(meta, dict):
            return 0.5            # ← qualification IMPOSSIBLE
        ...
        return 0.5                # ← qualifié SANS champ de confiance

Trois situations distinctes, **un seul nombre : 0.5**. Et 0.5 passe le seuil
(`min_trust=0.2`). Autrement dit : une panne du qualifieur se lisait exactement
comme « contenu de confiance moyenne », et tout entrait en base sans que rien
ne le signale. Le garde restait vert pendant que son capteur était mort.

C'est le corollaire de la constitution, dans sa variante ouvrante : quand une
couche expose l'état d'un canal, elle expose aussi **pourquoi** le signal
manque. Un score absent traité comme un score NUL fait conclure à tort à la
non-pertinence ; traité comme un score MOYEN, il ouvre la porte. Les deux sont
la même faute — le défaut est de fabriquer un nombre là où il n'y a pas de
mesure.

⚠️ CE QUI NE CHANGE PAS, volontairement : le comportement d'ingestion. Le gate
reste **fail-open** quand la qualification est impossible — le durcir d'un coup
bloquerait l'ancrage entier sur une dépendance absente. Ce qui change, c'est
qu'un fail-open est désormais **NOMMÉ et TRACÉ** au lieu d'être déguisé en 0.5.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent.parent
for _d in (RACINE, RACINE / "app", RACINE / "tools"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

_QUALIFY = "nokido_agent.app.forge_rag_qualify"
_TRACE = "nokido_agent.tools.forge_alignment_trace"
_TEXTE = "une lecon technique assez longue pour passer le seuil de trivialite"


def _mod():
    import forge_memory_gate  # type: ignore

    return forge_memory_gate


def _faux_qualifieur(monkeypatch, fabrique):
    """Remplace le qualifieur par un module factice. `fabrique` peut lever."""
    m = types.ModuleType(_QUALIFY)
    m.qualify_for_ingest = fabrique  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, _QUALIFY, m)


def _qualifieur_absent(monkeypatch):
    """Un module SANS l'attribut : l'import echoue, comme en production quand
    la dependance n'est pas installee."""
    monkeypatch.setitem(sys.modules, _QUALIFY, types.ModuleType(_QUALIFY))


# ── 1. L'état existe et il est nommé ──────────────────────────────────────────

def test_le_verdict_porte_un_etat_de_confiance_nomme(monkeypatch):
    _faux_qualifieur(monkeypatch, lambda **k: {"trust_weight": 0.8})
    r = _mod().should_ingest(_TEXTE, source="docs/interne.md")
    assert "etat_confiance" in r, (
        "le verdict ne rend qu'un nombre : rien ne distingue une confiance "
        "MESUREE d'une confiance FABRIQUEE faute de mesure"
    )
    assert r["etat_confiance"] == "QUALIFIE"
    assert r["trust"] == 0.8


# ── 2. Les trois causes de « 0.5 » sont désormais distinctes ──────────────────

def test_un_qualifieur_indisponible_ne_rend_pas_une_confiance_moyenne(monkeypatch):
    """Le cœur de V1. Une dépendance absente donnait 0.5, donc `ok=True`, donc
    une ingestion sans aucun contrôle de qualité — silencieusement."""
    _qualifieur_absent(monkeypatch)
    r = _mod().should_ingest(_TEXTE, source="docs/interne.md")
    assert r["etat_confiance"] == "NON_QUALIFIABLE", (
        "une qualification IMPOSSIBLE est rendue comme « %s » : la panne du "
        "capteur se lit comme une mesure" % r.get("etat_confiance")
    )
    assert r["trust"] is None, (
        "un nombre a ete fabrique (%s) la ou il n'y a aucune mesure" % r["trust"]
    )
    assert r["ok"] is True, "le fail-open est volontaire et ne doit pas changer"
    assert "NON_QUALIFIABLE" in r["reason"] or "qualifi" in r["reason"].lower()


def test_un_qualifieur_qui_leve_est_distingue_d_un_qualifieur_absent(monkeypatch):
    def _casse(**k):
        raise RuntimeError("qualifieur en panne")

    _faux_qualifieur(monkeypatch, _casse)
    r = _mod().should_ingest(_TEXTE, source="docs/interne.md")
    assert r["etat_confiance"] == "NON_QUALIFIABLE"
    assert r["trust"] is None
    assert "RuntimeError" in (r.get("motif_non_qualifiable") or ""), (
        "le motif de l'echec n'est pas conserve : impossible de distinguer une "
        "dependance absente d'un qualifieur qui plante"
    )


def test_un_meta_sans_champ_de_confiance_est_nomme_tel_quel(monkeypatch):
    """Le qualifieur a répondu, mais aucun champ de confiance : ce n'est ni une
    panne, ni une mesure. C'est un troisième état."""
    _faux_qualifieur(monkeypatch, lambda **k: {"domaine": "code"})
    r = _mod().should_ingest(_TEXTE, source="docs/interne.md")
    assert r["etat_confiance"] == "SANS_CHAMP_DE_CONFIANCE", r
    assert r["trust"] is None


# ── 3. Les états déjà sûrs restent intacts ────────────────────────────────────

def test_une_source_faible_reste_plafonnee_et_le_DIT(monkeypatch):
    _faux_qualifieur(monkeypatch, lambda **k: {"trust_weight": 0.9})
    r = _mod().should_ingest(_TEXTE, source="https://reddit.com/r/x/abc")
    assert r["etat_confiance"] == "SOURCE_PLAFONNEE", r
    assert r["trust"] == 0.3, "le plafond de source faible a saute"


def test_le_bruit_n_invente_aucune_confiance(monkeypatch):
    r = _mod().should_ingest("todo", source="docs/interne.md")
    assert r["ok"] is False
    assert r["etat_confiance"] == "BRUIT", r
    assert r["trust"] is None, (
        "le rejet pour bruit rendait trust=0.0 — un zero qui ressemble a une "
        "confiance mesuree nulle, alors que rien n'a ete mesure"
    )


def test_la_frontiere_du_garde_de_bruit_est_fixee(monkeypatch):
    """Trouvé par le cliquet de mutation, pas par relecture : muter `<` en `<=`
    sur `len(t) < _MIN_CHARS` survivait — aucun test ne tenait la frontière.

    Un contenu de longueur EXACTEMENT `_MIN_CHARS` est accepté, un de
    `_MIN_CHARS - 1` est du bruit. Sans ces deux points, le seuil peut glisser
    d'un caractère sans que rien ne s'allume — et un seuil de rejet qui glisse
    écarte du contenu réel en le classant « trivial »."""
    m = _mod()
    _faux_qualifieur(monkeypatch, lambda **k: {"trust_weight": 0.9})
    borne = m._MIN_CHARS

    juste_assez = "a" * borne
    r = m.should_ingest(juste_assez, source="docs/interne.md")
    assert r["ok"] is True, (
        "un contenu de longueur EXACTEMENT _MIN_CHARS (%d) est rejete comme "
        "bruit : le seuil a glisse d'un caractere (%s)" % (borne, r["reason"])
    )
    assert r["etat_confiance"] != "BRUIT", r

    un_de_moins = "a" * (borne - 1)
    r2 = m.should_ingest(un_de_moins, source="docs/interne.md")
    assert r2["ok"] is False and r2["etat_confiance"] == "BRUIT", (
        "un contenu sous le seuil n'est plus vu comme du bruit : le garde de "
        "trivialite ne mord plus (%s)" % r2
    )


def test_un_trust_sous_le_seuil_reste_un_refus_mesure(monkeypatch):
    _faux_qualifieur(monkeypatch, lambda **k: {"trust_weight": 0.05})
    r = _mod().should_ingest(_TEXTE, source="docs/interne.md")
    assert r["ok"] is False
    assert r["etat_confiance"] == "QUALIFIE", (
        "un refus sur mesure reelle ne doit pas etre confondu avec une absence "
        "de mesure : %s" % r
    )
    assert r["trust"] == 0.05


def test_le_selftest_du_module_survit_au_nouveau_contrat():
    """Le point d'entrée, pas seulement la fonction. `selftest()` formatait
    `trust` en `%.2f` : dès que la confiance a pu valoir None, il levait un
    `TypeError` — la fonction verte, le programme mort. Défaut jumeau déjà payé
    ici (`check()` vert, `--check` en `NameError`), et attrapé à la mesure."""
    assert _mod().selftest() is True


# ── 4. Le fail-open est TRACÉ, sinon il est invisible ─────────────────────────

def test_une_qualification_impossible_laisse_une_trace(monkeypatch):
    """Un fail-open muet est indistinguable d'un fonctionnement normal. Celui-ci
    doit s'annoncer, sinon le jour où le qualifieur meurt, personne ne le sait."""
    vues = []
    faux = types.ModuleType(_TRACE)
    faux.emit = lambda *a, **k: vues.append(a)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, _TRACE, faux)
    _qualifieur_absent(monkeypatch)

    _mod().should_ingest(_TEXTE, source="docs/interne.md")
    assert vues, (
        "aucune trace emise : une panne du qualifieur passe inapercue, et le "
        "gate reste vert en n'ayant rien controle"
    )
    assert any("indetermine" in " ".join(str(x) for x in a) for a in vues), vues
