"""Start the real bridge, inspect status, test no-Roblox Start, then await clean exit."""
import argparse
import json
import os
from pathlib import Path
import queue
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sidecar", type=Path)
    args = parser.parse_args()
    directory = ROOT / ".build" / "smoke"
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=directory) as data_dir:
        token = secrets.token_hex(32)
        command = [str(args.sidecar.resolve())] if args.sidecar else [sys.executable, "-B", str(ROOT / "python" / "core_server.py")]
        command += ["--data-dir", data_dir, "--parent-pid", str(os.getpid()), "--no-hotkeys"]
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        lines = queue.Queue()
        threading.Thread(target=lambda: lines.put(process.stdout.readline()), daemon=True).start()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        port = None
        try:
            process.stdin.write(token + "\n")
            process.stdin.close()
            line = lines.get(timeout=30)
            if not line:
                raise RuntimeError("Bridge exited before readiness; check installed dependencies")
            ready = json.loads(line)
            assert ready["pid"] == process.pid and ready["version"] == "1.0.0"
            port = ready["port"]

            def request(route, action=None):
                body = json.dumps({"action": action, "payload": {}}).encode() if action else None
                query = urllib.request.Request(f"http://127.0.0.1:{port}{route}", data=body, headers={"X-XynLevel-Token": token, "Content-Type": "application/json"})
                with opener.open(query, timeout=5) as response:
                    return json.load(response)

            assert request("/health")["ok"]
            state = request("/state")
            print("PASS: bridge starts and reports status")
            if state["window"]["found"]:
                raise RuntimeError("Roblox is open; no real Start was sent. Use the isolated real-core unit test for the no-window branch.")
            request("/command", "start")
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                state = request("/state")
                if not state["running"]:
                    break
                time.sleep(0.05)
            assert state["status"] == "Stopped: Roblox not found", state["status"]
            print('PASS: Start with no Roblox returns "Stopped: Roblox not found"')
            request("/command", "shutdown")
            process.wait(timeout=12)
            assert process.returncode == 0
            print("PASS: bridge exits cleanly")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            process.stdout.close()
            process.stderr.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Avoid leaking subprocess tracebacks or local paths in saved check output.
        sys.path.insert(0, str(ROOT / "python"))
        from privacy import scrub
        print(f"FAIL: {scrub(error)}")
        sys.exit(1)
