# Third-party source snapshots

These sources were copied from the existing local Shundo Hunter build inputs
on October 7, 2026. The local inputs were archive extractions without Git
metadata, so their exact upstream commit IDs are not known. No signed apps,
provisioning profiles, private keys, or device pairing records are included.

| Directory | Upstream | Snapshot | License |
| --- | --- | --- | --- |
| `vendor/WebDriverAgent` | https://github.com/appium/WebDriverAgent | Local source reports 16.12.11; includes the project's existing notification endpoint changes | Apache-2.0; see its LICENSE |
| `vendor/pymobiledevice3` | https://github.com/doronz88/pymobiledevice3 | Local September 27, 2026 Wi-Fi transport source snapshot | GPL-3.0-or-later; see its LICENSE |

Upstream CI and agent configuration, Python caches, and build artifacts were
excluded from the copies. `shundo_hunter/native/wda/FBDebugCommands.m` also
retains its upstream copyright/license header. The original dependency
licenses govern their respective files; no new license is assigned here to
the project's first-party code.

`requirements-wifi.txt` records supplemental installed package versions. Those
packages are downloaded during setup and retain their respective licenses.
