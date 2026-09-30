"""NR — le contrat agent_id -> key_id -> public_key -> generation -> status.

ETAPE 1 du chantier arrete par l'owner le 2026-09-20 : « figer le contrat »
AVANT de provisionner la moindre cle TPM. L'ordre compte -- creer des cles sans
machine d'etat de revocation, c'est fabriquer un point de non-retour.

CE QUI EXISTE DEJA, et qu'on ne refait pas :
    app/forge_dpop.thumbprint(jwk)                 RFC 7638
    forge_integrity.decode(..., dpop_jkt=...)      RFC 9449, verifie cnf.jkt
    forge_cert_binding.thumbprint(cert_der)        RFC 8705
    forge_persona_tpm.nom_cle_agent / sign_as      ECDSA P-256, non exportable
    forge_integrity.revoke(agent_id, min_seq)      revocation AGENT + TOKEN

CE QUI MANQUE, mesure sur `forge_integrity.revoke` :
    self._revoked_seqs[agent_id] = ...   EN MEMOIRE -> perdu au redemarrage
    deux niveaux (agent, token), PAS de niveau CLE
    ni `generation`, ni `status`, ni `public_key`

MESURE DU 2026-09-21 -- la dette n'est plus deduite du code, elle est REPRODUITE
sur le chemin reel (meme secret, manager neuf = ce que produit tout redemarrage,
`get_manager` etant un `global _manager`) :

    verify AVANT revocation       True
    verify APRES revocation       False   (« Token revoque : emis a X <= revoc X »)
    ---- REDEMARRAGE ----
    revoke_status                 {}
    MEME jeton revoque            True    <-- il repasse, tout son TTL restant

Et l'asymetrie est le vrai defaut : `app/web_hub/jti_cache.py` PERSISTE deja ses
revocations (SQLite, write-through, preload au boot) quand `revoke(agent)` ne
persiste rien. Le patron existe dans le corps ; il n'est pas branche ici.

D'ou ce ledger. Il ne porte AUCUNE crypto : la signature reste au TPM, la
verification a `forge_integrity`. Il tient l'ETAT.

LES INVARIANTS QUE CE NR VERROUILLE
===================================

1. REVOQUER N EST PAS DETRUIRE. Une revocation ordinaire laisse la cle en place
   et l'historique intact -- « revoquer logiquement d'abord, detruire
   physiquement seulement lors d'un retrait definitif ». Sans cela, chaque
   rotation ferait perdre l'identite cryptographique passee et toute lecture
   forensique deviendrait impossible.

2. TROIS REVOCATIONS DISTINCTES : token / cle / agent. Les confondre, c'est soit
   sur-reagir (tuer l'agent pour un token fuite), soit sous-reagir (revoquer un
   token quand c'est la cle qui est compromise).

3. LA ROTATION NE FAIT PAS DE TROU. Pendant la transition, DEUX generations sont
   acceptees ; l'ancienne n'est revoquee qu'APRES validation de la nouvelle.
   Une rotation qui coupe l'identite est une panne, pas une rotation.

4. LE `jkt` EST DERIVE, JAMAIS FOURNI. Un appelant qui transmet l'empreinte de
   sa propre cle peut MENTIR dessus. Elle se recalcule depuis la cle publique
   par `forge_dpop.thumbprint` (RFC 7638), la primitive que `cnf.jkt` utilise
   deja -- une seconde convention d'empreinte divergerait en silence.

   Les trois maillons sont DISTINCTS et aucun ne remplace l'autre :
       agent_id     qui est cense posseder cette cle
       generation   quelle version de la cle de cette identite
       jkt          quelle cle a effectivement signe

5. FAIL-CLOSED, ET IL SE DIT ICI PARCE QU'IL S'HERITE MAL. Le patron de
   persistance reutilisable (`jti_cache`) est explicitement FAIL-OPEN : « une
   panne persister ne fait JAMAIS echouer revoke() ». Defendable pour de
   l'anti-rejeu ; INTERDIT ici. Un ledger de cles illisible doit REFUSER, sinon
   on rejoue ce qui vient d'etre mesure : revocation posee, etat non restaure,
   cle implicitement utilisable.

6. LE LEDGER NE DECIDE JAMAIS DU RING. Une cle valide prouve « celui qui signe
   possede la cle de cette identite », JAMAIS « donc il est ring 1 ». C'est
   exactement le defaut mesure ce soir sur LAFORGE_CLI/NOKIDO_CLI, ou un alias
   partage pouvait rendre le ring 1 a un appelant de ring 4. Le ring reste au
   SSoT d'identite ; le ledger n'en porte pas.

PORTEE DITE : ce NR ne signe rien, ne cree aucune cle TPM et ne juge aucun
token. Il garde le CONTRAT et la machine d'etat.

CE QU'IL NE COUVRE PAS, et qui reste entier : la separation des DEUX familles de
jetons. `dpop_jwk` est optionnel a l'emission (`bound: bool(dpop_jwk)`), donc un
jeton sans `cnf.jkt` existe et reste un bearer rejouable. Le futur verificateur
doit EXIGER `cnf.jkt` sur le chemin lie au lieu de chercher une preuve
eventuelle sur un bearer -- sinon le TPM devient decoratif. Cela se verrouille
cote verificateur, pas ici.
"""
from __future__ import annotations

