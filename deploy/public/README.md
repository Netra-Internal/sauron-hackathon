# Public access (Oct 24 2026)
William: "turn off all password req". /ask and /hack on internal.netralabs.net work with no login: nginx maps a request
with no Authorization header to the shared internal user `public` (its password lives only on the droplet).
- /etc/nginx/conf.d/netra-public-auth.conf: `map $http_authorization $netra_public_auth { "" "Basic <public creds>"; default $http_authorization; }`
- `proxy_set_header Authorization $netra_public_auth;` in `location /ask`, `location /hack/`, `location = /_hack_stream_auth`.
- The edge bucket route (`location = /ask/api/edge/bucket`) and /hack/relay keep their own worker tokens.
- Still behind login: /map, /AI, /catalog.
Undo: delete the conf file and the three lines, `nginx -t && systemctl reload nginx`.
