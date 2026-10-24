"""Annotated crimevid video from a run_demo.py timeline: what Sauron saw and decided, frame by frame.

  ~/sauron-venv/bin/python crimevid/render.py OUT/<clip>        # reads timeline.json, writes annotated.mp4 there

Two layers, both from our models, nothing hand-placed:
- person boxes + track ids on EVERY rendered frame: YOLO11s COCO (the edge weights) + ByteTrack, run here at FPS
  (cached in tracks.json). Display only — the decisions come from the pipeline layer.
- the pipeline layer, straight from timeline.json (netra-ask dispatch Watcher, replay): every Jev strip's facts, E and
  verdict at its frame time, the incident's subject track (Jev box snapped to the gate's YOLO person) and caption, and
  the first deploy/urgent strip = the drone launch.
The timeline strip under the video marks the human-labelled event window against the deploy time."""
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FPS = 12
POLICE_P = 0.5                               # police.py answer at or above this = police officer
VH, HUD_W, TL_H = 540, 400, 110
WALL0 = 1_800_000_000                        # run_demo.py replays at wall = WALL0 + stream time
FACTS = ["break_in", "theft", "tampering", "trespass", "vandalism", "weapon", "violence", "menace", "normal"]
VCOL = {"none": (120, 120, 120), "watch": (240, 170, 30), "deploy": (230, 50, 40), "urgent": (220, 30, 160)}
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
f = {s: ImageFont.truetype(FONT, s) for s in (11, 13, 15, 18)}
fb = {s: ImageFont.truetype(BOLD, s) for s in (12, 14, 16, 20, 26, 30)}


def frames(path, fps):
    """(t, rgb frame) at `fps`, decoded by ffmpeg (YouTube AV1/VP9 is beyond OpenCV's build)."""
    w, h = map(int, subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                    "stream=width,height", "-of", "csv=p=0", path],
                                   capture_output=True, text=True, check=True).stdout.strip().split(",")[:2])
    p = subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-i", path, "-vf", f"fps={fps}",
                          "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"], stdout=subprocess.PIPE)
    i = 0
    while True:
        b = p.stdout.read(w * h * 3)
        if len(b) < w * h * 3:
            break
        yield i / fps, np.frombuffer(b, np.uint8).reshape(h, w, 3)
        i += 1
    p.wait()


def track(path, out: Path, weights: str):
    """YOLO11s person boxes + ByteTrack ids for every frame at FPS -> tracks.json [[t, [[id, x1, y1, x2, y2, conf]]]]."""
    if out.exists():
        return json.loads(out.read_text())
    from ultralytics import YOLO
    m = YOLO(weights)
    res = []
    for t, fr in frames(path, FPS):
        r = m.track(fr[:, :, ::-1], persist=True, classes=[0], conf=0.25, imgsz=960, tracker="bytetrack.yaml",
                    verbose=False)[0]
        ps = []
        if r.boxes is not None and r.boxes.id is not None:
            for (x1, y1, x2, y2), c, i in zip(r.boxes.xyxy.tolist(), r.boxes.conf.tolist(), r.boxes.id.tolist()):
                ps.append([int(i), *[round(v, 1) for v in (x1, y1, x2, y2)], round(c, 3)])
        res.append([round(t, 3), ps])
    out.write_text(json.dumps(res))
    return res


def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - ix * iy
    return ix * iy / u if u > 0 else 0.0


def stream_t(iso):
    return datetime.fromisoformat(iso).timestamp() - WALL0


def bar(d, x, y, w, h, v, col, bg=(45, 45, 50)):
    d.rectangle([x, y, x + w, y + h], fill=bg)
    d.rectangle([x, y, x + max(1, int(w * min(1.0, v))), y + h], fill=col)


def wrap(d, text, font, width):
    lines, cur = [], ""
    for word in text.split():
        nxt = (cur + " " + word).strip()
        if d.textlength(nxt, font=font) > width and cur:
            lines.append(cur)
            cur = word
        else:
            cur = nxt
    return lines + ([cur] if cur else [])


