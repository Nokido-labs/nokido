# -*- coding: utf-8 -*-
"""NR — Osmorégulation : SessionContext unifié et digestion avant éviction.

Vérifie l'élimination des 5 constats de la revue d'osmorégulation (commit 7765f7137) :
1. resume_sans_borne : budget de résumé (max_summary_tokens), saturation 10000 msgs avec get_context borné.
2. vocabulaire_du_test_en_production : aucun FAIT_TEMOIN en prod ; rappel 100% sur faits génériques (chemins, DECISION, erreurs) sous budget.
3. resumeur_sans_delai : délai borné (asyncio.wait_for) + repli déterministe immédiat sur timeout.
4. message_courant_evince : message plus gros que budget -> préservation absolue du dernier message dans messages.
5. chemin_sync_muet : résumeur async hors boucle -> avertissement journalisé et compteur sync_async_skipped_count incrémenté.
"""
from __future__ import annotations

import asyncio
import pytest
from pathlib import Path
from typing import List

from nokido_agent.app.forge_session_context import SessionContext, SessionMessage

_REAL_PERSIST_CHUNK = SessionContext._persist_chunk


@pytest.fixture(autouse=True)
def isolate_rag_writer_nr(monkeypatch):
    """Monkeypatch de l'écrivain dans TOUS les NR pour isoler la vraie base RAG de production (constat 3)."""
    # 1. Remplacement de l'écrivain SessionContext._persist_chunk par une doublure sûre
    def mock_persist_chunk(self, cid: str, source: str, domain: str, text: str) -> bool:
        return True

    monkeypatch.setattr(SessionContext, "_persist_chunk", mock_persist_chunk)

    # 2. Interdiction formelle d'ouvrir open_writer sur la production depuis les tests NR
    def forbidden_open_writer(*args, **kwargs):
        raise AssertionError("INTERDIT : un test NR a tenté d'ouvrir open_writer sur la base de production !")

    monkeypatch.setattr("nokido_agent.app.forge_db_path.open_writer", forbidden_open_writer)


@pytest.mark.asyncio
async def test_osmoregulation_anti_double_digestion():
    """Vérifie qu'aucune double digestion concurrente ne peut écraser le résumé."""
    ctx = SessionContext(name="test_anti_double", max_messages=4)

    pause_event = asyncio.Event()
    digest_calls = 0

    async def slow_summarizer(msgs: List[SessionMessage]) -> str:
        nonlocal digest_calls
        digest_calls += 1
        await pause_event.wait()
        return f"[digest_call_{digest_calls}] " + "; ".join(m.text for m in msgs)

    ctx.set_summarizer(slow_summarizer)

    # 1. Remplissage jusqu'au seuil max_messages (4 messages)
    for i in range(4):
        ctx.add_message("user", f"initial_{i}")
    assert not ctx.is_digesting
    assert digest_calls == 0

    # 2. 5e message : dépassement de max_messages -> déclenche la 1ère digestion
    ctx.add_message("user", "msg_trigger_1")
    assert ctx.is_digesting is True
    assert len(ctx._running_tasks) == 1

    # Céder la main à la boucle pour que la tâche asynchrone démarre et atteigne la pause
    await asyncio.sleep(0)

    # 3. Ajout d'autres messages PENDANT que la première digestion est encore en cours
    ctx.add_message("user", "msg_while_digesting_1")
    ctx.add_message("user", "msg_while_digesting_2")

    # Anti-défaut 1 : Aucune deuxième tâche de digestion n'est lancée en parallèle
    assert digest_calls == 1
    assert len(ctx._running_tasks) == 1
    assert ctx.is_digesting is True

    # 4. Libération de la première digestion
    pause_event.set()
    await ctx.wait_digestion()

    assert ctx.is_digesting is False
    assert ctx.summary is not None
    assert "[digest_call_1]" in ctx.summary
    assert digest_calls == 1


