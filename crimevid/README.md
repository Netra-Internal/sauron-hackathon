# crimevid — Sauron on real crime footage (hackathon, Oct 24 2026)

Real CCTV crime clips run through the real netra-ask dispatch pipeline (main) with the deployed default policy, then
rendered as annotated videos. Result page: https://claude.ai/artifact/HAjU6Ncdn3FY9ci6hzzrrf
(5/5 crimes deployed, 0/2 benign; fastest +3.5 s after the crime starts on clean CCTV).

| step | file | what it does |
|---|---|---|
| 1 | `prep.sh` | Cleans sources before any model runs: crops news banners and app icons, cuts editor marks and camera switches. Output goes to `~/sauron-data/crimevid/src/`. |
| 2 | `run.sh` | Per clip, one CPU model job at a time: netra-ask `tools/dispatch-eval/demo/run_demo.py` (Watcher in replay, nothing posted, PersonGate YOLO11s, Jev strip every 2 s, default `PolicyConfig`) → `render.py` (tracks) → `police.py` → `render.py` again. Then it opens the mp4 on William's screen (Downloads/sauron-<clip>.mp4). |
| 3 | `render.py` | Annotated MP4: YOLO11s + ByteTrack person boxes on every frame at 12 fps, POLICE in blue (never the suspect), the incident's suspect in red, a HUD with Jev facts / E / verdict / caption, a deploy banner at the policy's deploy time, and a timeline of the human-labelled crime window vs the deploy. |
| 4 | `police.py` | Police label per track: Jev yes/no on the person crop (uniformed police/security? holding a weapon?), cached per track, re-asked when the crop gets ≥1.6× larger. |
| 5 | `page.py` + `page.tpl.html` + `summary.html` | Builds the artifact page (videos + results table) from the timelines. |
| 6 | `upload_r2.py` | Uploads annotated.mp4 / timeline.json / tracks.json to `netra-lake/_work/hackathon/crimevid/<clip>/`. Creds are read from `netra-training/.env`; none are stored here. |

Needs: `~/netra/netra-ask` (main) with its .venv and `~/work/ask/models/yolo11s-1280.onnx`; `~/sauron-venv` (ultralytics,
PIL); `~/sauron-data/yolo11s.pt`; a Jev key in `~/.config/netra/typesafe.env` (`TYPESAFE_API_KEY=<your key>`).
Clips: `~/sauron-data/dispatch-clips/yt/` (YouTube CCTV; sources in page.py `SRC`) and MEVA `~/sauron-data/lockneg/seg/`.

    ./crimevid/prep.sh && ./crimevid/run.sh
    python3 crimevid/page.py ~/sauron-data/crimevid/out /tmp/page      # then publish /tmp/page/index.html + v/*.mp4

Nothing is deployed and no units or nginx changes were made. The policy match was checked read-only against the edge host (`<edge-host>`); nothing here connects to a host.
