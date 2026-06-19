# Kdenlive MCP Server

A Model Context Protocol (MCP) server wrapping `cli-anything-kdenlive` for LLM-driven video editing workflows via Kdenlive.

## Overview

This FastMCP server enables AI models to perform complex video editing tasks on Kdenlive projects through a unified set of 36 tools organized into 8 functional categories. The server uses the Python API of `cli-anything-kdenlive` directly (not subprocess) to maintain a persistent session state, ensuring modifications are immediately available to subsequent tool calls.

### Key Features

- **Persistent Session State**: Uses CLI's in-memory session API, auto-saves after every mutation
- **Gen 5 XML Export**: Kdenlive-compatible XML output with proper bin references and version metadata
- **Robust Error Handling**: All exceptions caught and returned as structured JSON payloads
- **Auto-Project Tracking**: Globally tracks project path; all tools automatically target the active project
- **36 MCP Tools**: Comprehensive coverage of Kdenlive operations

## Installation

### Prerequisites

```bash
# Python 3.10+
# Ensure uv is installed for dependency management
pip install uv
```

### Install Dependencies

```bash
cd kdenlive-mcp-server
uv sync
```

## Usage

### As an MCP Server

The server runs as a FastMCP server compatible with any LLM platform that supports MCP (e.g., Claude Code, Pi, OpenCode).

### Command Line

```bash
# Run the MCP server
uv run kdenlive-mcp

# Or directly via Python
uv run python3 -m kdenlive_mcp_server.server
```

### Python Integration

```python
from kdenlive_mcp_server.server import (
    project_new, bin_import_clip, timeline_add_clip, export_xml
)

# Create project
result = project_new(output_path="my_project.kdenlive-cli.json", profile="hd1080p30")

# Import media
result = bin_import_clip(clip_path="video.mp4", name="Interview", duration=120.0)

# Add to timeline
result = timeline_add_clip(clip_id="clip0", track=0, position=0.0)

# Export XML
result = export_xml(output_path="output.kdenlive")
```

## Project Structure

```
kdenlive-mcp-server/
├── kdenlive_mcp_server/
│   ├── __init__.py           # Empty package init
│   └── server.py             # FastMCP server with 36 tools (876 lines)
├── main.py                   # Entry point delegating to server module
├── pyproject.toml            # Project configuration and dependencies
├── uv.lock                   # Dependency lock file
└── README.md                 # This file
```

## Tools

### Project (5 tools)

| Tool | Description |
|------|-------------|
| `project_new()` | Create a new Kdenlive project with optional profile override |
| `project_open()` | Load an existing .kdenlive-cli.json project |
| `project_save()` | Persist the current project state to disk |
| `project_get_info()` | Get project metadata (resolution, FPS, track layout, clip counts) |
| `project_list_profiles()` | List all available video output profiles (hd1080p30, 4k60, sd_pal, etc.) |

### Bin (4 tools)

| Tool | Description |
|------|-------------|
| `bin_import_clip()` | Ingest media files (video, audio, image) into the project bin |
| `bin_remove_clip()` | Delete a clip from the bin by ID |
| `bin_list_clips()` | List all assets in the project bin |
| `bin_get_clip_details()` | Fetch detailed properties of a clip (duration, type, source) |

### Timeline (8 tools)

| Tool | Description |
|------|-------------|
| `timeline_add_track()` | Append a video or audio track to the timeline |
| `timeline_remove_track()` | Delete a track and all its clips |
| `timeline_add_clip()` | Place a bin clip on a track at a specific position |
| `timeline_remove_clip()` | Remove a clip from a track |
| `timeline_move_clip()` | Reposition a clip on the same track |
| `timeline_trim_clip()` | Adjust clip in/out crop handles |
| `timeline_split_clip()` | Cut a clip into two pieces at a precise offset |
| `timeline_list()` | List all tracks with clip counts and status |

### Filters (5 tools)

