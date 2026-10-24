"""Police / uniformed-officer label per render track, from a real Jev call on the person crop (no hand labels).

  ~/netra/netra-ask/.venv/bin/python crimevid/police.py OUT/<clip>     # reads tracks.json, writes police.json

For each ByteTrack id in tracks.json, Jev is asked about a padded crop of that person when the track has been seen for
MIN_FRAMES frames with a box at least MIN_H px tall, and asked again whenever a later crop is >= REASK_GROW x larger in
area (a better look), at most MAX_ASKS times per track. Two noul questions per crop: is this a uniformed police officer
or security guard, and is this person visibly holding a weapon. police.json keeps every answer with the frame time it
was asked at, so the renderer only uses what was known by then."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path.home() / "netra/netra-ask"))
sys.path.insert(0, str(Path(__file__).parent))
from ask.dispatch.caption import crop_box  # noqa: E402
import cv2  # noqa: E402

from ask.dispatch.jev import Jev, JevError, jpeg  # noqa: E402
from render import FPS, frames  # noqa: E402

MIN_FRAMES, MIN_H, REASK_GROW, MAX_ASKS = 3, 40, 1.6, 4
LEAD = "`person` is a close crop of one person from a security camera (the person in the middle of the crop). "
QUESTIONS = {
    "police": {"type": "noul", "instructions": LEAD + "True if this person is a uniformed police officer or a uniformed "
               "security guard (police uniform, duty belt, badge, tactical vest or similar). False for anyone in "
               "ordinary clothes, including dark hoodies or jackets."},
    "armed": {"type": "noul", "instructions": LEAD + "True if this person is visibly holding a gun, knife or other "
              "weapon in their hand."},
}


def main(d: Path):
    tl = json.loads((d / "timeline.json").read_text())
    tracks = json.loads((d / "tracks.json").read_text())
    out = d / "police.json"
    jev = Jev()
    seen, asked, res = {}, {}, {}
    for k, (t, fr) in enumerate(frames(tl["path"], FPS)):
        if k >= len(tracks):
            break
        for tid, x1, y1, x2, y2, conf in tracks[k][1]:
            seen[tid] = seen.get(tid, 0) + 1
            h, area = y2 - y1, (x2 - x1) * (y2 - y1)
            if seen[tid] < MIN_FRAMES or h < MIN_H or len(res.get(tid, [])) >= MAX_ASKS:
                continue
            if tid in asked and area < REASK_GROW * asked[tid]:
                continue
            crop = crop_box(fr[:, :, ::-1], [x1, y1, x2, y2], pad=0.15)
            ch, cw = crop.shape[:2]
            if ch > 3 * cw:                          # a person cut by the frame edge: pad so Jev accepts the shape
                p = (ch // 3 - cw) // 2 + 1
                crop = cv2.copyMakeBorder(crop, 0, 0, p, p, cv2.BORDER_CONSTANT)
            try:
                a = jev.ask({"person": jpeg(crop, short=max(320, min(640, round(h))))}, QUESTIONS)
            except JevError as e:
                print(d.name, "track", tid, "jev failed:", e, flush=True)
                continue
            asked[tid] = area
            r = {"t": round(t, 3), "box": [x1, y1, x2, y2], "police": (a.get("police") or {}).get("noul"),
                 "armed": (a.get("armed") or {}).get("noul")}
            res.setdefault(tid, []).append(r)
            print(d.name, "track", tid, r, flush=True)
    usage = dict(jev.usage)
    out.write_text(json.dumps({"tracks": {str(k): v for k, v in res.items()}, "jev": usage,
                               "questions": QUESTIONS, "fps": FPS}))
    print(d.name, "tracks asked", len(res), "jev", usage)


if __name__ == "__main__":
    for a in sys.argv[1:]:
        main(Path(a))
