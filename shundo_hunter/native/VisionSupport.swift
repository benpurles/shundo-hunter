import Foundation
import Security
import ImageIO
import CoreGraphics

// Private helpers for the local backend. Secrets and images travel on pipes,
// not command arguments, temporary files, browser storage, or application logs.
let mode = CommandLine.arguments.dropFirst().first ?? ""
func fail(_ message: String) -> Never {
    FileHandle.standardError.write(Data((message + "\n").utf8)); exit(1)
}
func output(_ object: Any) {
    guard let data = try? JSONSerialization.data(withJSONObject: object) else { fail("Invalid helper response") }
    FileHandle.standardOutput.write(data)
}
let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
    kSecAttrService as String: "local.shundohunter.vision.openai",
    kSecAttrAccount as String: "api-key"]
switch mode {
case "key-store":
    let data = FileHandle.standardInput.readDataToEndOfFile()
    guard data.count >= 20, data.count < 512, let key = String(data: data, encoding: .utf8),
          key.hasPrefix("sk-"), !key.contains(where: { $0.isWhitespace }) else { fail("Invalid API key format") }
    let update = SecItemUpdate(query as CFDictionary, [kSecValueData as String: data] as CFDictionary)
    if update == errSecItemNotFound {
        var add = query
        add[kSecValueData as String] = data
        add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        guard SecItemAdd(add as CFDictionary, nil) == errSecSuccess else { fail("Could not save API key in Keychain") }
    } else if update != errSecSuccess { fail("Could not update API key in Keychain") }
    output(["saved": true])
case "key-read", "key-status":
    var q = query
    q[kSecReturnData as String] = mode == "key-read"
    q[kSecMatchLimit as String] = kSecMatchLimitOne
    q[kSecUseAuthenticationUI as String] = kSecUseAuthenticationUIFail
    var result: CFTypeRef?
    let status = SecItemCopyMatching(q as CFDictionary, &result)
    if mode == "key-status" { output(["configured": status == errSecSuccess]); break }
    guard status == errSecSuccess, let data = result as? Data else { fail("API key unavailable; save it in Hunter Settings") }
    FileHandle.standardOutput.write(data)
case "key-delete":
    let status = SecItemDelete(query as CFDictionary)
    guard status == errSecSuccess || status == errSecItemNotFound else { fail("Could not remove the Hunter API key") }
    output(["removed": true])
case "frame", "recovery-frame":
    let data = FileHandle.standardInput.readDataToEndOfFile()
    guard data.count <= 12_000_000, let source = CGImageSourceCreateWithData(data as CFData, nil),
          let image = CGImageSourceCreateImageAtIndex(source, 0, nil),
          image.width >= 300, image.width <= 3000, image.height > image.width, image.height <= 5000 else { fail("Unsupported phone screenshot") }
    // Omit the status/notification band and bottom trainer/inventory controls.
    let top = Int(Double(image.height) * 0.16), bottom = Int(Double(image.height) * (mode == "recovery-frame" ? 0.98 : 0.82))
    guard let crop = image.cropping(to: CGRect(x: 0, y: top, width: image.width, height: bottom - top)) else { fail("Could not crop phone image") }
    let png = NSMutableData()
    guard let destination = CGImageDestinationCreateWithData(png, "public.png" as CFString, 1, nil) else { fail("Could not encode phone image") }
    CGImageDestinationAddImage(destination, crop, nil)
    guard CGImageDestinationFinalize(destination) else { fail("Could not encode phone image") }
    var grid = [UInt8](repeating: 0, count: 96 * 96)
    let ok = grid.withUnsafeMutableBytes { bytes -> Bool in
        guard let context = CGContext(data: bytes.baseAddress, width: 96, height: 96, bitsPerComponent: 8,
            bytesPerRow: 96, space: CGColorSpaceCreateDeviceGray(), bitmapInfo: CGImageAlphaInfo.none.rawValue) else { return false }
        // Bitmap row order here already matches CGImage/PNG top-left order.
        // A synthetic two-tone image test guards against accidental inversion.
        context.draw(crop, in: CGRect(x: 0, y: 0, width: 96, height: 96)); return true
    }
    guard ok else { fail("Could not fingerprint phone image") }
    output(["image": (png as Data).base64EncodedString(), "pixelWidth": image.width,
        "pixelHeight": image.height, "cropTop": Double(top) / Double(image.height),
        "cropHeight": Double(bottom - top) / Double(image.height), "grid": grid])
default: fail("Unknown vision helper operation")
}
