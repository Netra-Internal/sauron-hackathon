"""Send-drone demo app: the page at /hack/ and the API under /hack/api.

The API routers belong to other pieces (hackdash.live = cameras, live frame, person boxes; hackdash.launch = send
drone, abort, incidents, drone messages). They are imported tolerantly: a router that is missing or fails to import
is reported by /hack/api/health and its routes answer 404, so the page shows "not deployed" instead of anything made up.

Auth: the one internal.netralabs.net login (netra-internal common.auth: the /map/login cookie or HTTP basic), the same
as /ask. HACK_NO_AUTH=1 turns it off for a local dev server only.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import traceback
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

log = logging.getLogger("hackdash")
STATIC = Path(__file__).parent / "static"
PREFIX = "/hack"
LOGIN = "/map/login?next=/hack/"
# machine routes that check the worker Bearer token themselves (hackdash.live: nginx mirror of the edge bucket POST)
NO_LOGIN = {f"{PREFIX}/api/_edge/bucket"}

sys.path.insert(0, os.environ.get("ASK_INTERNAL_DIR", "/opt/netra/netra-internal"))
NO_AUTH = os.environ.get("HACK_NO_AUTH") == "1"
try:
    from common import auth as internal_auth  # the one login for internal.netralabs.net
except Exception:  # local dev without the internal checkout
    internal_auth = None

app = FastAPI(title="Sauron hack: send drone", docs_url=None, redoc_url=None, openapi_url=None)

ROUTERS = {"live": "hackdash.live", "launch": "hackdash.launch"}
MOUNTED: dict[str, str] = {}   # name -> "ok" or the import error


def _mount(name: str, module: str):
    try:
        mod = importlib.import_module(module)
        app.include_router(mod.router, prefix=f"{PREFIX}/api")
        MOUNTED[name] = "ok"
    except Exception as e:
        MOUNTED[name] = f"{type(e).__name__}: {e}"
        log.warning("router %s not mounted: %s", module, "".join(traceback.format_exception_only(e)).strip())


def user_of(req: Request) -> str | None:
    if NO_AUTH:
        return "dev"
    return internal_auth.user_of(req.headers) if internal_auth else None


@app.middleware("http")
async def need_user(req: Request, call_next):
    """Every /hack path needs the internal login. Pages redirect to it; the API answers 401."""
    if req.url.path.startswith(PREFIX) and req.url.path not in NO_LOGIN:
        u = user_of(req)
        if not u:
            if req.url.path.startswith(f"{PREFIX}/api"):
                return JSONResponse({"detail": "sign in at /map/login"}, status_code=401)
            return RedirectResponse(LOGIN, status_code=303)
        req.state.user = u
    return await call_next(req)


@app.get(f"{PREFIX}/api/health")
def health(req: Request):
    return {"user": req.state.user, "routers": MOUNTED, "auth": "off (dev)" if NO_AUTH else
            "internal login" if internal_auth else "unavailable: common.auth not importable"}


@app.get(PREFIX)
def to_slash():
    return RedirectResponse(f"{PREFIX}/", status_code=308)


@app.get(f"{PREFIX}/")
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


app.mount(f"{PREFIX}/static", StaticFiles(directory=STATIC), name="static")

for _name, _module in ROUTERS.items():
    _mount(_name, _module)
