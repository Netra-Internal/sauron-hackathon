# Sauron hackathon — Oct 24 2026 — rules every agent follows

You are one of several Claude agents in tmux session `hack`, managed by a manager agent. William (COO) is the human.
Read your own brief in briefs/<you>.md. This file holds the rules shared by all agents.

## Report back
- When you finish, get blocked, or need a decision: write it in ~/hack-2026-10-24/status/<you>.md (overwrite; first line = DONE | BLOCKED | NEEDS-WILLIAM | WORKING + one sentence), then stop and wait.
- Never claim done without running the thing and showing the output. No simulated / mock / synthetic data in any product or UI: if there is no real data, show nothing.

## Code
- Work only in YOUR OWN git worktree on YOUR OWN branch (`git worktree add ~/netra/<repo>-wt-hack-<you> -b hack-<you> origin/main`). Other agents are editing the same repos.
- Commit with explicit paths (never `git add -A`). Push your branch. Do not merge to main or deploy unless your brief says so; the manager integrates.
- Deploy hazard: netra-ask deploys rsync --delete from a checkout → a deploy from your branch wipes other agents' code. Manager deploys only.

## Machines (state checked 13:37 PDT today)
- Laptop WSL: 16 GB RAM shared by every agent + Chromium. ONE CPU model job at a time across all agents; run `free -g` before loading a model; no unguarded nohup jobs. Disk: `df -h /mnt/c` (C: has ~61 GB) — ask before anything > 5 GB.
- jetson-cloud (`ssh netra@jetson-cloud`, Orin, 7.5 GB, ~2.5 GB available): edge units for axis-q6215 / jetson-c920 / node3-c920 + edge-serve + LTE running. Do not stop or restart units without the manager. netra-dispatch@jetson-c920 is disabled on purpose (Jev tokens) — start only for a demo window.
- netra-ptz (second Jetson, Sauron viewer :8060): OFFLINE today (not on tailnet, cable IP unreachable).
- Droplet flywheel-01 `ssh root@104.131.163.205`: netra-ask (internal.netralabs.net/ask), catalog, evald, map. DB: `sudo -u netra psql netra_ask`. Use `systemd-run --unit` for temp servers, never `pkill -f` there.
- node3: offline 3 days.

## Money
- Jev (TypeSafe, key ~/.config/netra/typesafe.env): OK without asking if the task costs ≤ $15 (estimate first; $0.042/M input tokens, output free).
- RunPod: state the hourly price; pod commands must self-exit (never `sleep infinity`); stop what you start.
- LLM/VLM calls are reference ceilings, not hot paths; ship small local models for anything per-frame.

## Product rules (decided by William — don't re-litigate)
- Launch is autonomous: a dispatch deploy/urgent = drone launch; Sauron sends `deter` itself. Operators abort/override only — never add an approval gate.
- jetson-c920 is a desk test rig: sanity check only, never headline evidence. Weight evals to real fixed CCTV, day + night.
- Break-in is the demo priority (burglary, forced doors/windows/gates, lock cutting, fence climbing, bike/car tampering). Shoplifting is out of headline metrics.
- Scored eval sets are online human-labelled only; own-camera labels are `unverified`.
- Netra does NOT decode DJI DroneID; DJI DroneID ≠ FAA Remote ID.

## Where things are
- netra-ask (~/netra/netra-ask, main): Ask, Sites/monitor (`/ask/sites`), dispatch (`ask/dispatch/`: judge, caption, subject, watch, webhook command/position/watch streams), sitefuse, edge. docs/dispatch.md, docs/current-vs-ideal.md.
- netra-training branch sauron-bench (~/netra/netra-training-wt-sauron): `src/sauron/` benchmarks, live viewer (`python -m sauron.viewer`, :8060, Jev Watch /jev), graph labeller, actions. Data ~/sauron-data.
- sauron-autonomy (~/netra/sauron-autonomy, Pranay): drone side — ROS 2 + Gazebo + PX4 Offboard tracker, Site A mission, e2e checks (`e2e/*.py`).
- Sauron spec: Notion "Sauron — System Specification" (Netra HQ / Context) + "Product Design — Autonomous Site Security".
- Drone link contract: ~/reports/sauron-link-answers-2026-10-22.md (schema netra.dispatch.command/v1), example payload ~/reports/sauron-link-example/.
- Dispatch demo page: https://claude.ai/artifact/DqVaeP1fFDkhkZrt8SUCXb ; eval clips ~/sauron-data/dispatch-clips, labelled corpus via clipcheck.py.
