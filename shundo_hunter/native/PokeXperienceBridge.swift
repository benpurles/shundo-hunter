import AppKit
import CryptoKit
import Foundation

/// Reads the same complete encrypted snapshot used by the PokeXperience app.
/// It never drives the PokeXperience window and never touches input or clipboard state.
final class PokeXperienceBridge {
    private let endpoint: URL
    private let statusURL: URL
    private let workQueue = DispatchQueue(label: "local.shundohunter.pokexperience", qos: .utility)
    private var timer: DispatchSourceTimer?
    private var syncing = false
    private var syncRequested = true
    private var lastSyncAttempt = Date.distantPast

    private let feedURL = URL(string: "https://pokexperience.com/p/?z=pokemon&iv=100")!
    private let refreshInterval: TimeInterval = 60
    private let clientCredential = "public:LJT0PJRBotR0EKRvnp6S"
    private let payloadKeyBase64 = "fQvMDM4NVHw70L0+80+kLAK3xxHsFYoWuXv9ZnrGsOE="

    init(endpoint: URL, jobURL _: URL, statusURL: URL, preferencesURL _: URL) {
        self.endpoint = endpoint
        self.statusURL = statusURL
    }

    func start() {
        guard timer == nil else { return }
        let source = DispatchSource.makeTimerSource(queue: workQueue)
        source.schedule(deadline: .now() + 1, repeating: 1)
        source.setEventHandler { [weak self] in self?.automaticTick() }
        timer = source
        source.resume()
        postStatus(state: "idle", message: "Full background feed ready. No scrolling or clipboard access is used.")
    }

    func stop() {
        timer?.cancel()
        timer = nil
    }

    func requestSync() {
        workQueue.async { [weak self] in
            guard let self else { return }
            self.syncRequested = true
            self.automaticTick()
        }
    }

    func handleTeleportURL(_: URL) {
        // Kept for compatibility with older app bundles that registered pokemongo://.
        // The background snapshot already includes coordinates, so no URL interception
        // is needed and the user's default URL handler is never changed.
    }

    private func automaticTick() {
        guard !syncing,
              let status = getJSON(statusURL),
              status["feedSourceMode"] as? String == "pokexperience" else { return }
        let now = Date()
        guard syncRequested || now.timeIntervalSince(lastSyncAttempt) >= refreshInterval else { return }
        syncRequested = false
        syncing = true
        lastSyncAttempt = now
        postStatus(state: "scanning", message: "Downloading the complete live 100-IV snapshot…")
        fetchSnapshot()
    }

    private func fetchSnapshot() {
        var request = URLRequest(url: feedURL)
        request.timeoutInterval = 30
        request.setValue(
            "Basic " + Data(clientCredential.utf8).base64EncodedString(),
            forHTTPHeaderField: "Authorization"
        )
        request.setValue("ios", forHTTPHeaderField: "X-Client-Platform")

        URLSession.shared.dataTask(with: request) { [weak self] data, response, error in
            guard let self else { return }
            self.workQueue.async {
                defer { self.syncing = false }
                do {
                    let items = try self.decodeSnapshot(data: data, response: response, error: error)
                    let accepted = self.postAndWait([
                        "type": "snapshot",
                        "state": "synced",
                        "message": "Synced \(items.count) live targets from the complete background feed.",
                        "appRunning": true,
                        "trusted": true,
                        "items": items,
                    ])
                    if !accepted {
                        self.postStatus(
                            state: "error",
                            message: "The full feed was decoded, but Hunter could not store the snapshot."
                        )
                    }
                } catch {
                    self.postStatus(state: "error", message: self.userFacingMessage(for: error))
                }
            }
        }.resume()
    }

    private enum FeedError: Error {
        case transport(String)
        case http(Int)
        case invalidPayload
        case unsupportedCatalog
    }

