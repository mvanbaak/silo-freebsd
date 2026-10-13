#!/bin/sh
# Build the offline Go vendor distfile for a Silo-Server/silo-server ref and
# attach it to a GitHub release in this helper repository.
#
#   Usage: ./make-vendor-release.sh <silo-server-ref> <distversion>
#
#     silo-server-ref  commit SHA, tag, or branch of Silo-Server/silo-server
#     distversion      the port's DISTVERSION, e.g. 0.0.0.20261013
#                      (the release tag becomes v<distversion>)
#
#   Environment:
#     REPO=owner/name   publish target (default: this repository)
#     GO=go126          go binary to use (default: go)
#     PUBLISH=0         build the asset only, skip the GitHub release
#
#   Requires: git, go >= 1.26, gh (authenticated) unless PUBLISH=0,
#             shasum or sha256sum, and bsdtar.
set -eu

REF=${1:?usage: $0 <silo-server-ref> <distversion>}
DISTVERSION=${2:?usage: $0 <silo-server-ref> <distversion>}
GO=${GO:-go}
PUBLISH=${PUBLISH:-1}

ASSET="silo-${DISTVERSION}-vendor.tar.gz"
TAG="v${DISTVERSION}"

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT INT TERM

echo "==> fetching Silo-Server/silo-server@${REF}"
git init --quiet "$work/silo"
git -C "$work/silo" remote add origin https://github.com/Silo-Server/silo-server.git
git -C "$work/silo" fetch --quiet --depth 1 origin "$REF"
git -C "$work/silo" checkout --quiet FETCH_HEAD

echo "==> go mod vendor"
( cd "$work/silo" && "$GO" mod vendor )

echo "==> packaging ${ASSET} (root=vendor/, reproducible)"
(
	cd "$work/silo"
	find vendor -print | LC_ALL=C sort > "$work/vendor.list"
	# Touch children first so directory mtimes settle after their entries.
	LC_ALL=C sort -r "$work/vendor.list" |
		while IFS= read -r p; do touch -h -t 198001010000 "$p"; done
	tar --uid 0 --gid 0 --uname root --gname wheel --no-recursion \
		-cf "$work/vendor.tar" -T "$work/vendor.list"
	gzip -9 -n -c "$work/vendor.tar" > "$work/${ASSET}"
)

sha=$( (sha256sum "$work/${ASSET}" 2>/dev/null || shasum -a 256 "$work/${ASSET}") | awk '{print $1}')
size=$(wc -c < "$work/${ASSET}" | tr -d ' ')

if [ "$PUBLISH" = 1 ]; then
	: "${REPO:=$(gh repo view --json nameWithOwner -q .nameWithOwner)}"
	echo "==> publishing release ${TAG} in ${REPO}"
	gh release view "$TAG" --repo "$REPO" >/dev/null 2>&1 || \
		gh release create "$TAG" --repo "$REPO" \
			--title "silo ${DISTVERSION} vendor tree" \
			--notes "Offline Go vendor tree for Silo-Server/silo-server@${REF}."
	gh release upload "$TAG" "$work/${ASSET}" --repo "$REPO" --clobber
fi

echo "==> done"
echo "  ASSET   ${ASSET}"
echo "  SIZE    ${size}"
echo "  SHA256  ${sha}"
echo
echo "Point the port at it and refresh checksums:"
echo
printf '  DISTVERSION=\t%s\n' "${DISTVERSION}"
if [ -n "${REPO:-}" ]; then
	printf '  MASTER_SITES+=\thttps://github.com/%s/releases/download/%s/:vendor\n' "${REPO}" "${TAG}"
else
	printf '  MASTER_SITES+=\thttps://github.com/<owner>/silo-freebsd/releases/download/%s/:vendor\n' "${TAG}"
fi
echo
echo "  cd multimedia/silo && make makesum"
