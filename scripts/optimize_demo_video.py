#!/usr/bin/env python3
"""Optimize an MP4 demo video for click-to-play use on goodedunote.

Example:
    python3 scripts/optimize_demo_video.py --in demo.mp4 --out web/demo.mp4 \\
        --poster-ts 2.5
"""

from __future__ import annotations

import argparse
import json
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Optimize an MP4 for web playback and extract a JPEG poster."
    )
    parser.add_argument("--in", dest="input_file", required=True, type=Path,
                        help="Source MP4 file")
    parser.add_argument("--out", dest="output_file", required=True, type=Path,
                        help="Optimized MP4 destination")
    parser.add_argument("--poster-ts", required=True, type=float,
                        help="Poster timestamp in seconds")
    parser.add_argument("--poster", type=Path,
                        help="Poster JPEG destination (default: <out>_poster.jpg)")
    parser.add_argument("--crf", type=int, default=26,
                        help="libx264 CRF value (default: 26)")
    parser.add_argument("--max-longedge", type=int, default=1280,
                        help="Only shrink videos whose longest edge exceeds this value "
                             "(default: 1280)")
    return parser.parse_args()


def require_binary(name: str) -> str:
    binary = shutil.which(name)
    if binary is None:
        raise RuntimeError(
            f"Required executable '{name}' was not found in PATH. "
            "Install ffmpeg (which also provides ffprobe) and try again."
        )
    return binary


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, text=True)


def probe_video(ffprobe: str, video_path: Path) -> dict[str, Any]:
    result = subprocess.run(
        [
            ffprobe,
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height:format=duration,size",
            "-of", "json",
            str(video_path),
        ],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    data: dict[str, Any] = json.loads(result.stdout)
    streams = data.get("streams", [])
    if not streams or "width" not in streams[0] or "height" not in streams[0]:
        raise RuntimeError(f"No video stream found in: {video_path}")
    return data


def first_video_dimensions(probe_data: dict[str, Any]) -> tuple[int, int]:
    stream = probe_data["streams"][0]
    return int(stream["width"]), int(stream["height"])


def has_faststart_moov(video_path: Path) -> bool:
    """Return whether the top-level moov atom precedes the top-level mdat atom."""
    moov_offset: int | None = None
    mdat_offset: int | None = None

    with video_path.open("rb") as video:
        file_size = video_path.stat().st_size
        while video.tell() + 8 <= file_size:
            atom_offset = video.tell()
            header = video.read(8)
            atom_size, atom_type = struct.unpack(">I4s", header)
            header_size = 8

            if atom_size == 1:
                extended_size = video.read(8)
                if len(extended_size) != 8:
                    return False
                atom_size = struct.unpack(">Q", extended_size)[0]
                header_size = 16
            elif atom_size == 0:
                atom_size = file_size - atom_offset

            if atom_size < header_size or atom_offset + atom_size > file_size:
                return False
            if atom_type == b"moov" and moov_offset is None:
                moov_offset = atom_offset
            elif atom_type == b"mdat" and mdat_offset is None:
                mdat_offset = atom_offset

            if moov_offset is not None and mdat_offset is not None:
                return moov_offset < mdat_offset
            video.seek(atom_offset + atom_size)

    return False


def default_poster_path(output_file: Path) -> Path:
    return output_file.with_suffix("").with_name(output_file.stem + "_poster.jpg")


def main() -> int:
    args = parse_args()
    if args.poster_ts < 0:
        raise ValueError("--poster-ts must be zero or greater")
    if not 0 <= args.crf <= 51:
        raise ValueError("--crf must be between 0 and 51")
    if args.max_longedge <= 0:
        raise ValueError("--max-longedge must be greater than zero")
    if not args.input_file.is_file():
        raise FileNotFoundError(f"Input file does not exist or is not a file: {args.input_file}")

    ffmpeg = require_binary("ffmpeg")
    ffprobe = require_binary("ffprobe")
    poster_file = args.poster or default_poster_path(args.output_file)

    args.output_file.parent.mkdir(parents=True, exist_ok=True)
    poster_file.parent.mkdir(parents=True, exist_ok=True)
    if args.output_file.exists():
        print(f"WARNING: overwriting existing output: {args.output_file}", file=sys.stderr)

    source_probe = probe_video(ffprobe, args.input_file)
    width, height = first_video_dimensions(source_probe)
    needs_scale = max(width, height) > args.max_longedge

    transcode_command = [
        ffmpeg, "-y", "-i", str(args.input_file),
        "-map", "0:v:0", "-map", "0:a?",
        "-c:v", "libx264", "-crf", str(args.crf), "-preset", "veryfast",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k",
        "-movflags", "+faststart",
    ]
    if needs_scale:
        transcode_command.extend([
            "-vf",
            f"scale={args.max_longedge}:{args.max_longedge}:"
            "force_original_aspect_ratio=decrease:force_divisible_by=2",
        ])
    transcode_command.append(str(args.output_file))
    run(transcode_command)

    run([
        ffmpeg, "-y", "-ss", str(args.poster_ts), "-i", str(args.output_file),
        "-frames:v", "1", "-q:v", "3", str(poster_file),
    ])

    output_probe = probe_video(ffprobe, args.output_file)
    output_width, output_height = first_video_dimensions(output_probe)
    output_format = output_probe.get("format", {})
    duration = float(output_format.get("duration", 0))
    size = int(output_format.get("size", args.output_file.stat().st_size))
    faststart = has_faststart_moov(args.output_file)

    print(f"Output: {args.output_file}")
    print(f"Video: {output_width}x{output_height}, duration={duration:.3f}s, size={size} bytes")
    print(f"Poster: {poster_file}")
    print(f"Faststart (moov before mdat): {'yes' if faststart else 'no'}")
    if not faststart:
        raise RuntimeError("Faststart verification failed: moov atom is not before mdat")
    print("OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
