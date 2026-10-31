"""The repository's pre-commit hook (dev/git-hooks/pre-commit) refuses anything staged under desktop-assets/,
which .gitignore already ignores: release inputs and personal-use looks are never committed, even with
`git add -f`. Each test runs git in a scratch repository with the hook installed through core.hooksPath."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

HOOK = Path(__file__).resolve().parents[1] / 'git-hooks/pre-commit'


def git(repo, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@example.invalid',
               GIT_COMMITTER_NAME='t', GIT_COMMITTER_EMAIL='t@example.invalid')
    return subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True, env=env)


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, 'init', '-q')
    hooks = tmp_path / 'dev/git-hooks'
    hooks.mkdir(parents=True)
    shutil.copy2(HOOK, hooks / 'pre-commit')
    git(tmp_path, 'config', 'core.hooksPath', 'dev/git-hooks')
    (tmp_path / '.gitignore').write_text('desktop-assets/\n')
    return tmp_path


def test_the_hook_is_executable():
    assert os.access(HOOK, os.X_OK)


def test_a_commit_without_desktop_assets_goes_through(repo):
    (repo / 'notes.txt').write_text('hello\n')
    git(repo, 'add', 'notes.txt', '.gitignore')
    assert git(repo, 'commit', '-q', '-m', 'notes').returncode == 0


@pytest.mark.parametrize('path', ['desktop-assets/personal/presets/personal-six-v1/slot1.a7look',
                                  'desktop-assets/film-looks-v1/portra400.a7look'])
def test_a_forced_add_under_desktop_assets_is_refused(repo, path):
    target = repo / path
    target.parent.mkdir(parents=True)
    target.write_bytes(b'look')
    assert git(repo, 'add', '-f', path).returncode == 0
    result = git(repo, 'commit', '-q', '-m', 'oops')
    assert result.returncode != 0
    assert path in result.stderr and 'desktop-assets/' in result.stderr
    assert git(repo, 'rev-parse', '--verify', '-q', 'HEAD').returncode != 0  # nothing was committed
