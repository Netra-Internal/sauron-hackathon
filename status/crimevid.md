WORKING — first annotated video done: ~/sauron-data/crimevid/out/bike-lock/annotated.mp4 (bike lock cut, Jev deploy at 5.5 s = +3.5 s after crime start); 6 more clips running.

- Pipeline: netra-ask main dispatch Watcher (replay, DirSink, nothing posted), PersonGate YOLO11s ONNX, Jev strips every 2 s, default PolicyConfig (judge.py md5 identical to jetson-cloud deploy; no DISPATCH_POLICY override there).
- Render: crimevid/render.py (YOLO11s + ByteTrack every frame at 12 fps, HUD, deploy banner, timeline). Branch hack-crimevid.
- Next: catalytic, atm-rip, car-breakin, fence-climb, 2 benign MEVA owner-at-car clips → artifact page.
