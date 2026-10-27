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
  temp, RSSI and whether its push ssh is connected to the relay (`tunnel_up`) to the droplet's receiver. It stores nothing, so it works on the read-only root.
- Read-only root: `raspi-config nonint do_overlayfs 0` (overlayroot=tmpfs). `/boot/firmware` stays **rw** because the
  fstab `,ro` that raspi-config adds was removed. journald is volatile (`RuntimeMaxUse=64M`).
  **Persistent changes** now go to the lower layer: `sudo overlayroot-chroot <cmd>` (stdin works), or
  `raspi-config nonint do_overlayfs 1` + reboot. After `overlayroot-chroot`, the lower root can stay mounted rw until the
  next boot ("mount point is busy"). The next boot mounts it ro again.

## Droplet (`droplet/`)
- `nodeguard.py check` (timer `netra-nodeguard-check`, every minute) observes four things:
  - node: `tailscale ping`, or a Pi report under 3 min old;
  - tunnel: the Pi's `tunnel_up` in a fresh report. UCSD-GUEST changes the public NAT IP under a live session, so the droplet cannot match sessions by IP;
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

## Night schedule: built, currently ALL OFF (William, Oct 27)
Design: OFF Mon–Fri 01:00–06:00 San Diego time (the nights of Sun..Thu); Fri and Sat nights stay on.
It ran once as designed on the night of Oct 26→27. On Oct 27 William turned it **off** until the 12 V timer switch is
installed: without the switch the camera stays powered, so pausing the push saved only ~1 W, and night outages
should alert. Its three parts go back on **together**, with one command, once William confirms the switch.
- **(A) push pause:** `pi/netra-night-schedule apply`, from `netra-night-schedule.timer` (now DISABLED in both
  layers). The timer fires at `Mon..Fri 01:00 America/Los_Angeles`, at `Mon..Fri 06:00 America/Los_Angeles`, and
  15 s after boot.
  - Inside the window it stops `netra-cloud-push`; outside it, it makes sure the push runs.
  - The timezone is part of the calendar spec because the Pi's own zone is Europe/London.
- **(B) poweroff:** `netra-night-poweroff.timer` (DISABLED) runs a clean `systemctl poweroff` at
  `Mon..Fri 00:58 America/Los_Angeles`. The script refuses to power off outside Mon–Fri 00:50–01:00.
  - It needs a 12 V 7-day timer switch between the low-voltage cutoff and camera+Pi, set to OFF 01:00 and ON 06:00
    Mon–Fri. The switch's 06:00 power-on is the only thing that boots the Pi again.
- **(C) alert mute:** `SCHEDULE_OFF="Mon-Fri 01:00-06:00 America/Los_Angeles"` in the droplet's
  `/etc/netra-nodeguard.env` (now commented out, so it is empty = always alert).
  - With it set, outages from 00:55 to 06:15 local are logged with `"scheduled": true` and not posted. The window
    opens 5 min early to cover the 00:58 poweroff.
  - Anything still down at 06:15 is posted once, with a mention ("NOT back after the scheduled night off"); its
    recovery is posted without a mention.

**Turn all three on** (only after William confirms the timer switch). It writes the Pi's SD layer and the live
system. It uses `;` because `overlayroot-chroot` can exit non-zero when it cannot remount the SD layer ro afterwards.
The command ends with a check: expect `enabled enabled`, `active active` and the `SCHEDULE_OFF=` line.
```
ssh netra@demo-node 'for t in netra-night-schedule.timer netra-night-poweroff.timer; do sudo overlayroot-chroot systemctl enable $t; sudo systemctl enable --now $t; done; sudo overlayroot-chroot systemctl is-enabled netra-night-schedule.timer netra-night-poweroff.timer 2>/dev/null; systemctl is-active netra-night-schedule.timer netra-night-poweroff.timer'; ssh root@<droplet> 'sed -i "s|^#SCHEDULE_OFF=|SCHEDULE_OFF=|" /etc/netra-nodeguard.env; grep ^SCHEDULE_OFF= /etc/netra-nodeguard.env'
```
**Turn all three off** (the state since Oct 27): the same command with `disable` in place of `enable`, `disable --now`
in place of `enable --now`, and `s|^SCHEDULE_OFF=|#SCHEDULE_OFF=|`.

## Install
Pi (before enabling the overlay, or into the lower layer after):
```
sudo install -m 755 pi/netra-node-wifi-watchdog pi/netra-node-report pi/netra-night-schedule /usr/local/sbin/
sudo install -m 644 pi/netra-node-*.service pi/netra-node-*.timer pi/netra-night-*.service pi/netra-night-*.timer /etc/systemd/system/
sudo install -m 644 pi/netra-node-wifi-watchdog.default /etc/default/netra-node-wifi-watchdog
sudo install -m 600 <filled pi/netra-node-report.env.example> /etc/netra-node-report.env
sudo systemctl daemon-reload && sudo systemctl enable --now netra-node-wifi-watchdog.timer netra-node-report.timer   # night-* timers: see "Night schedule"
```
Droplet:
```
install -d /opt/netra/nodeguard && install -m 755 droplet/nodeguard.py /opt/netra/nodeguard/
install -m 600 <filled droplet/nodeguard.env.example> /etc/netra-nodeguard.env
install -m 644 droplet/netra-nodeguard-*.service droplet/netra-nodeguard-check.timer /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now netra-nodeguard-recv.service netra-nodeguard-check.timer
```
Tests: `pytest tests/test_nodeguard.py` (state machine and timeline; no network).
