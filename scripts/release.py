"""One-command Windows release: test, build, verify the ZIP, then publish locally."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.build_release import application_files, digest
from scripts.verify_release import cleanup_verification

BACKEND_TESTS = [f'backend/tests/{name}.py' for name in (
    'test_portable_release', 'test_release_workflow', 'test_connection_validation',
    'test_provider_profiles', 'test_codex_subscription', 'test_model_settings',
    'test_remote_provider', 'test_reading_first', 'test_translation_queue', 'test_migrations')]


def release_name(version):
    if not re.fullmatch(r'\d{4}\.\d{2}\.\d{2}(?:\.[1-9]\d*)?', version):
        raise ValueError('版本格式应为 YYYY.MM.DD 或 YYYY.MM.DD.N，N 从 1 开始')
    datetime.strptime('.'.join(version.split('.')[:3]), '%Y.%m.%d')
    return f'LIRA-{version}-Windows-x64'


def next_version(output, day):
    release_name(day)
    pattern = re.compile(r'^LIRA-' + re.escape(day) + r'(?:\.([1-9]\d*))?-Windows-x64(?:\.|$)')
    seen = [int(match[1] or 0) for p in output.glob('*') if (match := pattern.match(p.name))]
    return day if not seen else f'{day}.{max(seen) + 1}'


@contextmanager
def publish_lock(directory):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / 'release-workflow.lock').open('a+b') as stream:
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError('另一个发布流程正在运行，请等待完成') from None
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def atomic_json(path, value):
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def promote(archive, output, report):
    if report.get('status') != 'passed':
        raise RuntimeError('验收尚未通过，禁止发布')
    checksum = digest(archive)
    if checksum != report.get('archive_sha256'):
        raise RuntimeError('发布前 checksum 校验失败')
    checksum_file = archive.with_suffix('.zip.sha256')
    if not checksum_file.is_file() or checksum_file.read_text(encoding='ascii').split()[0] != checksum:
        raise RuntimeError('发布前 checksum 文件校验失败')
    output.mkdir(parents=True, exist_ok=True)
    report_file = output / (archive.stem + '.report.json')
    text_file = output / (archive.stem + '.report.md')
    targets = [output / archive.name, output / checksum_file.name, report_file, text_file]
    if any(path.exists() for path in targets) or (output / archive.stem).exists():
        raise FileExistsError('已有同版本产物，拒绝覆盖')
    created = []
    try:
        for source, target in zip((archive, checksum_file), targets):
            with target.open('xb') as stream:
                created.append(target)
                with source.open('rb') as incoming:
                    shutil.copyfileobj(incoming, stream)
        for target, content in (
            (report_file, json.dumps(report, ensure_ascii=False, indent=2)),
            (text_file, f'# {archive.stem}\n\n验收通过，可分发 ZIP。\n\n'
                f'- 文件：`{archive.name}`\n- SHA256：`{checksum}`\n'
                f'- 大小：{archive.stat().st_size:,} 字节\n'
                '- 已通过：发布回归、前端构建、归档与私人数据检查、最终 ZIP 隔离启动、PDF 阅读及笔记持久化、浏览器验收。\n'
                '- 本次验证在构建机独立数据目录执行；未验证其他电脑或远端模型服务。\n'
                '- 使用：完整解压后双击「启动 LIRA.cmd」，自行配置模型。CAJ 与扫描件 OCR 暂不支持。\n\n'
                '详细阶段与检查结果见同名 `.report.json`；阶段日志位置在其中记录。\n')):
            with target.open('x', encoding='utf-8') as stream:
                created.append(target)
                stream.write(content)
        latest = {'name': archive.stem, 'zip': archive.name, 'sha256': checksum,
                  'report': report_file.name, 'status': 'passed'}
        atomic_json(output / 'latest.json', latest)
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    return latest


def source_signature():
    paths = {p for p in application_files(ROOT) if 'frontend/dist' not in p.relative_to(ROOT).as_posix()}
    paths.update(p for p in (ROOT / 'scripts').rglob('*') if p.is_file() and p.suffix in {'.py', '.cjs', '.ps1', '.cmd', '.txt'} and '__pycache__' not in p.parts)
    entries = [(p.relative_to(ROOT).as_posix(), digest(p)) for p in sorted(paths)]
    return hashlib.sha256(json.dumps(entries).encode()).hexdigest()


def run_stage(report, work, name, command, *, cwd=ROOT, timeout=1200):
    log = work / (name + '.log')
    stage = {'name': name, 'status': 'running', 'log': str(log)}
    report['stages'].append(stage)
    atomic_json(work / 'report.json', report)
    print(f'[{len(report["stages"])}] {name} ... 日志：{log}', flush=True)
    start = time.monotonic()
    try:
        with log.open('w', encoding='utf-8') as stream:
            with subprocess.Popen(command, cwd=cwd, stdin=subprocess.DEVNULL, stdout=stream,
                    stderr=subprocess.STDOUT,
                    env={**os.environ, 'PYTHONUTF8': '1', 'PYTHONDONTWRITEBYTECODE': '1'},
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0) as process:
                try:
                    code = process.wait(timeout=timeout)
                except BaseException:
                    # Stop live child launchers before cleaning up detached test services.
                    if process.poll() is None:
                        if os.name == 'nt':
                            subprocess.run(['taskkill.exe', '/PID', str(process.pid), '/T', '/F'],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
                        else:
                            process.terminate()
                        try:
                            process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=10)
                    raise
                if code:
                    raise subprocess.CalledProcessError(code, command)
        stage['status'] = 'passed'
    except BaseException:
        stage['status'] = 'failed'
        raise
    finally:
        stage['seconds'] = round(time.monotonic() - start, 2)
        atomic_json(work / 'report.json', report)


def execute(version=None):
    if sys.platform != 'win32' or sys.version_info[:2] != (3, 13):
        raise RuntimeError('请用 backend/.venv/Scripts/python.exe（Windows x64 Python 3.13）发布')
    output = ROOT / 'dist'
    with publish_lock(ROOT / '.local-runtime'):
        day = datetime.now(timezone(timedelta(hours=8))).strftime('%Y.%m.%d')
        name = release_name(version or next_version(output, day))
        if any(output.glob(name + '*')):
            raise FileExistsError('此版本已有产物，请使用新版本号')
        work = ROOT / '.local-runtime/releases' / (name + '-' + uuid.uuid4().hex[:8])
        work.mkdir(parents=True)
        report = {'name': name, 'status': 'running', 'stages': [], 'work_dir': str(work),
                  'started_at': datetime.now(timezone(timedelta(hours=8))).isoformat()}
        atomic_json(work / 'report.json', report)
        try:
            npm, npx = shutil.which('npm.cmd'), shutil.which('npx.cmd')
            if not npm or not npx or not (ROOT / 'frontend/node_modules/@playwright/test').is_dir():
                raise RuntimeError('发布机需要 Node/npm、前端依赖及 Chromium；安装步骤见 docs/DISTRIBUTION.md')
            original = source_signature()
            report['source_sha256'] = original
            run_stage(report, work, 'backend-regression', [sys.executable, '-m', 'pytest', *BACKEND_TESTS, '-q'])
            run_stage(report, work, 'model-settings-ui', [npx, 'playwright', 'test', 'tests/codex-subscription.spec.ts', '--reporter=line'], cwd=ROOT / 'frontend')
            run_stage(report, work, 'frontend-build', [npm, 'run', 'build'], cwd=ROOT / 'frontend')
            candidate = work / 'candidate'
            run_stage(report, work, 'package', [sys.executable, str(ROOT / 'scripts/build_release.py'), '--output', str(candidate), '--name', name])
            archive = candidate / (name + '.zip')
            try:
                run_stage(report, work, 'final-zip-verification', [sys.executable, '-X', 'utf8', str(ROOT / 'scripts/verify_release.py'), str(archive), '--work-dir', str(work / 'verification')], timeout=600)
            finally:
                cleanup_verification(work / 'verification', name)
            verified = json.loads((work / 'verification/verification.json').read_text(encoding='utf-8'))
            if verified.get('status') != 'passed' or source_signature() != original:
                raise RuntimeError('验收失败或发布期间源码发生变化，请检查后重新发布')
            report.update(status='passed', archive_sha256=verified['archive_sha256'], verification=verified,
                          finished_at=datetime.now(timezone(timedelta(hours=8))).isoformat())
            atomic_json(work / 'report.json', report)
            latest = promote(archive, output, report)
        except BaseException as error:
            report.update(status='failed', error=str(error))
            atomic_json(work / 'report.json', report)
            print(f'发布未通过，不更新正式产物。诊断：{work / "report.json"}', file=sys.stderr, flush=True)
            raise
        print(f'发布验收通过：{output / latest["zip"]}\n校验码：{latest["sha256"]}\n报告：{output / latest["report"]}', flush=True)
        return latest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', help='YYYY.MM.DD.N；省略则按上海日期自动编号')
    args = parser.parse_args()
    try:
        execute(args.version)
    except (Exception, KeyboardInterrupt) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
