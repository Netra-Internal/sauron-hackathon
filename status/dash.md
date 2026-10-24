DONE: Open camera now plays the pod's live video (WHEP if available, else LL-HLS via hls.js 1.5.20) with person boxes drawn over it; ring JPEGs only as fallback. Deployed from hack-dash 3eff3cb (contains origin/main), pushed — MANAGER: please merge hack-dash into main.

- Verified on the real page (axis-q6215): /hack/stream/axis-q6215/whep -> 404, so it falls through to index.m3u8; hls.js plays 1280x720 video, state "playing" ~3 s after page load, currentTime advancing.
- Before cloud's stream was up, verified the fallback: both stream URLs 404 -> stills from the ring with a "video stream down · showing stills" chip, boxes still drawn; the stream is retried every 15 s.
- While the video plays: no "No frame from the camera's ring" message; spinner "Starting live video…" only while starting with no still to show; /live polled every 0.5 s for the newest boxes; chips "live video" + "boxes ≈N s behind live".
- A video that freezes for 5 s (tab visible), a fatal hls.js error, or WebRTC failed/disconnected -> fall back to stills, retry in 15 s.
- NOT verified: a screenshot of the playing video (Playwright MCP disconnected right after the playback check); WebRTC/WHEP (cloud's /whep is 404).
- Known mismatch, not fixable in the page: the video is near-live but the boxes from /live are ~14–25 s old, so boxes won't line up with moving people in the video. Needs fresher boxes upstream (boxes/edge).
