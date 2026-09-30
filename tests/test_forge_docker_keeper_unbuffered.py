"""tests/test_forge_docker_keeper_unbuffered.py — Test du flush ligne à ligne dans docker_keeper.
"""

import io
import logging
from tools.forge_docker_keeper import UnbufferedStreamHandler


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
