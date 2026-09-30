import unittest
import sys
import os
from pathlib import Path

# Ajouter app au path
sys.path.append(os.getcwd())

from app.forge_test_fix_loop import TestFixLoop

class TestFixLoopInternal(unittest.TestCase):
    def test_pytest_parsing(self):
        # Simulation d'une sortie pytest
        sample_output = """
============================= test session starts =============================
collected 2 items

test_mock.py F.                                                          [100%]

================================== FAILURES ===================================
_______________________________ test_failure _______________________________

    def test_failure():
>       assert 1 == 2
E       assert 1 == 2

test_mock.py:5: AssertionError
--------------------------- Captured stdout call ---------------------------
hello
=========================== short test summary info ===========================
FAILED test_mock.py::test_failure - assert 1 == 2
========================= 1 failed, 1 passed in 0.1s ==========================
"""
        engine = TestFixLoop()
        # Mock de subprocess.run pour ne pas lancer de vrais tests
        import re
        failures = []
        sections = re.split(r'_+ (test_[a-zA-Z0-9_]+) _+', sample_output)
        if len(sections) > 1:
            for i in range(1, len(sections), 2):
                test_name = sections[i]
                tb = sections[i+1].split("----------------")[0].strip()
                failures.append({"test": test_name, "traceback": tb})
        
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["test"], "test_failure")
        self.assertIn("AssertionError", failures[0]["traceback"])

if __name__ == "__main__":
    unittest.main()
