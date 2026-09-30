"""NR — le profil egress `public` doit rester ATTEIGNABLE pour le depot de publication.

Trou paye le 2026-09-14 (roadmap P0 `roadmap_p0_profil_egress_public_inatteignable`) :
`.git-publish-rules.json` portait `default_profile=private` avec `remote_profiles` VIDE,
donc AUCUNE URL ne resolvait vers le profil `public` — scrub, chemins interdits et cap
5 Mo etaient DECLARES et jamais APPLIQUES. Mecanisme present, effet nul : exactement le
motif « un garde branche sur un signal que personne n'emet ».

Ce NR lit le manifeste REEL du depot, parce que le trou etait dans la DONNEE et non
dans le code : une fixture fabriquee passerait pendant que la publication part nue.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# import DUR, jamais importorskip : un skip rendrait la CI verte sans rien prouver.
from app import forge_git_egress as E  # noqa: E402

URL_PUBLICATION = "https://github.com/Nokido-labs/nokido-dist.git"
URL_TRAVAIL = "https://github.com/Nokido-labs/nokido.git"


def test_remote_profiles_n_est_pas_vide():
    rp = E.load_manifest().get("remote_profiles") or {}
    assert rp, (
        "remote_profiles VIDE : le profil `public` redevient inatteignable et tout push "
        "de publication partirait sans scrub ni chemins interdits"
    )


def test_le_depot_de_publication_resout_en_public_et_filtre_vraiment():
    nom, prof = E.resolve_profile(URL_PUBLICATION)
    assert nom == "public", f"{URL_PUBLICATION} resout en {nom!r} au lieu de 'public'"
    assert prof.get("scrub") is True, "profil public sans scrub"
    assert (prof.get("max_file_bytes") or 0) > 0, "profil public sans plafond de taille"
    assert prof.get("blocked_paths"), "profil public sans chemins interdits"


# --- Doctrine de publication du 2026-09-15 : la publication est SUBSTANTIELLE. ---
# Le filtre doit mordre sur deux familles seulement (IP_HOLD + telemetrie de
# developpement) et EPARGNER le coeur. Les deux sens sont testes : un filtre trop
# large produirait un depot propre et CREUX, ce qui est un echec, pas une securite.

# Owner 2026-09-30 : « je veux un Nokido pleinement fonctionnel, pas bride ; rien
# ne justifie les decisions de propriete intellectuelle pour le moment ». Ne
# restent bloques que des motifs de SECURITE, de VIE PRIVEE ou de TAILLE.
_DOIT_ETRE_BLOQUE = [
    "sandbox/secrets/x.json",                                    # secrets
    "config/LaForge.env",
    "config/identites_privees.txt",                              # vie privee
    "app/build_cython/Users/x/y.c",                              # chemins portant le compte owner
    "tools/ch88_scan.py",                                        # offensif (owner 2026-09-15)
    "docs/AUDIT_SECURITE_REGISTRE.md",                           # failles non corrigees
    "docs/AUDIT_VAULT_2026-09-20.md",
    ".github/workflows/ci-selfhosted.yml",                       # PR publique -> code sur le poste owner
    "sandbox/.ngrok_pid",                                        # etat volatil
    "sandbox/pids/registry.json",
    "sandbox/_phantoms_backup/x",
    "sandbox/db_schema_data.pkl",                                # pickle : execution au chargement
    "sandbox/perf_history/rca_jepa_train_py312_baseline_20260529T071433.prof",  # dump binaire (chemin owner embarque)
    "docs/launch/media/demo_feed_real.gif",                      # > cap 5 Mo (le .webm couvre la demo)
    "seed/commit_intel.jsonl",                                   # identite civile des auteurs (a regenerer pseudonymise)
    # IP_CLEARANCE (owner 2026-09-30) : docs/ip/** en HOLD par defaut -- un candidat
    # brevet publie perd sa nouveaute, definitivement. Seul un document LIBERE
    # nommement (profil public `ip_clearance`) part.
    "docs/ip/IP_TRIAGE_CANDIDATS.md",
]

# Bloques jusqu'au 2026-09-30 (IP_HOLD, telemetrie, config env-specifique) --
# ils PARTENT desormais : une partie fait TOURNER Nokido (superviseur, deploiement,
# taches, calibration d'embedding, census, skills). Chemins machine generises au
# promoteur ; identite civile refusee ; secrets scannes fail-closed.
_DOIT_PARTIR = [
    ".agents/skills/forge-core/SKILL.md",
    ".agents/orchestrator/BRIEFING.md",
    "seed/trajectories.jsonl",
    "config/pca_64.npz",
    "tools/forge_embed_bridge.npz",
    "proxy_deno/core/services.toml",
    "tools/cline_mcp_settings.json",
    "deploy/com.nokido.master.plist",
    "tools/tasks/LaForge-EmbedRebuild.xml",
    "docs/launch/legal_protection.md",
    "sandbox/workspace/organ_map_full.json",
]

_NE_DOIT_PAS_ETRE_BLOQUE = [
    "app/forge_videur.py",                                       # regulation / autorite
    "app/forge_resource_manager.py",
    "tools/forge_worktree.py",                                   # preuve
    "tests/nr/test_egress_profil_public_atteignable_nr.py",      # les NR SONT la credibilite
    "docs/skills/nokido/SKILL.md",                               # skills canoniques
    "docs/internal/cartographie_autopoietique_organes_computationnels.md",
    "design_handoff_nokido/SKILL.md",                            # design system
    "docs/launch/media/demo_feed_real.webm",                     # demonstration
    # les brouillons editoriaux restent publiables : le blocage vise les documents
    # OPERATIONNELS de docs/launch/, pas le domaine entier.
    "docs/launch/show_hn.md",
    "docs/launch/tweet_thread.md",
    "docs/launch/followup_24h.md",
    # amorcage d'un clone public : REQUIRED au sens runtime_criticality. Les bloquer
    # rendrait le snapshot public non amorcable -- un depot creux d'un autre genre.
    "seed/manifest.json",
    "seed/system_rules.jsonl",
    "seed/agent_profiles.jsonl",
    "seed/adr_records.jsonl",
    # owner 2026-09-15 (DECISION REAFFIRMEE apres mise en garde) : PUBLIC. Le RBAC
    # doit etre "la ET fonctionnel" dans le repo public -> le seed reel accompagne
    # le moteur. token_hash="" (aucun credential) ; topologie assumee par l'owner.
    "seed/forge_entities.jsonl",
    # scrub-source 2026-09-15 : le CODE du coeur et les TESTS portent des chemins owner,
    # mais on ne les BLOQUE PAS -- ce serait vider l'export. Ils relevent du slice SOURCE.
    "tools/nokido_acl_observabilite.py",
    "app/forge_resource_manager.py",
    "proxy_deno/core/supervisor.ts",
    "tests/nr/test_gardes_sans_passe_droit_nr.py",
    "tests/test_agy_mcp.py",
]


def test_securite_vie_privee_et_taille_restent_bloques_a_l_export_public():
    _, prof = E.resolve_profile(URL_PUBLICATION)
    bp = prof.get("blocked_paths") or []
    fuites = [p for p in _DOIT_ETRE_BLOQUE if not E._path_blocked(p, bp)]
    assert not fuites, f"sortiraient au public alors qu'ils ne doivent pas : {fuites}"


def test_ip_clearance_libere_un_document_NOMME_et_rien_d_autre():
    # Juge unique : un chemin libere nommement n'est pas bloque ; son voisin, si.
    motifs = ["docs/ip/**"]
    assert E._path_blocked("docs/ip/a.md", motifs, degages={"docs/ip/a.md"}) is None
    assert E._path_blocked("docs/ip/b.md", motifs, degages={"docs/ip/a.md"})
    assert E._path_blocked("docs/ip/b.md", motifs)


def test_chaque_liberation_ip_est_justifiee_et_bornee_a_docs_ip():
    _, prof = E.resolve_profile(URL_PUBLICATION)
    clearance = prof.get("ip_clearance")
    assert isinstance(clearance, dict), "profil public sans registre ip_clearance"
    for chemin, statut in clearance.items():
        assert chemin.startswith("docs/ip/") and "*" not in chemin, f"liberation non nominative : {chemin}"
        assert isinstance(statut, str) and len(statut.strip()) >= 10, f"liberation sans justification : {chemin}"


def test_ce_qui_fait_tourner_nokido_part_au_public():
    """Sens inverse, fige par la decision owner du 2026-09-30 : un blocage qui
    reapparaitrait sur ces chemins brideait la version publique en silence."""
    _, prof = E.resolve_profile(URL_PUBLICATION)
    bp = prof.get("blocked_paths") or []
    brides = [p for p in _DOIT_PARTIR if E._path_blocked(p, bp)]
    assert not brides, f"bloques alors que l'owner veut un Nokido non bride : {brides}"


def test_le_coeur_publiable_n_est_pas_capture_par_le_filtre():
    _, prof = E.resolve_profile(URL_PUBLICATION)
    bp = prof.get("blocked_paths") or []
    perdus = [p for p in _NE_DOIT_PAS_ETRE_BLOQUE if E._path_blocked(p, bp)]
    assert not perdus, (
        "le filtre capture la valeur a demontrer -- depot creux : "
        f"{perdus}. La publication est SUBSTANTIELLE, pas exhaustive : on retire la "
        "telemetrie de developpement et l'IP_HOLD, jamais l'architecture, la "
        "regulation, les preuves, les skills canoniques ni la demonstration."
    )


def test_le_cap_de_taille_du_profil_public_reste_a_5_mo():
    # Conserve sur decision owner du 2026-09-15 : un asset trop lourd est un probleme
    # de format (le .webm equivalent fait 3,16 Mo), jamais un motif de relacher un
    # garde anti-fuite.
    _, prof = E.resolve_profile(URL_PUBLICATION)
    assert prof.get("max_file_bytes") == 5_000_000, (
        "cap public modifie : toute evolution passe par une decision owner explicite"
    )


def test_l_ordre_protege_de_l_ambiguite_de_sous_chaine():
    # 'Nokido-labs/nokido' est une SOUS-CHAINE de 'Nokido-labs/nokido-dist'. Si l'entree
    # du depot de travail passait en premier, `resolve_profile` (premier match gagne)
    # capterait aussi les push de publication et les ferait partir en `private`, donc
    # sans aucun scrub. L'ordre EST le garde-fou : ce test le verrouille.
    nom, _ = E.resolve_profile(URL_TRAVAIL)
    assert nom == "private", f"{URL_TRAVAIL} resout en {nom!r} au lieu de 'private'"

    cles = list((E.load_manifest().get("remote_profiles") or {}).keys())
    assert "Nokido-labs/nokido-dist" in cles, "l'entree du depot de publication a disparu"
    i_dist = cles.index("Nokido-labs/nokido-dist")
    i_travail = next(
        (i for i, k in enumerate(cles) if k in URL_TRAVAIL and "dist" not in k),
        len(cles),
    )
    assert i_dist < i_travail, (
        "ordre inverse : l'entree du depot de travail precede celle du depot de "
        "publication et capterait ses push (premier match gagne)"
    )