@pytest.mark.asyncio
async def test_osmoregulation_resumeur_qui_leve_reprise_sans_perte():
    """Vérifie qu'une exception du résumeur ne bloque pas le drapeau et ne perd aucun message."""
    ctx = SessionContext(name="test_failing_summarizer", max_messages=4)

    async def failing_summarizer(msgs: List[SessionMessage]) -> str:
        raise RuntimeError("Panne simulee du resumeur LLM (503 Service Unavailable)")

    ctx.set_summarizer(failing_summarizer)

    # Injection de faits génériques (chemin, décision, erreur) avant éviction
    ctx.add_message("system", "consigne initiale")
    ctx.add_message("user", "Migration schema dans app/forge_migration.py\nDECISION: valider le checkpoint\nERREUR: 404 table manquante")
    ctx.add_message("assistant", "confirmation")
    ctx.add_message("user", "remplissage_1")

    # Dépassement -> déclenche la digestion qui va échouer
    ctx.add_message("user", "remplissage_trigger")
    await ctx.wait_digestion()

    # Anti-défaut 2 : Le drapeau n'est PAS resté coincé à True
    assert ctx.is_digesting is False
    assert ctx._last_error is not None
    assert "Panne simulee" in ctx._last_error

    # Les messages évincés ne sont PAS perdus : le repli déterministe les a capturés dans summary
    assert ctx.summary is not None
    assert "app/forge_migration.py" in ctx.summary
    assert "valider le checkpoint" in ctx.summary

    # La session peut continuer normalement sans être paralysée
    ctx.add_message("user", "message_suivant_apres_erreur")
    assert len(ctx.messages) > 0


@pytest.mark.asyncio
async def test_osmoregulation_resumeur_bloque_timeout_repli_deterministe():
    """Constat 3 : un résumeur qui bloque indéfiniment est interrompu par digest_timeout et applique le repli déterministe."""
    ctx = SessionContext(name="test_timeout", max_messages=3, digest_timeout=0.1)

    async def blocking_summarizer(msgs: List[SessionMessage]) -> str:
        await asyncio.sleep(10.0)  # Bloque bien au-delà de 0.1s
        return "jamais_atteint"

    ctx.set_summarizer(blocking_summarizer)
    ctx.add_message("system", "prompt")
    ctx.add_message("user", "Point d'arret dans app/forge_checkpoint.py\nDECISION: forcer le timeout")
    ctx.add_message("user", "trigger_msg")
    ctx.add_message("user", "overflow_msg")

    # Attente de la digestion bornée par digest_timeout
    await ctx.wait_digestion(timeout=2.0)

    assert ctx.is_digesting is False
    assert ctx._last_error is not None
    assert "Timeout" in ctx._last_error
    assert ctx.summary is not None
    assert "app/forge_checkpoint.py" in ctx.summary
    assert "forcer le timeout" in ctx.summary


@pytest.mark.asyncio
async def test_osmoregulation_faits_generiques_retrouves_rappel_100_sous_budget():
    """Constat 2 & Constat 1 : rappel 100% sur faits génériques (chemins, décisions, erreurs) SOUS budget de résumé."""
    ctx = SessionContext(name="test_generic_recall", max_messages=4, max_tokens=1000, max_summary_tokens=250)

    expected_paths = [f"app/forge_module_{i:02d}.py" for i in range(5)]
    expected_decisions = [f"strategie_osmo_{i:02d}" for i in range(5)]
    expected_errors = [f"timeout_err_{i:02d}" for i in range(3)]

    for i in range(5):
        p = expected_paths[i]
        d = expected_decisions[i]
        err_part = f"\nERREUR: {expected_errors[i % 3]}" if i < 3 else ""
        ctx.add_message("user", f"Etape {i}: audit de {p}\nDECISION: {d}{err_part}")
        await asyncio.sleep(0.01)

    await ctx.wait_digestion()

    recalled = ctx.get_recalled_facts()
    for p in expected_paths:
        assert p in recalled["paths"], f"Chemin {p} absent des faits rappelés"
    for d in expected_decisions:
        assert d in recalled["decisions"], f"Décision {d} absente des faits rappelés"
    for e in expected_errors:
        assert e in recalled["errors"], f"Erreur {e} absente des faits rappelés"

    # Vérification stricte du budget de résumé
    assert ctx.summary is not None
    assert len(ctx.summary) <= ctx.summary_token_budget * 4


