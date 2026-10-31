"""release.yml's second entry point: a published release (or a manual run naming one) builds the Windows
and Apple Silicon packages from that release's source and its public assets zip, with the same tests and
packaged checks as a release branch, and publishes them as a separate pre-release marked untested. The
release-branch flow (push build/release-*, then a draft) is unchanged."""
from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / '.github/workflows/release.yml'
ASSETS = 'A7C2Tools-desktop-assets.zip'


def workflow():
    document = yaml.safe_load(WORKFLOW.read_text(encoding='utf-8'))
    document['on'] = document.pop(True, document.get('on'))  # YAML 1.1 reads the key `on` as True
    return document


def steps(job):
    return workflow()['jobs'][job]['steps']


def step(job, name):
    return next(s for s in steps(job) if s.get('name') == name)


def test_a_published_release_or_a_named_tag_starts_the_untested_builds():
    triggers = workflow()['on']
    assert triggers['push'] == {'branches': ['build/release-*']}  # the release-branch flow stays
    assert triggers['release'] == {'types': ['published']}
    tag = triggers['workflow_dispatch']['inputs']['tag']
    assert tag['required'] is True and tag['type'] == 'string'


def test_the_builds_check_out_the_released_source():
    checkout = steps('package')[0]
    assert checkout['uses'] == 'actions/checkout@v4'
    assert checkout['with']['ref'] == '${{ inputs.tag || github.event.release.tag_name || github.sha }}'


def test_the_public_assets_zip_from_that_release_is_unpacked_before_the_build_assets():
    names = [s.get('name') for s in steps('package')]
    fetch = step('package', 'Release inputs from the source release')
    assert fetch['if'] == "github.event_name != 'push'"  # a release branch commits its own inputs
    assert 'gh release download "$SOURCE_TAG"' in fetch['run'] and ASSETS in fetch['run']
    assert fetch['env']['SOURCE_TAG'] == '${{ inputs.tag || github.event.release.tag_name }}'
    assert names.index('Release inputs from the source release') < names.index('Prepare build assets')


def test_the_draft_release_job_is_only_for_release_branches():
    assert workflow()['jobs']['draft-release']['if'] == "github.event_name == 'push'"


def test_untested_builds_go_out_as_a_prerelease_and_never_as_the_latest_release():
    job = workflow()['jobs']['untested-prerelease']
    assert job['needs'] == 'package'
    assert job['if'] == "github.event_name != 'push'"
    run = next(s for s in job['steps'] if s.get('name') == 'Publish the untested pre-release')['run']
    assert 'tag="$SOURCE_TAG-untested"' in run
    assert '--prerelease' in run and '--latest=false' in run
    for package in ('A7C2Tools-Windows-x64.zip', 'A7C2Tools-macOS-arm64.dmg'):
        assert 'packages/' + package in run


def test_a_prerelease_never_starts_another_build():
    # Publishing the untested pre-release is itself a release event; only full releases build.
    condition = workflow()['jobs']['package']['if']
    assert condition == "github.event_name != 'release' || !github.event.release.prerelease"


def test_the_untested_notes_say_untested_and_ask_for_a_build_report():
    run = step('untested-prerelease', 'Publish the untested pre-release')['run']
    assert 'Untested' in run and 'issues/new?template=build-report.yml' in run
    assert 'sha256sum' in run  # checksums for both packages go in the notes


def test_no_run_script_expands_a_tag_or_release_field_inline():
    # Tag names reach the shell only through env, never through ${{ }} inside a script.
    for job in workflow()['jobs'].values():
        for s in job['steps']:
            run = s.get('run', '')
            assert '${{ inputs.' not in run and '${{ github.event.release' not in run, s.get('name')
