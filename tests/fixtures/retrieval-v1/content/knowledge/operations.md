---
title: "Synthetic Operations Runbook"
verified: 2026-09-01
ttl: process
---

# Synthetic Operations Runbook

## Deployment commands

The `kb-api` service restarts with `systemctl restart kb-api`.
Use `scripts/search --json --limit 5` to inspect a deploy.
The manual sync command accepts `--no-push`.

## Restart order

The media services startup order is Traefik, Syncthing, then Plex.
The startup order starts network services before media services.

## Encrypted backups

Encrypted backup recovery reads `vault-kb-02` under `/srv/backups/kb`.

## Deployment target

The current deploy target is `kb-api-v2` in the synthetic environment.

## Network configuration

Configure internal DNS resolver before deployment.