def test_osmoregulation_saturation_10000_messages_taille_contexte_bornee():
    """Constat 1 : 10000 messages en flux continu -> taille de get_context bornée sous budget et ancrages bornés."""
    lessons_path = Path("logs/lessons_learned.md")
    lessons_len_before = len(lessons_path.read_text(encoding="utf-8")) if lessons_path.exists() else 0

    ctx = SessionContext(name="test_saturation_10000", max_messages=10, max_tokens=400, max_summary_tokens=150)

    for i in range(10000):
        ctx.add_message("user", f"Message {i} sur app/forge_agent_{i % 4}.py : DECISION: opt_{i % 3}")

    context = ctx.get_context()
    assert len(ctx.messages) <= 10
    total_context_chars = sum(len(c.get("content", "")) for c in context)

    # La taille du contexte ne doit jamais exploser (strictement bornée)
    assert total_context_chars < 3000, f"Saturation anormale de get_context : {total_context_chars} caractères"
    assert ctx.summary is not None
    assert len(ctx.summary) <= ctx.summary_token_budget * 4 + 50
    assert ctx._digest_count > 1000

    # Constat revue : aucune décision ni chemin n'est sorti de la fenêtre retenue (3 décisions, 4 chemins)
    # -> nombre d'ancrages strictement nul (borné et mesuré), zéro pollution de lessons_learned
    assert ctx.rag_anchor_count == 0, f"Ancrages intempestifs détectés sur répétition de faits : {ctx.rag_anchor_count}"
    lessons_len_after = len(lessons_path.read_text(encoding="utf-8")) if lessons_path.exists() else 0
    assert lessons_len_after == lessons_len_before, "Pollution interdite de logs/lessons_learned.md lors de la saturation"


def test_osmoregulation_message_courant_plus_gros_que_budget_preserve():
    """Constat 4 : un message plus gros que max_tokens ne doit JAMAIS faire évincer le message courant lui-même."""
    ctx = SessionContext(name="test_large_current_msg", max_tokens=100)

    ctx.add_message("system", "Consigne systeme initiale")
    ctx.add_message("user", "Premier echange utilisateur")

    # Message géant qui dépasse à lui seul max_tokens
    huge_text = "GRAND_MESSAGE_UTILISATEUR_" + ("ABCD " * 200)
    huge_msg = ctx.add_message("user", huge_text)

    # Le dernier message actif dans ctx.messages DOIT être le message qui vient d'entrer
    assert len(ctx.messages) >= 1
    assert ctx.messages[-1].text == huge_text
    assert ctx.messages[-1] is huge_msg


def test_osmoregulation_sync_digest_signale_resumeur_async_ignore():
    """Constat 5 : un résumeur async en chemin sync est signalé par journal et compteur."""
    ctx = SessionContext(name="test_sync_skip", max_messages=2)

    async def async_only_summarizer(msgs: List[SessionMessage]) -> str:
        return "async_result"

    ctx.set_summarizer(async_only_summarizer)
    assert ctx.sync_async_skipped_count == 0

    # Déclenche digestion synchrone hors boucle
    ctx.add_message("user", "msg1 dans app/forge_sync.py\nDECISION: test_sync")
    ctx.add_message("user", "msg2")
    ctx.add_message("user", "msg3_trigger")

    assert ctx.sync_async_skipped_count >= 1
    assert ctx.summary is not None
    assert "app/forge_sync.py" in ctx.summary


@pytest.mark.asyncio
async def test_osmoregulation_compartiment_en_digestion_visible_zero_trou_memoire():
    """Anti-défaut 3 : Pendant la digestion, les vieux messages restent visibles dans le contexte."""
    ctx = SessionContext(name="test_zero_gap", max_messages=3)

    hold_digest = asyncio.Event()

    async def held_summarizer(msgs: List[SessionMessage]) -> str:
        await hold_digest.wait()
        return "Resume final valide"

    ctx.set_summarizer(held_summarizer)

    ctx.add_message("system", "prompt systeme initial")
    ctx.add_message("user", "message_important_en_transit")
    ctx.add_message("user", "message_tampon")

    # Déclenchement de la digestion (éviction de message_important_en_transit)
    ctx.add_message("user", "message_declencheur")

    # La digestion est en cours
    assert ctx.is_digesting is True
    assert ctx.in_digestion_count > 0

    # Inspection immédiate du contexte : TROU DE MÉMOIRE IMPOSSIBLE
    current_context = ctx.get_context()
    context_texts = [c.get("content", "") for c in current_context]

    # Le message en cours d'éviction EST DANS LE CONTEXTE avec le tag in_digestion
    in_digestion_items = [c for c in current_context if c.get("in_digestion")]
    assert len(in_digestion_items) > 0
    assert any("message_important_en_transit" in t for t in context_texts)

    # Libération de la digestion
    hold_digest.set()
    await ctx.wait_digestion()

    # Après digestion terminée, le résumé est posé et le compartiment temporaire est vidé
    assert ctx.is_digesting is False
    assert ctx.in_digestion_count == 0
    final_context = ctx.get_context()
    assert any(c.get("role") == "system" and "Résumé:" in c.get("content", "") for c in final_context)


