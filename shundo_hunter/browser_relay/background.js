const LOCAL_INGEST_URL = "http://127.0.0.1:8765/api/ingest";
const LOCAL_HEARTBEAT_URL = "http://127.0.0.1:8765/api/heartbeat";
// Pokedex100 is the primary feed. Its Discord embeds contain authenticated
// coord.pokedex100.com links, matching the reference hunter's data path.
// PokeX's Copy-button interaction remains available as a deliberately disabled
// fallback because it is not needed for the selected server.
const ENABLE_POKEX_INTERACTION_FALLBACK = false;
// Discord messages contain many adjacent integers (level, CP, timers). Real feed
// coordinates are decimal pairs, so requiring decimals prevents those fields from
// being mistaken for latitude and longitude.
const COORDINATE_RE = /(-?(?:[0-8]?\d\.\d{4,}|90\.0{4,}))\s*[, ]\s*(-?(?:1[0-7]\d\.\d{4,}|\d?\d\.\d{4,}|180\.0{4,}))/;
let discordAuthorization = null;
let interactionTemplate = null;
let interactionURL = "https://discord.com/api/v9/interactions";
let interactionHeaders = {};
const apiMessagesSeen = new Set();
const copyMessagesSeen = new Set();
const channelPollTimes = new Map();
const apiRetryTimes = new Map();
const interactionQueue = [];
let interactionBusy = false;
const apiDiagnostics = {
  lastPollAt: null,
  messageCount: 0,
  coordinateLinkCount: 0,
  linkHosts: [],
  acceptedCount: 0,
  interactionSentCount: 0,
  interactionLastError: null,
  lastError: null
};

chrome.storage.session.get([
  "discordAuthorization", "interactionTemplate", "interactionURL",
  "interactionHeaders", "copyMessagesSeen"
]).then((stored) => {
  if (typeof stored.discordAuthorization === "string") {
    discordAuthorization = stored.discordAuthorization;
  }
  if (stored.interactionTemplate && typeof stored.interactionTemplate === "object") {
    interactionTemplate = stored.interactionTemplate;
  }
  if (typeof stored.interactionURL === "string") interactionURL = stored.interactionURL;
  if (stored.interactionHeaders && typeof stored.interactionHeaders === "object") {
    interactionHeaders = stored.interactionHeaders;
  }
  if (Array.isArray(stored.copyMessagesSeen)) {
    for (const key of stored.copyMessagesSeen) copyMessagesSeen.add(String(key));
  }
});

// The reference hunter reads Discord's channel-messages endpoint with the
// signed-in web client's Authorization header. Observe that existing request,
// keep the value in Chrome's session-only storage, and never send it to the Mac.
chrome.webRequest.onBeforeSendHeaders.addListener(
  (details) => {
    const requestHeaders = details.requestHeaders || [];
    const header = requestHeaders.find(
      (item) => item.name.toLowerCase() === "authorization"
    );
    if (header?.value && header.value !== discordAuthorization) {
      discordAuthorization = header.value;
      chrome.storage.session.set({ discordAuthorization });
    }
    if (details.url.includes("/interactions")) {
      const allowed = new Set([
        "authorization", "content-type", "x-super-properties", "x-discord-locale",
        "x-discord-timezone", "x-debug-options"
      ]);
      interactionHeaders = Object.fromEntries(requestHeaders
        .filter((item) => allowed.has(item.name.toLowerCase()) && item.value)
        .map((item) => [item.name, item.value]));
      chrome.storage.session.set({ interactionHeaders });
    }
  },
  { urls: [
    "https://discord.com/api/*/channels/*/messages*",
    "https://discord.com/api/*/interactions"
  ], types: ["xmlhttprequest"] },
  ["requestHeaders", "extraHeaders"]
);

chrome.webRequest.onBeforeRequest.addListener(
  (details) => {
    try {
      const bytes = details.requestBody?.raw?.[0]?.bytes;
      if (!bytes) return;
      const parsed = JSON.parse(new TextDecoder().decode(bytes));
      if (parsed?.type !== 3 || !parsed?.data?.custom_id) return;
      interactionTemplate = parsed;
      interactionURL = details.url;
      apiDiagnostics.interactionLastError = null;
      chrome.storage.session.set({ interactionTemplate, interactionURL });
    } catch (error) {
      apiDiagnostics.interactionLastError = error instanceof Error ? error.message : String(error);
    }
  },
  { urls: ["https://discord.com/api/*/interactions"], types: ["xmlhttprequest"] },
  ["requestBody"]
);

