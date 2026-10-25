# droplink + operator launch (agent `launch`)

**What it does.** An operator clicks a tracked person on /hack/ to launch the drone. Then:

- `hackdash/launch.py` POSTs an operator incident to netra-ask's worker endpoint. The verdict is `deploy` and the why is `operator_launch`.
- A 1 Hz loop keeps adding that person's newest observation until they are lost (30 s) or the operator aborts.
- netra-ask's dispatch sends signed webhooks for each message (`incident`, `end` and `abort`) to **droplink**.
- droplink stands in for the drone side: it checks the signature on each message and records it.

| piece | where | what |
|---|---|---|
| `hackdash/launch.py` | sauron-hack :8500, `/hack/api` | `POST /launch`, `POST /incidents/{id}/abort`, `GET /incidents[/{id}]`, `GET /drone/messages` |
| `droplink/droplink.py` | droplet 127.0.0.1:8510 (`droplink.service`, user netra) | `POST /sauron/v1/messages` (checks HMAC `X-Netra-Signature: t=..,v1=..`, ±300 s), `GET /messages?since=&limit=`, `GET /health`; sqlite at /var/lib/droplink/messages.sqlite |
| `droplink/droplink.service` | /etc/systemd/system | unit |
| `droplink/install.sh` | laptop | copies the code and unit, writes /etc/droplink.env from netra-ask's secret, restarts, checks /health |
| `droplink/droplink.env.example` | | env template (the real file holds the secret: root 600) |
| `tools/click_path_test.py` | droplet | real end-to-end test on a live tracked person: launch → incident → droplink → abort → `end` + `abort`, and no update after the abort |
| `tests/test_droplink.py`, `tests/test_launch.py` | | unit tests |

**Behaviour:**

- **Abort order:** stop the loop, then close our incident as `dismissed` (dispatch sends `end`), then call netra-ask's abort with the operator's own login (dispatch sends `abort`). Nothing is posted after that.
- **Launch is idempotent:** a second click on the same track returns the open incident.
- **No live track:** if the track has no observation within 10 s of its camera's newest, launch returns 409.

**Set-up done outside this repo:**

- netra-ask env: `DISPATCH_WEBHOOK=http://127.0.0.1:8510/sauron/v1/messages`. The manager set it and restarted netra-ask.
- Service account `hack_launch`:
  - Created with netra-internal's `deploy/add-user.sh` (htpasswd).
  - Its password is stored in droplet /root/hack-launch.pw and laptop ~/.config/netra/hack-launch.env, both mode 600. Neither is in git.
  - It is used only by the tests. It can never move the PTZ (see `ptzd/README.md`).
- netra-internal branch `hack-launch-next-ok` (71d5695) adds `/hack` to `NEXT_OK` in `common/auth.py`, so login can redirect back to /hack/. It is deployed: auth.py was copied and netra-map restarted.

Install / update: `bash droplink/install.sh` (HOST defaults to the droplet).