| Tool | Description |
|------|-------------|
| `filter_add()` | Attach a video/audio effect (blur, brightness, frei0r.opacity, volume) |
| `filter_remove()` | Remove an effect from a clip |
| `filter_set_param()` | Update a single filter parameter (radius, opacity, level) |
| `filter_list()` | List all active filters on a clip |
| `filter_list_available()` | Discover all available filters by category |

### Transitions (4 tools)

| Tool | Description |
|------|-------------|
| `transition_add()` | Create blend transitions (dissolve, wipe, slide, composite, affine) |
| `transition_remove()` | Delete a transition by ID |
| `transition_set()` | Update a transition parameter |
| `transition_list()` | List all transitions on the timeline |

### Guides (3 tools)

| Tool | Description |
|------|-------------|
| `guide_add()` | Add timeline markers/chapters |
| `guide_remove()` | Remove a guide by ID |
| `guide_list()` | List all guide markers |

### Export (3 tools)

| Tool | Description |
|------|-------------|
| `export_xml()` | Generate Kdenlive/MLT XML for the project |
| `export_list_presets()` | List available render presets |
| `export_render()` | Render project to video via melt CLI |

### Session (4 tools)

| Tool | Description |
|------|-------------|
| `session_undo()` | Revert the most recent operation (up to 50 history entries) |
| `session_redo()` | Redo the last undone operation |
| `session_status()` | Inspect session state (project loaded, modified flag, history depth) |
| `session_history()` | List all undo/redo history entries |

## Example Workflows

### Create a Simple Video Project

```python
from kdenlive_mcp_server.server import (
    project_new, bin_import_clip, timeline_add_track,
    timeline_add_clip, export_xml, project_save
)

# 1. Create project
result = project_new(
    output_path="intro_video.kdenlive-cli.json",
    profile="hd1080p30",
    name="Introduction"
)

# 2. Import media
result = bin_import_clip(
    clip_path="interview.mp4",
    name="Interview",
    duration=120.0
)

# 3. Add track and place clip
result = timeline_add_track(track_type="video", track_name="V1")
result = timeline_add_clip(
    clip_id="clip0",  # From bin_import_clip response
    track=0,
    position=0.0
)

# 4. Export
result = export_xml(output_path="intro.kdenlive")
```

### Apply Effects to Clips

```python
from kdenlive_mcp_server.server import (
    project_new, bin_import_clip, timeline_add_track,
    timeline_add_clip, filter_add, filter_set_param, filter_list
)

# Setup
result = project_new(output_path="effects_demo.kdenlive-cli.json", profile="hd720p60")
result = bin_import_clip(clip_path="movie.mp4", name="Movie", duration=300.0)
result = timeline_add_track(track_type="video")
result = timeline_add_clip(clip_id="clip0", track=0, position=0.0)

# Add brightness filter
result = filter_add(
    track_id=0,
    clip_index=0,
    filter_type="brightness",
    params=["level=0.8"]
)

# Update brightness
result = filter_set_param(
    track_id=0,
    clip_index=0,
    filter_index=0,
    parameter="level",
    value="1.2"
)

# List filters
result = filter_list(track_id=0, clip_index=0)
```

### Add Chapter Markers

```python
from kdenlive_mcp_server.server import (
    project_new, bin_import_clip, timeline_add_track,
    timeline_add_clip, guide_add, guide_list, project_save
)

# Setup
result = project_new(output_path="documentary.kdenlive-cli.json", profile="4k30")
result = bin_import_clip(clip_path="documentary.mp4", name="Doc", duration=900.0)
result = timeline_add_track(track_type="video")
result = timeline_add_clip(clip_id="clip0", track=0, position=0.0)

# Add chapter markers
result = guide_add(position=60.0, label="Chapter 1: Introduction", guide_type="chapter")
result = guide_add(position=180.0, label="Chapter 2: Main Content", guide_type="chapter")
result = guide_add(position=300.0, label="Chapter 3: Conclusion", guide_type="chapter")

# List guides
result = guide_list()

# Save
result = project_save()
```

