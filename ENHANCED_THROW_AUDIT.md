# iPogo 4.3.9 Enhanced Throw — static audit, 2026-09-28

Research only. No IPA, installed app, preferences, phone state, or Hunter code
changed. No throws performed. This is ARM64 binary analysis, not access to
iPogo's original source. Static presence is not proof of live execution or of
server acceptance/catch probability.

## Inputs

- User's `/Users/benpurles/Downloads/ipogo-4.3.9.ipa`.
- Framework: `Payload/PokmonGO.app/Frameworks/FBLPromises.framework/FBLPromises`.
- Framework SHA-256:
  `5b591e991018eef1e0dfdd6178af96a7a2647250713e9e041c20a97e90e6790c`.
- Compared against local signed Hunter artifact:
  `ipogo-4.3.9-shundo-runtime-v8-iphone143-signed-legacy-id.ipa`.
- Analysis scratch directory: `/private/tmp/ipogo-enhanced-throw-b6aw7s`.
  Contains extracted framework, English localization, read-only inspection
  script, and generated disassembly. No credentials involved.

## Findings

### Menu and persistence

The retained source-path string `FBLPromises/ThrowViewController.swift` identifies
the obfuscated controller `Zzdj5vrq8imjzvo5wtifeX24wTYkI2MG`.
Selection handler at `0x121ac4` writes preference ID 13 with selected mode 0–4.
The enum label function at `0x158e9c`, with jump table at `0x87bd00`, maps:

| Value | UI label | Generated quality parameter | Generated spin parameter |
| --- | --- | --- | --- |
| 0 | None | Enhancement disabled | No override |
| 1 | Good to Excellent | Random approximately 1.30–1.85 | 0 or 1, random bit |
| 2 | Great to Excellent | Random approximately 1.50–1.85 | 0 or 1, random bit |
| 3 | Excellent | Random approximately 1.70–1.85 | 0 or 1, random bit |
| 4 | Excellent with Curve | Random approximately 1.70–1.85 | Always 1 |

These are generated numeric parameters, not measured catch probabilities.
The range labels should not be read as requiring the user first to land a
Good/Great throw: the observed gate tests hitPokemon, not the original grade.
The random bit for modes 1–3 is consistent with roughly 50/50 curve status,
not a demonstrated 50% probability of an Excellent grade in mode 3.

### Runtime implementation

- Handler `0x25b9fc` reads a catch request and preference ID 13.
- It decodes the SwiftProtobuf catch structure, including `hitPokemon`.
  `0x25bb24` loads that Boolean; `0x25bb34–0x25bb38` requires it to equal 1.
- None/missing/invalid preference, decoding failure, or a miss takes the
  disable path at `0x25bc38`.
- Active hit path calculates the parameters above and invokes
  `+[wNPgAm aGpWUJ:oEHufv:dNiggy:fkkkWU:]` at `0x96708`.
  This stores an enable flag and three doubles. One double is fixed at 1.0.
- Consumer `_SogDWk` at `0x98e34` processes request objects. At
  `0x98f40–0x98f80`, it checks the object's class name against the literal
  `CatchPokemonProto` (string address `0x828000`) and the enhancement flag.
  It then overwrites three double fields at object offsets +0x20, +0x38,
  and +0x40 with generated quality, spin, and fixed 1.0, respectively.
  These offsets are consistent with reticle size, spin modifier, and normalized
  hit position in the catch request layout; the current Unity object layout
  has not independently been recovered or verified on the running phone.
- Hook setup references `_SogDWk` at `0x947f0–0x94800`. This is an actual
  request-data hook, not merely a menu label or reward-label drawing routine.
- No ball-path planning, target-depth measurement, attack timing, berry
  feeding, or automatic touch gesture was found in this traced feature path.

### Preservation in Hunter artifact

The following byte ranges are identical between stock framework and signed
Hunter framework:

- Throw controller: `0x120388–0x121d3c`.
- Mode enum/labels: `0x158e54–0x159098`.
- Catch/preference handler: `0x25b9fc–0x25bd64`.
- Enhancement parameter setter: `0x96708–0x9672c`.
- Request consumer: `0x98e34–0x99180`.

This rules out direct overwriting of these feature bodies by our IPA patches.
It does not rule out an upstream iPogo bug, inactive hook, changed Unity layout,
user preference issue, indirect runtime interaction, or server-side changes.

## Documentation versus proof

Official feature description:
https://ipogo.app/# (Enhanced Throw / Remember last ball modal).
Retrieved via https://ipogo.app/?coords=23.316299%2C120.26979 because the plain
homepage fetch timed out. The page describes selected throw XP and randomized
options; its displayed release is older than this local 4.3.9 artifact.

The code supports reported throw-metadata enhancement after an actual hit,
not an auto-aim/auto-curve gesture. The official wording emphasizes XP.
Static client inspection cannot establish whether today's game server applies
these altered fields to capture odds. Do not claim that this feature proves
safer Shundo catching, or definitively assert it cannot affect odds based only
on this analysis.

## Current verdict and minimal next validation

Feature implementation exists, mode selection is connected to runtime logic,
and inspected bodies survived Hunter patching. No specific break was found.
Live functionality remains UNVERIFIED: no settings or phone were touched.

With new user authorization, select Excellent with Curve and land an ordinary
straight throw on an ordinary Pokémon, recording the landing and successful
catch summary. Excellent + Curveball credit despite a clearly non-excellent,
non-curved physical throw would demonstrate the grading override for that
test. A miss or breakout alone is inconclusive; even successful XP override
does not measure catch-rate improvement. Keep enhancement off while evaluating
the physical throw controller's actual precision, since it can mask misses of
the target ring in the final reported grade.
