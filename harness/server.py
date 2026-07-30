from __future__ import annotations

import secrets
import shutil
import subprocess
import threading
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .catalog import (
    ScenarioCatalogError,
    delete_scenario,
    discover_saves,
    import_save_as_scenario,
    list_scenarios,
    scenario_details,
)
from .controller import RunController
from .debug_artifact import DebugArtifactError
from .debugger import DebugController
from .fixture import FixtureRestoreError
from .rpc import ModConnectionError, ModProtocolError
from .runtime import HarnessRuntimeError
from .scenario import ScenarioError, load_scenario
from .records import RecordError, delete_snapshot, replace_assertions
from .suite import RegressionSuite


_FRONTEND_DIST = Path(__file__).resolve().parent / "frontend" / "dist"
_FRONTEND_ROOT = _FRONTEND_DIST.parent
_DEFAULT_RUNS_DIR = Path(__file__).resolve().parents[2] / "stalley-v2" / "runs"
_CSP = (
    "default-src 'self'; img-src 'self' data:; object-src 'none'; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)
_BAD_REQUEST_ERRORS = (
    FixtureRestoreError,
    HarnessRuntimeError,
    ModConnectionError,
    ModProtocolError,
    ScenarioCatalogError,
    RecordError,
    ScenarioError,
    DebugArtifactError,
    TypeError,
    ValueError,
)


class ImportScenarioRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    save_name: str = Field(alias="saveName")
    scenario_id: str = Field(alias="scenarioId")
    name: str
    description: str = ""


class StartRunRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    scenario_id: str = Field(alias="scenarioId")
    port: int = 10783
    attach: bool = False
    sample_rate: int = Field(default=100, alias="sampleRate")
    timeout: float = 90


class DeleteScenarioRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    scenario_id: str = Field(alias="scenarioId", min_length=1, max_length=120)


class ActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str = Field(min_length=1, max_length=80)
    arguments: list[str] = Field(default_factory=list, max_length=32)


class RecordingRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    from_index: int | None = Field(default=None, alias="fromIndex", ge=0)


class SnapshotNameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)


class AssertionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assertions: list[dict[str, Any]] = Field(max_length=500)


class SuiteRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    scenario_ids: list[str] = Field(alias="scenarioIds", min_length=1)
    port: int = 10783
    attach: bool = False
    sample_rate: int = Field(default=100, alias="sampleRate")
    timeout: float = 90


class LoadDebugRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    run_id: str = Field(alias="runId", min_length=1, max_length=200)
    event_sequence: int = Field(alias="eventSequence", ge=0)
    function: str = Field(min_length=1, max_length=300)


class DebugBreakpointsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lines: list[int] = Field(default_factory=list, max_length=500)


class StartDebugRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    port: int = Field(default=10783, ge=1, le=65535)
    sample_rate: int = Field(default=100, alias="sampleRate", ge=1, le=100)
    timeout: float = Field(default=90, gt=0)


def _error(message: str, status_code: int) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": message})


def _ensure_frontend_build() -> None:
    output = _FRONTEND_DIST / "index.html"
    sources = [
        _FRONTEND_ROOT / "package.json",
        _FRONTEND_ROOT / "package-lock.json",
        _FRONTEND_ROOT / "tsconfig.json",
        _FRONTEND_ROOT / "vite.config.ts",
        _FRONTEND_ROOT / "index.html",
        *_FRONTEND_ROOT.joinpath("src").rglob("*"),
        *_FRONTEND_ROOT.joinpath("public").rglob("*"),
    ]
    newest_source = max(
        (path.stat().st_mtime for path in sources if path.is_file()),
        default=0,
    )
    if output.is_file() and output.stat().st_mtime >= newest_source:
        return

    npm = shutil.which("npm")
    if npm is None:
        raise HarnessRuntimeError(
            "the React UI needs Node.js and npm; install them and start the harness again"
        )

    try:
        if not (_FRONTEND_ROOT / "node_modules").is_dir():
            install_command = (
                "ci"
                if (_FRONTEND_ROOT / "package-lock.json").is_file()
                else "install"
            )
            print("Installing harness UI dependencies...")
            subprocess.run(
                [npm, install_command],
                cwd=_FRONTEND_ROOT,
                check=True,
            )
        print("Building harness UI...")
        subprocess.run(
            [npm, "run", "build"],
            cwd=_FRONTEND_ROOT,
            check=True,
        )
    except subprocess.CalledProcessError as error:
        raise HarnessRuntimeError("the React UI build failed") from error


