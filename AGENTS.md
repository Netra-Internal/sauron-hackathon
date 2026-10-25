# AGENTS.md — a map of this repo for AI reviewers

**Sauron** is autonomous site security. It watches a site's cameras and judges what a person is doing (break-in,
theft, tampering, trespass, weapon…). It puts that person on the map as lat/lon ± m and sends a drone with an
HMAC-signed launch message. Operators can abort; there is no approval gate. Built in one day (Oct 24 2026) by a manager
agent plus one Claude agent per brief in [`briefs/`](briefs/), on top of Netra's existing production stack.

- Live (public, no login): https://internal.netralabs.net/hack/ (operator page) and
  https://internal.netralabs.net/ask/sites#/site/ucsd-design-innovation-building-c1dd (site map)
- Slides: https://docs.google.com/presentation/d/1DFFL7WKfvFmFfGj1GIm5n_uDdgEpInlzHpR_xEo7hNI/edit?usp=sharing (PDF copy: [media/Sauron-Hackathon-Deck.pdf](media/Sauron-Hackathon-Deck.pdf))
- Human overview: [README.md](README.md). Agent-team story: [docs/how-we-built-it.md](docs/how-we-built-it.md).

## Run the tests (one command)

    pip install -r requirements.txt && pytest

Python 3.13. Tests live in `tests/` only ([pytest.ini](pytest.ini)). They need no network, no database and no camera:
the camera, ptzd and netra-ask are local stand-ins inside the tests. One file skips on a clean checkout, with a reason:
[tests/test_calib.py](tests/test_calib.py) needs a checkout of the private netra-ask repo (`ASK_DIR`) for `ask/camgeo.py`.
CI runs the same thing on every push: [.github/workflows/tests.yml](.github/workflows/tests.yml).
`tools/*_test.py` are **live** end-to-end checks against the deployed system. They are not unit tests, and
`tools/ptz_test.py` refuses to run unless explicitly authorised, because it moves a real camera.

## Where each claim is verified

Every number comes from an agent's report in [`status/`](status/). Each report holds the raw log lines it was taken from.

