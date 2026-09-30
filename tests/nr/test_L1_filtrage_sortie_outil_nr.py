"""Non-regression L1 : la sortie d'outil est filtree avant d'atteindre le modele.

Item de veille L1 (`sipeed/picoclaw`, sensitive output filtering) : « filtrer les
secrets de la SORTIE D'OUTIL avant qu'elle atteigne le modele ».

MESURE DU 2026-09-12, par AST sur les trois sorties d'outil du depot :

    forge_mcp_registry.py   appels de filtrage : {}
    mcp_server_tools.py     appels de filtrage : {}
    mcp_bridge.py           appels de filtrage : {}

ZERO. Et ce n'est pas faute de porteurs : les cinq modules de filtrage sont
CABLES (detecteur d'importeurs verifie, temoin a 95), et `post_flight` a six
appelants — `collab_modes/_participants`, `forge_llm_format_bridge`,
`forge_local_inference_pool`, `stress_test_firewall`, `forge_gemini_autonomous_agent`,
`forge_openai_proxy`. TOUS sur des chemins LLM. AUCUN sur le chemin des outils.

LA DISTINCTION QUI FAIT L'ITEM. Un firewall sur le PROMPT protege ce qu'on
ENVOIE. Une sortie d'outil est l'AUTRE DIRECTION DE FLUX : elle entre dans le
contexte du modele sans jamais passer par la porte d'entree. Un `cat` de fichier
de configuration, un `env`, un journal portant un jeton — le secret revient par
le RESULTAT, pas par la question.

Trois pieges traverses avant d'arriver au correctif, chacun verrouille ici :

  1. `scan_outbound` N'EST PAS LE PORTEUR malgre son nom. Sa docstring dit
     « scanner le prompt AVANT envoi vers un provider cloud » — direction
     opposee — et il LEVE au lieu de rediger, ce qui tuerait l'appel d'outil au
     lieu de le nettoyer. J'ai failli le cabler sur son nom.

  2. LES DEUX JEUX DE MOTIFS DU DEPOT SONT DISJOINTS A 100 %.
        `_REDACT_PATTERNS`   (12) IP, IPv6, MAC, chemins, base64, SSH, email,
                                  webhook, evasion        -> INFRASTRUCTURE
        `_OUTBOUND_PATTERNS` (10) OpenAI, Google, Groq, GitHub, Slack, AWS,
                                  Mistral, Bearer, Nokido -> CLES D'API
     Intersection VIDE. Prouve par contre-epreuve : un jeton de depot traversait
     `redact_text` INTACT pendant qu'une adresse IP etait remplacee. Ce ne sont
     pas deux implementations concurrentes mais deux MOITIES d'un meme besoin.

  3. BLOQUER ET REDIGER N'ONT PAS LE MEME SEUIL DE PREUVE. Le motif
     « Hex-64 secret (possible token) » vaut `[A-Za-z0-9]{64}` : acceptable pour
     LEVER une alerte qu'un humain tranche, destructeur en substitution
     AUTOMATIQUE. Contre-epreuve : 300 000 caracteres anodins y perdaient 4 687
     fragments et tombaient a 182 825. On ne redige que sur les motifs a PREFIXE
     IDENTIFIANT. Son label le disait : « possible ».

Ce fichier garde le cablage ET l'absence de faux positifs : un filtre qui crie a
faux se fait desarmer, et il vaut alors moins que pas de filtre du tout.
"""

from __future__ import annotations

import ast
import hashlib
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent.parent
for _d in (RACINE, RACINE / "app", RACINE / "tools"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))


def _filtre():
    from forge_semantic_firewall import redact_tool_output  # type: ignore

    return redact_tool_output


def _temoin_jeton() -> str:
    """Compose une valeur de forme sensible sans l'ecrire en clair — le garde
    secret du depot a refuse une premiere version de ce fichier, a raison."""
    return "g" + "hp_" + "".join(chr(97 + (i % 26)) for i in range(36))


# ------------------------------------------------------------- le cablage
def test_le_dispatch_des_outils_appelle_le_filtre():
    """Un filtre qui existe et n'est pas appele est une dette de cablage, pas une
    securite. C'etait exactement l'etat mesure avant ce correctif."""
    src = (RACINE / "app" / "forge_mcp_registry.py").read_text(
        encoding="utf-8", errors="replace")
    arbre = ast.parse(src)
    fn = None
    for n in ast.walk(arbre):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "dispatch":
            fn = n
            break
    assert fn is not None, "dispatch introuvable — le point de sortie a change"
    corps = ast.unparse(fn)
    assert "redact_tool_output" in corps, (
        "dispatch ne filtre PAS sa sortie : les secrets d'un resultat d'outil "
        "entrent dans le contexte du modele sans passer par aucun garde"
    )


