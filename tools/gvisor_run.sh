#!/bin/bash
# gvisor_run.sh — exécute du code UNTRUSTED dans gVisor via un bundle OCI par-appel monté
# sur la rootfs minimale read-only ($HOME/lfgvisor/rootfs, cf build_gvisor_rootfs.sh).
# Le code est bind-monté RO → le FS hôte n'est PAS lisible (ferme le trou `runsc do`).
# Fallback `runsc do` si la rootfs n'est pas construite (isole syscalls+écritures, FS hôte RO).
# Appelé par forge_privileged_bridge._run_gvisor (contexte owner WSL).
# Args : $1=code_path(WSL)  $2=lang(python3|sh|bash)  $3=net(none|host)  $4=id
set -u
CODE="${1:?code path requis}"; LANG_X="${2:-python3}"; NET="${3:-none}"; ID="${4:-lfgv_$$}"
RFS="$HOME/lfgvisor/rootfs"
case "$LANG_X" in python3) INTERP=/usr/bin/python3; EXT=py;; *) INTERP=/usr/bin/sh; EXT=sh;; esac
NETOPT=""; [ "$NET" = none ] && NETOPT="--network=none"

# rootfs minimale absente → fallback `runsc do` (FS hôte monté RO = lecture possible)
if [ ! -x "$RFS/usr/bin/python3" ]; then
  exec runsc --rootless $NETOPT do "$LANG_X" "$CODE"
fi

if [ "$NET" = none ]; then
  NS='{"type":"pid"},{"type":"mount"},{"type":"ipc"},{"type":"uts"},{"type":"network"}'
else
  NS='{"type":"pid"},{"type":"mount"},{"type":"ipc"},{"type":"uts"}'
fi

B="$HOME/lfgvisor/_run/$ID"; mkdir -p "$B"
cat > "$B/config.json" <<JSON
{"ociVersion":"1.0.0",
 "process":{"terminal":false,"user":{"uid":0,"gid":0},
   "args":["$INTERP","/code.$EXT"],
   "env":["PATH=/usr/bin:/bin","HOME=/root","PYTHONDONTWRITEBYTECODE=1","LD_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu:/lib64"],
   "cwd":"/","capabilities":{"bounding":[],"effective":[],"permitted":[]},"rlimits":[]},
 "root":{"path":"$RFS","readonly":true},
 "hostname":"gvisor",
 "mounts":[{"destination":"/proc","type":"proc","source":"proc"},
   {"destination":"/tmp","type":"tmpfs","source":"tmpfs","options":["nosuid","nodev","mode=1777"]},
   {"destination":"/code.$EXT","type":"bind","source":"$CODE","options":["rbind","ro"]}],
 "linux":{"namespaces":[$NS]}}
JSON
runsc --rootless $NETOPT run -bundle "$B" "$ID"; RC=$?
runsc --rootless delete "$ID" 2>/dev/null
rm -rf "$B"
exit $RC
