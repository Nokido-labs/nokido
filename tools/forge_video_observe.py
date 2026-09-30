# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE [BLUE]
DATE:2026-06-02 | VER:v_video_observe_1

forge_video_observe.py — Oracle VIDÉO : sous-échantillonnage sémantique d'un flux
vidéo en format digestible par un LLM (cf. essai "barrière temporelle").

POURQUOI (anti-dup) : aucun module Nokido n'analyse la vidéo — gen_demo_gifs /
forge_demo_record_all PRODUISENT des gifs/captures (sortie), ici on INGÈRE et on
réduit (entrée). Domaine neuf.

PRINCIPE : une vidéo 30fps/1min = 1800 images → sature le contexte. On la réduit
DÉTERMINISTE avant le LLM :
  1. KEYFRAMES — ffmpeg scene-detect : ne garde que les images où ça change
     (1800 → ~10). ffmpeg dispo dans C:/nokido/ms-playwright (bundle Playwright).
  2. TRANSCRIPT horodaté — faster-whisper (l'audio porte souvent + de contexte que
     l'image). Optionnel : si faster-whisper absent → note d'install.
Le LLM lit le transcript + regarde la grille de keyframes comme une BD.

NB pour le COMPORTEMENT d'une UI web : ne PAS filmer puis analyser les pixels —
utiliser le trace structuré Playwright (DOM-snapshot par action). La vidéo = pour
du contenu vidéo réel, pas pour de l'automation web.

USAGE :
    LAFORGE_PYTHON forge_video_observe.py --video in.mp4 --out sandbox/vid [--no-audio]
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _ffmpeg() -> str:
    """env FFMPEG_BIN > bundle ms-playwright > PATH."""
    env = os.environ.get("FFMPEG_BIN")
    if env and os.path.isfile(env):
        return env
    import glob

    for c in glob.glob(r"C:\nokido\ms-playwright\ffmpeg*\ffmpeg*.exe"):
        return c
    import shutil

    return shutil.which("ffmpeg") or "ffmpeg"


def extract_keyframes(video: str, out_dir: str | Path, threshold: float = 0.3, max_frames: int = 20) -> list[str]:
    """Keyframes par détection de changement de scène (ffmpeg). Retourne les chemins.
    threshold 0..1 (0.3 = sensible, 0.5 = coupes franches seulement)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("kf_*.jpg"):
        old.unlink()
    pattern = str(out / "kf_%03d.jpg")
    cmd = [
        _ffmpeg(), "-hide_banner", "-loglevel", "error", "-i", str(video),
        "-vf", f"select='gt(scene,{threshold})'", "-vsync", "vfr",
        "-frames:v", str(max_frames), "-q:v", "3", pattern,
    ]
    subprocess.run(cmd, check=True, timeout=300)
    frames = sorted(str(p) for p in out.glob("kf_*.jpg"))
    if not frames:  # aucune coupe détectée -> au moins la 1re frame
        first = str(out / "kf_000.jpg")
        subprocess.run(
            [_ffmpeg(), "-hide_banner", "-loglevel", "error", "-i", str(video),
             "-frames:v", "1", "-q:v", "3", first],
            check=False, timeout=60,
        )
        frames = [first] if os.path.isfile(first) else []
    return frames


def transcribe(video: str, model_size: str = "base") -> list[dict] | None:
    """Transcript horodaté via faster-whisper. None si non installé (note d'install
    renvoyée par l'appelant). Modèle local, 0 cloud."""
    try:
        from faster_whisper import WhisperModel
    except Exception:
        return None
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, _info = model.transcribe(str(video), vad_filter=True)
    return [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()} for s in segments]


def observe_video(video: str, out_dir: str | Path, transcribe_audio: bool = True,
                  threshold: float = 0.3, max_frames: int = 20) -> dict:
    """Réduit une vidéo en {keyframes[], n_keyframes, transcript[]|null, note}.
    À donner au LLM : transcript (texte = génie) + grille keyframes (vision)."""
    if not os.path.isfile(video):
        return {"error": f"vidéo introuvable: {video}"}
    kfs = extract_keyframes(video, out_dir, threshold=threshold, max_frames=max_frames)
    res: dict = {"video": str(video), "keyframes": kfs, "n_keyframes": len(kfs), "transcript": None}
    if transcribe_audio:
        tr = transcribe(video)
        if tr is None:
            res["note"] = "transcript indisponible — `pip install faster-whisper` (env base miniforge)"
        else:
            res["transcript"] = tr
    return res


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Oracle vidéo — keyframes + transcript pour LLM.")
    ap.add_argument("--video", required=True)
    ap.add_argument("--out", default=str(ROOT / "sandbox" / "video"))
    ap.add_argument("--no-audio", action="store_true", help="skip transcript")
    ap.add_argument("--threshold", type=float, default=0.3)
    ap.add_argument("--max-frames", type=int, default=20)
    a = ap.parse_args(argv)
    res = observe_video(a.video, a.out, transcribe_audio=not a.no_audio,
                        threshold=a.threshold, max_frames=a.max_frames)
    sys.stdout.write(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if "error" not in res else 1


if __name__ == "__main__":
    raise SystemExit(main())