import pytest


def _mod():
    for nom in ("nokido_agent.app.forge_agent_keys", "app.forge_agent_keys",
                "forge_agent_keys"):
        try:
            m = __import__(nom, fromlist=["enregistrer"])
        except Exception:  # noqa: BLE001
            continue
        if hasattr(m, "enregistrer"):
            return m
    # PAS de `skip`. Mesure du 2026-09-21 : ce NR rendait `15 skipped` alors
    # qu'un commit du 2026-09-20 l'annoncait « ROUGE ». Un test skippe ne
    # prouve RIEN et ne tirera JAMAIS -- c'est le faux calme deja paye
    # (« importorskip sur un livrable = faux vert »). Le contrat attendu est
    # un LIVRABLE : son absence doit se voir en rouge, pas se taire en gris.
    # Ce fichier reste hors PURE_TESTS jusqu'a l'implementation du ledger,
    # donc ce rouge ne casse aucune CI -- il rend seulement la dette VISIBLE.
    raise AssertionError(
        "forge_agent_keys ABSENT sous ses trois noms d'import. Le contrat "
        "agent_id -> key_id -> public_key -> generation -> status n'a pas "
        "d'implementation : c'est le niveau CLE de la revocation, mesure "
        "manquant le 2026-09-21 (token = cable et persistant, identite = "
        "existe mais non cablee, cle = inexistant)."
    )


def _jwk(n: int) -> dict:
    """JWK P-256 SYNTHETIQUE, structurellement valide pour RFC 7638.

    Le ledger ne fait AUCUNE crypto : il tient l'etat. Une vraie cle P-256 ne
    prouverait rien de plus ici et laisserait croire que ce NR verifie une
    signature -- ce qu'il ne fait pas, et ne doit pas faire.
    """
    return {"kty": "EC", "crv": "P-256",
            "x": "x" + str(n) * 20, "y": "y" + str(n) * 20}


def _empreinte(jwk: dict) -> str:
    from nokido_agent.app.forge_dpop import thumbprint
    return thumbprint(jwk)


@pytest.fixture(autouse=True)
def _ledger_isole(tmp_path, monkeypatch):
    """Chaque test ecrit dans SON ledger : un NR ne touche pas l'etat reel."""
    m = _mod()
    monkeypatch.setattr(m, "_CHEMIN", tmp_path / "agent_keys.json", raising=False)
    if hasattr(m, "_vider_cache"):
        m._vider_cache()
    yield


# ─────────────────────────────  CONTRAT  ─────────────────────────────

def test_le_contrat_porte_les_SIX_champs():
    m = _mod()
    e = m.enregistrer("CLAUDE", public_key=_jwk(1))
    for champ in ("agent_id", "key_id", "public_key", "generation", "status",
                  "jkt"):
        assert champ in e, f"champ de contrat manquant : {champ} ({e})"
    assert e["status"] == "ACTIVE"
    assert e["generation"] >= 1


def test_le_key_id_vient_du_TPM_pas_d_une_invention():
    """Le nom de cle est celui que `forge_persona_tpm` calcule -- une seconde
    convention divergerait en silence."""
    m = _mod()
    from nokido_agent.app.forge_persona_tpm import nom_cle_agent
    e = m.enregistrer("CLAUDE", public_key=_jwk(1))
    assert e["key_id"] == nom_cle_agent("CLAUDE")


