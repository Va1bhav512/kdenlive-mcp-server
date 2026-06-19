"""FastMCP server wrapping cli-anything-kdenlive for LLM-driven video editing.

Uses the cli-anything-kdenlive Python API directly instead of subprocess
so that the in-memory session persists across tool calls.
"""

from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from cli_anything.kdenlive.core import (
    project as proj_mod,
    bin as bin_mod,
    timeline as tl_mod,
    filters as filt_mod,
    transitions as trans_mod,
    guides as guide_mod,
    export as export_mod,
)
from cli_anything.kdenlive.core.session import Session

server = FastMCP("kdenlive-mcp-server")

_session = Session()


# ── helpers ──────────────────────────────────────────────────────


def _ok(data: Any) -> dict[str, Any]:
    return {"success": True, "data": data}


def _err(msg: str) -> dict[str, Any]:
    return {"success": False, "error": msg}


def _require_project() -> dict[str, Any] | None:
    if not _session.has_project():
        return _err("No project open. Call project_new or project_open first.")
    return None


def _save() -> None:
    """Persist the session project to disk."""
    if _session.has_project() and _session.project_path:
        _session.save_session()


# ── Project & Environment ────────────────────────────────────────


@server.tool()
def project_new(
    output_path: str,
    profile: str | None = None,
    name: str = "untitled",
    width: int = 1920,
    height: int = 1080,
    fps_num: int = 30,
    fps_den: int = 1,
) -> dict[str, Any]:
    """Create a brand new Kdenlive project session.

    After this call the project path is stored so subsequent tools
    automatically target this project.

    Args:
        output_path: Path where the project JSON will be saved (.kdenlive-cli.json).
        profile: Preset profile (hd1080p30, hd1080p25, hd720p60, 4k30, 4k60, sd_pal, sd_ntsc).
            Overrides width/height/fps if set.
        name: Human-readable project name.
        width: Video width in pixels (ignored when profile is set).
        height: Video height in pixels (ignored when profile is set).
        fps_num: FPS numerator (ignored when profile is set).
        fps_den: FPS denominator (ignored when profile is set).
    """
    try:
        proj = proj_mod.create_project(
            name=name, profile=profile,
            width=width, height=height,
            fps_num=fps_num, fps_den=fps_den,
        )
        _session.set_project(proj, os.path.abspath(output_path))
        _session.save_session()
        info = proj_mod.get_project_info(proj)
        return _ok(info)
    except (ValueError, FileNotFoundError, RuntimeError) as e:
        return _err(str(e))


@server.tool()
def project_open(project_path: str) -> dict[str, Any]:
    """Load an existing .kdenlive-cli.json project into the session.

    Args:
        project_path: Path to an existing project file.
    """
    resolved = os.path.abspath(project_path)
    if not os.path.exists(resolved):
        return _err(f"Project file not found: {resolved}")
    try:
        proj = proj_mod.open_project(resolved)
        _session.set_project(proj, resolved)
        info = proj_mod.get_project_info(proj)
        return _ok(info)
    except (ValueError, FileNotFoundError, RuntimeError) as e:
        return _err(str(e))


@server.tool()
def project_save(output_path: str | None = None) -> dict[str, Any]:
    """Persist the current project state to a file.

    Args:
        output_path: Optional path to write to. Defaults to the original project path.
    """
    err = _require_project()
    if err:
        return err
    try:
        saved = _session.save_session(
            os.path.abspath(output_path) if output_path else None
        )
        return _ok({"saved": saved})
    except (ValueError, RuntimeError) as e:
        return _err(str(e))


@server.tool()
def project_get_info() -> dict[str, Any]:
    """Return project metadata: FPS, resolution, track layout, bin clip count."""
    err = _require_project()
    if err:
        return err
    try:
        return _ok(proj_mod.get_project_info(_session.get_project()))
    except RuntimeError as e:
        return _err(str(e))


@server.tool()
def project_list_profiles() -> dict[str, Any]:
    """Enumerate all available video output profiles (hd1080p30, 4k60, sd_pal, etc.)."""
    return _ok(proj_mod.list_profiles())


# ── Project Bin (Assets) ─────────────────────────────────────────


