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

The helper writes the archive into the directory it runs from and prints its
absolute path. It refuses to replace anything already at that path — file,
directory or symlink, including one created while the build was running — so
re-running the same `DISTVERSION` means moving the old archive away first;
there is deliberately no force flag. The local archive also stays usable when
publishing fails afterwards. A published asset of the same name is never
replaced either: `gh release upload` fails instead, and replacing it is a
deliberate manual action on GitHub.

If publishing fails, upload the printed local archive rather than rebuilding,
because a rebuild will refuse to replace it:

    gh release upload <v-distversion> <printed PATH> --repo <owner>/silo-freebsd

## Publishing a version

One-time: create this repository on GitHub and push it.

    gh repo create silo-freebsd --public --source=. --push

For every port version (re-run when the pinned silo commit changes):

    ./make-vendor-release.sh <silo-server-ref> <distversion>

For example:

    ./make-vendor-release.sh 7696287dd4c617fecee6c980b8b500cb35b90697 0.0.0.20261009

It clones the given ref, runs `go mod vendor`, packs a normalised
`vendor/` tarball, attaches it to release `v<distversion>` and keeps the same
archive in the shell's working directory. It prints the SHA256 and the
`MASTER_SITES` line to paste into the port Makefile, after which run
`make makesum` in `multimedia/silo`.

The Go binary must satisfy the `go` directive of that ref's `go.mod`; there is
no single floor that covers every ref. On a FreeBSD build host use the matching
suffixed binary:

    GO=go127 ./make-vendor-release.sh <ref> <distversion>

For `Silo-Server/silo-server@217ff25` that means Go 1.27.4 or newer, which is
why the example uses `go127`. Check the ref's `go.mod` again after every pin
bump instead of copying this version forward.

## Updating the FreeBSD port

The `multimedia/silo` port pins exactly one silo-server commit. To move it to a
newer one:

1. Get the new ref:

       gh api repos/Silo-Server/silo-server/commits/main -q .sha

2. Build and publish the vendor tree for it. On a FreeBSD host use a `GO` whose
   version satisfies the new ref's `go.mod` (`go127` for the current pins) so
   the vendor matches the port's Go toolchain:

       GO=go127 ./make-vendor-release.sh <ref> <distversion>

   `<distversion>` is the commit's date, e.g. `0.0.0.20261015`; the release tag
   becomes `v<distversion>`. Keep the printed archive: it is the local copy of
   the asset.

3. In the port directory (`multimedia/silo`):

   - set `DISTVERSION` to `<distversion>` and `GH_TAGNAME` to `<ref>`;
   - delete any `PORTREVISION` line (a new version resets it to 0);
   - refresh the frontend manifests from the new source tree:

         cp <checkout>/web/package.json <checkout>/web/pnpm-lock.yaml files/packagejsons/

     then regenerate the generated store/archive and inspect the payload it
     produces rather than trusting the copy alone. Missing this breaks the
     build whenever dependencies change (it is how the `@webgpu/types` dep was
     caught);
   - if `package.json` or the lockfile changed, drop only that port's cached
     prefetch so it is rebuilt:

         rm "${DISTDIR:-/usr/ports/distfiles}/silo-server-<distversion>-node-modules.tar.gz"

     Do not wipe shared caches or distfiles directories. If the inputs did not
     change, the regenerated archive may legitimately hash the same as the
     previous one — that is not a reason to force a rebuild;
   - run `make makesum`.

4. Preflight the dependencies and build eligibility before any real build, and
   pass `BATCH=yes` so no options screen waits for a terminal:

        sudo env BATCH=yes poudriere testport -n -v -j <jail> -p <set> -o multimedia/silo

   A missing package, an unexpected dependency or an option change shows up
   here instead of after a long build. Then build for real:

        sudo env BATCH=yes poudriere testport -j <jail> -p <set> -o multimedia/silo

   `make stage` plus `stage-qa` is only a pre-check on a host without
   poudriere.

   For the patch series, read the actual patch files in the port's `files/`
   directory and the target blobs they touch at the new ref; do not work from a
   list copied out of this README. A patch whose target path or hunk changed
   will not apply and must be regenerated, and a file that a patch adds must
   still be absent upstream. Add or drop entries as the series changes.

## Requirements

git, `gh` (authenticated) unless `PUBLISH=0`, bsdtar (not GNU tar), gzip, and
`shasum` or `sha256sum`. The Go toolchain must satisfy the pinned ref's
`go.mod`; check that file rather than assuming a fixed minimum version.

The helper's own regressions run offline with the local toolchain:

    uv run --no-project python -m unittest discover -s tests -v
