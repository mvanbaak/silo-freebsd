"""Offline regressions for make-vendor-release.sh.

Real git, Go (mod vendor), bsdtar and gzip run against a tiny local source
fixture; the only stand-in is `gh`, which models the publishing boundary
(new release, existing asset, failed upload).  No network access.
"""

import gzip
import hashlib
import os
import pathlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "make-vendor-release.sh"
GO = os.environ.get("GO_BIN") or shutil.which("go") or "/opt/homebrew/bin/go"

DEP_GO_MOD = "module example.com/dep\n\ngo 1.27.4\n"
DEP_SRC = 'package dep\n\nconst Name = "dep"\n'
MAIN_SRC = 'package main\n\nimport (\n\t"fmt"\n\n\t"example.com/dep"\n)\n\nfunc main() { fmt.Println(dep.Name) }\n'
SILO_GO_MOD = (
    "module example.com/silo\n\n"
    "go 1.27.4\n\n"
    "require example.com/dep v0.0.0\n\n"
    "replace example.com/dep => ./deps/dep\n"
)

FAKE_GH = '''#!{python}
import os, pathlib, sys

state = pathlib.Path(os.environ["FAKE_GH_STATE"])
args = sys.argv[1:]

if args[:2] == ["repo", "view"]:
    print("test/repo")
    sys.exit(0)
if not args or args[0] != "release":
    sys.exit(2)

command, tag = args[1], args[2]
releases = state / "releases"

if command == "view":
    sys.exit(0 if (releases / tag).is_dir() else 1)
if command == "create":
    (releases / tag).mkdir(parents=True, exist_ok=True)
    sys.exit(0)
if command == "upload":
    if os.environ.get("FAKE_GH_FAIL_UPLOAD"):
        sys.stderr.write("gh: upload failed\\n")
        sys.exit(1)
    asset = releases / tag / pathlib.Path(args[3]).name
    if asset.exists() and "--clobber" not in args:
        sys.stderr.write("gh: asset already exists\\n")
        sys.exit(1)
    asset.write_bytes(pathlib.Path(args[3]).read_bytes())
    sys.exit(0)
sys.exit(2)
'''


def sha256(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def run(cmd, cwd=None, env=None):
    return subprocess.run(
        cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=600
    )


class VendorReleaseTest(unittest.TestCase):
    distversion = "0.0.0.20261117"
    asset = "silo-%s-vendor.tar.gz" % distversion
    tag = "v%s" % distversion

    def setUp(self):
        for tool in (GO, shutil.which("bsdtar"), shutil.which("gzip"), shutil.which("git")):
            if not tool or not os.path.exists(tool):
                self.skipTest("missing required tool: %r" % tool)
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="vendor-test-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.state = self.root / "gh-state"
        self.state.mkdir()
        (self.root / "home").mkdir()
        self.gitconfig = self.root / "gitconfig"
        self.ghbin = self.root / "bin"
        self.ghbin.mkdir()
        gh = self.ghbin / "gh"
        gh.write_text(FAKE_GH.format(python=sys.executable))
        gh.chmod(0o755)
        self.fixture = self.make_fixture("source")
        self.gitconfig.write_text(
            '[url "file://%s"]\n\tinsteadOf = https://github.com/Silo-Server/silo-server.git\n'
            % self.fixture
        )

    # -- fixture ---------------------------------------------------------
    def make_fixture(self, name, executable_dep=False):
        src = self.root / name
        (src / "deps" / "dep").mkdir(parents=True)
        (src / "go.mod").write_text(SILO_GO_MOD)
        (src / "main.go").write_text(MAIN_SRC)
        (src / "deps" / "dep" / "go.mod").write_text(DEP_GO_MOD)
        dep = src / "deps" / "dep" / "dep.go"
        dep.write_text(DEP_SRC)
        dep.chmod(0o755 if executable_dep else 0o644)

        env = self.env()
        for cmd in (
            ["git", "init", "--quiet"],
            ["git", "add", "-A"],
            ["git", "commit", "--quiet", "-m", "fixture"],
            ["git", "tag", "v1.0.0"],
        ):
            done = run(cmd, cwd=src, env=env)
            self.assertEqual(done.returncode, 0, done.stderr)
        return src

    def env(self):
        gohome = self.root / "gohome"
        env = {
            "PATH": "%s:%s" % (self.ghbin, os.environ["PATH"]),
            "HOME": str(self.root / "home"),
            "TMPDIR": str(self.root),
            "GIT_CONFIG_GLOBAL": str(self.gitconfig),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.invalid",
            "GOTOOLCHAIN": "local",
            "GOPROXY": "off",
            "GOSUMDB": "off",
            "GOPATH": str(gohome / "gopath"),
            "GOMODCACHE": str(gohome / "gopath" / "pkg" / "mod"),
            "GOCACHE": str(gohome / "gocache"),
            "GO": GO,
            "REPO": "test/repo",
            "FAKE_GH_STATE": str(self.state),
        }
        return env

    def outdir(self, name):
        out = self.root / ("out-" + name)
        out.mkdir()
        return out

    def build(self, name, distversion=None, env=None, umask=None, ref="v1.0.0"):
        out = self.outdir(name)
        run_env = dict(self.env() if env is None else env)
        preexec = (lambda: os.umask(umask)) if umask is not None else None
        done = subprocess.run(
            [str(SCRIPT), ref, distversion or self.distversion],
            cwd=out,
            env=run_env,
            capture_output=True,
            text=True,
            timeout=600,
            preexec_fn=preexec,
        )
        return out, done

    def asset_path(self, out):
        return out / self.asset

    def printed_path(self, stdout):
        for line in stdout.splitlines():
            if line.strip().startswith("PATH"):
                return line.split(None, 1)[1]
        return None

    def remote_asset(self):
        return self.state / "releases" / self.tag / self.asset

    # -- assertions ------------------------------------------------------
    def assert_normalised_archive(self, path):
        self.assertTrue(path.is_file(), "missing archive %s" % path)
        raw = path.read_bytes()
        self.assertEqual(raw[:2], b"\x1f\x8b")
        self.assertEqual(raw[3], 0, "gzip flags should be empty (-n)")
        self.assertEqual(raw[4:8], b"\0\0\0\0", "gzip mtime should be zero")
        with tarfile.open(path) as tar:
            members = tar.getmembers()
        names = [m.name for m in members]
        self.assertEqual(names, sorted(names), "entry list not sorted")
        self.assertIn("vendor/modules.txt", names)
        self.assertIn("vendor/example.com/dep/dep.go", names)
        for member in members:
            self.assertTrue(member.name == "vendor" or member.name.startswith("vendor/"),
                            member.name)
            self.assertEqual(member.mtime, 315532800, member.name)
            self.assertEqual((member.uid, member.gid), (0, 0), member.name)
            self.assertEqual((member.uname, member.gname), ("root", "wheel"), member.name)
            expected = 0o755 if member.isdir() else 0o644
            self.assertEqual(member.mode, expected, member.name)
        return path

    # -- tests -----------------------------------------------------------
    def test_build_only_keeps_archive_in_caller_directory(self):
        out, done = self.build("build-only", env=dict(self.env(), PUBLISH="0"))
        self.assertEqual(done.returncode, 0, done.stderr)
        path = self.asset_path(out)
        self.assert_normalised_archive(path)
        self.assertEqual(self.printed_path(done.stdout), str(path.resolve()))
        self.assertEqual([p.name for p in out.iterdir()], [self.asset])

    def test_identical_bytes_across_tz_umask_and_source_modes(self):
        _, first = self.build("det-a", env=dict(self.env(), PUBLISH="0", TZ="UTC"), umask=0o022)
        self.assertEqual(first.returncode, 0, first.stderr)
        fixture = self.make_fixture("source-exec", executable_dep=True)
        self.gitconfig.write_text(
            '[url "file://%s"]\n\tinsteadOf = https://github.com/Silo-Server/silo-server.git\n'
            % fixture
        )
        second_out, second = self.build(
            "det-b", env=dict(self.env(), PUBLISH="0", TZ="Pacific/Kiritimati"), umask=0o077
        )
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertTrue(self.asset_path(second_out).is_file())
        self.assertEqual(
            sha256(self.asset_path(second_out)),
            sha256(self.root / "out-det-a" / self.asset),
        )

    def test_existing_local_artifact_is_never_overwritten(self):
        out = self.outdir("local-exists")
        target = out / self.asset
        target.write_bytes(b"do not replace me")
        done = subprocess.run(
            [str(SCRIPT), "v1.0.0", self.distversion],
            cwd=out,
            env=dict(self.env(), PUBLISH="0"),
            capture_output=True,
            text=True,
            timeout=600,
        )
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(target.read_bytes(), b"do not replace me")

    def test_invalid_distversion_is_rejected_before_writing(self):
        for index, bad in enumerate(("../escape", "1.0/2", ".hidden", "-1.0")):
            out, done = self.build("bad-version-%d" % index, distversion=bad,
                                   env=dict(self.env(), PUBLISH="0"))
            self.assertNotEqual(done.returncode, 0, bad)
            self.assertEqual(list(out.iterdir()), [], bad)
            self.assertFalse((self.root / "escape-vendor.tar.gz").exists(), bad)

    def test_existing_remote_asset_is_refused_and_local_archive_kept(self):
        remote = self.remote_asset()
        remote.parent.mkdir(parents=True)
        remote.write_bytes(b"published bytes")
        out, done = self.build("remote-exists")
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(remote.read_bytes(), b"published bytes")
        self.assert_normalised_archive(self.asset_path(out))
        self.assertEqual([p.name for p in out.iterdir()], [self.asset])

    def test_new_publication_uploads_the_local_bytes(self):
        out, done = self.build("publish")
        self.assertEqual(done.returncode, 0, done.stderr)
        local = self.assert_normalised_archive(self.asset_path(out))
        remote_sha = sha256(self.remote_asset())
        self.assertEqual(remote_sha, sha256(local))
        self.assertIn(remote_sha, done.stdout)
        self.assertIn("%d" % local.stat().st_size, done.stdout)

    def test_existing_release_without_asset_accepts_upload(self):
        (self.state / "releases" / self.tag).mkdir(parents=True)
        out, done = self.build("publish-existing-release")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assert_normalised_archive(self.asset_path(out))
        self.assertEqual(sha256(self.remote_asset()), sha256(self.asset_path(out)))

    def test_failed_publish_keeps_usable_local_archive(self):
        out, done = self.build("publish-fail", env=dict(self.env(), FAKE_GH_FAIL_UPLOAD="1"))
        self.assertNotEqual(done.returncode, 0)
        local = self.assert_normalised_archive(self.asset_path(out))
        self.assertIn(sha256(local), done.stdout)
        self.assertFalse(self.remote_asset().exists())
        self.assertEqual([p.name for p in out.iterdir()], [self.asset])

    def go_wrapper(self):
        """Real Go plus a fault that creates the target before the save step.

        Only the external producer is wrapped; the archive and save behaviour
        stays real.
        """
        wrapper = self.root / "wrap-go"
        wrapper.write_text(
            "#!/bin/sh\n"
            '"%s" "$@" || exit $?\n'
            "case $RACE_KIND in\n"
            "\tfile) printf 'raced\\n' > \"$RACE_TARGET\" ;;\n"
            "\tdir) mkdir \"$RACE_TARGET\" && printf 'keep\\n' > \"$RACE_TARGET/sentinel\" ;;\n"
            '\tsymlink) ln -s /nonexistent-target "$RACE_TARGET" ;;\n'
            "\t*) exit 3 ;;\n"
            "esac\n" % GO
        )
        wrapper.chmod(0o755)
        return wrapper

    def test_preexisting_dangling_symlink_is_refused_before_build(self):
        out = self.outdir("dangling")
        target = out / self.asset
        target.symlink_to("/nonexistent-target")
        marker = self.root / "producer-ran"
        wrapper = self.root / "wrap-go-marker"
        wrapper.write_text(
            "#!/bin/sh\ntouch '%s'\nexec '%s' \"$@\"\n" % (marker, GO)
        )
        wrapper.chmod(0o755)
        done = run(
            [str(SCRIPT), "v1.0.0", self.distversion],
            cwd=out,
            env=dict(self.env(), PUBLISH="0", GO=str(wrapper)),
        )
        self.assertNotEqual(done.returncode, 0)
        self.assertTrue(target.is_symlink())
        self.assertEqual(os.readlink(target), "/nonexistent-target")
        self.assertFalse(marker.exists(), "producer ran despite the existing target")
        self.assertEqual(sorted(p.name for p in out.iterdir()), [self.asset])

    def test_uncompressed_tar_uses_canonical_stdout_blocking(self):
        # The verified recipe pipes tar's stdout, so the stream carries the
        # canonical 20-record blocking even when written to a file here.
        # Deliberate pinned-recipe contract for this distfile, not a claim of
        # portable tar framing across implementations.
        out, done = self.build("blocking", env=dict(self.env(), PUBLISH="0"))
        self.assertEqual(done.returncode, 0, done.stderr)
        raw = gzip.decompress(self.asset_path(out).read_bytes())
        self.assertEqual(len(raw) % 10240, 0, "%d bytes" % len(raw))
        self.assertEqual(len(raw), 10240, "%d bytes" % len(raw))

    def test_artifact_created_during_build_is_refused(self):
        for kind in ("file", "dir", "symlink"):
            with self.subTest(kind=kind):
                out = self.outdir("race-" + kind)
                target = out / self.asset
                env = dict(self.env(), PUBLISH="0", GO=str(self.go_wrapper()),
                           RACE_KIND=kind, RACE_TARGET=str(target))
                done = run([str(SCRIPT), "v1.0.0", self.distversion], cwd=out, env=env)
                self.assertNotEqual(done.returncode, 0, kind)
                self.assertEqual(sorted(p.name for p in out.iterdir()), [self.asset], kind)
                if kind == "dir":
                    self.assertEqual(sorted(p.name for p in target.iterdir()), ["sentinel"])
                    self.assertEqual((target / "sentinel").read_text(), "keep\n")
                elif kind == "file":
                    self.assertEqual(target.read_text(), "raced\n")
                else:
                    self.assertTrue(target.is_symlink())
                    self.assertEqual(os.readlink(target), "/nonexistent-target")

    def test_hash_tool_failure_stops_before_publishing(self):
        bad = self.root / "badhash"
        bad.mkdir()
        for name in ("sha256sum", "shasum"):
            tool = bad / name
            tool.write_text("#!/bin/sh\necho 'hash tool broken' >&2\nexit 1\n")
            tool.chmod(0o755)
        env = dict(self.env(), PUBLISH="1")
        env["PATH"] = "%s:%s" % (bad, env["PATH"])
        out, done = self.build("hash-fail", env=env)
        self.assertNotEqual(done.returncode, 0)
        self.assertFalse(self.remote_asset().exists())
        self.assertEqual(list(out.iterdir()), [], "staging or final artifact left behind")

    def test_unresolvable_ref_propagates_failure(self):
        out, done = self.build("bad-ref", env=dict(self.env(), PUBLISH="0"), ref="v9.9.9")
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(list(out.iterdir()), [])

    def test_go_vendor_failure_propagates_without_artifact(self):
        src = self.root / "broken"
        src.mkdir()
        (src / "go.mod").write_text(
            "module example.com/silo\n\ngo 1.27.4\n\nrequire example.com/missing v0.0.0\n"
        )
        (src / "main.go").write_text('package main\n\nimport _ "example.com/missing"\n')
        for cmd in (["git", "init", "--quiet"], ["git", "add", "-A"],
                    ["git", "commit", "--quiet", "-m", "fixture"], ["git", "tag", "v1.0.0"]):
            done = run(cmd, cwd=src, env=self.env())
            self.assertEqual(done.returncode, 0, done.stderr)
        self.gitconfig.write_text(
            '[url "file://%s"]\n\tinsteadOf = https://github.com/Silo-Server/silo-server.git\n'
            % src
        )
        out, done = self.build("vendor-fail", env=dict(self.env(), PUBLISH="0"))
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(list(out.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
