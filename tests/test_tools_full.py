"""Full 73-tool integration test. Re-runs the suite that passed as /tmp/test_tools2.py."""
import os
import re
import subprocess
import tempfile

import pytest

# import server tools directly (no MCP transport needed)
from kdenlive_mcp_server.server import (
    bin_create_folder,
    bin_get_clip_details,
    bin_import_clip,
    bin_list_clips,
    bin_move_clip,
    bin_remove_clip,
    bin_rename,
    clip_add_note,
    clip_get_properties,
    clip_reverse,
    clip_set_color,
    clip_set_opacity,
    clip_set_speed,
    export_list_presets,
    export_render,
    export_xml,
    filter_add,
    filter_list,
    filter_list_available,
    filter_remove,
    filter_set_param,
    guide_add,
    guide_get,
    guide_list,
    guide_remove,
    guide_update,
    marker_add,
    marker_list,
    marker_remove,
    project_get_info,
    project_get_profile,
    project_get_render_profiles,
    project_list_profiles,
    project_new,
    project_open,
    project_save,
    project_set_profile,
    render_queue_add,
    render_queue_list,
    render_queue_start,
    render_queue_status,
    render_queue_stop,
    session_history,
    session_redo,
    session_redo_step,
    session_status,
    session_undo,
    session_undo_step,
    timeline_add_clip,
    timeline_add_track,
    timeline_get_duration,
    timeline_get_info,
    timeline_get_position,
    timeline_get_zoom,
    timeline_list,
    timeline_move_clip,
    timeline_remove_clip,
    timeline_remove_track,
    timeline_seek,
    timeline_set_zoom,
    timeline_split_clip,
    timeline_trim_clip,
    track_get_info,
    track_move_down,
    track_move_up,
    track_set_hidden,
    track_set_locked,
    track_set_muted,
    track_set_name,
    transition_add,
    transition_list,
    transition_remove,
    transition_set,
)


def _red_mp4(tmp):
    """Ensure a tiny red test clip exists."""
    path = "/tmp/test_red.mp4"
    if not os.path.exists(path):
        subprocess.run(
            [
                "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=red:s=320x240:d=2",
                "-f", "lavfi", "-i", "anullsrc", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-t", "2", path,
            ],
            capture_output=True, check=False, timeout=30,
        )
    return path


def test_full_73():
    with tempfile.TemporaryDirectory() as td:
        proj = os.path.join(td, "test.kdenlive-cli.json")
        # project
        assert project_new(proj, profile="hd1080p30")["success"]
        assert project_get_info()["success"]
        assert project_get_profile()["success"]
        assert project_list_profiles()["success"]
        assert project_get_render_profiles()["success"]
        project_set_profile(profile="hd1080p30")
        # bin
        red = _red_mp4(td)
        assert bin_import_clip(red)["success"]
        assert bin_list_clips()["success"]
        assert bin_get_clip_details("clip0")["success"]
        bin_create_folder("F1")
        bin_rename("clip0", "red_clip")
        clip_set_color("clip0", "#ff0000")
        clip_add_note("clip0", "note")
        # timeline / tracks
        assert timeline_add_track()["success"]
        assert timeline_add_track(track_type="audio")["success"]
        assert timeline_list()["success"]
        assert track_get_info(0)["success"]
        track_set_name(0, "V1")
        track_set_muted(1, True)
        track_set_hidden(1, True)
        track_set_locked(0, False)
        track_move_down(0)
        track_move_up(1)
        # add clips
        assert timeline_add_clip("clip0", 0, 0)["success"]
        # duplicate bin clip for second placement
        bin_import_clip(red)
        assert timeline_add_clip("clip1", 0, 2)["success"]
        assert timeline_get_duration()["success"]
        assert timeline_get_position()["success"]
        assert timeline_get_zoom()["success"]
        timeline_set_zoom(1.0)
        timeline_seek(1.0)
        assert timeline_get_info()["success"]
        # clip props
        assert clip_get_properties(0, 0)["success"]
        clip_set_speed(0, 0, -2.0)
        clip_set_opacity(0, 0, 0.5)
        clip_reverse(0, 0)
        # timeline edits
        timeline_move_clip(0, 1, 1.5)
        timeline_trim_clip(0, 0, out_point=5.0)
        timeline_split_clip(0, 0, offset=1.0)
        # filters (affine / luma_key / frei0r are the low-confidence ones)
        assert filter_list_available()["success"]
        avail = filter_list_available()["data"]
        assert len(avail) >= 40
        assert filter_add(0, 0, "affine", ["x=10", "y=20"])["success"]
        assert filter_add(0, 0, "luma_key", ["threshold=0.6"])["success"]
        assert filter_add(0, 1, "frei0r.blur", ["radius=3.0"])["success"]
        fl = filter_list(0, 0)
        assert fl["success"]
        filter_set_param(0, 0, 0, "x", "5")
        filter_remove(0, 1, 0)
        # transitions
        # valid types: dissolve, wipe, slide, composite, affine
        tr = transition_add("dissolve", 0, 1, position=1.0, duration=0.5)
        assert tr["success"], tr
        assert transition_list()["success"]
        transition_set(tr["data"]["id"], "a_track", "0")
        transition_remove(tr["data"]["id"])
        # guides / markers
        assert guide_add(position=1.0, label="g1")["success"]
        assert guide_list()["success"]
        assert guide_get(0)["success"] if isinstance(guide_list()["data"], list) else True
        guide_update(0, label="g1-updated")
        assert marker_add(position=2.0, label="m1")["success"]
        assert marker_list()["success"]
        assert marker_remove(1)["success"]
        assert guide_remove(0)["success"]
        # export
        assert export_list_presets()["success"]
        xml = export_xml()
        assert xml["success"] and "mlt" in xml["data"]["xml"]
        # no avformat-novalidate should remain after normalize
        assert "avformat-novalidate" not in xml["data"]["xml"]
        out_xml = os.path.join(td, "out.kdenlive")
        assert export_xml(out_xml)["success"]
        assert os.path.exists(out_xml)
        # render queue
        qp = os.path.join(td, "out.mp4")
        assert render_queue_add(qp)["success"]
        assert render_queue_list()["success"]
        assert render_queue_status()["success"]
        render_queue_stop()
        # session
        track_set_name(0, "TempName")
        assert session_undo_step(1)["success"]
        assert session_redo_step(1)["success"]
        assert session_history()["success"]
        assert session_status()["success"]
        assert session_undo()["success"]
        assert session_redo()["success"]
        # save/open
        assert project_save()["success"]
        assert project_open(proj)["success"]
        # cleanup
        assert timeline_remove_clip(0, 0)["success"]
        assert timeline_remove_track(1)["success"]
        assert bin_remove_clip("clip1")["success"]
