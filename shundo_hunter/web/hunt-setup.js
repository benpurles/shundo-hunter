/* Pure UI planning: selecting a mode never prepares, moves, or starts a phone. */
(function (root) {
  function huntSetup(s, mode, confirmed, hasTargets) {
    const result = (title, detail, action, label, step = 0) => ({title, detail, action, label, step});
    if (!s) return result("Connecting to Hunter…", "Waiting for the local app. No phone actions are available yet.", null, "Connecting…");
    const n = s.notificationWatcher || {};
    if (s.encounterProtected || s.huntState === "shundo") return result("Shundo found — inspect your phone", "The hunt is stopped. Catch manually when ready. Do not release protection until you have finished.", "manage", "View encounter protection");
    if (s.huntState === "running") return result(s.overnightActive ? "Overnight hunt is running" : "Casual hunt is running", s.overnightActive ? "Keep iPogo open. On a Shundo, Hunter stops; AI opening only runs if enabled. Check the health status below." : "You’re in charge of the phone. Hunter stops and alerts on a Shundo; automatic encounter opening is not armed.", "timeline", "View active hunt");
    if (s.huntState === "paused" || s.huntWorkerAlive) return result("Your hunt is paused", "Review the pause reason on the timeline. This checklist will not resume it or change modes automatically.", "timeline", "Review paused hunt");
    if (s.huntState === "error") return result("Reset the stopped hunt", "The previous hunt ended with an error. End its preparation, then follow this checklist again. Your location will not be reset by this step.", "unprepare", "End preparation & reset hunt");
    if (mode === "casual") {
      if (s.overnightActive) return result("End overnight setup first", "Stop/end preparation, then explicitly end overnight setup below. Selecting Casual alone does not release a protected encounter or change alerts.", "manage", "Manage overnight setup");
      if (n.alertSource === "direct") return s.ipogoPrepared
        ? result("Switch back to casual alerts", "End phone preparation first, then select Mac mirrored alerts. This does not change location.", "unprepare", "End phone preparation")
        : result("Choose casual alerts", "Use Mac mirrored notifications for this casual session. Keep the Mac notification path available; overnight protection will stay off.", "source-mac", "Use Mac alerts for casual hunting");
      if (!s.phoneConnected) return result("Connect your iPhone", "Open iPogo on your unlocked iPhone. Connect with USB or previously paired Wi-Fi, then check the connection.", "connection", "Check phone connection");
      if (!s.ipogoPrepared) return result("Prepare for a casual hunt", "Prepare iPogo, verify notifications, then start. No overnight setup or AI is required.", "prepare", "Prepare phone");
      if (!n.unattendedReady) return result("Verify notifications", "Send a queued target with Test on phone and wait for a real Hundo notification. Hunter must confirm it received the alert before starting.", "proof", "Choose a test target");
      if (!s.ipogoSpawnRuntimeVerified || s.notificationWatcherState !== "listening") return result("Phone setup needs attention", "The runtime or notification reader is not ready. Recheck preparation before starting.", "prepare", "Recheck phone setup");
      if (!hasTargets) return result("Add fresh targets", "Select a coordinate source and sync fresh sightings on the Hunt page.", "feed", "Open hunt queue");
      return result("Ready for a casual hunt", "Hunter checks your queue and stops on a Shundo. You open and catch it yourself. Keep your chosen notification path available.", "start", "Start casual hunt");
    }
    if (!s.phoneConnected) return result("1. Connect your iPhone", "Leave iPogo open on your unlocked phone. Use USB or previously paired Wi-Fi on the same network as this Mac.", "connection", "Check phone connection", 1);
    if (!s.overnightActive && s.ipogoPrepared) return result("Finish casual preparation first", "End preparation before setting up overnight mode. This stops the hunt but does not reset your location.", "unprepare", "End preparation for overnight", 1);
    if (!s.overnightActive && !confirmed) return result("1. Get your devices ready", "Complete the device checklist below. Checking the box does not start a hunt or change your phone settings.", null, "Confirm the device checklist", 1);
    if (!s.overnightActive) return result("2. Connect overnight protection", "Start the direct iPhone alert reader and keep this Mac awake for up to 12 hours. The Mac display can still sleep. This does not start hunting.", "setup", "Set up overnight mode", 2);
    if (!s.overnightMacAwake || s.overnightState !== "setup" || s.overnightSecondsRemaining <= 0) return result("Overnight setup needs attention", "End this setup, then reconnect. Hunting stays blocked until wake protection and the controller are ready.", "manage", "Review setup & recovery", 2);
    if (!s.visionConfigured) return result("3. Enable automatic encounter opening", "Review AI settings below. A saved API key, screenshot consent and enabled AI are required for this guided overnight hunt. No balls or berries are used.", "ai", "Review AI setup", 3);
    if (!s.ipogoPrepared) return result("4. Prepare iPogo", "Verify the installed runtime and begin listening for fresh phone notifications.", "prepare", "Prepare phone for overnight", 4);
    if (n.alertSource !== "direct" || !(n.huntReady ?? n.unattendedReady) || s.notificationWatcherState !== "listening") return result("Connect the phone alert reader", "The reader must be connected, but no test notification is required. Recheck preparation if it stays disconnected.", "prepare", "Recheck phone reader", 4);
    if (!s.ipogoSpawnRuntimeVerified) return result("Phone runtime needs verification", "Recheck preparation. Hunter cannot start until the installed runtime is verified.", "prepare", "Recheck phone setup", 4);
    if (!hasTargets) return result("5. Load your hunt queue", "Choose your coordinate source and sync fresh targets. Expired coordinates are not eligible.", "feed", "Open hunt queue", 5);
    return result("Ready to start overnight", "No separate test needed. Start the walking hunt; the first real Hundo verifies alerts automatically. Until then, delivery is unverified. On a Shundo, Hunter stops and attempts to open the encounter for you.", "start", "Start overnight hunt", 5);
  }
  if (typeof module !== "undefined" && module.exports) module.exports = huntSetup;
  else root.huntSetup = huntSetup;
})(typeof window !== "undefined" ? window : globalThis);
