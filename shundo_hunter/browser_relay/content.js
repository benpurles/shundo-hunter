(() => {
  const seen = new Set();
  let scanScheduled = false;
  let relayActive = true;
  let observer;
  let autoCopyEnabled = false;
  let copyBusy = false;
  const timers = [];
  const copyQueued = new Set();
  const copyQueue = [];

  function stopRelay() {
    relayActive = false;
    observer?.disconnect();
    for (const timer of timers) clearInterval(timer);
  }

  function safeSend(message) {
    if (!relayActive) return;
    try {
      const pending = chrome.runtime.sendMessage(message);
      if (pending?.catch) pending.catch(stopRelay);
    } catch {
      // Chrome invalidates the old content-script context during an extension
      // reload. Stop its timers quietly; the refreshed tab starts a new copy.
      stopRelay();
    }
  }

  function copyButton(element) {
    return Array.from(element.querySelectorAll('button, [role="button"]')).find((button) =>
      /(?:^|\s)copy(?:\s|$)/i.test((button.textContent || button.getAttribute("aria-label") || "").trim())
    );
  }

  function runCopyQueue() {
    if (!relayActive || copyBusy || copyQueue.length === 0) return;
    copyBusy = true;
    const item = copyQueue.shift();
    if (item.button.isConnected) {
      try { item.button.click(); } catch { /* A removed Discord row is safe to skip. */ }
    }
    const timer = setTimeout(() => {
      copyBusy = false;
      runCopyQueue();
    }, 1100);
    timers.push(timer);
  }

  function enqueueCoordinateCopy(element, key) {
    if (copyQueued.has(key)) return;
    const button = copyButton(element);
    if (!button) return;
    copyQueued.add(key);
    copyQueue.push({ button, key });
    runCopyQueue();
  }

  function enableAutoCopy() {
    if (!relayActive) return;
    const context = channelContext();
    const candidates = candidateElements();
    for (const element of candidates.slice(-3)) {
      const id = messageId(element);
      const rawText = (element.innerText || element.textContent || "").trim();
      if (id && !/-?\d{1,2}\.\d{4,}\s*,\s*-?\d{1,3}\.\d{4,}/.test(rawText)) {
        enqueueCoordinateCopy(element, `${context.channelId}:${id}`);
      }
    }
    autoCopyEnabled = true;
    scheduleScan();
  }

  function channelContext() {
    const parts = location.pathname.split("/").filter(Boolean);
    return {
      guildId: parts[1] || "",
      channelId: parts[2] || "",
      channelName: document.title.match(/\|\s*#([^|]+)\s*\|/)?.[1]?.trim()
        || document.title.match(/#([^|]+)/)?.[1]?.trim()
        || "unknown"
    };
  }

  function messageId(element) {
    const id = element.id || element.getAttribute("data-list-item-id") || "";
    const numericParts = id.match(/\d{10,}/g);
    if (numericParts?.length) return numericParts[numericParts.length - 1];
    const text = (element.innerText || element.textContent || "").trim().slice(0, 500);
    let hash = 0;
    for (let index = 0; index < text.length; index += 1) {
      hash = ((hash << 5) - hash + text.charCodeAt(index)) | 0;
    }
    return text ? `dom-${Math.abs(hash)}` : "";
  }

  function collectLinks(element) {
    const links = [];
    const seenLinks = new Set();
    const controls = element.querySelectorAll(
      'a, button, [role="link"], [role="button"], [data-href], [data-url]'
    );
    for (const control of controls) {
      const label = (control.textContent || control.getAttribute("aria-label") || "").trim();
      const values = [
        control.href,
        control.getAttribute("href"),
        control.getAttribute("data-href"),
        control.getAttribute("data-url"),
        control.getAttribute("aria-label"),
        control.getAttribute("title")
      ].filter(Boolean);
      const encodedHtml = control.outerHTML || "";
      for (const match of encodedHtml.matchAll(/https?(?::|%3A)(?:\/|%2F){2}[^\s"'<>]+/gi)) {
        values.push(match[0]);
      }
      for (let href of values) {
        try { href = decodeURIComponent(href); } catch { /* Keep the original value. */ }
        const urlMatch = String(href).match(/https?:\/\/[^\s"'<>]+/i);
        if (!urlMatch || seenLinks.has(urlMatch[0])) continue;
        seenLinks.add(urlMatch[0]);
        links.push({ href: urlMatch[0], label: label.slice(0, 240) });
      }
    }
    return links.slice(0, 20);
  }

  function controlSamples(element) {
    return Array.from(element.querySelectorAll('a, button, [role="link"], [role="button"]'))
      .filter((control) => /copy|nearby|pokex/i.test(
        `${control.textContent || ""} ${control.getAttribute("aria-label") || ""}`
      ))
      .slice(0, 6)
      .map((control) => ({
        tag: control.tagName,
        text: (control.textContent || "").trim().slice(0, 120),
        html: (control.outerHTML || "").slice(0, 1200)
      }));
  }

  function candidateElements() {
    const selectors = [
      '[id^="chat-messages-"]',
      '[id^="chat-messages___"]',
      '[data-list-item-id^="chat-messages"]',
      'li[class*="messageListItem"]',
      'article[class*="message"]'
    ];
    const direct = Array.from(document.querySelectorAll(selectors.join(",")));
    const coordinateLinks = Array.from(document.querySelectorAll("a[href]"))
      .filter((anchor) => {
        const label = (anchor.textContent || "").toLowerCase();
        const href = (anchor.href || "").toLowerCase();
        return label.includes("coord") || href.includes("pokedex100");
      })
      .map((anchor) => anchor.closest('[id*="chat-messages"], [data-list-item-id*="chat-messages"], li, article'))
      .filter(Boolean);
    return Array.from(new Set([...direct, ...coordinateLinks])).slice(-150);
  }

  function scan() {
    scanScheduled = false;
    const context = channelContext();
    const candidates = candidateElements();
    let newCandidateCount = 0;
    let samples = [];
    for (const element of candidates) {
      const id = messageId(element);
      if (!id || seen.has(`${context.channelId}:${id}`)) continue;

      const rawText = (element.innerText || element.textContent || "").trim();
      const links = collectLinks(element);
      if (samples.length === 0) samples = controlSamples(element);
      if (!rawText && links.length === 0) continue;

      seen.add(`${context.channelId}:${id}`);
      newCandidateCount += 1;
      safeSend({
        type: "SHUNDO_SIGHTING_CANDIDATE",
        payload: {
          ...context,
          messageId: id,
          rawText: rawText.slice(0, 12000),
          links,
          observedAt: new Date().toISOString(),
          trustedHundoChannel: context.channelName.includes("💯")
            || context.channelName.toLowerCase().includes("100")
        }
      });
      const trustedChannel = context.channelName.includes("💯")
        || context.channelName.toLowerCase().includes("100");
      const alreadyHasCoordinate = /-?\d{1,2}\.\d{4,}\s*,\s*-?\d{1,3}\.\d{4,}/.test(rawText);
      if (trustedChannel && !alreadyHasCoordinate && autoCopyEnabled) {
        enqueueCoordinateCopy(element, `${context.channelId}:${id}`);
      }
    }
    heartbeat({ visibleMessageCount: candidates.length, newCandidateCount, controlSamples: samples });
  }

  function scheduleScan() {
    if (scanScheduled) return;
    scanScheduled = true;
    setTimeout(scan, 250);
  }

  function heartbeat(diagnostics = {}) {
    safeSend({
      type: "SHUNDO_RELAY_HEARTBEAT",
      payload: { ...channelContext(), ...diagnostics }
    });
  }

  observer = new MutationObserver(scheduleScan);
  observer.observe(document.documentElement, { childList: true, subtree: true });
  timers.push(setInterval(scan, 3000));
  timers.push(setInterval(heartbeat, 15000));
  scan();
  heartbeat();
})();
