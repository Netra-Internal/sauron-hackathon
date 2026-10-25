# How we built it: a manager agent and a team of Claude agents

Sauron was built in one day (first commit 14:16 PDT, Oct 24 2026) by a team of Claude Code agents. Each ran in its own
tmux window, its own git worktree and its own branch. A manager agent coordinated them, and William (COO) made the
product calls.

## The loop: brief → status → merge

1. **Shared rules.** [COMMON.md](../COMMON.md) is read by every agent first. It covers reporting, how to commit (own
   worktree, own branch, explicit paths), machine limits (one CPU model job at a time on a 16 GB laptop), money limits,
   and the product rules William decided (launch is autonomous with operator abort only; break-in is the demo
   priority; no mock data in any UI).
2. **A brief per agent.** The manager writes [`briefs/<agent>.md`](../briefs/): the goal, the exact deliverables and the
   limits. Agents and briefs:
   [map](../briefs/map.md) (the click-to-dispatch plan) ·
   [dash](../briefs/dash.md) (the `/hack/` operator page) ·
   [boxes](../briefs/boxes.md) (live person boxes + edge relay) ·
   [launch](../briefs/launch.md) (Send drone / Abort + droplink) ·
   [calib](../briefs/calib.md) (camera calibration UI) ·
   [ptz](../briefs/ptz.md) (PTZ control + operator-only guard) ·
   [cloud](../briefs/cloud.md) (edge moved from the Jetson to a RunPod GPU) ·
   [crimevid](../briefs/crimevid.md) (real crime clips through the real judge) ·
   [deck](../briefs/deck.md) (the slides) ·
   [repo](../briefs/repo.md) (this repo's layout for reviewers).
3. **Spawn and steer.** [`tools/hagent`](../tools/hagent) runs `hagent spawn <name> <dir> <brief>`. It opens a tmux
   window running Claude Code and tells it to read the brief. `hagent send` steers an agent, `hagent peek` reads its
   pane, and `hagent ls` lists every agent with its last line.
4. **Status, not chat.** When an agent finishes, gets blocked or needs a decision, it overwrites
   [`status/<agent>.md`](../status/). The first line is DONE / BLOCKED / NEEDS-WILLIAM / WORKING. The body has the
   evidence: commands run, raw log lines and measured numbers. Agents may not claim "done" without running the thing.
   Every number in the [README](../README.md) and [AGENTS.md](../AGENTS.md) comes from one of these files.
5. **Merge and deploy by the manager only.** Each agent pushes `hack-<agent>`. The manager merges into `main`, and only
   the manager deploys. [`deploy/install.sh`](../deploy/install.sh) refuses to ship a checkout that does not contain
   `origin/main`, so one agent's deploy cannot wipe another's routers.

## Guard rails that mattered

- **Real hardware is protected.** Writes to the PTZ camera are operator-only, enforced in code
  ([hackdash/ptz.py](../hackdash/ptz.py) `write_guard`, tests in [tests/test_ptz_guard.py](../tests/test_ptz_guard.py)).
  The agents' own service account gets 403, and the live PTZ test refuses to start without explicit authorisation.
- **Tests that found real bugs.** The live click-path test ([tools/click_path_test.py](../tools/click_path_test.py))
  found an incident update that arrived after an abort. It was fixed and re-verified within the hour
  ([status/launch.md](../status/launch.md)).
- **Plans before code.** The map agent wrote [plans/click-to-dispatch.md](../plans/click-to-dispatch.md) and the manager
  wrote [ARCH.md](../ARCH.md) (the API contract) before the build agents started, so the agents built against one
  contract in parallel.
