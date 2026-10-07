const state = {
  status: null,
  sightings: [],
  queue: [],
  channels: [],
  events: [],
  stats: { received: 0, checked: 0, shundos: 0, skipped: 0, species: [] },
  preferences: { mode: "all", rankedSpecies: [], availableSpecies: [] },
  selectedId: null,
  timelineFilter: "",
  queuedOnly: false,
  eventSource: "all",
  statsSearch: "",
  activeView: "hunt",
  relayPath: "shundo_hunter/browser_relay",
  huntSettingsDirty: false,
  polling: false,
  queueSaving: false,
  draggedSightingId: null
};

const elements = {
  timeline: document.querySelector("#timeline"),
  eventLog: document.querySelector("#event-log"),
  channelList: document.querySelector("#channel-list"),
  channelCount: document.querySelector("#channel-count"),
  huntHeading: document.querySelector("#hunt-heading"),
  huntMessage: document.querySelector("#hunt-message"),
  huntBadge: document.querySelector("#hunt-state-badge"),
  manualSpawnToggle: document.querySelector("#manual-spawn-toggle"),
  manualSpawnForm: document.querySelector("#manual-spawn-form"),
  manualSpecies: document.querySelector("#manual-species"),
  manualCoordinates: document.querySelector("#manual-coordinates"),
  manualSpeciesCatalog: document.querySelector("#manual-species-catalog"),
  cancelManualSpawn: document.querySelector("#cancel-manual-spawn"),
  addManualSpawn: document.querySelector("#add-manual-spawn"),
  queueOrderDetail: document.querySelector("#queue-order-detail"),
  resetQueueOrder: document.querySelector("#reset-queue-order"),
  prepare: document.querySelector("#prepare-button"),
  prepareLabel: document.querySelector("#prepare-label"),
  start: document.querySelector("#start-button"),
  startLabel: document.querySelector("#start-label"),
  pause: document.querySelector("#pause-button"),
  skip: document.querySelector("#skip-button"),
  prioritize: document.querySelector("#prioritize-button"),
  sendPhone: document.querySelector("#send-phone-button"),
  relayState: document.querySelector("#relay-state"),
  sidebarHealthDot: document.querySelector("#sidebar-health-dot"),
  sidebarHealthLabel: document.querySelector("#sidebar-health-label"),
  sourceFootnote: document.querySelector("#source-footnote"),
  filterToggle: document.querySelector("#filter-toggle"),
  filterPanel: document.querySelector("#filter-panel"),
  speciesFilter: document.querySelector("#species-filter"),
  queuedOnly: document.querySelector("#queued-only"),
  toast: document.querySelector("#toast"),
  settingsRelayBadge: document.querySelector("#settings-relay-badge"),
  relayPath: document.querySelector("#relay-path"),
  phoneState: document.querySelector("#phone-state"),
  phoneSettingsBadge: document.querySelector("#phone-settings-badge"),
  phoneDeviceName: document.querySelector("#phone-device-name"),
  phoneVersion: document.querySelector("#phone-version"),
  phoneLocation: document.querySelector("#phone-location"),
  phoneDelivery: document.querySelector("#phone-delivery"),
  ipogoRuntime: document.querySelector("#ipogo-runtime"),
  ipogoPrepared: document.querySelector("#ipogo-prepared"),
  ipogoAutoRefresh: document.querySelector("#ipogo-auto-refresh"),
  ipogoRefreshState: document.querySelector("#ipogo-refresh-state"),
  ipogoRefreshCount: document.querySelector("#ipogo-refresh-count"),
  ipogoLastRefresh: document.querySelector("#ipogo-last-refresh"),
  notificationWatcher: document.querySelector("#notification-watcher"),
  worldScanWatcher: document.querySelector("#world-scan-watcher"),
  worldScanLast: document.querySelector("#world-scan-last"),
  macNotificationBridge: document.querySelector("#mac-notification-bridge"),
  macNotificationLast: document.querySelector("#mac-notification-last"),
  enableNotificationAccess: document.querySelector("#enable-notification-access"),
  refreshPhone: document.querySelector("#refresh-phone"),
  enableWifi: document.querySelector("#enable-wifi"),
  preparePhoneSettings: document.querySelector("#prepare-phone-settings"),
  clearPhoneLocation: document.querySelector("#clear-phone-location"),
  readinessIcon: document.querySelector("#readiness-icon"),
  readinessSection: document.querySelector("#readiness-section"),
  readinessMessage: document.querySelector("#readiness-message"),
  readinessPhone: document.querySelector("#readiness-phone"),
  readinessSource: document.querySelector("#readiness-source"),
  readinessLocation: document.querySelector("#readiness-location"),
  readinessAlerts: document.querySelector("#readiness-alerts"),
  alertAssurance: document.querySelector("#alert-assurance"),
  alertAssuranceDot: document.querySelector("#alert-assurance-dot"),
  alertAssuranceTitle: document.querySelector("#alert-assurance-title"),
  alertAssuranceDetail: document.querySelector("#alert-assurance-detail"),
  alertCurrentProof: document.querySelector("#alert-current-proof"),
  alertLastProof: document.querySelector("#alert-last-proof"),
  alertRunProof: document.querySelector("#alert-run-proof"),
  selectedOnly: document.querySelector("#selected-only"),
  rulesModeBadge: document.querySelector("#rules-mode-badge"),
  prioritySpecies: document.querySelector("#priority-species"),
  speciesSuggestions: document.querySelector("#species-suggestions"),
  priorityList: document.querySelector("#priority-species-list"),
  priorityEmpty: document.querySelector("#priority-empty"),
  internalFeedBadge: document.querySelector("#internal-feed-badge"),
  internalFeedLastSync: document.querySelector("#internal-feed-last-sync"),
  internalFeedCount: document.querySelector("#internal-feed-count"),
  internalFeedMessage: document.querySelector("#internal-feed-message"),
  syncInternalFeed: document.querySelector("#sync-internal-feed"),
  pokexperienceFeedBadge: document.querySelector("#pokexperience-feed-badge"),
  pokexperienceAppState: document.querySelector("#pokexperience-app-state"),
  pokexperienceLastSync: document.querySelector("#pokexperience-last-sync"),
  pokexperienceCount: document.querySelector("#pokexperience-count"),
  pokexperienceCatalogCoverage: document.querySelector("#pokexperience-catalog-coverage"),
  pokexperienceReadyCount: document.querySelector("#pokexperience-ready-count"),
  pokexperienceResolverState: document.querySelector("#pokexperience-resolver-state"),
  pokexperienceMessage: document.querySelector("#pokexperience-message"),
  syncPokexperience: document.querySelector("#sync-pokexperience"),
  huntFeedSource: document.querySelector("#hunt-feed-source"),
  settingsFeedSource: document.querySelector("#settings-feed-source"),
  activeFeedTitle: document.querySelector("#active-feed-title"),
  activeFeedDetail: document.querySelector("#active-feed-detail"),
  huntFeedAction: document.querySelector("#hunt-feed-action"),
  sourceModeBadge: document.querySelector("#source-mode-badge"),
  sourceInternalCount: document.querySelector("#source-internal-count"),
  sourcePokexperienceCount: document.querySelector("#source-pokexperience-count"),
  sourceDiscordCount: document.querySelector("#source-discord-count"),
  sourceManualCount: document.querySelector("#source-manual-count"),
  timingSettingsBadge: document.querySelector("#timing-settings-badge"),
  huntTimingForm: document.querySelector("#hunt-timing-form"),
  huntDwellSeconds: document.querySelector("#hunt-dwell-seconds"),
  hundoCooldownSeconds: document.querySelector("#hundo-cooldown-seconds"),
  recoveryFailureThreshold: document.querySelector("#recovery-failure-threshold"),
  saveHuntTiming: document.querySelector("#save-hunt-timing"),
  timingSettingsNote: document.querySelector("#timing-settings-note")
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function plural(count, singular, pluralForm = `${singular}s`) {
  return count === 1 ? singular : pluralForm;
}

function formatNumber(value) {
  return new Intl.NumberFormat().format(Number(value || 0));
}

function formatAge(timestamp) {
  if (!timestamp) return "Unknown";
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(timestamp).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function formatTimeRemaining(timestamp) {
  if (!timestamp) return "Unknown";
  const seconds = Math.ceil((new Date(timestamp).getTime() - Date.now()) / 1000);
  if (!Number.isFinite(seconds)) return "Unknown";
  if (seconds <= 0) return "Gone";
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  if (minutes < 60) return remainder ? `${minutes}m ${remainder}s` : `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

function clockTime(timestamp) {
  if (!timestamp) return "";
  return new Intl.DateTimeFormat([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(new Date(timestamp));
}

function showToast(message, error = false) {
  elements.toast.textContent = message;
  elements.toast.classList.toggle("is-error", error);
  elements.toast.hidden = false;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => { elements.toast.hidden = true; }, 4200);
}

function feedContext() {
  const reportedMode = state.status?.feedSourceMode;
  const mode = ["ipogo-internal", "pokexperience", "discord"].includes(reportedMode)
    ? reportedMode
    : "ipogo-internal";
  const counts = state.status?.feedSourceCounts || {};
  const fresh = Number(state.status?.activeQueueCount ?? counts[mode] ?? 0);
  const labels = {
    "ipogo-internal": "iPogo internal feed",
    pokexperience: "PokeXperience background feed",
    discord: "Discord / Chrome relay"
  };
  return {
    mode,
    fresh,
    internalFresh: Number(counts["ipogo-internal"] || 0),
    pokexperienceFresh: Number(counts.pokexperience || 0),
    discordFresh: Number(counts.discord || 0),
    manualFresh: Number(counts.manual || 0),
    label: labels[mode]
  };
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) }
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `Request failed with ${response.status}`);
  return data;
}

async function refresh() {
  if (state.polling || state.queueSaving) return;
  state.polling = true;
  try {
    const [status, sightings, queue, channels, events, stats, preferences] = await Promise.all([
      api("/api/status"),
      api("/api/sightings?limit=250"),
      api("/api/queue?limit=250"),
      api("/api/channels"),
      api("/api/events"),
      api("/api/stats"),
      api("/api/preferences")
    ]);
    state.status = status;
    state.relayPath = status.relayPath || state.relayPath;
    state.queue = queue.sightings;
    const sightingsById = new Map(sightings.sightings.map((item) => [item.id, item]));
    state.queue.forEach((item) => sightingsById.set(item.id, item));
    state.sightings = [...sightingsById.values()];
    if (status.currentTarget && !state.sightings.some((item) => item.id === status.currentTarget.id)) {
      state.sightings.unshift(status.currentTarget);
    }
    state.channels = channels.channels;
    state.events = events.events;
    state.stats = stats;
    state.preferences = preferences;
    elements.relayPath.textContent = state.relayPath;
    if (state.selectedId && !state.sightings.some((item) => item.id === state.selectedId)) {
      state.selectedId = null;
    }
    render();
  } catch (error) {
    renderOffline();
  } finally {
    state.polling = false;
  }
}

function render() {
  renderConnection();
  renderControls();
  renderAlertAssurance();
  renderChannels();
  renderTimeline();
  renderEvents();
  renderStats();
  renderPreferences();
  renderHuntSettings();
  renderCatchLab();
  renderOvernight();
}

function renderHuntSettings() {
  const locked = ["running", "paused"].includes(state.status?.huntState);
  if (!state.huntSettingsDirty) {
    elements.huntDwellSeconds.value = String(Number(state.status?.huntDwellSeconds ?? 45));
    elements.hundoCooldownSeconds.value = String(Number(state.status?.huntHundoCooldownSeconds ?? 30));
    elements.recoveryFailureThreshold.value = String(Number(state.status?.ipogoRecoveryTimeoutThreshold ?? 2));
  }
  elements.huntDwellSeconds.disabled = locked;
  elements.hundoCooldownSeconds.disabled = locked;
  elements.recoveryFailureThreshold.disabled = locked;
  elements.saveHuntTiming.disabled = locked || !state.huntSettingsDirty;
  elements.timingSettingsBadge.className = `state-badge ${state.huntSettingsDirty ? "" : "is-running"}`;
  elements.timingSettingsBadge.textContent = state.huntSettingsDirty ? "Unsaved" : "Saved";
  elements.timingSettingsNote.textContent = locked
    ? "Stop the active hunt before changing timing settings."
    : "Defaults are 45 seconds for map loading, 30 seconds after a Hundo, and 2 failures. Saved values remain active after restarting the app.";
}

function renderOffline() {
  state.status = null;
  renderGuidedSetup();
  elements.relayState.innerHTML = '<span class="status-dot is-offline"></span><span>Feed unavailable</span>';
  elements.sidebarHealthDot.className = "status-dot is-offline";
  elements.sidebarHealthLabel.textContent = "Service offline";
  elements.settingsRelayBadge.className = "state-badge is-offline";
  elements.settingsRelayBadge.textContent = "Service offline";
  elements.start.disabled = true;
  elements.prepare.disabled = true;
  elements.pause.disabled = true;
  elements.skip.disabled = true;
  elements.prioritize.disabled = true;
  elements.sendPhone.disabled = true;
  elements.huntFeedSource.disabled = true;
  elements.settingsFeedSource.disabled = true;
  elements.huntFeedAction.disabled = true;
  elements.syncPokexperience.disabled = true;
  elements.huntDwellSeconds.disabled = true;
  elements.hundoCooldownSeconds.disabled = true;
  elements.recoveryFailureThreshold.disabled = true;
  elements.saveHuntTiming.disabled = true;
}

function renderConnection() {
  const feed = feedContext();
  const reportedInternalState = state.status?.internalFeedState || "idle";
  const internalLastSyncAt = state.status?.internalFeedLastSyncAt
    || state.status?.internalFeedStoredLastSyncAt;
  const internalState = ["waiting", "error", "live", "synced", "stale", "offline"].includes(reportedInternalState)
    ? reportedInternalState
    : (feed.internalFresh > 0 ? "synced" : (internalLastSyncAt ? "expired" : "idle"));
  const pokexperienceState = state.status?.pokexperienceBridgeState || "not-started";
  const pokexperienceConnected = Boolean(state.status?.pokexperienceBridgeConnected);
  const pokexperienceRunning = Boolean(state.status?.pokexperienceAppRunning);
  const pokexperienceSyncing = pokexperienceState === "scanning";
  const relayConnected = Boolean(state.status?.relayConnected);
  const connected = feed.mode === "ipogo-internal"
    ? (feed.internalFresh > 0 || ["waiting", "live", "synced"].includes(internalState))
    : (feed.mode === "pokexperience"
      ? (pokexperienceConnected || feed.pokexperienceFresh > 0)
      : relayConnected);
  const visible = Number(state.status?.visibleMessages || 0);
  const relayLabel = feed.mode === "ipogo-internal"
    ? (internalState === "waiting"
      ? "iPogo feed · connecting"
      : (internalState === "live"
        ? `iPogo live feed · ${feed.internalFresh} fresh`
        : (feed.internalFresh > 0 ? `iPogo feed · ${feed.internalFresh} fresh` : "iPogo feed · start required")))
    : (feed.mode === "pokexperience"
      ? (pokexperienceSyncing
        ? "PokeXperience · syncing"
        : (pokexperienceConnected
          ? `PokeXperience · ${feed.pokexperienceFresh} fresh`
          : "PokeXperience · feed offline"))
      : (relayConnected
        ? (visible ? `Discord feed · ${visible} messages visible` : "Discord feed connected")
        : "Discord feed · relay offline"));
  elements.relayState.innerHTML = `<span class="status-dot ${connected ? "" : "is-offline"}"></span><span>${relayLabel}</span>`;
  elements.sidebarHealthDot.className = `status-dot ${connected ? "" : "is-offline"}`;
  elements.sidebarHealthLabel.textContent = connected ? `${feed.label} ready` : `${feed.label} needs attention`;
  elements.sourceFootnote.textContent = feed.mode === "discord"
    ? "Discord credentials stay in Chrome"
    : "Expired coordinates delete automatically";
  elements.settingsRelayBadge.className = `state-badge ${relayConnected ? "is-running" : "is-offline"}`;
  elements.settingsRelayBadge.textContent = relayConnected ? (visible ? `${visible} visible` : "Connected") : "Not connected";

  const internalLabels = {
    idle: "Not synced",
    waiting: "Waiting on iPhone",
    live: "Live",
    stale: "Updates stalled",
    synced: "Synced",
    offline: "Disconnected",
    expired: "Sync required",
    error: "Needs attention"
  };
  elements.internalFeedBadge.className = `state-badge ${["synced", "live"].includes(internalState) ? "is-running" : (internalState === "waiting" ? "" : "is-offline")}`;
  elements.internalFeedBadge.textContent = internalLabels[internalState] || internalState;
  elements.internalFeedLastSync.textContent = internalLastSyncAt
    ? formatAge(internalLastSyncAt)
    : "Not yet";
  elements.internalFeedCount.textContent = formatNumber(feed.internalFresh);
  elements.internalFeedMessage.textContent = state.status?.internalFeedLastError
    || (internalState === "synced" && reportedInternalState === "idle"
      ? `${formatNumber(feed.internalFresh)} fresh targets remain from the last sync.`
      : state.status?.internalFeedMessage)
    || "Ready to sync";
  const pokexperienceHealthy = pokexperienceConnected
    && !["error", "catalog-incomplete"].includes(pokexperienceState);
  const pokexperienceLabels = {
    "not-started": "Not synced",
    idle: "Ready",
    scanning: "Syncing",
    synced: "Synced",
    "catalog-incomplete": "Partial catalog",
    error: "Needs attention"
  };
  elements.pokexperienceFeedBadge.className = `state-badge ${pokexperienceHealthy ? "is-running" : (pokexperienceSyncing ? "is-pending" : "is-offline")}`;
  elements.pokexperienceFeedBadge.textContent = pokexperienceLabels[pokexperienceState] || pokexperienceState;
  elements.pokexperienceAppState.textContent = pokexperienceConnected ? "Background connection active" : "Connecting";
  elements.pokexperienceLastSync.textContent = state.status?.pokexperienceLastSyncAt
    ? formatAge(state.status.pokexperienceLastSyncAt)
    : "Not yet";
  elements.pokexperienceCount.textContent = formatNumber(feed.pokexperienceFresh);
  const catalogComplete = Boolean(state.status?.pokexperienceCatalogComplete);
  const catalogRows = Number(state.status?.pokexperienceCatalogRows || 0);
  const catalogPages = Number(state.status?.pokexperienceCatalogPages || 0);
  const catalogExpected = Number(state.status?.pokexperienceCatalogExpectedRows || 0);
  elements.pokexperienceCatalogCoverage.textContent = catalogRows > 0
    ? `${formatNumber(catalogRows)}${catalogExpected ? ` of ${formatNumber(catalogExpected)}` : ""} live · ${catalogComplete ? "complete" : "partial"}`
    : "Not verified";
  elements.pokexperienceCatalogCoverage.title = catalogPages > 0
    ? "Complete encrypted feed snapshot"
    : "Run a PokeXperience sync to verify complete-feed coverage.";
  const coordinatesReady = Number(state.status?.pokexperienceCoordinatesReady || 0);
  const coordinatesResolving = Number(state.status?.pokexperienceCoordinatesResolving || 0);
  const coordinatesPending = Number(state.status?.pokexperienceCoordinatesPending || 0);
  elements.pokexperienceReadyCount.textContent = `${formatNumber(coordinatesReady)} ready · ${formatNumber(coordinatesPending)} queued`;
  elements.pokexperienceResolverState.textContent = coordinatesPending > 0
    ? "Waiting for the next background refresh"
    : "All coordinates included";
  elements.pokexperienceMessage.textContent = state.status?.pokexperienceBridgeMessage || "Ready to sync";
  const huntLocked = ["running", "paused"].includes(state.status?.huntState);
  elements.huntFeedSource.value = feed.mode;
  elements.settingsFeedSource.value = feed.mode;
  elements.huntFeedSource.disabled = huntLocked;
  elements.settingsFeedSource.disabled = huntLocked;
  elements.sourceModeBadge.className = `state-badge ${connected ? "is-running" : "is-offline"}`;
  elements.sourceModeBadge.textContent = feed.mode === "ipogo-internal"
    ? "iPogo internal"
    : (feed.mode === "pokexperience" ? "PokeXperience" : "Discord relay");
  elements.sourceInternalCount.textContent = formatNumber(feed.internalFresh);
  elements.sourcePokexperienceCount.textContent = formatNumber(feed.pokexperienceFresh);
  elements.sourceDiscordCount.textContent = formatNumber(feed.discordFresh);
  elements.sourceManualCount.textContent = formatNumber(feed.manualFresh);
  elements.activeFeedTitle.textContent = `${feed.label} selected`;
  if (feed.mode === "ipogo-internal") {
    elements.activeFeedDetail.textContent = internalState === "waiting"
      ? "Hunter Lab is loading iPogo’s authenticated 100-IV feed automatically. No phone taps are needed."
      : (internalState === "live"
        ? `${formatNumber(feed.fresh)} fresh ${plural(feed.fresh, "target")} · updates are arriving automatically.`
        : (feed.fresh > 0
          ? `${formatNumber(feed.fresh)} fresh ${plural(feed.fresh, "target")} · automatic refresh is armed.`
          : "No fresh targets. Choose Sync iPogo feed before hunting."));
    elements.huntFeedAction.textContent = internalState === "waiting"
      ? "Connecting…"
      : (internalState === "live" ? "Live feed running" : "Start live feed");
    elements.huntFeedAction.disabled = !state.status?.phoneConnected || ["waiting", "live"].includes(internalState) || huntLocked;
  } else if (feed.mode === "pokexperience") {
    elements.activeFeedDetail.textContent = pokexperienceSyncing
      ? "Downloading and decrypting the complete background feed. Your mouse and clipboard remain untouched."
      : (feed.fresh > 0
        ? `${formatNumber(feed.fresh)} fresh ${plural(feed.fresh, "target")} · ${catalogComplete ? "full feed verified" : "feed coverage incomplete"} · ${formatNumber(coordinatesReady)} coordinates ready.`
        : "Connect to the complete PokeXperience background feed before hunting.");
    elements.huntFeedAction.textContent = pokexperienceSyncing ? "Syncing…" : "Sync PokeXperience";
    elements.huntFeedAction.disabled = pokexperienceSyncing || huntLocked;
  } else {
    elements.activeFeedDetail.textContent = relayConnected
      ? `${formatNumber(feed.fresh)} fresh ${plural(feed.fresh, "target")} from the Chrome relay.`
      : "Chrome relay is offline. Open the setup guide before starting.";
    elements.huntFeedAction.textContent = "Open relay setup";
    elements.huntFeedAction.disabled = huntLocked;
  }

  const phoneConnected = Boolean(state.status?.phoneConnected);
  const phoneName = state.status?.phoneName || "iPhone";
  const phoneError = state.status?.phoneLastError || "No paired iPhone detected over USB or Wi-Fi";
  const phoneTransport = state.status?.phoneConnectionType === "Network" ? "Wi-Fi" : "USB";
  elements.phoneState.innerHTML = `<span class="device-icon" aria-hidden="true"></span><span>${
    phoneConnected ? `${escapeHtml(phoneName)} connected` : "Phone offline"
  }</span>`;
  elements.phoneState.title = phoneConnected ? `Connected over ${phoneTransport}` : phoneError;
  elements.phoneSettingsBadge.className = `state-badge ${phoneConnected ? "is-running" : "is-offline"}`;
  elements.phoneSettingsBadge.textContent = phoneConnected ? `${phoneTransport} connected` : "Not connected";
  elements.enableWifi.disabled = !phoneConnected;
  elements.phoneDeviceName.textContent = phoneConnected ? phoneName : phoneError;
  elements.phoneVersion.textContent = state.status?.phoneProductVersion || "Unknown";
  const location = state.status?.phoneSimulatedLocation;
  elements.phoneLocation.textContent = location
    ? `${Number(location.latitude).toFixed(6)}, ${Number(location.longitude).toFixed(6)}`
    : "None set by this session";
  elements.clearPhoneLocation.disabled = !phoneConnected || !location;

  const prepared = Boolean(state.status?.ipogoPrepared);
  const runtimeVerified = Boolean(state.status?.ipogoSpawnRuntimeVerified);
  const runtimeVersion = state.status?.ipogoSpawnRuntimeVersion;
  const phoneWatcherReady = state.status?.notificationWatcherState === "listening";
  const usbWatcherState = state.status?.notificationWatcher?.usbWatcherState || "stopped";
  const bridgeState = state.status?.notificationWatcher?.macBridgeState || "not-configured";
  const bridgeTrusted = Boolean(state.status?.notificationWatcher?.macBridgeTrusted);
  const reportedBridgeReady = state.status?.notificationWatcher?.macBridgeReady;
  const directAlerts = state.status?.notificationWatcher?.alertSource === "direct";
  const bridgeReady = directAlerts ? Boolean(state.status?.notificationWatcher?.unattendedReady) : reportedBridgeReady === undefined
    ? bridgeState === "listening" && bridgeTrusted
    : Boolean(reportedBridgeReady);
  const lastAlert = state.status?.notificationWatcher?.lastObservedAlert || state.status?.notificationWatcher?.lastEvent;
  const worldWatcherState = state.status?.notificationWatcher?.worldScanWatcherState || "unavailable";
  const lastWorldEvent = state.status?.notificationWatcher?.lastWorldScanEvent;
  const lastWorldSnapshot = state.status?.notificationWatcher?.lastWorldScanSnapshot;
  const lastAlertLabel = lastAlert?.is_shundo || lastAlert?.kind === "shundo"
    ? "Shundo"
    : (lastAlert?.is_hundo || lastAlert?.kind === "hundo" ? "Hundo" : "Alert");
  const delivery = state.status?.phoneLocationDelivery;
  const walkingLoop = delivery === "walking-loop-1hz";
  const locationActive = walkingLoop || delivery === "continuous-1hz";
  const walkRadius = Number(state.status?.phoneMovementRadiusMeters || 20);
  const walkSpeed = Number(state.status?.phoneMovementSpeedKmh || 5);
  elements.phoneDelivery.textContent = walkingLoop
    ? `Walking loop · ${walkRadius.toFixed(0)} m · ${walkSpeed.toFixed(1)} km/h`
    : (locationActive ? "Continuous · 1 update/second" : "Idle");
  elements.ipogoPrepared.textContent = prepared ? "Prepared" : "Not prepared";
  elements.ipogoRuntime.textContent = runtimeVerified
    ? `Verified · v${runtimeVersion}`
    : (state.status?.ipogoSpawnRuntimeError || "Not verified");
  const refreshState = state.status?.ipogoRefreshState || "idle";
  const refreshStateLabels = {
    idle: "Ready",
    restarting: "Restarting iPogo",
    settling: "Waiting for world load",
    verifying: "Awaiting Hundo proof",
    verified: "World load verified",
    failed: "Paused for attention"
  };
  elements.ipogoAutoRefresh.textContent = state.status?.ipogoAutoRefreshEnabled
    ? `Clean relaunch after ${state.status.ipogoRefreshVisitInterval} completed map loads`
    : "Disabled";
  elements.ipogoRefreshState.textContent = refreshStateLabels[refreshState] || refreshState;
  elements.ipogoRefreshCount.textContent = formatNumber(state.status?.ipogoRefreshesThisRun || 0);
  elements.ipogoLastRefresh.textContent = state.status?.ipogoLastRefreshAt
    ? formatAge(state.status.ipogoLastRefreshAt)
    : "Not yet";
  elements.notificationWatcher.textContent = usbWatcherState === "listening"
    ? (directAlerts ? "Direct phone source listening" : "Listening as fallback")
    : (directAlerts ? "Direct source stopped" : "Stopped · not required");
  elements.worldScanWatcher.textContent = worldWatcherState === "listening"
    ? "Watching decoded spawns"
    : (worldWatcherState === "error" ? "Observer interrupted" : "Not available");
  elements.worldScanLast.textContent = lastWorldSnapshot
    ? `${formatNumber(lastWorldSnapshot.spawnCount || 0)} spawns · ${formatNumber((lastWorldSnapshot.gyms || 0) + (lastWorldSnapshot.stops || 0))} stops/gyms · ${formatAge(lastWorldSnapshot.received_at || lastWorldSnapshot.receivedAt)}`
    : (lastWorldEvent
      ? `${String(lastWorldEvent.kind || "world").replaceAll("-", " ")} · ${formatNumber(lastWorldEvent.count || 0)} · ${formatAge(lastWorldEvent.received_at || lastWorldEvent.receivedAt)}`
      : "None seen");
  elements.macNotificationBridge.textContent = directAlerts ? "Ignored · direct phone mode" : bridgeReady
    ? "Primary detector listening"
    : (bridgeState === "accessibility-required" ? "Accessibility access required" : "Unavailable");
  elements.macNotificationLast.textContent = lastAlert
    ? `${lastAlertLabel} · ${formatAge(lastAlert.received_at || lastAlert.receivedAt)}`
    : "None seen";
  elements.enableNotificationAccess.disabled = directAlerts || bridgeReady;
  elements.enableNotificationAccess.textContent = directAlerts ? "Mirrored alerts not used" : bridgeReady ? "Mac alert access enabled" : "Enable Mac alert access";
  const alertPaused = state.status?.huntPhase === "paused-alerts";
  elements.preparePhoneSettings.disabled = !phoneConnected
    || state.status?.huntState === "running"
    || (state.status?.huntState === "paused" && !alertPaused);
  elements.preparePhoneSettings.textContent = alertPaused ? "Recheck detector" : (prepared ? "Prepare again" : "Prepare iPogo");
  elements.syncInternalFeed.disabled = feed.mode !== "ipogo-internal"
    || !phoneConnected
    || ["waiting", "live"].includes(internalState)
    || ["running", "paused"].includes(state.status?.huntState);
  elements.syncInternalFeed.textContent = internalState === "waiting"
    ? "Connecting to 100-IV feed…"
    : (internalState === "live" ? "Receiving feed…" : "Sync iPogo feed now");
  elements.syncInternalFeed.title = feed.mode === "ipogo-internal" ? "" : "Select iPogo internal as the coordinate source first.";
  elements.syncPokexperience.disabled = feed.mode !== "pokexperience" || pokexperienceSyncing;
  elements.syncPokexperience.textContent = pokexperienceSyncing ? "Syncing PokeXperience…" : "Sync PokeXperience";
  elements.syncPokexperience.title = feed.mode === "pokexperience" ? "" : "Select PokeXperience as the coordinate source first.";

  elements.readinessPhone.textContent = phoneConnected ? "Connected" : "Not connected";
  const readinessSourceLabel = feed.mode === "ipogo-internal"
    ? "iPogo internal"
    : (feed.mode === "pokexperience" ? "PokeXperience" : "Discord relay");
  elements.readinessSource.textContent = `${readinessSourceLabel} · ${formatNumber(feed.fresh)} fresh`;
  elements.readinessLocation.textContent = walkingLoop
    ? `Walking · ${walkRadius.toFixed(0)} m loop`
    : (locationActive ? "Active · 1 Hz" : "Starts with hunt");
  elements.readinessAlerts.textContent = bridgeReady
    ? (directAlerts ? "Direct phone alert verified" : lastAlert ? `${lastAlertLabel} confirmed` : "Mac detector listening")
    : (directAlerts ? "Awaiting real direct Hundo proof" : "Mac detector unavailable");
  const readerReady = state.status?.notificationWatcher?.huntReady ?? bridgeReady;
  const ready = phoneConnected && runtimeVerified && prepared && readerReady && feed.fresh > 0;
  elements.readinessSection.classList.toggle("is-ready", ready);
  elements.readinessIcon.textContent = ready ? "✓" : (phoneConnected ? "2" : "1");
  elements.readinessMessage.textContent = ready
    ? "Ready to start. The first real Hundo verifies alert delivery during the hunt."
    : (!phoneConnected
      ? "Connect the paired iPhone over USB or the same Wi-Fi network to continue."
      : (!runtimeVerified
        ? "Install and verify the supported iPogo spawn runtime."
        : (!readerReady
          ? (directAlerts ? "Prepare iPogo and wait for the phone alert reader to connect. No test notification required." : "Enable Mac alert access so the hunt can stop reliably.")
          : (feed.fresh < 1
            ? (feed.mode === "ipogo-internal"
              ? "Sync the Hunter Lab feed to load fresh coordinates."
              : (feed.mode === "pokexperience"
                ? "Sync the PokeXperience background feed."
                : "Wait for fresh Discord relay coordinates."))
            : "Choose Prepare phone to begin."))));
}

function renderAlertAssurance() {
  const status = state.status || {};
  const prepared = Boolean(status.ipogoPrepared);
  const listening = status.notificationWatcherState === "listening";
  const unattendedReady = Boolean(status.notificationWatcher?.huntReady ?? status.notificationWatcher?.unattendedReady);
  const huntState = status.huntState || "idle";
  const running = huntState === "running";
  const current = status.currentTarget;
  const observedSincePrepare = Boolean(status.notificationObservedSincePrepare);
  const lastObserved = status.notificationWatcher?.lastObservedAlert || status.notificationWatcher?.lastEvent;
  const lastProof = status.huntLastNotificationProof;
  const worldState = status.notificationWatcher?.worldScanTargetState || "idle";
  const worldSkips = Number(status.huntWorldReadySkipsThisRun || 0);
  const confirmed = Number(status.huntNotificationsConfirmedThisRun || 0);
  const timeouts = Number(status.huntTimeoutsThisRun || 0);
  const refreshes = Number(status.ipogoRefreshesThisRun || 0);
  const recoveryPhase = ["restarting-ipogo", "settling-ipogo", "verifying-world", "paused-world", "retrying-world", "clearing-screen"].includes(status.huntPhase);

  elements.alertAssurance.className = "alert-assurance";
  if (recoveryPhase) {
    const recoveryCopy = {
      "clearing-screen": ["Hundo received · clearing the screen", "Checking for blocking notices before moving on. Shundo alerts still take priority."],
      "restarting-ipogo": ["Refreshing iPogo", "The spoofed location remains active while iPogo restarts."],
      "settling-ipogo": ["Waiting for the world to load", "The hunter is holding position before it resumes checks."],
      "verifying-world": ["Verifying the refreshed world", "The current target is preserved until a live Hundo alert proves the map is healthy."],
      "retrying-world": ["Retrying world recovery", "iPogo is being cleanly restarted on the preserved target. Skip remains locked."],
      "paused-world": ["World recovery needs attention", `${status.ipogoLastRefreshError || "The world could not be verified."} Choose Retry recovery. The target is preserved and Skip is locked.`]
    }[status.huntPhase];
    elements.alertAssurance.classList.add(status.huntPhase === "paused-world" ? "is-offline" : "is-armed");
    elements.alertAssuranceTitle.textContent = recoveryCopy[0];
    elements.alertAssuranceDetail.textContent = recoveryCopy[1];
  } else if (!prepared || !listening || !unattendedReady) {
    elements.alertAssurance.classList.add("is-offline");
    const recovering = status.huntPhase === "paused-alerts";
    elements.alertAssuranceTitle.textContent = recovering
      ? "Notification detector interrupted"
      : (prepared ? (status.notificationWatcher?.alertSource === "direct" ? "Phone alert reader disconnected" : "Mac notification access is required") : "Notification detector is off");
    elements.alertAssuranceDetail.textContent = recovering
      ? "The current target is preserved while the detector reconnects. Use Recheck detector if it does not recover automatically."
      : (prepared
        ? (status.notificationWatcher?.alertSource === "direct" ? "Recheck the phone connection. A healthy reader is required; a test Hundo is not." : "Open Settings and enable Mac alert access. The hunt cannot start without it.")
        : "Choose Prepare phone before starting an unattended hunt.");
  } else if (observedSincePrepare) {
    elements.alertAssurance.classList.add("is-verified");
    elements.alertAssuranceTitle.textContent = running
      ? "Live alert verified"
      : "Live iPogo alert verified";
    elements.alertAssuranceDetail.textContent = lastProof?.kind === "hundo"
      ? (lastProof.action === "cooldown"
        ? `${lastProof.species} produced a Hundo alert. The cooldown is active before the next check.`
        : (lastProof.action === "advanced-after-cooldown"
          ? `${lastProof.species} produced a Hundo alert. The cooldown finished and the hunter advanced.`
          : `${lastProof.species} produced a Hundo alert and the hunter advanced immediately.`))
      : (lastProof?.kind === "shundo"
        ? `${lastProof.species} produced a Shundo alert and the hunter stopped.`
        : "The detector captured a real iPogo notification during this prepared session.");
  } else {
    elements.alertAssurance.classList.add("is-armed");
    elements.alertAssuranceTitle.textContent = running
      ? "Detector armed, awaiting first live proof"
      : "Detector armed";
    elements.alertAssuranceDetail.textContent = running
      ? "The first captured Hundo or Shundo will turn this verification green."
      : "Start the hunt to verify the complete notification path on its first live alert.";
  }

  if (current) {
    const phaseLabel = status.huntPhase === "dwelling" ? "Watching" : "Starting";
    const worldLabel = worldState === "grace"
      ? " · world loaded"
      : (worldState === "watching" ? " · waiting for spawns" : "");
    elements.alertCurrentProof.textContent = `${phaseLabel} ${current.species || "target"}${worldLabel}`;
  } else if (huntState === "shundo") {
    elements.alertCurrentProof.textContent = "Stopped on Shundo";
  } else if (status.huntPhase === "cooldown") {
    elements.alertCurrentProof.textContent = `Cooldown after ${lastProof?.species || "Hundo"}`;
  } else {
    elements.alertCurrentProof.textContent = running ? "Selecting next target" : "Not hunting";
  }

  if (lastProof?.kind === "world-loaded-no-hundo") {
    elements.alertLastProof.textContent = `World loaded · no Hundo · ${formatAge(lastProof.receivedAt)}`;
    elements.alertLastProof.title = lastProof.message || "Fresh iPogo spawn data arrived without a Hundo alert.";
  } else if (lastObserved) {
    const isShundo = Boolean(lastObserved.is_shundo || lastObserved.kind === "shundo");
    const isHundo = isShundo || Boolean(lastObserved.is_hundo || lastObserved.kind === "hundo");
    const kind = isShundo ? "Shundo" : (isHundo ? "Hundo" : "Alert");
    const timestamp = lastObserved.received_at || lastObserved.receivedAt;
    elements.alertLastProof.textContent = `${kind} · ${formatAge(timestamp)}`;
    elements.alertLastProof.title = lastObserved.text || lastObserved.message || "";
  } else {
    elements.alertLastProof.textContent = "None yet";
    elements.alertLastProof.removeAttribute("title");
  }
  elements.alertRunProof.textContent = `${confirmed} confirmed · ${worldSkips} world ${plural(worldSkips, "skip")} · ${timeouts} ${plural(timeouts, "timeout")} · ${refreshes} ${plural(refreshes, "refresh", "refreshes")}`;
}

function renderControls() {
  const feed = feedContext();
  const huntState = state.status?.huntState || "idle";
  const current = state.status?.currentTarget || state.sightings.find((item) => item.status === "current");
  const selected = state.sightings.find((item) => item.id === state.selectedId);
  const hasActionable = state.sightings.some((item) => ["queued", "prioritized", "current"].includes(item.status));
  const prepared = Boolean(state.status?.ipogoPrepared);
  const listening = state.status?.notificationWatcherState === "listening";
  const unattendedReady = Boolean(state.status?.notificationWatcher?.huntReady ?? state.status?.notificationWatcher?.unattendedReady);
  const runtimeVerified = Boolean(state.status?.ipogoSpawnRuntimeVerified);
  const alertPaused = state.status?.huntPhase === "paused-alerts";
  const worldRecoveryPaused = state.status?.huntPhase === "paused-world";
  const recoveryLocked = Boolean(state.status?.ipogoRecoveryTargetLocked);
  elements.prepare.disabled = !state.status?.phoneConnected
    || huntState === "running"
    || (huntState === "paused" && !alertPaused);
  elements.prepareLabel.textContent = alertPaused ? "Recheck detector" : (prepared ? "Phone prepared" : "Prepare phone");
  elements.start.disabled = huntState === "paused"
    ? !unattendedReady
    : (!hasActionable || !runtimeVerified || !prepared || !listening || !unattendedReady || huntState === "running");
  elements.start.title = !hasActionable
    ? (feed.mode === "ipogo-internal"
      ? "Sync the iPogo Lab feed to load fresh targets."
      : (feed.mode === "pokexperience"
        ? "Sync the PokeXperience background feed."
        : "Wait for fresh Discord relay targets."))
    : "";
  elements.pause.disabled = huntState !== "running";
  elements.skip.disabled = !current || recoveryLocked;
  elements.skip.title = recoveryLocked ? "Skip is locked until world recovery finishes." : "";
  elements.prioritize.disabled = !selected || !["queued", "prioritized"].includes(selected.status);
  elements.sendPhone.disabled = !selected || !state.status?.phoneConnected;
  elements.startLabel.textContent = worldRecoveryPaused
    ? "Retry recovery"
    : (huntState === "paused" ? "Resume hunt" : "Start hunt");
  elements.huntBadge.className = `state-badge is-${huntState}`;
  elements.huntBadge.textContent = huntState[0].toUpperCase() + huntState.slice(1);
  const seconds = state.status?.huntSecondsRemaining;
  elements.huntMessage.textContent = state.status?.huntMessage || "Connect the phone and prepare iPogo to begin.";
  if (seconds !== null && seconds !== undefined && ["dwelling", "cooldown", "settling-ipogo", "verifying-world"].includes(state.status?.huntPhase)) {
    elements.huntMessage.textContent += ` ${seconds}s remaining.`;
  }
  if (state.status?.huntPhase === "cooldown") {
    elements.huntHeading.textContent = `Cooldown after ${state.status?.huntLastNotificationProof?.species || "Hundo"}`;
  } else if (current) {
    elements.huntHeading.textContent = `Checking ${current.species || "current target"}`;
  } else if (state.sightings.length) {
    elements.huntHeading.textContent = `${state.sightings.filter((item) => ["queued", "prioritized"].includes(item.status)).length} sightings queued`;
  } else {
    elements.huntHeading.textContent = feed.mode === "ipogo-internal"
      ? "Sync fresh iPogo targets"
      : (feed.mode === "pokexperience" ? "Sync fresh PokeXperience targets" : "Waiting for Discord sightings");
  }
}

function renderPreferences() {
  const preferences = state.preferences || { mode: "all", rankedSpecies: [], availableSpecies: [] };
  elements.selectedOnly.checked = preferences.mode === "selected";
  elements.rulesModeBadge.className = `state-badge ${preferences.mode === "selected" ? "is-running" : ""}`;
  elements.rulesModeBadge.textContent = preferences.mode === "selected" ? "Selected only" : "All species";
  hideSpeciesSuggestions();
  elements.priorityEmpty.hidden = preferences.rankedSpecies.length > 0;
  elements.priorityList.innerHTML = preferences.rankedSpecies.map((species, index) => `
    <li>
      <span class="priority-rank">${index + 1}</span>
      <strong>${escapeHtml(species)}</strong>
      <span class="priority-actions">
        <button class="text-button" data-priority-action="up" data-index="${index}" ${index === 0 ? "disabled" : ""} aria-label="Move ${escapeHtml(species)} up">↑</button>
        <button class="text-button" data-priority-action="down" data-index="${index}" ${index === preferences.rankedSpecies.length - 1 ? "disabled" : ""} aria-label="Move ${escapeHtml(species)} down">↓</button>
        <button class="text-button danger-text" data-priority-action="remove" data-index="${index}" aria-label="Remove ${escapeHtml(species)}">Remove</button>
      </span>
    </li>
  `).join("");
  elements.manualSpeciesCatalog.innerHTML = speciesCatalog()
    .map((item) => `<option value="${escapeHtml(item.species)}"></option>`)
    .join("");
}

function speciesCatalog() {
  const catalog = new Map();
  for (const item of state.preferences?.availableSpecies || []) {
    catalog.set(item.species.toLowerCase(), {
      species: item.species,
      actionable: Number(item.actionable || 0)
    });
  }
  for (const species of state.preferences?.rankedSpecies || []) {
    const key = species.toLowerCase();
    if (!catalog.has(key)) catalog.set(key, { species, actionable: 0 });
  }
  return [...catalog.values()].sort((a, b) => a.species.localeCompare(b.species));
}

function hideSpeciesSuggestions() {
  elements.speciesSuggestions.hidden = true;
  elements.prioritySpecies.setAttribute("aria-expanded", "false");
}

function renderSpeciesSuggestions() {
  const query = elements.prioritySpecies.value.trim().replace(/\s+/g, " ");
  const folded = query.toLowerCase();
  const ranked = new Set((state.preferences?.rankedSpecies || []).map((item) => item.toLowerCase()));
  const catalog = speciesCatalog();
  let matches = catalog.filter((item) => !ranked.has(item.species.toLowerCase()));
  if (folded) {
    matches = matches
      .filter((item) => item.species.toLowerCase().includes(folded))
      .sort((a, b) => {
        const aStarts = a.species.toLowerCase().startsWith(folded) ? 0 : 1;
        const bStarts = b.species.toLowerCase().startsWith(folded) ? 0 : 1;
        return aStarts - bStarts || a.species.localeCompare(b.species);
      });
  }
  matches = matches.slice(0, 8);

  const exactCatalogMatch = catalog.some((item) => item.species.toLowerCase() === folded);
  const customRow = query && !exactCatalogMatch && !ranked.has(folded)
    ? `<button type="button" role="option" data-species-suggestion="${escapeHtml(query)}"><strong>Add “${escapeHtml(query)}”</strong><small>Save for future spawns</small></button>`
    : "";
  const matchRows = matches.map((item) => `
    <button type="button" role="option" data-species-suggestion="${escapeHtml(item.species)}">
      <strong>${escapeHtml(item.species)}</strong>
      <small>${item.actionable ? `${formatNumber(item.actionable)} live now` : "No live sightings"}</small>
    </button>`).join("");
  elements.speciesSuggestions.innerHTML = customRow + matchRows;
  elements.speciesSuggestions.hidden = !(customRow || matchRows);
  elements.prioritySpecies.setAttribute("aria-expanded", String(!elements.speciesSuggestions.hidden));
}

let catchLabPreview = null;
let catchLabPoints = [];
let catchLabBusy = false;
let catchLabExpiryTimer = null;
const catchLabImage = document.querySelector("#catch-lab-image");
const catchLabConfirm = document.querySelector("#catch-lab-confirm");
const catchLabDuration = document.querySelector("#catch-lab-duration");
catchLabDuration.addEventListener("input", () => {
  document.querySelector("#catch-lab-duration-label").textContent = `${catchLabDuration.value} ms`;
});

function renderCatchLab() {
  const allowed = state.status?.phoneConnected && state.status?.huntState === "idle" && !state.status?.huntWorkerAlive && !state.status?.ipogoPrepared && !state.status?.overnightActive && !state.status?.encounterProtected;
  document.querySelector("#catch-lab-status").textContent = state.status?.catchLabDetail || "Controller not connected. Automatic catching is off.";
  document.querySelector("#catch-lab-inspect").disabled = !allowed || catchLabBusy;
  document.querySelector("#catch-lab-start").disabled = !allowed || catchLabBusy;
  document.querySelector("#catch-lab-stop").disabled = catchLabBusy;
  const observing = state.status?.catchLabState === "observing";
  document.querySelector("#catch-lab-inspect").disabled = !allowed || catchLabBusy || observing;
  document.querySelector("#catch-lab-throw").disabled = !allowed || catchLabBusy || observing || !catchLabPreview || catchLabPreview.scene?.scene !== "encounter" || catchLabPoints.length !== 2 || !catchLabConfirm.checked || Date.now() >= catchLabPreview.expiresAt;
  const attempt = state.status?.catchLabAttempt;
  document.querySelector("#catch-lab-result").textContent = attempt ? `Last test · CP ${attempt.cp} · ${attempt.durationMs} ms · ${observing ? "Observing…" : attempt.result} · ${attempt.samples} screen samples. ${attempt.captureVerified ? "Catch screen confirmed; shiny/IV identity is NOT verified." : "No catch confirmed."}` : "No calibration attempt yet.";
  document.querySelector("#catch-lab-evidence").textContent = attempt?.evidence?.join("\n") || "No screen evidence yet.";
}

let overnightBusy = false;
let visionSettingsLoaded = false;
let huntModeChoice = null;
let guidedBusy = false;
document.querySelector("#night-settings-content").append(document.querySelector("#overnight-settings"));
function selectedHuntMode() { return state.status?.overnightActive || state.status?.encounterProtected ? "overnight" : (huntModeChoice || "casual"); }
function setupPlan(mode = selectedHuntMode()) {
  return huntSetup(state.status, mode, document.querySelector("#overnight-autolock").checked,
    state.sightings.some(item => ["queued", "prioritized", "current"].includes(item.status)));
}
function showOvernightSection(id) {
  switchView("overnight");
  const section = document.querySelector(id);
  if (section?.tagName === "DETAILS") section.open = true;
  window.requestAnimationFrame(() => section?.scrollIntoView({behavior: "smooth", block: "start"}));
}
function renderGuidedSetup() {
  const s = state.status || {}, mode = selectedHuntMode(), plan = setupPlan(), night = setupPlan("overnight");
  const busy = guidedBusy || overnightBusy || s.visionBusy || s.screenRecoveryBusy;
  document.querySelector("#mode-casual").setAttribute("aria-pressed", String(mode === "casual"));
  document.querySelector("#mode-overnight").setAttribute("aria-pressed", String(mode === "overnight"));
  document.querySelector("#mode-description").textContent = mode === "overnight" ? "Overnight selected · follow the checklist before leaving it." : "Casual selected · no overnight AI or wake protection.";
  document.querySelector("#mode-next-title").textContent = plan.title;
  document.querySelector("#mode-next-detail").textContent = plan.detail;
  document.querySelector("#mode-next-button").textContent = mode === "overnight" ? "Open overnight checklist" : plan.label;
  document.querySelector("#mode-next-button").disabled = busy || !state.status || (mode === "casual" && !plan.action);
  document.querySelector("#night-next-title").textContent = night.title;
  document.querySelector("#night-next-detail").textContent = night.detail;
  document.querySelector("#night-progress").textContent = night.action === "start" ? "Setup complete · no test needed" : night.step ? `Step ${night.step} of 5` : "Session status";
  document.querySelector("#night-next-button").textContent = guidedBusy ? "Working…" : night.label;
  document.querySelector("#night-next-button").disabled = busy || !night.action;
  document.querySelector("#night-device-checklist").hidden = s.overnightActive || s.huntWorkerAlive || s.encounterProtected;
  document.querySelector("#night-action-status").textContent = busy ? "Working on the current step. The hunt will not start automatically." : "";
  document.querySelector("#night-health").textContent = s.overnightActive ? `Health check: ${s.healthDetail || "Waiting for your hunt to begin."}` : "";
  document.querySelector("#guided-ai-badge").textContent = s.visionConfigured ? "· saved and enabled" : "· setup needed";
  const direct = s.notificationWatcher?.alertSource === "direct";
  const steps = [
    ["Devices ready", !!s.phoneConnected && (s.overnightActive || document.querySelector("#overnight-autolock").checked)],
    ["Overnight protection", s.overnightActive && s.overnightMacAwake && s.overnightState === "setup" && s.overnightSecondsRemaining > 0],
    ["AI opening enabled", s.visionConfigured],
    ["Phone & reader connected", s.ipogoPrepared && s.ipogoSpawnRuntimeVerified && direct && (s.notificationWatcher?.huntReady ?? s.notificationWatcher?.unattendedReady)],
    ["Start overnight hunt", s.overnightActive && s.huntState === "running"]
  ];
  document.querySelector("#night-steps").innerHTML = steps.map(([label, done], i) => `<div class="night-step${done ? " is-done" : night.step === i+1 ? " is-current" : ""}"${night.step === i+1 ? ' aria-current="step"' : ""}><span aria-hidden="true">${done ? "✓" : i+1}</span><div>${label}<small>${done ? "Complete" : night.step === i+1 ? "Up next" : "Not yet complete"}</small></div></div>`).join("");
  document.querySelector("#overnight-end-preparation").disabled = busy || s.encounterProtected || (!s.ipogoPrepared && !s.huntWorkerAlive);
  document.querySelector("#overnight-real-location").disabled = busy || s.encounterProtected || !s.phoneConnected;
  document.querySelector("#health-summary").hidden = !s.overnightActive && !s.encounterProtected;
  if (mode === "overnight" && !s.encounterProtected && !["running", "paused", "shundo"].includes(s.huntState)) {
    // The toolbar leads to setup instead of becoming a disabled dead end.
    elements.startLabel.textContent = night.action === "start" ? "Start overnight hunt" : "Set up overnight";
    elements.start.disabled = busy || !state.status;
    elements.start.title = night.detail;
    elements.prepareLabel.textContent = "Overnight setup";
    elements.prepare.disabled = busy || !state.status;
  } else if (mode === "casual" && s.huntState === "idle") {
    elements.startLabel.textContent = "Start casual hunt";
  }
}
async function runGuidedStep(mode) {
  if (guidedBusy || overnightBusy) return;
  const p = setupPlan(mode);
  if (!p.action) return;
  if (p.action === "timeline" || p.action === "feed" || p.action === "proof") {
    switchView("hunt");
    if (p.action === "proof") showToast("Select a fresh target in the queue, then click Test on phone. Wait for Hunter to confirm a real Hundo alert.");
    return;
  }
  if (p.action === "manage" || p.action === "ai") { showOvernightSection(p.action === "ai" ? "#overnight-ai-settings" : "#overnight-management"); return; }
  if (p.action === "setup" || p.action === "source-mac") {
    document.querySelector(p.action === "setup" ? "#overnight-setup" : "#overnight-source-mac").click();
    return;
  }
  guidedBusy = true; renderGuidedSetup();
  try {
    if (p.action === "connection") await performDeviceAction("refresh");
    else await performAction(p.action);
  } finally { guidedBusy = false; render(); }
}
document.querySelector("#mode-casual").addEventListener("click", () => {
  if (state.status?.overnightActive || state.status?.encounterProtected) { showOvernightSection("#overnight-management"); showToast("End overnight setup explicitly before switching to Casual. Nothing has been changed."); return; }
  huntModeChoice = "casual"; render();
});
document.querySelector("#mode-overnight").addEventListener("click", () => { huntModeChoice = "overnight"; switchView("overnight"); render(); });
document.querySelector("#night-back").addEventListener("click", () => switchView("hunt"));
document.querySelector("#night-next-button").addEventListener("click", () => { huntModeChoice = "overnight"; runGuidedStep("overnight"); });
document.querySelector("#mode-next-button").addEventListener("click", () => selectedHuntMode() === "overnight" ? switchView("overnight") : runGuidedStep("casual"));
document.querySelector("#overnight-end-preparation").addEventListener("click", () => performAction("unprepare"));
document.querySelector("#overnight-real-location").addEventListener("click", () => performDeviceAction("clear_location"));
function renderOvernight() {
  const s = state.status || {};
  const healthText = `${s.healthState || "off"} · ${s.healthDetail || "Health checks are inactive."}`;
  document.querySelector("#health-summary").textContent = `Health · ${healthText}`;
  document.querySelector("#health-status").textContent = healthText;
  document.querySelector("#health-checks").textContent = `Last health check: ${s.healthLastCheck ? formatAge(s.healthLastCheck) : "none"} · Last completed coordinate: ${s.healthLastProgress ? formatAge(s.healthLastProgress) : "none"} · Recovery attempts: ${s.healthRecoveryAttempts || 0}/2 · This hour: ${s.healthHourlyAttempts || 0}/6${s.healthRetryAfterSeconds ? ` · Backoff: ${s.healthRetryAfterSeconds}s` : ""}`;
  document.querySelector("#health-history").textContent = (s.healthHistory || []).map(e => `${e.at} · ${e.state}\n${e.detail}`).join("\n\n") || "No health events yet.";
  const detector = s.notificationWatcher || {};
  document.querySelector("#overnight-status").textContent = s.overnightDetail || "Not configured.";
  document.querySelector("#overnight-source").textContent = detector.alertSource === "direct"
    ? (detector.unattendedReady ? "iPhone banner reader · live Hundo verified" : detector.huntReady ? "Reader connected · first Hundo will verify during hunt" : "Phone reader connecting…")
    : "Mac mirrored notifications";
  document.querySelector("#overnight-power").textContent = s.overnightMacAwake ? `Active · display may sleep · ${Math.ceil(s.overnightSecondsRemaining / 3600)}h max remaining` : "Off";
  document.querySelector("#overnight-check").textContent = s.overnightLastScreenCheck ? `${formatAge(s.overnightLastScreenCheck)} · CP ${s.overnightEncounterCP} · ${s.visionShundoEvidenceMatched ? "visual Shundo evidence matched (AI)" : "identity unverified"}` : "No encounter verified";
  document.querySelector("#overnight-setup").disabled = overnightBusy || s.overnightActive || s.encounterProtected || s.ipogoPrepared || s.huntWorkerAlive || s.huntState !== "idle" || !document.querySelector("#overnight-autolock").checked;
  document.querySelector("#overnight-protect").disabled = overnightBusy || s.visionBusy || s.screenRecoveryBusy || !s.overnightActive || s.huntWorkerAlive || !["idle", "shundo"].includes(s.huntState);
  document.querySelector("#overnight-release").disabled = overnightBusy || (!s.overnightActive && !s.encounterProtected) || s.huntWorkerAlive || !document.querySelector("#overnight-release-confirm").checked;
  document.querySelector("#overnight-source-mac").disabled = overnightBusy || s.overnightActive || s.encounterProtected || s.ipogoPrepared || s.huntState !== "idle";
  if (!visionSettingsLoaded && typeof s.visionEnabled === "boolean") {
    document.querySelector("#vision-enabled").checked = s.visionEnabled;
    document.querySelector("#vision-consent").checked = s.visionConsent;
    document.querySelector("#vision-model").value = s.visionModel || "gpt-6-astra";
    visionSettingsLoaded = true;
  }
  document.querySelector("#vision-key-state").textContent = s.visionKeyConfigured ? "· saved in Keychain" : "· not saved";
  document.querySelector("#vision-status").textContent = s.visionBusy ? `Inspecting · ${s.visionStage} · no automatic retries` : s.visionConfigured ? `AI configured · ${s.visionStage || "waiting"}. ${s.overnightActive ? "Applies to new Shundo alerts." : "Start overnight setup to arm it."} Live reliability is not certified.` : "AI disabled or missing consent/API key. No screenshots are sent; open encounters manually.";
  for (const id of ["vision-save", "vision-forget"]) document.querySelector(`#${id}`).disabled = overnightBusy || s.visionBusy || s.screenRecoveryBusy || s.huntWorkerAlive;
  document.querySelector("#vision-analyze").disabled = overnightBusy || s.visionBusy || s.screenRecoveryBusy || !s.visionConfigured || !s.overnightActive || s.huntWorkerAlive || !["idle", "shundo"].includes(s.huntState);
  document.querySelector("#vision-cancel").disabled = overnightBusy || (!s.visionBusy && !s.screenRecoveryBusy);
  document.querySelector("#screen-recovery-status").textContent = `${s.screenRecoveryState || "idle"} · ${s.screenRecoveryDetail || "No recovery needed yet."}`;
  document.querySelector("#screen-recovery-evidence").textContent = (s.screenRecoveryEvidence || []).map(e => `${e.at} · ${e.stage}\n${e.detail}${e.result ? "\n" + JSON.stringify(e.result) : ""}`).join("\n\n");
  document.querySelector("#screen-recover").disabled = overnightBusy || s.screenRecoveryBusy || s.visionBusy || !s.visionConfigured || !s.overnightActive || s.encounterProtected || s.huntWorkerAlive || s.ipogoPrepared || s.huntState !== "idle";
  document.querySelector("#vision-test-open").disabled = overnightBusy || s.visionBusy || s.screenRecoveryBusy || !s.visionConfigured || !s.overnightActive || s.huntWorkerAlive || s.huntState !== "idle" || s.ipogoPrepared || s.encounterProtected || !document.querySelector("#vision-test-confirm").checked;
  document.querySelector("#vision-evidence").textContent = s.visionEvidence?.length ? s.visionEvidence.map(e => `${e.at} · ${e.stage}\n${e.detail}${e.result ? "\n" + JSON.stringify(e.result, null, 2) : ""}`).join("\n\n") : "No AI inspection yet. This feature has not been live-validated on your phone.";
  if (s.screenRecoveryBusy && !s.encounterProtected) elements.huntMessage.textContent = `Clearing blocking screens · ${s.screenRecoveryDetail}`;
  if (s.encounterProtected) {
    for (const button of [elements.prepare, elements.start, elements.skip, elements.sendPhone, elements.clearPhoneLocation, elements.preparePhoneSettings, document.querySelector("#unprepare-phone-settings"), elements.syncInternalFeed]) {
      if (button) button.disabled = true;
    }
    elements.huntMessage.textContent = s.overnightDetail;
  }
  renderGuidedSetup();
}
document.querySelector("#vision-test-confirm").addEventListener("change", renderOvernight);
document.querySelector("#screen-recover").addEventListener("click", async () => {
  overnightBusy = true; renderOvernight();
  try { await api("/api/overnight", {method: "POST", body: JSON.stringify({action: "screen-recover", instanceToken: state.status?.instanceToken})}); }
  catch (error) { showToast(error.message, true); }
  finally { overnightBusy = false; await refresh(); renderOvernight(); }
});
for (const action of ["save", "forget", "analyze", "cancel", "test-open"]) {
  document.querySelector(`#vision-${action}`).addEventListener("click", async () => {
    overnightBusy = true;
    renderOvernight();
    const payload = {action: `vision-${action}`, instanceToken: state.status?.instanceToken};
    if (action === "save") Object.assign(payload, {enabled: document.querySelector("#vision-enabled").checked, consent: document.querySelector("#vision-consent").checked, model: document.querySelector("#vision-model").value, apiKey: document.querySelector("#vision-key").value.trim()});
    if (["analyze", "test-open"].includes(action)) payload.species = document.querySelector("#vision-species").value.trim();
    if (action === "test-open") { payload.confirmed = document.querySelector("#vision-test-confirm").checked; document.querySelector("#vision-test-confirm").checked = false; }
    document.querySelector("#vision-key").value = "";
    try {
      await api("/api/overnight", {method: "POST", body: JSON.stringify(payload)});
      if (["save", "forget"].includes(action)) visionSettingsLoaded = false;
    } catch (error) { showToast(error.message, true); }
    finally { delete payload.apiKey; overnightBusy = false; await refresh(); renderOvernight(); }
  });
}
document.querySelector("#overnight-autolock").addEventListener("change", renderOvernight);
document.querySelector("#overnight-release-confirm").addEventListener("change", renderOvernight);
for (const action of ["setup", "protect", "release", "source-mac"]) {
  document.querySelector(`#overnight-${action}`).addEventListener("click", async () => {
    if (action === "release" && !document.querySelector("#overnight-release-confirm").checked) return;
    overnightBusy = true;
    renderOvernight();
    try {
      await api("/api/overnight", {method: "POST", body: JSON.stringify({action, instanceToken: state.status?.instanceToken, autoLockConfirmed: document.querySelector("#overnight-autolock").checked, confirmed: action === "release"})});
    } catch (error) { showToast(error.message, true); }
    finally { overnightBusy = false; document.querySelector("#overnight-release-confirm").checked = false; await refresh(); renderOvernight(); }
  });
}

for (const action of ["start", "stop"]) {
  document.querySelector(`#catch-lab-${action}`).addEventListener("click", async () => {
    catchLabBusy = true;
    catchLabPreview = null;
    catchLabConfirm.checked = false;
    document.querySelector("#catch-lab-preview").hidden = true;
    renderCatchLab();
    try {
      await api("/api/catch-lab", { method: "POST", body: JSON.stringify({ action, instanceToken: state.status?.instanceToken }) });
    } catch (error) { showToast(error.message, true); }
    finally { catchLabBusy = false; await refresh(); renderCatchLab(); }
  });
}

document.querySelector("#catch-lab-inspect").addEventListener("click", async () => {
  catchLabBusy = true;
  catchLabPreview = null;
  catchLabPoints = [];
  catchLabConfirm.checked = false;
  document.querySelector("#catch-lab-preview").hidden = true;
  clearTimeout(catchLabExpiryTimer);
  renderCatchLab();
  try {
    const { result } = await api("/api/catch-lab", { method: "POST", body: JSON.stringify({ action: "inspect", instanceToken: state.status?.instanceToken }) });
    catchLabPreview = { ...result, expiresAt: Date.now() + result.expiresIn * 1000 };
    catchLabImage.src = result.image;
    document.querySelector("#catch-lab-scene").textContent = `Screen: ${result.scene?.scene || "uncertain"}${result.scene?.cp ? ` · CP ${result.scene.cp}` : ""}${result.scene?.cooldownSeconds ? ` · displayed cooldown ${result.scene.cooldownSeconds}s` : ""}. A fresh recognition check also runs before the throw.`;
    document.querySelector("#catch-lab-points").textContent = "Click the ball, then the throw destination.";
    document.querySelector("#catch-lab-preview").hidden = false;
    catchLabExpiryTimer = setTimeout(() => { catchLabPreview = null; renderCatchLab(); document.querySelector("#catch-lab-points").textContent = "Preview expired. Capture a new preview."; }, result.expiresIn * 1000);
  } catch (error) { showToast(error.message, true); }
  finally { catchLabBusy = false; await refresh(); renderCatchLab(); }
});

catchLabImage.addEventListener("click", (event) => {
  if (!catchLabPreview || catchLabBusy) return;
  if (catchLabPoints.length === 2) catchLabPoints = [];
  const rect = catchLabImage.getBoundingClientRect();
  catchLabPoints.push([(event.clientX - rect.left) / rect.width, (event.clientY - rect.top) / rect.height]);
  document.querySelector("#catch-lab-points").textContent = catchLabPoints.length === 1 ? "Ball selected. Now click the throw destination." : "Both points selected. Confirm the test below, or click to choose again.";
  renderCatchLab();
});
catchLabConfirm.addEventListener("change", renderCatchLab);
document.querySelector("#catch-lab-throw").addEventListener("click", async () => {
  if (!catchLabPreview || catchLabBusy || catchLabPoints.length !== 2 || !catchLabConfirm.checked) return;
  const payload = { action: "throw_once", instanceToken: state.status?.instanceToken, token: catchLabPreview.token,
    start: catchLabPoints[0], end: catchLabPoints[1], durationMs: Number(catchLabDuration.value), confirmedOrdinaryRegularBall: true };
  catchLabBusy = true;
  catchLabPreview = null;
  catchLabConfirm.checked = false;
  clearTimeout(catchLabExpiryTimer);
  renderCatchLab();
  try {
    await api("/api/catch-lab", { method: "POST", body: JSON.stringify(payload) });
    showToast("One throw sent. Watching the result; no automatic retry.");
  } catch (error) { showToast(error.message, true); }
  finally { catchLabBusy = false; await refresh(); renderCatchLab(); }
});

async function savePreferences(rankedSpecies = state.preferences.rankedSpecies, mode = state.preferences.mode) {
  const result = await api("/api/preferences", {
    method: "POST",
    body: JSON.stringify({ mode, rankedSpecies })
  });
  state.preferences = result.preferences;
  renderPreferences();
}

async function performDeviceAction(action, sightingId = null) {
  try {
    const payload = { action };
    if (sightingId !== null) payload.sightingId = sightingId;
    await api("/api/device", { method: "POST", body: JSON.stringify(payload) });
    if (action === "set_location") showToast("Selected target sent to the iPhone.");
    if (action === "clear_location") showToast("The iPhone is using its real location again.");
    if (action === "refresh") showToast("Phone connection checked.");
    if (action === "enable_wifi") showToast("Wi-Fi pairing enabled. Stop before unplugging, check the connection, then prepare again on the same network.");
    await refresh();
  } catch (error) {
    showToast(error.message, true);
  }
}

function renderChannels() {
  elements.channelCount.textContent = state.channels.length;
  if (!state.channels.length) {
    elements.channelList.innerHTML = '<p class="sidebar-empty">No channels observed</p>';
    return;
  }
  elements.channelList.innerHTML = state.channels.map((channel) => `
    <div class="channel-item" title="#${escapeHtml(channel.channel_name)}">
      <span>${escapeHtml(channel.channel_name || channel.channel_id)}</span>
      <small>${formatNumber(channel.sightings)}</small>
    </div>
  `).join("");
}

function isUpcoming(item) {
  return ["queued", "prioritized"].includes(item.status);
}

function queuePosition(item) {
  if (item.queue_position === null || item.queue_position === undefined) return null;
  const position = Number(item.queue_position);
  return Number.isInteger(position) && position >= 0 ? position : null;
}

function compareUpcoming(a, b) {
  const aRank = Number.isInteger(a.queue_rank) ? a.queue_rank : null;
  const bRank = Number.isInteger(b.queue_rank) ? b.queue_rank : null;
  if (aRank !== null || bRank !== null) {
    if (aRank === null) return 1;
    if (bRank === null) return -1;
    if (aRank !== bRank) return aRank - bRank;
  }
  const preferenceRanks = new Map(
    (state.preferences?.rankedSpecies || []).map((species, index) => [species.toLowerCase(), index])
  );
  const aPosition = queuePosition(a);
  const bPosition = queuePosition(b);
  if (aPosition !== null || bPosition !== null) {
    if (aPosition === null) return 1;
    if (bPosition === null) return -1;
    if (aPosition !== bPosition) return aPosition - bPosition;
  }
  if (a.status !== b.status) {
    if (a.status === "prioritized") return -1;
    if (b.status === "prioritized") return 1;
  }
  const aSpeciesRank = preferenceRanks.get((a.species || "").toLowerCase()) ?? Number.MAX_SAFE_INTEGER;
  const bSpeciesRank = preferenceRanks.get((b.species || "").toLowerCase()) ?? Number.MAX_SAFE_INTEGER;
  if (aSpeciesRank !== bSpeciesRank) return aSpeciesRank - bSpeciesRank;
  const pokexperienceFallback = state.status?.feedSourceMode === "pokexperience"
    && aSpeciesRank === Number.MAX_SAFE_INTEGER
    && bSpeciesRank === Number.MAX_SAFE_INTEGER;
  if (state.status?.feedSourceMode === "ipogo-internal" || pokexperienceFallback) {
    const cpDifference = Number(b.cp ?? -1) - Number(a.cp ?? -1);
    if (cpDifference) return cpDifference;
    if (pokexperienceFallback) {
      const levelDifference = Number(b.level ?? -1) - Number(a.level ?? -1);
      if (levelDifference) return levelDifference;
    }
  } else {
    const levelDifference = Number(b.level ?? -1) - Number(a.level ?? -1);
    if (levelDifference) return levelDifference;
    const cpDifference = Number(b.cp ?? -1) - Number(a.cp ?? -1);
    if (cpDifference) return cpDifference;
  }
  return new Date(b.received_at) - new Date(a.received_at);
}

function upcomingSightings() {
  return state.queue.filter(isUpcoming).sort(compareUpcoming);
}

function filteredSightings() {
  const query = state.timelineFilter.trim().toLowerCase();
  return state.sightings.filter((item) => {
    if (state.queuedOnly && !["queued", "prioritized", "current"].includes(item.status)) return false;
    if (!query) return true;
    return `${item.species || ""} ${item.channel_name || ""}`.toLowerCase().includes(query);
  }).sort((a, b) => {
    const rank = { current: 0, prioritized: 1, queued: 1, shundo: 2, checked: 3, skipped: 4, expired: 5, failed: 6 };
    const stateDifference = (rank[a.status] ?? 9) - (rank[b.status] ?? 9);
    if (stateDifference) return stateDifference;
    if (isUpcoming(a) && isUpcoming(b)) return compareUpcoming(a, b);
    return new Date(b.received_at) - new Date(a.received_at);
  });
}

function renderQueueOrderState() {
  const upcoming = upcomingSightings();
  const custom = upcoming.some((item) => queuePosition(item) !== null);
  elements.queueOrderDetail.textContent = custom
    ? `Custom order active for ${formatNumber(upcoming.length)} ${plural(upcoming.length, "target")}. Drag rows or use the arrow controls.`
    : "Automatic: Pokémon priority first; then highest CP for iPogo and PokeXperience, or highest level for Discord.";
  elements.resetQueueOrder.hidden = !custom;
  elements.resetQueueOrder.disabled = state.queueSaving;
}

function renderTimeline() {
  const feed = feedContext();
  const items = filteredSightings();
  const upcoming = upcomingSightings();
  const upcomingIndexes = new Map(upcoming.map((item, index) => [item.id, index]));
  renderQueueOrderState();
  if (!state.sightings.length) {
    const emptyCopy = feed.mode === "ipogo-internal"
      ? "No fresh iPogo targets remain. Sync the Hunter Lab feed, then leave and reopen its 100-IV screen once."
      : (feed.mode === "pokexperience"
        ? "No fresh PokeXperience targets remain. Sync the complete background feed."
        : "No fresh Discord targets remain. Confirm the Chrome relay is connected and keep a supported 100-IV channel open.");
    const actionLabel = feed.mode === "ipogo-internal"
      ? "Open iPogo feed setup"
      : (feed.mode === "pokexperience" ? "Open PokeXperience feed setup" : "Open relay setup");
    elements.timeline.innerHTML = `
      <div class="empty-state">
        <div class="empty-target" aria-hidden="true"><span></span></div>
        <h2>No fresh coordinates</h2>
        <p>${escapeHtml(emptyCopy)}</p>
        <button class="button setup-link" data-view="settings">${escapeHtml(actionLabel)}</button>
      </div>`;
    bindViewButtons();
    return;
  }
  if (!items.length) {
    elements.timeline.innerHTML = '<div class="table-empty">No sightings match these filters.</div>';
    return;
  }
  elements.timeline.innerHTML = items.map((item) => {
    const upcomingIndex = upcomingIndexes.get(item.id);
    const reorderable = upcomingIndex !== undefined;
    const priority = item.status === "prioritized" ? '<span class="priority-mark" aria-label="Prioritized">★</span>' : "";
    const evidence = completionEvidence(item);
    const sourceDetail = item.source === "manual-entry" && !evidence.detail
      ? '<small class="completion-proof is-manual">Manual coordinate · added by you</small>'
      : "";
    const remainingMs = item.expires_at ? new Date(item.expires_at).getTime() - Date.now() : null;
    const expiryClass = remainingMs !== null && remainingMs <= 120000 ? "is-urgent" : "";
    const orderCell = reorderable
      ? `<span class="queue-order-cell">
          <button class="drag-handle" type="button" data-queue-action="drag" aria-label="Drag ${escapeHtml(item.species || "target")} to reorder" title="Drag to reorder">⠿</button>
          <span class="queue-index" aria-label="Upcoming position ${upcomingIndex + 1}">${upcomingIndex + 1}</span>
          <span class="queue-stepper">
            <button type="button" data-queue-action="up" data-queue-id="${item.id}" ${upcomingIndex === 0 ? "disabled" : ""} aria-label="Move ${escapeHtml(item.species || "target")} up">↑</button>
            <button type="button" data-queue-action="down" data-queue-id="${item.id}" ${upcomingIndex === upcoming.length - 1 ? "disabled" : ""} aria-label="Move ${escapeHtml(item.species || "target")} down">↓</button>
          </span>
        </span>`
      : `<span class="queue-order-placeholder">${item.status === "current" ? "Now" : "–"}</span>`;
    return `
      <div class="timeline-row is-${escapeHtml(item.status)} ${item.id === state.selectedId ? "is-selected" : ""}" data-sighting-id="${item.id}" role="button" tabindex="0" aria-pressed="${item.id === state.selectedId}" draggable="${reorderable && !state.queueSaving}">
        ${orderCell}
        <span class="row-state ${escapeHtml(item.status)} ${escapeHtml(evidence.className)}">${escapeHtml(evidence.stateLabel)}${priority}</span>
        <span class="pokemon-cell"><span class="pokemon-name">${escapeHtml(item.species || "Unknown Pokémon")}</span>${evidence.detail ? `<small class="completion-proof ${escapeHtml(evidence.className)}">${escapeHtml(evidence.detail)}</small>` : sourceDetail}</span>
        <span class="numeric">${escapeHtml(item.cp ?? "–")}</span>
        <span class="numeric">${escapeHtml(item.level ?? "–")}</span>
        <span class="coordinates">${item.latitude === null || item.longitude === null
          ? (item.coordinate_state === "resolving" ? "Resolving…" : (item.coordinate_state === "failed" ? "Needs resync" : "Queued · on demand"))
          : `${Number(item.latitude).toFixed(5)}, ${Number(item.longitude).toFixed(5)}`}</span>
        <span class="expires-time ${expiryClass}" title="${item.expires_at ? `Disappears at ${escapeHtml(clockTime(item.expires_at))}` : "No disappearance time supplied"}">${formatTimeRemaining(item.expires_at)}</span>
      </div>`;
  }).join("");
  document.querySelectorAll(".timeline-row[data-sighting-id]").forEach((row) => {
    const selectRow = () => {
      const id = Number(row.dataset.sightingId);
      state.selectedId = state.selectedId === id ? null : id;
      renderControls();
      renderTimeline();
    };
    row.addEventListener("click", (event) => {
      if (event.target.closest("[data-queue-action]")) return;
      selectRow();
    });
    row.addEventListener("keydown", (event) => {
      if (event.target !== row || !["Enter", " "].includes(event.key)) return;
      event.preventDefault();
      selectRow();
    });
    row.addEventListener("dragstart", (event) => {
      if (!isUpcoming(state.sightings.find((item) => item.id === Number(row.dataset.sightingId)) || {})) {
        event.preventDefault();
        return;
      }
      state.draggedSightingId = Number(row.dataset.sightingId);
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", String(state.draggedSightingId));
      row.classList.add("is-dragging");
    });
    row.addEventListener("dragover", (event) => {
      const targetId = Number(row.dataset.sightingId);
      if (!state.draggedSightingId || targetId === state.draggedSightingId || !upcomingIndexes.has(targetId)) return;
      event.preventDefault();
      const after = event.clientY > row.getBoundingClientRect().top + row.offsetHeight / 2;
      document.querySelectorAll(".timeline-row").forEach((candidate) => candidate.classList.remove("drop-before", "drop-after"));
      row.classList.add(after ? "drop-after" : "drop-before");
    });
    row.addEventListener("drop", (event) => {
      event.preventDefault();
      const targetId = Number(row.dataset.sightingId);
      const after = event.clientY > row.getBoundingClientRect().top + row.offsetHeight / 2;
      reorderByDrop(state.draggedSightingId, targetId, after);
    });
    row.addEventListener("dragend", clearDragState);
  });
  document.querySelectorAll("[data-queue-action='up'], [data-queue-action='down']").forEach((button) => {
    button.addEventListener("click", () => {
      moveQueueItem(Number(button.dataset.queueId), button.dataset.queueAction === "up" ? -1 : 1);
    });
  });
}

function clearDragState() {
  state.draggedSightingId = null;
  document.querySelectorAll(".timeline-row").forEach((row) => {
    row.classList.remove("is-dragging", "drop-before", "drop-after");
  });
}

async function saveQueueOrder(orderedIds, successMessage) {
  if (state.queueSaving) return;
  state.queueSaving = true;
  const positions = new Map(orderedIds.map((id, index) => [id, index]));
  state.queue.forEach((item) => {
    if (isUpcoming(item)) {
      item.queue_position = positions.has(item.id) ? positions.get(item.id) : null;
      item.queue_rank = positions.has(item.id) ? positions.get(item.id) : null;
    }
  });
  clearDragState();
  renderTimeline();
  try {
    await api("/api/queue-order", {
      method: "POST",
      body: JSON.stringify({ orderedIds })
    });
    showToast(successMessage);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    state.queueSaving = false;
    await refresh();
  }
}

function moveQueueItem(sightingId, offset) {
  const orderedIds = upcomingSightings().map((item) => item.id);
  const index = orderedIds.indexOf(sightingId);
  const destination = index + offset;
  if (index < 0 || destination < 0 || destination >= orderedIds.length) return;
  [orderedIds[index], orderedIds[destination]] = [orderedIds[destination], orderedIds[index]];
  saveQueueOrder(orderedIds, "Upcoming order updated.");
}

function reorderByDrop(draggedId, targetId, after) {
  if (!draggedId || !targetId || draggedId === targetId) {
    clearDragState();
    return;
  }
  const orderedIds = upcomingSightings().map((item) => item.id);
  const sourceIndex = orderedIds.indexOf(draggedId);
  if (sourceIndex < 0 || !orderedIds.includes(targetId)) {
    clearDragState();
    return;
  }
  orderedIds.splice(sourceIndex, 1);
  const targetIndex = orderedIds.indexOf(targetId);
  orderedIds.splice(targetIndex + (after ? 1 : 0), 0, draggedId);
  saveQueueOrder(orderedIds, "Upcoming order updated.");
}

function completionEvidence(item) {
  const reason = item.completion_reason || "";
  if (reason === "hundo-notification") {
    const when = item.notification_received_at ? ` · ${clockTime(item.notification_received_at)}` : "";
    return { stateLabel: "Hundo seen", detail: `Alert captured${when} · advanced immediately`, className: "is-confirmed" };
  }
  if (reason === "shundo-notification" || item.status === "shundo") {
    const when = item.notification_received_at ? ` · ${clockTime(item.notification_received_at)}` : "";
    return { stateLabel: "Shundo", detail: `Shundo alert captured${when} · hunt stopped`, className: "is-shundo-proof" };
  }
  if (reason === "timeout-no-alert") {
    return { stateLabel: "No alert", detail: "Configured loading limit reached · advanced without world or notification proof", className: "is-timeout" };
  }
  if (reason === "world-loaded-no-hundo") {
    return { stateLabel: "World checked", detail: "Spawns loaded · no Hundo alert · advanced immediately", className: "is-confirmed" };
  }
  return { stateLabel: item.status, detail: "", className: "" };
}

function renderEvents() {
  const events = state.events.filter((event) => state.eventSource === "all" || event.source === state.eventSource);
  if (!events.length) {
    elements.eventLog.innerHTML = '<p class="event-empty">Events will appear when the relay begins receiving sightings.</p>';
    return;
  }
  elements.eventLog.innerHTML = events.map((event) => `
    <div class="event-row">
      <time datetime="${escapeHtml(event.created_at)}">${clockTime(event.created_at)}</time>
      <span class="event-source ${escapeHtml(event.source.toLowerCase())}">${escapeHtml(event.source)}</span>
      <span class="event-message">${escapeHtml(event.message)}</span>
    </div>
  `).join("");
}

function renderStats() {
  const stats = state.stats;
  document.querySelector("#checked-total").innerHTML = `${formatNumber(stats.checked)} <span>Pokémon checked</span>`;
  document.querySelector("#shundo-total").textContent = `${formatNumber(stats.shundos)} ${plural(stats.shundos, "Shundo")}`;
  document.querySelector("#received-total").textContent = formatNumber(stats.received);
  document.querySelector("#skipped-total").textContent = formatNumber(stats.skipped);
  document.querySelector("#stats-checked").textContent = formatNumber(stats.checked);
  document.querySelector("#stats-shundos").textContent = formatNumber(stats.shundos);
  document.querySelector("#stats-received").textContent = formatNumber(stats.received);

  const checkedSpecies = stats.species.filter((item) => item.checked > 0).slice(0, 5);
  document.querySelector("#species-mini-list").innerHTML = checkedSpecies.length
    ? checkedSpecies.map((item) => `<div class="species-mini-row"><span>${escapeHtml(item.species)}</span><small>${formatNumber(item.checked)} checked${item.shundos ? ` · ${formatNumber(item.shundos)} Shundo` : ""}</small></div>`).join("")
    : '<p class="rail-empty">Individual totals appear after Pokémon are checked.</p>';

  const search = state.statsSearch.trim().toLowerCase();
  const speciesRows = stats.species.filter((item) => !search || item.species.toLowerCase().includes(search));
  document.querySelector("#species-table").innerHTML = speciesRows.length
    ? speciesRows.map((item) => `
      <div class="species-table-row">
        <strong>${escapeHtml(item.species)}</strong>
        <span>${formatNumber(item.checked)} checked</span>
        <span>${formatNumber(item.shundos)}</span>
        <span>${formatNumber(item.received)}</span>
        <span>${formatAge(item.last_seen_at)}</span>
      </div>`).join("")
    : '<div class="table-empty">No Pokémon match this search.</div>';
}

async function performAction(action) {
  if (action === "start" && selectedHuntMode() === "overnight" && state.status?.huntState !== "paused" && setupPlan("overnight").action !== "start") {
    switchView("overnight"); render(); return;
  }
  try {
    await api("/api/action", {
      method: "POST",
      body: JSON.stringify({ action, sightingId: state.selectedId })
    });
    if (action === "prioritize") showToast("Selected sighting moved to the front of the queue.");
    if (action === "prepare") showToast("iPogo is prepared. Check the alert status; a fresh real Hundo verifies the notification path.");
    if (action === "start") showToast("Hunt started. The phone will move through fresh sightings automatically.");
    if (action === "sync_internal_feed") showToast("Hunter Lab opened. The 100-IV feed will sync automatically and return to iPogo.");
    await refresh();
  } catch (error) {
    showToast(error.message, true);
  }
}

function setManualSpawnFormOpen(open) {
  elements.manualSpawnForm.hidden = !open;
  elements.manualSpawnToggle.setAttribute("aria-expanded", String(open));
  elements.manualSpawnToggle.classList.toggle("is-active", open);
  if (open) window.requestAnimationFrame(() => elements.manualSpecies.focus());
}

async function addManualSpawn(event) {
  event.preventDefault();
  if (!elements.manualSpawnForm.reportValidity()) return;
  elements.addManualSpawn.disabled = true;
  try {
    const result = await api("/api/manual-sighting", {
      method: "POST",
      body: JSON.stringify({
        species: elements.manualSpecies.value,
        coordinates: elements.manualCoordinates.value
      })
    });
    const label = result.sighting.species || "Manual target";
    state.selectedId = result.sighting.id;
    elements.manualSpawnForm.reset();
    setManualSpawnFormOpen(false);
    showToast(`${label} added as the next upcoming check.`);
    await refresh();
  } catch (error) {
    showToast(error.message, true);
    elements.manualCoordinates.focus();
  } finally {
    elements.addManualSpawn.disabled = false;
  }
}

async function setFeedSource(source) {
  try {
    const result = await api("/api/action", {
      method: "POST",
      body: JSON.stringify({ action: "set_feed_source", source })
    });
    state.status = { ...(state.status || {}), ...(result.status || {}) };
    showToast(source === "ipogo-internal"
      ? "iPogo internal feed selected. Start the live feed before hunting."
      : (source === "pokexperience"
        ? "PokeXperience selected. Open the Mac app, then sync fresh targets."
        : "Discord relay selected. Only fresh relay coordinates can be hunted."));
    if (source === "pokexperience") requestPokexperienceSync();
    await refresh();
  } catch (error) {
    showToast(error.message, true);
    await refresh();
  }
}

function requestPokexperienceSync() {
  const nativeBridge = window.webkit?.messageHandlers?.nativeBridge;
  if (!nativeBridge) {
    showToast("Open this control from the Shundo Hunter Mac app.", true);
    return;
  }
  nativeBridge.postMessage("syncPokeXperience");
  showToast("PokeXperience sync started.");
}

function openSourceSetup() {
  const feed = feedContext();
  switchView("settings");
  window.requestAnimationFrame(() => {
    const setupHeading = feed.mode === "ipogo-internal"
      ? "#internal-feed-heading"
      : (feed.mode === "pokexperience" ? "#pokexperience-feed-heading" : "#relay-setup-heading");
    const heading = document.querySelector(setupHeading);
    heading?.scrollIntoView({ behavior: "smooth", block: "start" });
  });
}

function switchView(view) {
  if (view === "overnight") { huntModeChoice = "overnight"; renderGuidedSetup(); }
  document.body.classList.toggle("is-overnight-view", view === "overnight");
  state.activeView = view;
  document.querySelectorAll(".view").forEach((section) => {
    const active = section.id === `${view}-view`;
    section.hidden = !active;
    section.classList.toggle("is-active", active);
  });
  document.querySelectorAll(".nav-item").forEach((button) => {
    const active = button.dataset.view === view;
    button.classList.toggle("is-active", active);
    if (active) button.setAttribute("aria-current", "page"); else button.removeAttribute("aria-current");
  });
  if (view !== "hunt") {
    elements.filterPanel.hidden = true;
    elements.filterToggle.setAttribute("aria-expanded", "false");
  }
  document.querySelector(`#${view}-view h1`)?.focus?.({ preventScroll: true });
}

function bindViewButtons() {
  document.querySelectorAll("[data-view]").forEach((button) => {
    if (button.dataset.bound === "true") return;
    button.dataset.bound = "true";
    button.addEventListener("click", () => switchView(button.dataset.view));
  });
}

elements.prepare.addEventListener("click", () => selectedHuntMode() === "overnight" ? switchView("overnight") : performAction("prepare"));
elements.manualSpawnToggle.addEventListener("click", () => {
  setManualSpawnFormOpen(elements.manualSpawnForm.hidden);
});
elements.cancelManualSpawn.addEventListener("click", () => setManualSpawnFormOpen(false));
elements.manualSpawnForm.addEventListener("submit", addManualSpawn);
elements.resetQueueOrder.addEventListener("click", () => {
  saveQueueOrder([], "Automatic queue order restored.");
});
elements.syncInternalFeed.addEventListener("click", () => performAction("sync_internal_feed"));
elements.syncPokexperience.addEventListener("click", requestPokexperienceSync);
elements.huntFeedSource.addEventListener("change", (event) => setFeedSource(event.target.value));
elements.settingsFeedSource.addEventListener("change", (event) => setFeedSource(event.target.value));
elements.huntFeedAction.addEventListener("click", () => {
  if (feedContext().mode === "ipogo-internal") performAction("sync_internal_feed");
  else if (feedContext().mode === "pokexperience") requestPokexperienceSync();
  else openSourceSetup();
});
elements.start.addEventListener("click", () => performAction("start"));
elements.pause.addEventListener("click", () => performAction("pause"));
elements.skip.addEventListener("click", () => performAction("skip"));
elements.prioritize.addEventListener("click", () => performAction("prioritize"));
elements.sendPhone.addEventListener("click", () => performDeviceAction("set_location", state.selectedId));
elements.filterToggle.addEventListener("click", () => {
  const expanded = elements.filterToggle.getAttribute("aria-expanded") === "true";
  elements.filterToggle.setAttribute("aria-expanded", String(!expanded));
  elements.filterPanel.hidden = expanded;
  if (!expanded) elements.speciesFilter.focus();
});
elements.speciesFilter.addEventListener("input", (event) => { state.timelineFilter = event.target.value; renderTimeline(); });
elements.queuedOnly.addEventListener("change", (event) => { state.queuedOnly = event.target.checked; renderTimeline(); });
document.querySelector("#clear-filters").addEventListener("click", () => {
  state.timelineFilter = "";
  state.queuedOnly = false;
  elements.speciesFilter.value = "";
  elements.queuedOnly.checked = false;
  renderTimeline();
});
document.querySelector("#stats-search").addEventListener("input", (event) => { state.statsSearch = event.target.value; renderStats(); });
async function addPrioritySpecies(value) {
  const typed = String(value || "").trim().split(/\s+/).join(" ");
  if (!typed) return;
  const catalogMatch = speciesCatalog().find((item) => item.species.toLowerCase() === typed.toLowerCase());
  const species = catalogMatch?.species || typed;
  if (!species) return;
  const ranked = state.preferences.rankedSpecies.filter((item) => item.toLowerCase() !== species.toLowerCase());
  ranked.push(species);
  try {
    await savePreferences(ranked);
    elements.prioritySpecies.value = "";
    hideSpeciesSuggestions();
    showToast(`${species} added to the hunt ranking.`);
  } catch (error) {
    showToast(error.message, true);
  }
}

document.querySelector("#add-priority-species").addEventListener("click", () => {
  addPrioritySpecies(elements.prioritySpecies.value);
});
elements.prioritySpecies.addEventListener("input", renderSpeciesSuggestions);
elements.prioritySpecies.addEventListener("focus", renderSpeciesSuggestions);
elements.prioritySpecies.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    addPrioritySpecies(elements.prioritySpecies.value);
  }
  if (event.key === "Escape") {
    hideSpeciesSuggestions();
  }
});
elements.speciesSuggestions.addEventListener("mousedown", (event) => {
  event.preventDefault();
  const button = event.target.closest("[data-species-suggestion]");
  if (!button) return;
  addPrioritySpecies(button.dataset.speciesSuggestion);
});
document.addEventListener("click", (event) => {
  if (!event.target.closest(".priority-add-row")) hideSpeciesSuggestions();
});
elements.selectedOnly.addEventListener("change", async (event) => {
  try {
    await savePreferences(state.preferences.rankedSpecies, event.target.checked ? "selected" : "all");
    showToast(event.target.checked ? "Only ranked Pokémon will be hunted." : "Unranked Pokémon will follow the ranked list.");
  } catch (error) {
    event.target.checked = !event.target.checked;
    showToast(error.message, true);
  }
});
elements.priorityList.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-priority-action]");
  if (!button) return;
  const index = Number(button.dataset.index);
  const ranked = [...state.preferences.rankedSpecies];
  if (!Number.isInteger(index) || !ranked[index]) return;
  const action = button.dataset.priorityAction;
  if (action === "remove") ranked.splice(index, 1);
  if (action === "up" && index > 0) [ranked[index - 1], ranked[index]] = [ranked[index], ranked[index - 1]];
  if (action === "down" && index < ranked.length - 1) [ranked[index + 1], ranked[index]] = [ranked[index], ranked[index + 1]];
  try {
    const mode = state.preferences.mode === "selected" && ranked.length === 0 ? "all" : state.preferences.mode;
    await savePreferences(ranked, mode);
  } catch (error) {
    showToast(error.message, true);
  }
});
elements.refreshPhone.addEventListener("click", () => performDeviceAction("refresh"));
elements.enableWifi.addEventListener("click", () => performDeviceAction("enable_wifi"));
elements.preparePhoneSettings.addEventListener("click", () => performAction("prepare"));
document.querySelector("#unprepare-phone-settings").addEventListener("click", () => performAction("unprepare"));
elements.enableNotificationAccess.addEventListener("click", () => {
  const bridge = window.webkit?.messageHandlers?.nativeBridge;
  if (!bridge) {
    showToast("Open this control from the Shundo Hunter Mac app.", true);
    return;
  }
  bridge.postMessage("requestAccessibility");
  showToast("Follow the macOS prompt to allow Shundo Hunter in Accessibility.");
});
elements.clearPhoneLocation.addEventListener("click", () => performDeviceAction("clear_location"));
elements.huntTimingForm.addEventListener("input", () => {
  state.huntSettingsDirty = true;
  renderHuntSettings();
});
elements.huntTimingForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!elements.huntTimingForm.reportValidity()) return;
  try {
    const result = await api("/api/hunt-settings", {
      method: "POST",
      body: JSON.stringify({
        dwellSeconds: Number(elements.huntDwellSeconds.value),
        hundoCooldownSeconds: Number(elements.hundoCooldownSeconds.value),
        recoveryFailureThreshold: Number(elements.recoveryFailureThreshold.value)
      })
    });
    state.status = { ...(state.status || {}), ...(result.status || {}) };
    state.huntSettingsDirty = false;
    renderHuntSettings();
    showToast(`Hunt timing saved: ${result.settings.dwellSeconds}s map wait, ${result.settings.hundoCooldownSeconds}s after each Hundo, refresh after ${result.settings.recoveryFailureThreshold} ${plural(result.settings.recoveryFailureThreshold, "failure")}.`);
  } catch (error) {
    showToast(error.message, true);
  }
});
document.querySelectorAll(".event-filter").forEach((button) => button.addEventListener("click", () => {
  state.eventSource = button.dataset.source;
  document.querySelectorAll(".event-filter").forEach((candidate) => candidate.classList.toggle("is-active", candidate === button));
  renderEvents();
}));
document.querySelector("#copy-relay-path").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(state.relayPath);
    showToast("Relay folder path copied.");
  } catch {
    showToast("Chrome could not copy the path. Select it manually from Settings.", true);
  }
});

document.addEventListener("keydown", (event) => {
  if (event.target.matches("input, textarea, select, button")) return;
  if (event.code === "Space") {
    event.preventDefault();
    if (state.status?.huntState === "running" && !elements.pause.disabled) performAction("pause");
    else if (!elements.start.disabled) performAction("start");
  }
  if (event.key.toLowerCase() === "p" && !elements.pause.disabled) performAction("pause");
  if (event.key.toLowerCase() === "k" && !elements.skip.disabled) performAction("skip");
  if (event.key.toLowerCase() === "r" && !elements.prioritize.disabled) performAction("prioritize");
});

elements.relayPath.textContent = state.relayPath;
bindViewButtons();
refresh();
window.setInterval(refresh, 2500);
