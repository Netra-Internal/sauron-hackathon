"""Send-drone demo app: the page at /hack/ and the API under /hack/api.

The API routers belong to other pieces (hackdash.live = cameras, live frame, person boxes; hackdash.launch = send
drone, abort, incidents, drone messages). They are imported tolerantly: a router that is missing or fails to import
is reported by /hack/api/health and its routes answer 404, so the page shows "not deployed" instead of anything made up.

Auth: public view. Any GET/HEAD under /hack (page, API reads, and /hack/stream via nginx's auth_request to
/hack/api/health) works without a login. Writes need the one internal.netralabs.net login (netra-internal common.auth:
the /map/login cookie or HTTP basic, the same as /ask). HACK_NO_AUTH=1 turns it off for a local dev server only.
"""
from __future__ import annotations

import importlib
import logging
import os
import re
import sys
import traceback
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

log = logging.getLogger("hackdash")
STATIC = Path(__file__).parent / "static"
PREFIX = "/hack"
LOGIN = "/map/login?next=/hack/"
# machine routes that check the worker Bearer token themselves (hackdash.live: nginx mirror of the edge bucket POST)
NO_LOGIN = {f"{PREFIX}/api/_edge/bucket", f"{PREFIX}/relay/api/edge/bucket", f"{PREFIX}/relay/api/edge/config",
            f"{PREFIX}/relay/api/edge/heartbeat"}   # hackdash.relay: the edge's ask base URL; token checked by us/netra-ask

sys.path.insert(0, os.environ.get("ASK_INTERNAL_DIR", "/opt/netra/netra-internal"))
NO_AUTH = os.environ.get("HACK_NO_AUTH") == "1"
try:
    from common import auth as internal_auth  # the one login for internal.netralabs.net
except Exception:  # local dev without the internal checkout
    internal_auth = None

app = FastAPI(title="Sauron hack: send drone", docs_url=None, redoc_url=None, openapi_url=None)

ROUTERS = {"live": "hackdash.live", "launch": "hackdash.launch", "calib": "hackdash.calib", "ptz": "hackdash.ptz"}
MOUNTED: dict[str, str] = {}   # name -> "ok" or the import error


def _mount(name: str, module: str, prefix: str = f"{PREFIX}/api"):
    try:
        mod = importlib.import_module(module)
        app.include_router(mod.router, prefix=prefix)
        MOUNTED[name] = "ok"
    except Exception as e:
        MOUNTED[name] = f"{type(e).__name__}: {e}"
        log.warning("router %s not mounted: %s", module, "".join(traceback.format_exception_only(e)).strip())


def user_of(req: Request) -> str | None:
    if NO_AUTH:
        return "dev"
    return internal_auth.user_of(req.headers) if internal_auth else None


# Public view (William): anyone with the link sees everything (GET/HEAD) without a login; every write needs the login.
# Harmless POSTs that only compute or show something stay public too. Internal-only reads stay behind the login.
PUBLIC_POST = [re.compile(p) for p in (rf"^{PREFIX}/api/calib/freeze/[^/]+$",
                                       rf"^{PREFIX}/api/calib/sites/[^/]+/cameras/[^/]+/project$")]
LOGIN_GET = {f"{PREFIX}/relay/status"}


@app.middleware("http")
async def need_user(req: Request, call_next):
    """Reads under /hack are public (anonymous = req.state.user None); writes need the internal login (401)."""
    path = req.url.path
    if path.startswith(PREFIX) and path not in NO_LOGIN:
        u = user_of(req)
        req.state.user = u
        public = (req.method in ("GET", "HEAD") and path not in LOGIN_GET) or \
                 (req.method == "POST" and any(p.match(path) for p in PUBLIC_POST))
        if not u and not public:
            if path.startswith(f"{PREFIX}/api") or req.method != "GET":
                return JSONResponse({"detail": "sign in to control: /map/login?next=/hack/"}, status_code=401)
            return RedirectResponse(LOGIN, status_code=303)
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
    """The page, with its JS/CSS URLs versioned by mtime so a redeploy is never hidden by the browser cache."""
    html = (STATIC / "index.html").read_text()
    for f in ("hack.js", "hack.css"):
        html = html.replace(f"/static/{f}", f"/static/{f}?v={int((STATIC / f).stat().st_mtime)}")
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


app.mount(f"{PREFIX}/static", StaticFiles(directory=STATIC), name="static")

for _name, _module in ROUTERS.items():
    _mount(_name, _module)
_mount("relay", "hackdash.relay", f"{PREFIX}/relay")