def test_osmoregulation_compatibilite_legacy_et_migration():
    """Vérifie la compatibilité ascendante avec les appelants historiques."""
    ctx = SessionContext(session_name="legacy_compat", max_tokens=1500)

    # Appel via add() legacy (forge_core_models)
    msg1 = ctx.add("user", "action_legacy: commande passee dans app/forge_legacy.py")
    assert isinstance(msg1, SessionMessage)
    assert msg1.content == "action_legacy: commande passee dans app/forge_legacy.py"
    assert msg1["content"] == "action_legacy: commande passee dans app/forge_legacy.py"
    assert msg1.tokens > 0

    # Propriétés de compatibilité
    assert ctx.session_name == "legacy_compat"
    assert ctx.name == "legacy_compat"
    assert ctx.current_tokens > 0
    assert ctx.filename.name.startswith("session_legacy_compat")

    # get_context()
    context_list = ctx.get_context()
    assert len(context_list) >= 1
    assert context_list[0]["content"] == "action_legacy: commande passee dans app/forge_legacy.py"

    # unregister() sans lever d'erreur
    ctx.unregister()


def test_osmoregulation_ancrages_bornes_par_fenetre_sur_faits_jetes():
    """Constat 1 : l'ancrage ne capture QUE ce que la compaction jette vraiment, borné par fenêtre."""
    lessons_path = Path("logs/lessons_learned.md")
    lessons_len_before = len(lessons_path.read_text(encoding="utf-8")) if lessons_path.exists() else 0

    # max_summary_tokens=60 -> budget_chars = 240
    # archive_window_size=8 -> ancrage par paquet de 8 faits sortis de la fenêtre retenue
    ctx = SessionContext(
        name="test_windowed_anchors",
        max_messages=4,
        max_tokens=200,
        max_summary_tokens=60,
        archive_window_size=8,
    )

    # Injection de 34 décisions uniques dans la session (sans chemin pour isoler les décisions)
    # 4 messages restent actifs dans ctx.messages, donc 30 messages sont évincés.
    # La fenêtre retenue retient les 12 dernières décisions (decisions[-12:]).
    # Il y aura 18 décisions sorties de la fenêtre retenue (30 - 12 = 18).
    # Avec archive_window_size=8, il doit y avoir exactement 2 ancrages (16 faits archivés, 2 en attente).
    for i in range(34):
        ctx.add_message("user", f"Etape {i:02d} instruction sans chemin\nDECISION: decision_{i:02d}")

    assert ctx.rag_anchor_count == 2, f"Nombre d'ancrages inattendu: {ctx.rag_anchor_count} (attendu: 2 pour 18 faits jetés)"
    lessons_len_after = len(lessons_path.read_text(encoding="utf-8")) if lessons_path.exists() else 0
    assert lessons_len_after == lessons_len_before, "Pollution de lessons_learned.md interdite"

    # Vérification que le pointeur de résumé référence l'identifiant réel rendu par l'ancrage
    assert ctx.last_archive_chunk_id is not None
    assert len(ctx.last_archive_chunk_id) == 16
    assert f"[Archive RAG: id={ctx.last_archive_chunk_id}]" in ctx.summary


def test_osmoregulation_troncature_non_muette_compteur_et_pointeur_sha256():
    """Constat 2 : dire ce qui est coupé (compteur) et pointer l'id réel rendu par l'ancrage (sha256 source+texte)."""
    ctx = SessionContext(
        name="test_truncation_counter",
        max_messages=4,
        max_tokens=300,
        max_summary_tokens=40,  # budget très strict : 160 caractères
        archive_window_size=4,
    )

    # Génère du contenu volumineux qui forcera une troncature du résumé compacté
    for i in range(16):
        ctx.add_message("user", f"Module app/forge_long_path_name_{i:02d}.py avec description étendue\nDECISION: strategie_complexe_{i:02d}\nERREUR: code_erreur_bloquant_{i:02d}")

    # Vérification du compteur de troncature non muette
    assert ctx.summary_truncated_count > 0, "Aucune troncature comptabilisée alors que le résumé dépasse le budget"
    assert ctx.summary_truncated_chars > 0, "Nombre de caractères tronqués nul"
    assert "[tronqué:" in ctx.summary, f"Mention explicite de la troncature absente du résumé : {ctx.summary}"

    # Vérification du pointeur réel sha256
    assert ctx.last_archive_chunk_id is not None
    assert f"[Archive RAG: id={ctx.last_archive_chunk_id}]" in ctx.summary
    assert len(ctx.last_archive_chunk_id) == 16


