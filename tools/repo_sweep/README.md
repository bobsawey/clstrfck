repo_sweep — Dockerized Windows‑repo collector (Arch Linux)

Collect unsynced working copies of the same Git repo scattered across Windows partitions—without booting Windows—then bring them into a controlled Docker environment to stage, branch, and attempt merges against a target GitHub repo. Designed for read‑only harvesting and optional host egress lockdown so only Docker can reach the internet during the merge run.

⸻

TL;DR (Quick start)

```
# 1) Save the script
curl -sSL -o repo_sweep.sh https://example.invalid/repo_sweep.sh
chmod +x repo_sweep.sh

# 2) Run on Arch Linux, with your target GitHub repo:
sudo TARGET_REPO=https://github.com/you/your-repo.git ./repo_sweep.sh
```

Outputs
- Staged sources (no .git): /var/tmp/repo_sweep_archive/sources/*
- Metadata JSONL: /var/tmp/repo_sweep_archive/sources.jsonl
- Report: /var/tmp/repo_sweep_out/merge_report.txt
- Docker image: repo-collector:latest

⸻

What it does
1. Verify / install dependencies: docker, ntfs-3g, git, rsync. Enables and starts Docker.
2. Identify Windows partitions on the same physical disk as / and mount them read‑only under /mnt/win_* (supports ntfs3 or falls back to ntfs-3g).
   Optional: Append noauto,ro fstab entries (DO_FSTAB=1).
3. Scan for Git repos (directories containing .git) on those mounts.
4. Harvest working trees (copy files only, excluding .git) into ARCHIVE_DIR/sources/*, and log source→dest→origin in sources.jsonl.
5. Build a tiny Docker image (Alpine) with git + a merge driver script.
6. Run merge workflow in Docker (binds staged data read‑only):
   - Clone TARGET_REPO.
   - For each staged copy, create import/<name> branch with its snapshot.
   - Attempt merges into BASE_BRANCH on separate merge-<name> branches.
   - Write a clean/conflicts summary to merge_report.txt.
   - Optional: Push import & merge branches (PUSH_BRANCHES=1, PUSH_MERGES=1).
7. (Optional) Temporarily lock down host egress so only Docker traffic is allowed; original nftables rules are restored on exit (DO_LOCKDOWN=1).

⸻

Requirements & Assumptions
- OS: Arch Linux (or Arch‑based).
- Privileges: Run with sudo (mounts, nftables, Docker).
- Disk scope: Scans NTFS partitions on the same disk as /. (Extendable if you want to cover all disks.)
- BitLocker: Encrypted volumes are skipped (no dislocker integration in this script).
- Safety: Mounts are read‑only. Harvest copies exclude .git/ and .github/.

⸻

Installation & Usage
1. Get the script

```
# Use your preferred fetch method or copy/paste from your source control
chmod +x repo_sweep.sh
```

2. Basic run

```
sudo TARGET_REPO=https://github.com/you/your-repo.git ./repo_sweep.sh
```

3. Useful variants

```
# Filter only repos whose 'origin' contains a substring
sudo TARGET_REPO=https://github.com/you/your-repo.git \
     FILTER_REMOTE_SUBSTR=my-company \
     ./repo_sweep.sh

# Push created import/* and merge-* branches
sudo TARGET_REPO=https://github.com/you/your-repo.git \
     PUSH_BRANCHES=1 PUSH_MERGES=1 \
     AUTHOR_NAME="Your Name" AUTHOR_EMAIL="you@example.com" \
     ./repo_sweep.sh

# Add conservative fstab entries and enable host egress lockdown
sudo TARGET_REPO=https://github.com/you/your-repo.git \
     DO_FSTAB=1 DO_LOCKDOWN=1 \
     ./repo_sweep.sh
```

⸻

Environment variables (configuration)

| Variable | Default | Description |
| --- | --- | --- |
| TARGET_REPO | — (required) | GitHub (or any Git) URL for the canonical repo to merge into. |
| BASE_BRANCH | main | Base branch for merges (auto‑detects origin/HEAD when possible). |
| ARCHIVE_DIR | /var/tmp/repo_sweep_archive | Staging area for harvested sources. |
| OUTPUT_DIR | /var/tmp/repo_sweep_out | Reports and logs output. |
| FILTER_REMOTE_SUBSTR | (empty) | Only include found repos whose origin URL contains this substring. |
| DO_FSTAB | 0 | If 1, append noauto,ro ntfs lines with x-systemd.automount. |
| DO_LOCKDOWN | 0 | If 1, apply temporary host egress lockdown via nftables; containers still have internet. |
| PUSH_BRANCHES | 0 | If 1, push each import/* branch to origin. |
| PUSH_MERGES | 0 | If 1, push each merge-* branch to origin. |
| AUTHOR_NAME | Repo Collector | Git author for import commits. |
| AUTHOR_EMAIL | repo-collector@local | Git email for import commits. |

Auth note: If your target repo is private, configure Docker auth or embed a temporary PAT in the URL (e.g., https://<TOKEN>@github.com/you/repo.git). Treat with care.

⸻

Outputs & layout
- Mounts: /mnt/win_* (read‑only)
- Staged copies: $ARCHIVE_DIR/sources/<name_hash>/ (files only; no .git)
- Metadata: $ARCHIVE_DIR/sources.jsonl (one JSON per line: source, dest, origin)
- Docker image: repo-collector:latest (created in a temp merge_container/ build dir)
- Report: $OUTPUT_DIR/merge_report.txt (clean merges vs. conflicts, per source)

⸻

Network lockdown (optional)

When DO_LOCKDOWN=1:
- Saves current nftables rules to /tmp/nft.rules.backup.<rand>.
- Applies a minimal ruleset that drops host egress except loopback and Docker bridge traffic.
- Restores original rules on exit (even on most errors).
Heads‑up: If you’re on SSH, lockdown may drop your session.

⸻

Design notes & limitations
- Read‑only harvesting prevents accidental mutation of Windows volumes.
- Disk scope limited to the root disk to minimize surprises; extendable to enumerate all disks if desired.
- Merge strategy: Each staged snapshot becomes import/<name>; merges are attempted independently into BASE_BRANCH on separate merge-* branches to reveal conflicts cleanly without altering the base.
- Windows quirks: NTFS path length and case differences may surface as conflicts. Symlinks from NTFS may behave differently on Linux.

⸻

Troubleshooting
- No NTFS partitions found: You might be on a different disk; extend the scanner or point it at additional devices.
- BitLocker volumes: Not supported by default. We can add dislocker integration if needed.
- Docker can’t reach GitHub under lockdown: Ensure Docker is using docker0 (default). Custom networks may need rules updated.
- Auth failures: Use a PAT or SSH inside the container; consider mounting /root/.ssh read‑only with known_hosts & a deploy key (harden carefully).

⸻

Security notes
- Host mounts are read‑only.
- Merge work happens inside Docker with only the staged data and network access (if not locked down).
- Consider replacing the container’s root user with a non‑root UID/GID if you want additional defense‑in‑depth.

⸻

Roadmap / TODO
- Cumulative merges (decision point): Option to merge sources in sequence (A → base, then B onto result, then C…) to produce a single “best effort” integrated branch.
- Pros: Produces a concrete integrated state sooner.
- Cons: Conflict resolution order matters; later imports might be penalized.
- Action: Provide a MERGE_MODE=independent|cumulative toggle; implement deterministic source ordering (e.g., by path hash).
- BitLocker support via dislocker (read‑only) with safe key handling.
- Multi‑disk scan (enumerate all ntfs partitions, not just root disk).
- Non‑root container user; optional --network=none runs for offline prep phases.
- Optional content de‑duplication in staging (hash‑based file store) to save space.

⸻

Uninstall / cleanup

```
# Remove staged data and outputs
sudo rm -rf /var/tmp/repo_sweep_archive /var/tmp/repo_sweep_out

# Remove Docker artifacts
docker rmi repo-collector:latest 2>/dev/null || true

# If you enabled DO_FSTAB=1, manually review /etc/fstab and remove the added lines.
# Mounts under /mnt/win_* will disappear after a reboot or manual umount:
sudo umount /mnt/win_* 2>/dev/null || true
```

⸻

License

Use at your own risk. Consider adding a proper license if you intend to redistribute.
