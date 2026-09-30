# -*- coding: utf-8 -*-
"""
tests/nr/test_integrity_nr.py — NR forge_integrity (Capability-Based Security)
===============================================================================
Suite de non-régression — comportement figé.
Règle : si un test casse, c'est un bug ou une évolution volontaire.
JAMAIS mettre à jour les assertions sans review explicite.

Marqueurs : @pytest.mark.nr, @pytest.mark.security
Lancer    : python -m pytest tests/nr/test_integrity_nr.py -v
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

# ── Imports module sous test ──────────────────────────────────────────────────
from forge_integrity import (
    CapabilityToken,
    IntegrityManager,
    IntegrityRing,
    RingContext,
    TokenExpiredError,
    get_manager,
    is_at_least,
)

# ── Constante NR — secret fixe pour reproductibilité ─────────────────────────
_SECRET = "nr_test_secret_32chars_long_enough!"
_MGR    = IntegrityManager(_SECRET)


# =============================================================================
# BLOC 1 — IntegrityRing : ordre et sémantique
# =============================================================================

class TestIntegrityRing:
    """Les rings sont ordonnés correctement — jamais de comparaison == directe."""

    def test_ring_values_ordered(self):
        """SYSTEM(0) < DEV(1) < TRUSTED(2) < COLLAB(3) < UNTRUSTED(4)."""
        assert IntegrityRing.SYSTEM    == 0
        assert IntegrityRing.DEV       == 1
        assert IntegrityRing.TRUSTED   == 2
        assert IntegrityRing.COLLAB    == 3
        assert IntegrityRing.UNTRUSTED == 4

    def test_ring_labels(self):
        labels = {
            IntegrityRing.SYSTEM:    "SYSTEM",
            IntegrityRing.DEV:       "DEV",
            IntegrityRing.TRUSTED:   "TRUSTED",
            IntegrityRing.COLLAB:    "COLLAB",
            IntegrityRing.UNTRUSTED: "UNTRUSTED",
        }
        for ring, expected in labels.items():
            assert ring.label() == expected

    @pytest.mark.parametrize("ring,expected", [
        (IntegrityRing.SYSTEM,    "gold"),
        (IntegrityRing.DEV,       "gold"),
        (IntegrityRing.TRUSTED,   "verified"),
        (IntegrityRing.COLLAB,    "draft"),
        (IntegrityRing.UNTRUSTED, "raw"),
    ])
    def test_consensus_level(self, ring, expected):
        """Golden dataset consensus — ne jamais changer sans review."""
        assert ring.consensus_level() == expected


# =============================================================================
# BLOC 2 — is_at_least : règle fondamentale
# =============================================================================

class TestIsAtLeast:
    """
    Matrice complète de is_at_least().
    Ces assertions sont la source de vérité — toute régression ici
    signifie que la logique de permission est cassée.
    """

    @pytest.mark.parametrize("ring,required,expected", [
        # SYSTEM peut tout
        (IntegrityRing.SYSTEM,    IntegrityRing.SYSTEM,    True),
        (IntegrityRing.SYSTEM,    IntegrityRing.DEV,       True),
        (IntegrityRing.SYSTEM,    IntegrityRing.TRUSTED,   True),
        (IntegrityRing.SYSTEM,    IntegrityRing.COLLAB,    True),
        (IntegrityRing.SYSTEM,    IntegrityRing.UNTRUSTED, True),
        # DEV
        (IntegrityRing.DEV,       IntegrityRing.SYSTEM,    False),
        (IntegrityRing.DEV,       IntegrityRing.DEV,       True),
        (IntegrityRing.DEV,       IntegrityRing.TRUSTED,   True),
        (IntegrityRing.DEV,       IntegrityRing.COLLAB,    True),
        (IntegrityRing.DEV,       IntegrityRing.UNTRUSTED, True),
        # TRUSTED
        (IntegrityRing.TRUSTED,   IntegrityRing.SYSTEM,    False),
        (IntegrityRing.TRUSTED,   IntegrityRing.DEV,       False),
        (IntegrityRing.TRUSTED,   IntegrityRing.TRUSTED,   True),
        (IntegrityRing.TRUSTED,   IntegrityRing.COLLAB,    True),
        (IntegrityRing.TRUSTED,   IntegrityRing.UNTRUSTED, True),
        # COLLAB
        (IntegrityRing.COLLAB,    IntegrityRing.SYSTEM,    False),
        (IntegrityRing.COLLAB,    IntegrityRing.DEV,       False),
        (IntegrityRing.COLLAB,    IntegrityRing.TRUSTED,   False),
        (IntegrityRing.COLLAB,    IntegrityRing.COLLAB,    True),
        (IntegrityRing.COLLAB,    IntegrityRing.UNTRUSTED, True),
        # UNTRUSTED ne peut rien (sauf lui-même)
        (IntegrityRing.UNTRUSTED, IntegrityRing.SYSTEM,    False),
        (IntegrityRing.UNTRUSTED, IntegrityRing.DEV,       False),
        (IntegrityRing.UNTRUSTED, IntegrityRing.TRUSTED,   False),
        (IntegrityRing.UNTRUSTED, IntegrityRing.COLLAB,    False),
        (IntegrityRing.UNTRUSTED, IntegrityRing.UNTRUSTED, True),
    ])
    def test_matrix(self, ring, required, expected):
        assert is_at_least(ring, required) == expected

    def test_never_compare_with_equality_directly(self):
        """Démonstration : == est trompeur, is_at_least() est la bonne façon."""
        # DEV != TRUSTED mais DEV peut tout ce que TRUSTED peut
        assert IntegrityRing.DEV != IntegrityRing.TRUSTED
        assert is_at_least(IntegrityRing.DEV, IntegrityRing.TRUSTED) is True


# =============================================================================
# BLOC 3 — CapabilityToken : encode / decode / sécurité
# =============================================================================

class TestCapabilityToken:
    """Token HMAC — intégrité cryptographique et format."""

    def test_format_payload_dot_signature(self, dev_token):
        """Format sérialisé : exactement un '.' séparant payload et signature."""
        parts = dev_token.split(".")
        assert len(parts) == 2, f"Attendu 2 parties, got {len(parts)}"
        payload_b64, sig = parts
        assert len(payload_b64) > 10
        assert len(sig) == 64          # SHA-256 hexdigest = 64 chars

    def test_decode_round_trip(self, dev_token):
        """Encode → decode doit produire les mêmes valeurs."""
        token = CapabilityToken.decode(dev_token, _SECRET.encode())
        assert token.sub    == "claude"
        assert token.ring   == IntegrityRing.DEV
        assert "fs"  in token.scopes
        assert "rag" in token.scopes
        assert token.ttl()  > 0

    def test_invalid_signature_raises(self, dev_token):
        """Altération du payload → ValueError."""
        payload_b64, sig = dev_token.split(".")
        tampered = payload_b64[:-2] + "AA"    # modifie 2 chars du payload
        with pytest.raises(ValueError, match="[Ss]ignature"):
            CapabilityToken.decode(f"{tampered}.{sig}", _SECRET.encode())

    def test_wrong_secret_raises(self, dev_token):
        """Mauvais secret → ValueError."""
        with pytest.raises(ValueError):
            CapabilityToken.decode(dev_token, b"wrong_secret")

    def test_expired_token_raises(self):
        """Token expiré → TokenExpiredError (sous-classe de ValueError)."""
        expired_str = _MGR.create_manifest(
            "x", IntegrityRing.COLLAB,
            scopes={"rag": ["query"]},
            duration_s=-10,
        )
        with pytest.raises(TokenExpiredError):
            CapabilityToken.decode(expired_str, _SECRET.encode())

    def test_ttl_positive_for_valid(self, dev_token):
        token = CapabilityToken.decode(dev_token, _SECRET.encode())
        assert token.ttl() > 3500    # proche de 1h

    def test_can_scope_wildcard(self):
        """Wildcard '*' autorise toutes les actions du scope."""
        t_str = _MGR.create_manifest("x", IntegrityRing.DEV,
                                      scopes={"fs": ["*"]}, duration_s=60)
        t = CapabilityToken.decode(t_str, _SECRET.encode())
        assert t.can("fs", "read")
        assert t.can("fs", "write")
        assert t.can("fs", "exec")

    def test_can_explicit_actions(self, collab_token):
        """Seules les actions explicites sont autorisées."""
        t = CapabilityToken.decode(collab_token, _SECRET.encode())
        assert t.can("rag", "query")
        assert t.can("rag", "ingest")
        assert not t.can("rag", "admin")    # absent du token

    def test_jti_unique(self):
        """Chaque token a un JTI unique (anti-replay)."""
        t1 = _MGR.create_manifest("x", IntegrityRing.COLLAB,
                                   scopes={}, duration_s=60)
        t2 = _MGR.create_manifest("x", IntegrityRing.COLLAB,
                                   scopes={}, duration_s=60)
        tok1 = CapabilityToken.decode(t1, _SECRET.encode())
        tok2 = CapabilityToken.decode(t2, _SECRET.encode())
        assert tok1.jti != tok2.jti


# =============================================================================
# BLOC 4 — Atténuation : jamais d'extension de droits
# =============================================================================

class TestAttenuation:
    """
    Règle fondamentale capability-based :
    un token fils ne peut PAS avoir plus de droits que son parent.
    """

    def test_child_cannot_add_scope(self, dev_token):
        """Scope absent chez le parent → absent chez le fils."""
        parent = CapabilityToken.decode(dev_token, _SECRET.encode())
        # dev_token n'a pas scope "sql" → l'atténuation ne peut pas l'ajouter
        child = parent.attenuate({"sql": ["read", "write"]})
        assert not child.can("sql", "read")
        assert not child.can("sql", "write")

    def test_child_cannot_add_action(self, trusted_token):
        """Action absente chez le parent → absente chez le fils."""
        parent = CapabilityToken.decode(trusted_token, _SECRET.encode())
        # trusted_token a fs=["read","write"] mais pas "exec"
        child = parent.attenuate({"fs": ["read", "write", "exec"]})
        assert child.can("fs", "read")
        assert child.can("fs", "write")
        assert not child.can("fs", "exec")     # refusé — absent du parent

    def test_child_cannot_add_rag_admin(self, trusted_token):
        """trusted n'a pas rag/admin → atténuation ne peut l'accorder."""
        parent = CapabilityToken.decode(trusted_token, _SECRET.encode())
        child = parent.attenuate({"rag": ["query", "ingest", "admin"]})
        assert child.can("rag", "query")
        assert child.can("rag", "ingest")
        assert not child.can("rag", "admin")

    def test_child_ttl_cannot_exceed_parent(self, dev_token):
        """Le TTL du fils ≤ TTL du parent."""
        parent = CapabilityToken.decode(dev_token, _SECRET.encode())
        # Demander 24h mais parent expire dans ~1h
        child = parent.attenuate({"fs": ["read"]}, duration_s=86400)
        assert child.exp <= parent.exp

    def test_parent_wildcard_child_can_restrict(self, dev_token):
        """Parent a fs=["*"] → fils peut restreindre à read seul."""
        parent = CapabilityToken.decode(dev_token, _SECRET.encode())
        child = parent.attenuate({"fs": ["read"]})
        assert child.can("fs", "read")
        assert not child.can("fs", "write")


# =============================================================================
# BLOC 5 — IntegrityManager : émission et vérification
# =============================================================================

class TestIntegrityManager:
    """Façade principale — verify() retourne (bool, RingContext|str)."""

    def test_verify_authorized_action(self, dev_token):
        """Action dans le scope → (True, RingContext)."""
        ok, result = _MGR.verify("fs", "write", dev_token)
        assert ok is True
        assert isinstance(result, RingContext)
        assert result.ring == IntegrityRing.DEV
        assert result.agent_id == "claude"

    def test_verify_denied_scope_absent(self, collab_token):
        """Scope absent du token → (False, str_reason)."""
        ok, reason = _MGR.verify("system", "sentinel_bypass", collab_token)
        assert ok is False
        assert isinstance(reason, str)
        assert len(reason) > 0

    def test_verify_denied_action_absent(self, trusted_token):
        """Action absente du scope → (False, str)."""
        ok, reason = _MGR.verify("tasks", "review", trusted_token)
        assert ok is False

    def test_verify_expired_returns_false(self):
        """Token expiré → (False, str) — jamais d'exception non gérée."""
        expired = _MGR.create_manifest("x", IntegrityRing.DEV,
                                        scopes={"fs": ["write"]},
                                        duration_s=-1)
        ok, reason = _MGR.verify("fs", "write", expired)
        assert ok is False
        assert "expir" in reason.lower()

    def test_verify_invalid_token_returns_false(self):
        """Token malformé → (False, str)."""
        ok, reason = _MGR.verify("fs", "read", "not_a_valid.token_at_all")
        assert ok is False

    def test_verify_ring_minimum_enforced(self):
        """Ring insuffisant même si scope présent → (False, str)."""
        # sql/write requiert SYSTEM — créer un token DEV avec sql/write
        token_with_sql = _MGR.create_manifest(
            "claude", IntegrityRing.DEV,
            scopes={"sql": ["write"]},
            duration_s=60,
        )
        ok, reason = _MGR.verify("sql", "write", token_with_sql)
        # DEV n'est pas is_at_least(DEV, SYSTEM) → False
        assert ok is False

    def test_create_manifest_has_jti(self):
        """Chaque manifest a un JTI unique."""
        t1 = _MGR.create_manifest("a", IntegrityRing.COLLAB, duration_s=60)
        t2 = _MGR.create_manifest("a", IntegrityRing.COLLAB, duration_s=60)
        tok1 = CapabilityToken.decode(t1, _SECRET.encode())
        tok2 = CapabilityToken.decode(t2, _SECRET.encode())
        assert tok1.jti != tok2.jti

    def test_decode_raw_returns_none_on_invalid(self):
        """decode_raw() sur un token invalide → None (jamais d'exception)."""
        result = _MGR.decode_raw("garbage.data")
        assert result is None

    def test_decode_raw_returns_token_on_valid(self, dev_token):
        token = _MGR.decode_raw(dev_token)
        assert token is not None
        assert token.ring == IntegrityRing.DEV


