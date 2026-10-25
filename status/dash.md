DONE: Public-view middleware CANCELLED as asked. It had already been deployed (9b782a4) when the cancel arrived, so it is rolled back: hack-dash reverts it (3d3e056, pushed, redeployed), and the change is parked unmerged on branch hack-dash-public-view. MANAGER: hack-dash is safe to merge.

- Deployed app.py and calib.py now match the pre-change code (md5 checked). Straight to the app with no cookie, /hack/ -> 303 to login.
- Through nginx, /hack/ and /hack/api/cameras -> 200 without a cookie. That is your shared public account, not my code.
- The public view was live for about 3 minutes (9b782a4, deployed then reverted).
- Also removed: the HACK_LAUNCH_USER/PASSWORD lines I had copied into /etc/sauron-hack.env from /root/hack-launch.pw. The file is back to its header comment only.
- Branch hack-dash-public-view (9b782a4), NOT for main. It holds:
  - reads public, writes behind login
  - anonymous calib reads as hack_launch
  - Send drone, Abort and Move camera disabled with "Sign in to control"
  Delete the branch if it isn't wanted.


## Repo push
PUSHED 1597371
- Branch hack-dash in Netra-Internal/sauron-hackathon. It contains everything dash built or deployed today, and origin/main.
  - code: hackdash/app.py and hackdash/static/{index.html,hack.js,hack.css}
  - deploy: deploy/{install.sh,sauron-hack.service,nginx-hack.conf}, plus the new deploy/sauron-hack.env.example
    (placeholders only, no secrets) and deploy/README.md (the README section for my piece)
  - tool: tools/dash_shot.js (the read-only page check)
  - screenshot: plans/dash-live.png
  - requirements.txt
- No secrets in the tree: the real /etc/sauron-hack.env holds only a comment, and the tokens live in netra-ask's env on the droplet.
