#!/usr/bin/env python3
"""
Combine top-level PNGs and MP4s (lexicographically ordered) into a single MP4.

- Images: shown as 3-second stills.
- Videos: played at full length, with a 1-second frozen first frame
  before and a 1-second frozen last frame after.
- Video audio is preserved for the playing portion.
- Everything is rendered on a supersampled 8K-ish canvas (2x 4K in
  each dimension ≈ 4x 4K pixels) and then downscaled to 4K output.
- Output uses H.264 + AAC with a slow preset for good quality/size.

Requires:
    moviepy==2.2.1 (or any 2.x where moviepy.editor is removed)
    imageio, imageio-ffmpeg, numpy
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable, List

from moviepy import (
    VideoFileClip,
    ImageClip,
    concatenate_videoclips,
)


# --- Configuration ---------------------------------------------------------

# 4K target resolution
FINAL_RES = (3840, 2160)

# Work at 2x width and 2x height => 4x 4K pixel count (supersampling)
WORKING_RES = (FINAL_RES[0] * 2, FINAL_RES[1] * 2)

# Timeline parameters
FPS = 30
IMAGE_DURATION = 3.0       # seconds per PNG
VIDEO_FREEZE_DURATION = 1.0  # seconds before & after each video

# Output filename
OUTPUT_NAME = "combined_4k.mp4"


# --- Helpers ---------------------------------------------------------------

def list_media_files(directory: Path) -> List[Path]:
    """
    Return all top-level PNG and MP4 files in `directory`,
    sorted lexicographically by filename.
    """
    exts = {".png", ".mp4"}
    media = [
        p for p in directory.iterdir()
        if p.is_file() and p.suffix.lower() in exts
    ]
    media.sort(key=lambda p: p.name)
    return media


def letterbox_to_canvas(clip, canvas_size) :
    """
    Scale `clip` to fit inside canvas_size while keeping aspect ratio,
    then place it centered on a black background of exactly canvas_size.
    """
    canvas_w, canvas_h = canvas_size
    clip_w, clip_h = clip.w, clip.h

    if clip_w == 0 or clip_h == 0:
        raise RuntimeError(f"Invalid clip size: {clip_w}x{clip_h}")

    scale = min(canvas_w / float(clip_w), canvas_h / float(clip_h))
    target_w = int(round(clip_w * scale))
    target_h = int(round(clip_h * scale))

    # Resize and place on black background (MoviePy 2.x API)
    return (
        clip.resized(new_size=(target_w, target_h))
            .with_background_color(size=canvas_size, color=(0, 0, 0))
    )


def build_image_clip(path: Path):
    """
    Build a 3-second 30fps letterboxed clip from a PNG.
    """
    img_clip = ImageClip(str(path))
    img_clip = letterbox_to_canvas(img_clip, WORKING_RES)
    img_clip = img_clip.with_duration(IMAGE_DURATION).with_fps(FPS)
    return img_clip


def build_video_segment(path: Path):
    """
    Build [1s frozen-first-frame, full video, 1s frozen-last-frame]
    from an MP4, all letterboxed and at the working resolution.
    """
    video = VideoFileClip(str(path))  # audio=True by default
    letterboxed = letterbox_to_canvas(video, WORKING_RES)

    # Grab first and last frames from the letterboxed clip so the stills
    # are exactly the same size as the working canvas.
    first_frame = letterboxed.get_frame(0.0)

    # Avoid requesting a frame exactly at duration in case of rounding.
    t_last = max(letterboxed.duration - 1.0 / FPS, 0.0)
    last_frame = letterboxed.get_frame(t_last)

    pre_freeze = (
        ImageClip(first_frame)
        .with_duration(VIDEO_FREEZE_DURATION)
        .with_fps(FPS)
    )

    post_freeze = (
        ImageClip(last_frame)
        .with_duration(VIDEO_FREEZE_DURATION)
        .with_fps(FPS)
    )

    # Ensure a consistent FPS on the video segment itself.
    live_segment = letterboxed.with_fps(FPS)

    return [pre_freeze, live_segment, post_freeze]


# --- Main ------------------------------------------------------------------

def main(argv: Iterable[str] | None = None) -> None:
    """
    If a directory is provided as the first argument, use that.
    Otherwise, use the directory containing this script.
    """
    argv = list(argv) if argv is not None else sys.argv[1:]

    if argv:
        root = Path(argv[0]).expanduser().resolve()
    else:
        root = Path(__file__).resolve().parent

    if not root.is_dir():
        raise RuntimeError(f"Not a directory: {root}")

    media_files = list_media_files(root)
    if not media_files:
        raise RuntimeError(f"No PNG or MP4 files found in {root}")

    clips = []

    for path in media_files:
        suffix = path.suffix.lower()
        if suffix == ".png":
            clips.append(build_image_clip(path))
        elif suffix == ".mp4":
            clips.extend(build_video_segment(path))
        else:
            # Should never happen due to filtering in list_media_files
            raise RuntimeError(f"Unsupported file type: {path}")

    # Concatenate everything in order.
    timeline = concatenate_videoclips(clips, method="compose")

    # Downscale to 4K output and ensure consistent fps.
    timeline_4k = timeline.resized(new_size=FINAL_RES).with_fps(FPS)

    # High-quality H.264 + AAC, Chrome-friendly, CPU-heavy encode.
    timeline_4k.write_videofile(
        str(root / OUTPUT_NAME),
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        preset="veryslow",
        ffmpeg_params=[
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-profile:v", "high",
        ],
    )


if __name__ == "__main__":
    main()
