"""Regression: phone MP4 (avformat-novalidate) must not render blank.

Catches future library regression where avformat-novalidate returns white.
Asserts:
- luma_key appears in XML as mlt_service=luminance
- export_render on a real phone clip is not white (mean RGB != 255)
"""
import os
import re
import subprocess
import tempfile

from kdenlive_mcp_server.server import (
    bin_import_clip,
    export_render,
    export_xml,
    filter_add,
    filter_list,
    project_new,
    timeline_add_clip,
    timeline_add_track,
)

PHONE = "/home/vaibhav/Downloads/VID_20251125_173758442_3.mp4"
RED = "/tmp/test_red.mp4"


def _ensure_red():
    if not os.path.exists(RED):
        subprocess.run(
            [
                "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=red:s=320x240:d=2",
                "-f", "lavfi", "-i", "anullsrc", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-t", "2", RED,
            ],
            capture_output=True, check=False, timeout=30,
        )


def _mean_rgb(mp4_path):
    with tempfile.TemporaryDirectory() as td:
        raw = os.path.join(td, "f.raw")
        subprocess.run(
            ["ffmpeg", "-y", "-i", mp4_path, "-frames:v", "1", "-pix_fmt", "rgb24", "-f", "rawvideo", raw],
            capture_output=True, check=False, timeout=30,
        )
        if not os.path.exists(raw):
            return None
        data = open(raw, "rb").read()
        if not data:
            return None
        rs = gs = bs = cnt = 0
        step = 3 * 100
        for i in range(0, len(data) - 2, step):
            rs += data[i]
            gs += data[i + 1]
            bs += data[i + 2]
            cnt += 1
        return (rs // cnt, gs // cnt, bs // cnt) if cnt else None


def test_luma_key_maps_to_luminance():
    with tempfile.TemporaryDirectory() as td:
        project_new(os.path.join(td, "p.json"), profile="hd1080p30")
        _ensure_red()
        bin_import_clip(RED)
        timeline_add_track()
        timeline_add_clip("clip0", 0, 0)
        assert filter_add(0, 0, "luma_key", ["threshold=0.5"])["success"]
        fl = filter_list(0, 0)["data"]
        # filter stored as luma_key but mlt_service is lumakey
        assert any(f.get("mlt_service") == "lumakey" for f in (fl if isinstance(fl, list) else fl.get("filters", [])))
        xml = export_xml()["data"]["xml"]
        assert "lumakey" in xml
        assert "avformat-novalidate" not in xml  # normalized to avformat


def test_phone_clip_not_white():
    if not os.path.exists(PHONE):
        import pytest
        pytest.skip(f"phone clip not found: {PHONE}")
    with tempfile.TemporaryDirectory() as td:
        project_new(os.path.join(td, "p.json"), profile="hd1080p30")
        bin_import_clip(PHONE)
        timeline_add_track()
        timeline_add_clip("clip0", 0, 0)
        # add the three low-confidence filters
        assert filter_add(0, 0, "frei0r.blur", ["radius=2"])["success"]
        assert filter_add(0, 0, "affine", ["angle=10"])["success"]
        assert filter_add(0, 0, "luma_key", ["threshold=0.5"])["success"]
        xml = export_xml()["data"]["xml"]
        # all three must appear as mlt_service
        assert "frei0r.IIRblur" in xml
        assert "affine" in xml
        assert "lumakey" in xml
        out = os.path.join(td, "out.mp4")
        res = export_render(out)
        assert res["success"], res
        assert os.path.exists(out) and os.path.getsize(out) > 1000
        mean = _mean_rgb(out)
        assert mean is not None, "could not decode rendered frame"
        assert mean != (255, 255, 255) and mean != (254, 254, 254), f"rendered frame is white/blank: {mean}"
