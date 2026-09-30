from typing import Dict, List, Optional

STOPWORDS_EN = {
    "the",
    "a",
    "an",
    "of",
    "in",
    "on",
    "at",
    "to",
    "for",
    "and",
    "or",
    "but",
    "with",
    "from",
    "by",
    "as",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "will",
    "would",
    "could",
    "should",
    "may",
    "might",
    "must",
    "shall",
    "can",
    "this",
    "that",
    "these",
    "those",
}

STOPWORDS_FR = {
    "le",
    "la",
    "les",
    "un",
    "une",
    "des",
    "du",
    "de",
    "et",
    "ou",
    "mais",
    "donc",
    "or",
    "car",
    "ni",
    "pour",
    "par",
    "sur",
    "sous",
    "dans",
    "avec",
    "sans",
    "vers",
    "chez",
    "depuis",
    "avant",
    "apres",
    "pendant",
    "ce",
    "cet",
    "cette",
    "ces",
    "mon",
    "ma",
    "mes",
    "ton",
    "ta",
    "tes",
    "son",
    "sa",
    "ses",
    "notre",
    "votre",
    "leur",
    "leurs",
}

STOPWORDS = STOPWORDS_EN | STOPWORDS_FR


def parse_lastname(author: str) -> str:
    """Extrait le nom de famille d un auteur formate "Prenom Nom" ou "Nom, Prenom"."""
    s = author.strip()
    if "," in s:
        return s.split(",")[0].strip()
    parts = s.split()
    return parts[-1] if parts else s


def refine_query(entry: Dict[str, Optional[str | List[str] | int]]) -> str:
    """
    Genere une requete SearXNG depuis une entry biblio.

    Args:
        entry: dict avec keys title (str), authors (list[str]|None), year (int|None)

    Returns:
        str: query 1-100 chars, sans chars problematiques (& = ?)

    Logique :
    1. Title : prendre 6 premiers mots significatifs (skip stopwords casefolded)
    2. Si authors non vide : ajouter parse_lastname(authors[0])
    3. Si year present : ajouter str(year)
    4. Joindre par espace
    5. Supprimer chars problematiques: & = ? (remplace par espace)
    6. Cap a 100 chars max
    7. Strip espaces multiples
    """
    title = entry.get("title", "")
    authors = entry.get("authors", [])
    year = entry.get("year")

    # Prendre les 6 premiers mots significatifs du titre
    title_words = [word for word in title.split() if word.casefold() not in STOPWORDS]
    title_short = " ".join(title_words[:6])

    # Ajouter le nom de famille du premier auteur si authors non vide
    if authors:
        title_short += " " + parse_lastname(authors[0])

    # Ajouter l'année si présente
    if year:
        title_short += " " + str(year)

    # Supprimer les caractères problématiques
    title_short = title_short.replace("&", " ").replace("=", " ").replace("?", " ")

    # Cap à 100 caractères max
    title_short = title_short[:100]

    # Strip les espaces multiples
    title_short = " ".join(title_short.split())

    return title_short