def test_un_agent_NON_DECLARE_n_entre_pas_au_ledger():
    m = _mod()
    with pytest.raises((ValueError, KeyError)):
        m.enregistrer("agt_agt_gemini", public_key=_jwk(1))


def test_le_ledger_ne_porte_AUCUN_ring():
    """Une cle prouve la possession, jamais l'autorisation.

    C'est le defaut LAFORGE_CLI/NOKIDO_CLI transpose : si le ledger portait un
    ring, posseder une cle vaudrait privilege.
    """
    m = _mod()
    e = m.enregistrer("CLAUDE", public_key=_jwk(1))
    interdits = [k for k in e if "ring" in k.lower() or "scope" in k.lower()
                 or "lane" in k.lower()]
    assert not interdits, f"le ledger porte de l'autorisation : {interdits}"


# ─────────────────────────  MACHINE D ETAT  ──────────────────────────

def test_les_etats_sont_les_QUATRE_declares():
    m = _mod()
    assert set(m.ETATS) == {"ACTIVE", "SUSPENDED", "REVOKED", "DESTROYED"}


def test_la_transition_avance_et_ne_RECULE_jamais():
    m = _mod()
    m.enregistrer("CLAUDE", public_key=_jwk(1))
    assert m.transition("CLAUDE", "SUSPENDED", par="SUPERVISOR", motif="NR")["status"] == "SUSPENDED"
    assert m.transition("CLAUDE", "REVOKED", par="SUPERVISOR", motif="NR")["status"] == "REVOKED"
    with pytest.raises(ValueError):
        m.transition("CLAUDE", "ACTIVE", par="SUPERVISOR", motif="retour arriere")


def test_chaque_transition_porte_sa_PROVENANCE():
    """Un etat sans auteur ni motif ne se relit pas six mois plus tard."""
    m = _mod()
    m.enregistrer("CLAUDE", public_key=_jwk(1))
    e = m.transition("CLAUDE", "REVOKED", par="SUPERVISOR", motif="cle suspectee")
    assert e.get("revoked_by") == "SUPERVISOR"
    assert e.get("reason")
    assert e.get("revoked_at")


def test_REVOQUER_N_EST_PAS_DETRUIRE():
    """LE COEUR. La cle reste au ledger, l'historique reste lisible."""
    m = _mod()
    m.enregistrer("CLAUDE", public_key=_jwk(7))
    m.transition("CLAUDE", "REVOKED", par="SUPERVISOR", motif="NR")
    hist = m.historique("CLAUDE")
    assert hist, "la revocation a efface l'historique"
    assert any(x["public_key"] == _jwk(7) for x in hist), (
        "la cle publique revoquee a disparu : aucune lecture forensique possible")


# ─────────────────────────────  ROTATION  ────────────────────────────

def test_la_rotation_INCREMENTE_la_generation():
    m = _mod()
    a = m.enregistrer("CLAUDE", public_key=_jwk(7))
    b = m.enregistrer("CLAUDE", public_key=_jwk(8))
    assert b["generation"] == a["generation"] + 1


def test_pendant_la_rotation_DEUX_generations_sont_acceptees():
    """Une rotation qui coupe l'identite est une panne, pas une rotation."""
    m = _mod()
    m.enregistrer("CLAUDE", public_key=_jwk(7))
    m.enregistrer("CLAUDE", public_key=_jwk(8))
    acceptees = m.cles_acceptees("CLAUDE")
    assert len(acceptees) == 2, f"transition sans recouvrement : {acceptees}"


def test_apres_revocation_de_l_ANCIENNE_une_seule_reste():
    m = _mod()
    a = m.enregistrer("CLAUDE", public_key=_jwk(7))
    m.enregistrer("CLAUDE", public_key=_jwk(8))
    m.transition("CLAUDE", "REVOKED", generation=a["generation"],
                 par="SUPERVISOR", motif="rotation terminee")
    restantes = m.cles_acceptees("CLAUDE")
    assert [x["public_key"] for x in restantes] == [_jwk(8)]


# ──────────────────────  TROIS REVOCATIONS  ──────────────────────────

