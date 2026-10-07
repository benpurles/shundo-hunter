import AppKit

@main
final class PokeXTeleportCapture: NSObject, NSApplicationDelegate {
    private static let outputURL = URL(fileURLWithPath: "/private/tmp/pokex-teleport-urls.log")

    static func main() {
        let application = NSApplication.shared
        let delegate = PokeXTeleportCapture()
        application.delegate = delegate
        application.setActivationPolicy(.accessory)
        application.run()
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        // This helper stays invisible and exits after LaunchServices delivers a URL.
    }

    func application(_ application: NSApplication, open urls: [URL]) {
        let lines = urls.map { "\(Date().timeIntervalSince1970)\t\($0.absoluteString)\n" }.joined()
        let data = Data(lines.utf8)

        if FileManager.default.fileExists(atPath: Self.outputURL.path),
           let handle = try? FileHandle(forWritingTo: Self.outputURL) {
            defer { try? handle.close() }
            try? handle.seekToEnd()
            try? handle.write(contentsOf: data)
        } else {
            try? data.write(to: Self.outputURL, options: .atomic)
        }

        application.terminate(nil)
    }
}
