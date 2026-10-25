#!/usr/bin/env bash
# R2 (netra-lake) through the droplet's boto3 creds; the laptop has no rclone. Keys not starting with _work/ go under _work/sauron-cloud/.
#   r2.sh put <key> < file      r2.sh get <key> > file      r2.sh url <key> [get|put] [ttl_s]      r2.sh ls [prefix]
set -euo pipefail
D=${DROPLET:-${HACK_HOST:?set HACK_HOST=root@<droplet>}}
op=$1; key=${2:-}; case $key in _work/*) ;; *) key=_work/sauron-cloud/$key ;; esac
py='import boto3,os,sys
s=boto3.client("s3",endpoint_url=os.environ["S3_ENDPOINT"],region_name="auto",aws_access_key_id=os.environ["S3_ACCESS_KEY_ID"],aws_secret_access_key=os.environ["S3_SECRET_ACCESS_KEY"])
op,key,a,b=sys.argv[1],sys.argv[2],sys.argv[3],int(sys.argv[4]); B="netra-lake"
if op=="put": s.upload_fileobj(sys.stdin.buffer,B,key)
elif op=="get": s.download_fileobj(B,key,sys.stdout.buffer)
elif op=="url": print(s.generate_presigned_url("put_object" if a=="put" else "get_object",Params={"Bucket":B,"Key":key},ExpiresIn=b))
elif op=="ls":
  for o in s.list_objects_v2(Bucket=B,Prefix=key).get("Contents",[]): print(o["Key"],o["Size"],o["LastModified"])'
ssh -o BatchMode=yes "$D" "set -a; . /etc/netra-ask-relay.env; set +a; /opt/netra/netra-ask/.venv/bin/python -c '$py' $op $key ${3:-get} ${4:-604800}"