def test_revoquer_UNE_CLE_ne_revoque_pas_l_AGENT():
    m = _mod()
    a = m.enregistrer("CLAUDE", public_key=_jwk(7))
    m.enregistrer("CLAUDE", public_key=_jwk(8))
    m.transition("CLAUDE", "REVOKED", generation=a["generation"],
                 par="SUPERVISOR", motif="cle compromise")
    assert m.agent_actif("CLAUDE") is True
    assert m.cles_acceptees("CLAUDE"), "l'agent n'a plus aucune cle utilisable"


def test_revoquer_l_AGENT_rend_TOUTES_ses_cles_inutilisables():
    """Le niveau le plus fort : plus aucun nouveau token, toutes cles refusees."""
    m = _mod()
    m.enregistrer("CLAUDE", public_key=_jwk(7))
    m.enregistrer("CLAUDE", public_key=_jwk(8))
    m.revoquer_agent("CLAUDE", par="SUPERVISOR", motif="compromission")
    assert m.agent_actif("CLAUDE") is False
    assert m.cles_acceptees("CLAUDE") == []
    assert m.historique("CLAUDE"), "l'historique forensique a ete efface"


def test_le_ledger_SURVIT_au_redemarrage():
    """`forge_integrity.revoke` ne vit qu'en memoire : une revocation disparait
    au restart. Ce ledger doit persister, sinon il ne revoque rien."""
    m = _mod()
    m.enregistrer("CLAUDE", public_key=_jwk(7))
    m.revoquer_agent("CLAUDE", par="SUPERVISOR", motif="NR")
    if hasattr(m, "_vider_cache"):
        m._vider_cache()
    assert m.agent_actif("CLAUDE") is False, "la revocation n'a pas survecu"


def test_le_ledger_ne_CASSE_JAMAIS_sur_un_etat_illisible(monkeypatch):
    """Un ledger corrompu ne doit pas ouvrir les vannes : fail-CLOSED.

    C'est l'inverse du choix fait pour le protocole M2M (fail-open, ne pas
    couper la communication) -- ici, un doute doit REFUSER.
    """
    m = _mod()
    m._CHEMIN.parent.mkdir(parents=True, exist_ok=True)
    m._CHEMIN.write_text("{ pas du json", encoding="utf-8")
    if hasattr(m, "_vider_cache"):
        m._vider_cache()
    assert m.cles_acceptees("CLAUDE") == []
    assert m.agent_actif("CLAUDE") is False


# ──────────────────────  LE MAILLON `jkt`  ───────────────────────────

def test_le_jkt_est_DERIVE_de_la_cle_et_jamais_accepte_de_l_appelant():
    """Accepter un `jkt` fourni, c'est accepter qu'un appelant MENTE sur
    l'empreinte de sa propre cle. Refuser le parametre est aussi valable que
    l'ignorer -- ce qui est interdit, c'est de le CROIRE."""
    m = _mod()
    jwk = _jwk(7)
    try:
        e = m.enregistrer("CLAUDE", public_key=jwk, jkt="empreinte-mensongere")
    except TypeError:
        e = m.enregistrer("CLAUDE", public_key=jwk)
    assert e["jkt"] == _empreinte(jwk), (
        "le ledger a retenu une empreinte qu'il n'a pas calculee")


def test_le_statut_se_consulte_PAR_JKT_sans_connaitre_l_agent():
    """Le verificateur derive le `jkt` du jeton, pas l'identite. S'il devait
    deja savoir de quel agent il s'agit, le ledger ne servirait a rien : c'est
    precisement le maillon que la chasse du 2026-09-21 a trouve manquant."""
    m = _mod()
    jwk = _jwk(7)
    m.enregistrer("CLAUDE", public_key=jwk)
    assert m.statut_de_jkt(_empreinte(jwk)) == "ACTIVE"


def test_un_jkt_INCONNU_n_est_JAMAIS_actif():
    """Liste BLANCHE : n'est utilisable que ce qui est PROUVE enregistre. Une
    liste noire laisserait toute empreinte inattendue tomber du cote sain."""
    m = _mod()
    m.enregistrer("CLAUDE", public_key=_jwk(7))
    assert m.statut_de_jkt(_empreinte(_jwk(99))) != "ACTIVE"


