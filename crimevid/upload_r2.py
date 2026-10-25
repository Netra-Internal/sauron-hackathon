"""Upload annotated videos + timelines to R2 netra-lake _work/hackathon/crimevid/<id>/ (creds: netra-training/.env).
  ~/netra/netra-training/.venv/bin/python crimevid/upload_r2.py OUT"""
import sys
from pathlib import Path

import boto3

env = dict(l.strip().split("=", 1) for l in open(Path.home() / "netra/netra-training/.env") if "=" in l and not l.startswith("#"))
env = {k: v.strip().strip('"') for k, v in env.items()}
s3 = boto3.client("s3", endpoint_url=env["S3_ENDPOINT"], region_name=env.get("S3_REGION", "auto"),
                  aws_access_key_id=env["S3_ACCESS_KEY_ID"], aws_secret_access_key=env["S3_SECRET_ACCESS_KEY"])
for d in sorted(Path(sys.argv[1]).iterdir()):
    for name in ("annotated.mp4", "timeline.json", "tracks.json"):
        if (d / name).exists():
            key = f"_work/hackathon/crimevid/{d.name}/{name}"
            s3.upload_file(str(d / name), "netra-lake", key)
            print("s3://netra-lake/" + key)
