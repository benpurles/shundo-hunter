import AppKit
import Darwin
import Foundation
import WebKit

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, WKScriptMessageHandler {
    private var window: NSWindow!
    private var webView: WKWebView!
    private var serverProcess: Process?
    private var logHandle: FileHandle?
    private var pidFileURL: URL?
    private var notificationBridge: MacNotificationBridge!
    private var pokexperienceBridge: PokeXperienceBridge!
    private let localURL = URL(string: "http://127.0.0.1:8765")!
    private let instanceToken = UUID().uuidString

    func applicationDidFinishLaunching(_ notification: Notification) {
        configureMenu()
        configureWindow()
        do {
            try startFeedService()
            notificationBridge = MacNotificationBridge(
                endpoint: localURL.appendingPathComponent("api/mac-notification")
            )
            notificationBridge.start()
            pokexperienceBridge = PokeXperienceBridge(
                endpoint: localURL.appendingPathComponent("api/pokexperience"),
                jobURL: localURL.appendingPathComponent("api/pokexperience/job"),
                statusURL: localURL.appendingPathComponent("api/status"),
                preferencesURL: localURL.appendingPathComponent("api/preferences")
            )
            pokexperienceBridge.start()
            waitForFeedService(attempt: 0)
        } catch {
            showLaunchError(error.localizedDescription)
        }
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationWillTerminate(_ notification: Notification) {
        notificationBridge?.stop()
        pokexperienceBridge?.stop()
        stopOwnedFeedService()
        try? logHandle?.close()
    }

    func application(_ application: NSApplication, open urls: [URL]) {
        for url in urls where url.scheme?.lowercased() == "pokemongo" {
            pokexperienceBridge?.handleTeleportURL(url)
        }
    }

    func windowWillClose(_ notification: Notification) {
        NSApp.terminate(nil)
    }

    private func configureWindow() {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .default()
        configuration.userContentController.add(self, name: "nativeBridge")
        webView = WKWebView(frame: .zero, configuration: configuration)
        webView.setValue(false, forKey: "drawsBackground")

        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1320, height: 860),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = "Shundo Hunter"
        window.minSize = NSSize(width: 900, height: 620)
        window.center()
        window.contentView = webView
        window.delegate = self
        window.makeKeyAndOrderFront(nil)
        webView.loadHTMLString("""
        <html><body style="margin:0;background:#0f1211;color:#dfe6e2;font:14px -apple-system;display:grid;place-items:center;height:100vh">
        <p>Starting Shundo Hunter…</p></body></html>
        """, baseURL: nil)
    }

    func userContentController(
        _ userContentController: WKUserContentController,
        didReceive message: WKScriptMessage
    ) {
        guard message.name == "nativeBridge", let action = message.body as? String else { return }
        if action == "requestAccessibility" {
            notificationBridge?.requestAccessibility()
        } else if action == "syncPokeXperience" {
            pokexperienceBridge?.requestSync()
        }
    }

    private func configureMenu() {
        let mainMenu = NSMenu()
        let appMenuItem = NSMenuItem(title: "Shundo Hunter", action: nil, keyEquivalent: "")
        mainMenu.addItem(appMenuItem)
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "About Shundo Hunter", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Quit Shundo Hunter", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appMenuItem.submenu = appMenu

        // WKWebView relies on the macOS responder chain for standard editing
        // shortcuts. Without an Edit menu, Command-V never reaches focused
        // text fields even though typing still works.
        let editMenuItem = NSMenuItem(title: "Edit", action: nil, keyEquivalent: "")
        let editMenu = NSMenu(title: "Edit")

        let undoItem = editMenu.addItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z")
        undoItem.keyEquivalentModifierMask = [.command]
        let redoItem = editMenu.addItem(withTitle: "Redo", action: Selector(("redo:")), keyEquivalent: "z")
        redoItem.keyEquivalentModifierMask = [.command, .shift]

        editMenu.addItem(.separator())
        editMenu.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        editMenu.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        editMenu.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        editMenu.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")

        editMenuItem.submenu = editMenu
        mainMenu.addItem(editMenuItem)
        NSApp.mainMenu = mainMenu
    }

    private func startFeedService() throws {
        guard let resources = Bundle.main.resourceURL else {
            throw NSError(domain: "ShundoHunter", code: 1, userInfo: [NSLocalizedDescriptionKey: "Application resources are missing."])
        }

        let fileManager = FileManager.default
        let supportRoot = try fileManager.url(
            for: .applicationSupportDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        ).appendingPathComponent("Shundo Hunter", isDirectory: true)
        try fileManager.createDirectory(at: supportRoot, withIntermediateDirectories: true)
        let databaseURL = supportRoot.appendingPathComponent("shundo_hunter.db")
        try terminateStaleFeedServices(databasePath: databaseURL.path, supportRoot: supportRoot)

        let bundledRelay = resources.appendingPathComponent("shundo_hunter/browser_relay", isDirectory: true)
        let installedRelay = supportRoot.appendingPathComponent("browser_relay", isDirectory: true)
        if !fileManager.fileExists(atPath: installedRelay.path) {
            try fileManager.copyItem(at: bundledRelay, to: installedRelay)
        } else {
            for name in ["manifest.json", "background.js", "content.js", "coordinate.js"] {
                let source = bundledRelay.appendingPathComponent(name)
                let destination = installedRelay.appendingPathComponent(name)
                let sourceData = try Data(contentsOf: source)
                let destinationData = try? Data(contentsOf: destination)
                if destinationData != sourceData {
                    try sourceData.write(to: destination, options: .atomic)
                }
            }
        }

        let pythonCandidates = [
            "/opt/homebrew/bin/python3",
            "/usr/local/bin/python3",
            "/usr/bin/python3"
        ]
        guard let python = pythonCandidates.first(where: { fileManager.isExecutableFile(atPath: $0) }) else {
            throw NSError(domain: "ShundoHunter", code: 2, userInfo: [NSLocalizedDescriptionKey: "Python 3 was not found on this Mac."])
        }

        let logURL = supportRoot.appendingPathComponent("shundo-hunter.log")
        if !fileManager.fileExists(atPath: logURL.path) {
            fileManager.createFile(atPath: logURL.path, contents: nil)
        }
        logHandle = try FileHandle(forWritingTo: logURL)
        try logHandle?.seekToEnd()

        let process = Process()
        process.executableURL = URL(fileURLWithPath: python)
        process.arguments = [
            "-m", "shundo_hunter.feed_server",
            "--database", databaseURL.path,
            "--static", resources.appendingPathComponent("shundo_hunter/web").path,
            "--relay-path", installedRelay.path,
            "--port", "8765",
            "--instance-token", instanceToken
        ]
        var environment = ProcessInfo.processInfo.environment
        environment["PYTHONPATH"] = resources.path
        environment["PYTHONUNBUFFERED"] = "1"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        process.environment = environment
        process.standardOutput = logHandle
        process.standardError = logHandle
        try process.run()
        serverProcess = process
        let pidURL = supportRoot.appendingPathComponent("feed-server.pid")
        try String(process.processIdentifier).write(to: pidURL, atomically: true, encoding: .utf8)
        pidFileURL = pidURL
    }

    private func terminateStaleFeedServices(databasePath: String, supportRoot: URL) throws {
        var candidates = Set<Int32>()
        let pidURL = supportRoot.appendingPathComponent("feed-server.pid")
        if let rawPID = try? String(contentsOf: pidURL, encoding: .utf8),
           let pid = Int32(rawPID.trimmingCharacters(in: .whitespacesAndNewlines)) {
            candidates.insert(pid)
        }
        if let listeners = capture("/usr/sbin/lsof", ["-nP", "-iTCP:8765", "-sTCP:LISTEN", "-t"]) {
            for line in listeners.split(whereSeparator: \Character.isNewline) {
                if let pid = Int32(line.trimmingCharacters(in: .whitespacesAndNewlines)) {
                    candidates.insert(pid)
                }
            }
        }

        for pid in candidates where pid != getpid() && processIsRunning(pid) {
            guard let command = capture("/bin/ps", ["-p", String(pid), "-o", "command="]),
                  command.contains("-m shundo_hunter.feed_server"),
                  command.contains(databasePath),
                  command.contains("--port 8765") else {
                throw NSError(
                    domain: "ShundoHunter",
                    code: 3,
                    userInfo: [NSLocalizedDescriptionKey: "Port 8765 is occupied by an unrelated process. It was left untouched."]
                )
            }
            _ = Darwin.kill(pid, SIGTERM)
            for _ in 0..<30 where processIsRunning(pid) { usleep(50_000) }
            if processIsRunning(pid) { _ = Darwin.kill(pid, SIGKILL) }
        }
        try? FileManager.default.removeItem(at: pidURL)
    }

    private func stopOwnedFeedService() {
        guard let process = serverProcess else { return }
        let pid = process.processIdentifier
        if process.isRunning {
            process.terminate()
            for _ in 0..<20 where process.isRunning { usleep(50_000) }
            if process.isRunning { _ = Darwin.kill(pid, SIGKILL) }
        }
        if let pidFileURL,
           let rawPID = try? String(contentsOf: pidFileURL, encoding: .utf8),
           rawPID.trimmingCharacters(in: .whitespacesAndNewlines) == String(pid) {
            try? FileManager.default.removeItem(at: pidFileURL)
        }
        serverProcess = nil
    }

    private func processIsRunning(_ pid: Int32) -> Bool {
        Darwin.kill(pid, 0) == 0 || errno == EPERM
    }

    private func capture(_ executable: String, _ arguments: [String]) -> String? {
        let process = Process()
        let pipe = Pipe()
        process.executableURL = URL(fileURLWithPath: executable)
        process.arguments = arguments
        process.standardOutput = pipe
        process.standardError = FileHandle.nullDevice
        do {
            try process.run()
            process.waitUntilExit()
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            return String(data: data, encoding: .utf8)
        } catch {
            return nil
        }
    }

    private func waitForFeedService(attempt: Int) {
        guard attempt < 40 else {
            showLaunchError("The local feed service did not start. Check ~/Library/Application Support/Shundo Hunter/shundo-hunter.log for details.")
            return
        }
        URLSession.shared.dataTask(with: localURL.appendingPathComponent("api/status")) { [weak self] data, response, _ in
            let matchingInstance: Bool
            if let data,
               let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                matchingInstance = payload["instanceToken"] as? String == self?.instanceToken
            } else {
                matchingInstance = false
            }
            if let http = response as? HTTPURLResponse, http.statusCode == 200, matchingInstance {
                DispatchQueue.main.async {
                    self?.webView.load(URLRequest(url: self!.localURL))
                }
            } else {
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) {
                    self?.waitForFeedService(attempt: attempt + 1)
                }
            }
        }.resume()
    }

    private func showLaunchError(_ message: String) {
        let escaped = message
            .replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;")
        webView.loadHTMLString("""
        <html><body style="margin:0;background:#0f1211;color:#dfe6e2;font:14px -apple-system;display:grid;place-items:center;height:100vh">
        <main style="max-width:520px;padding:32px"><h1 style="font-size:20px">Shundo Hunter could not start</h1><p style="color:#aab4af;line-height:1.6">\(escaped)</p></main>
        </body></html>
        """, baseURL: nil)
    }
}