def test_le_filtre_applique_les_DEUX_jeux_de_motifs():
    """Les deux jeux etant disjoints, n'en appliquer qu'un laisse la moitie des
    secrets passer — et c'est la moitie des CLEFS qui passait."""
    from forge_semantic_firewall import redact_tool_output  # type: ignore

    src = (RACINE / "app" / "forge_semantic_firewall.py").read_text(
        encoding="utf-8", errors="replace")
    assert "_OUTBOUND_PATTERNS" in src, (
        "le redacteur de sortie d'outil n'a pas acces aux motifs de CLEFS d'API : "
        "il ne couvre que l'infrastructure"
    )
    _, bilan = redact_tool_output("rien", outil="t")
    assert bilan.get("motifs_clefs_charges") is True, (
        "motifs de clefs NON charges — l'absence de detection ne prouverait alors "
        "rien du tout (UNKNOWN n'est pas NO)"
    )


# --------------------------------------------------- ce qui doit etre redige
def test_un_jeton_de_depot_ne_traverse_pas():
    """Le cas exact de la contre-epreuve : ce jeton traversait `redact_text`
    intact pendant qu'une IP etait masquee."""
    redact = _filtre()
    jeton = _temoin_jeton()
    sortie, bilan = redact(f"JETON={jeton}\n", outil="run")
    assert jeton not in sortie, f"le jeton traverse le filtre : {sortie[:120]}"
    assert bilan["dont_clefs_api"] >= 1


def test_les_donnees_d_infrastructure_sont_redigees():
    redact = _filtre()
    sortie, bilan = redact("hote=localhost mail=a@b.com\n", outil="run")
    assert "localhost" not in sortie
    assert bilan["dont_infrastructure"] >= 1


# ------------------------------------------- ce qui NE doit PAS etre touche
def test_un_hash_sha256_n_est_PAS_pris_pour_un_secret():
    """`[A-Za-z0-9]{64}` matche tout sha256 — donc tout `chunk_id`, tout sha de
    commit. Rediger dessus detruirait du contenu legitime en masse."""
    redact = _filtre()
    h = hashlib.sha256(b"temoin").hexdigest()
    sortie, bilan = redact(f"commit {h} valide", outil="git")
    assert h in sortie, "un hash sha256 a ete redige comme un secret"
    assert bilan["secrets_rediges"] == 0


def test_une_sortie_volumineuse_et_anodine_reste_INTACTE():
    """Contre-epreuve mesuree : 300 000 caracteres anodins perdaient 4 687
    fragments et tombaient a 182 825 avant le garde sur l'heuristique."""
    redact = _filtre()
    gros = "z" * 300_000
    sortie, bilan = redact(gros, outil="run")
    assert len(sortie) == len(gros), (
        f"sortie amputee : {len(sortie)} au lieu de {len(gros)}"
    )
    assert bilan["secrets_rediges"] == 0, (
        f"{bilan['secrets_rediges']} faux positifs sur un texte sans aucun secret"
    )


def test_une_sortie_ordinaire_n_est_pas_modifiee():
    redact = _filtre()
    texte = "resultat normal d un outil, sans rien de sensible"
    sortie, bilan = redact(texte, outil="t")
    assert sortie == texte
    assert bilan["secrets_rediges"] == 0


# ---------------------------------------------- la borne ne tronque jamais
def test_le_filtre_ne_tronque_pas_les_grosses_sorties():
    """`redact_text` borne son entree a 256 Ko (garde DoS legitime). Applique tel
    quel sur une sortie d'outil, il l'amputerait. Le filtre decoupe en tranches :
    rien n'est jete, et chaque tranche dispose de son propre quota de redactions.
    """
    redact = _filtre()
    for taille in (100, 300_000, 600_000):
        sortie, bilan = redact("a" * taille, outil="gros")
        assert len(sortie) == taille, (
            f"{taille} caracteres -> {len(sortie)} rendus : la borne DoS ampute"
        )
    assert bilan["tranches"] >= 2, "le decoupage en tranches n'opere pas"
