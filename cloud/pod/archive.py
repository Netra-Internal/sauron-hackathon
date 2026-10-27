"""Copy closed ring segments to R2 so footage outlives the pod's ring (EDGE_RING_MAX_GB, ~1 day at 0.8 GB/h).

Every ARCHIVE_EVERY_S (1 h) for each camera in /workspace/edge/archive_cams: every <epoch>.mkv in the camera's ring except
the newest two (ask/edge/ring.py never prunes those either; one may still be open), oldest first, is PUT to
netra-lake _ephemeral/footage/<camera>/<UTC date of epoch>/<epoch>.mkv and then HEADed: done only when R2's Content-Length
equals the local size. Done files are listed in /workspace/edge/archive/<camera>.done ("name size"), so a restart resumes.
R2 deletes them 12 days after upload (bucket lifecycle rule on _ephemeral/footage/). The local ring is left alone.
URLs come from the droplet's presigner (cloud/droplet/presign.py) on 127.0.0.1:8472, which the droplet's
netra-cloud-presign-tunnel forwards here: the pod holds no R2 keys."""
from __future__ import annotations

import os
import subprocess
import time
import urllib.parse
import urllib.request

W = "/workspace/edge"
RING = os.environ.get("EDGE_RING_ROOT", f"{W}/ring")
PRESIGN = os.environ.get("ARCHIVE_PRESIGN", "http://127.0.0.1:8472")
EVERY_S = int(os.environ.get("ARCHIVE_EVERY_S", "3600"))
STATE = f"{W}/archive"


def log(msg: str):
    print(time.strftime("%H:%M:%S", time.gmtime()), msg, flush=True)


def presign(op: str, key: str) -> str:
    q = urllib.parse.urlencode({"key": key})
    with urllib.request.urlopen(f"{PRESIGN}/{op}?{q}", timeout=20) as r:
        return r.read().decode()


def r2_size(key: str) -> int:
    req = urllib.request.Request(presign("head", key), method="HEAD")
    with urllib.request.urlopen(req, timeout=60) as r:
        return int(r.headers["Content-Length"])


def archive(cam: str):
    d = f"{RING}/{cam}"
    done_path = f"{STATE}/{cam}.done"
    done = set()
    if os.path.exists(done_path):
        done = {ln.split()[0] for ln in open(done_path) if ln.strip()}
    segs = sorted((int(n[:-4]), n) for n in os.listdir(d) if n.endswith(".mkv") and n[:-4].isdigit())
    todo = [n for _, n in segs[:-2] if n not in done]
    ok = failed = nbytes = 0
    for name in todo:
        path, epoch = f"{d}/{name}", int(name[:-4])
        key = f"_ephemeral/footage/{cam}/{time.strftime('%Y-%m-%d', time.gmtime(epoch))}/{name}"
        try:
            size = os.path.getsize(path)
            subprocess.run(["curl", "-fsS", "--retry", "3", "-o", "/dev/null", "-X", "PUT", "-T", path,
                            presign("put", key)], check=True, timeout=900)
            got = r2_size(key)
            if got != size:
                raise RuntimeError(f"size mismatch local {size} r2 {got}")
            with open(done_path, "a") as f:
                f.write(f"{name} {size}\n")
            ok, nbytes = ok + 1, nbytes + size
        except FileNotFoundError:
            log(f"{cam} {name} pruned from the ring before it was archived")
            failed += 1
        except Exception as e:  # noqa: BLE001 - retried next pass
            log(f"{cam} {name} failed: {e}")
            failed += 1
    log(f"{cam}: archived {ok} ({nbytes / 1e9:.2f} GB), failed {failed}, done total {len(done) + ok}, "
        f"ring {len(segs)} segments")


def main():
    os.makedirs(STATE, exist_ok=True)
    while True:
        t0 = time.time()
        try:
            cams = open(f"{W}/archive_cams").read().split() if os.path.exists(f"{W}/archive_cams") else []
            for cam in cams:
                if os.path.isdir(f"{RING}/{cam}"):
                    archive(cam)
        except Exception as e:  # noqa: BLE001 - keep the hourly loop alive
            log(f"pass failed: {e}")
        time.sleep(max(60, EVERY_S - (time.time() - t0)))


if __name__ == "__main__":
    main()
