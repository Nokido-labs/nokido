import socket
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import nmap
from zeroconf import Zeroconf, ServiceBrowser
import miniupnpc

from pysnmp.hlapi import *

try:
    from scapy.all import *
except:
    pass


class Device:
    def __init__(self, ip):
        self.ip = ip
        self.hostname = None
        self.mac = None
        self.os = None
        self.ports = []
        self.protocols = []
        self.services = {}
        self.type = "unknown"

    def to_dict(self):
        return self.__dict__


class NetworkDiscovery:
    def __init__(self, subnet="localhost/24"):

        self.subnet = subnet
        self.devices = {}

    def get_device(self, ip):

        if ip not in self.devices:
            self.devices[ip] = Device(ip)

        return self.devices[ip]

    # -------------------------
    # NMAP scan + OS detection
    # -------------------------

    def nmap_scan(self):

        nm = nmap.PortScanner()

        print("Running Nmap scan...")

        nm.scan(hosts=self.subnet, arguments="-O -sS")

        for host in nm.all_hosts():
            dev = self.get_device(host)

            if "tcp" in nm[host]:
                for port in nm[host]["tcp"]:
                    dev.ports.append(port)

            if "osmatch" in nm[host] and nm[host]["osmatch"]:
                dev.os = nm[host]["osmatch"][0]["name"]

    # -------------------------
    # SNMP detection
    # -------------------------

    def snmp_scan(self, device):

        try:
            iterator = getCmd(
                SnmpEngine(),
                CommunityData("public"),
                UdpTransportTarget((device.ip, 161), timeout=1),
                ContextData(),
                ObjectType(ObjectIdentity("1.3.6.1.2.1.1.1.0")),
            )

            errorIndication, errorStatus, errorIndex, varBinds = next(iterator)

            if not errorIndication:
                for varBind in varBinds:
                    value = str(varBind[1])

                    device.services["snmp"] = value
                    device.protocols.append("SNMP")

        except:
            pass

    # -------------------------
    # mDNS discovery
    # -------------------------

    class MDNSListener:
        def __init__(self, discovery):
            self.discovery = discovery

        def add_service(self, zeroconf, type, name):

            info = zeroconf.get_service_info(type, name)

            if info:
                ip = socket.inet_ntoa(info.addresses[0])

                dev = self.discovery.get_device(ip)

                dev.protocols.append("mDNS")
                dev.services["mdns"] = name

    def mdns_discovery(self):

        print("Running mDNS discovery...")

        zeroconf = Zeroconf()

        listener = self.MDNSListener(self)

        ServiceBrowser(zeroconf, "_services._dns-sd._udp.local.", listener)

    # -------------------------
    # UPnP discovery
    # -------------------------

    def upnp_discovery(self):

        print("Running UPnP discovery...")

        u = miniupnpc.UPnP()

        u.discoverdelay = 200

        devices = u.discover()

        if devices > 0:
            ip = u.lanaddr

            dev = self.get_device(ip)

            dev.protocols.append("UPnP")

    # -------------------------
    # NetBIOS discovery
    # -------------------------

    def netbios_scan(self, device):

        try:
            name = socket.gethostbyaddr(device.ip)[0]

            if name:
                device.hostname = name
                device.protocols.append("NetBIOS")

        except:
            pass

    # -------------------------
    # LLDP / CDP sniffing
    # -------------------------

    def lldp_cdp_sniff(self, timeout=10):

        print("Sniffing LLDP/CDP packets...")

        def handle(pkt):

            if pkt.haslayer("LLDPDU"):
                src = pkt[Ether].src
                dev = self.get_device(src)

                dev.protocols.append("LLDP")

            if pkt.haslayer("CDPMsgDeviceID"):
                src = pkt[Ether].src
                dev = self.get_device(src)

                dev.protocols.append("CDP")

        sniff(filter="ether proto 0x88cc", prn=handle, timeout=timeout)

    # -------------------------
    # full analysis
    # -------------------------

    def analyze_device(self, device):

        self.snmp_scan(device)
        self.netbios_scan(device)

    # -------------------------
    # main run
    # -------------------------

    def run(self):

        self.nmap_scan()

        with ThreadPoolExecutor(max_workers=20) as executor:
            executor.map(self.analyze_device, self.devices.values())

        self.mdns_discovery()
        self.upnp_discovery()

        try:
            self.lldp_cdp_sniff()
        except:
            pass

        return [d.to_dict() for d in self.devices.values()]


if __name__ == "__main__":
    nd = NetworkDiscovery("localhost/24")

    devices = nd.run()

    print(json.dumps(devices, indent=2))