def create_app(
    *,
    scenarios_dir: str | Path,
    saves_dir: str | Path,
    controller: RunController | None = None,
    token: str | None = None,
    smapi_path: str | Path | None = None,
    runs_dir: str | Path | None = None,
    frontend_dir: str | Path | None = None,
) -> FastAPI:
    resolved_scenarios = Path(scenarios_dir).expanduser().resolve()
    resolved_saves = Path(saves_dir).expanduser().resolve()
    resolved_frontend = Path(frontend_dir or _FRONTEND_DIST).expanduser().resolve()
    resolved_runs = Path(runs_dir or _DEFAULT_RUNS_DIR).expanduser().resolve()
    run_controller = controller or RunController(
        scenarios_dir=resolved_scenarios,
        saves_dir=resolved_saves,
        smapi_path=smapi_path,
    )
    suite_runner = RegressionSuite(run_controller)
    debug_controller = DebugController(
        runs_dir=resolved_runs,
        saves_dir=resolved_saves,
        run_controller=run_controller,
        smapi_path=smapi_path,
    )
    page_token = token or secrets.token_urlsafe(32)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        suite_runner.stop()
        debug_controller.stop()
        run_controller.stop()

    app = FastAPI(
        title="Stalley Scenario Harness",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.controller = run_controller
    app.state.page_token = page_token
    app.state.suite = suite_runner
    app.state.debugger = debug_controller

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = _CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=()"
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(
        _: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        first = error.errors()[0] if error.errors() else None
        message = str(first["msg"]) if first else "request body is invalid"
        return _error(message, status.HTTP_400_BAD_REQUEST)

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, error: HTTPException) -> JSONResponse:
        return _error(str(error.detail), error.status_code)

    async def require_token(
        x_harness_token: Annotated[str | None, Header()] = None,
    ) -> None:
        if not x_harness_token or not secrets.compare_digest(
            x_harness_token,
            page_token,
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="invalid or missing page token",
            )

    @app.get("/api/bootstrap")
    def bootstrap() -> dict[str, Any]:
        return {
            "token": page_token,
            "catalog": list_scenarios(resolved_scenarios),
            "saves": discover_saves(resolved_saves),
            "run": run_controller.snapshot(),
            "suite": suite_runner.snapshot(),
            "debug": debug_controller.snapshot(),
            "capabilities": {
                "recording": True,
                "replay": True,
                "snapshots": True,
                "preview": True,
                "assertions": True,
                "suite": True,
                "debugger": True,
            },
        }

    @app.get("/api/run")
    def get_run() -> dict[str, Any]:
        return run_controller.snapshot()

    @app.get("/api/suite")
    def get_suite() -> dict[str, Any]:
        return suite_runner.snapshot()

    @app.get("/api/scenarios/{scenario_id:path}")
    def get_scenario(scenario_id: str) -> dict[str, Any]:
        scenario_path = (resolved_scenarios / scenario_id).resolve()
        if scenario_path.parent != resolved_scenarios:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="scenario not found",
            )
        try:
            scenario = scenario_details(load_scenario(scenario_path))
        except (OSError, ScenarioError) as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="scenario not found",
            ) from error
        return {"scenario": scenario}

    @app.post(
        "/api/scenarios/import",
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_token)],
    )
    def import_scenario(payload: ImportScenarioRequest) -> dict[str, Any]:
        try:
            scenario = import_save_as_scenario(
                saves_dir=resolved_saves,
                scenarios_dir=resolved_scenarios,
                save_name=payload.save_name,
                scenario_id=payload.scenario_id,
                name=payload.name,
                description=payload.description,
            )
            summary = next(
                item
                for item in list_scenarios(resolved_scenarios)["scenarios"]
                if item["id"] == scenario.id
            )
            return {"scenario": summary}
        except _BAD_REQUEST_ERRORS as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(error),
            ) from error

    @app.post(
        "/api/scenarios/{scenario_id}/delete",
        dependencies=[Depends(require_token)],
    )
    def remove_scenario(
        scenario_id: str,
        payload: DeleteScenarioRequest,
    ) -> dict[str, Any]:
        if payload.scenario_id != scenario_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="scenario confirmation does not match",
            )
        run = run_controller.snapshot()
        if (
            run.get("scenarioId") == scenario_id
            and run.get("status") not in {"idle", "error"}
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="stop the active scenario before deleting it",
            )
        try:
            destination = delete_scenario(resolved_scenarios, scenario_id)
            return {
                "deletedScenarioId": scenario_id,
                "recoverableFrom": str(destination),
            }
        except _BAD_REQUEST_ERRORS as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(error),
            ) from error

    @app.put(
        "/api/scenarios/{scenario_id}/assertions",
        dependencies=[Depends(require_token)],
    )
    def save_assertions(
        scenario_id: str,
        payload: AssertionsRequest,
    ) -> dict[str, Any]:
        try:
            scenario = load_scenario(resolved_scenarios / scenario_id)
            assertions = replace_assertions(scenario.path, payload.assertions)
            return {"assertions": assertions}
        except _BAD_REQUEST_ERRORS as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(error),
            ) from error

    @app.post(
        "/api/scenarios/{scenario_id}/snapshots/{snapshot_name}/delete",
        dependencies=[Depends(require_token)],
    )
    def remove_snapshot(scenario_id: str, snapshot_name: str) -> dict[str, Any]:
        try:
            scenario = load_scenario(resolved_scenarios / scenario_id)
            delete_snapshot(scenario.path, snapshot_name)
            return {"deletedSnapshot": snapshot_name}
        except _BAD_REQUEST_ERRORS as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(error),
            ) from error

    @app.post(
        "/api/run/start",
        status_code=status.HTTP_202_ACCEPTED,
        dependencies=[Depends(require_token)],
    )
    def start_run(payload: StartRunRequest) -> dict[str, Any]:
        try:
            debug_controller.stop()
            run_controller.start(
                payload.scenario_id,
                port=payload.port,
                attach=payload.attach,
                sample_rate=payload.sample_rate,
                timeout=payload.timeout,
            )
            return run_controller.snapshot()
        except _BAD_REQUEST_ERRORS as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(error),
            ) from error
        except RuntimeError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(error),
            ) from error

    @app.post(
        "/api/run/reset",
        status_code=status.HTTP_202_ACCEPTED,
        dependencies=[Depends(require_token)],
    )
    def reset_run() -> dict[str, Any]:
        try:
            run_controller.reset()
            return run_controller.snapshot()
        except _BAD_REQUEST_ERRORS as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(error),
            ) from error
        except RuntimeError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(error),
            ) from error

    @app.post("/api/run/stop", dependencies=[Depends(require_token)])
    def stop_run() -> dict[str, Any]:
        run_controller.stop()
        return run_controller.snapshot()

    @app.post("/api/run/observe", dependencies=[Depends(require_token)])
    def observe() -> dict[str, Any]:
        try:
            observation = run_controller.refresh_observation()
            return {"observation": observation}
        except _BAD_REQUEST_ERRORS as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(error),
            ) from error
        except RuntimeError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(error),
            ) from error

    @app.post("/api/run/actions", dependencies=[Depends(require_token)])
    def execute_action(payload: ActionRequest) -> dict[str, Any]:
        try:
            return {
                "action": run_controller.execute_action(
                    payload.action,
                    payload.arguments,
                )
            }
        except _BAD_REQUEST_ERRORS as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(error),
            ) from error
        except RuntimeError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(error),
            ) from error

    @app.post("/api/run/record/start", dependencies=[Depends(require_token)])
    def start_recording(payload: RecordingRequest) -> dict[str, Any]:
        try:
            return run_controller.start_recording(from_index=payload.from_index)
        except _BAD_REQUEST_ERRORS as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(error),
            ) from error
        except RuntimeError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(error),
            ) from error

    @app.post("/api/run/record/stop", dependencies=[Depends(require_token)])
    def stop_recording() -> dict[str, Any]:
        try:
            return run_controller.stop_recording()
        except RuntimeError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(error),
            ) from error

    @app.post("/api/run/snapshots/mark", dependencies=[Depends(require_token)])
    def mark_snapshot() -> dict[str, Any]:
        try:
            return {"snapshot": run_controller.mark_snapshot()}
        except _BAD_REQUEST_ERRORS as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(error),
            ) from error
        except RuntimeError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(error),
            ) from error

    @app.post("/api/run/snapshots/save", dependencies=[Depends(require_token)])
    def save_marked_snapshot(payload: SnapshotNameRequest) -> dict[str, Any]:
        try:
            return {"snapshot": run_controller.save_marked_snapshot(payload.name)}
        except _BAD_REQUEST_ERRORS as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(error),
            ) from error
        except RuntimeError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(error),
            ) from error

    @app.post("/api/run/snapshots/cancel", dependencies=[Depends(require_token)])
    def cancel_marked_snapshot() -> dict[str, Any]:
        run_controller.cancel_marked_snapshot()
        return run_controller.snapshot()

    @app.post("/api/run/preview", dependencies=[Depends(require_token)])
    def preview() -> dict[str, Any]:
        try:
            return {"preview": run_controller.refresh_preview()}
        except _BAD_REQUEST_ERRORS as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(error),
            ) from error
        except RuntimeError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(error),
            ) from error

    def replay_response(method: str) -> dict[str, Any]:
        try:
            result = getattr(run_controller, method)()
            if method == "step_replay":
                return {"action": result, "run": run_controller.snapshot()}
            return result
        except _BAD_REQUEST_ERRORS as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(error),
            ) from error
        except RuntimeError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(error),
            ) from error

    @app.post("/api/run/replay/start", dependencies=[Depends(require_token)])
    def start_replay() -> dict[str, Any]:
        return replay_response("start_replay")

    @app.post("/api/run/replay/pause", dependencies=[Depends(require_token)])
    def pause_replay() -> dict[str, Any]:
        return replay_response("pause_replay")

    @app.post("/api/run/replay/resume", dependencies=[Depends(require_token)])
    def resume_replay() -> dict[str, Any]:
        return replay_response("resume_replay")

    @app.post("/api/run/replay/step", dependencies=[Depends(require_token)])
    def step_replay() -> dict[str, Any]:
        return replay_response("step_replay")

    @app.post("/api/run/replay/stop", dependencies=[Depends(require_token)])
    def stop_replay() -> dict[str, Any]:
        return replay_response("stop_replay")

    @app.post("/api/run/assertions", dependencies=[Depends(require_token)])
    def run_assertions() -> dict[str, Any]:
        try:
            return {"report": run_controller.run_assertions()}
        except _BAD_REQUEST_ERRORS as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(error),
            ) from error
        except RuntimeError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(error),
            ) from error

    @app.post(
        "/api/suite/start",
        status_code=status.HTTP_202_ACCEPTED,
        dependencies=[Depends(require_token)],
    )
    def start_suite(payload: SuiteRequest) -> dict[str, Any]:
        catalog_ids = {
            scenario["id"]
            for scenario in list_scenarios(resolved_scenarios)["scenarios"]
        }
        missing = [
            scenario_id
            for scenario_id in payload.scenario_ids
            if scenario_id not in catalog_ids
        ]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"scenario not found: {missing[0]}",
            )
        try:
            debug_controller.stop()
            return suite_runner.start(
                payload.scenario_ids,
                port=payload.port,
                attach=payload.attach,
                sample_rate=payload.sample_rate,
                timeout=payload.timeout,
            )
        except _BAD_REQUEST_ERRORS as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(error),
            ) from error
        except RuntimeError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(error),
            ) from error

    @app.post("/api/suite/stop", dependencies=[Depends(require_token)])
    def stop_suite() -> dict[str, Any]:
        return suite_runner.stop()

    @app.get("/api/debug")
    def get_debug() -> dict[str, Any]:
        return debug_controller.snapshot()

    @app.post("/api/debug/load", dependencies=[Depends(require_token)])
    def load_debug(payload: LoadDebugRequest) -> dict[str, Any]:
        try:
            return debug_controller.load(
                payload.run_id,
                payload.event_sequence,
                payload.function,
            )
        except _BAD_REQUEST_ERRORS as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(error),
            ) from error

    @app.put("/api/debug/breakpoints", dependencies=[Depends(require_token)])
    def set_debug_breakpoints(
        payload: DebugBreakpointsRequest,
    ) -> dict[str, Any]:
        try:
            return debug_controller.set_breakpoints(payload.lines)
        except RuntimeError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(error),
            ) from error

    @app.post(
        "/api/debug/start",
        status_code=status.HTTP_202_ACCEPTED,
        dependencies=[Depends(require_token)],
    )
    def start_debug(payload: StartDebugRequest) -> dict[str, Any]:
        try:
            debug_controller.start(
                port=payload.port,
                sample_rate=payload.sample_rate,
                timeout=payload.timeout,
            )
            return debug_controller.snapshot()
        except (TypeError, ValueError) as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(error),
            ) from error
        except RuntimeError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(error),
            ) from error

    def debug_command(method: str) -> dict[str, Any]:
        try:
            return getattr(debug_controller, method)()
        except RuntimeError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(error),
            ) from error

    @app.post("/api/debug/pause", dependencies=[Depends(require_token)])
    def pause_debug() -> dict[str, Any]:
        return debug_command("pause")

    @app.post(
        "/api/debug/restart",
        status_code=status.HTTP_202_ACCEPTED,
        dependencies=[Depends(require_token)],
    )
    def restart_debug() -> dict[str, Any]:
        return debug_command("restart")

    @app.post("/api/debug/observe", dependencies=[Depends(require_token)])
    def observe_debug() -> dict[str, Any]:
        try:
            return {"observation": debug_controller.observe()}
        except _BAD_REQUEST_ERRORS as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(error),
            ) from error
        except RuntimeError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(error),
            ) from error

    @app.post("/api/debug/preview", dependencies=[Depends(require_token)])
    def preview_debug() -> dict[str, Any]:
        try:
            return {"preview": debug_controller.preview()}
        except _BAD_REQUEST_ERRORS as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(error),
            ) from error
        except RuntimeError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(error),
            ) from error

    @app.post("/api/debug/continue", dependencies=[Depends(require_token)])
    def continue_debug() -> dict[str, Any]:
        return debug_command("resume")

    @app.post("/api/debug/step", dependencies=[Depends(require_token)])
    def step_debug() -> dict[str, Any]:
        try:
            return debug_controller.resume(step=True)
        except RuntimeError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(error),
            ) from error

    @app.post("/api/debug/stop", dependencies=[Depends(require_token)])
    def stop_debug() -> dict[str, Any]:
        return debug_controller.stop()

    if resolved_frontend.is_dir() and (resolved_frontend / "index.html").is_file():
        app.mount(
            "/",
            StaticFiles(directory=resolved_frontend, html=True),
            name="frontend",
        )
    else:

        @app.get("/")
        def missing_frontend() -> JSONResponse:
            return _error(
                "UI assets are missing; run `npm install && npm run build` "
                "in harness/frontend",
                status.HTTP_503_SERVICE_UNAVAILABLE,
            )

    return app


def serve_ui(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    scenarios_dir: str | Path,
    saves_dir: str | Path,
    smapi_path: str | Path | None = None,
    runs_dir: str | Path | None = None,
    open_browser: bool = True,
) -> None:
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError("the harness UI may only bind to the local machine")

    _ensure_frontend_build()
    app = create_app(
        scenarios_dir=scenarios_dir,
        saves_dir=saves_dir,
        smapi_path=smapi_path,
        runs_dir=runs_dir,
    )
    url = f"http://{host}:{port}"
    print(f"Stalley Scenario Harness: {url}")
    if open_browser:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        uvicorn.run(app, host=host, port=port, log_level="warning")
    except KeyboardInterrupt:
        print("\nStopping the Stalley Scenario Harness.")