    private func decodeSnapshot(data: Data?, response: URLResponse?, error: Error?) throws -> [[String: Any]] {
        if let error { throw FeedError.transport(error.localizedDescription) }
        guard let http = response as? HTTPURLResponse else { throw FeedError.invalidPayload }
        guard http.statusCode == 200 else { throw FeedError.http(http.statusCode) }
        guard let data,
              let encoded = String(data: data, encoding: .utf8),
              let combined = Data(base64Encoded: encoded.trimmingCharacters(in: .whitespacesAndNewlines)),
              combined.count > 28,
              let keyData = Data(base64Encoded: payloadKeyBase64) else {
            throw FeedError.invalidPayload
        }

        let sealed = try AES.GCM.SealedBox(combined: combined)
        let plaintext = try AES.GCM.open(sealed, using: SymmetricKey(data: keyData))
        guard let rows = try JSONSerialization.jsonObject(with: plaintext) as? [[String: Any]],
              let catalog = pokemonCatalog(), !catalog.isEmpty else {
            throw FeedError.unsupportedCatalog
        }

        let now = Date()
        return rows.compactMap { row in
            guard number(row["iv"])?.intValue == 100,
                  let pokemonID = number(row["id"])?.intValue,
                  let species = catalog[String(pokemonID)],
                  let latitude = number(row["lat"])?.doubleValue,
                  let longitude = number(row["lng"])?.doubleValue,
                  (-90...90).contains(latitude), (-180...180).contains(longitude),
                  let expiresText = row["dsp"] as? String,
                  let expiresAt = ISO8601DateFormatter().date(from: expiresText),
                  expiresAt > now else { return nil }

            var item: [String: Any] = [
                "species": species,
                "latitude": latitude,
                "longitude": longitude,
                "expiresAt": expiresText,
            ]
            if let cp = number(row["cp"])?.intValue, cp > 0 { item["cp"] = cp }
            if let level = number(row["lvl"])?.doubleValue, level > 0 { item["level"] = level }
            if let city = clean(row["city"]) { item["city"] = city }
            if let country = clean(row["cc"]) { item["country"] = country }
            if let gender = clean(row["gender"]) { item["gender"] = gender.lowercased() }
            if let encounterID = clean(row["encounterid"]) { item["sourceKey"] = encounterID }
            return item
        }
    }

    private func pokemonCatalog() -> [String: String]? {
        guard let root = Bundle.main.resourceURL,
              let data = try? Data(contentsOf: root.appendingPathComponent("shundo_hunter/pokemon_catalog.json")),
              let catalog = try? JSONSerialization.jsonObject(with: data) as? [String: String] else {
            return nil
        }
        return catalog
    }

    private func clean(_ value: Any?) -> String? {
        guard let text = value as? String else { return nil }
        let result = text.trimmingCharacters(in: .whitespacesAndNewlines)
        return result.isEmpty ? nil : result
    }

    private func number(_ value: Any?) -> NSNumber? {
        if let number = value as? NSNumber { return number }
        if let text = value as? String, let number = Double(text) { return NSNumber(value: number) }
        return nil
    }

    private func userFacingMessage(for error: Error) -> String {
        switch error {
        case FeedError.transport:
            return "PokeXperience’s background feed could not be reached. Hunter will retry automatically."
        case FeedError.http(let status) where status == 401 || status == 403:
            return "PokeXperience rejected the background connection. Update the PokeXperience app, then sync again."
        case FeedError.http(let status):
            return "PokeXperience returned server status \(status). Hunter will retry automatically."
        case FeedError.unsupportedCatalog:
            return "Hunter could not match the feed to its Pokémon catalog."
        default:
            return "PokeXperience changed its feed format. Update the integration before hunting."
        }
    }

    private func postStatus(state: String, message: String) {
        post([
            "type": "status",
            "state": state,
            "message": message,
            "appRunning": true,
            "trusted": true,
        ])
    }

    private func post(_ payload: [String: Any]) {
        guard let body = try? JSONSerialization.data(withJSONObject: payload) else { return }
        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = body
        URLSession.shared.dataTask(with: request).resume()
    }

    @discardableResult
    private func postAndWait(_ payload: [String: Any]) -> Bool {
        guard let body = try? JSONSerialization.data(withJSONObject: payload) else { return false }
        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = body
        let semaphore = DispatchSemaphore(value: 0)
        var accepted = false
        URLSession.shared.dataTask(with: request) { _, response, _ in
            if let http = response as? HTTPURLResponse {
                accepted = (200..<300).contains(http.statusCode)
            }
            semaphore.signal()
        }.resume()
        _ = semaphore.wait(timeout: .now() + 20)
        return accepted
    }

    private func getJSON(_ url: URL) -> [String: Any]? {
        let semaphore = DispatchSemaphore(value: 0)
        var result: [String: Any]?
        URLSession.shared.dataTask(with: url) { data, response, _ in
            defer { semaphore.signal() }
            guard let http = response as? HTTPURLResponse, http.statusCode == 200,
                  let data,
                  let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }
            result = payload
        }.resume()
        _ = semaphore.wait(timeout: .now() + 10)
        return result
    }
}
