"""Bounded controller supervisor; cleans up even if Hunter is force-quit."""
import argparse
import os
import signal
import subprocess
import tempfile
import threading
import time
from pathlib import Path


def controller_archive():
    """Use the signed runner bundled with Hunter, not an arbitrary checkout."""
    archive = Path(__file__).resolve().parent.parent / "phone-controller.zip"
    return archive if archive.is_file() else None


def xcode_command(products, udid):
    plans = list(Path(products).glob("*.xctestrun"))
    if len(plans) != 1:
        raise RuntimeError("Hunter controller archive must contain one test plan")
    return ["/usr/bin/xcodebuild", "test-without-building", "-xctestrun", str(plans[0]),
            "-destination", f"id={udid}", "-parallel-testing-enabled", "NO",
            "-collect-test-diagnostics", "never", "-quiet"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", required=True)
    parser.add_argument("--udid", required=True)
    parser.add_argument("--native-wifi", action="store_true")
    parser.add_argument("--session-seconds", type=int, default=600)
    args = parser.parse_args()
    if not 60 <= args.session_seconds <= 43200:
        parser.error("Controller session must last between 60 seconds and 12 hours")
    owner = os.getppid()
    stopping = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    signal.signal(signal.SIGINT, lambda *_: stopping.set())
    commands = [
        [args.executable, "usbmux", "forward", "18100", "8100", "--udid", args.udid, "--host", "127.0.0.1"],
        [args.executable, "developer", "dvt", "xcuitest", "--userspace", "--udid", args.udid,
         "--timeout", str(args.session_seconds), "com.benpurles.shundohunter.wda.xctrunner"],
    ]
    if args.native_wifi:
        from .native_wifi import route
        python = str(Path(args.executable).resolve().parent / "python")
        commands = [
            [python, "-m", "shundo_hunter.paired_wifi", "--udid", args.udid, "--forward"],
            route(args.executable, commands[1][1:]),
        ]
    children = []
    runtime = None
    try:
        archive = controller_archive()
        if archive:
            # Xcode reliably starts the iOS 26 runner; the lightweight DVT
            # launch can stall at testRunnerReadyWithCapabilities. Preserve
            # device code signatures by archiving the runner inside the Mac
            # bundle rather than deep-signing its nested iOS app for macOS.
            runtime = tempfile.TemporaryDirectory(prefix="hunter-controller-")
            subprocess.run(["/usr/bin/ditto", "-x", "-k", str(archive), runtime.name], check=True)
            commands[1] = xcode_command(Path(runtime.name) / "Products", args.udid)
        for command in commands:
            children.append(subprocess.Popen(command, stdin=subprocess.DEVNULL))
        deadline = time.monotonic() + args.session_seconds
        while not stopping.wait(0.25):
            if os.getppid() != owner or time.monotonic() >= deadline or any(p.poll() is not None for p in children):
                break
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.send_signal(signal.SIGINT)
        for child in reversed(children):
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=2)
        if runtime is not None:
            runtime.cleanup()


if __name__ == "__main__":
    main()
