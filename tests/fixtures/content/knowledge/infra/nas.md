---
title: "NAS"
verified: 2026-08-16
ttl: domain
aliases:
  - "storage server"
  - "file server"
sources:
  - observations/archived/20260412T101500-a1b2c3d4.md
---

# NAS

The NAS runs Traefik, Syncthing, and Plex. Its disks are in one pool.

## Restart order

Traefik first, then Syncthing, then Plex.

## Power loss

After a power loss, check the disks before starting Plex.