@server.tool()
def bin_import_clip(
    clip_path: str,
    name: str | None = None,
    duration: float | None = None,
    clip_type: str = "video",
) -> dict[str, Any]:
    """Ingest a media file into the project bin for later timeline use.

    Args:
        clip_path: Path to the media file (video, audio, or image).
        name: Optional display name. Defaults to the filename.
        duration: Optional duration override in seconds (useful for images).
        clip_type: Media type hint: video, audio, image, color, title.
    """
    err = _require_project()
    if err:
        return err

    resolved = os.path.abspath(clip_path)
    if not os.path.exists(resolved):
        return _err(f"Media file not found: {clip_path}")

    try:
        _session.snapshot("Import clip")
        clip = bin_mod.import_clip(
            _session.get_project(), resolved,
            name=name, duration=duration or 0.0, clip_type=clip_type,
        )
        _save()
        return _ok(clip)
    except (ValueError, FileNotFoundError, RuntimeError, FileExistsError) as e:
        return _err(str(e))


@server.tool()
def bin_remove_clip(clip_id: str) -> dict[str, Any]:
    """Delete a clip from the media bin by its ID.

    Args:
        clip_id: The clip identifier from bin_list_clips or bin_import_clip.
    """
    err = _require_project()
    if err:
        return err
    try:
        _session.snapshot(f"Remove clip {clip_id}")
        removed = bin_mod.remove_clip(_session.get_project(), clip_id)
        _save()
        return _ok(removed)
    except (ValueError, RuntimeError, IndexError) as e:
        return _err(str(e))


@server.tool()
def bin_list_clips() -> dict[str, Any]:
    """List every asset in the project bin with ID, name, type, and duration."""
    err = _require_project()
    if err:
        return err
    return _ok(bin_mod.list_clips(_session.get_project()))


@server.tool()
def bin_get_clip_details(clip_id: str) -> dict[str, Any]:
    """Get detailed properties of a bin clip (length, aspect ratio, media info).

    Args:
        clip_id: The clip identifier from the bin.
    """
    err = _require_project()
    if err:
        return err
    try:
        return _ok(bin_mod.get_clip(_session.get_project(), clip_id))
    except (ValueError, RuntimeError) as e:
        return _err(str(e))


# ── Timeline Editing ─────────────────────────────────────────────


@server.tool()
def timeline_add_track(
    track_type: str = "video",
    track_name: str | None = None,
    mute: bool = False,
    hide: bool = False,
    locked: bool = False,
) -> dict[str, Any]:
    """Append a video or audio track to the timeline.

    Args:
        track_type: 'video' or 'audio'.
        track_name: Optional name (auto-generated if omitted).
        mute: Start muted.
        hide: Start hidden.
        locked: Prevent edits on this track.
    """
    err = _require_project()
    if err:
        return err
    try:
        _session.snapshot("Add track")
        track = tl_mod.add_track(
            _session.get_project(),
            name=track_name, track_type=track_type,
            mute=mute, hide=hide, locked=locked,
        )
        _save()
        return _ok(track)
    except (ValueError, RuntimeError) as e:
        return _err(str(e))


@server.tool()
def timeline_remove_track(track_id: int) -> dict[str, Any]:
    """Delete a track and all its clips from the timeline.

    Args:
        track_id: Numeric track identifier (from timeline_list).
    """
    err = _require_project()
    if err:
        return err
    try:
        _session.snapshot(f"Remove track {track_id}")
        removed = tl_mod.remove_track(_session.get_project(), track_id)
        _save()
        return _ok(removed)
    except (ValueError, RuntimeError, IndexError) as e:
        return _err(str(e))


@server.tool()
def timeline_add_clip(
    clip_id: str,
    track: int,
    position: float,
    in_point: float = 0.0,
    out_point: float | None = None,
) -> dict[str, Any]:
    """Place a bin clip onto a specific track at a given time position.

    Args:
        clip_id: Bin clip identifier to place (from bin_list_clips).
        track: Target track number.
        position: Start time on the timeline in seconds.
        in_point: Media in-point (crop start) in seconds.
        out_point: Media out-point (crop end) in seconds. Defaults to full duration.
    """
    err = _require_project()
    if err:
        return err
    try:
        _session.snapshot("Add clip to track")
        entry = tl_mod.add_clip_to_track(
            _session.get_project(), track, clip_id,
            position=position, in_point=in_point, out_point=out_point,
        )
        _save()
        return _ok(entry)
    except (ValueError, RuntimeError, IndexError) as e:
        return _err(str(e))


@server.tool()
def timeline_move_clip(
    track_id: int,
    clip_index: int,
    new_position: float,
) -> dict[str, Any]:
    """Reposition a clip on the same track to a new time position.

    Args:
        track_id: Track containing the clip.
        clip_index: 0-based index of the clip within the track.
        new_position: New timeline position in seconds.
    """
    err = _require_project()
    if err:
        return err
    try:
        _session.snapshot("Move clip")
        result = tl_mod.move_clip(
            _session.get_project(), track_id, clip_index, new_position,
        )
        _save()
        return _ok(result)
    except (ValueError, RuntimeError, IndexError) as e:
        return _err(str(e))


