# Shundo Hunter control panel design brief

## Feature summary

A production-ready dark macOS utility for receiving 100-IV sightings, managing the hunt queue, monitoring Discord and phone connections, and later running the external location/check loop.

## Primary action

Start or supervise a hunt while understanding the current target and system health at a glance.

## Visual direction

Restrained dark interface inspired by Raycast immediacy, Linear hierarchy, and Activity Monitor data legibility. Warm graphite surfaces, muted mint for success, amber for queued or priority state, and coral for errors. The approved north star is the sequential hunt-timeline probe.

## Scope

Production-ready desktop utility with a primary Hunt screen and a dedicated Settings screen. Visible controls include Start, Pause, Skip, Prioritize, and Filters.

## Layout

- Left rail: watched Discord channels and navigation.
- Top command bar: primary hunt controls and connection status.
- Center: sequential hunt timeline with the current target emphasized.
- Bottom: Discord, phone, and system event log.
- Statistics: durable lifetime totals and per-species check/shundo history.

## States

First-run setup, disconnected relay, empty queue, receiving data, ready, running, paused, checking, checked, skipped, expired, error, and Shundo detected.

## Interaction model

Keyboard-friendly controls, obvious active states, minimal confirmation, direct prioritization, species and channel filtering, and explanatory disabled states.

## Content

Species, CP, level, coordinates, source channel, observation age, queue state, connection health, lifetime totals, per-species totals, and event history.

## Constraints and anti-goals

Use only real application data. Do not use copied Discord user tokens or cookies, decorative Pokémon artwork, neon gamer styling, glassmorphism, gradients, giant metric tiles, excessive pills, or nested card grids.

## Visual probe decision

The timeline direction was selected. Carry into code: the left channel rail, compact top command bar, sequential status topology, bottom event log, restrained semantic colors, and tabular data. Do not literalize fake channels, fake statistics, or generated metadata.
