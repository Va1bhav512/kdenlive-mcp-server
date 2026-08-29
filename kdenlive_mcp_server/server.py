"""FastMCP server wrapping cli-anything-kdenlive for LLM-driven video editing.

Uses the cli-anything-kdenlive Python API directly instead of subprocess
so that the in-memory session persists across tool calls.
"""

from __future__ import annotations

import os
import re
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

# ── global state for timeline navigation & render queue ───────────
_render_queue: list[dict[str, Any]] = []
_render_status: dict[str, Any] = {"running": False, "current": None, "completed": 0, "total": 0}


# Extend filter registry with additional frei0r/effect filters
_EXTRA_FILTERS: dict[str, dict[str, Any]] = {
    "affine": {"mlt_service": "affine", "category": "transform", "params": {"x": {"type": "float", "default": 0}, "y": {"type": "float", "default": 0}, "scale_x": {"type": "float", "default": 1}, "scale_y": {"type": "float", "default": 1}, "angle": {"type": "float", "default": 0}}},
    "luma_key": {"mlt_service": "luminance", "category": "keying", "params": {"threshold": {"type": "float", "default": 0.5}, "slope": {"type": "float", "default": 0.1}}},
    "opacity": {"mlt_service": "frei0r.opacity", "category": "effect", "params": {"opacity": {"type": "float", "default": 1.0}}},
    "frei0r.opacity": {"mlt_service": "frei0r.opacity", "category": "effect", "params": {"opacity": {"type": "float", "default": 1.0}}},
    "frei0r.blur": {"mlt_service": "frei0r.blur", "category": "effect", "params": {"radius": {"type": "float", "default": 5.0}}},
    "frei0r.sharpness": {"mlt_service": "frei0r.sharpness", "category": "effect", "params": {"amount": {"type": "float", "default": 0.5}}},
    "frei0r.contrast": {"mlt_service": "frei0r.contrast0r", "category": "color", "params": {"contrast": {"type": "float", "default": 1.0}}},
    "frei0r.brightness": {"mlt_service": "frei0r.brightness", "category": "color", "params": {"brightness": {"type": "float", "default": 0.0}}},
    "frei0r.saturation": {"mlt_service": "frei0r.saturat0r", "category": "color", "params": {"saturation": {"type": "float", "default": 1.0}}},
    "frei0r.hue": {"mlt_service": "frei0r.hueshift0r", "category": "color", "params": {"hue": {"type": "float", "default": 0.0}}},
    "frei0r.gamma": {"mlt_service": "frei0r.gamma", "category": "color", "params": {"gamma": {"type": "float", "default": 1.0}}},
    "frei0r.invert": {"mlt_service": "frei0r.invert0r", "category": "color", "params": {}},
    "frei0r.mirror": {"mlt_service": "frei0r.mirror", "category": "effect", "params": {"mirror_x": {"type": "bool", "default": False}, "mirror_y": {"type": "bool", "default": False}}},
    "frei0r.flip": {"mlt_service": "frei0r.flippo", "category": "effect", "params": {}},
    "frei0r.sepia": {"mlt_service": "frei0r.sopsat", "category": "color", "params": {"amount": {"type": "float", "default": 0.5}}},
    "frei0r.vignette": {"mlt_service": "frei0r.vignette", "category": "effect", "params": {"radius": {"type": "float", "default": 0.5}, "softness": {"type": "float", "default": 0.2}}},
    "frei0r.glow": {"mlt_service": "frei0r.glow", "category": "effect", "params": {"blur": {"type": "float", "default": 5.0}}},
    "frei0r.sobel": {"mlt_service": "frei0r.sobel", "category": "effect", "params": {}},
    "frei0r.emboss": {"mlt_service": "frei0r.emboss", "category": "effect", "params": {"azimuth": {"type": "float", "default": 30}, "elevation": {"type": "float", "default": 30}}},
    "frei0r.pixelize": {"mlt_service": "frei0r.pixeliz0r", "category": "effect", "params": {"blocksize": {"type": "int", "default": 8}}},
    "frei0r.scanline": {"mlt_service": "frei0r.scanline0r", "category": "effect", "params": {"line_height": {"type": "int", "default": 2}}},
    "frei0r.distort": {"mlt_service": "frei0r.dist0r", "category": "effect", "params": {"amount": {"type": "float", "default": 0.1}}},
    "frei0r.nervous": {"mlt_service": "frei0r.nervous", "category": "effect", "params": {}},
    "frei0r.cartoon": {"mlt_service": "frei0r.cartoon", "category": "effect", "params": {"threshold": {"type": "float", "default": 0.5}}},
    "frei0r.bw0r": {"mlt_service": "frei0r.bw0r", "category": "color", "params": {}},
    "frei0r.tint": {"mlt_service": "frei0r.tint0r", "category": "color", "params": {"color": {"type": "str", "default": "#ff0000"}}},
    "frei0r.curves": {"mlt_service": "frei0r.curves", "category": "color", "params": {}},
    "frei0r.equalizer": {"mlt_service": "frei0r.equaliz0r", "category": "color", "params": {}},
    "frei0r.noise": {"mlt_service": "frei0r.noise", "category": "effect", "params": {"amount": {"type": "float", "default": 0.1}}},
    "frei0r.lens_correction": {"mlt_service": "frei0r.lenscorrection", "category": "effect", "params": {"k1": {"type": "float", "default": 0}, "k2": {"type": "float", "default": 0}}},
    "chroma_key_advanced": {"mlt_service": "frei0r.select0r", "category": "keying", "params": {"color": {"type": "str", "default": "#00ff00"}, "variance": {"type": "float", "default": 0.2}, "slope": {"type": "float", "default": 0.1}}},
    "color_balance": {"mlt_service": "avfilter.colorbalance", "category": "color", "params": {"red": {"type": "float", "default": 0}, "green": {"type": "float", "default": 0}, "blue": {"type": "float", "default": 0}}},
    "white_balance": {"mlt_service": "avfilter.colortemperature", "category": "color", "params": {"temperature": {"type": "float", "default": 6500}}},
    "unsharp": {"mlt_service": "avfilter.unsharp", "category": "effect", "params": {"amount": {"type": "float", "default": 1.0}}},
}
for _k, _v in _EXTRA_FILTERS.items():
    if _k not in filt_mod.FILTER_REGISTRY:
        filt_mod.FILTER_REGISTRY[_k] = _v