# =============================================================================
# BLOC 6 — RingContext : contexte d'exécution
# =============================================================================

class TestRingContext:
    """RingContext est le porteur de contexte dans toute la chaîne d'appels."""

    def test_system_context_bypass_sentinel(self):
        """SYSTEM bypass toujours la sentinel."""
        ctx = RingContext.system()
        assert ctx.ring == IntegrityRing.SYSTEM
        assert ctx.bypass_sentinel is True

    def test_dev_context_bypass_sentinel(self, dev_token):
        """DEV avec sentinel_bypass dans les scopes → bypass."""
        ok, ctx = _MGR.verify("fs", "write", dev_token)
        assert ok
        assert ctx.bypass_sentinel is True

    def test_collab_no_bypass(self, collab_token):
        """COLLAB ne bypass jamais la sentinel."""
        ok, ctx = _MGR.verify("rag", "query", collab_token)
        assert ok
        assert ctx.bypass_sentinel is False

    def test_rag_author_tag_format(self, dev_token):
        """Format : 'ring:agent_id:session_id[:16]'."""
        ok, ctx = _MGR.verify("fs", "write", dev_token)
        assert ok
        tag = ctx.rag_author_tag()
        parts = tag.split(":")
        assert len(parts) == 3
        assert parts[0] == "dev"
        assert parts[1] == "claude"

    def test_rag_meta_patch_fields(self, dev_token):
        """meta_patch contient les champs requis pour rag_chunks.meta."""
        ok, ctx = _MGR.verify("fs", "write", dev_token)
        assert ok
        patch = ctx.rag_meta_patch()
        assert "ring"            in patch
        assert "ring_label"      in patch
        assert "consensus_level" in patch
        assert "ingested_by"     in patch
        assert patch["ring"]            == int(IntegrityRing.DEV)
        assert patch["ring_label"]      == "DEV"
        assert patch["consensus_level"] == "gold"
        assert patch["ingested_by"]     == "claude"

    def test_can_action(self, dev_token):
        """can() délègue au token pour DEV."""
        ok, ctx = _MGR.verify("fs", "write", dev_token)
        assert ok
        assert ctx.can("fs", "write")    is True
        assert ctx.can("fs", "exec")     is True
        assert ctx.can("sql", "write")   is False

    def test_assert_can_raises_permission_error(self, collab_token):
        """assert_can() lève PermissionError si refusé."""
        ok, ctx = _MGR.verify("rag", "query", collab_token)
        assert ok
        with pytest.raises(PermissionError):
            ctx.assert_can("fs", "write")

    @pytest.mark.parametrize("ring,expected_consensus", [
        (IntegrityRing.SYSTEM,    "gold"),
        (IntegrityRing.DEV,       "gold"),
        (IntegrityRing.TRUSTED,   "verified"),
        (IntegrityRing.COLLAB,    "draft"),
        (IntegrityRing.UNTRUSTED, "raw"),
    ])
    def test_rag_consensus_by_ring(self, ring, expected_consensus):
        ctx = RingContext(ring=ring, agent_id="test")
        assert ctx.rag_consensus == expected_consensus

    def test_untrusted_context(self):
        ctx = RingContext.untrusted("unknown_agent")
        assert ctx.ring == IntegrityRing.UNTRUSTED
        assert ctx.bypass_sentinel is False
        assert ctx.rag_consensus == "raw"