@server.tool()
def timeline_trim_clip(
    track_id: int,
    clip_index: int,
    in_point: float | None = None,
    out_point: float | None = None,
) -> dict[str, Any]:
    """Adjust the in/out crop handles of a timeline clip.

    Args:
        track_id: Track containing the clip.
        clip_index: 0-based index of the clip within the track.
        in_point: New in-point in seconds. None = leave unchanged.
        out_point: New out-point in seconds. None = leave unchanged.
    """
    err = _require_project()
    if err:
        return err
    try:
        _session.snapshot("Trim clip")
        result = tl_mod.trim_clip(
            _session.get_project(), track_id, clip_index,
            new_in=in_point, new_out=out_point,
        )
        _save()
        return _ok(result)
    except (ValueError, RuntimeError, IndexError) as e:
        return _err(str(e))


@server.tool()
def timeline_split_clip(
    track_id: int,
    clip_index: int,
    offset: float,
) -> dict[str, Any]:
    """Cut a clip into two independent pieces at a precise time offset.

    Args:
        track_id: Track containing the clip.
        clip_index: 0-based index of the clip within the track.
        offset: Time offset in seconds from the clip's start (0 < offset < clip duration).
    """
    err = _require_project()
    if err:
        return err
    try:
        _session.snapshot("Split clip")
        parts = tl_mod.split_clip(
            _session.get_project(), track_id, clip_index, offset,
        )
        _save()
        return _ok(parts)
    except (ValueError, RuntimeError, IndexError) as e:
        return _err(str(e))


@server.tool()
def timeline_remove_clip(
    track_id: int,
    clip_index: int,
) -> dict[str, Any]:
    """Delete a clip from the timeline.

    Args:
        track_id: Track containing the clip.
        clip_index: 0-based index of the clip within the track.
    """
    err = _require_project()
    if err:
        return err
    try:
        _session.snapshot("Remove clip from track")
        removed = tl_mod.remove_clip_from_track(
            _session.get_project(), track_id, clip_index,
        )
        _save()
        return _ok(removed)
    except (ValueError, RuntimeError, IndexError) as e:
        return _err(str(e))


@server.tool()
def timeline_list() -> dict[str, Any]:
    """Return all timeline tracks with clip counts, IDs, mute/lock status."""
    err = _require_project()
    if err:
        return err
    return _ok(tl_mod.list_tracks(_session.get_project()))


# ── Effects / Filters ────────────────────────────────────────────


@server.tool()
def filter_add(
    track_id: int,
    clip_index: int,
    filter_type: str,
    params: list[str] | None = None,
) -> dict[str, Any]:
    """Attach a video/audio effect to a timeline clip.

    Args:
        track_id: Track containing the clip.
        clip_index: 0-based clip index on that track.
        filter_type: Filter name (e.g. blur, brightness, frei0r.opacity, volume).
            Run filter_list_available for all options.
        params: 'key=value' parameter strings (e.g. ['radius=5.0', 'opacity=0.8']).
    """
    err = _require_project()
    if err:
        return err
    try:
        parsed_params: dict[str, Any] = {}
        if params:
            for p in params:
                if "=" not in p:
                    return _err(f"Invalid param format: '{p}'. Use key=value.")
                k, v = p.split("=", 1)
                try:
                    v = float(v) if "." in v else int(v)
                except ValueError:
                    pass
                parsed_params[k] = v

        _session.snapshot(f"Add filter {filter_type}")
        result = filt_mod.add_filter(
            _session.get_project(), track_id, clip_index,
            filter_type, params=parsed_params or None,
        )
        _save()
        return _ok(result)
    except (ValueError, RuntimeError, IndexError) as e:
        return _err(str(e))


@server.tool()
def filter_remove(
    track_id: int,
    clip_index: int,
    filter_index: int,
) -> dict[str, Any]:
    """Detach an effect from a clip.

    Args:
        track_id: Track containing the clip.
        clip_index: 0-based clip index.
        filter_index: 0-based filter index (see filter_list).
    """
    err = _require_project()
    if err:
        return err
    try:
        _session.snapshot("Remove filter")
        removed = filt_mod.remove_filter(
            _session.get_project(), track_id, clip_index, filter_index,
        )
        _save()
        return _ok(removed)
    except (ValueError, RuntimeError, IndexError) as e:
        return _err(str(e))


