# Manual PTZ for the Axis Q6215-LE (agent `launch`)

> **HARD RULE: do not move the camera from any test, script or browser run unless William asks directly.** William
> places it for calibration. Tests run against a stub (`tests/test_ptz.py`) or against the 403 path only.
> `tools/ptz_test.py` and `tools/ptz_shots.js` exit at once unless `PTZ_TEST_WILLIAM_ASKED=1`.

```
browser /hack/ ── ptz.js ──> hackdash/ptz.py (droplet :8500, /hack/api/ptz/...)
                                  │ Bearer /etc/ptzd-token
              ptzd-tunnel :8530 ──┤ (commands)       ssh -L over Tailscale
          ptzd-tunnel-img :8531 ──┘ (snapshots)
                                  v
                      ptzd/ptzd.py (Jetson 127.0.0.1:8530) ── VAPIX digest ──> Axis <camera-ip>
```

| piece | what |
|---|---|
| `ptzd/ptzd.py` | stdlib HTTP service next to the camera. It offers only a fixed set of commands and never passes VAPIX through. Endpoints: `/position`, `/move` (with a 1.2 s deadman), `/stop`, `/center` (areazoom), `/goto` and `/save` (preset `hack-home` only, created via `ptzconfig.cgi`), `/snapshot.jpg`, `/daynight` (ptz.cgi `ircutfilter=on\|off\|auto`). |
| `ptzd/install.sh BOX forward\|reverse [DROPLET]` | Installs ptzd.service plus /etc/ptzd.env on BOX. Creates the token in droplet /etc/ptzd-token (root:netra 640). Creates the tunnel units. Deployed as `forward` on the Jetson. |
| `ptzd/deployed/*.service` | The units as deployed: `ptzd.service` (Jetson) and `ptzd-tunnel{,-img}.service` (droplet). |
| `ptzd/ptzd.env.example`, `ptzd/hackdash-ptz.env.example` | Env templates. The real files hold the camera creds and token, root 600. |
| `hackdash/ptz.py` | Routes under `/hack/api/ptz/{cam}/`: `state`, `move`, `stop`, `center`, `home`, `home/save`, `daynight`, `lock`, `snapshot.jpg`. It also shows a calibration warning chip when the camera is off its calibrated pose. |
| `hackdash/static/ptz.js`, `ptz.css` | The full-screen "Move camera" view: hold-to-move pad and zoom, click to centre (shift for 2×), keyboard control, a speed slider, Home / Save as Home, Day / Night / Auto, a latency readout and a PTZ lock toggle. |
| `hackdash/ptz_zoomcal.json` | Measured zoom-step → field-of-view curve (Oct 12). |
| `tests/test_ptz.py`, `tests/test_ptz_guard.py` | ptzd against a recording stub camera, plus the operator-only guard. A refused request never reaches the stub. |

**Write guard.** Every write (move, stop, center, home, save, daynight) returns `403 PTZ is operator-only` unless the signed-in user is in `PTZ_OPERATORS` (default `william`). Users in `PTZ_NEVER` (default `hack_launch`) are always refused. Reading state, position and snapshots stays open. The **PTZ lock** (persisted in `PTZ_LOCK_FILE`) blocks every write, William's included, until he turns it off.

**Firmware notes (AXIS OS 11.7):**

- `ptz.cgi` answers OK to `setserverpresetname` but creates nothing. Use `ptzconfig.cgi`.
- The `PTZ.Various.V1.IrCutFilter` parameter does not show the live state. ptzd reports the last mode it set, and hackdash adds a measured colour/IR guess from the picture's saturation.
- The droplet↔Jetson path goes through a Tailscale DERP relay (~85 ms, ~65–130 KB/s). That is why snapshots get their own tunnel and are 640x360 at compression 75, shared between viewers.
