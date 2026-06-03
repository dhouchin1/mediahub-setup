# Remote seedbox + home receiver

Run the whole download stack on a cheap Linux VPS, and Syncthing the *organised
library* back to a Mac at home for local playback. The VPS does all the
torrenting; your Mac keeps the permanent copy and never has to be online for
downloads to happen.

```
VPS (Linux, --role=seedbox)                         Home Mac (--role=receiver)
  Prowlarr → Sonarr/Radarr → qBittorrent              Syncthing  (Receive-Only
    └ downloads → /data/Torrents                          + versioning forced ON)
    └ hardlink import → /data/Media  ───────────────►   …/Media   (permanent copy)
  Syncthing (Send-Only on /data/Media)                 Jellyfin / Plex ← local playback
  [optional] qBittorrent egress via Gluetun VPN
  UIs: loopback-bound + Caddy allowlist, reached over Tailscale
```

Only the renamed, organised `Media/` library is synced — never the `Torrents/`
working directory.

---

## ⚠️ The one rule you must not break

**Syncthing "Receive Only" does NOT stop deletions from propagating.** When the
seedbox prunes a file after seeding, that delete travels to the Mac and your
copy is removed too — *unless the receiver keeps file versions*.

mediahub-setup handles this for you: **receiver mode forces Staggered
versioning that keeps versions forever.** When the seedbox deletes a seeded
file, your Mac moves its copy into `.stversions/` instead of deleting it.

Do **not**, on the receiver:

- switch the folder from **Receive Only** to **Send & Receive**, or
- disable file versioning.

Either one re-arms deletion propagation and you can lose your library.

---

## Before you start

- **A torrent-friendly VPS.** Many budget hosts forbid P2P and suspend accounts
  on a DMCA notice. Either pick a provider whose ToS permits it, or route
  qBittorrent through a VPN (the built-in **Gluetun** toggle — see below). A VPN
  does not make infringement legal; host and seed only content you have the
  right to, and respect your provider's terms and copyright law.
- **Docker Engine on the VPS** (`https://docs.docker.com/engine/install/`), with
  your user in the `docker` group.
- **Tailscale** (recommended) on both the VPS and the Mac, so you can reach the
  service web UIs privately without exposing anything to the public internet.
- **A data location on the VPS.** A separate block-storage volume mounted at
  e.g. `/mnt/data` is ideal; on a tiny disk you can just point the wizard at a
  folder like `/opt/mediahub-data` (use the drive step's "enter a path
  manually" box).

---

## 1 · Set up the VPS (seedbox)

### Option A — fully automated (recommended)

Write a config file and run one non-interactive command — ideal for cloud-init
or a fresh VPS. Start from [`examples/seedbox.yml`](../examples/seedbox.yml), set
`data_dir` and (to push the library straight home) the Mac's
`syncthing.remote_device_id`, then:

```bash
# On the VPS — bootstrap mediahub-setup AND run the install in one shot.
# (Docker is a prerequisite; prepend MEDIAHUB_INSTALL_DOCKER=1 to auto-install it.)
curl -fsSL https://raw.githubusercontent.com/dhouchin1/mediahub-setup/main/scripts/install.sh \
  | bash -s -- install --role seedbox --config seedbox.yml --yes
```

It runs preflight → creates the data layout → `docker compose up -d` → wires
Prowlarr/Sonarr/Radarr/qBittorrent and Syncthing (Send-Only, pre-paired to the
Mac when you supplied its device ID), then prints the service URLs and **this
seedbox's own Syncthing device ID**. It exits non-zero if any phase fails, so a
provisioning script can branch on the result.

Already have `mediahub-setup` installed? Just:

```bash
mediahub-setup install --role seedbox --config seedbox.yml
```

### Option B — interactive wizard

```bash
# On the VPS
curl -fsSL https://raw.githubusercontent.com/dhouchin1/mediahub-setup/main/scripts/install.sh | bash
mediahub-setup --role=seedbox --no-browser
```

The wizard binds to `127.0.0.1` only, so open it through an SSH tunnel from your
laptop:

```bash
ssh -L 7842:127.0.0.1:7842 you@your-vps    # use the port the wizard printed
# then browse to http://localhost:7842
```

Walk the steps:

1. **Preflight** — includes a Tailscale check. Install Tailscale and
   `tailscale up` if you haven't.
2. **Drive** — pick your data disk, or type a folder path manually.
3. **Settings** — Caddy is pre-checked (its allowlist fronts the stack). Fill in
   the **Syncthing** section (folder label/ID; leave *Peer device ID* blank for
   now). Optionally enable **Gluetun** and the **Seedbox retention** limits.
   Syncthing is always installed in this role.
4. **Install / Wire-up** — the stack comes up; Syncthing is configured
   **Send-Only** on `/data/Media`.
5. **Done** — copy this machine's **Syncthing device ID** (you'll need it on the
   Mac). The page also shows how to reach the UIs over Tailscale.

