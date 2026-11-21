"""video_export.py -- pieces for Animate Mechanism's "Export video..."
(Session 181). No Qt, no OCP, so they can be tested on their own.

The dialog moves the parts to each slider value in turn, asks the
viewer to dump a PNG, then ffmpeg turns the numbered PNGs into an .mp4
(H.264, yuv420p: plays everywhere, in browsers and phones too).

    thetas = frame_values(lo, hi, units_per_second=30, fps=30,
                          hold_seconds=0.5, pingpong=True)
    cmd = ffmpeg_command(ffmpeg, frames_dir, out_path, fps=30)
"""
import os
import shutil

WIDTH, HEIGHT, FPS = 1280, 720, 30
PAD_COLOR = "0xBEBEBE"        # the viewer's grey, for the letterbox bars


def find_ffmpeg():
    """Path of the ffmpeg program, or None."""
    return shutil.which("ffmpeg")


def frame_values(lo, hi, units_per_second=30.0, fps=FPS,
                 hold_seconds=0.5, pingpong=True):
    """Slider values, one per video frame: hold at lo, run up to hi,
    hold, and (pingpong) run back to lo. Without pingpong: hold, up to
    hi, hold. The last frame of a pingpong video equals the first, so
    it loops cleanly; the final lo frame is not repeated."""
    n_move = max(2, int(round((hi - lo) / float(units_per_second) * fps)))
    n_hold = int(round(hold_seconds * fps))
    up = [lo + (hi - lo) * i / (n_move - 1.0) for i in range(n_move)]
    out = [lo] * n_hold + up + [hi] * n_hold
    if pingpong:
        out += up[-2::-1]            # back down, hi already shown
        out += [lo] * n_hold
    return out


def ffmpeg_command(ffmpeg, frames_dir, out_path, fps=FPS, width=WIDTH,
                   height=HEIGHT, pad_color=PAD_COLOR):
    """ffmpeg argument list: frame_00001.png ... -> out_path, scaled to
    fit width x height, letterboxed to exactly that size."""
    vf = (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
          f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color={pad_color},"
          f"format=yuv420p")
    return [ffmpeg, "-y", "-loglevel", "error", "-framerate", str(fps),
            "-i", os.path.join(frames_dir, "frame_%05d.png"),
            "-vf", vf, "-c:v", "libx264", "-crf", "18",
            "-movflags", "+faststart", out_path]
