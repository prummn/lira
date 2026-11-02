"""Release gates must reject unsafe/incomplete candidates and keep old releases."""
import hashlib
import importlib.util
import json
from pathlib import Path
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[2]


def module(name):
    path = ROOT / 'scripts' / (name + '.py')
    assert path.is_file(), f'Missing release workflow: {path.name}'
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def candidate(tmp_path, *, extra=None, corrupt=False):
    name = 'LIRA-2026.11.02.8-Windows-x64'
    path = tmp_path / (name + '.zip')
    body = b'<h1>LIRA</h1>'
    files = {'frontend/dist/index.html': hashlib.sha256(body).hexdigest()}
    manifest = {'name': name, 'private_data_included': False, 'files': files}
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr(name + '/frontend/dist/index.html', b'changed' if corrupt else body)
        archive.writestr(name + '/release.json', json.dumps(manifest))
        if extra:
            archive.writestr(extra, b'private')
    path.with_suffix('.zip.sha256').write_text(hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.name)
    return path


def test_next_version_checks_all_release_artifacts_and_uses_given_day(tmp_path):
    release = module('release')
    (tmp_path / 'LIRA-2026.11.02-Windows-x64.zip').touch()
    (tmp_path / 'LIRA-2026.11.02.2-Windows-x64.zip').touch()
    (tmp_path / 'LIRA-2026.11.02.3-Windows-x64.report.json').touch()
    assert release.next_version(tmp_path, '2026.11.02') == '2026.11.02.4'
    for value in ('../escape', '2026/11/02', '2026.11.02;bad', '2026.11.02.0'):
        with pytest.raises(ValueError):
            release.release_name(value)


@pytest.mark.parametrize('extra', ['../escape.txt', '/outside.txt', 'LIRA-2026.11.02.8-Windows-x64/backend/paper_reader.db', 'LIRA-2026.11.02.8-Windows-x64/.env'])
def test_archive_rejects_traversal_and_unlisted_private_files(tmp_path, extra):
    verify = module('verify_release')
    archive = candidate(tmp_path, extra=extra)
    with pytest.raises((ValueError, RuntimeError)):
        verify.check_archive(archive, tmp_path / 'extract')
    assert not (tmp_path / 'escape.txt').exists()


def test_archive_checks_checksum_manifest_and_extraction_destination(tmp_path):
    verify = module('verify_release')
    archive = candidate(tmp_path)
    install, manifest = verify.check_archive(archive, tmp_path / 'extract')
    assert (install / 'frontend/dist/index.html').is_file()
    assert manifest['private_data_included'] is False
    with pytest.raises((ValueError, RuntimeError)):
        verify.check_archive(archive, tmp_path / 'extract')
    archive.with_suffix('.zip.sha256').write_text('0' * 64 + '  ' + archive.name)
    with pytest.raises((ValueError, RuntimeError), match='checksum|校验'):
        verify.check_archive(archive, tmp_path / 'other')


def test_corrupted_file_is_rejected_even_with_valid_zip_checksum(tmp_path):
    verify = module('verify_release')
    with pytest.raises((ValueError, RuntimeError), match='manifest|清单'):
        verify.check_archive(candidate(tmp_path, corrupt=True), tmp_path / 'extract')


def test_failed_verification_never_changes_published_artifacts(tmp_path):
    release = module('release')
    archive = candidate(tmp_path)
    output = tmp_path / 'dist'
    output.mkdir()
    (output / 'latest.json').write_text('{"old":true}')
    with pytest.raises((ValueError, RuntimeError)):
        release.promote(archive, output, {'status': 'failed'})
    assert json.loads((output / 'latest.json').read_text()) == {'old': True}
    assert not (output / archive.name).exists()


