"""FastAPI web dashboard for AAT.

Provides REST endpoints for config/scenario management,
WebSocket for real-time event streaming, and serves the SPA UI.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import sys
from pathlib import Path
from typing import Any

from aat.core.config import load_config, save_config
from aat.core.exceptions import AATError, DashboardError
from aat.core.models import ApprovalMode, Config, StepStatus

try:
    from fastapi import (  # type: ignore[import-not-found]
        FastAPI,
        Request,
        WebSocket,
        WebSocketDisconnect,
    )
    from fastapi.responses import (  # type: ignore[import-not-found]
        FileResponse,
        HTMLResponse,
        JSONResponse,
    )
    from fastapi.staticfiles import StaticFiles  # type: ignore[import-not-found]
except ImportError as e:
    msg = "Dashboard requires 'web' extras: pip install aat-devqa[web]"
    raise ImportError(msg) from e

from aat.dashboard.events_ws import ConnectionManager, WebSocketEventHandler
from aat.dashboard.subprocess_manager import ProcessStatus, SubprocessManager

# ---------------------------------------------------------------------------
# Module state
# ---------------------------------------------------------------------------

_manager = ConnectionManager()
_ws_handler = WebSocketEventHandler(_manager)
_subprocess = SubprocessManager()


def _on_server_line(line: str) -> None:
    """Broadcast server subprocess output lines via WebSocket."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(
            _manager.broadcast({"type": "server_log", "line": line}),
        )
    except RuntimeError:
        pass  # no event loop


def _on_server_exit(return_code: int, status: ProcessStatus) -> None:
    """Broadcast server process exit via WebSocket."""
    try:
        loop = asyncio.get_running_loop()
        msg = f"Server process exited (code={return_code})"
        event_type = "info" if return_code == 0 else "warning"
        loop.create_task(
            _manager.broadcast(
                {
                    "type": "server_exit",
                    "return_code": return_code,
                    "status": status.value,
                }
            ),
        )
        loop.create_task(
            _manager.broadcast({"type": event_type, "message": msg}),
        )
    except RuntimeError:
        pass


_server_subprocess = SubprocessManager(
    on_line=_on_server_line,
    on_exit=_on_server_exit,
)

_current_config: Config | None = None
_config_path: Path | None = None
_run_task: asyncio.Task[Any] | None = None
_last_server_port: int | None = None

STATIC_DIR = Path(__file__).parent / "static"

# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(config_path: Path | None = None) -> FastAPI:
    """Create and configure the FastAPI dashboard app."""
    global _current_config, _config_path  # noqa: PLW0603

    _config_path = config_path

    try:
        _current_config = load_config(config_path=config_path)
    except AATError:
        _current_config = Config()

    app = FastAPI(title="AAT Dashboard", version="0.2.0")

    # -- Static files ---------------------------------------------------
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # -- Routes ---------------------------------------------------------
    app.add_api_route("/", _index, methods=["GET"], response_class=HTMLResponse)
    app.add_api_route("/api/config", _get_config, methods=["GET"])
    app.add_api_route("/api/config", _update_config, methods=["PUT"])
    app.add_api_route("/api/scenarios", _list_scenarios, methods=["GET"])
    app.add_api_route("/api/scenarios/upload", _upload_scenario, methods=["POST"])
    app.add_api_route("/api/scenarios/generate", _generate_scenarios, methods=["POST"])
    app.add_api_route("/api/run", _start_run, methods=["POST"])
    app.add_api_route("/api/loop", _start_loop, methods=["POST"])
    app.add_api_route("/api/stop", _stop_run, methods=["POST"])
    app.add_api_route("/api/status", _get_status, methods=["GET"])
    app.add_api_route("/api/logs", _get_logs, methods=["GET"])
    app.add_api_route(
        "/api/screenshots/{filename:path}",
        _get_screenshot,
        methods=["GET"],
        response_model=None,
    )

    # Server control
    app.add_api_route("/api/server/start", _start_server, methods=["POST"])
    app.add_api_route("/api/server/stop", _stop_server, methods=["POST"])
    app.add_api_route("/api/server/status", _get_server_status, methods=["GET"])
    app.add_api_route("/api/server/logs", _get_server_logs, methods=["GET"])

    # Document management
    app.add_api_route("/api/documents/upload", _upload_documents, methods=["POST"])
    app.add_api_route("/api/documents", _list_documents, methods=["GET"])

    # Preflight check
    app.add_api_route("/api/preflight", _preflight, methods=["POST"])

    # Folder browser
    app.add_api_route("/api/browse", _browse_directory, methods=["GET"])

    app.add_api_websocket_route("/ws", _websocket_endpoint)

    return app


# ---------------------------------------------------------------------------
# HTML index
# ---------------------------------------------------------------------------


async def _index() -> HTMLResponse:
    """Serve the SPA index.html."""
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise DashboardError("index.html not found")
    content = index_path.read_text(encoding="utf-8")
    return HTMLResponse(content=content)


# ---------------------------------------------------------------------------
# REST: Config
# ---------------------------------------------------------------------------


async def _get_config() -> JSONResponse:
    """Return current config as JSON."""
    if _current_config is None:
        return JSONResponse(content={}, status_code=200)
    data = _current_config.model_dump(mode="json")
    # Mask API key
    if data.get("ai", {}).get("api_key"):
        key = data["ai"]["api_key"]
        data["ai"]["api_key"] = key[:8] + "..." if len(key) > 8 else "***"
    return JSONResponse(content=data)


