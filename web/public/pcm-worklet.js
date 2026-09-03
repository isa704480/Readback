/* pcm-worklet.js -- the AudioWorkletProcessor that turns the microphone into
 * the bytes the server forwards to AssemblyAI: PCM16 signed little-endian,
 * mono, 16 kHz, in fixed 100 ms chunks.
 *
 * A PLAIN FILE, ON PURPOSE. It is served from web/public as-is and loaded with
 * audioWorklet.addModule('/pcm-worklet.js'). Vite cannot bundle a worklet
 * through `import`: the module runs on the audio rendering thread in its own
 * global scope, with no `window`, no `document` and no module graph, so it must
 * be a self-contained script. Nothing in here may import anything.
 *
 * WHY AN AUDIOWORKLET AND NOT THE TWO OBVIOUS ALTERNATIVES.
 *   ScriptProcessorNode is deprecated, runs on the main thread, and glitches
 *   whenever React renders for longer than one render quantum.
 *   MediaRecorder emits Opus in WebM. The server wants raw PCM and there is no
 *   way to ask MediaRecorder for it.
 *
 * WHAT IT DOES, IN ORDER
 *   1. receives Float32 frames at the AudioContext rate (48 kHz on nearly every
 *      device, 44.1 kHz on some, 96 kHz on a few pro interfaces);
 *   2. low-passes them below the 16 kHz Nyquist (8 kHz) with a windowed-sinc
 *      FIR, then resamples to 16 kHz;
 *   3. converts Float32 [-1, 1] to Int16 LE;
 *   4. posts one 1600-sample (3200-byte) chunk every 100 ms, as a transferred
 *      ArrayBuffer, along with the chunk's peak level.
 *
 * THE RESAMPLER IS NOT A DECIMATOR. Taking every third sample of a 48 kHz
 * signal folds everything between 8 and 24 kHz back into the 0-8 kHz band the
 * recogniser reads: a 10 kHz whistle becomes a 6 kHz one, and the noise floor
 * above 8 kHz lands on top of the sibilants the S/F distinction lives in. So
 * the signal is filtered first. The filter is a Blackman-windowed sinc with a
 * -6 dB point at 7040 Hz (0.44 x 16 kHz); its length scales with the input
 * rate so the transition band stays about 2.7 kHz wide whatever the device
 * rate is. Measured with synthetic tones (scripts in the report): a 10 kHz
 * input at 48 kHz reaches the 16 kHz output tens of dB down, while a 1 kHz
 * tone passes within a fraction of a dB.
 *
 * For an integer ratio (48 -> 16) the filtered signal is read at every third
 * sample, which is exact. For a fractional ratio (44.1 -> 16, step 2.75625)
 * the filtered signal is evaluated at the two integer positions either side of
 * the ideal one and linearly interpolated; after a 7 kHz low-pass the signal
 * at 44.1 kHz is smooth enough that the interpolation error is small for
 * anything in the speech band. The report carries the measured figure.
 *
 * WHY 100 ms CHUNKS. AssemblyAI accepts 50-1000 ms per binary frame and closes
 * the socket (3007) outside that window. 50 ms would be twenty messages a
 * second per session -- twice the WebSocket framing, twice the server's
 * per-message wakeups and lock acquisitions, for no gain in recognition. 250 ms
 * would delay the first byte of every word by up to a quarter of a second
 * before the recogniser could even start on it, and the pipeline's interrupt
 * budget (ARCHITECTURE 3.6) is measured in the same units. 100 ms sits at 2x
 * the floor and 10x under the ceiling, so a scheduler hiccup that delivers two
 * chunks back to back (200 ms) is still well inside the window.
 *
 * WHAT IT NEVER DOES. It keeps exactly one chunk in flight -- the one being
 * filled -- and transfers it out the moment it is full. It writes nothing to
 * any storage, logs nothing, and never sees the network.
 */

const TARGET_RATE = 16000;
const CHUNK_MS = 100;
const CUTOFF_HZ = 0.44 * TARGET_RATE; // 7040 Hz: -6 dB point of the low-pass
const TAPS_AT_48K = 97; // odd, so the filter has a centre tap

function blackman(k, n) {
  const x = (2 * Math.PI * k) / (n - 1);
  return 0.42 - 0.5 * Math.cos(x) + 0.08 * Math.cos(2 * x);
}