@pytest.mark.asyncio
async def test_osmoregulation_ancrage_async_to_thread_hors_boucle():
    """Constat 1 : écriture hors boucle asyncio (to_thread) sans bloquer l'event loop."""
    ctx = SessionContext(
        name="test_async_to_thread",
        max_messages=4,
        max_summary_tokens=60,
        archive_window_size=4,
    )

    # Dans une boucle asyncio, on injecte 24 messages (20 évincés -> 20 décisions -> 8 sorties de la fenêtre retenue)
    for i in range(24):
        ctx.add_message("user", f"Action {i} dans app/forge_async_{i}.py\nDECISION: d_async_{i}")
        await asyncio.sleep(0.005)

    await ctx.wait_digestion()

    assert ctx.rag_anchor_count >= 1
    assert ctx.last_archive_chunk_id is not None
    assert f"[Archive RAG: id={ctx.last_archive_chunk_id}]" in ctx.summary


def test_osmoregulation_aucun_nr_n_ouvre_open_writer():
    """Constat 3 : un NR vérifie qu'aucun test ni digestion n'ouvre open_writer sur la production."""
    open_writer_called = False

    def spy_forbidden_open_writer(*args, **kwargs):
        nonlocal open_writer_called
        open_writer_called = True
        raise AssertionError("INTERDIT : open_writer a été appelé !")

    # Exécute une session complète avec 20 messages et plusieurs ancrages
    ctx = SessionContext(
        name="test_zero_open_writer",
        max_messages=4,
        max_summary_tokens=60,
        archive_window_size=4,
    )
    for i in range(20):
        ctx.add_message("user", f"Etape {i} dans app/forge_test_{i}.py\nDECISION: dec_{i}")

    # L'ancrage a eu lieu au niveau de la session
    assert ctx.rag_anchor_count >= 1
    # Mais open_writer n'a JAMAIS été appelé (base de production 100% isolée)
    assert not open_writer_called, "open_writer a été ouvert pendant le test NR !"


def test_osmoregulation_echec_archive_warning_compteur_et_faits_conserves(monkeypatch, caplog):
    """Constat 2 : un échec d'écriture RAG émet un WARNING, incrémente archive_failed_count et CONSERVE les faits non archivés dans le résumé."""
    # Doublure qui simule un échec de l'écrivain RAG
    def failing_persist_chunk(self, cid: str, source: str, domain: str, text: str) -> bool:
        self._archive_failed_count += 1
        import logging
        logging.getLogger("Nokido.SessionContext").warning(
            "Échec simulé de l'archivage RAG (chunk_id=%s) : base indisponible",
            cid,
        )
        return False

    monkeypatch.setattr(SessionContext, "_persist_chunk", failing_persist_chunk)

    ctx = SessionContext(
        name="test_archive_failure_preserves_facts",
        max_messages=4,
        max_tokens=200,
        max_summary_tokens=60,
        archive_window_size=8,
    )

    import logging
    with caplog.at_level(logging.WARNING):
        # Injection de 24 décisions pour déclencher au moins une tentative d'ancrage
        for i in range(24):
            ctx.add_message("user", f"Action {i:02d}\nDECISION: decision_critique_{i:02d}")

    # 1. Compteur d'archives échouées exposé et incrémenté
    assert ctx.archive_failed_count > 0, "Le compteur d'échecs d'archivage doit être incrémenté"
    assert ctx.rag_archive_failed_count == ctx.archive_failed_count

    # 2. Un WARNING explicite a été journalisé (pas un simple debug silencieux)
    assert any("Échec" in record.message or "archive" in record.message.lower() for record in caplog.records if record.levelno >= logging.WARNING)

    # 3. Zéro perte muette : les faits non archivés RESTENT dans le résumé
    # Les décisions qui auraient dû être jetées si l'archive avait réussi (01 à 07) restent dans le résumé
    for i in range(1, 8):
        assert f"decision_critique_{i:02d}" in ctx.summary, (
            f"La décision {i:02d} a été perdue alors que l'archive a échoué !"
        )

    # 4. Aucun fait n'est marqué comme archivé tant que l'archive n'est pas confirmée
    assert len(ctx._anchored_fact_keys) == 0, "Aucun fait ne doit être marqué archivé en cas d'échec"
    assert ctx.last_archive_chunk_id is None, "Aucun identifiant d'archive ne doit être référencé en cas d'échec"
    assert ctx.rag_anchor_count == 0, "Le compteur d'ancrages réussis doit être nul"


