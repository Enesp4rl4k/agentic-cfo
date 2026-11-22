# Disk is full

A full disk stops Postgres first, then uploads and logs. Do not delete anything inside a Docker volume by hand.

## Check

```bash
df -h /                                   # which filesystem
docker system df                          # images, containers, volumes, build cache
du -sh /var/lib/docker/volumes/*/_data 2>/dev/null | sort -h | tail     # which volume (as root)
ls -lh /var/backups/aicfo                 # local backup copies (backup.sh keeps the newest 2)
```

## Fix, in this order (cheapest and safest first)

1. Build cache and unused images (the deploy builds on the server, so these grow every deploy):
   ```bash
   docker builder prune -f
   docker image ls agentic-cfo-backend   # keep the running tag and the previous one for rollback
   docker image rm agentic-cfo-backend:<old tag>      # name each tag; no wildcards
   ```
2. Local backup copies beyond the newest two, only after confirming the off-server copy exists
   (`rclone lsl $BACKUP_RCLONE_REMOTE | tail`).
3. Container logs are capped at 5 x 20 MB per service in the compose file; if one is larger, that service
   is not using the shipped logging block.
4. Uploads (`uploads_data` volume): the files are customers' originals, kept forever by design (no retention
   job). Do not delete. Grow the disk, or move to an object store (a code change).
5. Postgres: the volume grows with data. `VACUUM` does not shrink it; resize the disk.

After freeing space: `dc ps`; Postgres may need `dc restart postgres`; `curl .../api/v1/ready`.

## Prevent

No disk alert exists (audit item 5.6). Until one does, check `df -h /` weekly, or have the uptime monitor
hit `/api/v1/ready` (a full disk makes the database check fail).

## Not verified

Volume paths assume the default Docker data root and the volume names in `docker-compose.prod.yml`.
