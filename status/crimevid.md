DONE — page https://claude.ai/artifact/HAjU6Ncdn3FY9ci6hzzrrf (private; William shares it). 5/5 crimes ended in a drone deploy, 0/2 benign clips deployed. Hero = fence-climb (+3.5 s on clean CCTV). Jev total $0.054.

| clip (clean source?) | crime window | deploy at | from crime start | police |
|---|---|---|---|---|
| atm-rip (clean CCTV, trimmed to 1 camera) | 4–40 s | 7.5 s | +3.5 s | none |
| fence-climb HERO (clean CCTV) | 0–12 s | 3.5 s | +3.5 s | none |
| bike-lock (news banner cropped) | 2–12 s | 7.5 s | +5.5 s | officers from 11.5 s; deploy came before them; the urgent escalation at 15.5 s is the arrest |
| catalytic (clean CCTV) | 2–62 s | 13.5 s | +11.5 s (slow) | none |
| car-breakin (app icons + editor box cut; night, tiny) | 7–29 s | 19.5 s | +12.5 s (slow) | none |
| owner-car-1 (MEVA, benign) | — | never (E 0.00) | — | — |
| owner-car-2 (MEVA, benign) | — | never (E 0.00) | — | — |

- Videos: ~/sauron-data/crimevid/out/<clip>/annotated.mp4, each opened on William's screen as Downloads/sauron-<clip>.mp4 (catalytic and the old bike-lock were copied there earlier). R2: netra-lake/_work/hackathon/crimevid/<clip>/{annotated.mp4,timeline.json,tracks.json}.
- Pipeline: netra-ask main dispatch Watcher in replay, nothing posted; droplet untouched. Default PolicyConfig, with judge.py byte-identical to the jetson-cloud deploy. No per-clip tuning.
- Police: Jev yes/no per tracked-person crop (crimevid/police.py). Police drawn blue, never picked as suspect; the weapon fact is attributed to officers in the HUD.
- Crop/cut is done on the source before the models run (crimevid/prep.sh).
- Code: Netra-Internal/sauron-hackathon branch hack-crimevid, crimevid/ (run.sh, prep.sh, render.py, police.py, page.py, upload_r2.py).
- PTZ: crimevid sent NO commands to the Axis PTZ, ever. Only read-only ssh to jetson-cloud (md5sum, systemctl cat, env read) at ~15:30.
- Side effect: ultralytics auto-installed `lap` into ~/sauron-venv (needed for ByteTrack).
