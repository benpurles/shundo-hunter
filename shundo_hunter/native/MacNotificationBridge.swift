import AppKit
import ApplicationServices
import Foundation

final class MacNotificationBridge {
    private let endpoint: URL
    private var timer: Timer?
    private var visibleFingerprints = Set<String>()
    private var recentEmissions: [String: Date] = [:]
    private var completedWarmup = false
    private var lastStatusSentAt = Date.distantPast
    private var lastState = "starting"
    private var lastPostedState = ""
    private var lastPostedTrusted = false
    private let targetBundleIdentifiers = [
        "com.apple.notificationcenterui",
        "com.apple.UserNotificationCenter"
    ]

    init(endpoint: URL) {
        self.endpoint = endpoint
    }

    func start() {
        guard timer == nil else { return }
        scan()
        timer = Timer.scheduledTimer(withTimeInterval: 0.35, repeats: true) { [weak self] _ in
            self?.scan()
        }
    }

    func stop() {
        timer?.invalidate()
        timer = nil
    }

    func requestAccessibility() {
        let promptKey = kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String
        let options = [promptKey: true] as CFDictionary
        _ = AXIsProcessTrustedWithOptions(options)
        postStatus(force: true)
    }

    private func scan() {
        guard AXIsProcessTrusted() else {
            lastState = "accessibility-required"
            completedWarmup = false
            postStatus()
            return
        }

        let applications = NSWorkspace.shared.runningApplications.filter { application in
            guard let bundleIdentifier = application.bundleIdentifier else { return false }
            return targetBundleIdentifiers.contains(bundleIdentifier)
        }
        guard !applications.isEmpty else {
            lastState = "notification-center-unavailable"
            postStatus()
            return
        }

        lastState = "listening"
        let now = Date()
        recentEmissions = recentEmissions.filter { now.timeIntervalSince($0.value) < 6 }
        var observed: [(elementFingerprint: String, contentFingerprint: String, lines: [String])] = []

        for application in applications {
            let root = AXUIElementCreateApplication(application.processIdentifier)
            let topLevelElements = elements(from: root, attribute: kAXWindowsAttribute)
                + elements(from: root, attribute: kAXChildrenAttribute)
            for element in topLevelElements {
                var lines: [String] = []
                var visited = Set<CFHashCode>()
                collectStrings(from: element, depth: 0, visited: &visited, lines: &lines)
                lines = uniqueMeaningfulLines(lines)
                let joined = lines.joined(separator: " · ")
                // Notification Center's accessibility tree can also expose menus
                // and unrelated system UI. Require both the source app and an
                // alert keyword so our own "Shundo Hunter" app name can never be
                // mistaken for a Shundo notification.
                guard !containsHunterKeyword(joined),
                      containsTargetAppKeyword(joined),
                      containsHundoKeyword(joined) else { continue }
                let contentFingerprint = joined.lowercased()
                // Text alone is not an identity: consecutive Pokémon of the
                // same species produce identical banners, and both cards may
                // coexist in Notification Center. AX element identity lets a
                // newly inserted identical card create a fresh visibility edge.
                let elementFingerprint = "\(CFHash(element))|\(contentFingerprint)"
                observed.append((elementFingerprint, contentFingerprint, lines))
            }
        }

        if !completedWarmup {
            visibleFingerprints = Set(observed.map(\.elementFingerprint))
            completedWarmup = true
            postStatus(force: true)
            return
        }

        let currentFingerprints = Set(observed.map(\.elementFingerprint))
        for item in observed
        where !visibleFingerprints.contains(item.elementFingerprint)
            && recentEmissions[item.contentFingerprint] == nil {
            recentEmissions[item.contentFingerprint] = now
            postNotification(lines: item.lines)
        }
        visibleFingerprints = currentFingerprints
        postStatus()
    }

