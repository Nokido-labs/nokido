import re
from typing import Tuple
from urllib.parse import urlparse


def validate_doi(s: str) -> bool:
    pattern = re.compile(r"^10\.\d{4,9}/[-._;()/:A-Z0-9]+$", re.IGNORECASE)
    return bool(pattern.fullmatch(s))


def validate_arxiv_id(s: str) -> bool:
    pattern = re.compile(r"^\d{4}\.\d{4,5}(v\d+)?$")
    return bool(pattern.fullmatch(s))


def validate_isbn(s: str) -> bool:
    s = re.sub(r"[-\s]", "", s)
    if len(s) == 10:
        total = 0
        for i in range(9):
            if not s[i].isdigit():
                return False
            total += int(s[i]) * (10 - i)
        check = s[9].upper()
        if check == "X":
            total += 10
        elif check.isdigit():
            total += int(check)
        else:
            return False
        return total % 11 == 0
    elif len(s) == 13:
        if not s.isdigit():
            return False
        total = 0
        for i in range(12):
            digit = int(s[i])
            total += digit * (1 if i % 2 == 0 else 3)
        check = (10 - (total % 10)) % 10
        return check == int(s[12])
    return False


def is_url_whitelisted(url: str) -> Tuple[bool, str]:
    try:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return False, "url_invalid"
        if parsed.scheme not in ("https", "http"):
            return False, "http_not_allowed"
        if parsed.scheme == "http" and not url.startswith("http://localhost"):
            return False, "http_not_allowed"

        domain = parsed.netloc.lower()
        blacklist = {"medium.com", "dev.to", "researchgate.net", "academia.edu"}
        if any(domain.endswith(f".{b}") or domain == b for b in blacklist):
            return False, "url_blacklist"

        whitelist_domains = {
            "arxiv.org",
            "doi.org",
            "oadoi.org",
            "openalex.org",
            "openlibrary.org",
            "semanticscholar.org",
            "scholar.google.com",
            "openreview.net",
            "neurips.cc",
            "aclanthology.org",
            "ijcai.org",
            "acm.org",
            "ieee.org",
            "springer.com",
            "sciencedirect.com",
            "github.com",
            "zenodo.org",
            "figshare.com",
            "osf.io",
            # Essais et publications fondatrices (Bush, Engelbart, Berners-Lee, etc.)
            "theatlantic.com",
            "scientificamerican.com",
            "dougengelbart.org",
            "kgbook.org",
            "maggieappleton.com",
            # Sites d'outils IA / no-code surveilles en veille
            "gumloop.com",
        }
        if any(domain.endswith(f".{w}") or domain == w for w in whitelist_domains):
            return True, ""
        if domain.endswith(".edu") or domain.endswith(".gov"):
            return True, ""
        return False, "url_blacklist"
    except:
        return False, "url_invalid"


def sanitize_content(text: str) -> Tuple[bool, str]:
    if not text:
        return True, ""
    pattern = re.compile(
        r"(?s)(?<!```)(?<!<!--)\b(ignore|disregard|override|you are now|act as|from now on)\b.*?(previous|instructions|rules)\b(?!```)(?!-->)",
        re.IGNORECASE,
    )
    if pattern.search(text):
        return False, "prompt_injection"
    return True, ""


def sanitize_entry(entry: dict) -> Tuple[bool, str]:
    if not isinstance(entry.get("title"), str) or len(entry["title"]) < 5:
        return False, "missing_required_field"
    if "triggered_by_idea_id" not in entry:
        return False, "missing_required_field"
    if entry.get("source_kind") not in {"human_paste", "agent_extract", "agent_research"}:
        return False, "invalid_source_kind"
    if entry.get("type") not in {"book", "paper", "url", "concept"}:
        return False, "invalid_type"

    if entry.get("doi") and not validate_doi(entry["doi"]):
        return False, "doi_invalid"

    for url_field in ("url", "pdf_url"):
        if entry.get(url_field):
            is_valid, reason = is_url_whitelisted(entry[url_field])
            if not is_valid:
                return False, reason

    if entry.get("description"):
        is_valid, reason = sanitize_content(entry["description"])
        if not is_valid:
            return False, reason

    return True, ""
