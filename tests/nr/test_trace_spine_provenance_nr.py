"""Non-regression : le contrat de provenance des traces.

CE QUE CES TESTS PROTEGENT
==========================
Le 2026-08-23, une sonde a conclu « le bus n'annonce pas les defaillances
d'organe » sur des traits decales de DEUX HEURES par rapport a leurs etiquettes :
`event_bus_replay` ecrit de l'UTC en ISO naif, `network_log` ecrit du LOCAL en ISO
naif, et rien ne les distingue a la lecture. Rejouee avec le repere corrige, la
meme sonde sur les memes donnees est passee d'un gain de 1,00 a 1,23.

Le negatif avait ete rapporte comme un resultat. C'est ce defaut-la que ces tests
empechent de revenir, et il ne se voit pas a l'oeil nu : un repere faux ne leve
aucune erreur, il decale simplement tout d'un multiple d'une heure.

Tests PURS : aucune source reelle, aucun service, aucune base.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (RACINE, RACINE / "app", RACINE / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

S = pytest.importorskip("forge_trace_spine")


def test_une_horloge_naive_sans_repere_est_REFUSEE_a_la_construction():
    """Le coeur du contrat. Un producteur ISO naif sans repere declare est
    ambigu de 3600 ou 7200 s, et l'ambiguite ne se voit jamais a l'usage."""
    with pytest.raises(ValueError) as e:
        S.Provenance("x", "organe", "iso_naif", "ts")
    assert "repere" in str(e.value).lower()
    with pytest.raises(ValueError):
        S.Provenance("x", "organe", "sql_naif", "ts", repere="paris")


def test_un_horodatage_naif_lu_en_utc_ou_en_local_differe_de_l_offset():
    """LE BUG DU 23-08, encode. Meme chaine, deux contrats, deux instants.

    Si ce test tombe parce que les deux valeurs deviennent egales, quelqu'un a
    fait deviner le repere au lieu de le declarer."""
    brut = "2026-08-23T17:32:10"
    p_utc = S.Provenance("a", "o", "iso_naif", "ts", repere="utc")
    p_loc = S.Provenance("b", "o", "iso_naif", "ts", repere="local")
    t_utc, _ = S.normaliser_ts(brut, p_utc)
    t_loc, _ = S.normaliser_ts(brut, p_loc)
    attendu = datetime.fromisoformat(brut).astimezone().utcoffset().total_seconds()
    assert t_utc is not None and t_loc is not None
    assert abs((t_utc - t_loc) - attendu) < 1.0, (
        "l'ecart entre lecture UTC et lecture LOCALE doit valoir exactement "
        "l'offset du fuseau ; obtenu %.0f s pour un offset de %.0f s"
        % (t_utc - t_loc, attendu))


def test_un_horodatage_qui_PORTE_son_fuseau_ignore_le_repere_declare():
    p = S.Provenance("c", "o", "iso_tz", "ts")
    t, _ = S.normaliser_ts("2026-08-23T17:32:10+00:00", p)
    assert abs(t - datetime(2026, 8, 23, 17, 32, 10, tzinfo=timezone.utc).timestamp()) < 1.0


def test_epoch_ms_est_ramene_en_secondes():
    p = S.Provenance("d", "o", "epoch_ms", "ts")
    t, _ = S.normaliser_ts(1787506459206, p)
    assert 1787506459.0 < t < 1787506460.0


def test_un_producteur_NON_DECLARE_est_refuse():
    """Refus par defaut. Ingerer au jugement reviendrait a inventer une provenance."""
    evt, raison = S.ingerer("producteur_qui_n_existe_pas", {"ts": 1787506459.0})
    assert evt is None
    assert "non declare" in raison


def test_un_evenement_sans_horodatage_est_refuse_avec_sa_raison():
    evt, raison = S.ingerer("network_log", {"method": "tools/call"})
    assert evt is None
    assert raison, "un refus sans raison est indistinguable d'une panne"


def test_l_evenement_canonique_reste_AUDITABLE():
    """La normalisation ne doit pas effacer ce que le producteur avait ecrit :
    sans `ts_source` et `repere_source`, une erreur de repere devient indetectable
    une fois la trace centralisee."""
    evt, _ = S.ingerer("network_log", {"ts": "2026-08-23T19:32:10", "method": "tools/call"})
    assert evt is not None
    for cle in ("ts", "ts_source", "horloge_source", "repere_source", "producteur", "organe"):
        assert cle in evt, "champ d'audit manquant : %s" % cle
    assert evt["ts_source"] == "2026-08-23T19:32:10"
    assert evt["repere_source"] == "local"


def test_verifier_DETECTE_un_repere_inverse():
    """Un repere faux produit un ecart proche d'un multiple de 3600 s. C'est le
    seul moment ou l'erreur est visible ; apres, elle est gravee."""
    import time as _t
    maintenant = datetime.fromtimestamp(_t.time(), timezone.utc)
    naif_utc = maintenant.replace(tzinfo=None).isoformat()
    bon, _ = S.verifier(S.Provenance("e", "o", "iso_naif", "ts", repere="utc"), naif_utc)
    assert bon, "le repere JUSTE doit etre confirme"
    mauvais, raison = S.verifier(S.Provenance("f", "o", "iso_naif", "ts", repere="local"), naif_utc)
    if datetime.now().astimezone().utcoffset().total_seconds() != 0:
        assert not mauvais, "le repere INVERSE doit etre detecte"
        assert "repere" in raison.lower()


