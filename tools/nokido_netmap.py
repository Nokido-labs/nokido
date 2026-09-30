#!/usr/bin/env python3
"""
Nokido Network Map — Terminal interactif
Usage : python3 /workspace/nokido_netmap.py

Navigation :
  j/k ou fleches  — naviguer entre les noeuds
  Enter           — inspecter le noeud selectionne
  r               — refresh depuis les scan results
  q               — quitter
"""

__FORGE_COLOR__ = "reseau/topology : carte reseau interactive en terminal"  # organe declare le 2026-09-06 (audit de raccordement)

import curses
import re
import time
from pathlib import Path

SCAN_DIR = Path("/workspace/scan_results")
INVENTORY_DIR = SCAN_DIR / "inventory"

# ── Données réseau ────────────────────────────────────────────────────────────

NODES = [
    {
        "id": "gw",
        "ip": "localhost",
        "label": "Gateway",
        "mac": "20-66-cf",
        "type": "infra",
        "risk": "none",
        "ports": [],
        "notes": "Routeur/Box — admin :80/:443",
    },
    {
        "id": "host",
        "ip": "localhost",
        "label": "Nokido",
        "mac": "—",
        "type": "host",
        "risk": "none",
        "ports": [],
        "notes": "Windows/Ryzen 8700G — Exegol container",
    },
    {
        "id": "tv",
        "ip": "localhost",
        "label": "Samsung TV",
        "mac": "38-86-f7",
        "type": "iot",
        "risk": "medium",
        "ports": ["8443/ssl", "10001/ssl"],
        "notes": "Tizen 2022+ — Remote API 8001/8002 non actif\nAttack: Tizen sideload, SmartThings token bypass",
    },
    {
        "id": "bulb",
        "ip": "localhost",
        "label": "Smart Bulb",
        "mac": "7c-49-eb",
        "type": "iot",
        "risk": "low",
        "ports": [],
        "notes": "Samsung SmartThings — rescan TV allumee",
    },
    {
        "id": "air",
        "ip": "localhost",
        "label": "Philips Air",
        "mac": "e4-bc-96",
        "type": "iot",
        "risk": "low",
        "ports": [],
        "notes": "Filtre connecté Philips — UPnP/mDNS probable",
    },
    {
        "id": "cast",
        "ip": "?",
        "label": "Chromecast",
        "mac": "?",
        "type": "iot",
        "risk": "medium",
        "ports": ["8008", "8009"],
        "notes": "IP inconnue — scan en cours\nAttack: /setup/eureka_info sans auth",
    },
    {
        "id": "mob1",
        "ip": "localhost",
        "label": "Mobile A",
        "mac": "56-d1-7e",
        "type": "mobile",
        "risk": "none",
        "ports": [],
        "notes": "MAC randomisée Android/iOS",
    },
    {
        "id": "mob2",
        "ip": "localhost",
        "label": "Mobile B",
        "mac": "ea-c1-4e",
        "type": "mobile",
        "risk": "none",
        "ports": [],
        "notes": "MAC randomisée Android/iOS",
    },
    {
        "id": "pc",
        "ip": "localhost",
        "label": "PC/Laptop",
        "mac": "c4-57-6e",
        "type": "host",
        "risk": "none",
        "ports": [],
        "notes": "Intel WiFi — OS inconnu",
    },
]

LINKS = [
    ("gw", "host", "wired"),
    ("gw", "tv", "wired"),
    ("gw", "bulb", "wired"),
    ("gw", "air", "wifi"),
    ("gw", "cast", "wifi"),
    ("gw", "mob1", "wifi"),
    ("gw", "mob2", "wifi"),
    ("gw", "pc", "wifi"),
    ("tv", "bulb", "smartthings"),
    ("tv", "cast", "cast"),
]

RISK_CHAR = {"high": "[!]", "medium": "[~]", "low": "[.]", "none": "[ ]"}
TYPE_ICON = {"infra": "<R>", "host": "[H]", "iot": "(i)", "mobile": "(m)"}

# ── Parser scan results ───────────────────────────────────────────────────────


