"""timeline_build_from_segments, clip_reframe_vertical and vertical profiles."""
import json
import shutil
import subprocess

import pytest

from kdenlive_mcp_server.server import (
    _normalize_segments,
    bin_import_clip,
    clip_reframe_vertical,
    export_render,
    export_xml,
    filter_list,
    project_list_profiles,
    project_new,
    session_undo,
    timeline_add_track,
    timeline_build_from_segments,
    timeline_get_duration,
    track_get_info,
)

needs_ffmpeg = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg/ffprobe not installed"
)
needs_melt = pytest.mark.skipif(not shutil.which("melt"), reason="melt not installed")


# ── segment validation (pure) ────────────────────────────────────


def test_normalize_sorts():
    segs = [{"start": 5, "end": 6}, {"start": 1, "end": 2}]
    assert _normalize_segments(segs, 10) == [(1, 2), (5, 6)]


def test_normalize_clamps_to_duration():
    segs = [{"start": -1, "end": 2}, {"start": 8, "end": 15}]
    assert _normalize_segments(segs, 10) == [(0, 2), (8, 10)]


def test_normalize_merges_overlaps_and_touching():
    segs = [{"start": 1, "end": 3}, {"start": 2, "end": 4}, {"start": 4, "end": 5}, {"start": 7, "end": 8}]
    assert _normalize_segments(segs, 10) == [(1, 5), (7, 8)]


def test_normalize_drops_tiny_and_inverted():
    segs = [{"start": 1, "end": 1.04}, {"start": 3, "end": 2}, {"start": 5, "end": 5.05}]
    assert _normalize_segments(segs, 10) == [(5, 5.05)]


def test_normalize_drops_segments_past_end():
    assert _normalize_segments([{"start": 11, "end": 12}], 10) == []


def test_normalize_unknown_duration_keeps_end():
    assert _normalize_segments([{"start": 1, "end": 50}], 0) == [(1, 50)]


def test_normalize_bad_segment_raises():
    with pytest.raises(ValueError):
        _normalize_segments([{"begin": 1}], 10)


def test_vertical_profiles_listed():
    names = {p["name"] for p in project_list_profiles()["data"]}
    assert {"vertical1080p30", "vertical1080p60"} <= names


# ── build (needs ffmpeg for the test clip) ───────────────────────


@pytest.fixture
def av_clip(tmp_path):
    """10 s testsrc + 440 Hz sine, 640x360."""
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        pytest.skip("ffmpeg/ffprobe not installed")
    path = tmp_path / "src.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30:duration=10",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=10",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path),
        ],
        check=True, capture_output=True, timeout=60,
    )
    return str(path)


def _new_project(tmp_path, clip, profile="hd1080p30"):
    assert project_new(str(tmp_path / "p.kdenlive-cli.json"), profile=profile)["success"]
    assert bin_import_clip(clip)["success"]
    assert timeline_add_track()["success"]


@needs_ffmpeg
def test_build_three_segments_and_single_undo(tmp_path, av_clip):
    _new_project(tmp_path, av_clip)
    segs = [{"start": 6, "end": 8}, {"start": 0.5, "end": 1.5}, {"start": 3, "end": 4.5}]
    r = timeline_build_from_segments("clip0", segs)
    assert r["success"], r
    d = r["data"]
    assert d["placed"] == 3
    assert d["track"] == 0
    assert d["kept_seconds"] == pytest.approx(4.5)
    assert d["timeline_duration"] == pytest.approx(4.5)

    clips = track_get_info(0)["data"]["clips"]
    assert [(c["in"], c["out"]) for c in clips] == [(0.5, 1.5), (3, 4.5), (6, 8)]
    assert [c["position"] for c in clips] == pytest.approx([0, 1, 2.5])

    # source has audio -> mirrored on an auto-created audio track
    assert d["audio_track"] is not None
    audio = track_get_info(d["audio_track"])["data"]
    assert audio["type"] == "audio"
    assert [(c["in"], c["out"], c["position"]) for c in audio["clips"]] == [
        (c["in"], c["out"], c["position"]) for c in clips
    ]

    assert session_undo()["success"]
    assert track_get_info(0)["data"]["clips"] == []
    assert not track_get_info(d["audio_track"])["success"]  # auto-created track undone too
    assert timeline_get_duration()["data"]["duration"] == 0