@server.tool()
def filter_set_param(
    track_id: int,
    clip_index: int,
    filter_index: int,
    parameter: str,
    value: str,
) -> dict[str, Any]:
    """Update a single parameter on an active filter.

    Args:
        track_id: Track containing the clip.
        clip_index: 0-based clip index.
        filter_index: 0-based filter index.
        parameter: Parameter name (e.g. radius, opacity, level).
        value: New value (auto-converted to int/float if numeric).
    """
    err = _require_project()
    if err:
        return err
    try:
        parsed: Any = value
        try:
            parsed = float(value) if "." in value else int(value)
        except ValueError:
            pass

        _session.snapshot("Set filter param")
        result = filt_mod.set_filter_param(
            _session.get_project(), track_id, clip_index,
            filter_index, parameter, parsed,
        )
        _save()
        return _ok(result)
    except (ValueError, RuntimeError, IndexError) as e:
        return _err(str(e))


@server.tool()
def filter_list(track_id: int, clip_index: int) -> dict[str, Any]:
    """List all active filters on a specific timeline clip.

    Args:
        track_id: Track containing the clip.
        clip_index: 0-based clip index.
    """
    err = _require_project()
    if err:
        return err
    try:
        return _ok(filt_mod.list_filters(
            _session.get_project(), track_id, clip_index,
        ))
    except (ValueError, RuntimeError, IndexError) as e:
        return _err(str(e))


@server.tool()
def filter_list_available(category: str | None = None) -> dict[str, Any]:
    """Discover all filters the Kdenlive runtime exposes.

    Args:
        category: Optional category filter (e.g. blur, color, audio).
    """
    return _ok(filt_mod.list_available(category))


# ── Transitions ──────────────────────────────────────────────────


@server.tool()
def transition_add(
    transition_type: str,
    track_a: int,
    track_b: int,
    position: float = 0.0,
    duration: float = 1.0,
    params: list[str] | None = None,
) -> dict[str, Any]:
    """Create a blend transition (crossfade, wipe, etc.) between two track layers.

    Args:
        transition_type: Transition name (e.g. crossfade, luma, mix).
        track_a: Upper track index.
        track_b: Lower track index.
        position: Start time on the timeline in seconds.
        duration: Transition length in seconds.
        params: 'key=value' parameter strings.
    """
    err = _require_project()
    if err:
        return err
    try:
        parsed_params: dict[str, Any] = {}
        if params:
            for p in params:
                if "=" not in p:
                    return _err(f"Invalid param format: '{p}'. Use key=value.")
                k, v = p.split("=", 1)
                try:
                    v = float(v) if "." in v else int(v)
                except ValueError:
                    pass
                parsed_params[k] = v

        _session.snapshot(f"Add transition {transition_type}")
        result = trans_mod.add_transition(
            _session.get_project(), transition_type,
            track_a, track_b,
            position=position, duration=duration,
            params=parsed_params or None,
        )
        _save()
        return _ok(result)
    except (ValueError, RuntimeError, IndexError) as e:
        return _err(str(e))


@server.tool()
def transition_remove(transition_id: int) -> dict[str, Any]:
    """Delete a transition by its numeric ID.

    Args:
        transition_id: Transition identifier.
    """
    err = _require_project()
    if err:
        return err
    try:
        _session.snapshot(f"Remove transition {transition_id}")
        removed = trans_mod.remove_transition(_session.get_project(), transition_id)
        _save()
        return _ok(removed)
    except (ValueError, RuntimeError, IndexError) as e:
        return _err(str(e))


@server.tool()
def transition_set(
    transition_id: int,
    param_name: str,
    value: str,
) -> dict[str, Any]:
    """Modify a parameter on an existing transition.

    Args:
        transition_id: Transition identifier.
        param_name: Parameter name.
        value: New value (auto-converted to numeric if applicable).
    """
    err = _require_project()
    if err:
        return err
    try:
        parsed: Any = value
        try:
            parsed = float(value) if "." in value else int(value)
        except ValueError:
            pass

        _session.snapshot("Set transition param")
        result = trans_mod.set_transition(
            _session.get_project(), transition_id, param_name, parsed,
        )
        _save()
        return _ok(result)
    except (ValueError, RuntimeError, IndexError) as e:
        return _err(str(e))


@server.tool()
def transition_list() -> dict[str, Any]:
    """List all transitions on the timeline."""
    err = _require_project()
    if err:
        return err
    return _ok(trans_mod.list_transitions(_session.get_project()))


# ── Guides / Markers ─────────────────────────────────────────────


