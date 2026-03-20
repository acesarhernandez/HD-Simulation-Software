from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from helpdesk_sim.api.routes import router
from helpdesk_sim.bootstrap import build_runtime
from helpdesk_sim.config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    runtime = build_runtime(settings=settings, cwd=Path.cwd())
    app.state.runtime = runtime
    runtime.workers.start()
    try:
        yield
    finally:
        await runtime.workers.stop()


app = FastAPI(
    title="HelpDesk Simulator API",
    version="2.1.0",
    lifespan=lifespan,
)
app.include_router(router)

WEB_DIR = Path(__file__).resolve().parent / "web"
if WEB_DIR.exists():
    app.mount("/ui/static", StaticFiles(directory=WEB_DIR), name="ui-static")


@app.get("/", include_in_schema=False)
def root_redirect() -> RedirectResponse:
    return RedirectResponse(url="/ui")


@app.get("/ui", include_in_schema=False)
def ui_index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/ui/guide", include_in_schema=False)
def ui_guide() -> FileResponse:
    return FileResponse(WEB_DIR / "guide.html")


def _god_access_allowed(request: Request) -> bool:
    runtime = getattr(request.app.state, "runtime", None)
    settings = runtime.settings if runtime is not None else get_settings()
    if not settings.god_mode_enabled:
        return False

    access_key = settings.god_mode_access_key.strip()
    if not access_key:
        return True

    provided = (
        request.headers.get("X-God-Key", "").strip()
        or request.query_params.get("k", "").strip()
    )
    return bool(provided and provided == access_key)


@app.get("/god", include_in_schema=False)
def god_ui(request: Request) -> FileResponse:
    if not _god_access_allowed(request):
        raise HTTPException(status_code=404, detail="Not Found")
    return FileResponse(WEB_DIR / "god.html")


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "helpdesk_sim.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )
