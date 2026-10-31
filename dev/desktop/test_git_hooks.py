"""The repository's pre-commit hook (dev/git-hooks/pre-commit). .gitignore ignores desktop-assets/; the hook
stops a forced `git add -f`: the personal root never, and the public release inputs only on a build/release-*
branch, where release.yml expects them in the last commit. Each test runs git in a scratch repository with
the hook installed through core.hooksPath."""
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


def stage(repo, path):
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b'look')
    assert git(repo, 'add', '-f', path).returncode == 0


def refused(repo, path):
    result = git(repo, 'commit', '-q', '-m', 'oops')
    return result.returncode != 0 and path in result.stderr


PERSONAL = 'desktop-assets/personal/presets/personal-six-v1/slot1.a7look'
PUBLIC = 'desktop-assets/film-looks-v1/portra400.a7look'


@pytest.mark.parametrize('branch', ['main', 'build/release-3.0.3'])
def test_the_personal_root_is_refused_on_every_branch(repo, branch):
    git(repo, 'checkout', '-q', '-b', branch)
    stage(repo, PERSONAL)
    assert refused(repo, PERSONAL)
    assert git(repo, 'rev-parse', '--verify', '-q', 'HEAD').returncode != 0  # nothing was committed


def test_public_release_inputs_are_refused_outside_a_release_branch(repo):
    git(repo, 'checkout', '-q', '-b', 'main')
    stage(repo, PUBLIC)
    assert refused(repo, PUBLIC)


def test_a_release_branch_commits_the_public_release_inputs(repo):
    git(repo, 'checkout', '-q', '-b', 'build/release-3.0.3')
    stage(repo, PUBLIC)
    assert git(repo, 'commit', '-q', '-m', 'release inputs').returncode == 0