def test_l_ecriture_qui_echoue_le_DIT():
    """Une trace perdue ne se distingue pas d'un evenement qui n'a pas eu lieu."""
    assert S.ecrire({"producteur": "x"}, Path("Z:/inexistant/interdit/spine.jsonl")) is False


def test_l_ecriture_qui_reussit_ajoute_une_ligne(tmp_path):
    p = tmp_path / "spine.jsonl"
    assert S.ecrire({"producteur": "x", "ts": 1.0}, p) is True
    assert S.ecrire({"producteur": "y", "ts": 2.0}, p) is True
    assert len(p.read_text(encoding="utf-8").strip().splitlines()) == 2


def test_une_afference_neuve_demarre_au_PRESENT(tmp_path):
    """Un nerf transporte le present, pas l'archive. Sans cette regle, le premier
    tick d'un raccordement ingererait des mois d'historique et noierait le relais."""
    f = tmp_path / "flux.jsonl"
    f.write_text("\n".join('{"ts": %d}' % t for t in range(1000, 1050)) + "\n", encoding="utf-8")
    pos: dict = {}
    lignes, note = S.afferent_jsonl("hub_blackbox", f, pos)
    assert lignes == [], "un raccordement ne doit rien rejouer"
    assert "present" in note
    assert pos, "la position doit etre memorisee des le raccordement"


def test_une_afference_transporte_ce_qui_a_ete_AJOUTE(tmp_path):
    f = tmp_path / "flux.jsonl"
    f.write_text('{"ts": 1}\n', encoding="utf-8")
    pos: dict = {}
    S.afferent_jsonl("hub_blackbox", f, pos)
    with open(f, "a", encoding="utf-8") as fh:
        fh.write('{"ts": 2}\n{"ts": 3}\n')
    lignes, _ = S.afferent_jsonl("hub_blackbox", f, pos)
    assert [l["ts"] for l in lignes] == [2, 3]


def test_un_flux_qui_RETRECIT_ne_rejoue_pas(tmp_path):
    """Rotation ou troncature. Rejouer produirait un pic fantome de milliers
    d'evenements, pire qu'un trou assume — et il serait indiscernable d'une rafale."""
    f = tmp_path / "flux.jsonl"
    f.write_text("\n".join('{"ts": %d}' % t for t in range(200)) + "\n", encoding="utf-8")
    pos: dict = {}
    S.afferent_jsonl("hub_blackbox", f, pos)
    with open(f, "a", encoding="utf-8") as fh:
        fh.write('{"ts": 999}\n')
    S.afferent_jsonl("hub_blackbox", f, pos)
    f.write_text('{"ts": 1}\n', encoding="utf-8")          # rotation
    lignes, note = S.afferent_jsonl("hub_blackbox", f, pos)
    assert lignes == []
    assert "tronque" in note or "tourne" in note


def test_toute_afference_pointe_un_producteur_SOUS_CONTRAT():
    """Un nerf qui aboutirait sans provenance declaree serait refuse a l'ingestion :
    autant ne pas le cabler."""
    for producteur in S.AFFERENCES:
        assert producteur in S.REGISTRE, "afference hors contrat : %s" % producteur


def test_toute_provenance_declaree_est_coherente():
    """Garde de registre : une entree naive sans repere aurait explose a la
    construction, mais on verifie qu'aucune n'a ete ajoutee autrement."""
    assert S.REGISTRE, "registre vide = contrat inexistant"
    for nom, p in S.REGISTRE.items():
        assert p.horloge in S.FORMATS, "%s : horloge %r hors contrat" % (nom, p.horloge)
        if p.horloge in S.FORMATS_SANS_REPERE:
            assert p.repere in S.REPERES, "%s : naif sans repere declare" % nom


