import Foundation
import Vision
import ImageIO

// PNG arrives on stdin; only text/boxes leave on stdout. No images or OCR
// results are written to disk and no network or screen-recording API is used.
do {
    let data = FileHandle.standardInput.readDataToEndOfFile()
    guard data.count <= 12_000_000,
          let source = CGImageSourceCreateWithData(data as CFData, nil),
          let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
        throw NSError(domain: "CatchScreenReader", code: 1)
    }
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["en-US"]
    request.usesLanguageCorrection = false
    try VNImageRequestHandler(cgImage: image).perform([request])
    let lines: [[String: Any]] = (request.results ?? []).compactMap { observation in
        guard let candidate = observation.topCandidates(1).first else { return nil }
        let box = observation.boundingBox
        return ["text": candidate.string, "confidence": candidate.confidence,
                "x": box.minX, "y": 1 - box.maxY, "width": box.width, "height": box.height]
    }
    let output = try JSONSerialization.data(withJSONObject: lines, options: [.sortedKeys])
    FileHandle.standardOutput.write(output)
} catch {
    FileHandle.standardError.write(Data("Local encounter text recognition unavailable\n".utf8))
    exit(1)
}
