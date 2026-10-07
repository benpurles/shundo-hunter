# Spawn Runtime Lock

This file records the exact iPogo runtime required by Shundo Hunter. Do not
replace it with a reconstructed helper-framework, `sourceInformation = nil`, or
Hunter Lab build. Every iPogo base update requires a version-specific rebase and
the full acceptance test below.

## Installed 4.3.9 candidate awaiting physical acceptance

- Source: `/Users/benpurles/Downloads/ipogo-4.3.9.ipa`
- Source SHA-256: `cc7ec6a26cad36ad4055e5c53f63cd61a442cc2ac3edda0c918a61017fc3c1ea`
- Artifact: `ipogo-4.3.9-shundo-runtime-v8-iphone143-signed-legacy-id.ipa`
- Artifact SHA-256: `a728aaca83f64bdb972902f4f1f7ea51446c68539d21d9c00d2c61ec9af9341b`
- iPogo base version: `0.429.1`
- Bundle build: `0` (preserved exactly from the supplied iPogo base)
- Runtime version: `8`
- Runtime build: `worldscan-v3-ipogo439-20260925b`
- World protocol: `SHUNDO_WORLD_SCAN_V3`
- Bundle identifier: `com.nianticlabs.pokemongo`
- Application identifier: `H37AFANDDZ.com.nianticlabs.pokemongo.H37AFANDDZ`
- Installation mode: `pymobiledevice3 apps install --developer`
- Installed on 2026-09-25 at bundle path:
  `/private/var/containers/Bundle/Application/A8FB2F35-FCE3-4CEE-B8BF-1A306E6106AE/PokmonGO.app`
- Installed sequence: `3033`
- The supplied IPA was device-thinned to `iPhone11,8` and `iPhone12,1`.
  Runtime build `b` adds only the connected `iPhone14,3` identifier; the first
  signed candidate was rejected by iOS before replacing the v7 installation.
- Offline build, resign, installation, receipt, Hunter trust, notification
  detector, and world-watcher checks: passed.
- Physical world/spawn and Hundo-notification acceptance: pending.
- The guarded builder is `build_ipogo_439_runtime.py`; its release reports are
  `ipogo-4.3.9-runtime-v8-iphone143-build-report.json` and
  `ipogo-4.3.9-runtime-v8-iphone143-resign-report.json`.

The 4.3.9 executable returns to the 4.3.4 instruction layout. All offsets,
original bytes, getter symbols, imported stubs, branch targets, and cave-local
addresses were re-audited rather than inferred from that similarity. The Mac
app accepts only the exact v8 artifact hash above. Do not promote this candidate
until an external-location target loads spawns, PokéStops, and gyms and produces
a matching Hundo alert.

### 4.3.9 binary invariants

- Simulated-source hook: `0x130224`; false getter: `0x12e000`.
- `sourceInformation` prologue: `0x132c3c`.
- Startup wrapper: `0x139e74`; initializer pointer: `0xb9ecd8`.
- Notification call: `0x2574f8`; notification cave: `0x674730`.
- World cave: `0xb9a000`.
- World hooks: `0x25ff54`, `0x25ff58`, `0x25ff5c`, `0x25ff60`.
- Re-sign verification proved the patched `__TEXT` and `__DATA` bytes were
  identical before and after signing.

## Installed 4.3.8 candidate awaiting physical acceptance

- Source: `/Users/benpurles/Downloads/ipogo-4.3.8.ipa`
- Source SHA-256: `0238ad99cc0040f279ec14c9aff332b5d3f1e16696fef36a26c4e5dccfa747cf`
- Artifact: `ipogo-4.3.8-shundo-runtime-v7-signed-legacy-id.ipa`
- Artifact SHA-256: `828e79248ab4641eefe2a62ef585136e0c60ca65649cc0b222207ad97d08516d`
- iPogo base version: `0.427.0`
- Bundle build: `4` (preserved exactly from the supplied iPogo base)
- Runtime version: `7`
- Runtime build: `worldscan-v3-ipogo438-20260912a`
- World protocol: `SHUNDO_WORLD_SCAN_V3`
- Bundle identifier: `com.nianticlabs.pokemongo`
- Application identifier: `H37AFANDDZ.com.nianticlabs.pokemongo.H37AFANDDZ`
- Installation mode: `pymobiledevice3 apps install --developer`
- Installed on 2026-09-12 at bundle path:
  `/private/var/containers/Bundle/Application/293B5939-8E67-462F-B770-9C33C8D24CA2/PokmonGO.app`
- Installed sequence: `4315`
- Offline build, resign, installation, receipt, Hunter trust, notification
  detector, and world-watcher checks: passed.
- Physical world/spawn and Hundo-notification acceptance: pending.
- The 4.3.8 FBLPromises image differs from 4.3.5 in 17,351 bytes, but all
  Hunter-critical original instructions and cave bytes were independently
  checked before reuse. Never infer compatibility from equal file size alone.
- The guarded builder is `build_ipogo_438_runtime.py`; its reports are
  `ipogo-4.3.8-runtime-v7-build-report.json` and
  `ipogo-4.3.8-runtime-v7-resign-report.json`.

The Mac app accepts only the exact v7 artifact hash above. Do not promote this
candidate to the physically accepted release until a live external-location
target loads spawns, PokéStops, and gyms and produces a matching Hundo alert.

## Installed and physically accepted 4.3.5 release

