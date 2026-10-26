# node/: keep a solar camera node (demo-node) alive and known (theft week, 2026-10-26)

demo-node is a Raspberry Pi 4 with a Linovision camera on eth0, on solar + a 12 V 15 Ah battery. Its only uplink is
UCSD-GUEST Wi-Fi: onboard wlan0, plus a USB MT7921 (wlan1) since Oct 26. `cloud/push.sh` (`netra-cloud-push`) sends the
video to the cloud pod. This directory keeps it running unattended and records when it is up.

## Pi (`pi/`)
- `netra-node-wifi-watchdog` + timer (every minute). Each Wi-Fi interface without internet (no 204 from
  generate_204 and no ping, both forced out of that interface) for 2 min gets an NM disconnect+connect, again every
  2 min. With **no** interface online for 10 min it reboots, at most once per 30 min. The stamp lives in
  `/boot/firmware/netra-wifi-watchdog/`, which stays writable under the overlay. The Pi has no RTC, so uptime is the floor.
  Log: `/var/log/netra-node-wifi-watchdog.log` (RAM under the overlay) and `/boot/firmware/netra-wifi-watchdog/reboots.log`.
- `netra-node-report` + timer (every minute). Over Tailscale it POSTs boot_id, uptime, `vcgencmd get_throttled`, load,
  temp, RSSI and its public IPs to the droplet's receiver. It stores nothing, so it works on the read-only root.
- Read-only root: `raspi-config nonint do_overlayfs 0` (overlayroot=tmpfs). `/boot/firmware` stays **rw** because the
  fstab `,ro` that raspi-config adds was removed. journald is volatile (`RuntimeMaxUse=64M`).
  **Persistent changes** now go to the lower layer: `sudo overlayroot-chroot <cmd>` (stdin works), or
  `raspi-config nonint do_overlayfs 1` + reboot. After `overlayroot-chroot`, the lower root can stay mounted rw until the
  next boot ("mount point is busy"). The next boot mounts it ro again.

## Droplet (`droplet/`)
- `nodeguard.py check` (timer `netra-nodeguard-check`, every minute) observes four things:
  - node: `tailscale ping`, or a Pi report under 3 min old;
  - tunnel: the relay account's sshd session from the node's public IP;
  - video: feed_health has a row with `fps_analysed > 0` in the last 3 min;
  - boots and throttled bits, from the reports.
  Transitions go to the append-only `/var/lib/netra-nodeguard/events.jsonl` and to Discord:
  - with a mention: OFFLINE, video DOWN, under-voltage (once per outage/boot);
  - without a mention: back ONLINE, video recovered, rebooted.
- `nodeguard.py serve` (`netra-nodeguard-recv`): the receiver, bound to the droplet's Tailscale IP only, with a bearer
  token. Each report is appended to `reports-<node>-YYYY-MM.jsonl` (the load/throttle history).
- `nodeguard.py timeline --days 7`: the timeline with outage durations.
- Secrets: `/etc/netra-nodeguard.env` on the droplet and `/etc/netra-node-report.env` on the Pi (root 0600, see the
  `*.example` files). Never in git.
- Event kinds: node, video, tunnel, boot, throttle, note (hand-added corrections). Reserved: `power` (`v`, `a`) for an
  INA226 on the Pi's I2C. The Pi would add v/a to its report and `step()` would log threshold crossings. Not built.

## Install
Pi (before enabling the overlay, or into the lower layer after):
```
sudo install -m 755 pi/netra-node-wifi-watchdog pi/netra-node-report /usr/local/sbin/
sudo install -m 644 pi/netra-node-*.service pi/netra-node-*.timer /etc/systemd/system/
sudo install -m 644 pi/netra-node-wifi-watchdog.default /etc/default/netra-node-wifi-watchdog
sudo install -m 600 <filled pi/netra-node-report.env.example> /etc/netra-node-report.env
sudo systemctl daemon-reload && sudo systemctl enable --now netra-node-wifi-watchdog.timer netra-node-report.timer
```
Droplet:
```
install -d /opt/netra/nodeguard && install -m 755 droplet/nodeguard.py /opt/netra/nodeguard/
install -m 600 <filled droplet/nodeguard.env.example> /etc/netra-nodeguard.env
install -m 644 droplet/netra-nodeguard-*.service droplet/netra-nodeguard-check.timer /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now netra-nodeguard-recv.service netra-nodeguard-check.timer
```
Tests: `pytest tests/test_nodeguard.py` (state machine and timeline; no network).
