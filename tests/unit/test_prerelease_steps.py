"""prerelease.yml's real `run:` blocks on a real bash, in throwaway git repos, with `gh` faked.

GitHub lists releases newest-created first, so after a re-run of an older master run its build is listed
first.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
JOBS = yaml.safe_load((ROOT / ".github/workflows/prerelease.yml").read_text(encoding="utf-8"))["jobs"]
SHIPS = next(s["run"] for s in JOBS["ships"]["steps"] if s.get("id") == "ships")
KEEP = next(
    s["run"] for s in JOBS["prerelease"]["steps"] if s.get("name") == "Keep the newest 10 CI pre-releases"
)
BASH = shutil.which("bash")
# Windows' own bash.exe starts WSL, not a shell for these files
pytestmark = pytest.mark.skipif(
    BASH is None or "system32" in BASH.lower(), reason="needs bash (Git for Windows' or Linux')"
)


def _listed(*runs: int) -> str:
    return json.dumps([{"tagName": f"v1.1.0-ci.{n}", "isPrerelease": True} for n in runs])


def _gh(listing: str) -> str:
    """A fake gh: `release list` prints the listing, `release delete TAG` notes TAG in deleted.txt."""
    return (
        f"gh() {{ if [ \"$2\" = list ]; then printf '%s' '{listing}'; "
        'elif [ "$2" = delete ]; then echo "$3" >> deleted.txt; fi; }'
    )


GH_DOWN = "gh() { return 1; }"


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def _commit(repo: Path, files: dict[str, str]) -> str:
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "change")
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """The workflow's checkout: its tools, and a master with a code change in ci.7 and another in ci.8."""
    _git(tmp_path, "init", "-q", "-b", "master")
    (tmp_path / "tools").mkdir()
    for name in ("ci_scope.py", "ci_prereleases.py"):
        shutil.copy(ROOT / "tools" / name, tmp_path / "tools" / name)
    _commit(tmp_path, {"README.md": "a\n", "src/app.py": "x = 1\n"})
    _commit(tmp_path, {"src/app.py": "x = 2\n"})
    _git(tmp_path, "tag", "v1.1.0-ci.7")
    _commit(tmp_path, {"src/b.py": "y = 1\n"})
    _git(tmp_path, "tag", "v1.1.0-ci.8")
    return tmp_path


def _run(repo: Path, block: str, gh: str, head: str = "") -> subprocess.CompletedProcess[str]:
    (repo / "out.txt").write_text("", encoding="utf-8")
    (repo / "deleted.txt").write_text("", encoding="utf-8")
    (repo / "step.sh").write_text(block, encoding="utf-8", newline="\n")
    python = Path(sys.executable).as_posix()
    script = f'python3() {{ "{python}" "$@"; }}\n{gh}\n. ./step.sh\n'
    env = {**os.environ, "GITHUB_OUTPUT": "out.txt", "HEAD_SHA": head}
    assert BASH is not None
    # `bash -e`: how GitHub runs a step that names no shell
    return subprocess.run([BASH, "-e", "-c", script], cwd=repo, capture_output=True, text=True, env=env)  # noqa: S603


def _ships(repo: Path, gh: str, head: str) -> str:
    done = _run(repo, SHIPS, gh, head)
    assert done.returncode == 0, done.stderr
    outputs = dict(line.split("=", 1) for line in (repo / "out.txt").read_text(encoding="utf-8").splitlines())
    return outputs["ships"]


def test_a_text_merge_after_a_rerun_publishes_nothing(repo: Path) -> None:
    """ci.7 was re-run and published after ci.8: the merge is compared with ci.8, the newest build."""
    head = _commit(repo, {"CHANGELOG.md": "b\n"})
    assert _ships(repo, _gh(_listed(7, 8)), head) == "false"


def test_a_code_change_publishes(repo: Path) -> None:
    head = _commit(repo, {"src/app.py": "x = 3\n"})
    assert _ships(repo, _gh(_listed(7, 8)), head) == "true"


@pytest.mark.parametrize(
    "gh",
    [_gh("[]"), GH_DOWN, _gh("not json"), _gh(_listed(9))],
    ids=["no CI pre-release yet", "GitHub did not answer", "an unreadable answer", "its tag is not here"],
)
def test_what_cannot_be_compared_publishes(repo: Path, gh: str) -> None:
    head = _commit(repo, {"CHANGELOG.md": "b\n"})
    assert _ships(repo, gh, head) == "true"


def test_keep_deletes_beyond_the_ten_newest_builds(repo: Path) -> None:
    done = _run(repo, KEEP, _gh(_listed(7, 12, 11, 10, 9, 8, 6, 5, 4, 3, 2, 1)))
    assert done.returncode == 0, done.stderr
    assert (repo / "deleted.txt").read_text(encoding="utf-8").split() == ["v1.1.0-ci.1", "v1.1.0-ci.2"]


def test_keep_deletes_nothing_under_ten(repo: Path) -> None:
    done = _run(repo, KEEP, _gh(_listed(3, 2, 1)))
    assert done.returncode == 0, done.stderr
    assert (repo / "deleted.txt").read_text(encoding="utf-8") == ""


@pytest.mark.parametrize(
    "gh", [GH_DOWN, _gh("not json")], ids=["GitHub did not answer", "an unreadable answer"]
)
def test_keep_fails_when_it_cannot_read_the_list(repo: Path, gh: str) -> None:
    """A retention that silently did nothing would let CI pre-releases pile up unseen."""
    done = _run(repo, KEEP, gh)
    assert done.returncode != 0
    assert (repo / "deleted.txt").read_text(encoding="utf-8") == ""
