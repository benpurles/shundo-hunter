"""Read iPogo-only iPhone banners through the paired local controller.

No screen captures, cloud requests, Notification Center opening, or touches.
An initial/reconnected banner is baseline, never a fresh notification.
"""
import json
import re
from urllib.request import Request, build_opener, ProxyHandler


class PhoneBannerReader:
    def __init__(self):
        self.opener = build_opener(ProxyHandler({}))
        self.seen = None

    def reset(self):
        self.seen = None

    def read(self):
        request = Request("http://127.0.0.1:18100/wda/hunter/notifications")
        with self.opener.open(request, timeout=5) as response:
            data = response.read(24_001)
        if len(data) > 24_000:
            raise RuntimeError("Unexpected phone notification response")
        return self.consume(json.loads(data).get("value"))

    def consume(self, value):
        if not isinstance(value, dict) or value.get("protocol") != 1 or value.get("source") != "iphone-banner":
            raise RuntimeError("Update/restart the phone controller for direct alerts")
        # The notification transport remains alive while Hunter intentionally
        # restarts iPogo. Foreground guards belong to encounter actions, not
        # banner transport health. Never treat a locked phone as ready.
        if value.get("screenLocked") is not False:
            raise RuntimeError("Unlock the iPhone for direct alerts (updated controller required)")
        banners = value.get("banners")
        if not isinstance(banners, list) or len(banners) > 8:
            raise RuntimeError("Invalid phone banner snapshot")
        current = set()
        for banner in banners:
            if not isinstance(banner, dict) or banner.get("sourceBundleId") != "com.nianticlabs.pokemongo":
                raise RuntimeError("Unrecognized notification source")
            text = banner.get("text")
            if not isinstance(text, str) or len(text) > 2000:
                raise RuntimeError("Invalid phone banner text")
            # The native endpoint verifies the exact app header. Use only the
            # alert sentence as fingerprint, excluding a changing 'now/1m' UI.
            match = re.search(r"\b(?:a\s+)?(?:shundo|hundo)\s+[^·\n]{1,350}?\b(?:appeared|found)\b(?:\s+nearby)?[.!]?", text, re.I)
            if match:
                current.add(" ".join(match.group(0).split()))
        previous = self.seen
        self.seen = current
        return sorted(current - previous) if previous is not None else []