# patch validator to handle missing min/max and bool type
_orig_validate = filt_mod._validate_filter_params

def _tolerant_validate(filter_name: str, params: dict[str, Any]) -> dict[str, Any]:
    spec = filt_mod.FILTER_REGISTRY[filter_name]
    param_specs = spec["params"]
    unknown = set(params.keys()) - set(param_specs.keys())
    if unknown:
        raise ValueError(f"Unknown parameters for '{filter_name}': {', '.join(unknown)}. Valid: {', '.join(param_specs.keys())}")
    result: dict[str, Any] = {}
    for pname, pspec in param_specs.items():
        value = params.get(pname, pspec["default"])
        ptype = pspec["type"]
        if ptype == "float":
            value = float(value)
            if "min" in pspec and "max" in pspec:
                if value < pspec["min"] or value > pspec["max"]:
                    raise ValueError(f"Parameter '{pname}' value {value} out of range [{pspec['min']}, {pspec['max']}].")
        elif ptype == "int":
            value = int(value)
            if "min" in pspec and "max" in pspec:
                if value < pspec["min"] or value > pspec["max"]:
                    raise ValueError(f"Parameter '{pname}' value {value} out of range [{pspec['min']}, {pspec['max']}].")
        elif ptype == "bool":
            # accept bool/int/str
            if isinstance(value, str):
                value = value.lower() in ("1", "true", "yes")
            else:
                value = bool(value)
        elif ptype == "str":
            value = str(value)
        result[pname] = value
    return result

filt_mod._validate_filter_params = _tolerant_validate


# ── helpers ──────────────────────────────────────────────────────


def _ok(data: Any) -> dict[str, Any]:
    return {"success": True, "data": data}


def _err(msg: str) -> dict[str, Any]:
    return {"success": False, "error": msg}


def _resolve_path(p: str) -> str:
    """Expand ~ and env vars, then abspath. Handles ~/ correctly."""
    return os.path.abspath(os.path.expanduser(os.path.expandvars(p)))


def _probe_duration(media_path: str) -> float | None:
    """Try ffprobe to get duration in seconds; returns None if unavailable."""
    try:
        import subprocess
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", media_path],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except (FileNotFoundError, ValueError, subprocess.TimeoutExpired, OSError):
        pass
    return None


def _normalize_mlt_producers(xml: str) -> str:
    """Fix MLT producer settings so real-world media actually decodes.

    The kdenlive-cli library emits ``avformat-novalidate`` producers with
    hardcoded ``video_index=0``/``audio_index=1``. On many real files
    (e.g. phone MP4s with yuvj420p / jpeg-range, or audio-as-stream-0
    layouts) ``avformat-novalidate`` silently outputs a blank/white frame
    and the forced indexes point video at the wrong stream. Using the
    validated ``avformat`` producer and letting it auto-select streams
    (as ``melt file.mp4`` does by default) decodes correctly.

    This only rewrites producer properties; it does not change clips,
    tracks, filters, or transitions.
    """
    xml = xml.replace("avformat-novalidate", "avformat")
    xml = re.sub(r'<property name="video_index">[^<]*</property>\s*', "", xml)
    xml = re.sub(r'<property name="audio_index">[^<]*</property>\s*', "", xml)
    return xml



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
        resolved = _resolve_path(output_path)
        # if output_path is a directory, append default filename
        if os.path.isdir(resolved) or output_path.endswith(("/", os.sep)):
            resolved = os.path.join(resolved, f"{name}.kdenlive-cli.json")
        _session.set_project(proj, resolved)
        _session.save_session()
        info = proj_mod.get_project_info(proj)
        status = _session.status()
        info["saved_path"] = status["project_path"]
        info["saved"] = os.path.exists(status["project_path"]) if status["project_path"] else False
        info["modified"] = status["modified"]
        return _ok(info)
    except (ValueError, FileNotFoundError, RuntimeError) as e:
        return _err(str(e))


@server.tool()
def project_open(project_path: str) -> dict[str, Any]:
    """Load an existing .kdenlive-cli.json project into the session.

    Args:
        project_path: Path to an existing project file.
    """
    resolved = _resolve_path(project_path)
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
        resolved = _resolve_path(output_path) if output_path else None
        if resolved and (os.path.isdir(resolved) or output_path.endswith(("/", os.sep))):
            # directory given -> save inside with current name
            proj = _session.get_project()
            name = proj.get("name", "untitled")
            resolved = os.path.join(resolved, f"{name}.kdenlive-cli.json")
        saved = _session.save_session(resolved)
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
        info = proj_mod.get_project_info(_session.get_project())
        status = _session.status()
        info["saved_path"] = status.get("project_path")
        info["saved_exists"] = os.path.exists(status["project_path"]) if status.get("project_path") else False
        info["modified"] = status.get("modified")
        info["has_project"] = status.get("has_project")
        return _ok(info)
    except RuntimeError as e:
        return _err(str(e))


