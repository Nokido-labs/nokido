"""tests/test_forge_docker_keeper_unbuffered.py — Test du flush ligne à ligne dans docker_keeper.

OBSOLETE (revue 28/10) : UnbufferedStreamHandler a ete retire de tools/forge_docker_keeper.py par le revert
4187e084a (02/08, abandon du pivot dockerd-WSL) ; ce test cassait depuis la collecte de toute passe Docker.
Conserve (jamais supprime) et saute avec son motif ; le journal actuel du keeper est _journal_fichier().
Une livraison qui RESSUSCITAIT la classe pour le faire passer a ete rejetee (c32eae794).
"""

import io
import logging

import pytest

pytest.skip("UnbufferedStreamHandler retire par le revert 4187e084a (02/08) ; voir la docstring du module",
            allow_module_level=True)

from tools.forge_docker_keeper import UnbufferedStreamHandler  # noqa: E402


class DummyFlushedStream(io.StringIO):
    def __init__(self):
        super().__init__()
        self.flushed = False

    def flush(self):
        super().flush()
        self.flushed = True


def test_unbuffered_stream_handler_flushes():
    stream = DummyFlushedStream()
    handler = UnbufferedStreamHandler(stream)
    logger = logging.getLogger("test_unbuffered")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    
    assert not stream.flushed
    logger.info("Test log entry")
    assert stream.flushed
    assert "Test log entry" in stream.getvalue()
