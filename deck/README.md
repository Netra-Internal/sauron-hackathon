# deck — Sauron hackathon slide deck

The 12-slide deck for the Oct 24 2026 demo, made as a claude.ai **Slides** artifact:
https://claude.ai/artifact/DYN11dp3UtpFUi8ic2Pn7n (private; share from the page).
Exports in William's Documents: `Sauron-Hackathon-Deck.pptx` / `.pdf`.

- `project/deck.json` + `project/slides/<id>.html`: the deck's own source files, as published to the artifact
  (Slides type format: one `<section>` per slide, inline styles, speaker notes in `<aside>`).
  Images are artifact assets (`/_blob/<id>`): `plans/dash-live.png`, `plans/calib-camera.png` and the crime stills in `img/`
  (frames from `~/sauron-data/crimevid/out/<clip>/annotated.mp4` at the deploy moment).
- `export.py`: renders each slide in headless Chromium at 1920x1080 and builds a PDF and a picture-per-slide .pptx with the notes.
  `python export.py <dir>`, where `<dir>` holds `deck/project/` and `img/` (needs python-pptx + Pillow, playwright's chromium-1247).
  The pptx text isn't editable; the page's own Export gives an editable one.

Every number on the slides comes from `status/*.md` (sources listed in `status/deck.md`). No secrets in this folder.