async def _update_config(request: Request) -> JSONResponse:
    """Update config from JSON body."""
    global _current_config  # noqa: PLW0603

    try:
        body = await request.json()
    except Exception as exc:
        return JSONResponse(
            content={"error": f"Invalid JSON: {exc}"},
            status_code=400,
        )

    try:
        # Merge with existing config
        existing = _current_config.model_dump(mode="json") if _current_config else {}
        existing.update(body)
        _current_config = Config(**existing)

        # Save to file
        save_path = _config_path or Path(".aat/config.yaml")
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_config(_current_config, save_path)

        await _manager.broadcast({"type": "info", "message": "Config updated"})
        return JSONResponse(content={"status": "ok"})
    except Exception as exc:
        return JSONResponse(
            content={"error": str(exc)},
            status_code=400,
        )


# ---------------------------------------------------------------------------
# REST: Scenarios
# ---------------------------------------------------------------------------


def _get_scenario_guidance(error_str: str) -> str:
    """Parse Pydantic validation errors and return user-friendly Korean guidance."""
    hints: list[str] = []

    lower = error_str.lower()

    if "step" in lower and ("field required" in lower or "missing" in lower):
        hints.append("각 스텝에 'step' 번호(정수)가 필요합니다 (예: step: 1)")

    if "'click'" in lower or "'type'" in lower or "action" in lower:
        hints.append(
            "action은 다음 중 하나여야 합니다: "
            "navigate, find_and_click, find_and_type, scroll, wait, "
            "screenshot, assert, hover, press_key, select_option, drag_and_drop"
        )

    if "target" in lower and ("role" in lower or "url" in lower):
        hints.append("target에는 'text' 필드만 사용하세요 (role, url은 지원하지 않음)")

    if "assert_type" in lower or "expected" in lower:
        hints.append(
            "assert 스텝에는 assert_type과 expected 리스트가 필요합니다\n"
            "  예: assert_type: text_visible\n"
            "      expected:\n"
            "        - type: text_visible\n"
            "          value: \"확인할 텍스트\""
        )

    if "variables" in lower:
        hints.append(
            "시나리오 파일에 'variables' 섹션은 지원하지 않습니다. "
            "URL은 설정의 {{url}} 변수를 사용하세요"
        )

    if not hints:
        hints.append("시나리오 YAML 파일의 형식이 올바르지 않습니다")

    return (
        "시나리오 형식 오류가 있습니다. 아래 사항을 확인해주세요:\n\n"
        + "\n".join(f"• {h}" for h in hints)
    )


async def _list_scenarios(request: Request) -> JSONResponse:
    """List available scenarios.

    Query params:
        path: Custom scenario directory path (optional).
    """
    if _current_config is None:
        return JSONResponse(content={"scenarios": []})

    custom_path = request.query_params.get("path", "")
    base_dir = custom_path if custom_path else _current_config.scenarios_dir
    scenarios_dir = _resolve_scenario_path(base_dir)
    if not scenarios_dir.exists():
        return JSONResponse(content={"scenarios": []})

    try:
        from aat.core.scenario_loader import load_scenarios

        variables = _build_variables()
        scenarios = load_scenarios(scenarios_dir, variables=variables)
        result = []
        for sc in scenarios:
            result.append(
                {
                    "id": sc.id,
                    "name": sc.name,
                    "description": sc.description,
                    "tags": sc.tags,
                    "steps_count": len(sc.steps),
                }
            )
        return JSONResponse(content={"scenarios": result, "path": str(scenarios_dir)})
    except AATError as exc:
        error_str = str(exc)
        guidance = _get_scenario_guidance(error_str)
        return JSONResponse(content={
            "scenarios": [],
            "error": error_str,
            "guidance": guidance,
        })


async def _upload_scenario(request: Request) -> JSONResponse:
    """Upload a YAML scenario file."""
    if _current_config is None:
        return JSONResponse(
            content={"error": "No config loaded"},
            status_code=400,
        )

    scenarios_dir = _resolve_scenario_path(_current_config.scenarios_dir)
    scenarios_dir.mkdir(parents=True, exist_ok=True)

    try:
        form = await request.form()
    except Exception:  # noqa: BLE001
        return JSONResponse(
            content={"error": "No file provided"},
            status_code=400,
        )

    file = form.get("file")
    if not file or not hasattr(file, "read"):
        return JSONResponse(
            content={"error": "No file provided"},
            status_code=400,
        )

    filename = getattr(file, "filename", None)
    if not filename or not isinstance(filename, str):
        return JSONResponse(
            content={"error": "Invalid filename"},
            status_code=400,
        )

    # Only allow .yaml / .yml
    safe_name = Path(filename).name
    suffix = Path(safe_name).suffix.lower()
    if suffix not in (".yaml", ".yml"):
        return JSONResponse(
            content={"error": f"Only .yaml/.yml files allowed, got '{suffix}'"},
            status_code=400,
        )

    dest = scenarios_dir / safe_name
    content = await file.read()
    dest.write_bytes(content)

    await _manager.broadcast({"type": "info", "message": f"Scenario uploaded: {safe_name}"})

    # Return updated scenario list
    try:
        from aat.core.scenario_loader import load_scenarios

        variables = _build_variables()
        scenarios = load_scenarios(scenarios_dir, variables=variables)
        result = [
            {
                "id": sc.id,
                "name": sc.name,
                "description": sc.description,
                "tags": sc.tags,
                "steps_count": len(sc.steps),
            }
            for sc in scenarios
        ]
        return JSONResponse(content={"status": "ok", "uploaded": safe_name, "scenarios": result})
    except AATError:
        return JSONResponse(content={"status": "ok", "uploaded": safe_name, "scenarios": []})