# ===========================================================================
# LE MEME DEFAUT, SUR L'AUTRE AXE : L'IDENTITE (mesure 2026-09-16)
#
# Ce fichier protege deja les HORLOGES : `horloge` dit le format, `repere` dit
# la semantique, et sans cette paire deux ISO naifs aux reperes opposes se
# fusionnaient silencieusement. L'identite n'avait PAS son equivalent --
# `cles_causales` n'etait qu'un TUPLE DE NOMS.
#
# MESURE QUI L'IMPOSE, sur donnees reelles :
#   corr_id        (bus)     taille max 2, duree mediane 4 ms, 94,9 % inter-agent
#                            -> APPARIEMENT requete/reponse
#   correlation_id (postal)  99,7 % de SINGLETONS, duree jusqu'a 9,7 jours
#                            -> IDENTITE DE MESSAGE
#   session_id     (event_log) 362 groupes d'UNE ligne + UN groupe de 21 426
#                            -> session DEGENERE, inexploitable en l'etat
#   sequence_id    37 761 distincts sur 42 027 -> quasi unique, n'ordonne rien
#   prev_hash      chainage 20 245/20 245 = 100 % -> INTEGRITE, pas causalite
#   parent_id      ne relie AUCUN groupe a un autre -> INDETERMINE
#
# Sur six cles, AUCUNE n'est une cle causale. Trois portent un nom qui MENT sur
# leur fonction. Les unifier au motif que « corr_id » et « correlation_id » se
# ressemblent aurait melange des paires de 4 ms avec des identifiants uniques
# etales sur dix jours. D'ou la regle que ces tests rendent EXECUTABLE :
#
#     le NOM d'un champ ne dit RIEN de sa semantique.
#
# ===========================================================================


def test_le_vocabulaire_des_relations_est_FERME():
    assert S.RELATIONS, "aucun vocabulaire de relations : tout nom serait accepte"
    for attendu in ("correlation", "message_identity", "integrity_predecessor"):
        assert attendu in S.RELATIONS, "relation %r absente du vocabulaire" % attendu
    with pytest.raises(ValueError):
        S.Relation(champ="x", relation="cle_causale_magique", portee="message")


def test_une_portee_inconnue_est_REFUSEE():
    with pytest.raises(ValueError):
        S.Relation(champ="x", relation="correlation", portee="un_peu_partout")


def test_deux_relations_de_PORTEES_differentes_ne_se_joignent_pas():
    a = S.Relation(champ="corr_id", relation="correlation", portee="echange",
                   etat="OBSERVE", mesure="taille max 2, mediane 4 ms")
    b = S.Relation(champ="session_id", relation="correlation", portee="session",
                   etat="OBSERVE", mesure="un groupe de 21426, max 176 j")
    ok, motif = S.compatibles(a, b)
    assert ok is False, (
        "deux correlations de portees differentes sont declarees joignables : "
        "c'est l'erreur des horloges, transposee a l'identite"
    )
    assert "portee" in motif.lower()


def test_deux_relations_de_ROLES_differents_ne_se_joignent_pas():
    a = S.Relation(champ="corr_id", relation="correlation", portee="echange",
                   etat="OBSERVE", mesure="appariement requete/reponse")
    b = S.Relation(champ="correlation_id", relation="message_identity",
                   portee="message", etat="OBSERVE", mesure="99,7 % de singletons")
    ok, motif = S.compatibles(a, b)
    assert ok is False, (
        "corr_id et correlation_id sont declares joignables sur la foi de leurs "
        "noms : 4 ms contre 9,7 jours, appariement contre identite de message"
    )


def test_deux_relations_de_MEME_role_et_MEME_portee_se_joignent():
    a = S.Relation(champ="corr_id", relation="correlation", portee="echange",
                   etat="OBSERVE", mesure="m")
    b = S.Relation(champ="req_id", relation="correlation", portee="echange",
                   etat="OBSERVE", mesure="m")
    ok, _motif = S.compatibles(a, b)
    assert ok is True, "le contrat interdit TOUT, donc il ne sert a rien"


def test_une_relation_NON_OBSERVEE_ne_se_joint_a_rien():
    a = S.Relation(champ="corr_id", relation="correlation", portee="echange",
                   etat="OBSERVE", mesure="m")
    b = S.Relation(champ="mystere", relation="correlation", portee="echange")
    assert b.etat == "DECLARE", "l'etat par defaut doit etre le plus faible"
    ok, motif = S.compatibles(a, b)
    assert ok is False, (
        "une relation jamais mesuree est traitee comme une relation prouvee — "
        "DECLARE n'est pas OBSERVE"
    )


