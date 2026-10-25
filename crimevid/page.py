"""crimevid artifact page from the run outputs: videos + per-clip results, all numbers read from timeline.json.

  python3 crimevid/page.py OUT PAGE_DIR      # writes PAGE_DIR/index.html and copies videos to PAGE_DIR/v/<id>.mp4"""
import html
import json
import shutil
import sys
from pathlib import Path

PREP = {   # what prep.sh removed before the models saw the clip
    "bike-lock": "Cropped to the top 1280×500 to remove the news lower third and inset (the CCTV date stamp under it goes too).",
    "car-breakin": "Cut the first 1.0 s (an editor's highlight box) and cropped the camera-app icons off the right edge.",
    "atm-rip": "Trimmed to the first camera (0–41 s); the upload then cuts to a second angle.",
}
ORDER = ["bike-lock", "catalytic", "atm-rip", "car-breakin", "fence-climb", "owner-car-1", "owner-car-2"]
SRC = {   # where each clip comes from, what happens (human label notes, ~/sauron-data/dispatch-clips/event-labels.json)
    "bike-lock": ("https://www.youtube.com/watch?v=Z-5VBVAGUME", "News-chyroned CCTV: hooded man works a bike lock with a tool outside a police building; officers walk in at ~12 s and take him down."),
    "catalytic": ("https://www.youtube.com/watch?v=93r5PSP2rI4", "Overhead driveway camera: a man with a cordless saw cuts under a parked Prius, an accomplice lies under the car 24-58 s, both leave with the tool at 60-62 s."),
    "atm-rip": ("https://www.youtube.com/watch?v=wWEHimK-bNw", "Hooded men chain an ATM to a pickup and rip its front panel off (panel flies at 14 s); cut to another angle at 42 s."),
    "car-breakin": ("https://www.youtube.com/watch?v=LNA3EOR2W6c", "Night lot camera: a person rummages inside the open door of a pickup in the background (8-30 s), then walks to the foreground cars. Small and hard to read."),
    "fence-climb": ("https://www.youtube.com/watch?v=DzQTLgqtWmY", "Man climbs a wooden fence (0-4 s), falls with the sign (6-8 s), climbs at it again (10-12 s), walks off."),
    "owner-car-1": ("https://mevadata.org", "MEVA KF1 outdoor CCTV, camera G340 parking lot: a person walks to their own car and opens it. No crime."),
    "owner-car-2": ("https://mevadata.org", "MEVA KF1 outdoor CCTV, camera G505 parking lot: a person walks to their own car and opens it. No crime."),
}


def esc(s):
    return html.escape(str(s))