def test_promotion_preserves_old_package_and_only_points_to_verified_zip(tmp_path):
    release = module('release')
    archive = candidate(tmp_path)
    output = tmp_path / 'dist'
    report = {'status': 'passed', 'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}
    release.promote(archive, output, report)
    assert (output / archive.name).read_bytes() == archive.read_bytes()
    assert json.loads((output / 'latest.json').read_text())['zip'] == archive.name
    with pytest.raises((ValueError, RuntimeError, FileExistsError)):
        release.promote(archive, output, report)


def test_tampered_candidate_cannot_be_promoted_after_verification(tmp_path):
    release = module('release')
    archive = candidate(tmp_path)
    with pytest.raises((ValueError, RuntimeError), match='checksum|校验'):
        release.promote(archive, tmp_path / 'dist', {'status': 'passed', 'archive_sha256': '0' * 64})


def test_release_lock_rejects_parallel_publishers_and_releases_after_failure(tmp_path):
    release = module('release')
    with release.publish_lock(tmp_path):
        with pytest.raises(RuntimeError, match='发布|release'):
            with release.publish_lock(tmp_path):
                pass
    with release.publish_lock(tmp_path):
        pass


def test_workflow_failure_retains_diagnostics_and_previous_latest(tmp_path, monkeypatch):
    release = module('release')
    monkeypatch.setattr(release, 'ROOT', tmp_path)
    monkeypatch.setattr(release.sys, 'platform', 'win32')
    monkeypatch.setattr(release.sys, 'version_info', (3, 13))
    monkeypatch.setattr(release.shutil, 'which', lambda name: name)
    monkeypatch.setattr(release, 'source_signature', lambda: 'fixed-source')
    (tmp_path / 'frontend/node_modules/@playwright/test').mkdir(parents=True)
    output = tmp_path / 'dist'
    output.mkdir()
    (output / 'latest.json').write_text('{"old":true}')
    def failed(*args, **kwargs):
        raise RuntimeError('intentional regression failure')
    monkeypatch.setattr(release, 'run_stage', failed)
    with pytest.raises(RuntimeError, match='intentional'):
        release.execute('2026.11.02.9')
    assert json.loads((output / 'latest.json').read_text()) == {'old': True}
    assert list(output.glob('*.zip')) == []
    report = next((tmp_path / '.local-runtime/releases').glob('*/report.json'))
    assert json.loads(report.read_text(encoding='utf-8'))['status'] == 'failed'


def test_archive_audit_rejects_private_data_even_when_listed_in_manifest(tmp_path):
    verify = module('verify_release')
    archive = candidate(tmp_path)
    name = archive.stem
    with zipfile.ZipFile(archive) as zipped:
        contents = {p: zipped.read(p) for p in zipped.namelist()}
    manifest = json.loads(contents[name + '/release.json'])
    manifest['files']['.env'] = hashlib.sha256(b'private').hexdigest()
    contents[name + '/.env'] = b'private'
    contents[name + '/release.json'] = json.dumps(manifest).encode()
    with zipfile.ZipFile(archive, 'w') as zipped:
        for path, content in contents.items():
            zipped.writestr(path, content)
    archive.with_suffix('.zip.sha256').write_text(hashlib.sha256(archive.read_bytes()).hexdigest() + '  ' + archive.name)
    with pytest.raises(RuntimeError, match='私人'):
        verify.check_archive(archive, tmp_path / 'extract')


def test_parent_cleans_verifier_service_after_subprocess_timeout(tmp_path, monkeypatch):
    import subprocess
    release = module('release')
    monkeypatch.setattr(release, 'ROOT', tmp_path)
    monkeypatch.setattr(release.sys, 'platform', 'win32')
    monkeypatch.setattr(release.sys, 'version_info', (3, 13))
    monkeypatch.setattr(release.shutil, 'which', lambda name: name)
    monkeypatch.setattr(release, 'source_signature', lambda: 'fixed')
    (tmp_path / 'frontend/node_modules/@playwright/test').mkdir(parents=True)
    cleanups = []
    monkeypatch.setattr(release, 'cleanup_verification', lambda work, name: cleanups.append((work, name)))
    def stage(report, work, name, command, **kwargs):
        if name == 'final-zip-verification':
            raise subprocess.TimeoutExpired(command, 1)
    monkeypatch.setattr(release, 'run_stage', stage)
    with pytest.raises(subprocess.TimeoutExpired):
        release.execute('2026.11.02.9')
    assert len(cleanups) == 1
    assert cleanups[0][0].name == 'verification'
    assert cleanups[0][1] == 'LIRA-2026.11.02.9-Windows-x64'


def test_cleanup_refuses_to_stop_a_service_outside_its_extracted_package(tmp_path):
    verify = module('verify_release')
    run = tmp_path / '独立验收数据/run'
    run.mkdir(parents=True)
    (run / 'instance.json').write_text(json.dumps({'root': str(tmp_path / 'another-install')}))
    with pytest.raises(RuntimeError, match='本轮|拒绝'):
        verify.cleanup_verification(tmp_path, 'LIRA-2026.11.02.9-Windows-x64')


def test_final_work_report_is_written_before_promotion(tmp_path, monkeypatch):
    release = module('release')
    monkeypatch.setattr(release, 'ROOT', tmp_path)
    monkeypatch.setattr(release.sys, 'platform', 'win32')
    monkeypatch.setattr(release.sys, 'version_info', (3, 13))
    monkeypatch.setattr(release.shutil, 'which', lambda name: name)
    monkeypatch.setattr(release, 'source_signature', lambda: 'fixed')
    (tmp_path / 'frontend/node_modules/@playwright/test').mkdir(parents=True)
    monkeypatch.setattr(release, 'cleanup_verification', lambda *args: None)
    def stage(report, work, name, command, **kwargs):
        if name == 'final-zip-verification':
            folder = work / 'verification'
            folder.mkdir()
            (folder / 'verification.json').write_text(json.dumps({'status': 'passed', 'archive_sha256': 'abc'}))
    monkeypatch.setattr(release, 'run_stage', stage)
    def promote(archive, output, report):
        work_report = json.loads((Path(report['work_dir']) / 'report.json').read_text(encoding='utf-8'))
        assert work_report['status'] == 'passed'
        return {'zip': archive.name, 'sha256': 'abc', 'report': 'report.json'}
    monkeypatch.setattr(release, 'promote', promote)
    release.execute('2026.11.02.9')
