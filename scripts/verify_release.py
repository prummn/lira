"""Validate a final ZIP and exercise it using disposable files and credentials."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path, PurePosixPath
import socket
import sqlite3
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.build_release import audit_files, digest


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def safe_relative(value):
    path = PurePosixPath(value)
    return (bool(value) and '\\' not in value and ':' not in value and not path.is_absolute()
            and all(part not in {'..', '.'} for part in value.rstrip('/').split('/')))


def check_archive(archive: Path, destination: Path):
    require(not destination.exists(), '验收目录已存在，不覆盖已有文件')
    expected = archive.with_suffix('.zip.sha256').read_text(encoding='ascii').split()
    require(bool(expected) and expected[0] == digest(archive), 'ZIP checksum 校验失败')
    with zipfile.ZipFile(archive) as zipped:
        infos = zipped.infolist()
        names = [info.filename for info in infos if not info.is_dir()]
        require(len({name.casefold() for name in names}) == len(names), 'ZIP 含重复路径')
        for info in infos:
            require(safe_relative(info.filename) and info.filename.startswith(archive.stem + '/'), 'ZIP 路径越界')
            require((info.external_attr >> 16) & 0o170000 != 0o120000, 'ZIP 不允许符号链接')
        manifest = json.loads(zipped.read(archive.stem + '/release.json'))
        require(manifest.get('name') == archive.stem and manifest.get('private_data_included') is False, 'manifest 发布信息无效')
        files = manifest.get('files')
        require(isinstance(files, dict) and files and all(safe_relative(name) for name in files), 'manifest 文件清单无效')
        listed = {archive.stem + '/' + name for name in files} | {archive.stem + '/release.json'}
        require(set(names) == listed, 'ZIP 存在未列入 manifest 的文件或缺失文件')
        require(zipped.testzip() is None, 'ZIP CRC 校验失败')
        for name, checksum in files.items():
            import hashlib
            require(hashlib.sha256(zipped.read(archive.stem + '/' + name)).hexdigest() == checksum, 'manifest 文件校验失败: ' + name)
        destination.mkdir(parents=True)
        zipped.extractall(destination)
    install = destination / archive.stem
    errors = audit_files(install)
    require(not errors, '私人数据检查失败: ' + '; '.join(errors))
    return install, manifest


def cleanup_verification(work: Path, name: str):
    """Parent-owned cleanup also runs if a timed-out verifier cannot run finally."""
    data = work / '独立验收数据'
    record = data / 'run/instance.json'
    if not record.exists():
        return
    install = (work / '解压验收 中文 空格' / name).resolve()
    state = json.loads(record.read_text(encoding='utf-8'))
    require(Path(state['root']).resolve() == install, '拒绝停止不属于本轮验收的服务')
    python = install / 'runtime/python/python.exe'
    require(python.is_file() and (install / 'lira.py').is_file(), '本轮验收启动器缺失，无法安全停止')
    with (work / 'cleanup.log').open('a', encoding='utf-8') as log:
        result = subprocess.run([str(python), '-X', 'utf8', '-B', str(install / 'lira.py'),
            'stop', '--data-dir', str(data)], cwd=install, stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT, timeout=80,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    require(result.returncode == 0 and not record.exists(), '验收服务尚未停止，请查看 cleanup.log')


def verify(archive: Path, work: Path):
    import httpx
    require(not work.exists(), '请使用新的独立验收目录')
    work.mkdir(parents=True)
    install, manifest = check_archive(archive, work / '解压验收 中文 空格')
    data = work / '独立验收数据'
    env = dict(os.environ)
    env.update(PATH=str(Path(env['SYSTEMROOT']) / 'System32'),
               PAPER_READER_MODEL_API_KEY='inherited-config-must-be-ignored',
               OPENAI_API_KEY='unrelated-credential-must-be-ignored')
    python = install / 'runtime/python/python.exe'

    def command(which, *options):
        script = install / f'{which} LIRA.cmd'
        arguments = ' '.join(f'"{value}"' for value in (*options, '--data-dir', data))
        result = subprocess.run(f'"{env["COMSPEC"]}" /d /s /c ""{script}" {arguments}"',
            cwd=install, env=env, stdin=subprocess.DEVNULL, capture_output=True,
            text=True, encoding='utf-8', errors='replace', timeout=115)
        with (work / 'launcher.log').open('a', encoding='utf-8') as log:
            log.write(result.stdout + result.stderr)
        require(result.returncode == 0, f'{which}失败，请查看 {work / "launcher.log"}')

    def state():
        return json.loads((data / 'run/instance.json').read_text(encoding='utf-8'))

    occupied = socket.socket()
    occupied.bind(('127.0.0.1', 0))
    occupied.listen()
    preferred = occupied.getsockname()[1]
    summary = {'archive_sha256': digest(archive), 'manifest_files': len(manifest['files'])}
    try:
        print('验证并行启动、空库、端口避让和账号隔离', flush=True)
        with ThreadPoolExecutor(2) as pool:
            starts = [pool.submit(command, '启动', '--no-browser', '--port', preferred) for _ in range(2)]
            for task in starts:
                task.result()
        first = state()
        require(first['port'] != preferred, '未避让已占用端口')
        command('启动', '--no-browser')
        require(state()['instance'] == first['instance'], '重复启动产生了第二个服务')
        with httpx.Client(base_url=f'http://127.0.0.1:{first["port"]}', timeout=90, trust_env=False) as client:
            require(client.get('/api/papers').json()['total'] == 0, '初始文献库非空')
            require(client.get('/api/collections').json()['total'] == 0, '初始专题非空')
            profiles = client.get('/api/settings/profiles').raise_for_status().json()
            require(profiles['profiles'] == [] and profiles['codex_max_concurrency'] == 1, '初始模型配置非空或并发默认错误')
            account = client.get('/api/settings/codex').raise_for_status().json()
            require(account['available'] and not account['authenticated'] and not account.get('error'), '随包 CLI 不可用或带入了登录状态')
            require(client.post('/__lira/stop').status_code == 403, '停止接口未保护')
            for path in ('/.env', '/backend/app/main.py', '/runtime/python/python.exe', '/data/paper_reader.db', '/api/not-real'):
                require(client.get(path).status_code == 404, '私人路径可被访问: ' + path)
            require(client.put('/api/settings/codex/concurrency', json={'max_concurrency': 2}).status_code == 200, '账号并发设置失败')
            pdf = data / 'verification.pdf'
            code = ('import pymupdf,sys; d=pymupdf.open(); p=d.new_page(); '
                    'p.insert_text((72,72),"LIRA portable verification",fontsize=20); '
                    'p.insert_text((72,120),"Abstract",fontsize=14); '
                    'p.insert_text((72,145),"This isolated document verifies PDF reading and persistent research notes."); '
                    'p=d.new_page(); p.insert_text((72,72),"Second page: continuous reading works."); d.save(sys.argv[1])')
            subprocess.run([str(python), '-X', 'utf8', '-B', '-c', code, str(pdf)], env=env, check=True, timeout=30)
            with pdf.open('rb') as stream:
                response = client.post('/api/papers/import', files={'file': ('verification.pdf', stream, 'application/pdf')}, data={'analyze': 'false'})
            response.raise_for_status()
            paper = response.json()
            paper_id = paper['id']
            require(paper['page_count'] == 2 and not paper['is_demo'], 'PDF 导入错误')
            require(client.get(f'/api/papers/{paper_id}/pdf').content.startswith(b'%PDF'), '无法获取 PDF')
            require(client.get(f'/api/papers/{paper_id}/reading-paragraphs').json()['paragraphs'], '未提取阅读段落')
            note = client.post(f'/api/papers/{paper_id}/notes', json={'content': '发布验收：独立测试笔记。', 'kind': 'note', 'page': 1}).raise_for_status().json()
            collection = client.post('/api/collections', json={'name': '发布验收（独立库）'}).raise_for_status().json()
            client.post(f'/api/collections/{collection["id"]}/papers', json={'paper_ids': [paper_id]}).raise_for_status()
        print('验证停止重启、笔记与设置持久化', flush=True)
        command('停止')
        require(not (data / 'run/instance.json').exists(), '停止后仍有实例记录')
        command('启动', '--no-browser', '--port', preferred)
        second = state()
        require(first['instance'] != second['instance'], '重启实例未更新')
        url = f'http://127.0.0.1:{second["port"]}'
        with httpx.Client(base_url=url, timeout=90, trust_env=False) as client:
            require(client.get('/api/papers').json()['total'] == 1, '重启丢失论文')
            require(client.get(f'/api/papers/{paper_id}/notes').json()[0]['id'] == note['id'], '重启丢失笔记')
            require(client.get('/api/collections').json()['total'] == 1, '重启丢失专题')
            require(client.get('/api/settings/profiles').json()['codex_max_concurrency'] == 2, '重启丢失账号并发设置')
        with sqlite3.connect(data / 'paper_reader.db') as database:
            require(database.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', '验收库完整性错误')
        ui_state = work / 'ui-input.json'
        ui_state.write_text(json.dumps({'url': url, 'paper_id': paper_id}), encoding='utf-8')
        node = __import__('shutil').which('node.exe')
        require(node, '构建机缺少 Node，无法完成浏览器验收')
        print('验证最终包浏览器、PDF worker、刷新和窗口布局', flush=True)
        subprocess.run([node, str(ROOT / 'scripts/verify_release_ui.cjs'), str(ui_state)], cwd=ROOT, check=True, timeout=150)
        summary.update(status='passed', checks={
            key: True for key in ('manifest', 'private_data_audit', 'empty_library', 'inherited_credentials_isolated',
                'port_conflict', 'parallel_start', 'duplicate_start', 'codex_available_logged_out',
                'private_http_paths_blocked', 'pdf_reading', 'note_collection_persistence',
                'account_setting_persistence', 'database_integrity', 'browser_ui')})
        summary['browser'] = json.loads((work / 'ui-result.json').read_text(encoding='utf-8'))
    finally:
        occupied.close()
        if (data / 'run/instance.json').exists():
            require(Path(state()['root']).resolve() == install.resolve(), '拒绝停止不属于本轮验收的服务')
            command('停止')
            require(not (data / 'run/instance.json').exists(), '验收服务未成功停止')
    summary['checks']['test_service_stopped'] = True
    (work / 'verification.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--work-dir', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.archive.resolve(), args.work_dir.resolve()), ensure_ascii=False, indent=2))
