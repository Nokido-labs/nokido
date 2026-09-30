# mini_ids_agent.py
import asyncio
from scapy.all import sniff, IP, TCP, UDP
import pyshark


class MiniIDSAgent:
    def __init__(self, iface="eth0"):
        self.iface = iface
        self.suspect_ips = set()
        self.loop = asyncio.get_event_loop()

    # ----------------------------
    # SCAPY PACKET MONITOR
    # ----------------------------
    def scapy_callback(self, pkt):
        if IP in pkt:
            src = pkt[IP].src
            dst = pkt[IP].dst

            # SSH brute-force detection (exemple)
            if TCP in pkt and pkt[TCP].dport == 22:
                print(f"[SCAPY] SSH connection attempt from {src} -> {dst}")
                self.suspect_ips.add(src)

            # HTTP anomalies
            if TCP in pkt and pkt[TCP].dport == 80:
                print(f"[SCAPY] HTTP traffic {src} -> {dst}")

            # DNS unusual port
            if UDP in pkt and pkt[UDP].dport == 53:
                print(f"[SCAPY] DNS query {src} -> {dst}")

    async def run_scapy(self):
        await self.loop.run_in_executor(None, sniff, {"iface": self.iface, "prn": self.scapy_callback, "store": False})

    # ----------------------------
    # PYSHARK PACKET MONITOR
    # ----------------------------
    async def run_pyshark(self):
        capture = pyshark.LiveCapture(interface=self.iface)
        async for pkt in capture.sniff_continuously():
            try:
                ip_layer = pkt.ip
                src = ip_layer.src
                dst = ip_layer.dst

                # HTTP analysis
                if "http" in pkt:
                    print(f"[PYSHARK] HTTP {src} -> {dst}")
                    self.suspect_ips.add(src)

                # DNS analysis
                if "dns" in pkt:
                    print(f"[PYSHARK] DNS {src} -> {dst}")

            except AttributeError:
                continue

    # ----------------------------
    # ALERT FUNCTION
    # ----------------------------
    async def alert(self, message):
        # placeholder : tu peux connecter Telegram ou RAG ici
        print(f"[ALERT] {message}")

    # ----------------------------
    # RUN ALL
    # ----------------------------
    async def run(self):
        # lance scapy et pyshark en parallèle
        await asyncio.gather(self.run_scapy(), self.run_pyshark())


# ----------------------------
# Example usage
# ----------------------------
if __name__ == "__main__":
    agent = MiniIDSAgent(iface="eth0")
    asyncio.run(agent.run())
