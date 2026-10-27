"""R2 presigner for the cloud pod's footage archiver (cloud/pod/archive.py). Runs on the droplet, 127.0.0.1 only; the pod
reaches it through netra-cloud-presign-tunnel (ssh -R), so the R2 keys never leave the droplet. Signs only keys under
_ephemeral/footage/ in netra-lake (12-day lifecycle expiry), 1 h TTL.
  GET /put?key=K   -> presigned PUT URL        GET /head?key=K  -> presigned HEAD URL (size check after upload)
Env (from /etc/netra-ask-relay.env): S3_ENDPOINT S3_ACCESS_KEY_ID S3_SECRET_ACCESS_KEY.
"""
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import boto3

BUCKET, TTL = "netra-lake", 3600
KEY_OK = re.compile(r"^_ephemeral/footage/[a-z0-9-]+/\d{4}-\d{2}-\d{2}/\d+\.mkv$")
s3 = boto3.client("s3", endpoint_url=os.environ["S3_ENDPOINT"], region_name="auto",
                  aws_access_key_id=os.environ["S3_ACCESS_KEY_ID"],
                  aws_secret_access_key=os.environ["S3_SECRET_ACCESS_KEY"])
OPS = {"/put": "put_object", "/head": "head_object"}


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        u = urlparse(self.path)
        key = parse_qs(u.query).get("key", [""])[0]
        if u.path not in OPS or not KEY_OK.match(key):
            self.send_response(403)
            self.end_headers()
            return
        url = s3.generate_presigned_url(OPS[u.path], Params={"Bucket": BUCKET, "Key": key}, ExpiresIn=TTL).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(url)))
        self.end_headers()
        self.wfile.write(url)

    def log_message(self, fmt, *args):
        print(self.address_string(), fmt % args, flush=True)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("PRESIGN_PORT", "8472"))), H).serve_forever()
