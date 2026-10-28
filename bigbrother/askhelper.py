"""Runs INSIDE netra-ask's venv as user netra (bigbrother/askdata.py starts it): reads the site file, zones, racks,
calibration and the bike log through netra-ask's own code, so Big Brother says exactly what /ask/sites shows.
Prints one JSON object. No writes. Usage: python askhelper.py <command> '<json args>'"""
import json
import subprocess
import sys

from ask import db, sitelayer, sitemap

TZ = "America/Los_Angeles"


def _sitefile(sid):
    return sitelayer.sitefile(sitemap.get_site(sid), TZ)


def _cams(sf, camera):
    out = []
    for c in sf["cameras"]:
        live = (c.get("source") or {}).get("camera_id")
        if camera in ("", None, c["id"], live):
            out.append((c, live))
    return out


def calibration(sid, camera=""):
    sf = _sitefile(sid)
    return {"site": sid, "cameras": [
        {"live_id": live, "site_camera_id": c["id"], "name": c["name"], "calibrated": c.get("calibrated"),
         "grade": (c.get("calibration") or {}).get("grade"), "reasons": (c.get("calibration") or {}).get("reasons"),
         "numbers": {k: v for k, v in ((c.get("calibration") or {}).get("numbers") or {}).items()
                     if k in ("n", "rms_px", "loo_median_m", "loo_max_m", "pitch", "height_m")}}
        for c, live in _cams(sf, camera)]}


def _rack_zone(f):
    """A rack point as a 1.5 m square zone, so sitelayer.camera_zones can project it like any zone."""
    lon, lat = f["geometry"]["coordinates"][:2]
    d_lat, d_lon = 0.75 / 111320, 0.75 / (111320 * 0.8412)          # ~cos(32.9 deg)
    ring = [[lon - d_lon, lat - d_lat], [lon + d_lon, lat - d_lat], [lon + d_lon, lat + d_lat],
            [lon - d_lon, lat + d_lat], [lon - d_lon, lat - d_lat]]
    p = f["properties"]
    return {"id": f["id"], "geometry": {"type": "Polygon", "coordinates": [ring]}, "z_base_m": p.get("z_base_m") or 0,
            "props": {"name": f["id"], "type": "bike_rack"}, "source": p.get("source"), "confidence": p.get("confidence")}


def shapes(sid, camera=""):
    sf = _sitefile(sid)
    feats = sf["features"]["features"]
    zones = [{"id": f["id"], "name": f["properties"]["props"].get("name"), "type": f["properties"]["props"].get("type"),
              "rules": f["properties"]["props"].get("rules") or [], "notes": f["properties"]["props"].get("notes"),
              "confidence": f["properties"].get("confidence")}
             for f in feats if f["properties"].get("kind") == "zone"]
    racks = [f for f in feats if f["properties"].get("kind") == "asset"
             and (f["properties"].get("props") or {}).get("type") == "bike_rack" and f["geometry"]["type"] == "Point"]
    cams = []
    for c, live in _cams(sf, camera):
        row = sitelayer.live_row(live) if live else None
        rack_view = []
        if row and row.get("fit") is not None and racks:
            pz = sitelayer.camera_zones(row, zones=[_rack_zone(f) for f in racks], levels={})
            props = {f["id"]: f["properties"]["props"] for f in racks}
            rack_view = [{"rack": z["feature_id"], "capacity": props[z["feature_id"]].get("capacity"),
                          "rack_type": props[z["feature_id"]].get("rack_type"),
                          "frame_area_pct": round(100 * _area(z["norm"]), 3)} for z in pz["zones"] if z["in_view"]]
        cams.append({"live_id": live, "site_camera_id": c["id"], "name": c["name"],
                     "calibration_grade": (c.get("calibration") or {}).get("grade"),
                     "jev_area": {"polygons": len(c.get("jev_area") or []),
                                  "points_norm": c.get("jev_area"), "drawn_by": c.get("jev_area_by"),
                                  "drawn_at": str(c.get("jev_area_at")) if c.get("jev_area_at") else None},
                     "site_zones_in_view": [{"id": z["id"], "name": z["name"], "type": z["type"],
                                             "rules": z.get("rules"), "frame_area_pct": round(100 * _area(z["norm"]), 2)}
                                            for z in c.get("zones") or [] if z.get("in_view")],
                     "site_zones_not_in_view": [z["id"] for z in c.get("zones") or [] if not z.get("in_view")],
                     "bike_racks_in_view": rack_view,
                     "rack_note": None if row and row.get("fit") is not None else "camera pose not fitted"})
    return {"site": sid, "site_zones": zones, "bike_racks_on_site": len(racks), "cameras": cams,
            "note": "rack-in-view uses the camera's fitted pose; a camera graded bad can be metres off (see calibration)"}


def _area(norm):
    if not norm or len(norm) < 3:
        return 0.0
    return abs(sum(norm[i][0] * norm[i - 1][1] - norm[i - 1][0] * norm[i][1] for i in range(len(norm)))) / 2


def bikelog(sid, day="today", hours=48):
    cmd = [sys.executable, "-m", "ask.bikelog", "today"] if day == "today" else \
          [sys.executable, "-m", "ask.bikelog", "summary", "--day", day]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    logged_in = db.q("""SELECT camera_id, zone, count(*) AS logged_in, min(parked_at) AS oldest, max(parked_at) AS newest
                        FROM rack_log GROUP BY 1, 2 ORDER BY 1, 2""")
    audit = db.q("""SELECT at, camera_id, kind, spot->>'id' AS spot, n_candidates, round(score::numeric, 2) AS score,
                           matched, flagged, (posted IS NOT NULL) AS posted
                    FROM rack_audit WHERE at > now() - make_interval(hours => %s) ORDER BY at DESC LIMIT 40""",
                 int(hours))
    return {"vocabulary": "login / logged in / registered / check-in = PARK; logout / took a bike = TAKE",
            "today_line": (p.stdout or p.stderr).strip()[-1500:],
            "logged_in_now": logged_in, "audit_recent": audit,
            "privacy": "no person data: times, cameras, spots and scores only"}


if __name__ == "__main__":
    cmd, args = sys.argv[1], json.loads(sys.argv[2] if len(sys.argv) > 2 else "{}")
    fn = {"calibration": calibration, "shapes": shapes, "bikelog": bikelog}[cmd]
    print(json.dumps(fn(**args), default=str))
