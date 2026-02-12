"""FastAPI web dashboard for AAT.

Provides REST endpoints for config/scenario management,
WebSocket for real-time event streaming, and serves the SPA UI.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
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
        return JSONResponse(content={"scenarios": [], "error": str(exc)})


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

    await _manager.broadcast(
        {"type": "info", "message": f"Scenario uploaded: {safe_name}"}
    )

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
        return JSONResponse(
            content={"status": "ok", "uploaded": safe_name, "scenarios": result}
        )
    except AATError:
        return JSONResponse(
            content={"status": "ok", "uploaded": safe_name, "scenarios": []}
        )


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
    port = _extract_port(command)
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
        _ws_handler.error(f"Test run failed: {exc}")
        await _manager.broadcast({"type": "run_error", "error": str(exc)})


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
        _ws_handler.error(f"DevQA Loop failed: {exc}")
        await _manager.broadcast({"type": "loop_error", "error": str(exc)})