def render(d: Path, weights: str):
    tl = json.loads((d / "timeline.json").read_text())
    W, H, dur = tl["w"], tl["h"], tl["duration"]
    s = VH / H
    vw = int(round(W * s / 2) * 2)
    CW, CH = vw + HUD_W, VH + TL_H
    tracks = track(tl["path"], d / "tracks.json", weights)
    strips = tl["strips"]
    pol = tl["policy"]
    dep = tl["deploy_t"]
    ev0, ev1 = tl["event_s"], tl["event_end_s"]
    inc = tl["incidents"][0] if tl["incidents"] else None
    # the incident's subject over time: (stream t, box) from the record's track (Jev box snapped to a gate person)
    subj = [(stream_t(p["at"]), p["box"]) for p in (inc or {}).get("track", [])]
    inc_t0 = stream_t(inc["opened_at"]) if inc else None
    inc_t1 = stream_t(inc["closed_at"]) if inc and inc.get("closed_at") else dur
    # police per render track (police.py: Jev on the person crop); only answers asked at or before t are used
    pj = json.loads((d / "police.json").read_text())["tracks"] if (d / "police.json").exists() else {}

    def cop(tid, t):
        """(police p, armed p) from the newest Jev answer for this track asked by time t, else (None, None)."""
        a = [r for r in pj.get(str(tid), []) if r["t"] <= t + 1e-6]
        return (a[-1]["police"], a[-1]["armed"]) if a else (None, None)

    def is_cop(tid, t):
        return (cop(tid, t)[0] or 0.0) >= POLICE_P

    summ = {"police_tracks": sorted(int(k) for k, v in pj.items() if any((r["police"] or 0) >= POLICE_P for r in v)),
            "police_first_t": None, "police_in_view_at_deploy": False, "subject_resnapped_s": 0.0, "no_suspect_s": 0.0}
    last_sid = None
    emax = pol["urgent_e"] * 1.4                  # E bar/plot scale; E above it pins to the top
    dep_id = None
    enc = subprocess.Popen(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                            "-s", f"{CW}x{CH}", "-r", str(FPS), "-i", "pipe:0", "-c:v", "libx264", "-preset", "medium",
                            "-crf", "27", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(d / "annotated.mp4")],
                           stdin=subprocess.PIPE)
    for k, (t, fr) in enumerate(frames(tl["path"], FPS)):
        people = tracks[k][1] if k < len(tracks) else []
        st = [x for x in strips if x["t"] <= t + 1e-6]
        cur = st[-1] if st else None
        img = Image.new("RGB", (CW, CH), (18, 18, 22))
        img.paste(Image.fromarray(fr).resize((vw, VH), Image.BILINEAR), (0, 0))
        g = ImageDraw.Draw(img)
        # subject: newest record track point at or before t, while the incident is open
        sbox, sid, no_suspect = None, None, False
        cops = {p[0] for p in people if is_cop(p[0], t)}
        if cops and summ["police_first_t"] is None:
            summ["police_first_t"] = round(t, 2)
        if inc and subj and subj[0][0] <= t + 1e-6 and t <= inc_t1:
            sbox = [b for (ts, b) in subj if ts <= t + 1e-6][-1]
            best = max(people, key=lambda p: iou(p[1:5], sbox), default=None)
            if best is not None and iou(best[1:5], sbox) >= 0.2:
                sid = best[0]
            on_cop = sid in cops or (sid is None and any(iou(p[1:5], sbox) >= 0.2 for p in people if p[0] in cops))
            if on_cop:                                # never a police officer: keep the last suspect, else the nearest civilian
                civ = [p for p in people if p[0] not in cops]
                if any(p[0] == last_sid for p in civ):
                    sid = last_sid
                elif civ:
                    cx, cy = (sbox[0] + sbox[2]) / 2, (sbox[1] + sbox[3]) / 2
                    sid = min(civ, key=lambda p: ((p[1] + p[3]) / 2 - cx) ** 2 + ((p[2] + p[4]) / 2 - cy) ** 2)[0]
                else:
                    sid, no_suspect = None, True
                summ["subject_resnapped_s"] += 1 / FPS
                if no_suspect:
                    summ["no_suspect_s"] += 1 / FPS
            if sid is not None:
                last_sid = sid
        for p in people:
            x1, y1, x2, y2 = [v * s for v in p[1:5]]
            is_s, is_p = p[0] == sid, p[0] in cops
            col = (255, 40, 40) if is_s else (40, 110, 255) if is_p else (60, 220, 255)
            g.rectangle([x1, y1, x2, y2], outline=col, width=4 if is_s or is_p else 2)
            lab = (f"SUSPECT #{p[0]}" if is_s else f"POLICE #{p[0]} {cop(p[0], t)[0]:.2f}" if is_p
                   else f"person #{p[0]} {p[5]:.2f}")
            tw = g.textlength(lab, font=fb[12])
            g.rectangle([x1, y1 - 17, x1 + tw + 8, y1], fill=col)
            g.text((x1 + 4, y1 - 16), lab, font=fb[12], fill=(255, 255, 255) if is_p else (0, 0, 0))
        if sbox is not None and sid is None and not no_suspect and not any(iou(p[1:5], sbox) >= 0.2 for p in people):             # subject box from the pipeline with no matching render track
            x1, y1, x2, y2 = [v * s for v in sbox]
            g.rectangle([x1, y1, x2, y2], outline=(255, 40, 40), width=3)
            g.rectangle([x1, y1 - 17, x1 + 70, y1], fill=(255, 40, 40))
            g.text((x1 + 4, y1 - 16), "SUSPECT", font=fb[12], fill=(0, 0, 0))
        # deploy banner: 3 s big, then a persistent tag
        if dep is not None and t >= dep:
            if dep_id is None:
                dep_id = sid if sid is not None else (-1 if no_suspect else None)
                summ["police_in_view_at_deploy"] = bool(cops)
            who = f"suspect #{dep_id}" if dep_id not in (None, -1) else "no suspect in view" if dep_id == -1 else "suspect"
            if t < dep + 3.0:
                txt = f"SAURON: DEPLOY DRONE → {who}"
                tw = g.textlength(txt, font=fb[26])
                bx = (vw - tw) / 2
                g.rectangle([bx - 16, 14, bx + tw + 16, 60], fill=(200, 20, 20), outline=(255, 255, 255), width=2)
                g.text((bx, 22), txt, font=fb[26], fill=(255, 255, 255))
            else:
                txt = f"DRONE DEPLOYED at {dep:.1f} s → {who}"
                g.rectangle([8, 8, 16 + g.textlength(txt, font=fb[14]), 30], fill=(200, 20, 20))
                g.text((12, 10), txt, font=fb[14], fill=(255, 255, 255))
        g.rectangle([vw - 74, VH - 24, vw, VH], fill=(0, 0, 0))
        g.text((vw - 68, VH - 21), f"{t:5.1f} s", font=fb[14], fill=(255, 255, 255))
        # HUD
        x0 = vw + 16
        g.text((x0, 10), "SAURON  live judge", font=fb[20], fill=(255, 255, 255))
        g.text((x0, 36), tl["title"][:44], font=f[13], fill=(190, 190, 200))
        v = cur["verdict"] if cur else "none"
        g.rectangle([x0, 60, CW - 16, 104], fill=VCOL[v])
        g.text((x0 + 12, 66), {"none": "NO ACTION", "watch": "WATCH", "deploy": "DEPLOY DRONE",
                               "urgent": "URGENT — DEPLOY"}[v], font=fb[26], fill=(255, 255, 255))
        e = cur["e"] if cur else 0.0
        g.text((x0, 114), f"evidence E = {e:.2f}", font=fb[16], fill=(255, 255, 255))
        if cur:
            g.text((x0 + 200, 116), f"why: {cur['why']}", font=f[13], fill=(200, 200, 210))
        bw = CW - 16 - x0
        bar(g, x0, 138, bw, 14, e / emax, VCOL[v])
        for j, (name, key) in enumerate((("watch", "watch_e"), ("deploy", "deploy_e"), ("urgent", "urgent_e"))):
            tx = x0 + bw * pol[key] / emax
            g.line([tx, 134, tx, 156], fill=(255, 255, 255), width=1)
            g.text((tx - (g.textlength(name, font=f[11]) if j == 0 else 0) - 2 * (j == 0) + 2 * (j > 0), 158), name,
                   font=f[11], fill=(170, 170, 180))
        g.text((x0, 180), "Jev facts (newest 4-frame strip, every 2 s)", font=fb[12], fill=(200, 200, 210))
        for i, name in enumerate(FACTS):
            y = 200 + i * 19
            p = cur["facts"][name] if cur else 0.0
            g.text((x0, y), name.replace("_", "-"), font=f[13], fill=(220, 220, 225))
            col = (90, 170, 90) if name == "normal" else ((230, 70, 50) if p >= pol["danger_p"] else (170, 120, 60))
            bar(g, x0 + 92, y + 3, bw - 140, 11, p, col)
            g.text((CW - 44, y), f"{p:.2f}", font=f[13], fill=(220, 220, 225))
        y = 200 + len(FACTS) * 19 + 4
        if cur and cops and cur["facts"]["weapon"] >= 0.3:
            armed = [(c, cop(c, t)[1] or 0.0) for c in sorted(cops)]
            sa = cop(sid, t)[1] if sid is not None else None
            note = "weapon: police officer " + ", ".join(f"#{c} (armed {a:.2f})" for c, a in armed[:2])
            if sa is not None:
                note += f"; suspect armed {sa:.2f}"
            for j, line in enumerate(wrap(g, note, fb[12], bw)[:2]):
                g.text((x0, y + j * 15), line, font=fb[12], fill=(110, 160, 255))
            y += 32
        else:
            y += 4
        if inc and t >= inc_t0 and inc.get("caption_text"):
            g.text((x0, y), "Jev caption (incident subject)", font=fb[12], fill=(200, 200, 210))
            for j, line in enumerate(wrap(g, inc["caption_text"], f[13], bw)[:6]):
                g.text((x0, y + 18 + j * 17), line, font=f[13], fill=(255, 235, 200))
        g.text((x0, VH - 40), f"strips so far: {len(st)}   people now: {len(people)} (police {len(cops)})", font=f[11], fill=(150, 150, 160))
        g.text((x0, VH - 24), "YOLO11s person tracks; Jev judge + deployed policy", font=f[11], fill=(150, 150, 160))
        # timeline strip
        ty, lx, rx = VH + 10, 16, CW - 16
        X = lambda tt: lx + (rx - lx) * tt / max(dur, 1e-6)       # noqa: E731
        g.text((lx, ty), "timeline", font=fb[12], fill=(200, 200, 210))
        py0, py1 = ty + 18, ty + 66                               # E plot band
        g.rectangle([lx, py0, rx, py1], fill=(30, 30, 36))
        if ev0 is not None:
            g.rectangle([X(ev0), py0, X(ev1 if ev1 is not None else dur), py1], fill=(40, 90, 50))
            g.text((X(ev0) + 3, py0 + 1), "crime (human label)", font=f[11], fill=(170, 230, 170))
        ey = lambda ee: py1 - (py1 - py0) * min(1.0, ee / emax)  # noqa: E731
        for key in ("deploy_e",):
            g.line([lx, ey(pol[key]), rx, ey(pol[key])], fill=(120, 60, 60), width=1)
        pts = [(X(x["t"]), ey(x["e"])) for x in strips if x["t"] <= t + 1e-6]
        if len(pts) > 1:
            g.line(pts, fill=(255, 255, 255), width=2)
        for x in strips:
            if x["t"] <= t + 1e-6:
                g.ellipse([X(x["t"]) - 3, ey(x["e"]) - 3, X(x["t"]) + 3, ey(x["e"]) + 3], fill=VCOL[x["verdict"]])
        if dep is not None:
            g.line([X(dep), py0 - 4, X(dep), py1 + 4], fill=(255, 60, 60), width=3)
            lab = f"deploy {dep:.1f} s" + (f"  (+{dep - ev0:.1f} s after crime start)" if ev0 is not None else "")
            lx2 = min(X(dep) + 4, rx - g.textlength(lab, font=fb[12]))
            g.text((lx2, py1 + 6), lab, font=fb[12], fill=(255, 90, 90))
        else:
            g.text((lx, py1 + 6), "no deploy in this clip", font=fb[12], fill=(160, 200, 160) if ev0 is None else (255, 170, 60))
        g.line([X(t), py0 - 6, X(t), py1 + 2], fill=(255, 255, 0), width=2)
        enc.stdin.write(img.tobytes())
    enc.stdin.close()
    enc.wait()
    summ["subject_resnapped_s"] = round(summ["subject_resnapped_s"], 1)
    summ["no_suspect_s"] = round(summ["no_suspect_s"], 1)
    summ["deploy_suspect"] = dep_id
    (d / "police_summary.json").write_text(json.dumps(summ))
    print(d.name, summ)
    print(d / "annotated.mp4", subprocess.run(["du", "-h", str(d / "annotated.mp4")], capture_output=True, text=True).stdout.split()[0])


if __name__ == "__main__":
    for a in sys.argv[1:]:
        render(Path(a), str(Path.home() / "sauron-data/yolo11s.pt"))
