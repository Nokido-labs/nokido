# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_semantic_firewall
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial

API ajoutee depuis le 2026-09-22 (premiere ligne de la docstring de chaque symbole) :
- `redact_donnees_personnelles` — Masque les donnees personnelles (telephone, IBAN, carte Luhn, NIR, email, civilite+nom, adresse postale, IP publique) par une etiquette HMAC IRREVERSIBLE. -> (texte, nombre).
"""
from __future__ import annotations
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)
"""
forge_semantic_firewall.py — Pare-feu sémantique 4 couches pour Nokido v16.5
==============================================================================
Orchestre les briques sécurité existantes en un pipeline cohérent.

Architecture :
  pre_flight(task, context, ring)  → DLP + canary + injection + ring_check
  post_flight(response, task)      → SSRF + hallucination + format + social_eng
  redact(text)                     → anonymisation avec table de mapping local
  restore(text, mapping)           → re-traduit les placeholders

Usage dans _smart_ask :
  fw = get_firewall()
  ok, reason, safe_task, mapping = fw.pre_flight(task, context, ring=2)
  if not ok:
      return f"[VETO_SECURITY] {reason}"
  result = await router.route(safe_task)
  ok2, reason2 = fw.post_flight(result.response, task)
  if not ok2:
      return await handle_drift(result.response, reason2)
  return fw.restore(result.response, mapping)
