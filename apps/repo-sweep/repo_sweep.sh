#!/usr/bin/env bash
# repo_sweep.sh — Arch Linux
# Finds Windows (NTFS) partitions, mounts RO, harvests repo working trees (no .git),
# builds a tiny Docker tool that imports & tries merges into a target GitHub repo,
# optionally locks down host egress so only Docker can talk to the internet.

set -euo pipefail

# ---------- Defaults / CLI ----------
ARCHIVE_DIR="${ARCHIVE_DIR:-/var/tmp/repo_sweep_archive}"
OUTPUT_DIR="${OUTPUT_DIR:-/var/tmp/repo_sweep_out}"
TARGET_REPO="${TARGET_REPO:-}"          # e.g. https://github.com/you/your-repo.git
BASE_BRANCH="${BASE_BRANCH:-main}"      # base branch to merge into
FILTER_REMOTE_SUBSTR="${FILTER_REMOTE_SUBSTR:-}"  # optional: only repos whose 'origin' contains this substring
DO_FSTAB="${DO_FSTAB:-0}"               # 1=write noauto,ro fstab lines
DO_LOCKDOWN="${DO_LOCKDOWN:-0}"         # 1=temporarily drop host egress (containers still work)
PUSH_BRANCHES="${PUSH_BRANCHES:-0}"     # 1=push import/* branches
PUSH_MERGES="${PUSH_MERGES:-0}"         # 1=push merge-* branches
AUTHOR_NAME="${AUTHOR_NAME:-Repo Collector}"
AUTHOR_EMAIL="${AUTHOR_EMAIL:-repo-collector@local}"

