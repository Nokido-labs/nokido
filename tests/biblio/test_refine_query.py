import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from app.forge_biblio_refine import refine_query


class TestRefineQuery(unittest.TestCase):
    """Tests refine_query : 10 cas couvrant fonctionnalite + edge cases."""

    def test_entry_full(self):
        """Title + authors + year complets."""
        entry = {'title': 'This is a test title', 'authors': ['John Doe'], 'year': 2022}
        self.assertEqual(refine_query(entry), 'test title Doe 2022')

    def test_entry_full_english(self):
        """Stopwords EN bien filtres (the, quick stopword? non)."""
        entry = {'title': 'The quick brown fox', 'authors': ['Jane Doe'], 'year': 2022}
        self.assertEqual(refine_query(entry), 'quick brown fox Doe 2022')

    def test_entry_full_french(self):
        """Stopwords FR bien filtres (le, petit pas stopword)."""
        entry = {'title': 'Le petit chien', 'authors': ['Pierre Dupont'], 'year': 2022}
        self.assertEqual(refine_query(entry), 'petit chien Dupont 2022')

    def test_title_seul(self):
        """Title seul, pas authors ni year."""
        entry = {'title': 'This is a test title', 'authors': None, 'year': None}
        self.assertEqual(refine_query(entry), 'test title')

    def test_authors_seuls(self):
        """Authors seuls, title vide."""
        entry = {'title': '', 'authors': ['John Doe'], 'year': None}
        self.assertEqual(refine_query(entry), 'Doe')

    def test_author_format_nom_prenom(self):
        """Format "Nom, Prenom" -> parse extrait Nom."""
        entry = {'title': '', 'authors': ['Doe, John'], 'year': None}
        self.assertEqual(refine_query(entry), 'Doe')

    def test_author_format_compose(self):
        """Format "Prenom Nom Compose" -> parse extrait dernier mot."""
        entry = {'title': '', 'authors': ['John Smith Jr'], 'year': None}
        self.assertEqual(refine_query(entry), 'Jr')

    def test_title_avec_chars_speciaux(self):
        """Chars problematiques (?, &, =) cleanes."""
        entry = {'title': 'This is a test title ?', 'authors': None, 'year': None}
        result = refine_query(entry)
        self.assertNotIn('?', result)
        self.assertNotIn('&', result)
        self.assertNotIn('=', result)
        self.assertEqual(result, 'test title')

    def test_title_tres_long(self):
        """Title 200 chars -> output cape <= 100 chars."""
        long_title = ' '.join(['word' + str(i) for i in range(50)])
        entry = {'title': long_title, 'authors': None, 'year': None}
        result = refine_query(entry)
        self.assertLessEqual(len(result), 100)
        self.assertGreater(len(result), 0)

    def test_title_court(self):
        """Title court 1 mot, rien d autre."""
        entry = {'title': 'Hello', 'authors': None, 'year': None}
        self.assertEqual(refine_query(entry), 'Hello')


if __name__ == '__main__':
    unittest.main()