def parse_scans():
    """Met à jour les ports depuis les fichiers nmap."""
    updates = {}
    for fname in SCAN_DIR.rglob("*.txt"):
        try:
            txt = fname.read_text(errors="replace")
        except Exception:
            continue
        # Trouver IPs et leurs ports
        for block in re.split(r"Nmap scan report for ", txt)[1:]:
            ip_match = re.match(r"([\d\.]+)", block)
            if not ip_match:
                continue
            ip = ip_match.group(1)
            ports = re.findall(r"(\d+/tcp\s+open\s+\S+)", block)
            if ports:
                updates[ip] = [p.strip() for p in ports]
    # Chercher Chromecast (port 8008)
    cc_files = list(SCAN_DIR.glob("cc_*.txt")) + list(SCAN_DIR.glob("chromecast*.txt"))
    for f in cc_files:
        try:
            txt = f.read_text(errors="replace")
            m = re.search(r"Nmap scan report for ([\d\.]+)", txt)
            if m and "8008" in txt:
                updates["cast_ip"] = m.group(1)
        except Exception:
            pass
    return updates


def apply_updates(nodes, updates):
    for node in nodes:
        ip = node["ip"]
        if ip in updates and updates[ip]:
            node["ports"] = updates[ip]
            if node["risk"] == "none":
                node["risk"] = "low"
        if node["id"] == "cast" and "cast_ip" in updates:
            node["ip"] = updates["cast_ip"]


# ── Rendu ─────────────────────────────────────────────────────────────────────

TOPOLOGY = [
    #  col 0          col 1          col 2          col 3
    ["gw", "host", "tv", "bulb"],
    ["", "pc", "air", "cast"],
    ["", "mob1", "mob2", ""],
]

COL_W = 20
ROW_H = 6
MARGIN_X = 4
MARGIN_Y = 2


def node_pos(node_id):
    for r, row in enumerate(TOPOLOGY):
        for c, nid in enumerate(row):
            if nid == node_id:
                return r, c
    return None, None


def draw_topology(stdscr, nodes, selected_idx, scroll_y=0):
    stdscr.erase()
    h, w = stdscr.getmaxyx()

    # Couleurs
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_GREEN, -1)  # low
    curses.init_pair(2, curses.COLOR_YELLOW, -1)  # medium
    curses.init_pair(3, curses.COLOR_RED, -1)  # high
    curses.init_pair(4, curses.COLOR_CYAN, -1)  # infra/header
    curses.init_pair(5, curses.COLOR_WHITE, -1)  # normal
    curses.init_pair(6, curses.COLOR_MAGENTA, -1)  # selected
    curses.init_pair(7, curses.COLOR_BLUE, -1)  # port info

    RISK_COLOR = {"high": 3, "medium": 2, "low": 1, "none": 5}

    # Header
    header = "  Nokido Network Map  [j/k=nav  Enter=inspect  r=refresh  q=quit]"
    try:
        stdscr.addstr(0, 0, header[: w - 1], curses.color_pair(4) | curses.A_BOLD)
        stdscr.addstr(1, 0, "─" * min(w - 1, 78), curses.color_pair(4))
    except curses.error:
        pass

    # Dessiner les liens (simples tirets entre noeuds)
    for src, dst, ltype in LINKS:
        sr, sc = node_pos(src)
        dr, dc = node_pos(dst)
        if sr is None or dr is None:
            continue
        sx = MARGIN_X + sc * COL_W + COL_W // 2
        sy = MARGIN_Y + 2 + sr * ROW_H + ROW_H // 2
        ex = MARGIN_X + dc * COL_W + COL_W // 2
        ey = MARGIN_Y + 2 + dr * ROW_H + ROW_H // 2
        lchar = "." if ltype in ("wifi", "cast", "smartthings") else "-"
        lcolor = 7 if ltype == "cast" else (2 if ltype == "smartthings" else 5)
        # Ligne horizontale simple
        if sy == ey:
            for x in range(min(sx, ex) + 2, max(sx, ex) - 1):
                try:
                    stdscr.addch(sy - scroll_y, x, lchar, curses.color_pair(lcolor))
                except curses.error:
                    pass

    # Dessiner les noeuds
    node_positions = {}
    for node in nodes:
        r, c = node_pos(node["id"])
        if r is None:
            continue
        x = MARGIN_X + c * COL_W
        y = MARGIN_Y + 2 + r * ROW_H - scroll_y
        node_positions[node["id"]] = (y, x)

        if y < 2 or y > h - 4:
            continue

        idx = nodes.index(node)
        is_sel = idx == selected_idx
        risk_col = RISK_COLOR.get(node["risk"], 5)
        icon = TYPE_ICON.get(node["type"], "[ ]")
        risk_mark = RISK_CHAR.get(node["risk"], "[ ]")

        attr = curses.A_REVERSE if is_sel else curses.A_NORMAL
        col = 6 if is_sel else risk_col

        line1 = f"{icon} {node['label'][:12]}"
        line2 = f"    {node['ip']}"
        line3 = (
            f"    {risk_mark} {','.join(node['ports'][:2])[:14]}"
            if node["ports"]
            else f"    {risk_mark} no ports"
        )

        try:
            stdscr.addstr(y, x, line1[: COL_W - 1], curses.color_pair(col) | attr | curses.A_BOLD)
            stdscr.addstr(y + 1, x, line2[: COL_W - 1], curses.color_pair(5) | attr)
            stdscr.addstr(y + 2, x, line3[: COL_W - 1], curses.color_pair(risk_col) | attr)
        except curses.error:
            pass

    # Legend
    legend_y = h - 2
    try:
        stdscr.addstr(
            legend_y,
            0,
            " [!]=high  [~]=med  [.]=low  wired=─  wifi=...  cast=... (blue)",
            curses.color_pair(4),
        )
    except curses.error:
        pass

    stdscr.refresh()
    return node_positions


