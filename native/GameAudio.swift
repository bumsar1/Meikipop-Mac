import Foundation
import ScreenCaptureKit
import AVFoundation

// Audio only: stdout contains length-prefixed 24 kHz mono signed 16-bit PCM.
// No microphone or screen output is registered.
func fail(_ message: String) -> Never {
    FileHandle.standardError.write(Data((message + "\n").utf8)); exit(1)
}
func packet(_ pcm: Data) {
    var count = UInt32(pcm.count).littleEndian
    var out = Data(bytes: &count, count: 4); out.append(pcm)
    FileHandle.standardOutput.write(out)
}
final class Capture: NSObject, SCStreamOutput, SCStreamDelegate {
    var stream: SCStream?
    func stream(_ stream: SCStream, didStopWithError error: Error) { fail(error.localizedDescription) }
    func stream(_ stream: SCStream, didOutputSampleBuffer sample: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .audio, sample.isValid,
              let description = sample.formatDescription,
              let asbd = CMAudioFormatDescriptionGetStreamBasicDescription(description) else { return }
        guard asbd.pointee.mSampleRate == 24000,
              asbd.pointee.mFormatFlags & kAudioFormatFlagIsFloat != 0,
              asbd.pointee.mBitsPerChannel == 32 else { fail("Unsupported audio format") }
        let list = AudioBufferList.allocate(maximumBuffers: Int(asbd.pointee.mChannelsPerFrame))
        defer { list.unsafeMutablePointer.deallocate() }
        var block: CMBlockBuffer?
        let status = CMSampleBufferGetAudioBufferListWithRetainedBlockBuffer(sample, bufferListSizeNeededOut: nil,
            bufferListOut: list.unsafeMutablePointer, bufferListSize: AudioBufferList.sizeInBytes(maximumBuffers: Int(asbd.pointee.mChannelsPerFrame)),
            blockBufferAllocator: nil, blockBufferMemoryAllocator: nil, flags: 0, blockBufferOut: &block)
        guard status == noErr else { fail("Audio buffer error: \(status)") }
        let buffers = UnsafeMutableAudioBufferListPointer(list.unsafeMutablePointer)
        let frames = CMSampleBufferGetNumSamples(sample)
        var samples = [Int16](repeating: 0, count: frames)
        for i in 0..<frames {
            var total: Float = 0; var channels = 0
            for buffer in buffers {
                guard let data = buffer.mData else { continue }
                let n = Int(buffer.mNumberChannels)
                guard (i + 1) * n * 4 <= Int(buffer.mDataByteSize) else { fail("Truncated audio buffer") }
                let values = data.assumingMemoryBound(to: Float.self)
                for c in 0..<n { total += values[i*n+c]; channels += 1 }
            }
            let value = total / Float(max(1, channels))
            samples[i] = Int16(max(-32767, min(32767, (value.isFinite ? value : 0) * 32767))).littleEndian
        }
        samples.withUnsafeBytes { packet(Data($0)) }
    }
    func start(pid: pid_t, windowID: CGWindowID) async throws {
        let content = try await SCShareableContent.excludingDesktopWindows(true, onScreenWindowsOnly: true)
        guard let application = content.applications.first(where: { $0.processID == pid }),
              let window = content.windows.first(where: { $0.windowID == windowID && $0.owningApplication?.processID == pid }),
              let display = content.displays.first(where: { $0.frame.intersects(window.frame) }) else {
            fail("The selected game window is unavailable. Select it again.")
        }
        let filter = SCContentFilter(display: display, including: [application], exceptingWindows: [])
        let config = SCStreamConfiguration()
        config.capturesAudio = true
        config.excludesCurrentProcessAudio = true
        config.sampleRate = 24000; config.channelCount = 1
        config.width = 2; config.height = 2
        config.minimumFrameInterval = CMTime(value: 1, timescale: 1)
        let capture = SCStream(filter: filter, configuration: config, delegate: self)
        try capture.addStreamOutput(self, type: .audio, sampleHandlerQueue: DispatchQueue(label: "GameAudio.samples"))
        stream = capture
        try await capture.startCapture()
    }
}
if CommandLine.arguments.contains("--self-test") {
    let values = (0..<24000).map { Int16(sin(Double($0) * 2 * .pi * 440 / 24000) * 5000).littleEndian }
    values.withUnsafeBytes { packet(Data($0)) }; exit(0)
}
guard CommandLine.arguments.count == 3, let pid = Int32(CommandLine.arguments[1]), let window = UInt32(CommandLine.arguments[2]) else { fail("Expected process ID and window ID") }
let capture = Capture()
Task { do { try await capture.start(pid: pid, windowID: window) } catch { fail(error.localizedDescription) } }
RunLoop.main.run()