# =============================================================================
# BLOC 7 — Edge cases : entrées corrompues / limites (C3)
# =============================================================================

class TestEdgeCases:
    """
    C3 — NR Edge Case Driven.
    Les régressions arrivent toujours sur les cas limites.
    Ces tests figent le comportement défensif attendu.
    """

    def test_token_truncated_no_dot(self):
        """Token sans '.' → ValueError (pas de crash non géré)."""
        with pytest.raises(ValueError, match="[Ff]ormat"):
            CapabilityToken.decode("payloadwithoutdot", _SECRET.encode())

    def test_token_empty_string(self):
        """Token vide → ValueError."""
        with pytest.raises(ValueError):
            CapabilityToken.decode("", _SECRET.encode())

    def test_token_ring_out_of_range(self):
        """
        ring=99 dans le payload → IntegrityRing(99) lève ValueError.
        Le token ne doit pas être accepté silencieusement.
        """
        import base64, json as _json
        payload = {"sub": "x", "ring": 99, "scopes": {}, "exp": 9999999999.0,
                   "iat": 1.0, "jti": "abc", "seq": 1}
        pb64 = base64.urlsafe_b64encode(
            _json.dumps(payload).encode()
        ).rstrip(b"=").decode()
        sig = __import__('hmac').new(
            _SECRET.encode(), pb64.encode(), __import__('hashlib').sha256
        ).hexdigest()
        with pytest.raises((ValueError, KeyError)):
            CapabilityToken.decode(f"{pb64}.{sig}", _SECRET.encode())

    def test_create_manifest_duration_zero(self):
        """duration_s=0 → token immédiatement expiré → verify retourne False."""
        t = _MGR.create_manifest("x", IntegrityRing.DEV,
                                  scopes={"fs": ["read"]}, duration_s=0)
        ok, reason = _MGR.verify("fs", "read", t)
        # Peut être expiré ou à la limite — dans les deux cas on n'exige pas ok=True
        # Ce qui compte : pas de crash, retourne (bool, str)
        assert isinstance(ok, bool)
        assert isinstance(reason, (str, RingContext))

    def test_secret_empty_raises(self):
        """Secret vide → ValueError à la création."""
        with pytest.raises(ValueError, match="secret"):
            IntegrityManager("")

    def test_revoke_then_new_token_passes(self):
        """
        Révocation seq < N → ancien bloqué, nouveau (seq >= N) passe.
        C'est le comportement core de P1 révocation.
        """
        mgr = IntegrityManager(_SECRET)
        t_old = mgr.create_manifest("alice", IntegrityRing.COLLAB,
                                     scopes={"rag": ["query"]}, duration_s=3600)
        tok_old = CapabilityToken.decode(t_old, _SECRET.encode())
        t_new = mgr.create_manifest("alice", IntegrityRing.COLLAB,
                                     scopes={"rag": ["query"]}, duration_s=3600)
        # Révoquer tout ce qui est < seq du nouveau
        mgr.revoke("alice", tok_old.seq + 1)

        ok_old, _ = mgr.verify("rag", "query", t_old)
        ok_new, _ = mgr.verify("rag", "query", t_new)

        assert ok_old is False, "Ancien token doit être bloqué après révocation"
        assert ok_new is True,  "Nouveau token doit passer après révocation"

    def test_attenuate_respects_parent_expiry(self):
        """
        Atténuation depuis un token qui expire dans 1s.
        Le fils ne peut pas dépasser l'expiration du parent.
        """
        short = _MGR.create_manifest("x", IntegrityRing.DEV,
                                      scopes={"fs": ["read"]}, duration_s=1)
        parent = CapabilityToken.decode(short, _SECRET.encode())
        child  = parent.attenuate({"fs": ["read"]}, duration_s=86400)
        assert child.exp <= parent.exp

    def test_verify_garbage_token(self):
        """Données aléatoires → (False, str), pas d'exception."""
        ok, reason = _MGR.verify("fs", "read", "aaaa.bbbb.cccc")
        assert ok is False
        assert isinstance(reason, str)

    def test_revoke_unknown_agent_noop(self):
        """Révoquer un agent inconnu ne lève pas d'exception."""
        mgr = IntegrityManager(_SECRET)
        min_seq = mgr.revoke("unknown_agent_xyz")
        assert isinstance(min_seq, int)

    def test_revoke_status_reflects_table(self):
        """revoke_status() retourne le dict de révocation."""
        mgr = IntegrityManager(_SECRET)
        mgr.create_manifest("bob", IntegrityRing.COLLAB, duration_s=60)
        mgr.revoke("bob", 5)
        status = mgr.revoke_status()
        assert "bob" in status
        assert status["bob"] == 5


# =============================================================================
# BLOC 8 — get_manager() : singleton
# =============================================================================

class TestGetManager:

    def test_singleton(self):
        """get_manager() retourne toujours la même instance."""
        m1 = get_manager()
        m2 = get_manager()
        assert m1 is m2

    def test_singleton_is_integrity_manager(self):
        assert isinstance(get_manager(), IntegrityManager)