usage() {
  cat <<EOU
Usage: sudo ./repo_sweep.sh [options]

Env/flags (can be passed as VAR=value before the command):
  ARCHIVE_DIR=/path            Staging dir for harvested sources (default: $ARCHIVE_DIR)
  OUTPUT_DIR=/path             Output dir for reports/logs (default: $OUTPUT_DIR)
  TARGET_REPO=<url>            REQUIRED for merge step: GitHub repo URL
  BASE_BRANCH=<name>           Base branch to merge into (default: $BASE_BRANCH)
  FILTER_REMOTE_SUBSTR=...     Only include repos whose 'origin' remote URL contains this substring
  DO_FSTAB=1                   Also append noauto,ro ntfs fstab entries (safer default is 0)
  DO_LOCKDOWN=1                Temporarily block host egress so only Docker has internet (expert)
  PUSH_BRANCHES=1              Push import/* branches
  PUSH_MERGES=1                Push merge-* branches
  AUTHOR_NAME="Name"           Git author for import commits
  AUTHOR_EMAIL="email@host"    Git email for import commits

Examples:
  sudo TARGET_REPO=https://github.com/you/proj.git ./repo_sweep.sh
  sudo TARGET_REPO=https://github.com/you/proj.git FILTER_REMOTE_SUBSTR=your-origin ./repo_sweep.sh
  sudo TARGET_REPO=https://github.com/you/proj.git DO_LOCKDOWN=1 DO_FSTAB=1 ./repo_sweep.sh

Notes:
 - Script targets the *same disk* your root (/) is on, scanning its NTFS partitions.
 - Mounts NTFS read-only by default. BitLocker-encrypted volumes are skipped.
 - Lockdown will disrupt SSH/Wi-Fi/etc. It restores when the script exits.
EOU
  exit 1
}

[[ "${1:-}" == "-h" || "${1:-}" == "--help" ]] && usage
[[ -z "$TARGET_REPO" ]] && { echo "ERROR: TARGET_REPO is required."; usage; }

need_root() { [[ $EUID -eq 0 ]] || exec sudo -E bash "$0" "$@"; }
need_root "$@"

log() { printf "\n[%s] %s\n" "$(date '+%F %T')" "$*" >&2; }

# ---------- Sanity checks & deps ----------
if ! grep -qi arch /etc/os-release; then
  log "WARNING: Not an Arch-based system per /etc/os-release. Proceeding anyway."
fi

log "Installing required packages (docker, ntfs-3g, git, rsync, nftables)..."
pacman -Sy --needed --noconfirm docker ntfs-3g git rsync nftables >/dev/null

log "Enabling & starting Docker..."
systemctl enable --now docker

# ---------- Determine root disk and find NTFS partitions ----------
ROOT_DEV="$(findmnt -n -o SOURCE /)"
# Normalize /dev/mapper/* to parent
PARENT_DISK="$(lsblk -no pkname "$ROOT_DEV" 2>/dev/null || true)"
if [[ -z "$PARENT_DISK" ]]; then
  # Try direct device (e.g., /dev/nvme0n1p2 -> nvme0n1)
  base="$(basename "$ROOT_DEV")"
  PARENT_DISK="$(lsblk -no pkname "/dev/$base" 2>/dev/null || true)"
fi
[[ -z "$PARENT_DISK" ]] && { log "ERROR: Unable to identify parent disk for / ($ROOT_DEV)."; exit 2; }

log "Root is on: $ROOT_DEV (disk: /dev/$PARENT_DISK)"
mapfile -t NTFS_PARTS < <(lsblk -rno NAME,FSTYPE,TYPE "/dev/$PARENT_DISK" | awk '$3=="part" && tolower($2)=="ntfs"{print $1}')
if ((${#NTFS_PARTS[@]}==0)); then
  log "No NTFS partitions found on /dev/$PARENT_DISK. Nothing to scan."
  exit 0
fi
log "Found NTFS partitions: ${NTFS_PARTS[*]}"

# ---------- Mount NTFS partitions read-only ----------
mkdir -p /mnt
MOUNTED=()
FSTYPE="ntfs3"
grep -qw ntfs3 /proc/filesystems || FSTYPE="ntfs-3g"

for part in "${NTFS_PARTS[@]}"; do
  DEV="/dev/$part"
  UUID="$(blkid -s UUID -o value "$DEV" || true)"
  LABEL="$(blkid -s LABEL -o value "$DEV" || echo "$part")"
  MP="/mnt/win_${LABEL//[^A-Za-z0-9._-]/_}"
  mkdir -p "$MP"
  log "Mounting $DEV at $MP (fstype=$FSTYPE, ro)..."
  if mount | grep -q " on $MP "; then
    log "Already mounted: $MP"
  else
    if [[ "$FSTYPE" == "ntfs3" ]]; then
      mount -t ntfs3 -o ro,nofail,noatime "$DEV" "$MP" || { log "Mount failed (ntfs3), trying ntfs-3g..."; mount -t ntfs-3g -o ro,nofail "$DEV" "$MP"; }
    else
      mount -t ntfs-3g -o ro,nofail "$DEV" "$MP"
    fi
  fi
  MOUNTED+=("$MP")

  if [[ "$DO_FSTAB" == "1" && -n "$UUID" ]]; then
    if ! grep -q "UUID=$UUID " /etc/fstab; then
      log "Appending noauto,ro fstab line for $MP"
      echo "UUID=$UUID  $MP  $FSTYPE  ro,nofail,noatime,x-systemd.automount,noauto  0  0" >> /etc/fstab
    fi
  fi
done

# ---------- Harvest repos (no .git) to ARCHIVE_DIR ----------
mkdir -p "$ARCHIVE_DIR" "$OUTPUT_DIR"
SRC_DIR="$ARCHIVE_DIR/sources"
META_FILE="$ARCHIVE_DIR/sources.jsonl"
mkdir -p "$SRC_DIR"
: > "$META_FILE"

log "Scanning mounted NTFS paths for Git repositories..."
# find .git directories; parent is repo root
FOUND=()
for MP in "${MOUNTED[@]}"; do
  # depth limited a bit for speed; adjust if needed
  while IFS= read -r gitdir; do
    repo_root="$(dirname "$gitdir")"
    FOUND+=("$repo_root")
  done < <(find "$MP" -xdev -type d -name .git 2>/dev/null)
done

if ((${#FOUND[@]}==0)); then
  log "No Git working trees found on mounted Windows partitions."
else
  log "Found ${#FOUND[@]} repo(s). Copying working trees (excluding .git) to $SRC_DIR ..."
fi

# Copy working trees; optionally filter by remote substring
for REPO in "${FOUND[@]:-}"; do
  INCLUDE=1
  if [[ -n "$FILTER_REMOTE_SUBSTR" && -d "$REPO/.git" ]]; then
    if ! git --git-dir "$REPO/.git" remote -v 2>/dev/null | grep -Fq "$FILTER_REMOTE_SUBSTR"; then
      INCLUDE=0
    fi
  fi
  [[ $INCLUDE -eq 0 ]] && continue

  # Unique subdir name: sanitized basename + short hash of full path
  base="$(basename "$REPO")"
  hash="$(printf '%s' "$REPO" | sha1sum | cut -c1-10)"
  dest="$SRC_DIR/${base}_${hash}"
  log "  -> $REPO  =>  $dest"
  mkdir -p "$dest"
  rsync -a --delete --exclude='/.git/' --exclude='/.github/' "$REPO"/ "$dest"/

  # capture origin if present
  origin="$(git --git-dir "$REPO/.git" remote get-url origin 2>/dev/null || true)"
  printf '{"source":"%s","dest":"%s","origin":"%s"}\n' \
    "$REPO" "$dest" "${origin//\"/\\\"}" >> "$META_FILE"
done

# ---------- Build the merge container ----------
WORKDIR="$(pwd)/merge_container"
rm -rf "$WORKDIR"
mkdir -p "$WORKDIR"

cat > "$WORKDIR/Dockerfile" <<'DF'
FROM alpine:3.20
RUN apk add --no-cache git bash openssh-client ca-certificates rsync diffutils
WORKDIR /repo
COPY merge.sh /usr/local/bin/merge.sh
ENTRYPOINT ["/usr/local/bin/merge.sh"]
DF

cat > "$WORKDIR/merge.sh" <<'EOS'
#!/usr/bin/env bash
set -euo pipefail

: "${GIT_TARGET_REPO:?Set GIT_TARGET_REPO}"
BASE_BRANCH="${BASE_BRANCH:-main}"
PUSH_BRANCHES="${GIT_PUSH_BRANCHES:-0}"
PUSH_MERGES="${GIT_PUSH_MERGES:-0}"
AUTHOR_NAME="${GIT_AUTHOR_NAME:-Repo Collector}"
AUTHOR_EMAIL="${GIT_AUTHOR_EMAIL:-repo-collector@local}"

echo "[merge] cloning $GIT_TARGET_REPO ..."
# Prefer full history to allow real merges; fall back to shallow if huge is an issue
git clone "$GIT_TARGET_REPO" /repo
cd /repo

# Determine base branch (try origin/HEAD, else env)
if git rev-parse --verify -q "origin/HEAD" >/dev/null; then
  base_branch="$(git symbolic-ref --short -q refs/remotes/origin/HEAD | sed 's@^origin/@@')"
else
  base_branch="$BASE_BRANCH"
fi
git checkout -B "$base_branch" "origin/$base_branch" || git checkout -B "$base_branch"

mkdir -p /work
report="/work/merge_report.txt"
echo "Target: $GIT_TARGET_REPO" > "$report"
echo "Base:   $base_branch"    >> "$report"
echo ""                        >> "$report"

# For each staged source, create an import/* branch with its snapshot
for src in /data/sources/*; do
  [[ -d "$src" ]] || continue
  bn="$(basename "$src")"
  safe_bn="$(echo "$bn" | tr -c 'A-Za-z0-9._-' '-')"
  branch="import/${safe_bn}"

  echo "[merge] import $bn -> $branch"
  git checkout -B "$branch" "$base_branch"
  # wipe worktree except .git
  find . -mindepth 1 -maxdepth 1 ! -name '.git' -exec rm -rf {} +
  rsync -a "$src"/ .
  git add -A
  GIT_AUTHOR_NAME="$AUTHOR_NAME" GIT_AUTHOR_EMAIL="$AUTHOR_EMAIL" \
    git commit -m "Import snapshot from $bn" || echo "[merge] no changes for $bn"
  if [[ "$PUSH_BRANCHES" == "1" ]]; then
    git push -u origin "$branch" || true
  fi
done

# Attempt independent merges of each import/* onto base (non-destructive)
for src in /data/sources/*; do
  [[ -d "$src" ]] || continue
  bn="$(basename "$src")"
  safe_bn="$(echo "$bn" | tr -c 'A-Za-z0-9._-' '-')"
  branch="import/${safe_bn}"
  work="merge-${safe_bn}"

  echo "[merge] try merge of $branch into $base_branch (branch: $work)"
  git checkout -B "$work" "$base_branch"
  if git merge --no-ff --no-commit "$branch"; then
    echo "$bn: MERGED CLEANLY" | tee -a "$report"
    git commit -m "Merge $branch into $base_branch"
  else
    echo "$bn: CONFLICTS" | tee -a "$report"
    git status --porcelain | awk '$1=="UU"{print "  - " $2}' >> "$report"
    git merge --abort || true
  fi

  if [[ "$PUSH_MERGES" == "1" ]]; then
    git push -u origin "$work" || true
  fi
done

echo "" >> "$report"
echo "Done. See individual merge-* branches (if pushed) and the list above." >> "$report"
echo "[merge] finished; report at $report"
EOS
chmod +x "$WORKDIR/merge.sh"

log "Building Docker image 'repo-collector:latest'..."
docker build -t repo-collector:latest "$WORKDIR" >/dev/null

# ---------- Optional host egress lockdown (containers OK) ----------
NFT_BACKUP="/tmp/nft.rules.backup.$RANDOM"
restore_nft() {
  if [[ -f "$NFT_BACKUP" ]]; then
    log "Restoring nftables rules..."
    nft -f "$NFT_BACKUP" || true
    rm -f "$NFT_BACKUP"
  fi
}
lockdown_start() {
  log "Saving current nftables rules..."
  nft list ruleset > "$NFT_BACKUP" || true
  log "Applying temporary egress lockdown (host OUTPUT drop; containers allowed)..."
  nft -f - <<'EON'
flush ruleset
table inet filter {
  chain input {
    type filter hook input priority 0;
    ct state established,related accept
    iifname "lo" accept
    iifname "docker0" accept
    # Allow DHCP/ICMP if needed (commented out by default)
    # udp dport 67-68 accept
    # icmp type echo-request accept
    counter drop
  }
  chain forward {
    type filter hook forward priority 0;
    ct state established,related accept
    iifname "docker0" accept
    oifname "docker0" accept
    counter drop
  }
  chain output {
    type filter hook output priority 0;
    ct state established,related accept
    oifname "lo" accept
    oifname "docker0" accept
    counter drop
  }
}
EON
}
trap restore_nft EXIT

if [[ "$DO_LOCKDOWN" == "1" ]]; then
  if [[ -n "${SSH_CONNECTION:-}" ]]; then
    log "WARNING: You're on SSH. Lockdown will likely drop your session."
  fi
  lockdown_start
fi

# ---------- Run merge container ----------
log "Running merge container..."
mkdir -p "$OUTPUT_DIR"
docker run --rm \
  -e GIT_TARGET_REPO="$TARGET_REPO" \
  -e BASE_BRANCH="$BASE_BRANCH" \
  -e GIT_PUSH_BRANCHES="$PUSH_BRANCHES" \
  -e GIT_PUSH_MERGES="$PUSH_MERGES" \
  -e GIT_AUTHOR_NAME="$AUTHOR_NAME" \
  -e GIT_AUTHOR_EMAIL="$AUTHOR_EMAIL" \
  -v "$ARCHIVE_DIR":/data:ro \
  -v "$OUTPUT_DIR":/work \
  repo-collector:latest

log "DONE."
echo "  Staged sources: $SRC_DIR"
echo "  Metadata:       $META_FILE"
echo "  Report:         $OUTPUT_DIR/merge_report.txt"
echo
[[ "$DO_LOCKDOWN" == "1" ]] && log "Lockdown removed."
