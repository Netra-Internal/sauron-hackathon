# boxes: live frame + person boxes + labels, and the edge relay (agent `boxes`)

| File | What |
|---|---|
| `live.py` | APIRouter at `/hack/api`: `GET /cameras`, `GET /cameras/{cam}/live`, `GET /cameras/{cam}/frame.jpg?t=`, `POST /_edge/bucket` (feed only) |
| `relay.py` | APIRouter at `/hack/relay`: the edge's ask base URL. `POST api/edge/bucket` (spool, 200 at once, forward in order), `GET api/edge/config`, `POST api/edge/heartbeat` (pass-through), `GET status` |
| `nginx-edge-mirror.conf` | nginx snippet: `/ask/api/edge/bucket` to netra-ask as before, plus a mirror copy to `:8500/hack/api/_edge/bucket` |
| `live-relay.env.example` | env template (no secrets) |
| `../tests/test_live.py` | obs store, frame-time choice, 404 fallback, complete_ns empty frames, label shape |

**Boxes.** netra-ask keeps per-frame edge boxes only in memory, and its `tracks` table holds only foot points. So we take the edge bucket
`positions[].obs` (`[t_ns, x1, y1, x2, y2, conf]`, source px, the same track uuids sitefuse binds on) in one of two ways: the nginx mirror
(Jetson → `/ask`), or the relay (an edge whose base URL is `/hack/relay`).

**Frame.** `/live` returns the newest frame time t for which we hold the complete box set AND the ring JPEG
(edge-serve `/frame?camera&t`, about 0.65 s). So the picture and the boxes are one moment.
- Every bucket's `complete_ns − 1` is also a known frame time, which lets an empty scene advance with zero boxes.
- If the ring answers 404 at t, we try the next frame time ≥ 0.2 s older.
- Only one fetch per camera is in flight at a time.
- The frame is prefetched as soon as a bucket arrives, while someone is polling.

**Labels.** A box gets a label only from an open live `dispatch_incidents` row, or a `dispatch_watch` row less than 120 s old, whose
`record.site_track_id` is the box's site track (`site_track_links`). Otherwise the label is null. `judge_on` comes from
`systemctl is-active netra-dispatch@<cam>` over ssh (read-only).

**Relay.** netra-ask's bucket ingest takes 2–12 s, and the edge poster is sequential.
- The relay checks the worker token, then saves the raw request under `HACK_RELAY_DIR`, feeds the boxes and answers 200.
- One worker forwards the saved requests to netra-ask directly (`127.0.0.1:8400`) in order, with the same body, content-type and
  Authorization, retrying forever.
- A permanent 4xx moves the bucket to `rejected/`, so nothing is deleted unforwarded. Over `HACK_RELAY_MAX_MB` it answers 503.
- Backlog is logged as `relay: backlog N` in `journalctl -u sauron-hack`.

**Deploy.** Run `deploy/install.sh` from a tree that contains origin/main. The nginx mirror is applied by hand: add
`nginx-edge-mirror.conf` inside the `internal` server block, then `nginx -t && systemctl reload nginx`. `app.py` mounts both routers and
exempts `/hack/api/_edge/bucket` and the three `/hack/relay/api/edge/*` paths from the login.

**Measured (2026-10-24).**
- Box lag 2.9–6.4 s with people present. Edge obs arrive at t + 1.2–2.8 s, the frame fetch takes about 0.65 s, and the Jetson posts a bucket about every 3 s.
- Relay with the real RunPod edge: buckets about 1/s, each answered 200 at once, backlog 0–3, 0 rejected.
