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

## Requirements

git, Go >= 1.26, `gh` (authenticated) unless `PUBLISH=0`, bsdtar, and
`shasum` or `sha256sum`.
