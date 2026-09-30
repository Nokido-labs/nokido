# -*- coding: utf-8 -*-
"""
test_forge_rsp_gate.py — Tests unitaires pour la politique de sécurité RSP (matrice ASL).
"""
from __future__ import annotations

import pytest
import sys
from pathlib import Path

# Add project root to path to ensure tools is importable
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.forge_rsp_gate import gate

def test_asl1_docs_local_allowed():
    # ASL-1 docs -> local sandbox is allowed (True)
    res = gate(task_type="doc", sandbox="local", network=True, ring=3, owner_approved=False)
    assert res["ok"] is True
    assert res["asl"] == 1

def test_asl2_code_local_denied():
    # ASL-2 write_code -> local sandbox is denied (False) because min_rank >= 2 (gvisor/docker required)
    res = gate(task_type="write_code", sandbox="local", network=False, ring=2, owner_approved=False)
    assert res["ok"] is False
    assert res["asl"] == 2
    assert "confinement requis" in res["reason"]

def test_asl2_code_gvisor_allowed():
    # ASL-2 write_code -> gvisor sandbox is allowed (True)
    res = gate(task_type="write_code", sandbox="gvisor", network=False, ring=2, owner_approved=False)
    assert res["ok"] is True

def test_asl3_exec_local_denied():
    # ASL-3 exec -> local sandbox is denied (False)
    res = gate(task_type="exec", sandbox="local", network=False, ring=2, owner_approved=False)
    assert res["ok"] is False
    assert res["asl"] == 3

def test_asl3_exec_network_open_denied():
    # ASL-3 exec -> network allowed=True is denied (False)
    res = gate(task_type="exec", sandbox="gvisor", network=True, ring=2, owner_approved=False)
    assert res["ok"] is False
    assert "reseau sortant interdit" in res["reason"]

def test_asl4_recon_network_open_denied():
    # ASL-4 recon -> network open (True) is denied (False, needs isolated or False)
    res = gate(task_type="recon", sandbox="docker", network=True, ring=1, owner_approved=False)
    assert res["ok"] is False
    assert "reseau doit etre ISOLE" in res["reason"]

def test_asl5_infra_owner_required():
    # ASL-5 infra -> owner approval required
    res = gate(task_type="infra", sandbox="local", network=False, ring=0, owner_approved=False)
    assert res["ok"] is False
    assert res["asl"] == 5
    assert "approbation OWNER requise" in res["reason"]

def test_asl5_infra_owner_approved_allowed():
    # ASL-5 infra -> owner approved -> allowed
    res = gate(task_type="infra", sandbox="local", network=False, ring=0, owner_approved=True)
    assert res["ok"] is True
