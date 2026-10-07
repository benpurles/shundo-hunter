# iPogo Hunter Lab

This is the isolated development track for replacing unreliable Discord
coordinates with iPogo's own internal 100-IV feed.

## Production boundary

The installed production app is not a test target. The only accepted base is
`ipogo-4.3.3-shundo-runtime-signed.ipa` with SHA-256
`5f49228a0cdd64ddd378b2d4443311a60d7d9dc46ca03a27b4ee9f6198d4d9bf`.
The Lab is installed side-by-side as `com.nianticlabs.pokemongo.hunterlab`.
Its guarded installer snapshots production before and after every update and
refuses success if production identity, path, container, or sequence changes.

Run the offline gate:

```sh
python3 hunter_lab_artifact.py \
  ipogo-4.3.3-shundo-runtime-signed.ipa \
  --report hunter-lab/base-verification.json
```

The verifier rejects the broken `sourceInformation = nil` patch, missing early
location mask, changed notification hook, legacy `ShundoBridge.framework`, or
any IPA other than the exact empirically verified release.

Create the unsigned side-by-side lab shell:

```sh
python3 build_hunter_lab_clone.py \
  ipogo-4.3.3-shundo-runtime-signed.ipa \
  hunter-lab/ipogo-4.3.3-hunter-lab-v1-unsigned.ipa \
  --report hunter-lab/lab-build-manifest.json
```

This changes only the main app and extension bundle metadata. It verifies that
the spawn/runtime framework remains byte-for-byte identical, then stops. It
does not sign or install the clone.

After signing, `verify_signed_hunter_lab.py` compares the unsigned and signed
frameworks. It allows differences only inside the existing Mach-O code
signature and rechecks every runtime invariant. A signed artifact that changes
executable/runtime bytes is rejected.

## Internal feed boundary

iPogo's `FBLPromises.framework` owns an authenticated feed manager. Both the
initial HTTP snapshot and WebSocket deltas pass through one decoded merger at
image-relative address `0x13a188`. The argument in `x0` is native array storage
for already-decoded feed records and `w1` identifies snapshot versus delta.

Hunter Lab v14 observes both pristine call sites into that boundary and logs
the already-decoded record values to its attached Mac console. The wrapper
restores the original arguments and tail-calls the untouched merger. The Mac
uses a full snapshot as its initial state, merges later WebSocket deltas, and
deletes records at their actual expiry time. Its hook calls the record type's
own Swift metadata accessor before reading the first snapshot, avoiding a lazy-
initialization race at this earlier boundary. The Lab never modifies production
iPogo, spoofs location, or intercepts notifications.

The visible 100-IV screen is **not** a persistent stream. It performs one
timestamped, cache-disabled HTTP snapshot through manager vtable slot `+0xa0`
(`0x138214`). WebSocket deltas use a separate `+0x78` path (`0x136d04`) gated
behind iPogo setting key `0x2a`; returning to production suspends the Lab, so a
background Lab socket is never treated as reliable.

The proven v15 design redirects only one existing Lab module-initializer
pointer into verified executable tail padding. It runs the original initializer
unchanged, waits 12 seconds on the main queue for iPogo's authenticated state,
then calls iPogo's own manager `+0x78` entry. That entry requests the fresh HTTP
snapshot before starting any optional deltas. The complete `replace=true`
snapshot is logged as `HUNTER_FEED_ITEM_V12`, parsed on the Mac, and only then
does the Mac return to untouched production iPogo.

Hunter Lab has an isolated preferences container. Before v15, iPogo therefore
used its missing-preference fallback of level 35 while constructing the feed
request, limiting otherwise valid 100-IV snapshots to roughly 7–13 records.
V15 forces the request model's level field to zero (iPogo's all-levels value)
after the preference lookup while retaining IV 100 and 15/15/15 stats. This
prevents an empty or stale Lab preference from silently narrowing the feed.
The v15 path was proven on the physical phone on 2026-08-02 with a complete
85-record snapshot spanning 30 distinct levels from level 1 through level 35;
73 previously unseen, unexpired targets entered the usable queue. Production
iPogo's installed identity, build, path, and data container were unchanged.

The Mac schedules another launch-and-snapshot every two minutes while the
hunter is idle. Automatic refreshing defers while a hunt is running, paused,
or the production runtime is prepared, so it cannot interrupt a location check.
Every expired coordinate is physically deleted from the queue.

## Build gates

1. Verify the immutable production base offline.
2. Prove decoded internal feed samples in a separately named Hunter Lab build.
3. Add one user-triggered internal teleport and confirm the advertised Hundo,
   gyms, stops, spawns, and notification.
4. Observe Hundo/Shundo at iPogo's existing notification boundary.
5. Automate exactly two targets with a kill switch.
6. Add priority order, highest-level sorting, circular walking, alarms, stats,
   persistence, and a floating Hunter panel.
7. Run 25–30 internal teleports to test whether iPogo's world-loading slowdown
   also affects its native spoofing path.

No gate advances after a crash, black screen, missing world objects, missing
internal feed, or a failed byte invariant.