@server.tool()
def project_list_profiles() -> dict[str, Any]:
    """Enumerate all available video output profiles (hd1080p30, 4k60, sd_pal, etc.)."""
    return _ok(proj_mod.list_profiles())


@server.tool()
def project_get_profile() -> dict[str, Any]:
    """Get the current project's video profile (resolution, FPS, aspect ratio)."""
    err = _require_project()
    if err:
        return err
    try:
        proj = _session.get_project()
        profile = proj.get("profile", {})
        return _ok(profile)
    except RuntimeError as e:
        return _err(str(e))


@server.tool()
def project_set_profile(
    profile: str | None = None,
    width: int | None = None,
    height: int | None = None,
    fps_num: int | None = None,
    fps_den: int | None = None,
    progressive: bool | None = None,
    dar_num: int | None = None,
    dar_den: int | None = None,
) -> dict[str, Any]:
    """Set or update the project's video profile.

    Args:
        profile: Preset profile name (hd1080p30, hd1080p25, hd720p60, 4k30, 4k60, sd_pal, sd_ntsc).
            Overrides width/height/fps if set.
        width: Video width in pixels.
        height: Video height in pixels.
        fps_num: FPS numerator.
        fps_den: FPS denominator.
        progressive: Whether video is progressive.
        dar_num: Display aspect ratio numerator.
        dar_den: Display aspect ratio denominator.
    """
    err = _require_project()
    if err:
        return err
    try:
        proj = _session.get_project()
        current_profile = proj.get("profile", {})

        if profile:
            if profile not in proj_mod.PROFILES:
                return _err(f"Unknown profile: {profile}")
            new_profile = proj_mod.PROFILES[profile]
        else:
            new_profile = {
                "name": "custom",
                "width": width or current_profile.get("width", 1920),
                "height": height or current_profile.get("height", 1080),
                "fps_num": fps_num or current_profile.get("fps_num", 30),
                "fps_den": fps_den or current_profile.get("fps_den", 1),
                "progressive": progressive if progressive is not None else current_profile.get("progressive", True),
                "dar_num": dar_num or current_profile.get("dar_num", 16),
                "dar_den": dar_den or current_profile.get("dar_den", 9),
            }

        _session.snapshot("Set project profile")
        proj["profile"] = new_profile
        _save()
        return _ok(new_profile)
    except (ValueError, RuntimeError) as e:
        return _err(str(e))


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
        duration: Optional duration override in seconds (useful for images). If None, auto-probed via ffprobe.
        clip_type: Media type hint: video, audio, image, color, title.
    """
    err = _require_project()
    if err:
        return err

    resolved = _resolve_path(clip_path)
    if not os.path.exists(resolved):
        return _err(f"Media file not found: {clip_path} (resolved: {resolved})")

    try:
        # auto-probe duration if not provided
        effective_duration = duration
        if effective_duration is None:
            effective_duration = _probe_duration(resolved)
            # for images, default 5s if probe fails
            if effective_duration is None:
                effective_duration = 5.0 if clip_type in ("image", "color", "title") else 0.0
        _session.snapshot("Import clip")
        clip = bin_mod.import_clip(
            _session.get_project(), resolved,
            name=name, duration=effective_duration or 0.0, clip_type=clip_type,
        )
        # if duration was 0 (probe failed for video), try to patch with probed value after import
        if clip.get("duration", 0.0) == 0.0 and clip_type == "video":
            probed = _probe_duration(resolved)
            if probed and probed > 0:
                clip["duration"] = probed
                _save()
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
        in_point: Media trim-in (where to start playback inside source) in seconds.
        out_point: Media trim-out (where to end playback inside source) in seconds. Defaults to full bin duration. Use timeline_trim_clip to adjust after placement.
    """
    err = _require_project()
    if err:
        return err
    try:
        proj = _session.get_project()
        # auto-resolve missing out_point when bin duration is 0 (unprobed image/video)
        if out_point is None:
            bin_clip = next((c for c in proj.get("bin", []) if c["id"] == clip_id), None)
            if bin_clip is not None:
                dur = bin_clip.get("duration", 0.0)
                if dur == 0.0:
                    # try probe source file
                    probed = _probe_duration(bin_clip.get("source", ""))
                    if probed and probed > 0:
                        bin_clip["duration"] = probed
                        dur = probed
                        _save()
                if dur == 0.0:
                    # still 0: guide user
                    return _err(
                        f"Bin clip {clip_id} has duration 0. Re-import with duration or provide out_point. "
                        f"For images use duration=5. Got in_point={in_point}, bin duration {dur}"
                    )
                out_point = dur
        _session.snapshot("Add clip to track")
        entry = tl_mod.add_clip_to_track(
            proj, track, clip_id,
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
    """Adjust the in/out trim handles of a timeline clip (not the crop filter).

    Args:
        track_id: Track containing the clip.
        clip_index: 0-based index of the clip within the track.
        in_point: New trim-in in seconds. None = leave unchanged.
        out_point: New trim-out in seconds. None = leave unchanged.
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
        output_path: Optional file path to write the XML to (e.g. ~/Downloads/myproj.kdenlive). If None, no file is written and XML is returned in data.xml for you to copy.
    """
    err = _require_project()
    if err:
        return err
    try:
        xml = _normalize_mlt_producers(export_mod.generate_kdenlive_xml(_session.get_project()))
        if output_path:
            resolved = _resolve_path(output_path)
            # ensure parent dir exists
            parent = os.path.dirname(resolved)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(resolved, "w") as f:
                f.write(xml)
            return _ok({"path": resolved, "size": len(xml), "xml": xml})
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
        import tempfile

        xml = _normalize_mlt_producers(export_mod.generate_kdenlive_xml(_session.get_project()))
        if not xml.strip():
            return _err("No XML content generated from project")

        # Write XML to temp file - more reliable than stdin pipe headless
        with tempfile.NamedTemporaryFile(mode="w", suffix=".mlt", delete=False) as tf:
            tf.write(xml)
            xml_path = tf.name
        try:
            resolved_out = _resolve_path(output_path)
            # ensure parent dir exists for output
            parent = os.path.dirname(resolved_out)
            if parent:
                os.makedirs(parent, exist_ok=True)
            consumer = f"avformat:{resolved_out}"
            melt_cmd = ["melt", xml_path]
            # add consumer via args
            if preset:
                melt_cmd += ["-consumer", consumer, f"preset={preset}"]
            else:
                melt_cmd += ["-consumer", consumer]
            # real_time=-1 avoids melt hanging (and producing blank/white output)
            # on certain files/clocks where the realtime consumer stalls.
            melt_cmd += ["real_time=-1"]

            env = os.environ.copy()
            env.setdefault("QT_QPA_PLATFORM", "offscreen")
            result = subprocess.run(
                melt_cmd, capture_output=True, text=True, timeout=300, env=env,
            )
            # melt often prints QThreadStorage warning but exit 0; treat warnings as non-fatal
            # only fail if no output file created
            if result.returncode != 0 and not os.path.exists(resolved_out):
                return _err(result.stderr.strip()[-1200:] or f"melt exit code {result.returncode}")
            if not os.path.exists(resolved_out):
                return _err(result.stderr.strip()[-1200:] or "melt did not create output")

            return _ok({"output": resolved_out, "info": result.stdout[:500], "stderr": result.stderr[:500]})
        finally:
            try:
                os.unlink(xml_path)
            except OSError:
                pass
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
    except Exception as e:
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
    except Exception as e:
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


@server.tool()
def project_get_render_profiles() -> dict[str, Any]:
    """Alias for project_list_profiles - get available render presets."""
    return _ok(export_mod.list_render_presets())


# ── Clip Properties (timeline) ───────────────────────────────────

def _get_timeline_clip(project: dict[str, Any], track_id: int, clip_index: int) -> dict[str, Any]:
    for t in project.get("tracks", []):
        if t["id"] == track_id:
            clips = t.get("clips", [])
            if 0 <= clip_index < len(clips):
                return clips[clip_index]
            raise IndexError(f"Clip index {clip_index} out of range (0-{len(clips)-1})")
    raise ValueError(f"Track not found: {track_id}")


@server.tool()
def clip_get_properties(track_id: int, clip_index: int) -> dict[str, Any]:
    """Get timeline clip properties: in/out, duration, speed, opacity, reverse."""
    err = _require_project()
    if err:
        return err
    try:
        proj = _session.get_project()
        clip = _get_timeline_clip(proj, track_id, clip_index)
        in_p = clip.get("in", 0.0)
        out_p = clip.get("out", 0.0)
        duration = out_p - in_p
        # speed from filters
        speed = 1.0
        opacity = 1.0
        reverse = False
        for f in clip.get("filters", []):
            if f.get("name") == "speed":
                speed = f.get("params", {}).get("speed", 1.0)
                if speed < 0:
                    reverse = True
            if f.get("name") in ("opacity", "frei0r.opacity"):
                opacity = f.get("params", {}).get("opacity", 1.0)
        # also bin clip duration
        bin_clip = None
        for c in proj.get("bin", []):
            if c["id"] == clip.get("clip_id"):
                bin_clip = c
                break
        return _ok({
            "track_id": track_id,
            "clip_index": clip_index,
            "clip_id": clip.get("clip_id"),
            "position": clip.get("position", 0.0),
            "in": in_p,
            "out": out_p,
            "duration": duration,
            "speed": speed,
            "opacity": opacity,
            "reverse": reverse,
            "filters": clip.get("filters", []),
            "bin_clip": bin_clip,
        })
    except (ValueError, IndexError, RuntimeError) as e:
        return _err(str(e))


@server.tool()
def clip_set_speed(track_id: int, clip_index: int, speed: float) -> dict[str, Any]:
    """Set playback speed of a timeline clip (1.0=normal, 2.0=2x, 0.5=half, negative=reverse)."""
    err = _require_project()
    if err:
        return err
    if speed == 0:
        return _err("Speed cannot be 0")
    try:
        proj = _session.get_project()
        clip = _get_timeline_clip(proj, track_id, clip_index)
        _session.snapshot(f"Set clip speed to {speed}")
        # find existing speed filter
        for f in clip.get("filters", []):
            if f.get("name") == "speed":
                f["params"]["speed"] = speed
                _save()
                return _ok(f)
        # add new
        spec = filt_mod.FILTER_REGISTRY.get("speed", {"mlt_service": "timewarp"})
        new_f = {"name": "speed", "mlt_service": spec["mlt_service"], "params": {"speed": speed}, "enabled": True}
        clip.setdefault("filters", []).append(new_f)
        _save()
        return _ok(new_f)
    except (ValueError, IndexError, RuntimeError) as e:
        return _err(str(e))


@server.tool()
def clip_reverse(track_id: int, clip_index: int) -> dict[str, Any]:
    """Reverse playback direction of a timeline clip (toggles)."""
    err = _require_project()
    if err:
        return err
    try:
        proj = _session.get_project()
        clip = _get_timeline_clip(proj, track_id, clip_index)
        _session.snapshot("Reverse clip")
        # find speed filter
        for f in clip.get("filters", []):
            if f.get("name") == "speed":
                cur = f.get("params", {}).get("speed", 1.0)
                f["params"]["speed"] = -cur
                _save()
                return _ok(f)
        # no speed filter -> add reverse speed -1
        spec = filt_mod.FILTER_REGISTRY.get("speed", {"mlt_service": "timewarp"})
        new_f = {"name": "speed", "mlt_service": spec["mlt_service"], "params": {"speed": -1.0}, "enabled": True}
        clip.setdefault("filters", []).append(new_f)
        _save()
        return _ok(new_f)
    except (ValueError, IndexError, RuntimeError) as e:
        return _err(str(e))


@server.tool()
def clip_set_opacity(track_id: int, clip_index: int, opacity: float) -> dict[str, Any]:
    """Set opacity of a timeline clip (0.0 transparent .. 1.0 opaque)."""
    err = _require_project()
    if err:
        return err
    if not 0.0 <= opacity <= 1.0:
        return _err("Opacity must be between 0.0 and 1.0")
    try:
        proj = _session.get_project()
        clip = _get_timeline_clip(proj, track_id, clip_index)
        _session.snapshot(f"Set opacity to {opacity}")
        for f in clip.get("filters", []):
            if f.get("name") in ("opacity", "frei0r.opacity"):
                f["params"]["opacity"] = opacity
                _save()
                return _ok(f)
        spec = filt_mod.FILTER_REGISTRY.get("opacity", {"mlt_service": "frei0r.opacity"})
        new_f = {"name": "opacity", "mlt_service": spec["mlt_service"], "params": {"opacity": opacity}, "enabled": True}
        clip.setdefault("filters", []).append(new_f)
        _save()
        return _ok(new_f)
    except (ValueError, IndexError, RuntimeError) as e:
        return _err(str(e))


# ── Track Management ─────────────────────────────────────────────

@server.tool()
def track_get_info(track_id: int) -> dict[str, Any]:
    """Get detailed info for a single track (including clips)."""
    err = _require_project()
    if err:
        return err
    try:
        proj = _session.get_project()
        for t in proj.get("tracks", []):
            if t["id"] == track_id:
                return _ok(t)
        return _err(f"Track not found: {track_id}")
    except RuntimeError as e:
        return _err(str(e))


@server.tool()
def track_set_name(track_id: int, name: str) -> dict[str, Any]:
    """Rename a track."""
    err = _require_project()
    if err:
        return err
    try:
        proj = _session.get_project()
        for t in proj.get("tracks", []):
            if t["id"] == track_id:
                _session.snapshot(f"Rename track {track_id}")
                t["name"] = name
                _save()
                return _ok(t)
        return _err(f"Track not found: {track_id}")
    except RuntimeError as e:
        return _err(str(e))


@server.tool()
def track_set_locked(track_id: int, locked: bool) -> dict[str, Any]:
    """Lock/unlock a track."""
    err = _require_project()
    if err:
        return err
    try:
        proj = _session.get_project()
        for t in proj.get("tracks", []):
            if t["id"] == track_id:
                _session.snapshot(f"Set locked={locked} for track {track_id}")
                t["locked"] = locked
                _save()
                return _ok(t)
        return _err(f"Track not found: {track_id}")
    except RuntimeError as e:
        return _err(str(e))


@server.tool()
def track_set_hidden(track_id: int, hidden: bool) -> dict[str, Any]:
    """Hide/show a track (video visibility)."""
    err = _require_project()
    if err:
        return err
    try:
        proj = _session.get_project()
        for t in proj.get("tracks", []):
            if t["id"] == track_id:
                _session.snapshot(f"Set hidden={hidden} for track {track_id}")
                t["hide"] = hidden
                _save()
                return _ok(t)
        return _err(f"Track not found: {track_id}")
    except RuntimeError as e:
        return _err(str(e))


@server.tool()
def track_set_muted(track_id: int, muted: bool) -> dict[str, Any]:
    """Mute/unmute a track (audio)."""
    err = _require_project()
    if err:
        return err
    try:
        proj = _session.get_project()
        for t in proj.get("tracks", []):
            if t["id"] == track_id:
                _session.snapshot(f"Set muted={muted} for track {track_id}")
                t["mute"] = muted
                _save()
                return _ok(t)
        return _err(f"Track not found: {track_id}")
    except RuntimeError as e:
        return _err(str(e))


@server.tool()
def track_move_up(track_id: int) -> dict[str, Any]:
    """Move track up one position (swap with previous)."""
    err = _require_project()
    if err:
        return err
    try:
        proj = _session.get_project()
        tracks = proj.get("tracks", [])
        idx = next((i for i, t in enumerate(tracks) if t["id"] == track_id), None)
        if idx is None:
            return _err(f"Track not found: {track_id}")
        if idx == 0:
            return _err("Track already at top")
        _session.snapshot(f"Move track {track_id} up")
        tracks[idx], tracks[idx - 1] = tracks[idx - 1], tracks[idx]
        _save()
        return _ok({"moved": track_id, "new_index": idx - 1})
    except RuntimeError as e:
        return _err(str(e))


@server.tool()
def track_move_down(track_id: int) -> dict[str, Any]:
    """Move track down one position (swap with next)."""
    err = _require_project()
    if err:
        return err
    try:
        proj = _session.get_project()
        tracks = proj.get("tracks", [])
        idx = next((i for i, t in enumerate(tracks) if t["id"] == track_id), None)
        if idx is None:
            return _err(f"Track not found: {track_id}")
        if idx == len(tracks) - 1:
            return _err("Track already at bottom")
        _session.snapshot(f"Move track {track_id} down")
        tracks[idx], tracks[idx + 1] = tracks[idx + 1], tracks[idx]
        _save()
        return _ok({"moved": track_id, "new_index": idx + 1})
    except RuntimeError as e:
        return _err(str(e))


# ── Timeline Navigation ──────────────────────────────────────────

@server.tool()
def timeline_get_duration() -> dict[str, Any]:
    """Get total timeline duration in seconds (max end time)."""
    err = _require_project()
    if err:
        return err
    try:
        proj = _session.get_project()
        max_end = 0.0
        for t in proj.get("tracks", []):
            for c in t.get("clips", []):
                end = c.get("position", 0.0) + (c.get("out", 0.0) - c.get("in", 0.0))
                # adjust for speed filter
                speed = 1.0
                for f in c.get("filters", []):
                    if f.get("name") == "speed":
                        speed = abs(f.get("params", {}).get("speed", 1.0))
                if speed != 0:
                    end = c.get("position", 0.0) + (c.get("out", 0.0) - c.get("in", 0.0)) / speed
                if end > max_end:
                    max_end = end
        return _ok({"duration": max_end})
    except RuntimeError as e:
        return _err(str(e))


@server.tool()
def timeline_get_position() -> dict[str, Any]:
    """Get current playhead position."""
    err = _require_project()
    if err:
        return err
    try:
        proj = _session.get_project()
        pos = proj.get("timeline_state", {}).get("position", 0.0)
        return _ok({"position": pos})
    except RuntimeError as e:
        return _err(str(e))


@server.tool()
def timeline_seek(position: float) -> dict[str, Any]:
    """Seek playhead to position (seconds)."""
    err = _require_project()
    if err:
        return err
    if position < 0:
        return _err("Position must be >= 0")
    try:
        proj = _session.get_project()
        if "timeline_state" not in proj:
            proj["timeline_state"] = {}
        proj["timeline_state"]["position"] = position
        _save()
        return _ok({"position": position})
    except RuntimeError as e:
        return _err(str(e))


@server.tool()
def timeline_get_zoom() -> dict[str, Any]:
    """Get timeline zoom level."""
    err = _require_project()
    if err:
        return err
    try:
        proj = _session.get_project()
        zoom = proj.get("timeline_state", {}).get("zoom", 1.0)
        return _ok({"zoom": zoom})
    except RuntimeError as e:
        return _err(str(e))


@server.tool()
def timeline_set_zoom(zoom: float) -> dict[str, Any]:
    """Set timeline zoom level (0.1 .. 10.0)."""
    err = _require_project()
    if err:
        return err
    if not 0.1 <= zoom <= 10.0:
        return _err("Zoom must be between 0.1 and 10.0")
    try:
        proj = _session.get_project()
        if "timeline_state" not in proj:
            proj["timeline_state"] = {}
        _session.snapshot(f"Set zoom to {zoom}")
        proj["timeline_state"]["zoom"] = zoom
        _save()
        return _ok({"zoom": zoom})
    except RuntimeError as e:
        return _err(str(e))


@server.tool()
def timeline_get_info() -> dict[str, Any]:
    """Get comprehensive timeline info: tracks+clips, duration, position, zoom, guides, markers, profile."""
    err = _require_project()
    if err:
        return err
    try:
        proj = _session.get_project()
        # duration
        max_end = 0.0
        for t in proj.get("tracks", []):
            for c in t.get("clips", []):
                speed = 1.0
                for f in c.get("filters", []):
                    if f.get("name") == "speed":
                        speed = abs(f.get("params", {}).get("speed", 1.0))
                end = c.get("position", 0.0) + (c.get("out", 0.0) - c.get("in", 0.0)) / max(speed, 0.01)
                if end > max_end:
                    max_end = end
        state = proj.get("timeline_state", {})
        return _ok({
            "tracks": proj.get("tracks", []),
            "track_summaries": tl_mod.list_tracks(proj),
            "duration": max_end,
            "position": state.get("position", 0.0),
            "zoom": state.get("zoom", 1.0),
            "guides": proj.get("guides", []),
            "markers": proj.get("markers", []),
            "profile": proj.get("profile", {}),
            "clip_count": sum(len(t.get("clips", [])) for t in proj.get("tracks", [])),
        })
    except RuntimeError as e:
        return _err(str(e))


# ── Guides / Markers extended ────────────────────────────────────

@server.tool()
def guide_get(guide_id: int) -> dict[str, Any]:
    """Get single guide by ID."""
    err = _require_project()
    if err:
        return err
    try:
        proj = _session.get_project()
        for g in proj.get("guides", []):
            if g["id"] == guide_id:
                return _ok(g)
        return _err(f"Guide not found: {guide_id}")
    except RuntimeError as e:
        return _err(str(e))


@server.tool()
def guide_update(
    guide_id: int,
    position: float | None = None,
    label: str | None = None,
    guide_type: str | None = None,
    comment: str | None = None,
) -> dict[str, Any]:
    """Update guide properties."""
    err = _require_project()
    if err:
        return err
    try:
        proj = _session.get_project()
        for g in proj.get("guides", []):
            if g["id"] == guide_id:
                _session.snapshot(f"Update guide {guide_id}")
                if position is not None:
                    if position < 0:
                        return _err("Position must be >=0")
                    g["position"] = position
                if label is not None:
                    g["label"] = label
                if guide_type is not None:
                    if guide_type not in guide_mod.GUIDE_TYPES:
                        return _err(f"Invalid guide type: {guide_type}")
                    g["type"] = guide_type
                if comment is not None:
                    g["comment"] = comment
                # re-sort
                proj["guides"].sort(key=lambda x: x["position"])
                _save()
                return _ok(g)
        return _err(f"Guide not found: {guide_id}")
    except RuntimeError as e:
        return _err(str(e))


@server.tool()
def marker_add(position: float, label: str = "", comment: str = "", marker_type: str = "default", track_id: int | None = None, clip_index: int | None = None) -> dict[str, Any]:
    """Add timeline or clip marker (markers separate from guides)."""
    err = _require_project()
    if err:
        return err
    if position < 0:
        return _err("Position must be >=0")
    try:
        proj = _session.get_project()
        _session.snapshot("Add marker")
        if "markers" not in proj:
            proj["markers"] = []
        # next id
        next_id = max([m["id"] for m in proj["markers"]], default=0) + 1
        marker = {
            "id": next_id,
            "position": position,
            "label": label,
            "comment": comment,
            "type": marker_type,
            "track_id": track_id,
            "clip_index": clip_index,
        }
        proj["markers"].append(marker)
        proj["markers"].sort(key=lambda x: x["position"])
        _save()
        return _ok(marker)
    except RuntimeError as e:
        return _err(str(e))


@server.tool()
def marker_list() -> dict[str, Any]:
    """List all markers."""
    err = _require_project()
    if err:
        return err
    try:
        proj = _session.get_project()
        return _ok(proj.get("markers", []))
    except RuntimeError as e:
        return _err(str(e))


@server.tool()
def marker_remove(marker_id: int) -> dict[str, Any]:
    """Remove marker by ID."""
    err = _require_project()
    if err:
        return err
    try:
        proj = _session.get_project()
        markers = proj.get("markers", [])
        for i, m in enumerate(markers):
            if m["id"] == marker_id:
                _session.snapshot(f"Remove marker {marker_id}")
                removed = markers.pop(i)
                _save()
                return _ok(removed)
        return _err(f"Marker not found: {marker_id}")
    except RuntimeError as e:
        return _err(str(e))


# ── Render Queue ─────────────────────────────────────────────────

@server.tool()
def render_queue_add(output_path: str, preset: str | None = None, in_point: float | None = None, out_point: float | None = None) -> dict[str, Any]:
    """Add job to render queue."""
    err = _require_project()
    if err:
        return err
    try:
        resolved_out = _resolve_path(output_path)
        job_id = len(_render_queue) + 1
        job = {
            "id": job_id,
            "output_path": resolved_out,
            "preset": preset,
            "in_point": in_point,
            "out_point": out_point,
            "status": "queued",
            "created": __import__("datetime").datetime.now().isoformat(),
        }
        _render_queue.append(job)
        _render_status["total"] = len(_render_queue)
        return _ok(job)
    except RuntimeError as e:
        return _err(str(e))


@server.tool()
def render_queue_list() -> dict[str, Any]:
    """List render queue jobs."""
    err = _require_project()
    if err:
        return err
    return _ok(_render_queue)


@server.tool()
def render_queue_status() -> dict[str, Any]:
    """Get render queue status."""
    err = _require_project()
    if err:
        return err
    return _ok({**_render_status, "queue_length": len(_render_queue), "jobs": _render_queue})


@server.tool()
def render_queue_start() -> dict[str, Any]:
    """Start processing render queue (renders sequentially via melt)."""
    err = _require_project()
    if err:
        return err
    if _render_status.get("running"):
        return _err("Render queue already running")
    if not _render_queue:
        return _err("Render queue empty")
    try:
        import subprocess
        import tempfile
        _render_status["running"] = True
        _render_status["completed"] = 0
        results = []
        for job in _render_queue:
            if job["status"] == "completed":
                continue
            job["status"] = "rendering"
            _render_status["current"] = job["id"]
            try:
                xml = _normalize_mlt_producers(export_mod.generate_kdenlive_xml(_session.get_project()))
                if not xml.strip():
                    job["status"] = "failed"
                    job["error"] = "empty XML"
                    results.append({"id": job["id"], "status": "failed", "error": job["error"]})
                    continue
                with tempfile.NamedTemporaryFile(mode="w", suffix=".mlt", delete=False) as tf:
                    tf.write(xml)
                    xml_path = tf.name
                try:
                    consumer = f"avformat:{job['output_path']}"
                    melt_cmd = ["melt", xml_path, "-consumer", consumer]
                    if job.get("preset"):
                        melt_cmd += [f"preset={job['preset']}"]
                    melt_cmd += ["real_time=-1"]
                    env = os.environ.copy()
                    env.setdefault("QT_QPA_PLATFORM", "offscreen")
                    result = subprocess.run(melt_cmd, capture_output=True, text=True, timeout=300, env=env)
                    # treat QThreadStorage warning as non-fatal if file exists
                    out_exists = os.path.exists(job["output_path"]) and os.path.getsize(job["output_path"]) > 0
                    if result.returncode == 0 or out_exists:
                        # also check if file created despite non-zero due to Qt warning
                        if out_exists:
                            job["status"] = "completed"
                            _render_status["completed"] += 1
                            results.append({"id": job["id"], "status": "completed"})
                        elif result.returncode == 0:
                            job["status"] = "completed"
                            _render_status["completed"] += 1
                            results.append({"id": job["id"], "status": "completed"})
                        else:
                            job["status"] = "failed"
                            job["error"] = result.stderr.strip()[-500:] or f"exit {result.returncode}"
                            results.append({"id": job["id"], "status": "failed", "error": job["error"]})
                    else:
                        job["status"] = "failed"
                        job["error"] = result.stderr.strip()[-500:] or f"melt exit code {result.returncode}"
                        results.append({"id": job["id"], "status": "failed", "error": job["error"]})
                finally:
                    try:
                        os.unlink(xml_path)
                    except OSError:
                        pass
            except FileNotFoundError:
                job["status"] = "failed"
                job["error"] = "melt binary not found"
                results.append({"id": job["id"], "status": "failed"})
                break
            except subprocess.TimeoutExpired:
                job["status"] = "failed"
                job["error"] = "render timeout"
                results.append({"id": job["id"], "status": "failed"})
        _render_status["running"] = False
        _render_status["current"] = None
        return _ok({"results": results, "status": _render_status})
    except RuntimeError as e:
        _render_status["running"] = False
        return _err(str(e))


@server.tool()
def render_queue_stop() -> dict[str, Any]:
    """Stop render queue (marks running as stopped)."""
    err = _require_project()
    if err:
        return err
    if not _render_status.get("running"):
        return _err("Render queue not running")
    _render_status["running"] = False
    _render_status["current"] = None
    return _ok({"stopped": True})


# ── Undo/Redo Granular ───────────────────────────────────────────

@server.tool()
def session_undo_step(steps: int = 1) -> dict[str, Any]:
    """Undo N steps (granular)."""
    if not _session.has_project():
        return _err("No project loaded.")
    if steps < 1:
        return _err("Steps must be >=1")
    try:
        undone = []
        for _ in range(steps):
            try:
                desc = _session.undo()
                undone.append(desc)
            except Exception as e:
                if not undone:
                    return _err(str(e))
                break
        _save()
        return _ok({"undone": undone, "steps": len(undone)})
    except Exception as e:
        return _err(str(e))


@server.tool()
def session_redo_step(steps: int = 1) -> dict[str, Any]:
    """Redo N steps (granular)."""
    if not _session.has_project():
        return _err("No project loaded.")
    if steps < 1:
        return _err("Steps must be >=1")
    try:
        redone = []
        for _ in range(steps):
            try:
                desc = _session.redo()
                redone.append(desc)
            except Exception as e:
                if not redone:
                    return _err(str(e))
                break
        _save()
        return _ok({"redone": redone, "steps": len(redone)})
    except Exception as e:
        return _err(str(e))


# ── Bin / Clip Organization ──────────────────────────────────────

@server.tool()
def bin_create_folder(name: str, parent: str | None = None) -> dict[str, Any]:
    """Create folder in project bin."""
    err = _require_project()
    if err:
        return err
    try:
        proj = _session.get_project()
        if "bin_folders" not in proj:
            proj["bin_folders"] = []
        if any(f["name"] == name and f.get("parent") == parent for f in proj["bin_folders"]):
            return _err(f"Folder already exists: {name}")
        _session.snapshot(f"Create folder {name}")
        folder = {"name": name, "parent": parent, "created": __import__("datetime").datetime.now().isoformat()}
        proj["bin_folders"].append(folder)
        _save()
        return _ok(folder)
    except RuntimeError as e:
        return _err(str(e))


@server.tool()
def bin_move_clip(clip_id: str, folder: str | None = None) -> dict[str, Any]:
    """Move clip to folder (or root if folder None)."""
    err = _require_project()
    if err:
        return err
    try:
        proj = _session.get_project()
        # find actual bin entry (get_clip returns copy)
        target = next((c for c in proj.get("bin", []) if c["id"] == clip_id), None)
        if target is None:
            return _err(f"Clip not found: {clip_id}")
        if folder is not None:
            folders = proj.get("bin_folders", [])
            if not any(f["name"] == folder for f in folders):
                return _err(f"Folder not found: {folder}")
        _session.snapshot(f"Move clip {clip_id} to {folder}")
        target["folder"] = folder
        _save()
        return _ok(dict(target))
    except (ValueError, RuntimeError) as e:
        return _err(str(e))


@server.tool()
def bin_rename(clip_id: str, new_name: str) -> dict[str, Any]:
    """Rename bin clip."""
    err = _require_project()
    if err:
        return err
    try:
        proj = _session.get_project()
        target = next((c for c in proj.get("bin", []) if c["id"] == clip_id), None)
        if target is None:
            return _err(f"Clip not found: {clip_id}")
        _session.snapshot(f"Rename clip {clip_id}")
        target["name"] = new_name
        _save()
        return _ok(dict(target))
    except (ValueError, RuntimeError) as e:
        return _err(str(e))


@server.tool()
def clip_set_color(clip_id: str, color: str) -> dict[str, Any]:
    """Set color label for bin clip (hex or named)."""
    err = _require_project()
    if err:
        return err
    try:
        proj = _session.get_project()
        target = next((c for c in proj.get("bin", []) if c["id"] == clip_id), None)
        if target is None:
            return _err(f"Clip not found: {clip_id}")
        _session.snapshot(f"Set color for {clip_id}")
        target["color"] = color
        _save()
        return _ok(dict(target))
    except (ValueError, RuntimeError) as e:
        return _err(str(e))


@server.tool()
def clip_add_note(clip_id: str, note: str) -> dict[str, Any]:
    """Add / update note for bin clip."""
    err = _require_project()
    if err:
        return err
    try:
        proj = _session.get_project()
        target = next((c for c in proj.get("bin", []) if c["id"] == clip_id), None)
        if target is None:
            return _err(f"Clip not found: {clip_id}")
        _session.snapshot(f"Add note to {clip_id}")
        target["note"] = note
        _save()
        return _ok(dict(target))
    except (ValueError, RuntimeError) as e:
        return _err(str(e))


# ── Entry Point ──────────────────────────────────────────────────


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
