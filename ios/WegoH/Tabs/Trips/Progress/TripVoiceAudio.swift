import AVFAudio
import Foundation

private final class TripVoiceCapture: @unchecked Sendable {
    private let converter: AVAudioConverter
    private let format: AVAudioFormat
    private var pending = Data()
    private let frame: @Sendable (Data) -> Void
    private let failure: @Sendable () -> Void
    init(input: AVAudioFormat, frame: @escaping @Sendable (Data) -> Void, failure: @escaping @Sendable () -> Void) throws {
        guard input.sampleRate > 0, input.channelCount > 0,
              let format = AVAudioFormat(standardFormatWithSampleRate: 16_000, channels: 1),
              let converter = AVAudioConverter(from: input, to: format) else { throw TripVoiceFailure.audio }
        self.format = format; self.converter = converter; self.frame = frame; self.failure = failure
    }
    func consume(_ input: AVAudioPCMBuffer) {
        let capacity = AVAudioFrameCount(ceil(Double(input.frameLength) * 16_000 / input.format.sampleRate)) + 64
        guard let output = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: capacity) else { failure(); return }
        var used = false
        var error: NSError?
        let status = converter.convert(to: output, error: &error) { _, state in
            guard !used else { state.pointee = .noDataNow; return nil }
            used = true; state.pointee = .haveData; return input
        }
        guard status != .error, error == nil, let samples = output.floatChannelData?[0] else { failure(); return }
        for index in 0..<Int(output.frameLength) {
            let sample = samples[index]
            guard sample.isFinite else { failure(); return }
            var pcm = Int16(max(-32768, min(32767, Int((max(-1, min(1, sample)) * 32768).rounded())))).littleEndian
            withUnsafeBytes(of: &pcm) { pending.append(contentsOf: $0) }
        }
        while pending.count >= 640 {
            frame(Data(pending.prefix(640))); pending.removeFirst(640)
        }
    }
}

@MainActor
final class TripVoiceAudio {
    private var output: AVAudioEngine?
    private var player: AVAudioPlayerNode?
    private var input: AVAudioEngine?
    private(set) var playedFrames = 0
    private(set) var clipPlaying = false
    private var queued = 0
    private var playbackEpoch = UUID()
    private let format = AVAudioFormat(standardFormatWithSampleRate: 16_000, channels: 1)!

    func listen() throws {
        guard output == nil else { return }
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playback, mode: .voicePrompt, options: [.mixWithOthers])
        try session.setActive(true)
        let engine = AVAudioEngine(), node = AVAudioPlayerNode()
        engine.attach(node); engine.connect(node, to: engine.mainMixerNode, format: format)
        do { try engine.start(); node.play() }
        catch { engine.stop(); throw TripVoiceFailure.audio }
        output = engine; player = node
    }
    func capture(frame: @escaping @Sendable (Data) -> Void, failure: @escaping @Sendable () -> Void) throws {
        stopCapture(); stopPlayback()
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playAndRecord, mode: .voiceChat, options: [.defaultToSpeaker, .allowBluetoothHFP, .duckOthers])
        try session.setPreferredSampleRate(16_000)
        try session.setPreferredIOBufferDuration(0.02)
        try session.setActive(true)
        let engine = AVAudioEngine()
        let node = engine.inputNode
        let native = node.outputFormat(forBus: 0)
        let capture = try TripVoiceCapture(input: native, frame: frame, failure: failure)
        node.installTap(onBus: 0, bufferSize: AVAudioFrameCount(max(320, native.sampleRate * 0.02)), format: native) { buffer, _ in capture.consume(buffer) }
        do { try engine.start(); input = engine }
        catch { node.removeTap(onBus: 0); engine.stop(); throw TripVoiceFailure.audio }
    }
    func stopCapture() {
        if let input { input.inputNode.removeTap(onBus: 0); input.stop() }
        input = nil
    }
    func play(_ pcm: Data) throws {
        guard pcm.count == 640 else { throw TripVoiceFailure.protocolMismatch }
        if output?.isRunning != true { stopPlayback(); try listen() }
        guard let player, queued < 8,
              let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 320),
              let channel = buffer.floatChannelData?[0] else { throw TripVoiceFailure.pressure }
        buffer.frameLength = 320
        for index in 0..<320 {
            let offset = index * 2
            let value = UInt16(pcm[offset]) | UInt16(pcm[offset + 1]) << 8
            channel[index] = Float(Int16(bitPattern: value)) / 32768
        }
        queued += 1
        let epoch = playbackEpoch
        player.scheduleBuffer(buffer, completionCallbackType: .dataPlayedBack) { [weak self] _ in
            Task { @MainActor in
                guard let self, self.playbackEpoch == epoch else { return }
                self.queued = max(0, self.queued - 1)
                self.playedFrames += 320
            }
        }
    }
    func playClip(_ pcm: Data) throws {
        guard (640...480_000).contains(pcm.count), pcm.count.isMultiple(of: 640) else { throw TripVoiceFailure.protocolMismatch }
        clearPlayback()
        if output?.isRunning != true { stopPlayback(); try listen() }
        let samples = pcm.count / 2
        guard let player, let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(samples)),
              let channel = buffer.floatChannelData?[0] else { throw TripVoiceFailure.audio }
        buffer.frameLength = AVAudioFrameCount(samples)
        for index in 0..<samples {
            let offset = index * 2
            channel[index] = Float(Int16(bitPattern: UInt16(pcm[offset]) | UInt16(pcm[offset + 1]) << 8)) / 32768
        }
        let epoch = playbackEpoch
        clipPlaying = true
        player.scheduleBuffer(buffer, completionCallbackType: .dataPlayedBack) { [weak self] _ in
            Task { @MainActor in
                guard let self, self.playbackEpoch == epoch else { return }
                self.playedFrames += samples
                self.clipPlaying = false
            }
        }
    }
    func clearPlayback() { player?.stop(); playbackEpoch = UUID(); queued = 0; clipPlaying = false; if output?.isRunning == true { player?.play() } }
    private func stopPlayback() { clearPlayback(); output?.stop(); output = nil; player = nil }
    func stop() {
        stopCapture(); stopPlayback()
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }
}