def main(out: Path, page: Path):
    (page / "v").mkdir(parents=True, exist_ok=True)
    rows, cards, total_tok = [], [], 0
    n_crime = n_caught = n_benign = n_fp = 0
    def speed(cid):  # fastest true catches first, then slower/missed crimes, benign clips last
        t = json.loads((out / cid / "timeline.json").read_text())
        if t["label"] != "crime":
            return (2, 0)
        return (0, t["deploy_after_act_s"]) if t["deploy_t"] is not None else (1, 0)
    for cid in sorted((c for c in ORDER if (out / c / "annotated.mp4").exists()), key=speed):
        d = out / cid
        tl = json.loads((d / "timeline.json").read_text())
        shutil.copy(d / "annotated.mp4", page / "v" / f"{cid}.mp4")
        url, what = SRC[cid]
        tok = tl["stats"]["jev"]["input_tokens"]
        if (d / "police.json").exists():                 # the police-label calls count too
            tok += json.loads((d / "police.json").read_text())["jev"]["input_tokens"]
        total_tok += tok
        dep, ev0, ev1 = tl["deploy_t"], tl["event_s"], tl["event_end_s"]
        verdicts = [s["verdict"] for s in tl["strips"]]
        ps = json.loads((d / "police_summary.json").read_text()) if (d / "police_summary.json").exists() else {}
        urg = next((x for x in tl["strips"] if x["verdict"] == "urgent"), None)
        dstrip = next((x for x in tl["strips"] if x["verdict"] in ("deploy", "urgent")), None)
        pf = ps.get("police_first_t")
        if not ps.get("police_tracks"):
            pnote = "none seen"
        else:
            pnote = f"officers in view from {pf:.1f} s. "
            if dep is not None and ps.get("police_in_view_at_deploy"):
                pnote += (f"Deploy ({dstrip['why']}) fired with police in view, so police may have driven it. "
                          if dstrip["why"] in ("weapon", "violence", "menace") else
                          f"Police were in view at the deploy, but it fired on {dstrip['why']}. ")
            elif dep is not None:
                pnote += f"Deploy ({dstrip['why']}) came before any police were in view. "
            if urg is not None and pf is not None and urg["t"] >= pf:
                pnote += f"The urgent escalation at {urg['t']:.1f} s ({urg['why']}) came after police arrived and reflects the arrest."
        pnote = pnote.strip()
        top = "urgent" if "urgent" in verdicts else "deploy" if "deploy" in verdicts else "watch" if "watch" in verdicts else "none"
        if tl["label"] == "crime":
            n_crime += 1
            caught = dep is not None and dep <= (ev1 if ev1 is not None else tl["duration"]) + 4
            n_caught += caught
            early = dep is not None and dep < ev0 - 2
            res = (f'<span class="pill ok">caught</span>' if caught and not early else
                   f'<span class="pill warn">early</span>' if early else
                   f'<span class="pill bad">late</span>' if dep is not None else '<span class="pill bad">missed</span>')
            lat = "—" if dep is None else f"{dep - ev0:+.1f} s"
            fp = "1 (before the act)" if early else "0"
        else:
            n_benign += 1
            n_fp += dep is not None
            res = '<span class="pill bad">false deploy</span>' if dep is not None else '<span class="pill ok">stayed quiet</span>'
            lat, fp = "—", "1" if dep is not None else "0"
        win = "none (benign)" if ev0 is None else f"{ev0:g}–{ev1:g} s"
        rows.append(f"<tr><td><a href=\"#{cid}\">{esc(tl['title'])}</a></td><td>{esc(tl['label'])}</td><td class=n>{win}</td>"
                    f"<td class=n>{'—' if dep is None else f'{dep:.1f} s'}</td><td class=n>{lat}</td><td>{res}</td>"
                    f"<td>{top}</td><td class=n>{fp}</td><td class=wrap>{esc(pnote)}</td></tr>")
        cap = tl["incidents"][0].get("caption_text") if tl["incidents"] else None
        cards.append(f"""<section class="clip" id="{cid}">
  <h3>{esc(tl['title'])} {res}</h3>
  <video src="v/{cid}.mp4" controls muted playsinline preload="metadata"></video>
  <dl>
    <div><dt>What happens</dt><dd>{esc(what)}</dd></div>
    <div><dt>Source</dt><dd><a href="{url}">{esc(url)}</a></dd></div>
    <div><dt>Crime window (human label)</dt><dd>{win}</dd></div>
    <div><dt>Deploy</dt><dd>{'never' if dep is None else f'{dep:.1f} s' + ('' if ev0 is None else f' ({dep - ev0:+.1f} s from crime start)')}; highest verdict {top}</dd></div>
    <div><dt>Police</dt><dd>{esc(pnote)}</dd></div>
    {f'<div><dt>Cleaned before the models</dt><dd>{esc(PREP[cid])}</dd></div>' if cid in PREP else ''}
    {f'<div><dt>Jev caption</dt><dd>{esc(cap)}</dd></div>' if cap else ''}
  </dl>
</section>""")
    cost = total_tok * 0.042 / 1e6
    return rows, cards, dict(n_crime=n_crime, n_caught=n_caught, n_benign=n_benign, n_fp=n_fp, cost=cost, tok=total_tok)


if __name__ == "__main__":
    out, page = Path(sys.argv[1]), Path(sys.argv[2])
    rows, cards, s = main(out, page)
    tpl = (Path(__file__).parent / "page.tpl.html").read_text()
    (page / "index.html").write_text(tpl.replace("{{ROWS}}", "\n".join(rows)).replace("{{CARDS}}", "\n".join(cards))
                                     .replace("{{CAUGHT}}", f"{s['n_caught']} of {s['n_crime']}")
                                     .replace("{{FP}}", f"{s['n_fp']} of {s['n_benign']}")
                                     .replace("{{COST}}", f"${s['cost']:.2f}")
                                     .replace("{{SUMMARY}}", (Path(__file__).parent / "summary.html").read_text()))
    print(s)