@server.tool()
def guide_add(
    position: float,
    label: str = "",
    guide_type: str = "default",
    comment: str = "",
) -> dict[str, Any]:
    """Place a navigation guide marker along the timeline.

    Args:
        position: Time position in seconds.
        label: Short label for the guide.
        guide_type: 'default', 'chapter', or 'segment'.
        comment: Optional longer description.
    """
    err = _require_project()
    if err:
        return err
    try:
        _session.snapshot("Add guide")
        g = guide_mod.add_guide(
            _session.get_project(), position,
            label=label, guide_type=guide_type, comment=comment,
        )
        _save()
        return _ok(g)
    except (ValueError, RuntimeError, IndexError) as e:
        return _err(str(e))


@server.tool()
def guide_remove(guide_id: int) -> dict[str, Any]:
    """Delete a guide marker by its ID.

    Args:
        guide_id: Numeric guide identifier.
    """
    err = _require_project()
    if err:
        return err
    try:
        _session.snapshot(f"Remove guide {guide_id}")
        removed = guide_mod.remove_guide(_session.get_project(), guide_id)
        _save()
        return _ok(removed)
    except (ValueError, RuntimeError, IndexError) as e:
        return _err(str(e))


@server.tool()
def guide_list() -> dict[str, Any]:
    """Return all guide markers on the timeline."""
    err = _require_project()
    if err:
        return err
    return _ok(guide_mod.list_guides(_session.get_project()))


# ── Export / Rendering ───────────────────────────────────────────


@server.tool()
def export_xml(output_path: str | None = None) -> dict[str, Any]:
    """Generate Kdenlive/MLT XML for the current project.

    Args:
        output_path: Optional file path to write the XML to.
    """
    err = _require_project()
    if err:
        return err
    try:
        xml = export_mod.generate_kdenlive_xml(_session.get_project())
        if output_path:
            with open(output_path, "w") as f:
                f.write(xml)
            return _ok({"path": output_path, "size": len(xml), "xml": xml})
        return _ok({"xml": xml})
    except (ValueError, RuntimeError, OSError) as e:
        return _err(str(e))


@server.tool()
def export_list_presets() -> dict[str, Any]:
    """List all available render presets for final video output."""
    return _ok(export_mod.list_render_presets())


@server.tool()
def export_render(
    output_path: str,
    preset: str | None = None,
) -> dict[str, Any]:
    """Render the project to a video file via melt.

    Generates MLT XML from the current project then pipes it through melt.
    Requires 'melt' on the system (apt install melt).

    Args:
        output_path: Destination video file (e.g. output.mp4).
        preset: Optional render preset name (see export_list_presets).
    """
    err = _require_project()
    if err:
        return err
    try:
        import subprocess

        xml = export_mod.generate_kdenlive_xml(_session.get_project())
        if not xml.strip():
            return _err("No XML content generated from project")

        melt_cmd = ["melt", "-"]
        consumer = f"avformat:{os.path.abspath(output_path)}"
        if preset:
            melt_cmd += ["-consumer", consumer, f"preset={preset}"]
        else:
            melt_cmd += ["-consumer", consumer]

        result = subprocess.run(
            melt_cmd, input=xml, capture_output=True, text=True,
        )
        if result.returncode != 0:
            return _err(result.stderr.strip() or f"melt exit code {result.returncode}")

        return _ok({"output": output_path, "info": result.stdout[:500]})
    except FileNotFoundError:
        return _err("melt binary not found. Install: apt install melt")
    except OSError as e:
        return _err(str(e))


# ── Session Management ───────────────────────────────────────────


@server.tool()
def session_undo() -> dict[str, Any]:
    """Revert the most recent state change (up to 50 history entries)."""
    if not _session.has_project():
        return _err("No project loaded.")
    try:
        desc = _session.undo()
        _save()
        return _ok({"undone": desc})
    except RuntimeError as e:
        return _err(str(e))


@server.tool()
def session_redo() -> dict[str, Any]:
    """Reapply the last undone operation."""
    if not _session.has_project():
        return _err("No project loaded.")
    try:
        desc = _session.redo()
        _save()
        return _ok({"redone": desc})
    except RuntimeError as e:
        return _err(str(e))


@server.tool()
def session_status() -> dict[str, Any]:
    """Inspect session state: project loaded, modified flag, history depth."""
    return _ok(_session.status())


@server.tool()
def session_history() -> dict[str, Any]:
    """List all undo/redo history entries with descriptions."""
    if not _session.has_project():
        return _err("No project loaded.")
    return _ok(_session.list_history())


# ── Entry Point ──────────────────────────────────────────────────


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
