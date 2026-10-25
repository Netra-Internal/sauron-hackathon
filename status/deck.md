DONE: Sauron hackathon deck (12 slides, crimevid final results in, claude.ai Slides artifact, private, not shared): https://claude.ai/artifact/DYN11dp3UtpFUi8ic2Pn7n

## What's in it
1 cover (SAURON — sees, judges, sends a drone) · 2 problem · 3 what we built today (6-step chain) · 4 architecture (camera → Jetson capture → RunPod A5000 $0.27/h → droplet → /hack/ + droplink; edge→cloud cutover 22:19 UTC)
5 live /hack/ screenshot (plans/dash-live.png, 4:25 PM) · 6 crime hero: fence-climb still, +3.5 s, 5/5 crimes deployed, 0/2 benign · 7 every clip: status/crimevid.md table (7 rows)
8 judge: facts → policy → verdict (catalytic still) · 9 person → coordinate (plans/calib-camera.png, ±6.6 m LOO median, worst 21.7 m, test rig) · 10 measured numbers · 11 what's next · 12 close (team: Pranay CEO, Landon CTO, William COO)
Speaker notes on every slide. Look: near-black, one ember accent (#FF6A1A), Space Grotesk + IBM Plex Mono. Downloads as .pptx / PDF from the page.

## Exported files (William's Windows Documents; not redirected to OneDrive: HKCU User Shell Folders Personal = %USERPROFILE%\Documents)
- /mnt/c/Users/<user>/Documents/Sauron-Hackathon-Deck.pptx  (%USERPROFILE%\Documents\Sauron-Hackathon-Deck.pptx) 12 slides, speaker notes on all 12
- /mnt/c/Users/<user>/Documents/Sauron-Hackathon-Deck.pdf   (%USERPROFILE%\Documents\Sauron-Hackathon-Deck.pdf) 12 pages
- How: the Playwright browser is not signed in to claude.ai, so the page's own Export couldn't be used. I rendered the 11 slide files locally
  in headless Chromium at 1920x1080 and built the PDF and pptx from those renders. The pptx slides are PICTURES (text not editable); for an
  editable pptx, William can use Export on the artifact page. I checked the renders (re-exported 16:59 PDT after the crimevid update): nothing overflows.

## Numbers and where they come from
- crime: status/crimevid.md (DONE) table, verbatim: atm-rip +3.5, fence-climb +3.5 (hero), bike-lock +5.5 (police from 11.5 s, after deploy),
  catalytic +11.5 (slow), car-breakin +12.5 (slow), owner-car-1/2 never (E 0.00). Jev $0.054. Page: https://claude.ai/artifact/HAjU6Ncdn3FY9ci6hzzrrf
- launch: status/launch.md (click → droplink 2.78 s, click → netra-ask 0.79 s, abort ordering end → closed → abort).
- PTZ ~0.5 s median: status/ptz.md. Pod 5 fps / 40-43 ms (Axis), 34-46 ms vs Jetson 75-86 ms, HLS cold start 0.78-1.57 s: status/cloud.md.
- Box lag 2.9-6.4 s: status/boxes.md. Calibration: status/calib.md + calib-camera.png.

## Not done / notes
- Only read files; no camera, droplet or other agents' files touched.
- William must share it from the page's Share menu before anyone else can open it.

## Repo push (manager: one repo for the whole project)
PUSHED c849f68 (Netra-Internal/sauron-hackathon, branch hack-deck)
- deck/: README.md, project/deck.json + project/slides/*.html (the deck's own source, 12 slides, speaker notes in <aside>),
  img/ (the exact 5 images the deck shows: 4:25 PM /hack/ screenshot, calib-camera, 3 crime stills), export.py (headless Chromium
  render -> PDF + picture pptx), .gitignore for its outputs.
- Verified: `python deck/export.py deck` from the repo root builds 12 slides; output matches the files in Documents (same size; only the PDF timestamp differs).
- Nothing deployed by deck; no units, nginx, env or secrets involved.

## Public-repo cleanup (manager FYI: no hosts)
PUSHED da4021c: repo slide copies (live, close) now say `<dashboard-host>/hack/`; status paths use `<user>` / %USERPROFILE%. No IPs, pod ids or creds anywhere in deck/ (git grep checked).
- NOT fixed: the hostname internal.netralabs.net and the Windows username are still in OLDER commits (b13ae99 and earlier status commits),
  which are already merged into origin/main and other branches. Removing them needs a history rewrite of main: manager's call, I did not force-push.
- The published deck and the .pptx/.pdf in Documents still show the real dashboard address (private, for the talk).
