"""Explicitly invoked, one-throw diagnostic recorder. Never used by hunts.

Run with pymobiledevice3's Python. Video stays in the requested local directory;
no microphone audio, uploads, inventory actions, or automatic gesture retries.
"""
import argparse
import asyncio
import base64
import json
from pathlib import Path
import subprocess
import time
from urllib.request import build_opener, ProxyHandler, Request
from urllib.error import HTTPError
from .paired_wifi import discover, connect


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--udid", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cp", type=int, required=True)
    parser.add_argument("--duration-ms", type=int, default=240)
    parser.add_argument("--end-y", type=float, default=.4)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    op = build_opener(ProxyHandler({}))
    def request(port, path, payload=None):
        req = Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(payload).encode() if payload is not None else None,
                      headers={"Content-Type":"application/json", "Origin":"http://127.0.0.1:8765"})
        try:
            return json.load(op.open(req, timeout=30))
        except HTTPError as error:
            raise RuntimeError(error.read().decode()[:500]) from error
    def foreground():
        if request(18100,"/wda/activeAppInfo")["value"]["bundleId"] != "com.nianticlabs.pokemongo":
            raise RuntimeError("iPogo is no longer foreground; stop recording and do not throw")
    phone = asyncio.run(discover(args.udid))
    if not phone:
        raise RuntimeError("Paired Wi-Fi phone not discovered")
    async def authenticate():
        device = await connect(phone["HunterWifiAddress"], args.udid)
        await device.close()
    asyncio.run(authenticate())
    foreground()
    status = request(8765,"/api/status")
    def lab(action, **payload):
        return request(8765,"/api/catch-lab",dict(action=action,instanceToken=status["instanceToken"],**payload))["result"]
    preview = lab("inspect")
    if preview["scene"]["scene"] != "encounter" or preview["scene"]["cp"] != args.cp:
        raise RuntimeError("Live encounter does not match the supervised test")
    (args.output/"before.png").write_bytes(base64.b64decode(preview["image"].split(",",1)[1]))
    meta = {"cp":args.cp,"durationMs":args.duration_ms,"endY":args.end_y,"beforeScene":preview["scene"],"throwRequested":False}
    with (args.output/"ffmpeg.log").open("wb") as log:
        recorder = subprocess.Popen(["/opt/homebrew/bin/ffmpeg","-hide_banner","-loglevel","error","-rw_timeout","5000000",
                    "-use_wallclock_as_timestamps","1","-f","mpjpeg","-i",f"http://{phone['HunterWifiAddress']}:9100",
                    "-t","18","-an","-vf","scale=428:-2","-c:v","libx264","-preset","ultrafast","-pix_fmt","yuv420p",
                    "-movflags","+frag_keyframe+empty_moov",str(args.output/"throw.mp4")],stdout=subprocess.DEVNULL,stderr=log)
        began = time.monotonic()
        try:
            time.sleep(2)
            if recorder.poll() is not None:
                raise RuntimeError("Recording failed before throw; no ball used")
            foreground()
            meta["throwRequestOffsetSeconds"] = round(time.monotonic()-began,3)
            meta["throwRequested"] = True
            meta["throwResponse"] = lab("throw_once",token=preview["token"],start=[.5,.85],end=[.5,args.end_y],
                                       durationMs=args.duration_ms,confirmedOrdinaryRegularBall=True)
            print(json.dumps({"throwResponse":meta["throwResponse"],"video":str(args.output/"throw.mp4")}),flush=True)
            while recorder.poll() is None and time.monotonic()-began<22:
                foreground()
                time.sleep(1)
        except Exception as error:
            meta["error"] = str(error)
            print(json.dumps({"error":str(error)}),flush=True)
        finally:
            if recorder.poll() is None:
                recorder.terminate()
            try:
                recorder.wait(timeout=5)
            except subprocess.TimeoutExpired:
                recorder.kill()
                recorder.wait()
            meta["recorderExitCode"] = recorder.returncode
            result = request(8765,"/api/status")
            meta["outcome"] = {key:result.get(key) for key in ("catchLabState","catchLabDetail","catchLabAttempt")}
            (args.output/"result.json").write_text(json.dumps(meta,indent=2))
            print(json.dumps(meta["outcome"]),flush=True)


if __name__ == "__main__":
    main()
