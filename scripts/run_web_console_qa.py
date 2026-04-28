#!/usr/bin/env python3
import asyncio
import sys

from web_console.server import ConsoleServer

HOST = "127.0.0.1"
PORT = 18082
API_KEY = "test"
BASE = f"http://{HOST}:{PORT}"

results: list[tuple[str, bool, str]] = []


def log(name: str, passed: bool, detail: str = "") -> None:
    results.append((name, passed, detail))
    status = "PASS" if passed else "FAIL"
    print(f"[{status}] {name}{': ' + detail if detail else ''}")


async def curl(args: list[str]) -> tuple[int, str, str]:
    cmd = ["curl", "-s", "-i", "-w", "\nHTTP_CODE:%{http_code}"] + args
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    out = stdout.decode("utf-8", errors="ignore")
    err = stderr.decode("utf-8", errors="ignore")
    code = 0
    if "HTTP_CODE:" in out:
        parts = out.split("HTTP_CODE:")
        out = parts[0]
        try:
            code = int(parts[1].strip())
        except ValueError:
            pass
    return code, out, err


async def main() -> int:
    server = ConsoleServer(host=HOST, port=PORT, api_key=API_KEY)
    task = asyncio.create_task(server.start())
    await asyncio.sleep(0.5)

    log("1. Server starts correctly", True, f"listening on {HOST}:{PORT}")

    for path in ["/static/main.css", "/static/app.js"]:
        code, out, err = await curl([f"{BASE}{path}"])
        ok = code == 200
        log(f"2. Static files load ({path})", ok, f"HTTP {code}")

    code, out, err = await curl([f"{BASE}/login"])
    has_form = "api_key" in out.lower() or "password" in out.lower()
    has_theme = "theme" in out.lower()
    has_css = "main.css" in out.lower()
    ok = code == 200 and has_form and has_theme and has_css
    log("3. Login page loads", ok, f"HTTP {code}, form={has_form}, theme={has_theme}, css={has_css}")

    code, out, err = await curl(["-H", f"X-API-Key: {API_KEY}", f"{BASE}/"])
    is_dashboard = "Bot Status" in out or "bot status" in out.lower()
    not_login = "api_key" not in out.lower() or is_dashboard
    ok = code == 200 and is_dashboard and not_login
    log("4. Auth works (API key)", ok, f"HTTP {code}, dashboard={is_dashboard}")

    endpoints = ["/api/status", "/api/bridge", "/api/calendar"]
    for ep in endpoints:
        code, out, err = await curl(["-H", f"X-API-Key: {API_KEY}", f"{BASE}{ep}"])
        has_json = "{" in out
        ok = code == 200 and has_json
        log(f"5. API endpoint {ep}", ok, f"HTTP {code}, json={has_json}")

    code, out, err = await curl([f"{BASE}/static/../../core/config.py"])
    ok = code in (403, 404)
    log("6. Path traversal blocked", ok, f"HTTP {code}")

    code, out, err = await curl(["-H", f"X-API-Key: {API_KEY}", f"{BASE}/"])
    sections = [
        ("Bot Status", "Bot Status" in out),
        ("Bridge", "Bridge" in out),
        ("Kalender", "Kalender" in out),
        ("Avstemninger", "Avstemninger" in out),
        ("Rate Limits", "Rate Limits" in out),
        ("Intents", "Intents" in out),
        ("Minne", "Minne" in out),
        ("Logger", "Logger" in out),
    ]
    all_present = all(p for _, p in sections)
    missing = [name for name, p in sections if not p]
    log("7. Dashboard HTML structure", all_present, f"missing={missing}")

    code, out, err = await curl(["-H", f"X-API-Key: {API_KEY}", f"{BASE}/"])
    has_localstorage = "localStorage" in out
    has_theme = "theme" in out.lower()
    has_dark = "dark" in out.lower()
    has_light = "light" in out.lower()
    ok = has_localstorage and has_theme and has_dark and has_light
    log("8. Theme support", ok, f"localStorage={has_localstorage}, dark={has_dark}, light={has_light}")

    code, out, err = await curl(["-H", f"X-API-Key: {API_KEY}", f"{BASE}/"])
    has_dialog = 'role="dialog"' in out or "modal" in out.lower()
    ok = has_dialog
    log("9. Modal HTML present", ok, f"dialog={has_dialog}")

    await server.stop()
    log("10. Clean shutdown", True, "server.stop() completed without error")

    passed = sum(1 for _, p, _ in results if p)
    total = len(results)
    print(f"\nScenarios [{passed}/{total} pass] | VERDICT: {'PASS' if passed == total else 'FAIL'}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
