"""
tools/store_github_token.py
============================
Stocke le GITHUB_TOKEN dans Windows Credential Manager.
Usage : python tools/store_github_token.py ghp_XXXXXXXX
"""

import sys


def store(token: str) -> None:
    import win32cred

    credential = {
        "Type": win32cred.CRED_TYPE_GENERIC,
        "TargetName": "GITHUB_TOKEN",
        "CredentialBlob": token,
        "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
        "UserName": "Nokido",
    }
    win32cred.CredWrite(credential, 0)
    # Vérif immédiate
    cred = win32cred.CredRead("GITHUB_TOKEN", win32cred.CRED_TYPE_GENERIC)
    val = cred["CredentialBlob"].decode("utf-16")
    assert val == token
    print(f"OK — token stocké: {token[:12]}...{token[-4:]}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tools/store_github_token.py ghp_XXXXXXXX")
        sys.exit(1)
    store(sys.argv[1])
