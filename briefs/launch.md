# Brief: launch — Send drone, abort, and our own drone receiver (hackathon repo)
Read ~/hack-2026-10-24/ARCH.md and plans/click-to-dispatch.md (§4). Own `hackdash/launch.py` (APIRouter `router`) and
`droplink/`. Do NOT edit netra-ask; use its deployed endpoints (code in ~/netra/netra-ask, main 6417b5f, docs/dispatch.md):
- POST /launch: build an operator incident (id `<cam>-op-<UTC stamp>-<hex4>` matching store.ID_RE, mode live, verdict
  deploy, why operator_launch, box, frame_w/h, subject_confirmed true, track [{at, box}], evidence frame+crop from the
  ring frame) and post it through netra-ask's existing worker endpoint POST /ask/api/dispatch/incidents (worker token
  from /etc/netra-ask.env) so netra-ask locates, binds to the site track, signs and forwards it. Find the person's box
  from the same live source `boxes` uses (coordinate via status files; until then read it yourself). Idempotent:
  a click on a person already in an open incident returns it.
- Lifecycle: no watcher posts to our incidents, so run a 1 Hz loop that keeps posting track points while the person is
  tracked so netra-ask's subject_lost close (→ automatic `end`) fires when they leave.
- POST /incidents/{id}/abort → netra-ask's existing abort route (it needs the internal login: figure out the cleanest
  way, e.g. a service account; ask the manager before creating users).
- droplink: a small service on the droplet (127.0.0.1:8510, POST /sauron/v1/messages) that verifies X-Netra-Signature
  (HMAC-SHA256 with DISPATCH_WEBHOOK_SECRET, |now−t| ≤ 300 s), de-dupes by delivery_id, stores every message (sqlite or
  jsonl), returns 2xx; GET /hack/api/drone/messages exposes them. It is OUR stand-in for the drone receiver: it shows
  exactly what a drone would get. Later it can bridge to a drone we own. Do not contact dwone.
- You may install/restart droplink's own unit. Setting DISPATCH_WEBHOOK in /etc/netra-ask.env + restarting netra-ask
  is the MANAGER's: write NEEDS-MANAGER in status/launch.md when droplink is ready.
Done = a real click path test: POST /launch on a real tracked person → incident in netra-ask → signed message in
droplink → abort → `end` in droplink; output pasted in status/launch.md.
