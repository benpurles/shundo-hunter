# Shundo Hunter

Shundo Hunter is a personal macOS utility that collects 100-IV Pokémon sightings from selected Discord channels, stores a durable queue, and supervises an iPhone-based location-checking workflow. Its eventual success condition is to stop on an iPogo Shundo notification and notify the operator without automatically clicking or catching Pokémon.

## Primary user

One operator using a Mac and a USB-connected iPhone. The app is expected to run for long sessions with minimal attention, so health, current target, queue progress, and exceptions must be legible at a glance.

## Core jobs

- Receive and normalize 100-IV sightings without exporting Discord credentials.
- Show the current target and sequential queue state.
- Start, pause, skip, and prioritize checks.
- Filter and prioritize by Pokémon species and source channel.
- Preserve lifetime totals and per-species checking history across restarts.
- Expose clear Discord relay and iPhone connection status.
- Maintain a detailed local event history for diagnosis.

## Product principles

- Operational clarity over decoration.
- Real status only; never imply the phone or feed is connected when it is not.
- Familiar macOS interactions and keyboard access.
- Durable local data with no Discord token or cookie storage.
- Restrained color reserved for status and actions.
