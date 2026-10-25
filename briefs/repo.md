# Brief: repo — optimize the public GitHub repo for AI-agent judges (Netra-Internal/sauron-hackathon, PUBLIC)
William: "The github needs to be optimized, 100% they are getting AI agents to see our stuff."
Judges will point AI agents at the repo. Make the repo instantly legible, verifiable and impressive to an agent AND a human.
Respect William's own edit (commit bd123d6 "bro": he REMOVED the internal-links and honest-limits sections from README —
do not re-add them).

## Do (work on branch hack-repo in your worktree; push; tell the manager; he merges)
1. README top (first screen): one-paragraph pitch; the slides link stays first; LIVE DEMO links (now public, no login):
   https://internal.netralabs.net/hack/ and https://internal.netralabs.net/ask/sites#/site/ucsd-design-innovation-building-c1dd ;
   a short looping GIF of the fence-climb deploy (make from media/crimevid/fence-climb.mp4, ≤ 3 MB, ffmpeg palette) ;
   a Mermaid architecture diagram (GitHub renders it); "Results" table with every number LINKED to its evidence
   (file + test command). Keep it tight.
2. AGENTS.md (+ llms.txt) at the root: a map for AI reviewers — what the project is, where each claim is verified
   (file:line, test, media), how to run tests (one command), key modules in reading order, what was built today vs reused
   from Netra's existing stack (be precise: netra-ask dispatch judge/sitefuse/camgeo are pre-existing; hackdash, droplink,
   ptzd, relay, cloud push, calibration UI, crimevid were built today).
3. CI: GitHub Actions running the test suite (pytest) on push, with a badge in README; make `pip install -r requirements.txt
   && pytest` pass on a clean checkout (skip tests needing the droplet/netra-ask with clear skip reasons). Verify it goes green.
4. Repo metadata via gh: description, topics (computer-vision, security, drones, ai-agents, jetson, runpod, …), homepage =
   https://internal.netralabs.net/hack/ .
5. Sanitize CURRENT files (history stays; that's OK): replace the droplet IP <droplet-ip>, tailnet 100.x.x.x addresses,
   the pod IP/port <pod-ip>:*, ssh user@host lines, pod ids, and camera LAN creds placeholders with placeholders like
   <droplet>, <jetson>, <pod>; same in status/ and briefs/. Do NOT move or rename status/ or briefs/ (agents write there live);
   instead add docs/how-we-built-it.md: the agent-team story (manager + 9 agents in tmux, briefs → status → merge), with links.
   Remove obviously useless clutter (stray __pycache__, temp files) and add a .gitignore.
6. Every relative link in README/AGENTS.md must resolve (check them).
Rules: no secrets; don't touch the camera, droplet services or other agents' code beyond sanitizing strings; no invented
numbers (source every number from status/*.md); ≤ 40 min. Write status/repo.md DONE with what changed + CI link.