async def _generate_scenarios(request: Request) -> JSONResponse:
    """Generate scenarios from document text using AI adapter."""
    if _current_config is None:
        return JSONResponse(content={"error": "설정이 없습니다"}, status_code=400)

    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return JSONResponse(content={"error": "잘못된 요청"}, status_code=400)

    document_text = body.get("document_text", "")
    if not document_text.strip():
        return JSONResponse(content={"error": "문서 내용이 비어있습니다"}, status_code=400)

    # Create AI adapter
    from aat.adapters import ADAPTER_REGISTRY

    provider = _current_config.ai.provider
    adapter_cls = ADAPTER_REGISTRY.get(provider)
    if adapter_cls is None:
        return JSONResponse(
            content={"error": f"AI 어댑터 없음: {provider}"},
            status_code=400,
        )

    # Validate API key for providers that require one
    if provider != "ollama" and not _current_config.ai.api_key:
        return JSONResponse(
            content={
                "error": (
                    f"API 키가 설정되지 않았습니다. "
                    f"설정 > API 키에 {provider} API 키를 입력하고 "
                    f"'설정 저장'을 클릭하세요."
                ),
            },
            status_code=400,
        )

    try:
        adapter = adapter_cls(_current_config.ai)
        scenarios = await adapter.generate_scenarios(document_text)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(
            content={"error": f"시나리오 생성 실패: {e}"},
            status_code=500,
        )

    if not scenarios:
        return JSONResponse(content={"error": "생성된 시나리오가 없습니다"}, status_code=400)

    # Save to temp directory (not mixed with project files)
    import tempfile

    import yaml

    temp_dir = Path(tempfile.mkdtemp(prefix="aat_scenarios_"))

    saved_files: list[str] = []
    result_scenarios: list[dict[str, Any]] = []
    for sc in scenarios:
        safe_name = sc.name.replace(" ", "_").lower()
        safe_name = re.sub(r"[^a-z0-9_]", "", safe_name)
        filename = f"{sc.id}_{safe_name}.yaml"
        filepath = temp_dir / filename

        data = sc.model_dump(mode="json", exclude_none=True)
        for step in data.get("steps", []):
            for key in list(step.keys()):
                if step[key] is None:
                    del step[key]
            target = step.get("target")
            if target:
                step["target"] = {k: v for k, v in target.items() if v is not None}

        with open(filepath, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

        saved_files.append(filename)
        result_scenarios.append({
            "id": sc.id,
            "name": sc.name,
            "description": sc.description,
            "tags": sc.tags,
            "steps_count": len(sc.steps),
        })

    await _manager.broadcast({
        "type": "success",
        "message": f"시나리오 {len(scenarios)}개 생성 완료",
    })

    return JSONResponse(content={
        "success": True,
        "count": len(scenarios),
        "files": saved_files,
        "scenarios": result_scenarios,
        "scenarios_path": str(temp_dir),
    })


# ---------------------------------------------------------------------------
# REST: Run / Loop / Stop
# ---------------------------------------------------------------------------


async def _start_run(request: Request) -> JSONResponse:
    """Start a single test run."""
    global _run_task  # noqa: PLW0603

    if _run_task and not _run_task.done():
        return JSONResponse(
            content={"error": "A test is already running"},
            status_code=409,
        )

    try:
        body = await request.json()
    except Exception:
        body = {}

    scenario_path = body.get("scenario_path", "")
    if not scenario_path and _current_config:
        scenario_path = _current_config.scenarios_dir

    if not scenario_path:
        return JSONResponse(
            content={"error": "No scenario path specified"},
            status_code=400,
        )

    scenario_ids: list[str] = body.get("scenario_ids", [])

    _run_task = asyncio.create_task(
        _execute_run(scenario_path, scenario_ids),
    )
    return JSONResponse(content={"status": "started"})


async def _start_loop(request: Request) -> JSONResponse:
    """Start a DevQA Loop."""
    global _run_task  # noqa: PLW0603

    if _run_task and not _run_task.done():
        return JSONResponse(
            content={"error": "A test is already running"},
            status_code=409,
        )

    try:
        body = await request.json()
    except Exception:
        body = {}

    scenario_path = body.get("scenario_path", "")
    if not scenario_path and _current_config:
        scenario_path = _current_config.scenarios_dir

    if not scenario_path:
        return JSONResponse(
            content={"error": "No scenario path specified"},
            status_code=400,
        )

    approval_mode = body.get("approval_mode", "manual")
    max_loops = body.get("max_loops")
    scenario_ids: list[str] = body.get("scenario_ids", [])

    _run_task = asyncio.create_task(
        _execute_loop(scenario_path, approval_mode, max_loops, scenario_ids),
    )
    return JSONResponse(content={"status": "started"})


async def _stop_run() -> JSONResponse:
    """Stop the current test run."""
    if _run_task and not _run_task.done():
        _run_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _run_task
    await _subprocess.stop()
    await _manager.broadcast({"type": "info", "message": "Test stopped"})
    return JSONResponse(content={"status": "stopped"})


async def _get_status() -> JSONResponse:
    """Get current execution status."""
    running = _run_task is not None and not _run_task.done()
    return JSONResponse(
        content={
            "running": running,
            "subprocess": _subprocess.status.value,
            "ws_clients": _manager.count,
            "server_running": _server_subprocess.is_running,
        }
    )


async def _get_logs() -> JSONResponse:
    """Get subprocess log lines."""
    return JSONResponse(content={"logs": _subprocess.log_lines})


# ---------------------------------------------------------------------------
# REST: Screenshots
# ---------------------------------------------------------------------------


async def _get_screenshot(filename: str) -> FileResponse | JSONResponse:
    """Serve a screenshot file."""
    if _current_config is None:
        return JSONResponse(
            content={"error": "No config"},
            status_code=404,
        )

    screenshot_dir = Path(_current_config.data_dir) / "screenshots"
    filepath = screenshot_dir / filename

    if not filepath.exists() or not filepath.is_file():
        return JSONResponse(
            content={"error": "Screenshot not found"},
            status_code=404,
        )

    # Security: prevent path traversal
    try:
        filepath.resolve().relative_to(screenshot_dir.resolve())
    except ValueError:
        return JSONResponse(
            content={"error": "Invalid path"},
            status_code=403,
        )

    return FileResponse(str(filepath))


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------


async def _websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time event streaming."""
    await _manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "")

            if msg_type == "prompt_response":
                _ws_handler.resolve_prompt(data.get("response", ""))
            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})
            elif msg_type == "server_command":
                # Allow starting server via WS (optional)
                pass
    except WebSocketDisconnect:
        _manager.disconnect(websocket)
    except Exception:  # noqa: BLE001
        _manager.disconnect(websocket)


# ---------------------------------------------------------------------------
# REST: Server control
# ---------------------------------------------------------------------------


def _extract_port(command: str) -> int | None:
    """Extract port number from a command string using regex heuristics."""
    # Match common patterns: --port 3000, -p 8080, :8000, PORT=5000
    patterns = [
        r"(?:--port|--Port|-p|-P)\s+(\d{2,5})",
        r":(\d{4,5})\b",
        r"PORT[=\s]+(\d{2,5})",
    ]
    for pattern in patterns:
        m = re.search(pattern, command)
        if m:
            port = int(m.group(1))
            if 1024 <= port <= 65535:  # noqa: PLR2004
                return port
    return None


async def _start_server(request: Request) -> JSONResponse:
    """Start the target server subprocess."""
    if _server_subprocess.is_running:
        return JSONResponse(
            content={"error": "Server is already running"},
            status_code=409,
        )

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            content={"error": "Invalid JSON body"},
            status_code=400,
        )

    command = body.get("command", "")
    cwd = body.get("cwd", "")

    # Replace "python3" with the current venv interpreter so that
    # subprocess inherits installed packages (flask, django, etc.)
    if command and "python3" in command:
        command = command.replace("python3", sys.executable)

    if not command:
        return JSONResponse(
            content={"error": "No command specified"},
            status_code=400,
        )

    cwd_path = Path(cwd) if cwd else None

    try:
        await _server_subprocess.start_shell(command, cwd=cwd_path)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            content={"error": f"Failed to start server: {exc}"},
            status_code=500,
        )

    # Extract port and suggest URL
    global _last_server_port  # noqa: PLW0603
    port = _extract_port(command)
    _last_server_port = port
    suggested_url = f"http://localhost:{port}" if port else None

    await _manager.broadcast(
        {
            "type": "info",
            "message": f"Server started: {command}",
        }
    )

    return JSONResponse(
        content={
            "status": "started",
            "pid": _server_subprocess.pid,
            "suggested_url": suggested_url,
        }
    )


async def _stop_server() -> JSONResponse:
    """Stop the target server subprocess."""
    if not _server_subprocess.is_running:
        return JSONResponse(
            content={"status": "not_running"},
        )

    await _server_subprocess.stop()
    await _manager.broadcast(
        {
            "type": "info",
            "message": "Server stopped",
        }
    )
    return JSONResponse(content={"status": "stopped"})


async def _get_server_status() -> JSONResponse:
    """Get server subprocess status."""
    return JSONResponse(
        content={
            "running": _server_subprocess.is_running,
            "status": _server_subprocess.status.value,
            "pid": _server_subprocess.pid,
        }
    )


async def _get_server_logs() -> JSONResponse:
    """Get server subprocess log lines."""
    return JSONResponse(content={"lines": _server_subprocess.log_lines})


# ---------------------------------------------------------------------------
# REST: Documents
# ---------------------------------------------------------------------------


def _get_docs_dir() -> Path:
    """Get the documents directory path."""
    if _current_config:
        return Path(_current_config.data_dir) / "docs"
    return Path(".aat") / "docs"


async def _upload_documents(request: Request) -> JSONResponse:
    """Upload documents via multipart/form-data."""
    docs_dir = _get_docs_dir()
    docs_dir.mkdir(parents=True, exist_ok=True)

    try:
        form = await request.form()
    except Exception:  # noqa: BLE001
        return JSONResponse(
            content={"error": "No files provided"},
            status_code=400,
        )

    files = form.getlist("files")

    if not files:
        return JSONResponse(
            content={"error": "No files provided"},
            status_code=400,
        )

    saved: list[str] = []
    for file in files:
        if not hasattr(file, "read"):
            continue
        filename = getattr(file, "filename", None)
        if not filename or not isinstance(filename, str):
            continue
        # Security: prevent path traversal
        safe_name = Path(filename).name
        if not safe_name:
            continue
        dest = docs_dir / safe_name
        content = await file.read()
        dest.write_bytes(content)
        saved.append(safe_name)

    if not saved:
        return JSONResponse(
            content={"error": "No valid files uploaded"},
            status_code=400,
        )

    # Read text content of uploaded files for AI processing
    import contextlib

    contents: dict[str, str] = {}
    for name in saved:
        filepath = docs_dir / name
        with contextlib.suppress(UnicodeDecodeError, OSError):
            contents[name] = filepath.read_text(encoding="utf-8")

    await _manager.broadcast(
        {
            "type": "info",
            "message": f"Uploaded {len(saved)} document(s): {', '.join(saved)}",
        }
    )

    return JSONResponse(
        content={
            "status": "ok",
            "uploaded": saved,
            "count": len(saved),
            "contents": contents,
        }
    )


async def _list_documents() -> JSONResponse:
    """List uploaded documents."""
    docs_dir = _get_docs_dir()
    if not docs_dir.exists():
        return JSONResponse(content={"documents": []})

    allowed_ext = {".md", ".txt", ".pdf", ".html", ".rst", ".yaml", ".yml", ".json"}
    documents: list[dict[str, Any]] = []

    for f in sorted(docs_dir.iterdir()):
        if f.is_file() and f.suffix.lower() in allowed_ext:
            documents.append(
                {
                    "name": f.name,
                    "size": f.stat().st_size,
                    "ext": f.suffix.lower(),
                }
            )

    return JSONResponse(content={"documents": documents})


# ---------------------------------------------------------------------------
# REST: Folder browser
# ---------------------------------------------------------------------------


async def _browse_directory(request: Request) -> JSONResponse:
    """Browse directories for the folder picker modal.

    Query params:
        path: Directory path to list (default: user home).

    Returns:
        {dirs: ["subdir1", ...], parent: "/parent/path", current: "/current/path"}
    """
    raw_path = request.query_params.get("path", "")
    target = Path(raw_path).expanduser() if raw_path else Path.home()

    if not target.is_absolute():
        target = Path.home() / target
    target = target.resolve()

    if not target.exists() or not target.is_dir():
        return JSONResponse(
            content={"dirs": [], "parent": str(target.parent), "current": str(target)},
        )

    dirs: list[str] = []
    try:
        for entry in sorted(target.iterdir()):
            if entry.name.startswith("."):
                continue  # skip hidden dirs
            if entry.is_dir():
                dirs.append(entry.name)
    except PermissionError:
        pass

    return JSONResponse(
        content={
            "dirs": dirs,
            "parent": str(target.parent),
            "current": str(target),
        }
    )


# ---------------------------------------------------------------------------
# Preflight check
# ---------------------------------------------------------------------------


async def _preflight(request: Request) -> JSONResponse:
    """Run pre-flight checks before test execution.

    Body params:
        mode: "run" | "loop" (default: "run")

    Returns check results with pass/warn/fail status and guidance messages.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    mode = body.get("mode", "run")
    checks: list[dict[str, Any]] = []

    # 1. server_running — warn only
    checks.append(
        {
            "id": "server_running",
            "status": "pass" if _server_subprocess.is_running else "warn",
            "message": "서버 실행 중"
            if _server_subprocess.is_running
            else "서버가 실행되지 않았습니다",
            "guidance": ""
            if _server_subprocess.is_running
            else "Step 1에서 서버를 시작하세요. 외부 서버를 사용하는 경우 무시해도 됩니다.",
            "blocking": False,
        }
    )

    # 2. url_configured — blocking
    url = _current_config.url if _current_config else ""
    url_ok = bool(url and url.strip())
    checks.append(
        {
            "id": "url_configured",
            "status": "pass" if url_ok else "fail",
            "message": f"URL 설정됨: {url}" if url_ok else "테스트 대상 URL이 설정되지 않았습니다",
            "guidance": ""
            if url_ok
            else "설정 > 대상 URL에 테스트할 주소를 입력하고 '설정 저장'을 클릭하세요.",
            "blocking": True,
        }
    )

    # 3. url_reachable — warn only (skip if url not configured)
    if url_ok:
        try:
            from aat.core.connection import test_url

            reachable, msg = await test_url(url)
            checks.append(
                {
                    "id": "url_reachable",
                    "status": "pass" if reachable else "warn",
                    "message": msg,
                    "guidance": (
                        ""
                        if reachable
                        else "URL에 접속할 수 없습니다. "
                        "서버가 실행 중인지, URL이 정확한지 확인하세요."
                    ),
                    "blocking": False,
                }
            )
        except Exception as exc:
            checks.append(
                {
                    "id": "url_reachable",
                    "status": "warn",
                    "message": f"URL 접속 확인 실패: {exc}",
                    "guidance": "URL 접속 확인 중 오류가 발생했습니다. 서버 상태를 확인하세요.",
                    "blocking": False,
                }
            )
    else:
        checks.append(
            {
                "id": "url_reachable",
                "status": "skip",
                "message": "URL 미설정으로 접속 확인 건너뜀",
                "guidance": "",
                "blocking": False,
            }
        )

    # 4. port_mismatch — warn only
    if url_ok and _last_server_port:
        import urllib.parse

        try:
            parsed = urllib.parse.urlparse(url)
            url_port = parsed.port or (443 if parsed.scheme == "https" else 80)
            if url_port != _last_server_port:
                checks.append(
                    {
                        "id": "port_mismatch",
                        "status": "warn",
                        "message": f"포트 불일치: 서버={_last_server_port}, URL={url_port}",
                        "guidance": (
                            f"서버는 포트 {_last_server_port}에서 실행 중이지만, "
                            f"URL은 포트 {url_port}을 사용합니다. "
                            f"URL을 http://localhost:{_last_server_port} 으로 변경하세요."
                        ),
                        "blocking": False,
                    }
                )
            else:
                checks.append(
                    {
                        "id": "port_mismatch",
                        "status": "pass",
                        "message": f"포트 일치: {url_port}",
                        "guidance": "",
                        "blocking": False,
                    }
                )
        except Exception:
            checks.append(
                {
                    "id": "port_mismatch",
                    "status": "skip",
                    "message": "포트 비교 불가",
                    "guidance": "",
                    "blocking": False,
                }
            )
    else:
        checks.append(
            {
                "id": "port_mismatch",
                "status": "skip",
                "message": "포트 비교 건너뜀",
                "guidance": "",
                "blocking": False,
            }
        )

    # 5. scenarios_loaded — blocking
    try:
        from aat.core.scenario_loader import load_scenarios

        sc_path = _current_config.scenarios_dir if _current_config else "scenarios/"
        resolved = _resolve_scenario_path(sc_path)
        variables = _build_variables()
        scenarios = load_scenarios(resolved, variables=variables)
        checks.append(
            {
                "id": "scenarios_loaded",
                "status": "pass" if scenarios else "fail",
                "message": f"시나리오 {len(scenarios)}개 로드됨"
                if scenarios
                else "시나리오를 찾을 수 없습니다",
                "guidance": "" if scenarios else "Step 2에서 시나리오를 불러오거나 업로드하세요.",
                "blocking": True,
            }
        )
    except Exception as exc:
        checks.append(
            {
                "id": "scenarios_loaded",
                "status": "fail",
                "message": f"시나리오 로드 실패: {exc}",
                "guidance": "시나리오 경로와 YAML 형식을 확인하세요.",
                "blocking": True,
            }
        )

    # 6 & 7. AI checks — blocking only for loop mode
    is_loop = mode == "loop"
    if is_loop:
        provider = _current_config.ai.provider if _current_config else ""
        api_key = _current_config.ai.api_key if _current_config else ""

        # ai_provider
        from aat.adapters import ADAPTER_REGISTRY

        if provider in ADAPTER_REGISTRY:
            checks.append(
                {
                    "id": "ai_provider",
                    "status": "pass",
                    "message": f"AI 제공자: {provider}",
                    "guidance": "",
                    "blocking": True,
                }
            )
        else:
            checks.append(
                {
                    "id": "ai_provider",
                    "status": "fail",
                    "message": f"알 수 없는 AI 제공자: {provider}",
                    "guidance": (
                        "설정에서 AI 제공자를 선택하세요. "
                        f"지원: {', '.join(ADAPTER_REGISTRY.keys())}"
                    ),
                    "blocking": True,
                }
            )

        # ai_api_key
        if provider == "ollama":
            checks.append(
                {
                    "id": "ai_api_key",
                    "status": "skip",
                    "message": "Ollama는 API 키 불필요",
                    "guidance": "",
                    "blocking": False,
                }
            )
        elif api_key:
            checks.append(
                {
                    "id": "ai_api_key",
                    "status": "pass",
                    "message": "API 키 설정됨",
                    "guidance": "",
                    "blocking": True,
                }
            )
        else:
            checks.append(
                {
                    "id": "ai_api_key",
                    "status": "fail",
                    "message": "API 키가 설정되지 않았습니다",
                    "guidance": (
                        f"설정 > API 키에 {provider} API 키를 입력하고 "
                        "'설정 저장'을 클릭하세요."
                    ),
                    "blocking": True,
                }
            )
    else:
        checks.append(
            {
                "id": "ai_provider",
                "status": "skip",
                "message": "단일 실행 모드 — AI 검사 건너뜀",
                "guidance": "",
                "blocking": False,
            }
        )
        checks.append(
            {
                "id": "ai_api_key",
                "status": "skip",
                "message": "단일 실행 모드 — AI 검사 건너뜀",
                "guidance": "",
                "blocking": False,
            }
        )

    has_blocking_fail = any(c["status"] == "fail" and c["blocking"] for c in checks)
    return JSONResponse(content={"ok": not has_blocking_fail, "checks": checks})


# ---------------------------------------------------------------------------
# Smart error guidance
# ---------------------------------------------------------------------------

_ERROR_GUIDANCE: list[tuple[str, str]] = [
    (
        "ERR_CONNECTION_REFUSED",
        "서버에 연결할 수 없습니다. Step 1에서 서버를 시작했는지 확인하세요.",
    ),
    ("ERR_CONNECTION_RESET", "서버 연결이 끊어졌습니다. 서버가 정상 실행 중인지 확인하세요."),
    ("ERR_NAME_NOT_RESOLVED", "도메인을 찾을 수 없습니다. URL이 정확한지 확인하세요."),
    (
        "404",
        "페이지를 찾을 수 없습니다 (404). 서버 유형이 맞는지, URL 경로가 정확한지 확인하세요.",
    ),
    ("403", "접근이 거부되었습니다 (403). 인증 설정을 확인하세요."),
    ("500", "서버 내부 오류 (500). 서버 로그를 확인하세요."),
    ("Timeout", "연결 시간 초과. 서버 상태와 네트워크를 확인하세요."),
    ("timed out", "연결 시간 초과. 서버 상태와 네트워크를 확인하세요."),
    ("api_key", "API 키를 확인하세요. 설정 > API 키에서 올바른 키를 입력했는지 확인하세요."),
    ("API key", "API 키를 확인하세요. 설정 > API 키에서 올바른 키를 입력했는지 확인하세요."),
    ("authentication", "인증 오류. API 키가 올바른지 확인하세요."),
    ("Ollama", "Ollama가 실행 중인지 확인하세요 (ollama serve)."),
    ("ollama", "Ollama가 실행 중인지 확인하세요 (ollama serve)."),
]

# AAT exception type → guidance
_EXCEPTION_GUIDANCE: dict[str, str] = {
    "EngineError": (
        "브라우저 엔진 오류. Playwright가 설치되어 있는지 확인하세요 (playwright install)."
    ),
    "AdapterError": "AI 어댑터 오류. API 키와 모델 설정을 확인하세요.",
    "ScenarioError": "시나리오 오류. YAML 형식과 필수 필드를 확인하세요.",
    "MatchError": "이미지 매칭 오류. 참조 이미지 경로와 화면 상태를 확인하세요.",
    "ConfigError": "설정 오류. 설정 파일의 형식과 필수 값을 확인하세요.",
    "StepExecutionError": "스텝 실행 오류. 해당 스텝의 액션과 대상 요소를 확인하세요.",
    "LoopError": "DevQA 루프 오류. AI 설정과 소스 코드 경로를 확인하세요.",
    "GitOpsError": "Git 작업 오류. Git 저장소 상태와 권한을 확인하세요.",
}


def _get_error_guidance(exc: Exception) -> str:
    """Match an exception against known error patterns and return guidance."""
    error_str = str(exc)

    # Check AAT exception types first
    exc_type = type(exc).__name__
    if exc_type in _EXCEPTION_GUIDANCE:
        guidance = _EXCEPTION_GUIDANCE[exc_type]
        # Also check for more specific pattern match
        for pattern, specific_guidance in _ERROR_GUIDANCE:
            if pattern.lower() in error_str.lower():
                return specific_guidance
        return guidance

    # Check error string patterns
    for pattern, guidance in _ERROR_GUIDANCE:
        if pattern.lower() in error_str.lower():
            return guidance

    return ""


# ---------------------------------------------------------------------------
# Execution helpers
# ---------------------------------------------------------------------------


def _resolve_scenario_path(scenario_path: str) -> Path:
    """Resolve scenario path relative to config file directory."""
    path = Path(scenario_path)
    if path.is_absolute():
        return path
    # Resolve relative to config file's parent directory
    if _config_path and _config_path.parent.exists():
        resolved = _config_path.parent / path
        if resolved.exists():
            return resolved
    return path


def _build_variables() -> dict[str, str]:
    """Build template variables from current config."""
    variables: dict[str, str] = {}
    if _current_config:
        if _current_config.url:
            variables["url"] = _current_config.url.rstrip("/")
        variables["project_name"] = _current_config.project_name
    return variables


async def _execute_run(
    scenario_path: str,
    scenario_ids: list[str] | None = None,
) -> None:
    """Execute a test run with WebSocket event broadcasting."""
    assert _current_config is not None

    try:
        from aat.core.scenario_loader import load_scenarios
        from aat.engine import ENGINE_REGISTRY
        from aat.engine.comparator import Comparator
        from aat.engine.executor import StepExecutor
        from aat.engine.humanizer import Humanizer
        from aat.engine.waiter import Waiter
        from aat.matchers import MATCHER_REGISTRY
        from aat.matchers.hybrid import HybridMatcher

        await _manager.broadcast({"type": "run_start"})
        _ws_handler.info("Loading scenarios...")

        path = _resolve_scenario_path(scenario_path)
        variables = _build_variables()
        scenarios = load_scenarios(path, variables=variables)

        if scenario_ids:
            id_set = set(scenario_ids)
            scenarios = [s for s in scenarios if s.id in id_set]

        _ws_handler.info(f"Loaded {len(scenarios)} scenario(s)")

        # Assemble engine
        engine_cls = ENGINE_REGISTRY.get(_current_config.engine.type)
        if engine_cls is None:
            _ws_handler.error(f"Unknown engine: {_current_config.engine.type}")
            return
        engine = engine_cls(_current_config.engine)

        # Assemble matchers
        matchers = [
            MATCHER_REGISTRY[m.value](_current_config.matching)  # type: ignore[call-arg]
            for m in _current_config.matching.chain_order
            if m.value in MATCHER_REGISTRY
        ]
        hybrid = HybridMatcher(matchers, _current_config.matching)

        # Assemble executor
        humanizer = Humanizer(_current_config.humanizer)
        waiter = Waiter()
        comparator = Comparator()
        screenshot_dir = Path(_current_config.data_dir) / "screenshots"
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        executor = StepExecutor(
            engine,
            hybrid,
            humanizer,
            waiter,
            comparator,
            screenshot_dir=screenshot_dir,
        )

        try:
            await engine.start()
            _ws_handler.info("Engine started")

            total_steps = sum(len(sc.steps) for sc in scenarios)
            step_counter = 0

            for sc in scenarios:
                _ws_handler.section(f"Scenario: {sc.id} — {sc.name}")

                for step_config in sc.steps:
                    step_counter += 1
                    _ws_handler.step_start(
                        step_counter,
                        total_steps,
                        step_config.description,
                    )
                    _ws_handler.progress("Testing", step_counter, total_steps)

                    step_result = await executor.execute_step(step_config)

                    passed = step_result.status == StepStatus.PASSED
                    _ws_handler.step_result(
                        step_counter,
                        passed,
                        step_config.description,
                        error=step_result.error_message,
                    )

                    # Send screenshot if available
                    if step_result.screenshot_after:
                        try:
                            ss_path = Path(step_result.screenshot_after)
                            if ss_path.exists():
                                img_data = ss_path.read_bytes()
                                await _ws_handler.send_screenshot(img_data)
                        except Exception:  # noqa: BLE001
                            pass

                    # Also take a live screenshot after each step
                    try:
                        screenshot_bytes = await engine.screenshot()
                        if screenshot_bytes:
                            await _ws_handler.send_screenshot(screenshot_bytes)
                    except Exception:  # noqa: BLE001
                        pass

            # Summary
            _ws_handler.success(f"Test run complete: {step_counter} steps executed")
            await _manager.broadcast({"type": "run_complete"})

        finally:
            await engine.stop()
            _ws_handler.info("Engine stopped")

    except asyncio.CancelledError:
        _ws_handler.warning("Test run cancelled")
        await _manager.broadcast({"type": "run_cancelled"})
    except Exception as exc:  # noqa: BLE001
        guidance = _get_error_guidance(exc)
        error_text = str(exc) or f"{type(exc).__name__}: (상세 메시지 없음)"
        _ws_handler.error(f"Test run failed: {error_text}")
        msg: dict[str, Any] = {"type": "run_error", "error": error_text}
        if guidance:
            msg["guidance"] = guidance
        await _manager.broadcast(msg)


async def _execute_loop(
    scenario_path: str,
    approval_mode_str: str,
    max_loops: int | None,
    scenario_ids: list[str] | None = None,
) -> None:
    """Execute a DevQA Loop with WebSocket event broadcasting."""
    assert _current_config is not None

    try:
        from aat.adapters import ADAPTER_REGISTRY
        from aat.core.git_ops import GitOps
        from aat.core.loop import DevQALoop
        from aat.core.scenario_loader import load_scenarios
        from aat.engine import ENGINE_REGISTRY
        from aat.engine.comparator import Comparator
        from aat.engine.executor import StepExecutor
        from aat.engine.humanizer import Humanizer
        from aat.engine.waiter import Waiter
        from aat.matchers import MATCHER_REGISTRY
        from aat.matchers.hybrid import HybridMatcher
        from aat.reporters import REPORTER_REGISTRY

        await _manager.broadcast({"type": "loop_start"})

        try:
            mode = ApprovalMode(approval_mode_str)
        except ValueError:
            _ws_handler.error(f"Invalid approval mode: {approval_mode_str}")
            return

        config = _current_config
        if max_loops is not None:
            config.max_loops = max_loops

        # Load scenarios
        path = _resolve_scenario_path(scenario_path)
        variables = _build_variables()
        scenarios = load_scenarios(path, variables=variables)

        if scenario_ids:
            id_set = set(scenario_ids)
            scenarios = [s for s in scenarios if s.id in id_set]

        _ws_handler.info(f"Loaded {len(scenarios)} scenario(s)")

        # Assemble components
        engine_cls = ENGINE_REGISTRY.get(config.engine.type)
        if engine_cls is None:
            _ws_handler.error(f"Unknown engine: {config.engine.type}")
            return
        engine = engine_cls(config.engine)

        matchers = [
            MATCHER_REGISTRY[m.value](config.matching)  # type: ignore[call-arg]
            for m in config.matching.chain_order
            if m.value in MATCHER_REGISTRY
        ]
        hybrid = HybridMatcher(matchers, config.matching)

        humanizer = Humanizer(config.humanizer)
        waiter = Waiter()
        comparator = Comparator()
        executor = StepExecutor(engine, hybrid, humanizer, waiter, comparator)

        adapter_cls = ADAPTER_REGISTRY.get(config.ai.provider)
        if adapter_cls is None:
            _ws_handler.error(f"Unknown AI adapter: {config.ai.provider}")
            return
        adapter = adapter_cls(config.ai)

        reporter_cls = REPORTER_REGISTRY.get("markdown")
        if reporter_cls is None:
            _ws_handler.error("Markdown reporter not found")
            return
        reporter = reporter_cls()

        git_ops: GitOps | None = None
        if mode == ApprovalMode.BRANCH:
            git_ops = GitOps(Path(config.source_path))

        # Approval callback via WebSocket
        def _approval_callback(analysis_text: str) -> bool:
            """Sync wrapper — sends prompt and returns True (for non-manual modes)."""
            _ws_handler.prompt(analysis_text, ["Approve", "Deny"])
            return True  # auto-approve in sync context

        async def _async_approval(analysis_text: str) -> str:
            """Async approval via WebSocket modal."""
            return await _ws_handler.prompt_async(
                "Approve this AI fix?",
                options=["approve", "deny", "approve_all"],
                context={"analysis": analysis_text},
            )

        loop = DevQALoop(
            config=config,
            executor=executor,
            adapter=adapter,
            reporter=reporter,
            engine=engine,
            approval_callback=_approval_callback,
            git_ops=git_ops,
        )

        result = await loop.run(scenarios)

        # Broadcast result
        if result.success:
            _ws_handler.success(f"Loop SUCCESS after {result.total_iterations} iteration(s)")
        else:
            _ws_handler.warning(
                f"Loop ended after {result.total_iterations} iteration(s): {result.reason}"
            )

        await _manager.broadcast(
            {
                "type": "loop_complete",
                "success": result.success,
                "iterations": result.total_iterations,
                "reason": result.reason,
                "duration_ms": result.duration_ms,
            }
        )

    except asyncio.CancelledError:
        _ws_handler.warning("DevQA Loop cancelled")
        await _manager.broadcast({"type": "loop_cancelled"})
    except Exception as exc:  # noqa: BLE001
        guidance = _get_error_guidance(exc)
        error_text = str(exc) or f"{type(exc).__name__}: (상세 메시지 없음)"
        _ws_handler.error(f"DevQA Loop failed: {error_text}")
        msg: dict[str, Any] = {"type": "loop_error", "error": error_text}
        if guidance:
            msg["guidance"] = guidance
        await _manager.broadcast(msg)