function coordinateFromText(text) {
  const match = String(text || "").match(COORDINATE_RE);
  if (!match) return null;
  const latitude = Number(match[1]);
  const longitude = Number(match[2]);
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return null;
  if (Math.abs(latitude) > 90 || Math.abs(longitude) > 180) return null;
  return { latitude, longitude };
}

function coordinateLinkSource(url, label = "") {
  try {
    const parsed = new URL(url);
    if (parsed.hostname === "pokedex100.com" || parsed.hostname.endsWith(".pokedex100.com")) {
      return "pokedex100";
    }
    if (/(?:^|\.)pokexperience\.com$|(?:^|\.)pokex\.co$/i.test(parsed.hostname)
        || /pokex/i.test(label)) {
      return "pokex";
    }
    return null;
  } catch {
    return null;
  }
}

function isCoordinateLink(url, label = "") {
  return coordinateLinkSource(url, label) !== null;
}

async function resolvePokedex100InAuthenticatedTab(url) {
  // Extension service-worker fetches are cross-site and can omit Pokedex100's
  // SameSite session cookie. Execute the GET in an already signed-in
  // coord.pokedex100.com tab instead. Only the coordinate comes back; cookies
  // and page HTML never leave Chrome.
  const tabs = await chrome.tabs.query({ url: ["https://coord.pokedex100.com/*"] });
  const tab = tabs.find((candidate) => Number.isInteger(candidate.id));
  if (!tab?.id) throw new Error("Keep one signed-in Pokedex100 coordinate tab open");
  const request = { type: "SHUNDO_RESOLVE_POKEDEX100", url };
  let result;
  try {
    result = await chrome.tabs.sendMessage(tab.id, request);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (!/receiving end does not exist/i.test(message)) throw error;
    await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      files: ["coordinate.js"]
    });
    result = await chrome.tabs.sendMessage(tab.id, request);
  }
  if (result?.error) throw new Error(String(result.error));
  return result?.coordinate || null;
}

async function resolveCoordinate(links) {
  for (const link of links || []) {
    const direct = coordinateFromText(decodeURIComponent(link.href || ""));
    if (direct) return { ...direct, url: link.href };
    const source = coordinateLinkSource(link.href, link.label);
    if (!source) continue;

    if (source === "pokedex100") {
      try {
        const coordinate = await resolvePokedex100InAuthenticatedTab(link.href);
        if (coordinate) return coordinate;
      } catch (error) {
        apiDiagnostics.lastError = `Pokedex100 resolver: ${
          error instanceof Error ? error.message : String(error)
        }`;
      }
      continue;
    }

    try {
      const response = await fetch(link.href, { credentials: "include", redirect: "follow" });
      if (!response.ok) continue;
      const html = await response.text();
      // Coordinate services expose the value in a form input. Never scan the
      // whole page: CSS/SVG markup contains harmless decimal pairs such as
      // `2.5,4.5` that are not geographic coordinates.
      for (const inputMatch of html.matchAll(/<input\b[^>]*\bvalue=["']([^"']+)["'][^>]*>/gi)) {
        const coordinate = coordinateFromText(inputMatch[1]);
        if (coordinate) return { ...coordinate, url: response.url || link.href };
      }
    } catch {
      // The local service records candidates only after a coordinate is resolved.
    }
  }
  return null;
}

async function relay(payload) {
  const resolvedCoordinate = await resolveCoordinate(payload.links);
  const body = { ...payload, resolvedCoordinate };
  const response = await fetch(LOCAL_INGEST_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  if (!response.ok) throw new Error(`Local feed returned ${response.status}`);
  const result = await response.json();
  await chrome.action.setBadgeBackgroundColor({ color: result.accepted ? "#278A5B" : "#656B73" });
  await chrome.action.setBadgeText({ text: result.accepted ? "ON" : "" });
  return { ...result, resolvedCoordinate };
}

async function postHeartbeat(payload) {
  const response = await fetch(LOCAL_HEARTBEAT_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ...payload,
      apiAuthorized: Boolean(discordAuthorization),
      apiLastPollAt: apiDiagnostics.lastPollAt,
      apiMessageCount: apiDiagnostics.messageCount,
      apiCoordinateLinkCount: apiDiagnostics.coordinateLinkCount,
      apiLinkHosts: apiDiagnostics.linkHosts,
      apiAcceptedCount: apiDiagnostics.acceptedCount,
      interactionReady: Boolean(interactionTemplate && discordAuthorization),
      interactionSentCount: apiDiagnostics.interactionSentCount,
      interactionLastError: apiDiagnostics.interactionLastError,
      apiLastError: apiDiagnostics.lastError
    })
  });
  if (!response.ok) throw new Error("Heartbeat failed");
}

