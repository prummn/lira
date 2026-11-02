"""Local-only launcher shipped with the Windows portable release."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hmac
import json
import mimetypes
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent


def configure_environment(root: Path, data: Path) -> None:
    data.mkdir(parents=True, exist_ok=True)
    for name in list(os.environ):
        if name.startswith("PAPER_READER_") or name == "OPENAI_API_KEY":
            os.environ.pop(name)
    os.environ["PAPER_READER_DATABASE_URL"] = f"sqlite:///{(data / 'paper_reader.db').as_posix()}"
    os.environ["PAPER_READER_STORAGE_DIR"] = str(data / "storage")
    os.environ["PAPER_READER_MODEL_CONFIG_PATH"] = str(data / "model.env")
    os.environ["PATH"] = str(root / "runtime" / "codex" / "bin") + os.pathsep + os.environ.get("PATH", "")
    sys.path[:0] = [str(root), str(root / "backend")]


def create_application(root: Path, data: Path, instance: str, token: str):
    configure_environment(root, data)
    from fastapi import HTTPException, Request
    from fastapi.responses import JSONResponse
    from fastapi.staticfiles import StaticFiles
    from backend.app.main import create_app

    # Windows registry entries for source editors can override these with
    # text/plain. Browsers then refuse both the UI modules and the PDF worker.
    for extension, media_type in {".js": "text/javascript", ".mjs": "text/javascript",
        ".css": "text/css", ".svg": "image/svg+xml", ".wasm": "application/wasm",
        ".woff": "font/woff", ".woff2": "font/woff2"}.items():
        mimetypes.add_type(media_type, extension)

    app = create_app(database_url=os.environ["PAPER_READER_DATABASE_URL"],
        storage_dir=data / "storage", model_config_path=data / "model.env", seed_demo=False)
    app.state.exit_requested = threading.Event()

    @app.get("/__lira/instance", include_in_schema=False)
    def identity():
        return {"instance": instance, "root": str(root)}

    # Request is placed in module globals for postponed annotation resolution.
    globals()["Request"] = Request

    @app.post("/__lira/stop", include_in_schema=False)
    def stop(request: Request):
        if not hmac.compare_digest(request.headers.get("X-Lira-Token", ""), token):
            raise HTTPException(403, "Invalid instance token")
        app.state.exit_requested.set()
        return JSONResponse({"stopping": True}, status_code=202)

    app.mount("/", StaticFiles(directory=root / "frontend" / "dist", html=True), name="web")
    return app


def api(state: dict, route: str, *, stop: bool = False):
    address = state.get("port")
    if not isinstance(address, int) or not 1024 <= address <= 65535:
        raise ValueError("Invalid local service port")
    headers = {"X-Lira-Token": state["token"]} if stop else {}
    request = urllib.request.Request(f"http://127.0.0.1:{address}{route}",
        headers=headers, method="POST" if stop else "GET")
    # Loopback never goes through an inherited system or shell HTTP proxy.
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=2) as response:
        return json.load(response)


def active_state(data: Path):
    try:
        state = json.loads((data / "run" / "instance.json").read_text(encoding="utf-8"))
        if api(state, "/__lira/instance").get("instance") == state["instance"]:
            return state
    except (OSError, ValueError, KeyError):
        pass
    return None


@contextmanager
def launcher_lock(data: Path):
    import msvcrt
    runtime = data / "run"
    runtime.mkdir(parents=True, exist_ok=True)
    with (runtime / "launcher.lock").open("a+b") as lock:
        if lock.tell() == 0:
            lock.write(b"0")
            lock.flush()
        deadline = time.monotonic() + 100
        while True:
            try:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("另一次启动仍在进行，请稍后重试。") from None
                time.sleep(.2)
        try:
            yield
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def listen(preferred: int):
    for port in [*range(preferred, min(preferred + 30, 65536)), 0]:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            listener.bind(("127.0.0.1", port))
            listener.listen(128)
            return listener
        except OSError:
            listener.close()
    raise RuntimeError("无法创建本地服务端口。")


@contextmanager
def service_lock(data: Path):
    """Keep one worker per library, even when HTTP health is temporarily slow."""
    import msvcrt
    runtime = data / "run"
    runtime.mkdir(parents=True, exist_ok=True)
    with (runtime / "service.lock").open("a+b") as lock:
        if lock.tell() == 0:
            lock.write(b"0")
        lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise RuntimeError("LIRA 正在运行或仍在启动，请稍后重新打开；不会重复启动后台任务。") from None
        try:
            yield
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def serve(data: Path, preferred: int) -> None:
    with service_lock(data):
        _serve(data, preferred)


def _serve(data: Path, preferred: int) -> None:
    import uvicorn
    runtime = data / "run"
    state_path = runtime / "instance.json"
    instance, token = secrets.token_hex(16), secrets.token_hex(32)
    app = create_application(ROOT, data, instance, token)
    listener = listen(preferred)
    state = {"instance": instance, "token": token, "root": str(ROOT),
        "pid": os.getpid(), "port": listener.getsockname()[1]}
    temporary = state_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state), encoding="utf-8")
    temporary.replace(state_path)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=state["port"],
        log_level="info", access_log=False, loop="asyncio", http="h11", ws="none",
        timeout_graceful_shutdown=30))

    def watch_stop():
        app.state.exit_requested.wait()
        server.should_exit = True

    threading.Thread(target=watch_stop, daemon=True).start()
    try:
        server.run(sockets=[listener])
    finally:
        listener.close()
        try:
            if json.loads(state_path.read_text(encoding="utf-8")).get("instance") == instance:
                state_path.unlink()
        except (OSError, ValueError):
            pass


def start(data: Path, preferred: int, no_browser: bool) -> None:
    with launcher_lock(data):
        state = active_state(data)
        if state and Path(state["root"]).resolve() != ROOT:
            raise RuntimeError("另一个目录中的 LIRA 正在使用此文献库，请先用那一版的停止脚本关闭服务。")
        if not state:
            with service_lock(data):
                pass
            runtime = data / "run"
            # Avoid pythonw: stdout/stderr are explicit files, and no visible child window is needed.
            with (runtime / "service.log").open("ab", buffering=0) as log:
                process = subprocess.Popen([sys.executable, "-X", "utf8", "-B", str(ROOT / "lira.py"), "serve",
                    "--data-dir", str(data), "--port", str(preferred)], cwd=ROOT,
                    stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                state = active_state(data)
                if state:
                    break
                if process.poll() is not None:
                    raise RuntimeError(f"服务未能启动，错误记录：{runtime / 'service.log'}")
                time.sleep(.3)
            if not state:
                # Do not leave a late-starting orphan that could race the next launch.
                process.terminate()
                process.wait(timeout=10)
                raise RuntimeError(f"启动超时，错误记录：{runtime / 'service.log'}")
    address = f"http://127.0.0.1:{state['port']}"
    print(f"LIRA 已启动：{address}\n数据目录：{data}", flush=True)
    if not no_browser:
        webbrowser.open(address)


def stop_service(data: Path) -> None:
    with launcher_lock(data):
        state = active_state(data)
        if not state:
            print("LIRA 已停止。")
            return
        if Path(state["root"]).resolve() != ROOT:
            raise RuntimeError("服务属于另一个 LIRA 目录，请用对应版本的停止脚本操作。")
        api(state, "/__lira/stop", stop=True)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if not (data / "run" / "instance.json").exists():
                print("LIRA 已停止，文献与笔记已保留。")
                return
            time.sleep(.3)
        raise RuntimeError("服务仍在结束请求，请稍后重试停止；不要在运行中移动数据目录。")


def main():
    parser = argparse.ArgumentParser(description="LIRA Windows portable launcher")
    parser.add_argument("command", choices=["start", "stop", "serve", "status"])
    parser.add_argument("--data-dir", type=Path,
        default=Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "LIRA")
    parser.add_argument("--port", type=int, default=5173)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    data = args.data_dir.resolve()
    if not 1024 <= args.port <= 65535:
        parser.error("port must be between 1024 and 65535")
    if args.command == "serve":
        serve(data, args.port)
    elif args.command == "start":
        start(data, args.port, args.no_browser)
    elif args.command == "stop":
        stop_service(data)
    else:
        state = active_state(data)
        print(f"http://127.0.0.1:{state['port']}" if state else "LIRA 未运行。")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"\n{error}", file=sys.stderr)
        sys.exit(1)