def test_le_ledger_REFUSE_une_JWK_qui_porte_sa_composante_PRIVEE():
    """`d` est la composante privee d'une JWK EC. Un ledger qui l'accepte
    devient un magasin de secrets -- et il est lu par le RAG. La contrainte
    owner est explicite : jamais la cle privee en cle primaire, en valeur de
    registre ni en donnee persistee."""
    m = _mod()
    jwk = dict(_jwk(7))
    jwk["d"] = "composante-privee-qui-ne-doit-jamais-etre-persistee"
    with pytest.raises(ValueError):
        m.enregistrer("CLAUDE", public_key=jwk)


# ─────────────────  LES QUATRE SCENARIOS ADVERSARIAUX  ────────────────
# Arretes par l'owner le 2026-09-21. Ils portent sur la CLE, pas sur le jeton :
# c'est le niveau que `forge_integrity.revoke` ne modelise pas.

def test_adversarial_1_K0_ACTIVE_est_acceptee():
    m = _mod()
    k0 = _jwk(0)
    m.enregistrer("CLAUDE", public_key=k0)
    assert m.statut_de_jkt(_empreinte(k0)) == "ACTIVE"


def test_adversarial_2_K0_REVOQUEE_refuse_meme_un_artefact_NEUF():
    """LE COEUR DU TROU MESURE. Une signature K0 reste cryptographiquement
    valide apres compromission : seul un etat consultable peut la refuser.
    Sans ce test, `cnf.jkt` prouverait « cette preuve correspond a cette cle »
    sans jamais dire « cette cle est encore autorisee »."""
    m = _mod()
    k0 = _jwk(0)
    a = m.enregistrer("CLAUDE", public_key=k0)
    m.transition("CLAUDE", "REVOKED", generation=a["generation"],
                 par="SUPERVISOR", motif="cle compromise")
    assert m.statut_de_jkt(_empreinte(k0)) == "REVOKED"
    assert _empreinte(k0) not in [x["jkt"] for x in m.cles_acceptees("CLAUDE")]


def test_adversarial_3_apres_rotation_le_sort_de_K0_est_EXPLICITE():
    """Une rotation ne laisse jamais une generation dans un etat implicite.
    `REPLACED` n'est volontairement PAS un etat separe : le remplacement se lit
    a la GENERATION, et ajouter un etat pour la meme chose ferait deux
    modelisations concurrentes du meme fait."""
    m = _mod()
    k0, k1 = _jwk(0), _jwk(1)
    m.enregistrer("CLAUDE", public_key=k0)
    m.enregistrer("CLAUDE", public_key=k1)
    statut = m.statut_de_jkt(_empreinte(k0))
    assert statut in m.ETATS, f"sort de K0 non nomme : {statut!r}"


def test_adversarial_4_ledger_ILLISIBLE_refuse_par_JKT_aussi(monkeypatch):
    """Le chemin `jkt` doit etre fail-closed comme le chemin agent. C'est la
    divergence a ne pas heriter : le patron de persistance reutilisable
    (`jti_cache`) est fail-open par contrat ecrit."""
    m = _mod()
    k0 = _jwk(0)
    m.enregistrer("CLAUDE", public_key=k0)
    m._CHEMIN.write_text("{ pas du json", encoding="utf-8")
    if hasattr(m, "_vider_cache"):
        m._vider_cache()
    assert m.statut_de_jkt(_empreinte(k0)) != "ACTIVE"


def test_la_revocation_par_JKT_SURVIT_au_redemarrage():
    """C'est CE test qui transforme « fonctionne en memoire » en propriete de
    securite persistante -- exactement ce que `forge_integrity.revoke` n'a pas,
    mesure le 2026-09-21 : revoke, restart, le jeton revoque repasse."""
    m = _mod()
    k0 = _jwk(0)
    a = m.enregistrer("CLAUDE", public_key=k0)
    m.transition("CLAUDE", "REVOKED", generation=a["generation"],
                 par="SUPERVISOR", motif="cle compromise")
    if hasattr(m, "_vider_cache"):
        m._vider_cache()
    assert m.statut_de_jkt(_empreinte(k0)) == "REVOKED", (
        "la revocation de CLE n'a pas survecu au redemarrage")