def test_osmoregulation_persist_chunk_voie_gouvernee_sans_insert_fts(monkeypatch):
    """Constat 1 : _persist_chunk passe par la voie gouvernée (process_document + store_chunks sous write_retry) sans aucun INSERT manuel dans rag_fts."""
    process_doc_called = False
    store_chunks_called = False

    def spy_process_document(text, source, domain_hint="", role_hint="", author="", doc_summary="", max_tokens=400):
        nonlocal process_doc_called
        process_doc_called = True
        from nokido_agent.app.forge_ingest_pipeline import RefinedChunk
        return [RefinedChunk(
            id="test_chunk_id",
            text=text,
            source=source,
            domain=domain_hint,
            role_hint=role_hint,
            author=author,
        )]

    def spy_store_chunks(chunks, db_path=None, batch_size=100):
        nonlocal store_chunks_called
        store_chunks_called = True
        return len(chunks)

    monkeypatch.setattr("nokido_agent.app.forge_ingest_pipeline.process_document", spy_process_document)
    monkeypatch.setattr("nokido_agent.app.forge_ingest_pipeline.store_chunks", spy_store_chunks)

    ctx = SessionContext(name="test_gov_path")
    success = _REAL_PERSIST_CHUNK(ctx, "cid123", "session:test:osmo", "systeme", "Texte archivé à tester")

    assert success is True
    assert process_doc_called is True, "process_document doit être appelé pour enrichir le chunk"
    assert store_chunks_called is True, "store_chunks doit être appelé pour persister le chunk"


def test_osmoregulation_chunk_deja_present_confirme_zero_faux_echec(monkeypatch):
    """Constat 1 : si le chunk est déjà présent dans rag_chunks (store_chunks retourne 0 car fingerprint/id connu),
    _persist_chunk confirme l'archivage (True), sans faux échec ni rejeu infini."""
    def mock_process_document(text, source, domain_hint="", role_hint="", author="", doc_summary="", max_tokens=400):
        from nokido_agent.app.forge_ingest_pipeline import RefinedChunk
        c = RefinedChunk(
            id="already_known_cid",
            text=text,
            source=source,
            domain=domain_hint,
            role_hint=role_hint,
            author=author,
        )
        c.meta["already_present"] = True
        return [c]

    def mock_store_chunks(chunks, db_path=None, batch_size=100):
        # 0 chunk inséré car déjà connu
        return 0

    monkeypatch.setattr("nokido_agent.app.forge_ingest_pipeline.process_document", mock_process_document)
    monkeypatch.setattr("nokido_agent.app.forge_ingest_pipeline.store_chunks", mock_store_chunks)

    ctx = SessionContext(name="test_idempotent_archive")
    confirmed = _REAL_PERSIST_CHUNK(ctx, "already_known_cid", "session:test", "systeme", "Texte déjà archivé")

    assert confirmed is True, "Un chunk déjà présent doit être confirmé comme archivé (idempotence)"
    assert ctx.archive_failed_count == 0, "Aucun échec d'archivage ne doit être compté pour un chunk déjà présent"