## Error Handling

All tools return consistent response formats:

```python
# Success
{
    "success": True,
    "data": {...}
}

# Error
{
    "success": False,
    "error": "Error message describing the failure"
}
```

## Configuration

### pyproject.toml

```toml
[project]
name = "kdenlive-mcp-server"
version = "0.1.0"
description = "MCP server for Kdenlive video editing via cli-anything-kdenlive"
requires-python = ">=3.10"
dependencies = [
    "mcp>=1.28.0",
    "cli-anything-kdenlive>=1.0.0",
]

[project.scripts]
kdenlive-mcp = "kdenlive_mcp_server.server:main"

[tool.uv.sources]
cli-anything-kdenlive = { git = "https://github.com/HKUDS/CLI-Anything.git", subdirectory = "kdenlive/agent-harness" }
```

### uv.lock

Auto-generated by `uv sync`. Contains locked dependency versions.

## Dependencies

- **mcp>=1.28.0**: FastMCP server framework for MCP protocol
- **cli-anything-kdenlive @ git+https://github.com/HKUDS/CLI-Anything.git#subdirectory=kdenlive/agent-harness**:
  - CLI harness for Kdenlive video editing via melt
  - Includes Gen 5 MLT XML format rewrite (PR #216)
  - Provides Python API for project management

## Troubleshooting

### Kdenlive XML Compatibility Issues

If Kdenlive reports "Version of the project file cannot be read" or "Timeline clip without bin reference found":

1. **Cause**: Using PyPI v1.0.0 (Gen 4 format) which lacks proper Kdenlive metadata
2. **Fix**: The package now installs from GitHub HEAD with Gen 5 format that includes:
   - `kdenlive:docproperties.version="1.1"`
   - Chain-based clip structure with `kdenlive:id` linking to main_bin
   - Proper bin reference handling

### Project Not Saving

The server auto-saves to disk after every mutation. If changes aren't persisting:

1. Verify the project path is set via `project_new()` or `project_open()`
2. Check that `session_status()` shows `has_project: true`
3. Ensure the output directory is writable

### FastMCP Server Not Starting

1. Verify MCP version: `uv run python3 -c "import mcp; print(mcp.__version__)"`
2. Check FastMCP: `uv run python3 -c "from mcp.server.fastmcp import FastMCP; print('FastMCP OK')"`
3. Review logs for detailed error messages

## Development

### Testing

Run the test suite:

```bash
# Run all integration tests
uv run python3 test_integration.py

# Test with zero-duration edge case
uv run python3 test_edge_cases.py
```

### Code Style

The project follows PEP 8 style guidelines. Use `uv run ruff check .` to lint.

### Adding New Tools

To add a new MCP tool:

1. Add the tool function to `server.py` decorated with `@server.tool()`
2. Import the corresponding CLI API module if needed
3. Include comprehensive docstrings with Args and Returns sections
4. Implement error handling with try/except
5. Call `_save()` after mutations to persist changes

Example:

```python
@server.tool()
def my_new_tool(param1: str, param2: int) -> dict[str, Any]:
    """Brief description of what the tool does.

    Args:
        param1: Description of param1.
        param2: Description of param2.

    Returns:
        Success response format.
    """
    err = _require_project()
    if err:
        return err

    try:
        # Do something with the project
        result = some_api_function(param1, param2)
        _save()
        return _ok(result)
    except Exception as e:
        return _err(str(e))
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all tests pass: `uv run pytest`
5. Submit a pull request

## References

- [CLI-Anything Kdenlive](https://github.com/HKUDS/CLI-Anything/tree/main/kdenlive/agent-harness)
- [Kdenlive Documentation](https://kdenlive.org/en/doc/)
- [FastMCP Documentation](https://github.com/jlowin/fastmcp)
- [MLT XML Format](https://www.mltframework.org/docs/mltxml/)
- [Model Context Protocol](https://modelcontextprotocol.io/)