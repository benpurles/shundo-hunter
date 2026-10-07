(() => {
  const COORDINATE_RE = /(-?(?:[0-8]?\d\.\d{4,}|90\.0{4,}))\s*[, ]\s*(-?(?:1[0-7]\d\.\d{4,}|\d?\d\.\d{4,}|180\.0{4,}))/;

  function coordinateFromDocument(documentValue, url) {
    for (const input of documentValue.querySelectorAll("input[value]")) {
      const match = String(input.value || "").match(COORDINATE_RE);
      if (!match) continue;
      const latitude = Number(match[1]);
      const longitude = Number(match[2]);
      if (Number.isFinite(latitude) && Number.isFinite(longitude)
          && Math.abs(latitude) <= 90 && Math.abs(longitude) <= 180) {
        return { latitude, longitude, url };
      }
    }
    return null;
  }

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type !== "SHUNDO_RESOLVE_POKEDEX100") return false;
    (async () => {
      try {
        const targetURL = new URL(String(message.url || ""), location.href);
        if (targetURL.hostname !== "coord.pokedex100.com") {
          throw new Error("Rejected a non-Pokedex100 coordinate URL");
        }
        const response = await fetch(targetURL.href, {
          credentials: "include",
          redirect: "follow"
        });
        if (!response.ok) throw new Error(`Coordinate page returned ${response.status}`);
        const html = await response.text();
        const documentCopy = new DOMParser().parseFromString(html, "text/html");
        const coordinate = coordinateFromDocument(documentCopy, response.url || targetURL.href);
        if (!coordinate) throw new Error("Signed-in page did not contain a coordinate");
        sendResponse({ coordinate });
      } catch (error) {
        sendResponse({ error: error instanceof Error ? error.message : String(error) });
      }
    })();
    return true;
  });
})();