- Source: `/Users/benpurles/Downloads/ipogo-4.3.5.ipa`
- Source SHA-256: `4cf82525913e3d129e7ddabc40cccdd8456bb350d62c25b4954cf85caf54daae`
- Artifact: `ipogo-4.3.5-shundo-runtime-v6-signed-legacy-id.ipa`
- Artifact SHA-256: `507c9aa5f57eb8decad722a74bee16adebc20ff06a7d0e032fb1ca8566b4972c`
- iPogo base version: `0.423.1`
- Bundle build: `0` (preserved exactly from the supplied iPogo base)
- Runtime version: `6`
- Runtime build: `worldscan-v3-ipogo435-20260806c`
- World protocol: `SHUNDO_WORLD_SCAN_V3`
- Bundle identifier: `com.nianticlabs.pokemongo`
- Application identifier: `H37AFANDDZ.com.nianticlabs.pokemongo.H37AFANDDZ`
- Installation mode: `pymobiledevice3 apps install --developer`
- Installed on 2026-08-06 at bundle path:
  `/private/var/containers/Bundle/Application/C1247276-A5E9-4903-9E77-B09D49EFE511/PokmonGO.app`
- Installed sequence: `2480`
- Offline build, resign, installation, receipt, Hunter trust, notification
  detector, and world-watcher checks: passed.
- Physical world/spawn acceptance: passed; live advertised 100-IV targets loaded
  and produced matching iPogo Hundo alerts.
- Physical notification acceptance: passed on 2026-08-06. Hunter captured ten
  consecutive Hundo alerts between 19:34:08 and 19:36:50 MDT (Bulbasaur,
  Magikarp, and Charmander) and advanced immediately after every alert.
- The read-only world telemetry counter remained silent. It is retained as a
  diagnostic layer but is not used as notification proof or as a hunt gate.

## Required production layers

The first two layers are production-critical. The third is diagnostic only:

1. External-location compatibility mask and early-startup reapplication.
2. `SHUNDO_HUNTER_NOTIFICATION` local-notification logger.
3. Read-only `SHUNDO_WORLD_SCAN_V3` observer (non-blocking telemetry).

Avatar movement proves only coordinate delivery. It does not prove spawn
compatibility.

## 4.3.5 binary invariants

- Patched simulated-source mask: `0x130220`.
- False getter remains at `0x12dffc`: `00008052c0035fd6`.
- Original `sourceInformation` prologue remains intact at `0x132c38`:
  `fd7bbfa9fd030091`.
- Startup wrapper: `0x139e70`; initializer pointer: `0xb9ecd8`.
- Notification logger branch: `0x2574f4`; logger cave: `0x67472c`.
- World observer cave: `0xb9a000`.
- World hooks: `0x25ff50`, `0x25ff54`, `0x25ff58`, `0x25ff5c`.
- No `ShundoBridge.framework` or corresponding load command may exist.
- Re-sign verification must prove the `__TEXT` and `__DATA` runtime bytes are
  identical before and after signing.

The guarded builder is `build_ipogo_435_runtime.py`. Its current build and
resign reports are `ipogo-4.3.5-runtime-v6-build-report.json` and
`ipogo-4.3.5-runtime-v6-resign-report.json`.

The rejected first 4.3.5 candidate reused the 4.3.4 ADRP page for the false
getter. Because the getter moved from `0x12e000` to `0x12dffc`, that wrapper
would have targeted the wrong address. It was rejected before signing or
installation. Always instruction-decode both wrapper references after rebasing;
simple byte-offset relocation is insufficient across a 4 KB page boundary.

The installed v5 candidate also reused the original notification-wrapper bytes
after moving the code cave. Its cave-local ADRP+ADD pairs still resolved to
`0x674758` and `0x674768`, which are instructions in 4.3.5 rather than the
wrapper's `NSString` and log-format strings. Runtime v6 regenerates every
address-bearing notification instruction and has instruction-decoding tests.
That corrected v6 wrapper is now the physically accepted release above.

The rejected 4.3.4 experiment also changed `CFBundleVersion` to the internal
Hunter build number `4006`. Never store a Hunter release number in Pokémon GO's
version metadata; preserve the supplied base value and use the exact-hash
receipt for Hunter trust.

## Required install verification

An install counts only after all of these pass:

1. The IPA SHA-256 exactly matches the frozen signed artifact above.
2. Every version-specific binary invariant passes before installation.
3. Installation uses developer mode and completes successfully.
4. The phone reports the expected bundle path and installation sequence.
5. The guarded installer writes the receipt under
   `~/Library/Application Support/Shundo Hunter/spawn-runtime-receipt.json`.
6. `Prepare phone` validates the exact receipt against the installed app.

## Acceptance test

The physical release test is all of the following:

1. Launch iPogo after installing the candidate.
2. Prepare the phone in Shundo Hunter.
3. Select a fresh 100-IV target with a known despawn time.
4. Keep the external walking-location stream active at the target.
5. Confirm visually that nearby spawns, PokéStops, and gyms load.
6. Confirm that the matching iPogo Hundo notification is observed by Hunter.
7. Record `SHUNDO_WORLD_SCAN_V3` evidence when available; its absence must not
   override a captured iPogo Hundo/Shundo notification.

## Rollback release

The last physically accepted release remains available as
`ipogo-4.3.3-worldscan-v3-signed-legacy-id.ipa`, SHA-256
`563ae4fe54499c2a9f7b241945d06c4171961a0fd30250965970016ab7dc98e9`.
It was visually accepted on 2026-08-01 with world objects and the notification
`Hundo Pidove appeared` at `39.900806, -75.255952`.