function urlsFromDiscordMessage(message) {
  const found = new Map();
  const visit = (value, inheritedLabel = "Discord API") => {
    if (typeof value === "string") {
      for (const match of value.matchAll(/https?:\/\/[^\s<>)\]"']+/g)) {
        if (!found.has(match[0])) found.set(match[0], inheritedLabel);
      }
      return;
    }
    if (Array.isArray(value)) {
      for (const item of value) visit(item, inheritedLabel);
      return;
    }
    if (!value || typeof value !== "object") return;
    const label = typeof value.label === "string" ? value.label : inheritedLabel;
    for (const [key, item] of Object.entries(value)) {
      if (["embeds", "components", "description", "url"].includes(key)) visit(item, label);
    }
  };
  visit(message);
  return Array.from(found, ([href, label]) => ({ href, label }));
}

function findCopyComponent(components) {
  for (const component of components || []) {
    if (/copy/i.test(String(component.label || "")) && component.custom_id) return component;
    const nested = findCopyComponent(component.components);
    if (nested) return nested;
  }
  return null;
}

function discordNonce() {
  return String((BigInt(Date.now() - 1420070400000) << 22n) + BigInt(Math.floor(Math.random() * 4194304)));
}

async function sendCopyInteraction(message, payload) {
  const component = findCopyComponent(message.components);
  if (!component || !interactionTemplate || !discordAuthorization) return false;
  const body = JSON.parse(JSON.stringify(interactionTemplate));
  body.type = 3;
  body.nonce = discordNonce();
  body.guild_id = String(message.guild_id || payload.guildId || body.guild_id || "");
  body.channel_id = String(message.channel_id || payload.channelId || body.channel_id || "");
  body.message_id = String(message.id || "");
  body.application_id = String(message.application_id || message.author?.id || body.application_id || "");
  body.message_flags = Number(message.flags || 0);
  body.data = {
    ...(body.data || {}),
    component_type: Number(component.type || 2),
    custom_id: String(component.custom_id)
  };
  const headers = {
    ...interactionHeaders,
    Authorization: discordAuthorization,
    "Content-Type": "application/json"
  };
  const response = await fetch(interactionURL, {
    method: "POST",
    headers,
    body: JSON.stringify(body)
  });
  if (!response.ok) throw new Error(`Discord Copy interaction returned ${response.status}`);
  return true;
}

function runInteractionQueue() {
  if (interactionBusy || interactionQueue.length === 0) return;
  interactionBusy = true;
  const item = interactionQueue.shift();
  sendCopyInteraction(item.message, item.payload).then((sent) => {
    if (sent) apiDiagnostics.interactionSentCount += 1;
    apiDiagnostics.interactionLastError = null;
  }).catch((error) => {
    apiDiagnostics.interactionLastError = error instanceof Error ? error.message : String(error);
  }).finally(() => {
    setTimeout(() => {
      interactionBusy = false;
      runInteractionQueue();
    }, 1100);
  });
}

function queueCopyInteractions(messages, payload) {
  if (!interactionTemplate || !discordAuthorization) return;
  const channelId = String(payload.channelId || "");
  const previouslyInitialized = Array.from(copyMessagesSeen).some((key) => key.startsWith(`${channelId}:`));
  const selected = previouslyInitialized
    ? messages.filter((message) => !copyMessagesSeen.has(`${channelId}:${message.id}`)).reverse()
    : messages.slice(0, 3).reverse();
  for (const message of messages) copyMessagesSeen.add(`${channelId}:${message.id}`);
  for (const message of selected) {
    if (findCopyComponent(message.components)) interactionQueue.push({ message, payload });
  }
  chrome.storage.session.set({ copyMessagesSeen: Array.from(copyMessagesSeen).slice(-500) });
  runInteractionQueue();
}

