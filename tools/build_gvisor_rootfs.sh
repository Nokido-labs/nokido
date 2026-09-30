#!/bin/bash
# build_gvisor_rootfs.sh — construit une rootfs minimale read-only pour gVisor (#4).
# But : `runsc run` dans un FS isolé (libs+python3+sh, AUCUN /home /etc-secrets /root /mnt)
# au lieu de `runsc do` (qui monte le FS hote en RO = lecture possible).
# Idempotent. Owner WSL Debian, SANS sudo (tout sous $HOME). Self-test runsc run a la fin.
set -u
BASE="$HOME/lfgvisor"
RFS="$BASE/rootfs"
echo "== build rootfs gVisor minimale -> $RFS =="
echo "whoami: $(id -un) uid=$(id -u)  HOME=$HOME"
mkdir -p "$BASE" 2>/dev/null
if [ ! -w "$BASE" ]; then
  echo "FATAL: $BASE non writable"; ls -ld "$HOME" "$BASE" 2>/dev/null; exit 2
fi

# nettoyage best-effort ; le 12G root-owned d'un vieux run `cp -a /usr/lib` = nuke root AVANT
rm -rf "$RFS" 2>/dev/null
mkdir -p "$RFS"/{dev,proc,sys,tmp,etc,usr/bin,usr/lib,lib64,root}

# 1) shared libs multiarch — CIBLE. PAS /usr/lib64/. (= symlinks pendants -> loader casse)
[ -d /usr/lib/x86_64-linux-gnu ] && cp -a /usr/lib/x86_64-linux-gnu "$RFS/usr/lib/" 2>/dev/null
# loader : fichier REEL (deref -L), cible videe d'abord (sinon 'dangling symlink')
rm -f "$RFS/lib64/ld-linux-x86-64.so.2"
for ld in /lib64/ld-linux-x86-64.so.2 /usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2 /lib/ld-linux-x86-64.so.2; do
  [ -e "$ld" ] && { cp -L "$ld" "$RFS/lib64/ld-linux-x86-64.so.2"; break; }
done
for d in /usr/lib/python3*; do [ -d "$d" ] && cp -a "$d" "$RFS/usr/lib/" 2>/dev/null; done
# resolution dynamique : ld.so cache/conf
cp -a /etc/ld.so.cache "$RFS/etc/" 2>/dev/null || true
cp -a /etc/ld.so.conf "$RFS/etc/" 2>/dev/null || true
[ -d /etc/ld.so.conf.d ] && cp -a /etc/ld.so.conf.d "$RFS/etc/" 2>/dev/null

# 2) binaires : python3 (binaire reel) + un shell
cp -aL /usr/bin/python3 "$RFS/usr/bin/python3" 2>/dev/null || true
for b in /usr/bin/python3.*; do [ -e "$b" ] && cp -aL "$b" "$RFS/usr/bin/" 2>/dev/null; done
cp -aL /usr/bin/dash "$RFS/usr/bin/sh" 2>/dev/null || cp -aL /bin/sh "$RFS/usr/bin/sh" 2>/dev/null || true

# 3) symlinks usr-merge (resolution loader/libs)
ln -sfn usr/lib "$RFS/lib"
ln -sfn usr/bin "$RFS/bin"

# 3) /etc minimal (pas de shadow/passwd reels)
echo "root:x:0:0:root:/root:/bin/sh" > "$RFS/etc/passwd"
echo "root:x:0:" > "$RFS/etc/group"
: > "$RFS/etc/hostname"

PYBIN="$(ls "$RFS"/usr/bin/python3* 2>/dev/null | head -1)"
echo "python dans rootfs : ${PYBIN:-ABSENT}"
echo "taille rootfs : $(du -sh "$RFS" 2>/dev/null | cut -f1)"

# 4) config.json OCI de TEST (bundle minimal) + self-test runsc run
TBUNDLE="$BASE/_selftest"
rm -rf "$TBUNDLE"; mkdir -p "$TBUNDLE"
# code de test bind-monte en lecture seule
echo 'print("GVISOR_ROOTFS_OK", 6*7)' > "$TBUNDLE/code.py"
cat > "$TBUNDLE/config.json" <<JSON
{
  "ociVersion": "1.0.0",
  "process": {
    "terminal": false,
    "user": {"uid": 0, "gid": 0},
    "args": ["/usr/bin/python3", "/code.py"],
    "env": ["PATH=/usr/bin:/bin", "HOME=/root", "PYTHONDONTWRITEBYTECODE=1", "LD_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu:/lib64"],
    "cwd": "/",
    "capabilities": {"bounding": [], "effective": [], "permitted": []},
    "rlimits": []
  },
  "root": {"path": "$RFS", "readonly": true},
  "hostname": "gvisor",
  "mounts": [
    {"destination": "/proc", "type": "proc", "source": "proc"},
    {"destination": "/tmp", "type": "tmpfs", "source": "tmpfs", "options": ["nosuid","nodev","mode=1777"]},
    {"destination": "/code.py", "type": "bind", "source": "$TBUNDLE/code.py", "options": ["rbind","ro"]}
  ],
  "linux": {"namespaces": [{"type": "pid"}, {"type": "mount"}, {"type": "ipc"}, {"type": "uts"}, {"type": "network"}]}
}
JSON
echo "== self-test : runsc --rootless --network=none run =="
cd "$TBUNDLE" || exit 3
ID="lf_selftest_$$"
runsc --rootless --network=none run -bundle "$TBUNDLE" "$ID" 2>"$TBUNDLE/err.txt"
RC=$?
echo "rc=$RC"
echo "--- stderr (tail) ---"; tail -5 "$TBUNDLE/err.txt" 2>/dev/null
runsc --rootless delete "$ID" 2>/dev/null || true
echo "== FIN build (rootfs=$RFS) =="
