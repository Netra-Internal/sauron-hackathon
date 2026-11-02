DONE: branch hack-repo pushed (4916c22, contains origin/main incl. your Mermaid commit); CI green https://github.com/Netra-Internal/sauron-hackathon/actions/runs/40150728704 — MANAGER: merge hack-repo into main.

## What changed
- README top: tests badge → slides link (first link) → live demo links (/hack/ + UCSD DIB site) → pitch → pointer to AGENTS.md
  → looping GIF media/fence-climb.gif (1.4 MB, 12 s, 560 px, from media/crimevid/fence-climb.mp4, shows the DEPLOY banner)
  → Results table: every number links its status/*.md report + code + test command. Your Mermaid diagram is kept as-is; the
  text diagram moved into a <details>. The old prose sections are kept under "Details". Internal-links / honest-limits sections NOT re-added.
- AGENTS.md (claim → evidence → code file#Lline → test; one test command; reading order; built today vs pre-existing
  netra-ask judge/sitefuse/camgeo/edge), llms.txt, docs/how-we-built-it.md (manager + one agent per brief, briefs → status → merge, hagent).
- CI: .github/workflows/tests.yml (py 3.13, `pip install -r requirements.txt && pytest -rs`); pytest.ini (testpaths=tests,
  so tools/*_test.py are never collected: tools/ptz_test.py exits on import anyway); pytest==9.1.1 added to requirements.txt.
  Result on CI and on a clean local venv: 29 passed, 1 skipped (tests/test_calib.py: needs private netra-ask checkout ASK_DIR).
  With ~/netra/netra-ask present, test_calib passes too (7 passed).
- Repo metadata (gh): description, homepage https://internal.netralabs.net/hack/, topics computer-vision, security, drones,
  ai-agents, jetson, runpod, claude, vlm, object-tracking, hackathon, fastapi, camera-calibration. Repo is public.
- Sanitized in current files (28 files incl. status/, briefs/, COMMON.md, ARCH.md): droplet IP → <droplet>, tailnet 100.x → <jetson>/<tailnet-ip>,
  pod IP:port → <pod>:<port>, pod id → <pod-id>, netra@jetson-cloud → <jetson>, camera/LAN 192.168.x → <camera-ip>/<lan-ip>.
  `git grep` for all of these on HEAD is empty. .gitignore extended (*.pyc, .pytest_cache, *.env except *.env.example, editor temp).
  No tracked __pycache__/temp clutter existed. Every relative link in README/AGENTS.md/llms.txt/docs checked: 0 broken.

## Before the NEXT deploy (behaviour changes from sanitizing; nothing deployed by me)
- deploy/install.sh, droplink/install.sh, ptzd/install.sh, cloud/r2.sh, cloud/stage.sh, cloud/compare.py now REQUIRE the host
  in env (no hard-coded default): `HACK_HOST=root@<droplet-ip> deploy/install.sh` (resp. HOST= / DROPLET= / RELAY= / POD=).
- hackdash/live.py: HACK_JUDGE_SSH no longer defaults to the Jetson IP. Add to /etc/sauron-hack.env on the droplet:
  `HACK_JUDGE_SSH=jetson-cloud=netra@<jetson tailnet ip>` — otherwise the judge on/off indicator shows "unknown" (no crash).
  install.sh now reads the Jetson host for known_hosts from that same line. The dead HACK_JETSON_SSH line (unused by code) was removed from the unit.
- Merge note: status/*.md and briefs/*.md were sanitized on this branch; if agents edit them on main meanwhile, take theirs and
  re-run the redaction (patterns in this file's list above).

No camera, droplet service or other agent's code touched beyond string sanitizing. Temp venv/frames deleted.
