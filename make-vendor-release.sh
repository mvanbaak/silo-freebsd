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
#     GO=go127          go binary to use (default: go); it must satisfy the
#                       go directive of the ref's go.mod
#     PUBLISH=0         build the asset only, skip the GitHub release
#
#   The archive is written into the current directory and is kept when
#   publishing fails. An existing local or published asset of the same name is
#   never replaced.
#
#   Requires: git, a Go toolchain matching the pinned go.mod, gh
#             (authenticated) unless PUBLISH=0, shasum or sha256sum, bsdtar
#             and gzip.
set -eu

REF=${1:?usage: $0 <silo-server-ref> <distversion>}
DISTVERSION=${2:?usage: $0 <silo-server-ref> <distversion>}
GO=${GO:-go}
PUBLISH=${PUBLISH:-1}

# DISTVERSION becomes part of the asset filename, so reject anything that
# could escape the output directory or produce a hidden/option-like name.
case $DISTVERSION in
	"" | .* | -* | *[!0-9A-Za-z._-]* | *..*)
		echo "invalid DISTVERSION: ${DISTVERSION}" >&2
		exit 2
		;;
esac

ASSET="silo-${DISTVERSION}-vendor.tar.gz"
TAG="v${DISTVERSION}"

outdir=$(pwd -P)
dest="${outdir}/${ASSET}"
# -L catches a dangling symlink, which -e does not.
if [ -e "$dest" ] || [ -L "$dest" ]; then
	echo "refusing to overwrite existing ${dest}" >&2
	exit 1
fi

work=$(mktemp -d)
staging=
trap 'rm -rf "$work"; [ -z "$staging" ] || rm -f "$staging"' EXIT INT TERM

# Same directory as the final name, so the archive can be linked into place
# without a cross-device copy and without ever clobbering an existing file.
staging=$(mktemp "${outdir}/.${ASSET}.XXXXXX")

echo "==> fetching Silo-Server/silo-server@${REF}"
git init --quiet "$work/silo"
git -C "$work/silo" remote add origin https://github.com/Silo-Server/silo-server.git
git -C "$work/silo" fetch --quiet --depth 1 origin "$REF"
git -C "$work/silo" checkout --quiet FETCH_HEAD
commit=$(git -C "$work/silo" rev-parse HEAD)
echo "==> resolved ${commit}"

echo "==> go mod vendor"
( cd "$work/silo" && "$GO" mod vendor )

echo "==> packaging ${ASSET} (root=vendor/, reproducible)"
(
	cd "$work/silo"
	export TZ=UTC LC_ALL=C
	find vendor -print | sort > "$work/vendor.list"
	# Children first so directory mtimes settle after their entries.
	sort -r "$work/vendor.list" |
		while IFS= read -r p; do
			if [ -L "$p" ]; then
				: # chmod would follow the link; only the timestamp is set
			elif [ -d "$p" ]; then
				chmod 0755 "$p"
			else
				chmod 0644 "$p"
			fi
			touch -h -t 198001010000.00 "$p"
		done
	# tar and gzip run as separate commands so a failure of either one fails
	# the script instead of being masked by a pipeline. tar writes to stdout
	# and into a file here, which keeps the canonical blocking of the stream
	# the recipe pipes (`-cf file` truncates the trailing padding).
	bsdtar --uid 0 --gid 0 --uname root --gname wheel --no-recursion \
		-cf - -T "$work/vendor.list" > "$work/vendor.tar"
	gzip -9 -n -c "$work/vendor.tar" > "$staging"
)

size=$(wc -c < "$staging" | tr -d ' ')
if sha_out=$(sha256sum "$staging" 2>/dev/null); then
	:
elif sha_out=$(shasum -a 256 "$staging"); then
	:
else
	echo "no working sha256sum or shasum for ${staging}" >&2
	exit 1
fi
sha=${sha_out%%[[:space:]]*}
if [ -z "$sha" ]; then
	echo "empty SHA256 from the hash tool for ${staging}" >&2
	exit 1
fi
chmod 0644 "$staging"
# link(1), not ln(1): ln treats a directory at $dest as a target directory and
# silently hardlinks inside it. link only ever creates $dest itself.
if ! link "$staging" "$dest"; then
	echo "refusing to overwrite existing ${dest}" >&2
	exit 1
fi
rm -f "$staging"
staging=

echo "==> built ${dest}"
echo "  ASSET   ${ASSET}"
echo "  PATH    ${dest}"
echo "  SIZE    ${size}"
echo "  SHA256  ${sha}"
echo

if [ "$PUBLISH" = 1 ]; then
	: "${REPO:=$(gh repo view --json nameWithOwner -q .nameWithOwner)}"
	echo "==> publishing release ${TAG} in ${REPO}"
	gh release view "$TAG" --repo "$REPO" >/dev/null 2>&1 || \
		gh release create "$TAG" --repo "$REPO" \
			--title "silo ${DISTVERSION} vendor tree" \
			--notes "Offline Go vendor tree for Silo-Server/silo-server@${commit}."
	# No --clobber: gh refuses an existing asset, so a published archive is
	# never replaced. The local copy above stays usable when this fails.
	gh release upload "$TAG" "$dest" --repo "$REPO"
	echo "==> uploaded ${ASSET}"
fi

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