def test_une_filiation_d_INTEGRITE_n_est_PAS_une_causalite():
    r = S.Relation(champ="prev_hash", relation="integrity_predecessor",
                   portee="chaine", etat="OBSERVE", mesure="20245/20245 = 100 %")
    assert S.est_causale(r) is False, (
        "prev_hash chaine parfaitement, mais prouver que A precede B ne dit pas "
        "que A a CAUSE B — le confondre fabriquerait de la causalite"
    )


def test_une_cause_REELLE_est_reconnue_comme_telle():
    r = S.Relation(champ="reason", relation="causal_reason", portee="action",
                   etat="OBSERVE", mesure="lifecycle_actions, cause en clair")
    assert S.est_causale(r) is True


def test_les_quatre_etats_du_contrat_existent():
    for e in ("DECLARE", "OBSERVE", "NON_RESOLU", "CONTREDIT"):
        assert e in S.ETATS_RELATION, "etat %r absent : une declaration fausse " \
                                      "ne pourrait pas etre distinguee d'une vraie" % e


def test_les_vitaux_ne_peuvent_JAMAIS_porter_une_relation_causale():
    prov = S.REGISTRE.get("vitals_history")
    assert prov is not None, "producteur des vitaux absent du registre"
    for r in getattr(prov, "relations", ()) or ():
        assert not S.est_causale(r), (
            "une relation causale a ete declaree sur vitals_history : c'est un "
            "ECHANTILLONNEUR PERIODIQUE, declenche par la cadence et non par une "
            "action. Lui attacher une cause FABRIQUE une appartenance."
        )


def test_la_cause_deja_produite_est_enfin_DECLAREE():
    prov = S.REGISTRE.get("lifecycle_actions")
    assert prov is not None
    champs = {r.champ for r in (getattr(prov, "relations", ()) or ())}
    assert "reason" in champs, (
        "lifecycle_actions emet `reason` — une cause en clair — depuis toujours, "
        "et le registre l'ignore : la matiere existe, le contrat ne la declare pas"
    )


def test_une_declaration_CONTREDITE_par_la_source_est_marquee():
    prov = S.REGISTRE.get("network_log")
    assert prov is not None
    etats = {r.champ: r.etat for r in (getattr(prov, "relations", ()) or ())}
    assert etats.get("session_id") == "CONTREDIT", (
        "le registre declare session_id pour network_log, or la base localisee "
        "porte bridge_logs sans cette colonne (l'identifiant y est req_id) : une "
        "declaration jamais confrontee a sa source devient un mensonge"
    )


def test_les_provenances_existantes_restent_valides():
    """Compatibilite ascendante : `cles_causales` ne disparait pas."""
    assert S.REGISTRE, "registre vide"
    for nom, p in S.REGISTRE.items():
        assert isinstance(getattr(p, "cles_causales", ()), tuple), \
            "%s : cles_causales n'est plus un tuple — rupture ascendante" % nom


def test_l_auto_diagnostic_ne_declare_pas_SANS_CLE_un_producteur_qualifie():
    """`sans_cle_causale` lit l'ancien tuple de noms. Laisse seul, il annonce
    `lifecycle_actions` comme depourvu alors qu'il porte trois relations
    OBSERVEES — un auto-diagnostic trompeur est exactement le faux calme que ce
    contrat corrige."""
    e = S.etat_du_contrat()
    assert "sans_relation_qualifiee" in e, (
        "l'etat du contrat ne rend pas la couverture des RELATIONS : il ne peut "
        "donc pas distinguer un producteur qualifie d'un producteur muet"
    )
    assert "lifecycle_actions" not in e["sans_relation_qualifiee"], (
        "lifecycle_actions porte reason/callers/by et sort quand meme comme non "
        "qualifie"
    )
    assert "vitals_history" in e["sans_relation_qualifiee"], (
        "les vitaux DOIVENT y figurer : c'est un echantillonneur, et le contrat "
        "doit le dire plutot que de le masquer"
    )
    assert e.get("relations_contredites"), (
        "la declaration CONTREDITE de network_log n'est pas remontee : une "
        "contradiction tue se comporte comme une declaration valide"
    )


def test_ingerer_hisse_AUSSI_les_champs_des_relations():
    S.declarer(S.Provenance(
        producteur="banc_nr_relations", organe="test", horloge="epoch_s",
        champ_ts="ts",
        relations=(S.Relation(champ="reason", relation="causal_reason",
                              portee="action", etat="OBSERVE", mesure="nr"),)))
    evt, raison = S.ingerer("banc_nr_relations",
                            {"ts": 1789576000.0, "reason": "pression", "bruit": 1})
    assert evt is not None, raison
    assert evt.get("reason") == "pression", (
        "le champ d'une relation declaree reste enfoui dans `data` : il ne sera "
        "pas joignable, donc la declaration n'aura aucun effet"
    )