| claim | number | measured in | code | test / check |
|---|---|---|---|---|
| real crime clips → drone deploy | 5/5 | [status/crimevid.md](status/crimevid.md) (table, line 3) | [crimevid/run.sh](crimevid/run.sh), [crimevid/render.py](crimevid/render.py) | replay of netra-ask's dispatch Watcher; videos [media/crimevid/](media/crimevid/) |
| benign clips → deploy | 0/2 | [status/crimevid.md](status/crimevid.md) | same | [media/crimevid/owner-car-1.mp4](media/crimevid/owner-car-1.mp4), [owner-car-2.mp4](media/crimevid/owner-car-2.mp4) |
| fastest deploy after crime start | +3.5 s (fence climb, ATM) | [status/crimevid.md](status/crimevid.md) | same | [media/crimevid/fence-climb.mp4](media/crimevid/fence-climb.mp4) (timeline bar at the bottom) |
| police never picked as suspect | — | [status/crimevid.md](status/crimevid.md) | [crimevid/police.py](crimevid/police.py) | [media/crimevid/bike-lock.mp4](media/crimevid/bike-lock.mp4) |
| Jev cost, whole clip set | $0.054 | [status/crimevid.md](status/crimevid.md) | — | — |
| click person → netra-ask accepted | 0.8 s | [status/launch.md](status/launch.md) (`post_s`) | [hackdash/launch.py:224](hackdash/launch.py#L224) (`POST /launch`) | [tools/click_path_test.py](tools/click_path_test.py) (live); [tests/test_launch.py](tests/test_launch.py) |
| click → first signed launch at receiver | 2.8 s | [status/launch.md](status/launch.md) | [droplink/droplink.py:45](droplink/droplink.py#L45) (`verify`) | [tests/test_droplink.py](tests/test_droplink.py) (signature, replay, dedupe) |
| abort → `end` + closed + `abort`, no update after | — | [status/launch.md](status/launch.md) | [hackdash/launch.py:349](hackdash/launch.py#L349) | [tools/click_path_test.py](tools/click_path_test.py) |
| person → coordinate, LOO median (test rig) | 7.2 m | [status/calib.md](status/calib.md) | [hackdash/calib.py:319](hackdash/calib.py#L319) (`draft_fit`) | [tests/test_calib.py](tests/test_calib.py) (recovers a known camera, catches a mis-click) |
| PTZ browser → camera, median | ~0.5 s | [status/ptz.md](status/ptz.md) (latency table) | [ptzd/ptzd.py](ptzd/ptzd.py) | [tests/test_ptz.py](tests/test_ptz.py) (allow-list, dead-man stop) |
| PTZ is operator-only | 403 for every non-operator | [status/ptz.md](status/ptz.md) | [hackdash/ptz.py:172](hackdash/ptz.py#L172) (`write_guard`) | [tests/test_ptz_guard.py](tests/test_ptz_guard.py) |
| detection + judge on a cloud GPU | RTX A5000, $0.27/h | [status/cloud.md](status/cloud.md) | [cloud/pod/supervise.py](cloud/pod/supervise.py) | [cloud/compare.py](cloud/compare.py) (pod shadow vs production) |
| edge boxes acked at once | every bucket 200 | [status/boxes.md](status/boxes.md) | [hackdash/relay.py](hackdash/relay.py), [hackdash/live.py](hackdash/live.py) | [tests/test_live.py](tests/test_live.py) |

Own-camera results come from the desk test rig (jetson-c920). They are labelled as such and are not headline
evidence. The crime clips are public CCTV with human-labelled crime windows.

## Key modules, in reading order

1. [ARCH.md](ARCH.md): the API contract the agents built against.
2. [hackdash/app.py](hackdash/app.py): the `/hack/` service. It mounts each router tolerantly, so a missing router shows "not deployed", never fake data.
3. [hackdash/live.py](hackdash/live.py): cameras, live frame and person boxes. The frame and the boxes share one timestamp.
4. [hackdash/relay.py](hackdash/relay.py): the edge posts here. It acks at once and forwards to netra-ask in order in the background.
5. [hackdash/launch.py](hackdash/launch.py): Send drone and Abort. It follows the person, attaches evidence crops and posts the incident to netra-ask.
6. [droplink/droplink.py](droplink/droplink.py): the drone-side receiver. HMAC check, ±300 s clock window, dedupe, sqlite log.
7. [hackdash/calib.py](hackdash/calib.py) + [hackdash/static/calib.js](hackdash/static/calib.js): click frame↔map pairs, multi-start pose fit, leave-one-out error.
8. [hackdash/ptz.py](hackdash/ptz.py) → [ptzd/ptzd.py](ptzd/ptzd.py): the operator PTZ path and the allow-listed VAPIX proxy next to the camera.
9. [cloud/](cloud/) ([README](cloud/README.md)): Jetson → RunPod video push and the per-camera edge supervisor on the pod.
10. [crimevid/](crimevid/) ([README](crimevid/README.md)): replays real crime clips through the real judge and renders annotated videos.

## Built today vs reused

**Built today (this repo):** `hackdash/` (the operator page and API: live boxes, relay, launch/abort, calibration UI, PTZ
UI and guard), `droplink/`, `ptzd/`, `cloud/` (the Jetson → RunPod push and the pod edge), `crimevid/`, `deploy/`,
`tools/`, `tests/`, and the deck in `deck/`.

**Pre-existing Netra stack (not in this repo, used unmodified):** netra-ask, with the dispatch judge (Jev 4-frame
strips → facts → policy → verdict), sitefuse (the site tracker that turns a person into lat/lon) and camgeo (the camera
model and pose fit that `hackdash/calib.py` loads), plus the Sites monitor at `/ask/sites` and the edge detector/tracker
(`ask.edge`, YOLO11s) that now runs on the pod. Also pre-existing: the Jetson edge units and the droplet. The drone side
(ROS 2/PX4) is a separate repo and is not part of this one.

## Conventions

- No mock or synthetic data in any product surface: if there is no real data, the UI shows nothing.
- Secrets and hosts are placeholders (`<droplet>`, `<jetson>`, `<pod>`, `<camera-ip>`). Real values live only on the machines.
- `briefs/` and `status/` are the agent team's live working files. They are kept as written, with host addresses redacted.