"""


import logging
import re
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Types
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class PreFlightResult:
    ok: bool
    reason: str = ""
    safe_task: str = ""  # task après redaction
    safe_context: str = ""  # context après redaction
    mapping: dict[str, str] = field(default_factory=dict)  # placeholder→original
    ring_blocked: bool = False
    injection: bool = False
    dlp_triggered: bool = False
    # AB4 (2026-09-12) : la marque REELLEMENT posee dans `safe_context`. Vide =
    # aucune marque — donc une absence de fuite en aval ne prouve RIEN. Sans ce
    # champ, l'appelant ne pouvait pas distinguer « rien n'a fui » de « rien
    # n'a ete verifiable ».
    canary: str = ""
    cognition: dict = field(default_factory=dict)  # AMI #11 : {predicted_success, expected_free_energy, confidence}


@dataclass
class PostFlightResult:
    ok: bool
    reason: str = ""
    tag: str = ""  # SSRF | INJECTION | HALLUCINATION | FORMAT | SOCIAL_ENG
    response: str = ""  # réponse (éventuellement annotée)
    cognition: dict = field(default_factory=dict)  # AMI #11 : {success, surprise, free_energy, high_surprise}


# ─────────────────────────────────────────────────────────────────────────────
# Patterns post-flight : social engineering + commandes dangereuses
# ─────────────────────────────────────────────────────────────────────────────
# Patterns SSRF complementaires (IPs meta-donnees cloud, localhost, IPv6)
_SSRF_EXTRA = [
    # Cloud metadata endpoints
    re.compile(r"169\.254\.169\.254", re.IGNORECASE),  # AWS / GCP / Azure
    re.compile(r"metadata\.google\.internal", re.IGNORECASE),
    re.compile(r"169\.254\.170\.2", re.IGNORECASE),  # AWS ECS
    # Outbound shell tools
    re.compile(r"(?:curl|wget|fetch|requests?\.get)\s+http", re.IGNORECASE),
    # Localhost — toutes formes : http/https, port optionnel, IPv4 127/8, IPv6 ::1, 0.0.0.0
    re.compile(r"https?://(?:localhost|127(?:\.\d{1,3}){3}|\[::1\]|0\.0\.0\.0)(?::\d+)?(?:[/\s]|$)", re.IGNORECASE),
    # IPv6 link-local et ULA
    re.compile(r"\b(?:fe80|fc[0-9a-f]{2}|fd[0-9a-f]{2})(?::[0-9a-f]{0,4}){1,7}\b", re.IGNORECASE),
    # CGNAT / Tailscale
    re.compile(r"\b100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b"),
    # Localhost formes courtes / hex / IPv4-mapped (audit 2026-06-15 : 127.1, 0x7f000001)
    re.compile(r"https?://127(?:\.\d{1,3}){0,2}(?::\d+)?(?:[/\s]|$)", re.IGNORECASE),
    re.compile(r"https?://0x[0-9a-f]+", re.IGNORECASE),
    re.compile(r"\[::ffff:(?:127|10|0|192\.168|169\.254|172\.)", re.IGNORECASE),
]

# DNS-rebinding wildcard services (résolvent vers une IP arbitraire/interne).
_SSRF_REBIND = re.compile(r"\b[\w-]+\.(?:nip\.io|sslip\.io|localtest\.me|traefik\.me)\b", re.IGNORECASE)


def _ssrf_obfuscated(text: str):
    """SSRF par IP OBFUSQUÉE (décimal/hex/IPv4-mapped) que les regex littérales ratent :
    http://2130706433, http://0x7f000001, [::ffff:127.0.0.1]. Parse l'hôte -> ipaddress
    (is_private/loopback/link_local/reserved). + services DNS-rebinding. Audit 2026-06-15."""
    import ipaddress as _ipa
    _rb = _SSRF_REBIND.search(text)
    if _rb:
        return _rb.group(0)[:60]
    for _m in re.finditer(r"https?://([^/\s:?#]+)", text, re.IGNORECASE):
        host = _m.group(1).strip("[]")
        cand = None
        try:
            if host.lower().startswith("0x"):
                cand = _ipa.ip_address(int(host, 16))
            elif host.isdigit():
                cand = _ipa.ip_address(int(host))
            elif host.lower().startswith("::ffff:"):
                cand = _ipa.ip_address(host[7:])
            else:
                cand = _ipa.ip_address(host)
        except (ValueError, OSError):
            cand = None
        if cand is not None and (cand.is_private or cand.is_loopback or cand.is_link_local
                                 or cand.is_reserved or cand.is_unspecified):
            return f"{host} -> {cand}"
    return None

# Social engineering : seulement les phrasings contextuels qui revelent
# une intention de subversion. Les API bare (os.remove, subprocess.run,
# rm -rf) sont des reponses DevOps legitimes et ne sont plus matchees.
_SOCIAL_ENG_PATTERNS = [
    re.compile(r"disable\s+(?:the\s+)?(?:sentinel|firewall|security|lock)", re.IGNORECASE),
    re.compile(r"désactive[rz]?\s+(?:la\s+)?(?:sentinelle|sécurité|pare-feu)", re.IGNORECASE),
    re.compile(r"ignore\s+(?:les\s+)?(?:règles|restrictions|garde-fous)", re.IGNORECASE),
    re.compile(r"bypass\s+(?:the\s+)?(?:sentinel|firewall|security|lock|guard)", re.IGNORECASE),
    re.compile(r"contourne[rz]?\s+(?:la\s+)?(?:sentinelle|sécurité|pare-feu)", re.IGNORECASE),
]

_HALLUCINATION_SIGNALS = [
    "je ne sais pas",
    "i don't know",
    "je suis incertain",
    "erreur interne",
    "hallucin",
    "i cannot",
    "je ne peux pas répondre",
]

# Langue inattendue : seuil eleve a 30 caracteres contigus pour eviter
# de bloquer une traduction ponctuelle, un nom propre, un nom produit ou
# une citation RAG d'advisory CVE en langue locale. Detecte les derives
# massives ou la reponse part dans une autre langue.
_SUSPICIOUS_LANGS = [
    re.compile(r"[а-яёА-ЯЁ]{30,}"),  # cyrillique (russe etc.)
    re.compile(r"[\u4e00-\u9fff]{30,}"),  # CJK inattendu
    re.compile(r"[\u0600-\u06ff]{30,}"),  # arabe
]


# ─────────────────────────────────────────────────────────────────────────────
# Redaction dynamique
# ─────────────────────────────────────────────────────────────────────────────

_REDACT_PATTERNS = [
    # IPs internes : RFC1918 + link-local (169.254/16, inclut 169.254.169.254 cloud metadata)
    # + CGNAT 100.64/10 (Tailscale) + loopback 127/8
    (
        re.compile(
            r"\b(?:192\.168|10\.\d+|172\.(?:1[6-9]|2\d|3[01])|169\.254|100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])|127\.\d+)\.\d+\.\d+\b"
        ),
        "IP_INTERNAL",
    ),
    # IP wildcard
    (re.compile(r"\b0\.0\.0\.0\b"), "IP_WILDCARD"),
    # IPv6 internes : link-local (fe80::), ULA (fc00::/7 = fc00..fdff), loopback ::1
    (
        re.compile(r"\b(?:fe80|fc[0-9a-f]{2}|fd[0-9a-f]{2})(?::[0-9a-f]{0,4}){1,7}\b|::1\b", re.IGNORECASE),
        "IPV6_INTERNAL",
    ),
    # MAC addresses
    (re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b"), "MAC_ADDRESS"),
    # Chemins Windows
    (re.compile(r'C:\\Users\\[^\s\\,\'"]+', re.IGNORECASE), "PATH_WIN"),
    # Chemins Unix
    (re.compile(r'/home/[^\s/,\'"]+', re.IGNORECASE), "PATH_UNIX"),
    # API keys / tokens (renforcé pour payload splitting)
    (
        re.compile(
            r"(?i)(api[_-]?key|token|secret|password|passwd|pwd|bearer)\s*[=:]\s*\S+"
            r"|bearer\s+[A-Za-z0-9._~+/=-]{8,}"  # 'Authorization: Bearer eyJ...' (espace, pas =)
            r"|eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+"  # JWT brut (header.payload.sig)
            r"|sk-[a-zA-Z0-9]{20,}", re.IGNORECASE
        ),
        "SECRET",
    ),
    # Base64 suspects : >=24 chars ET au moins UNE majuscule ET un chiffre (= vraie
    # donnée encodée à entropie, pas un long mot naturel). L'ancien `{12,}=?` flaguait
    # les mots FR longs (amelioration, investissement) + "appelants/deps" (le / était
    # dans le charset) -> faux positifs qui bloquaient des prompts bénins.
    (re.compile(r"\b(?=[A-Za-z0-9+/]*[A-Z])(?=[A-Za-z0-9+/]*[0-9])[A-Za-z0-9+/]{24,}={0,2}\b"), "BASE64_SUSPECT"),
    # SSH keys
    (re.compile(r"-----BEGIN [A-Z ]+KEY-----.*?-----END [A-Z ]+KEY-----", re.DOTALL), "SSH_KEY"),
    # Emails
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE), "EMAIL"),
    # Exfiltration Webhooks & Attacker domains
    (
        re.compile(r"https?://(?:attacker\.com|webhook\.site|requestbin\.com|pipedream\.net)\S*", re.IGNORECASE),
        "EXFIL_WEBHOOK",
    ),
    # Payload Splitting & Token requests
    (
        re.compile(
            r"(?i)(?:first|second|part|split)\s+part\s+is\s+['\"]?\S+['\"]?|give\s+me\s+.*(?:token|hmac|credential|secret|password)",
            re.IGNORECASE,
        ),
        "EVASION_ATTEMPT",
    ),
]


# DoS bound : firewall redact (cf secret_guard 13ec85e2). Borne taille + nb de
# redactions -> evite le wedge event-loop (replace O(n^2) sur payload force).
_MAX_REDACT_LEN = 262144
_MAX_REDACTIONS = 5000


def redact_tool_output(text: str, outil: str = "?", journal: bool = True) -> Tuple[str, Dict[str, object]]:
    """Redige une SORTIE D'OUTIL avant qu'elle n'atteigne le contexte du modele.

    L1 de la veille (`sipeed/picoclaw`, sensitive output filtering). MESURE du
    2026-09-12 : `forge_mcp_registry`, `mcp_server_tools` et `mcp_bridge` rendent
    leurs resultats d'outil avec **ZERO** appel de filtrage — mesure AST, les trois
    fichiers. Les cinq porteurs de filtrage sont pourtant cables, et `post_flight`
    a six appelants : tous sur des chemins LLM (collab, format_bridge,
    inference_pool, gemini_autonomous_agent, openai_proxy), AUCUN sur le chemin
    des outils.

    La distinction qui fait l'item : un firewall sur le PROMPT protege ce qu'on
    ENVOIE. Une sortie d'outil est l'AUTRE direction — elle entre dans le contexte
    sans passer par la porte d'entree. Un `cat` de fichier de configuration, un
    `env`, un journal contenant un jeton : le secret revient par le RESULTAT.

    ⚠️ Pourquoi ne pas appeler `redact_text` directement — deux bornes DoS qui,
    sur ce chemin, deviendraient des defauts :
      `text[:_MAX_REDACT_LEN]`  amputerait la sortie d'outil (256 Ko) ;
      `_MAX_REDACTIONS`         arrete de rediger au-dela du quota, donc les
                                secrets SUIVANTS passeraient en clair.
    On decoupe donc en tranches de la taille de la borne : rien n'est jete, et
    chaque tranche dispose de son propre quota. Les bornes restent, elles cessent
    d'etre des trous.

    ⚠️ Et `scan_outbound` n'est PAS le porteur : sa docstring dit « scanner le
    prompt AVANT envoi vers un provider cloud » — direction opposee — et il LEVE
    au lieu de rediger, ce qui tuerait l'appel d'outil au lieu de le nettoyer.

    Rend (texte_redige, bilan). Le bilan DIT ce qui a ete fait : un filtrage muet
    ne se distingue pas d'un filtrage absent.

    `journal=False` (2026-10-01) : pas d'avertissement PAR APPEL -- pour un appelant en lot
    (envoi d'embedding vers le cloud, des centaines de milliers de textes) qui agrege les
    bilans et dit UNE ligne par lot. Le bilan reste rendu : rien n'est tu, c'est regroupe.
    """
    texte = text or ""
    if not texte:
        return texte, {"outil": outil, "secrets_rediges": 0, "tranches": 0,
                       "quota_atteint": False, "longueur": 0}

    # MESURE 2026-09-12 : les deux jeux de motifs du depot sont DISJOINTS A 100 %.
    #   `_REDACT_PATTERNS`   (12) IP, IPv6, MAC, chemins, base64, SSH, email,
    #                             webhook, evasion            -> INFRASTRUCTURE
    #   `_OUTBOUND_PATTERNS` (10) OpenAI, Google, Groq, GitHub, Slack, AWS,
    #                             Mistral, Bearer, Nokido, hex-64 -> CLES D'API
    # Intersection VIDE. Ce ne sont pas deux implementations concurrentes, ce sont
    # deux MOITIES d'un meme besoin, chacune aveugle a l'autre : le redacteur ne
    # connait aucune clef d'API, le scanner aucune donnee d'infrastructure.
    # Prouve par contre-epreuve avant ce correctif : un jeton de depot traversait
    # `redact_text` INTACT pendant qu'une adresse IP etait remplacee.
    # Une sortie d'outil porte les DEUX (un `cat` de configuration donne la clef,
    # un `ifconfig` donne l'infra) : on applique donc les deux jeux, sans en creer
    # un troisieme.
    # ⚠️ BLOQUER et REDIGER n'ont pas le meme seuil de preuve.
    # `scan_outbound` LEVE : une heuristique large y est acceptable, un humain
    # tranche derriere. Rediger est AUTOMATIQUE et destructif : un faux positif
    # remplace du contenu legitime sans que personne ne le voie.
    # Mesure du 2026-09-12 : le motif « Hex-64 secret (possible token) » vaut
    # `[A-Za-z0-9]{64}` — il matche donc tout hash SHA-256, tout `chunk_id`, tout
    # sha de commit, et meme 64 chiffres d'affilee. Contre-epreuve : une sortie de
    # 300 000 caracteres anodins y perdait 4 687 fragments et tombait a 182 825.
    # On ne redige que sur les motifs a PREFIXE IDENTIFIANT (ghp_, sk-, xoxb-,
    # AKIA...), jamais sur une heuristique de forme. Son label le disait lui-meme :
    # « possible ».
    HEURISTIQUES_HORS_REDACTION = {"Hex-64 secret (possible token)"}

    motifs_cles = []
    ecartes_heuristiques = []
    try:
        from nokido_agent.app.forge_secret_guard import _OUTBOUND_PATTERNS  # type: ignore

        for motif, label in _OUTBOUND_PATTERNS:
            if label in HEURISTIQUES_HORS_REDACTION:
                ecartes_heuristiques.append(label)
                continue
            motifs_cles.append((motif, label))
    except Exception as e:  # noqa: BLE001
        # Jamais muet : un filtre amoindri qui se tait laisse croire a une sortie
        # propre. On le DIT, et le bilan le porte.
        logger.error(
            "[firewall.outil] motifs de CLEFS indisponibles (%s: %s) — la sortie de "
            "%s n'est filtree que sur l'infrastructure, PAS sur les clefs d'API",
            type(e).__name__, str(e)[:80], outil)

    morceaux = []
    total = 0
    cles_redigees = 0
    quota_atteint = False
    for debut in range(0, len(texte), _MAX_REDACT_LEN):
        tranche = texte[debut:debut + _MAX_REDACT_LEN]
        redige, mapping = redact_text(tranche)
        total += len(mapping)
        if len(mapping) >= _MAX_REDACTIONS:
            quota_atteint = True
        # Seconde passe : les clefs d'API, que le redacteur ignore.
        for motif, label in motifs_cles:
            def _remplace(m, _l=label):
                return "[%s_REDIGE]" % _l.upper().replace(" ", "_").replace("/", "_")
            redige, n = motif.subn(_remplace, redige)
            cles_redigees += n
        morceaux.append(redige)

    bilan: Dict[str, object] = {
        "outil": outil,
        "secrets_rediges": total + cles_redigees,
        "dont_infrastructure": total,
        "dont_clefs_api": cles_redigees,
        # UNKNOWN n'est pas NO : si les motifs de clefs n'ont pas pu etre charges,
        # l'absence de detection ne prouve rien.
        "motifs_clefs_charges": bool(motifs_cles),
        # Dit ce qu'on ne redige PAS : une couverture partielle qui se tait se
        # lit comme une couverture totale.
        "heuristiques_non_redigees": ecartes_heuristiques,
        "tranches": len(morceaux),
        "quota_atteint": quota_atteint,
        "longueur": len(texte),
    }
    if journal and (total or cles_redigees):
        logger.warning(
            "[firewall.outil] %d secret(s) rediges dans la sortie de %s "
            "(%d infra + %d clefs, %d caracteres, %d tranche(s))%s",
            total + cles_redigees, outil, total, cles_redigees, len(texte),
            len(morceaux),
            " — QUOTA ATTEINT, des secrets ont pu passer" if quota_atteint else "")
    return "".join(morceaux), bilan


def redact_text(text: str, session_id: str = "") -> Tuple[str, Dict[str, str]]:
    """
    Remplace les données sensibles par des placeholders numérotés.
    Retourne (texte_rédacté, mapping {placeholder: valeur_originale}).
    """
    text = text[:_MAX_REDACT_LEN]  # DoS bound : borne la taille redactee
    mapping: Dict[str, str] = {}
    counters: Dict[str, int] = {}
    result = text
    _n = 0

    for pattern, label in _REDACT_PATTERNS:
        for match in pattern.finditer(result):
            if _n >= _MAX_REDACTIONS:  # DoS bound : stop replace O(n^2)
                break
            original = match.group(0)
            if original in mapping.values():
                # Déjà remplacé — trouve son placeholder
                ph = next(k for k, v in mapping.items() if v == original)
            else:
                counters[label] = counters.get(label, 0) + 1
                ph = f"[{label}_{counters[label]}]"
                mapping[ph] = original
            result = result.replace(original, ph, 1)
            _n += 1

    return result, mapping


# Labels JAMAIS ré-injectés dans une sortie : un LLM injecté pourrait émettre le
# placeholder hors contexte -> restore = canal d'exfiltration du secret. Audit 2026-06-15.
_NEVER_RESTORE_LABELS = {"SECRET", "SSH_KEY", "EXFIL", "EXFIL_WEBHOOK", "API_KEY"}


def restore_text(text: str, mapping: Dict[str, str]) -> str:
    """Remplace les placeholders par leurs valeurs originales — SAUF les labels secrets
    (jamais ré-exposés dans une réponse), et seulement les placeholders réellement présents."""
    for ph, original in mapping.items():
        if ph not in text:
            continue
        label = ph.strip("[]").rsplit("_", 1)[0] if ph.startswith("[") else ""  # placeholders = [LABEL_n] (underscore), pas [LABEL:hash]
        if label in _NEVER_RESTORE_LABELS:
            continue  # ne ré-injecte JAMAIS un secret dans la sortie
        text = text.replace(ph, original)
    return text


# ─────────────────────────────────────────────────────────────────────────────
# DLP des LOGS — Tier 1 (2026-05-30)
# ─────────────────────────────────────────────────────────────────────────────
# Trou comblé : net_log / record_trace / anchor_* / critical_events persistaient
# le payload BRUT. Le firewall/membrane ne couvraient QUE l'egress cloud, pas
# l'écriture locale -> PII/secrets en clair dans SQLite/texte/RAG-FTS (searchable).
# redact_for_log() scrub EN LIGNE (regex pures, cheap, fail-safe). Tags HMAC
# DÉTERMINISTES ([EMAIL:7f3a]) : même valeur -> même tag = corrélation debug
# préservée, valeur JAMAIS stockée -> fuite disque/backup = rien en clair
# (irréversible-au-repos, plus sûr qu'un mapping réversible pour des logs).
# Scope : personnel + secrets (EMAIL/SECRET/SSH_KEY + CB-Luhn/IBAN/SSN). On
# GARDE IP/MAC/PATH (valeur debug, infra basse-sensibilité, déjà redacté cloud).
# Téléphone et NOMS (FP regex) -> Tier 2 (ML batch opf/presidio).
import hashlib as _hashlib
import hmac as _hmac
import os as _os

_PII_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]){11,30}\b")
_PII_SSN_US = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_PII_SSN_FR = re.compile(r"\b[12][ ]?\d{2}[ ]?\d{2}[ ]?\d{2}[ ]?\d{3}[ ]?\d{3}(?:[ ]?\d{2})?\b")
_PII_CC = re.compile(r"\b(?:\d[ -]?){13,19}\b")  # candidat -> validé Luhn avant tag
# Tier 1.5 léger (inspiré presidio recognizers + opf private_person/phone, ZÉRO
# modèle) : téléphone format strict (+ international ou 0X français = peu de FP)
# + noms ancrés sur un TITRE (M./Mme/Dr… = haute précision sans NER).
_PII_PHONE = re.compile(r"(?:(?<![\w+])\+\d{1,3}[ .-]?\d(?:[ .-]?\d){6,12}|\b0[1-9](?:[ .-]?\d{2}){4}\b)")
_PII_NAME = re.compile(
    r"\b(?:M\.|MM\.|Mr|Mrs|Ms|Mme|Mlle|Madame|Monsieur|Mademoiselle|Dr|Pr)\.?\s+"
    r"[A-ZÀ-Ý][a-zà-ÿ'-]+(?:\s+[A-ZÀ-Ý][a-zà-ÿ'-]+){0,2}"
)

_LOG_PII_LABELS = {"EMAIL", "SECRET", "SSH_KEY"}
_LOG_REDACT_PATTERNS = [(p, l) for (p, l) in _REDACT_PATTERNS if l in _LOG_PII_LABELS] + [
    (_PII_IBAN, "IBAN"),
    (_PII_SSN_US, "SSN"),
    (_PII_SSN_FR, "SSN"),
    (_PII_PHONE, "PHONE"),
    (_PII_NAME, "NAME"),
]


def _luhn_ok(s: str) -> bool:
    d = [int(c) for c in s if c.isdigit()]
    if not (13 <= len(d) <= 19):
        return False
    tot = 0
    for i, x in enumerate(reversed(d)):
        if i % 2 == 1:
            x *= 2
            if x > 9:
                x -= 9
        tot += x
    return tot % 10 == 0


def _vault_path():
    from pathlib import Path

    return Path(__file__).resolve().parent.parent / "sandbox" / "redaction_vault.db"


def _vault_store(tag: str, value: str) -> None:
    """Réversibilité opt-in : stocke tag->valeur (DPAPI machine-scope, réutilise
    forge_machine_vault._protect) dans redaction_vault.db. Pruné >7j par
    forge_log_retention -> au-delà, irréversible-au-repos. Fail-safe."""
    try:
        import sqlite3
        import time as _t

        from nokido_agent.app.forge_machine_vault import _protect

        p = _vault_path()
        p.parent.mkdir(exist_ok=True)
        con = sqlite3.connect(str(p))
        con.execute("CREATE TABLE IF NOT EXISTS redaction_vault (tag TEXT PRIMARY KEY, enc BLOB, ts REAL)")
        con.execute(
            "INSERT OR IGNORE INTO redaction_vault(tag, enc, ts) VALUES (?,?,?)",
            (tag, _protect(value.encode("utf-8", "replace")), _t.time()),
        )
        con.commit()
        con.close()
    except Exception:
        pass


def deanonymize_log(text: str) -> str:
    """Restaure les valeurs des tags [LABEL:hash] depuis le vault DPAPI (debug
    autorisé local). Tag absent (pruné >7j ou irréversible) -> laissé tel quel."""
    try:
        import re as _re
        import sqlite3

        from nokido_agent.app.forge_machine_vault import _unprotect

        p = _vault_path()
        if not p.exists():
            return text
        con = sqlite3.connect(str(p))
        rows = dict(con.execute("SELECT tag, enc FROM redaction_vault").fetchall())
        con.close()

        def _sub(m):
            enc = rows.get(m.group(0))
            if enc is None:
                return m.group(0)
            try:
                return _unprotect(enc).decode("utf-8", "replace")
            except Exception:
                return m.group(0)

        return _re.sub(r"\[[A-Z]+:[0-9a-f]{6,16}\]", _sub, text)  # 6=legacy, 16=HMAC keyed
    except Exception:
        return text


_LOG_HMAC_KEY: bytes | None = None
_LOG_SALT: str = ""


def set_log_salt(salt: str) -> None:
    """Définit le sel global (ex: mission_id) pour les tags de log.
    Évite la corrélation inter-missions du même PII dans les logs."""
    global _LOG_SALT
    _LOG_SALT = salt


def _log_hmac_key() -> bytes:
    """Clé HMAC machine-scope (forge_machine_vault, DPAPI). Sans clé keyed, le tag =
    SHA tronqué non-keyed = brute-forçable offline sur PII faible-entropie (audit
    2026-06-15 CRITICAL). Fail-safe : clé éphémère process si le vault est indispo."""
    global _LOG_HMAC_KEY
    if _LOG_HMAC_KEY is not None:
        return _LOG_HMAC_KEY
    key = None
    try:
        import base64 as _b64
        from nokido_agent.app.forge_secrets import get_secret as _gs
        # Le GUICHET (2b-2, 2026-09-28) : nom reserve, coffre reserve lu d'abord. Le
        # `vault_get` direct ne voyait jamais le coffre reserve.
        existing = _gs("firewall_log_hmac")
        if existing:
            key = _b64.b64decode(existing)
        # Sinon : cle EPHEMERE du process (ci-dessous), JAMAIS reecrite au coffre machine
        # (2b-6, 2026-09-28). Hors SYSTEM le guichet tait ce nom par politique : l'ancien
        # `vault_set` aurait remplace la copie lisible par tous a chaque demarrage d'un
        # process bac a sable -- et « illisible » n'est pas « absent ».
    except Exception:  # noqa: BLE001
        pass
    _LOG_HMAC_KEY = key or _os.urandom(32)  # fallback éphémère (jamais de SHA nu non-keyed)
    return _LOG_HMAC_KEY


def _log_tag(label: str, value: str, reversible: bool = False) -> str:
    # HMAC keyed + 32 hex (128 bits) au lieu d'un SHA nu tronqué 24 bits (audit CRITICAL :
    # PII faible-entropie brute-forçable offline depuis les logs). On inclut _LOG_SALT
    # pour casser la corrélation inter-missions.
    global _LOG_SALT
    msg = f"{_LOG_SALT}:{label}:{value}".encode("utf-8", "replace")
    digest = _hmac.new(_log_hmac_key(), msg, _hashlib.sha256).hexdigest()
    tag = f"[{label}:{digest[:32]}]"
    if reversible:
        _vault_store(tag, value)
    return tag


def redact_str_for_log(text: str, reversible: bool = False) -> str:
    """Pseudonymise une chaîne pour persistance log. Tag HMAC déterministe.
    reversible=False (défaut) = irréversible (valeur jamais stockée).
    reversible=True = valeur stockée chiffrée DPAPI <7j (deanonymize_log)."""
    if not text or not isinstance(text, str):
        return text
    out = text
    # CB d'abord : valider Luhn -> évite de taguer tout nombre de 13-19 chiffres
    out = _PII_CC.sub(
        lambda m: _log_tag("CB", m.group(0), reversible) if _luhn_ok(m.group(0)) else m.group(0), out
    )
    for pattern, label in _LOG_REDACT_PATTERNS:
        out = pattern.sub(lambda m, _l=label: _log_tag(_l, m.group(0), reversible), out)
    return out


# ─── Donnees PERSONNELLES d'une copie destinee au RAG (decision owner 24/09) ───
# MESURE du 24/09 sur exemples fictifs : ni `redact_text`, ni `redact_tool_output`, ni
# `forge_conv_sanitizer`, ni `forge_hormones` ne masquaient telephone, IBAN, carte, NIR ;
# `redact_str_for_log` (ci-dessus) les masquait deja -- on la REUTILISE. Il lui manquait
# l'ADRESSE postale et l'IP PUBLIQUE (les IP internes sont a `redact_text`) : complement
# ci-dessous, etiquete comme elle (HMAC irreversible), sans toucher `_LOG_REDACT_PATTERNS`
# dont les journaux dependent tels quels.
_PII_COMPLEMENT = [
    (re.compile(r"(?i)\b\d{1,4}(?:\s?(?:bis|ter))?,?\s+(?:rue|avenue|av\.|boulevard|bd|place|chemin|"
                r"all[ée]e|impasse|route|quai|cours|square|voie)\s+[^\n,;]{2,60}?"
                r"(?:,?\s*\d{5}\s+[A-Za-zÀ-ÿ' -]{2,40})?(?=[\n,;.]|$)"), "ADRESSE"),
    (re.compile(r"\b(?!(?:10|127|0)\.)(?!192\.168\.)(?!172\.(?:1[6-9]|2\d|3[01])\.)(?!169\.254\.)"
                r"(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}\b"), "IP_PUBLIQUE"),
]
_TAG_PII = re.compile(r"\[[A-Z_]+:[0-9a-f]{32}\]")


def redact_donnees_personnelles(text: str) -> Tuple[str, int]:
    """Masque les donnees personnelles (telephone, IBAN, carte Luhn, NIR, email, civilite+nom,
    adresse postale, IP publique) par une etiquette HMAC IRREVERSIBLE. -> (texte, nombre)."""
    if not text or not isinstance(text, str):
        return text, 0
    avant = len(_TAG_PII.findall(text))
    out = redact_str_for_log(text, reversible=False)
    for motif, label in _PII_COMPLEMENT:
        out = motif.sub(lambda m, _l=label: _log_tag(_l, m.group(0), False), out)
    return out, len(_TAG_PII.findall(out)) - avant


def redact_for_log(obj, reversible: bool = False):
    """Scrub PII/secrets avant persistance log. Récursif (str/dict/list),
    fail-safe (jamais d'exception — le logging ne doit jamais casser)."""
    try:
        if isinstance(obj, str):
            return redact_str_for_log(obj, reversible)
        if isinstance(obj, dict):
            return {k: redact_for_log(v, reversible) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [redact_for_log(v, reversible) for v in obj]
        return obj
    except Exception:
        return obj


# ─────────────────────────────────────────────────────────────────────────────
# SemanticFirewall
# ─────────────────────────────────────────────────────────────────────────────


class SemanticFirewall:
    """
    Pare-feu sémantique 4 couches.

    Couche 1 — pre_flight : DLP + ring_check + injection
    Couche 2 — redact     : anonymisation avant envoi cloud
    Couche 3 — post_flight: SSRF + social_eng + hallucination + format
    Couche 4 — restore    : re-traduction des placeholders
    """

    def __init__(self) -> None:
        """Init."""
        self._canaries: Dict[str, str] = {}  # session_id → canary
        self._rrf_threshold = 0.85  # Seuil de fiabilité sémantique hyper-agressif
        self._stats = {
            "pre_blocked": 0,
            "post_blocked": 0,
            "dlp_hits": 0,
            "injection_hits": 0,
            "ssrf_hits": 0,
            "social_eng_hits": 0,
            "rrf_low_confidence": 0,
        }

    def set_rrf_threshold(self, value: float):
        """Ajuste le seuil de confiance sémantique (0.0-1.0)."""
        self._rrf_threshold = max(0.0, min(1.0, value))
        logger.info(f"[firewall] RRF threshold updated to {self._rrf_threshold}")

    # ── Couche 1 : Pre-flight ─────────────────────────────────────────────────

    def pre_flight(
        self,
        task: str,
        context: str = "",
        ring: int = 3,
        session_id: str = "",
        provider: str = "auto",
    ) -> PreFlightResult:
        """
        Vérifie task + context avant envoi au LLM.

        1. Ring check : ring=0 → blocage total
        2. Injection  : detect_injection() sur task
        3. DLP        : _redact sur task, filter_rag_context pour context
        4. Canary     : génère et stocke un canary pour la session
        """
        # ── 0. Kill-switch sémantique (corrigibility) ────────────────────────
        # network_kill actif → AUCUN egress cloud. Câblé sur le waist UNIQUE :
        # seule façon de rendre le kill-switch effectif (avant = drapeau orphelin
        # lu nulle part). trigger_kill_switch() devient réellement coupant.
        if provider not in ("local", "ollama"):
            try:
                from nokido_agent.app.forge_opsec import is_network_kill

                if is_network_kill():
                    self._stats["pre_blocked"] += 1
                    logger.warning("[firewall] KILL-SWITCH actif (network_kill) — egress cloud bloque")
                    return PreFlightResult(
                        ok=False,
                        reason="Kill-switch semantique actif (network_kill) — egress cloud bloque",
                    )
            except Exception as e:
                logger.warning(f"[firewall] kill-switch check indisponible (fail-open): {e}")

        # ── 1. Ring check ─────────────────────────────────────────────────────
        # Audit 2026-06-16 : ring <= 0 (SYSTEM et MASTER) interdit de sortie cloud.
        if ring <= 0:
            self._stats["pre_blocked"] += 1
            logger.warning(f"[firewall] Ring {ring} bloqué (interdit de sortie cloud)")
            return PreFlightResult(ok=False, reason=f"Ring {ring} — données source interdites de sortie", ring_blocked=True)

        # Cloud uniquement pour ring check DLP (local = ok)
        _is_cloud = provider not in ("local", "ollama")

        # ── 2. Injection dans le prompt ───────────────────────────────────────
        try:
            from nokido_agent.app.forge_prompt_guard import detect_injection

            inj = detect_injection(task)
            if inj.detected:
                self._stats["injection_hits"] += 1
                self._stats["pre_blocked"] += 1
                logger.warning(f"[firewall] Injection dans prompt: {inj.pattern[:60]}")
                return PreFlightResult(
                    ok=False,
                    reason=f"Prompt injection détectée : {inj.pattern[:60]}",
                    injection=True,
                )
        except Exception as e:
            logger.debug(f"[firewall] detect_injection skip: {e}")

        # ── 3. DLP ────────────────────────────────────────────────────────────
        safe_task = task
        safe_context = context
        mapping: Dict[str, str] = {}

        if _is_cloud:
            # redact_text est un pipeline de regex pures (pas d'I/O), aucun
            # except recovery utile : on appelle directement.
            safe_task, m1 = redact_text(task, session_id)
            mapping.update(m1)

            if context:
                try:
                    from nokido_agent.app.forge_conv_sanitizer import _redact as _r

                    safe_context = _r(context)
                    _, m2 = redact_text(context, session_id)
                    mapping.update(m2)
                except Exception:
                    safe_context, m2 = redact_text(context, session_id)
                    mapping.update(m2)

            if mapping:
                self._stats["dlp_hits"] += 1
                logger.info(f"[firewall] DLP: {len(mapping)} substitutions")
                # BLOQUAGE SI CLOUD + DONNEES SENSIBLES
                if _is_cloud:
                    return PreFlightResult(
                        ok=False,
                        reason=f"DLP: {len(mapping)} données sensibles détectées. Utilisez un modèle local.",
                        dlp_triggered=True,
                        mapping=mapping,
                    )

        # ── 4. Canary ─────────────────────────────────────────────────────────
        # AB4 (2026-09-12) : le canari etait genere, range… et JAMAIS insere dans
        # ce qui part au modele. `post_flight` cherchait donc dans la reponse une
        # chaine que le modele n'avait jamais vue : garde inerte par construction.
        # `_canari_emis` porte desormais la marque jusqu'a son INSERTION, plus bas.
        _canari_emis = ""
        if _is_cloud and session_id:
            try:
                from nokido_agent.app.forge_prompt_guard import generate_canary

                canary = generate_canary(session_id)
                self._canaries[session_id] = canary
                _canari_emis = canary
            except Exception:
                pass

        # ── 5. Cognition AMI (#11) : perception + inférence active + MPC ─────────
        # Léger (~1ms SQLite, NumPy RAM, 0 réseau/GPU), best-effort, JAMAIS bloquant.
        # predict = percevoir(method/target) + inférer l'issue ; expected_free_energy
        # = MPC (sélection d'action = minimiser E[F], LeCun/Friston). Pas d'embed sur
        # le chemin chaud (perception dense world_model 4096D = raffinement futur).
        cognition: Dict[str, object] = {}
        try:
            from nokido_agent.app.forge_active_inference import expected_free_energy as _efe
            from nokido_agent.app.forge_active_inference import predict as _ai_predict

            _method = "llm_flight"  # clé générique : la boucle FEP (predict pre / observe post) DOIT matcher
            _pred = _ai_predict(method=_method, target=(task or "")[:40])
            cognition = {
                "predicted_success": _pred.get("predicted_p_success", 0.5),
                "confidence": _pred.get("confidence", 0.0),
                "expected_free_energy": _efe(_method, target=(task or "")[:40]),
                "method": _method,
            }
            if cognition["confidence"] >= 0.3 and cognition["predicted_success"] < 0.25:
                logger.info(f"[firewall][AMI] basse confiance succes {cognition['predicted_success']:.2f} "
                            f"E[F]={cognition['expected_free_energy']:.2f} sur '{(task or '')[:50]}'")
        except Exception as _e:
            logger.debug(f"[firewall][AMI] pre cognition skip: {_e}")

        # ── 6. CacheAligner (waist universel) ─────────────────────────────────
        # Stabilise le PRÉFIXE (retire le volatil: timestamp/uuid/trace_id/date-du-
        # jour) pour HIT le prompt-cache provider sur TOUT egress passant par le
        # firewall, y compris forge_openai_proxy:7777 qui ne câblait NI align NI
        # cache_control (dead-zone mesurée 2026-06-17 = "historique re-facturé ×N").
        # Provider-agnostic, N'INJECTE AUCUN cache_control (ça reste gated par-
        # provider côté adaptateur, ex ClaudeOpenRouter). Fail-open, idempotent.
        try:
            from nokido_agent.app.forge_cache_aligner import align as _ca_align

            safe_context, safe_task, _ = _ca_align(safe_context, safe_task)
        except Exception:
            pass

        # AB4 — INSERTION de la marque, apres l'aligneur de cache : le bloc
        # sentinelle doit rester en FIN de contexte (meme place que dans
        # `build_safe_system`), et l'aligneur reordonne ce qui le precede.
        # La forme vient de `bloc_canari` : un seul emetteur de forme, sinon les
        # deux chemins divergent et le verificateur n'en reconnait plus qu'un.
        if _canari_emis:
            try:
                from nokido_agent.app.forge_prompt_guard import bloc_canari

                safe_context = (safe_context or "") + bloc_canari(_canari_emis)
            except Exception as _exc:
                logger.error(
                    "[firewall] canari genere mais NON insere (%s) — post_flight "
                    "ne pourra rien prouver ; on ne l'annonce donc pas",
                    type(_exc).__name__)
                _canari_emis = ""

        return PreFlightResult(
            ok=True,
            safe_task=safe_task,
            safe_context=safe_context,
            mapping=mapping,
            dlp_triggered=bool(mapping),
            cognition=cognition,
            canary=_canari_emis,
        )

    # ── Couche 3 : Post-flight ────────────────────────────────────────────────

    def post_flight(
        self,
        response: str,
        task: str = "",
        session_id: str = "",
        expected_fmt: str = "text",  # text | json | code
    ) -> PostFlightResult:
        """
        Vérifie la réponse du LLM avant de la retourner à l'utilisateur.

        1. SSRF / beacon
        2. Injection dans la réponse (social engineering)
        3. Canary leak
        4. Hallucination signals
        5. Langue inattendue
        6. Validation format (si expected_fmt=json)
        """
        if not response:
            return PostFlightResult(ok=True, response=response)

        # ── 1. SSRF (cloud metadata, localhost, IPv6, CGNAT, outbound shell) ─────
        # _SSRF_EXTRA est le detecteur unique : couvre cloud metadata (AWS/GCP/Azure),
        # localhost (toutes formes : http/https, port optionnel, IPv4 127/8, IPv6 ::1,
        # 0.0.0.0), IPv6 link-local/ULA, CGNAT/Tailscale, outbound shell tools.
        for _sp in _SSRF_EXTRA:
            _m = _sp.search(response)
            if _m:
                self._stats["ssrf_hits"] += 1
                self._stats["post_blocked"] += 1
                return PostFlightResult(
                    ok=False,
                    tag="SSRF",
                    reason=f"SSRF détecté: {_m.group(0)[:60]}",
                    response=response,
                )
        _obf = _ssrf_obfuscated(response)  # IP obfusquée (décimal/hex/mapped) + DNS-rebind
        if _obf:
            self._stats["ssrf_hits"] += 1
            self._stats["post_blocked"] += 1
            return PostFlightResult(ok=False, tag="SSRF",
                                    reason=f"SSRF IP obfusquée: {_obf}", response=response)

        # ── 2. Social engineering / commandes dangereuses ─────────────────────
        for pat in _SOCIAL_ENG_PATTERNS:
            m = pat.search(response)
            if m:
                self._stats["social_eng_hits"] += 1
                self._stats["post_blocked"] += 1
                snippet = m.group(0)[:60]
                logger.warning(f"[firewall] Social eng dans réponse: {snippet}")
                return PostFlightResult(
                    ok=False,
                    tag="SOCIAL_ENG",
                    reason=f"Tentative social engineering: {snippet}",
                    response=f"[SUSPICIOUS:{snippet}]\n{response}",
                )

        # ── 3. Canary leak ────────────────────────────────────────────────────
        # Cleanup : retire le canary du registre (succes OU echec) pour eviter
        # la croissance non bornee de _CANARY_REGISTRY a chaque cloud call.
        if session_id and session_id in self._canaries:
            canary_value = self._canaries.pop(session_id, "")
            try:
                from nokido_agent.app.forge_prompt_guard import check_canary_leak, clear_canary

                leaked = check_canary_leak(response, canary_value)
                clear_canary(canary_value)  # systematique
                if leaked:
                    self._stats["post_blocked"] += 1
                    return PostFlightResult(
                        ok=False,
                        tag="CANARY_LEAK",
                        reason="Fuite de canary — le LLM a révélé ses instructions",
                        response=response,
                    )
            except Exception:
                pass

        # ── 4. Hallucination signals ──────────────────────────────────────────
        resp_low = response.lower()
        for sig in _HALLUCINATION_SIGNALS:
            if sig in resp_low:
                logger.info(f"[firewall] Signal hallucination: {sig}")
                return PostFlightResult(
                    ok=False,
                    tag="HALLUCINATION",
                    reason=f"Signal de confusion LLM: '{sig}'",
                    response=response,
                )

        # ── 5. Langue inattendue ─────────────────────────────────────────────
        for lang_pat in _SUSPICIOUS_LANGS:
            if lang_pat.search(response):
                logger.warning("[firewall] Langue inattendue dans réponse")
                return PostFlightResult(
                    ok=False,
                    tag="LANG",
                    reason="Langue non-latine inattendue dans la réponse",
                    response=response,
                )

        # ── 6. Validation format JSON ─────────────────────────────────────────
        # Utilise raw_decode() pour scanner depuis chaque '{' ou '[' jusqu'a
        # trouver un JSON valide. Tolere du prose autour, des fences markdown,
        # ou plusieurs blocs JSON dans la reponse.
        if expected_fmt == "json":
            import json as _json

            stripped = response.strip()
            # Strip markdown code fences si presents
            stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
            stripped = re.sub(r"\s*```$", "", stripped)

            decoder = _json.JSONDecoder()
            parsed = False
            last_err: Optional[Exception] = None
            for i, ch in enumerate(stripped):
                if ch in "{[":
                    try:
                        decoder.raw_decode(stripped[i:])
                        parsed = True
                        break
                    except _json.JSONDecodeError as e:
                        last_err = e
                        continue

            if not parsed:
                msg = str(last_err) if last_err else "Pas de JSON trouve"
                logger.warning(f"[firewall] Format JSON invalide: {msg}")
                return PostFlightResult(
                    ok=False,
                    tag="FORMAT",
                    reason=f"JSON invalide ou absent: {msg}",
                    response=response,
                )

        # ── 7. Cognition AMI (#11) : OBSERVE = fermer la boucle FEP ──────────────
        # La réponse a passé tous les gates -> délégation réussie. observe() calcule la
        # SURPRISE (prédit vs réel) et met à jour le modèle génératif (inférence active
        # = apprentissage). Léger (~5ms SQLite), best-effort, JAMAIS bloquant. Clé
        # "llm_flight" = matche pre_flight.predict (la boucle se ferme). high_surprise
        # -> annotation/stat non-bloquante.
        cognition: Dict[str, object] = {}
        try:
            from nokido_agent.app.forge_active_inference import observe as _ai_observe

            _obs = _ai_observe(method="llm_flight", success=True, time_s=1.0, elegance=1.0)
            cognition = {
                "success": True,
                "surprise": _obs.get("surprise"),
                "free_energy": _obs.get("free_energy"),
                "high_surprise": _obs.get("high_surprise", False),
            }
            # Gemini #11 : valeur épistémique = opportunité d'apprentissage de cet outcome.
            # Haute si surprise haute -> pondère l'anchor (ne pas perdre la leçon).
            try:
                from nokido_agent.app.forge_active_inference import epistemic_value as _epi

                cognition["epistemic_value"] = _epi(
                    float(_obs.get("surprise") or 0.0), int(_obs.get("n", 0) or 0)
                )
            except Exception:
                pass
            if cognition.get("high_surprise"):
                self._stats["ami_high_surprise"] = self._stats.get("ami_high_surprise", 0) + 1
                logger.info(f"[firewall][AMI] high surprise post-flight "
                            f"(F={cognition.get('free_energy')}) -> modele generatif mis a jour")
        except Exception as _e:
            logger.debug(f"[firewall][AMI] post observe skip: {_e}")

        return PostFlightResult(ok=True, response=response, cognition=cognition)

    # ── Couche 4 : Restore ────────────────────────────────────────────────────

    def restore(self, text: str, mapping: Dict[str, str]) -> str:
        """Re-traduit les placeholders DLP dans la réponse LLM."""
        return restore_text(text, mapping)

    # ── Stats ─────────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        """Stats."""
        return dict(self._stats)

    def reset_stats(self) -> None:
        """Reset stats."""
        for k in self._stats:
            self._stats[k] = 0


# ─────────────────────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────────────────────

_FW: Optional[SemanticFirewall] = None


def get_firewall() -> SemanticFirewall:
    """Get firewall."""
    global _FW
    if _FW is None:
        _FW = SemanticFirewall()
    return _FW