def draw_inspect(stdscr, node):
    h, w = stdscr.getmaxyx()
    stdscr.erase()
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_GREEN, -1)
    curses.init_pair(2, curses.COLOR_YELLOW, -1)
    curses.init_pair(3, curses.COLOR_RED, -1)
    curses.init_pair(4, curses.COLOR_CYAN, -1)
    curses.init_pair(7, curses.COLOR_BLUE, -1)

    RISK_COLOR = {"high": 3, "medium": 2, "low": 1, "none": 4}
    rcol = RISK_COLOR.get(node["risk"], 4)

    lines = [
        ("", 4, False),
        (f"  Node: {node['label']}  ({node['ip']})", 4, True),
        (f"  MAC  : {node['mac']}  |  Type: {node['type']}", 5, False),
        (f"  Risk : {node['risk'].upper()}", rcol, True),
        ("", 4, False),
        ("  Open ports :", 4, True),
    ]
    if node["ports"]:
        for p in node["ports"]:
            lines.append((f"    • {p}", 7, False))
    else:
        lines.append(("    (none found in scans)", 5, False))

    lines += [
        ("", 4, False),
        ("  Notes / Attack surface :", 4, True),
    ]
    for note_line in node["notes"].split("\n"):
        lines.append((f"    {note_line}", 5, False))

    lines += [
        ("", 4, False),
        ("  [Backspace / b = back]", 4, False),
    ]

    for i, (txt, col, bold) in enumerate(lines):
        if i >= h - 1:
            break
        attr = curses.A_BOLD if bold else curses.A_NORMAL
        try:
            stdscr.addstr(i, 0, txt[: w - 1], curses.color_pair(col) | attr)
        except curses.error:
            pass

    stdscr.refresh()


# ── Main loop ─────────────────────────────────────────────────────────────────


def main(stdscr):
    nodes = [dict(n) for n in NODES]
    apply_updates(nodes, parse_scans())

    curses.curs_set(0)
    stdscr.nodelay(False)
    stdscr.keypad(True)

    sel = 0
    mode = "map"  # "map" | "inspect"
    scroll_y = 0
    last_refresh = time.time()

    while True:
        if mode == "map":
            draw_topology(stdscr, nodes, sel, scroll_y)
        elif mode == "inspect":
            draw_inspect(stdscr, nodes[sel])

        ch = stdscr.getch()

        if ch in (ord("q"), ord("Q")):
            break

        if ch == ord("r"):
            apply_updates(nodes, parse_scans())

        if mode == "map":
            if ch in (ord("j"), curses.KEY_DOWN):
                sel = (sel + 1) % len(nodes)
            elif ch in (ord("k"), curses.KEY_UP):
                sel = (sel - 1) % len(nodes)
            elif ch in (ord("l"), curses.KEY_RIGHT):
                sel = (sel + 3) % len(nodes)
            elif ch in (ord("h"), curses.KEY_LEFT):
                sel = (sel - 3) % len(nodes)
            elif ch in (curses.KEY_ENTER, 10, 13):
                mode = "inspect"

        elif mode == "inspect":
            if ch in (curses.KEY_BACKSPACE, ord("b"), 27):
                mode = "map"

        # Auto-refresh toutes les 30s
        if time.time() - last_refresh > 30:
            apply_updates(nodes, parse_scans())
            last_refresh = time.time()


if __name__ == "__main__":
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        pass
    print("\nNokido netmap closed.")
