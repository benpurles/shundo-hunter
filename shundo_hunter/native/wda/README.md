# Direct iPhone banner endpoint

`FBDebugCommands.m` is the preserved Hunter version of the WDA command file.
It retains the upstream license and source endpoints, adding the read-only
`GET /wda/hunter/notifications` endpoint. Before rebuilding the controller,
copy it to `build/wda/WebDriverAgent-master/WebDriverAgentLib/Commands/`.
Do not silently replace a different upstream version: compare changes first.

Build with the existing WebDriverAgentRunner scheme, device signing team and
`build/wda/DerivedData` path. Install only the signed runner, not a new iPogo.
The Mac build packages the signed products inside `phone-controller.zip`,
protecting their iOS signatures from macOS deep signing. Hunter's bounded
supervisor extracts this privately and uses Xcode test-without-building for
startup, with verbose device diagnostics disabled. It owns and stops both the
runner and port forwarder. No separate terminal/Xcode session should be left
running. An iOS automation-mode timeout still needs the phone unlocked with
Developer → Enable UI Automation on; a launcher change cannot bypass that.

The endpoint reads SpringBoard accessibility without opening Notification
Center, activating another app or touching the screen. It emits only visible
compact top banners with the game app header and Hundo/Shundo text. Revision
2 takes one snapshot and only expands native notification banner nodes, not
every hidden app element. It needs an unlocked phone, visible notification
previews and phone banners enabled. A planned game restart does not disconnect
notification transport; encounter actions still have their foreground guards.
It is not a structured OS notification subscription and can miss banners that
iOS does not display, hides, or presents between snapshots. Reconnection must
discard an existing banner and require fresh Hundo proof in Hunter.

Observed real iPhone wording on 2026-09-29 UTC:
`POKÉMON GO, now, Pokémon GO, Hundo Nidoking appeared`.
The `nearby` suffix is optional. The regression test preserves this actual
wording. A healthy endpoint by itself is NOT evidence of delivery.
