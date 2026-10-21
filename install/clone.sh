#!/usr/bin/env sh
# Optional clone-and-setup entry point. Review this script before running it.
set -eu
if [ "$#" -lt 1 ]; then
    printf '%s\n' 'Usage: sh clone.sh NEW_CHECKOUT [install.sh options; --yes permits cloning]'
    exit 2
fi
CHECKOUT=$1
shift
YES=0 DRY=0 OFFLINE=0
for arg in "$@"; do
    case "$arg" in --yes) YES=1;; --dry-run|--check) DRY=1;; --offline) OFFLINE=1;; esac
done
printf 'Clone https://github.com/BlehMaks/find-me-a-job.git into %s, then run its reviewed installer.\n' "$CHECKOUT"
if [ "$YES" -eq 0 ] || [ "$DRY" -eq 1 ]; then exit 0; fi
[ "$OFFLINE" -eq 0 ] || { printf '%s\n' 'Cloning requires network access; use an existing checkout for offline setup.' >&2; exit 2; }
[ ! -e "$CHECKOUT" ] && [ ! -L "$CHECKOUT" ] || { printf '%s\n' 'Checkout already exists; open it and resume install/install.sh. Nothing overwritten.' >&2; exit 2; }
command -v git >/dev/null 2>&1 || { printf '%s\n' 'Install Git or clone with GitHub Desktop, then run install/install.sh.' >&2; exit 2; }
git clone -- https://github.com/BlehMaks/find-me-a-job.git "$CHECKOUT"
exec sh "$CHECKOUT/install/install.sh" "$@"