async function pollDiscordChannel(payload) {
  const channelId = String(payload.channelId || "");
  if (!channelId) return;
  if (!discordAuthorization) {
    apiDiagnostics.lastError = "Waiting for Discord authorization header";
    return;
  }
  const now = Date.now();
  if (now - (channelPollTimes.get(channelId) || 0) < 2500) return;
  channelPollTimes.set(channelId, now);

  try {
    const response = await fetch(
      `https://discord.com/api/v9/channels/${encodeURIComponent(channelId)}/messages?limit=50`,
      { headers: { Authorization: discordAuthorization } }
    );
    if (!response.ok) throw new Error(`Discord feed returned ${response.status}`);
    const messages = await response.json();
    if (!Array.isArray(messages)) throw new Error("Discord feed returned invalid data");
    apiDiagnostics.lastPollAt = new Date().toISOString();
    apiDiagnostics.messageCount = messages.length;
    const allLinks = messages.flatMap((message) => urlsFromDiscordMessage(message));
    apiDiagnostics.coordinateLinkCount = allLinks.filter(
      (link) => isCoordinateLink(link.href, link.label)
    ).length;
    apiDiagnostics.linkHosts = Array.from(new Set(allLinks.map((link) => {
      try { return new URL(link.href).hostname; } catch { return "invalid"; }
    }))).slice(0, 12);
    apiDiagnostics.lastError = null;
    const hasPokedex100Links = allLinks.some(
      (link) => coordinateLinkSource(link.href, link.label) === "pokedex100"
    );
    if (ENABLE_POKEX_INTERACTION_FALLBACK && !hasPokedex100Links) {
      queueCopyInteractions(messages, payload);
    }

    for (const message of messages.slice(0, 20).reverse()) {
    const messageId = String(message.id || "");
    const key = `${channelId}:${messageId}`;
    if (!messageId || apiMessagesSeen.has(key) || now < (apiRetryTimes.get(key) || 0)) continue;
    const result = await relay({
      guildId: String(message.guild_id || payload.guildId || ""),
      channelId,
      channelName: String(payload.channelName || "unknown"),
      messageId,
      rawText: [message.content, ...(message.embeds || []).map((embed) => embed.description || "")]
        .filter(Boolean).join("\n").slice(0, 12000),
      links: urlsFromDiscordMessage(message),
      observedAt: message.timestamp || new Date().toISOString(),
      trustedHundoChannel: String(payload.channelName || "").includes("💯")
        || String(payload.channelName || "").toLowerCase().includes("100")
    });
      if (result.accepted) {
        apiMessagesSeen.add(key);
        apiDiagnostics.acceptedCount += result.inserted ? 1 : 0;
      } else {
        apiRetryTimes.set(key, now + 60_000);
      }
    }
    if (apiDiagnostics.coordinateLinkCount > 0
        && apiDiagnostics.acceptedCount === 0
        && !apiDiagnostics.lastError) {
      apiDiagnostics.lastError = "Coordinate link returned no explicit GPS value";
    }
  } catch (error) {
    apiDiagnostics.lastError = error instanceof Error ? error.message : String(error);
    throw error;
  }
}

let relayChain = Promise.resolve();
chrome.runtime.onMessage.addListener((message) => {
  if (message?.type === "SHUNDO_RELAY_HEARTBEAT") {
    pollDiscordChannel(message.payload).then(() => postHeartbeat(message.payload)).then(async () => {
      await chrome.action.setBadgeBackgroundColor({ color: "#278A5B" });
      await chrome.action.setBadgeText({ text: "ON" });
    }).catch(async () => {
      await chrome.action.setBadgeBackgroundColor({ color: "#B8423A" });
      await chrome.action.setBadgeText({ text: "ERR" });
    });
    return;
  }
  if (message?.type !== "SHUNDO_SIGHTING_CANDIDATE") return;
  relayChain = relayChain
    .then(() => relay(message.payload))
    .catch(async () => {
      await chrome.action.setBadgeBackgroundColor({ color: "#B8423A" });
      await chrome.action.setBadgeText({ text: "ERR" });
    });
});
