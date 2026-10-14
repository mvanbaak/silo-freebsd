# silo-freebsd

Helper repository for the FreeBSD `multimedia/silo` port
(package `silo-server`).

The port's only non-upstream distfile is the **Go vendor tree**. The
`USES=npm` framework generates the pnpm tarball and the node-modules archive
itself from the public npm registry, and the source comes from GitHub — so
this repository exists solely to host the vendor tree at a stable public URL,
the same way `www/immich` hosts its buildkit on a GitHub release.

## Releases

One asset per Silo version:

    silo-<distversion>-vendor.tar.gz

Its root is `vendor/`, so the port extracts it straight into `${WRKSRC}`.

## Publishing a version

One-time: create this repository on GitHub and push it.

    gh repo create silo-freebsd --public --source=. --push

For every port version (re-run when the pinned silo commit changes):

    ./make-vendor-release.sh <silo-server-ref> <distversion>

For example:

    ./make-vendor-release.sh 7696287dd4c617fecee6c980b8b500cb35b90697 0.0.0.20261009

It clones the given ref, runs `go mod vendor`, packs a normalised
`vendor/` tarball, and attaches it to release `v<distversion>`. It prints the
SHA256 and the `MASTER_SITES` line to paste into the port Makefile, after
which run `make makesum` in `multimedia/silo`.

On a FreeBSD build host, use the suffixed Go binary:

    GO=go126 ./make-vendor-release.sh <ref> <distversion>

## Updating the FreeBSD port

The `multimedia/silo` port pins exactly one silo-server commit. To move it to a
newer one:

1. Get the new ref:

       gh api repos/Silo-Server/silo-server/commits/main -q .sha

2. Build and publish the vendor tree for it. On a FreeBSD host use `GO=go126` so
   the vendor matches the port's Go toolchain:

       GO=go126 ./make-vendor-release.sh <ref> <distversion>

   `<distversion>` is the commit's date, e.g. `0.0.0.20261015`; the release tag
   becomes `v<distversion>`.

3. In the port directory (`multimedia/silo`):

   - set `DISTVERSION` to `<distversion>` and `GH_TAGNAME` to `<ref>`;
   - delete any `PORTREVISION` line (a new version resets it to 0);
   - refresh the frontend manifests from the new source tree:

         cp <checkout>/web/package.json <checkout>/web/pnpm-lock.yaml files/packagejsons/

     Missing this breaks the build whenever dependencies change (it is how the
     `@webgpu/types` dep was caught);
   - if the lockfile changed, drop the cached prefetch so it is rebuilt:

         rm "${DISTDIR:-/usr/ports/distfiles}/silo-server-<distversion>-node-modules.tar.gz"

   - run `make makesum`.

4. `make stage check-plist` must build clean. The port patches four upstream
   paths; if any changed between refs the patches will not apply and must be
   regenerated:

   - `internal/plugins/binary_platform.go`
   - `internal/plugins/catalog_channels.go`
   - `internal/plugins/catalog_settings.go`
   - `internal/jellycompat/process_token_other.go` (added by a patch; it must
     still be absent upstream)

## Requirements

git, Go >= 1.26, `gh` (authenticated) unless `PUBLISH=0`, bsdtar, and
`shasum` or `sha256sum`.
