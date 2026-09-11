/* Lip movement follows the audio device clock, never synthesis/network timing. */
(function (root) {
  'use strict';

  function envelopeFromBuffer(buffer) {
    const windowSize = Math.max(1, Math.round(buffer.sampleRate * 0.02));
    const levels = new Float32Array(Math.ceil(buffer.length / windowSize));
    const forms = new Float32Array(levels.length);
    const channels = Array.from({length: buffer.numberOfChannels}, (_, i) => buffer.getChannelData(i));
    for (let index = 0; index < levels.length; index++) {
      const start = index * windowSize;
      const end = Math.min(buffer.length, start + windowSize);
      let energy = 0;
      let crossings = 0;
      for (const channel of channels) {
        for (let frame = start; frame < end; frame++) {
          energy += channel[frame] ** 2;
          if (frame > start && (channel[frame] >= 0) !== (channel[frame-1] >= 0)) crossings++;
        }
      }
      levels[index] = Math.sqrt(energy / ((end - start) * channels.length));
      forms[index] = Math.max(-0.45, Math.min(0.55, crossings / Math.max(1,(end-start)*channels.length) * 7 - 0.35));
    }
    return {levels, forms, step: windowSize / buffer.sampleRate, duration: buffer.duration};
  }

  function outputTime(context, nowMs) {
    if (!context) return 0;
    // currentTime is the render clock and can lead the speakers by multiple
    // buffers. getOutputTimestamp maps the samples at the device to wall time.
    const stamp = context.getOutputTimestamp?.();
    if (stamp && Number.isFinite(stamp.contextTime) && stamp.performanceTime > 0) {
      return Math.max(0, Math.min(context.currentTime,
        stamp.contextTime + Math.max(0, nowMs - stamp.performanceTime) / 1000));
    }
    return Math.max(0, context.currentTime - (context.baseLatency || 0) - (context.outputLatency || 0));
  }

  class Timeline {
    constructor() { this.offsetMs = 0; this.sensitivity = 1; this.clear(); }

    clear() {
      this.entries = [];
      this.resetMouth();
    }

    resetMouth() {
      this.level = 0;
      this.form = 0;
      this.lastTime = null;
    }

    schedule(source, buffer, start, rate = 1) {
      this.entries.push({source, envelope: envelopeFromBuffer(buffer), start, rate,
        end: start + buffer.duration / rate});
    }

    cancel(source) {
      this.entries = this.entries.filter(entry => entry.source !== source);
    }

    sample(time, running = true, volume = 1) {
      if (!running || volume <= 0) {
        this.resetMouth();
        return 0;
      }
      // Keep entries after onended until the final samples reach the speakers.
      time -= this.offsetMs / 1000;
      this.entries = this.entries.filter(entry => entry.end + 0.4 > time);
      let energy = 0;
      let form = 0;
      for (const entry of this.entries) {
        if (time < entry.start) continue;
        const index = Math.floor((time - entry.start) * entry.rate / entry.envelope.step);
        const levels=entry.envelope.levels;
        const center=levels[index] || 0;
        // Symmetric smoothing preserves syllable timing instead of delaying
        // every opening/closure with a second long attack/release filter.
        const value=center > 0.006 ? (center*0.6+(levels[index-1]||0)*0.2+(levels[index+1]||0)*0.2) : 0;
        if (value > energy) { energy=value; form=entry.envelope.forms[index] || 0; }
      }
      // Gate quiet background noise and smooth over several audio windows.
      // AnalyserNode.smoothingTimeConstant only smooths FFT magnitudes; it
      // does not smooth the time-domain samples used by the old implementation.
      const target = Math.min(0.9, Math.max(0, energy * this.sensitivity - 0.008) * 5);
      const dt = this.lastTime === null ? 1 / 60 : Math.min(0.1, Math.max(0, time - this.lastTime));
      const step=Math.max(0.08, Math.min(0.23, dt * 13));
      this.level += Math.max(-step,Math.min(step,target-this.level));
      this.form += (form-this.form)*0.45;
      if (this.level < 0.005) this.level = 0;
      this.lastTime = time;
      return this.level;
    }
  }

  const api = {Timeline, envelopeFromBuffer, outputTime};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.SpeechLipSync = api;
})(globalThis);