    private func containsHundoKeyword(_ text: String) -> Bool {
        let withoutHunterName = text.replacingOccurrences(
            of: #"\bshundo\s+hunter\b"#,
            with: "",
            options: [.regularExpression, .caseInsensitive]
        )
        return withoutHunterName.range(
            of: #"\b(?:shundo|hundo|100\s*iv|iv\s*100)\b"#,
            options: [.regularExpression, .caseInsensitive]
        ) != nil
    }

    private func containsHunterKeyword(_ text: String) -> Bool {
        text.range(
            of: #"\bshundo\s+hunter\b"#,
            options: [.regularExpression, .caseInsensitive]
        ) != nil
    }

    private func containsTargetAppKeyword(_ text: String) -> Bool {
        text.range(
            of: #"\b(?:pok[eé]mon\s*go|ipogo)\b"#,
            options: [.regularExpression, .caseInsensitive]
        ) != nil
    }

    private func elements(from element: AXUIElement, attribute: String) -> [AXUIElement] {
        guard let value = attributeValue(element, attribute) else { return [] }
        if let array = value as? [AXUIElement] { return array }
        if CFGetTypeID(value) == AXUIElementGetTypeID() {
            return [unsafeBitCast(value, to: AXUIElement.self)]
        }
        return []
    }

    private func attributeValue(_ element: AXUIElement, _ attribute: String) -> CFTypeRef? {
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, attribute as CFString, &value) == .success else {
            return nil
        }
        return value
    }

    private func collectStrings(
        from element: AXUIElement,
        depth: Int,
        visited: inout Set<CFHashCode>,
        lines: inout [String]
    ) {
        guard depth <= 10, visited.count < 1_200 else { return }
        let identity = CFHash(element)
        guard visited.insert(identity).inserted else { return }

        for attribute in [kAXTitleAttribute, kAXDescriptionAttribute, kAXValueAttribute] {
            if let value = attributeValue(element, attribute) as? String {
                lines.append(value)
            }
        }
        for child in elements(from: element, attribute: kAXChildrenAttribute) {
            collectStrings(from: child, depth: depth + 1, visited: &visited, lines: &lines)
        }
    }

    private func uniqueMeaningfulLines(_ rawLines: [String]) -> [String] {
        var seen = Set<String>()
        var result: [String] = []
        for rawLine in rawLines {
            let line = rawLine
                .replacingOccurrences(of: #"\s+"#, with: " ", options: .regularExpression)
                .trimmingCharacters(in: .whitespacesAndNewlines)
            guard !line.isEmpty, line.count <= 700 else { continue }
            let key = line.lowercased()
            guard seen.insert(key).inserted else { continue }
            result.append(line)
        }
        return result
    }

    private func postNotification(lines: [String]) {
        let appName = lines.first(where: {
            $0.localizedCaseInsensitiveContains("Pokémon GO")
                || $0.localizedCaseInsensitiveContains("Pokemon GO")
                || $0.localizedCaseInsensitiveContains("iPogo")
        }) ?? "iPhone notification"
        let title = lines.first(where: { containsHundoKeyword($0) }) ?? "iPogo alert"
        let body = lines
            .filter { $0.caseInsensitiveCompare(appName) != .orderedSame && $0.caseInsensitiveCompare(title) != .orderedSame }
            .joined(separator: " · ")
        post([
            "type": "notification",
            "state": "listening",
            "trusted": true,
            "appName": appName,
            "title": title,
            "body": body
        ])
    }

    private func postStatus(force: Bool = false) {
        let now = Date()
        let trusted = AXIsProcessTrusted()
        let changed = lastState != lastPostedState || trusted != lastPostedTrusted
        guard force || changed || now.timeIntervalSince(lastStatusSentAt) >= 2 else { return }
        lastStatusSentAt = now
        lastPostedState = lastState
        lastPostedTrusted = trusted
        post([
            "type": "status",
            "state": lastState,
            "trusted": trusted
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
}