@needs_ffmpeg
def test_build_start_gap_and_json_file(tmp_path, av_clip):
    _new_project(tmp_path, av_clip)
    seg_file = tmp_path / "keep.json"
    seg_file.write_text(json.dumps({"segments": [{"start": 0, "end": 1}, {"start": 2, "end": 3}]}))
    r = timeline_build_from_segments("clip0", str(seg_file), start=5.0, gap=0.5, include_audio=False)
    assert r["success"], r
    assert r["data"]["audio_track"] is None
    clips = track_get_info(0)["data"]["clips"]
    assert [c["position"] for c in clips] == pytest.approx([5.0, 6.5])
    assert r["data"]["timeline_duration"] == pytest.approx(7.5)


@needs_ffmpeg
def test_build_empty_after_validation_is_error(tmp_path, av_clip):
    _new_project(tmp_path, av_clip)
    r = timeline_build_from_segments("clip0", [{"start": 20, "end": 30}, {"start": 1, "end": 1.01}])
    assert not r["success"]
    assert track_get_info(0)["data"]["clips"] == []


@needs_ffmpeg
def test_build_missing_track_is_error(tmp_path, av_clip):
    _new_project(tmp_path, av_clip)
    r = timeline_build_from_segments("clip0", [{"start": 0, "end": 1}], track=7)
    assert not r["success"]


# ── reframe ──────────────────────────────────────────────────────


@needs_ffmpeg
def test_reframe_vertical_rect(tmp_path, av_clip):
    _new_project(tmp_path, av_clip, profile="vertical1080p30")
    assert timeline_build_from_segments("clip0", [{"start": 0, "end": 1}])["success"]
    width = 1920 * 16 / 9
    r = clip_reframe_vertical(0, 0)
    assert r["success"], r
    assert r["data"]["params"]["transition.rect"] == f"{round(-(width - 1080) / 2)} 0 {round(width)} 1920 1"
    # second call updates in place, x_offset=1 shows the right edge
    r = clip_reframe_vertical(0, 0, x_offset=1.0)
    assert r["data"]["params"]["transition.rect"].startswith(f"{round(-(width - 1080))} ")
    assert len(filter_list(0, 0)["data"]) == 1
    assert "transition.rect" in export_xml()["data"]["xml"]
    assert not clip_reframe_vertical(0, 0, x_offset=2)["success"]


@needs_ffmpeg
def test_reframe_rejects_landscape_project(tmp_path, av_clip):
    _new_project(tmp_path, av_clip)
    assert timeline_build_from_segments("clip0", [{"start": 0, "end": 1}])["success"]
    assert not clip_reframe_vertical(0, 0)["success"]


@needs_ffmpeg
@needs_melt
def test_build_renders_with_audio(tmp_path, av_clip):
    _new_project(tmp_path, av_clip, profile="vertical1080p30")
    assert timeline_build_from_segments("clip0", [{"start": 1, "end": 2}, {"start": 5, "end": 6}])["success"]
    assert clip_reframe_vertical(0, 0)["success"]
    out = str(tmp_path / "out.mp4")
    assert export_render(out)["success"]
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration",
         "-of", "json", out],
        capture_output=True, text=True, check=True,
    )
    info = json.loads(probe.stdout)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (video["width"], video["height"]) == (1080, 1920)
    assert float(info["format"]["duration"]) == pytest.approx(2.0, abs=0.15)
    vol = subprocess.run(
        ["ffmpeg", "-i", out, "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True,
    ).stderr
    mean = float(vol.split("mean_volume:")[1].split("dB")[0])
    assert mean > -60, "mirrored audio track should be audible"