---

## 2 · Set up the Mac (receiver)

Automated — fill in `data_dir` and the **seedbox's** `remote_device_id` (printed
at the end of the seedbox install) in [`examples/receiver.yml`](../examples/receiver.yml), then:

```bash
# On the Mac
mediahub-setup install --role receiver --config receiver.yml
```

Or walk it interactively:

```bash
# On the Mac
mediahub-setup --role=receiver
```

1. **Drive** — choose where the synced library should live (e.g. an external
   drive). Only the `Media/` tree is created.
2. **Settings** — in the **Syncthing** section, paste the **seedbox's device
   ID** into *Peer device ID*. Use the **same Folder ID** as the seedbox. The
   folder type is **Receive-Only** and versioning is forced on (shown
   read-only). There is no Wire-up step — receiver mode only runs Syncthing.
3. **Done** — copy *this* machine's device ID.

**Finish pairing.** Each side must trust the other's device ID. If you pasted
the peer ID into the wizard on both ends, they'll connect automatically once
both are online. Otherwise open each Syncthing UI (the Done page links it) and
accept the incoming device + the shared `mediahub-media` folder.

Point **Jellyfin** (the optional service, or your own Plex) at the synced
`…/Media` folder and you're playing from a local disk.

---

## Retention: keeping a small VPS disk from filling up

A cheap VPS has a small disk, so the seedbox is configured to prune itself:

- **qBittorrent share limits** (Settings → *Seedbox retention*): when a torrent
  hits the **ratio** or **seed-time** limit, qBittorrent removes it and deletes
  its `Torrents/` copy.
- **Hardlink safety:** Sonarr/Radarr import by *hardlinking* into `Media/`, so
  the torrent copy and the library copy share one inode. Deleting the
  `Torrents/` copy frees nothing the library needs — the `Media/` file (and your
  synced Mac copy) survives untouched.
- Net effect: the VPS holds only what's actively seeding plus a short tail; the
  Mac (Receive-Only + versioning) is the permanent archive.

If you need more headroom, attach a bigger block-storage volume and mount the
**entire** `/data` tree on it — hardlinks can't cross filesystems, so don't
split `Torrents/` and `Media/` onto different mounts.

---

## Security on a public VPS

- **Nothing binds to the public IP.** On a seedbox the service web UIs bind to
  `127.0.0.1` (or sit behind Caddy's allowlist). Reach them over **Tailscale**
  (`http://<tailnet-ip>:<port>`) or an SSH tunnel.
- **Caddy local mode** (pre-checked for seedbox) publishes each UI behind an IP
  allowlist of loopback + RFC1918 + the Tailscale CGNAT range
  (`100.64.0.0/10`), rejecting everything else.
- **Syncthing needs no inbound port at home.** Its traffic is end-to-end
  encrypted and NAT-traversing, so the Mac behind home NAT just works.
- The wizard itself only ever listens on `127.0.0.1` — always tunnel to it.

---

## qBittorrent over VPN (Gluetun)

Enable **Gluetun** in Settings to route qBittorrent's traffic through a VPN:

- qBittorrent runs with `network_mode: service:gluetun` — *all* its traffic
  egresses through the tunnel, and its WebUI + BitTorrent ports are published on
  the gluetun container.
- Pick your **provider** and **VPN type** (WireGuard or OpenVPN) and paste the
  credentials. They're written to `~/mediahub/.env`, never into the compose
  file.
- Keep **port forwarding** on — seeding needs an inbound forwarded port. Confirm
  your VPN provider supports it. The wizard makes a best-effort attempt to set
  qBittorrent's listen port to the forwarded port; if the VPN assigns it later,
  set it manually in qBittorrent → Settings → Connection.
- The host must allow `NET_ADMIN` and `/dev/net/tun` (most VPS do; some locked
  down containers don't).

---

## Troubleshooting

- **Devices won't connect.** Both must be online and trust each other's device
  ID. Check the VPS firewall allows Syncthing's `22000/tcp+udp` and
  `21027/udp`. Watch the Syncthing UI's "Remote Devices" panel.
- **"Out of Sync" on the receiver.** Usually a path/permission issue — the
  receiver folder must be writable by the same PUID/PGID the wizard used.
- **Library missing on the VPS after a reboot.** Make sure your data volume is
  in `/etc/fstab` so `/data` is mounted before Docker starts.
- **Syncthing missed changes on a big library (Linux).** Raise the inotify
  watch limit: `sudo sysctl fs.inotify.max_user_watches=204800` (persist it in
  `/etc/sysctl.conf`).
- **VPS account warned for traffic.** Stop seeding, review the provider's ToS,
  and switch to a P2P-friendly host and/or the Gluetun VPN toggle.