/* Windowed-sinc low-pass, normalised to unit DC gain. */
function designLowPass(inputRate) {
  let n = Math.round((TAPS_AT_48K * inputRate) / 48000);
  if (n % 2 === 0) n += 1;
  if (n < 31) n = 31;
  const half = (n - 1) / 2;
  const fc = CUTOFF_HZ / inputRate; // cycles per sample
  const taps = new Float32Array(n);
  let sum = 0;
  for (let k = 0; k < n; k++) {
    const m = k - half;
    const sinc = m === 0 ? 2 * fc : Math.sin(2 * Math.PI * fc * m) / (Math.PI * m);
    const v = sinc * blackman(k, n);
    taps[k] = v;
    sum += v;
  }
  for (let k = 0; k < n; k++) taps[k] /= sum;
  return taps;
}

class PcmCaptureProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const opts = (options && options.processorOptions) || {};
    this.inputRate = sampleRate; // worklet-scope global: the context rate
    this.targetRate = opts.targetRate || TARGET_RATE;
    this.step = this.inputRate / this.targetRate;
    this.taps = designLowPass(this.inputRate);
    this.half = (this.taps.length - 1) / 2;

    // Samples carried over between process() calls: the filter needs
    // `taps.length` of history around every output position.
    this.tail = new Float32Array(0);
    this.pos = this.half; // fractional index into the work buffer of the next output
    this.work = new Float32Array(this.taps.length + 4096);

    this.chunkSamples = Math.round((this.targetRate * (opts.chunkMs || CHUNK_MS)) / 1000);
    this.chunk = new Int16Array(this.chunkSamples);
    this.fill = 0;
    this.peak = 0;
    this.running = true;

    this.port.onmessage = (event) => {
      if (event.data === 'stop') this.running = false;
    };
  }

  /* One low-passed sample at integer index i of the work buffer. */
  fir(buf, i) {
    const taps = this.taps;
    const base = i - this.half;
    let y = 0;
    for (let k = 0; k < taps.length; k++) y += taps[k] * buf[base + k];
    return y;
  }

  push(y) {
    if (y > 1) y = 1;
    else if (y < -1) y = -1;
    const a = y < 0 ? -y : y;
    if (a > this.peak) this.peak = a;
    this.chunk[this.fill++] = y < 0 ? Math.round(y * 32768) : Math.round(y * 32767);
    if (this.fill === this.chunkSamples) {
      const buffer = this.chunk.buffer;
      this.port.postMessage(
        { pcm: buffer, peak: this.peak, samples: this.chunkSamples, rate: this.targetRate },
        [buffer],
      );
      this.chunk = new Int16Array(this.chunkSamples);
      this.fill = 0;
      this.peak = 0;
    }
  }

  process(inputs) {
    if (!this.running) return false;
    const input = inputs[0];
    const ch = input && input[0];
    if (!ch || ch.length === 0) return true;

    const tail = this.tail;
    const need = tail.length + ch.length;
    if (need > this.work.length) this.work = new Float32Array(need + this.taps.length);
    const buf = this.work;
    buf.set(tail, 0);
    buf.set(ch, tail.length);

    // A second input channel, if the browser ignored channelCount: 1, is
    // folded in as a mean rather than dropped, so a stereo interface with the
    // voice on the right channel still reaches the recogniser.
    if (input.length > 1) {
      for (let c = 1; c < input.length; c++) {
        const other = input[c];
        for (let i = 0; i < ch.length; i++) buf[tail.length + i] += other[i];
      }
      for (let i = 0; i < ch.length; i++) buf[tail.length + i] /= input.length;
    }

    const last = need - 1 - this.half; // highest index at which fir() is valid
    let pos = this.pos;
    while (Math.floor(pos) + 1 <= last) {
      const i = Math.floor(pos);
      const frac = pos - i;
      const y0 = this.fir(buf, i);
      this.push(frac === 0 ? y0 : y0 + frac * (this.fir(buf, i + 1) - y0));
      pos += this.step;
    }

    const keepFrom = Math.max(0, Math.floor(pos) - this.half);
    this.tail = buf.slice(keepFrom, need);
    this.pos = pos - keepFrom;
    return true;
  }
}

registerProcessor('pcm-capture', PcmCaptureProcessor);