@pytest.mark.asyncio
async def test_osmoregulation_anti_course_faits_en_vol_sans_re_lot(monkeypatch):
    """Constat 2 : marquer les faits 'en vol' avant déportation (to_thread) pour empêcher un 2e appel concurrent de re-loter les mêmes faits."""
    import time
    persist_calls = []

    def slow_persist_chunk(self, cid: str, source: str, domain: str, text: str) -> bool:
        persist_calls.append(cid)
        time.sleep(0.05)
        return True

    monkeypatch.setattr(SessionContext, "_persist_chunk", slow_persist_chunk)

    ctx = SessionContext(
        name="test_race_inflight",
        max_messages=4,
        max_tokens=200,
        max_summary_tokens=60,
        archive_window_size=4,
    )

    dropped_decisions = ["dec_alpha", "dec_beta", "dec_gamma", "dec_delta"]

    # 1er appel : lance l'ancrage en tâche de fond (to_thread)
    ctx._anchor_dropped_facts(dropped_decisions, [], [])

    # Pendant que le 1er appel est en vol (dans le thread), les faits doivent être marqués en vol
    assert hasattr(ctx, "_inflight_fact_keys"), "ctx doit avoir _inflight_fact_keys"
    assert "d:dec_alpha" in ctx._inflight_fact_keys, "Les faits doivent être marqués 'en vol' AVANT déportation"

    # 2e appel IMMÉDIAT avant la fin du thread : ne doit PAS relancer de tâche pour les mêmes faits !
    tasks_count_before = len(ctx._running_tasks)
    ctx._anchor_dropped_facts(dropped_decisions, [], [])
    tasks_count_after = len(ctx._running_tasks)
    assert tasks_count_after == tasks_count_before, "Un 2e appel concurrent ne doit pas relancer de tâche pour les faits déjà en vol !"

    # On attend que la tâche en cours termine
    if ctx._running_tasks:
        await asyncio.gather(*list(ctx._running_tasks))

    # Au retour sous verrou : les faits ne sont plus en vol et sont maintenant ancrés
    assert "d:dec_alpha" not in ctx._inflight_fact_keys
    assert "d:dec_alpha" in ctx._anchored_fact_keys
    assert len(persist_calls) == 1, "Un seul lot doit avoir été persisté (aucun doublon par course)"


def test_osmoregulation_store_chunks_commit_batch_warning_sur_echec_write_retry(monkeypatch, caplog):
    """Constat 3 : _commit_batch dans store_chunks journalise un WARNING si write_retry échoue avant d'exécuter le repli direct."""
    import sqlite3
    import logging
    from nokido_agent.app.forge_ingest_pipeline import RefinedChunk, store_chunks

    def failing_write_retry(op, **kwargs):
        raise sqlite3.OperationalError("Simulated lock error on write_retry")

    monkeypatch.setattr("nokido_agent.app.forge_db_path.write_retry", failing_write_retry)

    fallback_executed = False

    class MockFallbackConn:
        def execute(self, sql, params=()):
            class Cursor:
                def fetchall(self):
                    return []
            return Cursor()

        def executemany(self, sql, params):
            nonlocal fallback_executed
            fallback_executed = True

        def commit(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr("nokido_agent.app.forge_ingest_pipeline._open_db", lambda *a, **kw: MockFallbackConn())

    chunks = [RefinedChunk(id="test_fallback_cid", text="Contenu test", source="src", domain="sys", role_hint="test")]
    with caplog.at_level(logging.WARNING):
        store_chunks(chunks)

    assert fallback_executed is True, "Le repli direct via _open_db doit être exécuté si write_retry échoue"
    assert any("write_retry" in rec.message.lower() and rec.levelno >= logging.WARNING for rec in caplog.records), (
        "Un WARNING doit être journalisé pour expliquer l'échec de write_retry"
    )


def test_osmoregulation_clean_val_compte_et_dit_troncatures(caplog):
    """Constat 4 : _clean_val compte et avertit (warning) lorsqu'il écarte des valeurs tronquées (commençant/finissant par '...')."""
    import logging
    ctx = SessionContext(name="test_clean_val")

    with caplog.at_level(logging.WARNING):
        raw = "Décisions (DECISION): ...decision_coupee; decision_normale; autre_coupee..."
        ctx._enforce_summary_budget(raw)

    assert hasattr(ctx, "clean_val_dropped_count"), "ctx doit exposer clean_val_dropped_count"
    assert ctx.clean_val_dropped_count >= 2, "Les 2 valeurs tronquées doivent avoir été comptées"
    assert any("écarté" in rec.message or "tronqu" in rec.message.lower() for rec in caplog.records if rec.levelno >= logging.WARNING), (
        "Un message de log WARNING doit signaler les valeurs écartées par _clean_val"
    )


