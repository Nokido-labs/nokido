import asyncio
import json


class ByteRouter:
    SENTINEL_MAP = {
        b"\xc2\xa7PING": "ping",
        b"\xc2\xa7EXEC": "exec",
        b"\xc2\xa7ROUT": "route",   # 6 bytes prefix match
        b"\xc2\xa7FAST": "fast",
        b"\xc2\xa7COST": "cost",
        b"\xc2\xa7STAT": "status",
        b"\xc2\xa7STRE": "stream",
        b"\xc2\xa7RESE": "reset",
    }

    def __init__(self, ring: int = 2):
        self.ring = ring

    async def peek_and_route(self, data: bytes) -> tuple[str, bytes]:
        if len(data) < 6:
            return ("raw", data)

        prefix = data[:6]
        for sentinel, action in self.SENTINEL_MAP.items():
            if prefix == sentinel:
                return (action, data[len(sentinel):])

        # Fallback: JSON
        try:
            json.loads(data.decode("utf-8"))
            return ("json", data)
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass

        return ("raw", data)


if __name__ == "__main__":
    async def main():
        router = ByteRouter(ring=0)

        cases = [
            (b"\xc2\xa7PING hello", "ping"),
            (b"\xc2\xa7EXEC code", "exec"),
            (b'{"key": "value"}', "json"),
            (b"\x00\x01\x02raw", "raw"),
        ]
        for data, expected in cases:
            action, payload = await router.peek_and_route(data)
            status = "OK" if action == expected else f"FAIL (got {action})"
            print(f"  {expected:8} -> {status} | payload={payload[:20]}")

    asyncio.run(main())
