/* The microphone: getUserMedia plus the AudioWorklet in public/pcm-worklet.js.
 *
 * This module opens the device, runs the worklet, and hands each 100 ms PCM16
 * chunk to a callback. It does nothing with the network -- useLiveSession.ts
 * owns the socket -- and it holds no audio beyond the chunk the worklet is
 * filling on the rendering thread: a chunk is transferred (not copied) out of
 * the worklet, handed to the callback, and dropped. Nothing here is written to
 * IndexedDB, localStorage or the console.
 *
 * CALL ORDER MATTERS. `openMicrophone()` is the only thing in the app that
 * calls getUserMedia, and useLiveSession calls it AFTER /api/session/start has
 * accepted the consent record and never before. Browser permission is not
 * consent (ARCHITECTURE 3.12); the order in the session hook is what enforces
 * that, and this file has no opinion on it beyond refusing to be called twice.
 *
 * WHAT THE BROWSER ACTUALLY GAVE US. The constraints below are requests, not
 * guarantees: Chrome on a stereo interface may ignore channelCount, Firefox
 * treats echoCancellation as advisory, and Safari reports what it feels like.
 * `track.getSettings()` is the only truthful source, so it is captured and
 * returned as `granted` and the live screen prints it rather than the request.
 */

export type MicFailure =
  | 'denied' // NotAllowedError, or a permissions-policy block
  | 'missing' // NotFoundError / OverconstrainedError: no capture device
  | 'busy' // NotReadableError: another app or tab holds it
  | 'unsupported' // no getUserMedia, no AudioWorklet, or an insecure origin
  | 'other';

export interface MicGranted {
  /** From track.getSettings(). Only the fields the pipeline cares about. */
  sampleRate: number | null;
  channelCount: number | null;
  echoCancellation: boolean | null;
  noiseSuppression: boolean | null;
  autoGainControl: boolean | null;
  deviceLabel: string;
  /** The AudioContext rate the worklet resamples FROM. */
  contextSampleRate: number;
}

export interface MicChunk {
  /** 3200 bytes: 1600 samples of PCM16 LE at 16 kHz. */
  pcm: ArrayBuffer;
  /** Peak absolute sample in this chunk, 0..1. A liveness number, not audio. */
  peak: number;
}

export interface MicHandle {
  granted: MicGranted;
  /** Stop forwarding chunks without releasing the device (a hidden tab). */
  mute(): void;
  /** Resume forwarding. Whatever the worklet produced meanwhile is gone --
   *  it was never buffered -- so there is no backlog to replay. */
  unmute(): void;
  readonly muted: boolean;
  /** Release the device, stop the worklet, close the context. Idempotent. */
  close(): Promise<void>;
}

export class MicError extends Error {
  readonly failure: MicFailure;
  constructor(failure: MicFailure, message: string) {
    super(message);
    this.failure = failure;
  }
}

/* One request, and the reasons behind each of the four constraints.
 *
 *   channelCount 1       the recogniser is mono; a stereo request would double
 *                        the bytes to be resampled and folded anyway
 *   echoCancellation     the operator's own speaker output must not reach the
 *                        recogniser as a second voice
 *   noiseSuppression     ARCHITECTURE 3.2 preferred to leave this off and let
 *   autoGainControl      voice_focus do the job upstream. The task brief for
 *                        this screen asks for both on, and the measured
 *                        parameter set for universal-3-5-pro does not include
 *                        voice_focus, so the browser's processing is the only
 *                        noise treatment this build has. Reported, not assumed:
 *                        see `granted`. */
const CONSTRAINTS: MediaStreamConstraints = {
  audio: {
    channelCount: 1,
    echoCancellation: true,
    noiseSuppression: true,
    autoGainControl: true,
  },
  video: false,
};

const WORKLET_URL = '/pcm-worklet.js';
const WORKLET_NAME = 'pcm-capture';

function classify(error: unknown): MicError {
  const name = error instanceof DOMException || error instanceof Error ? error.name : '';
  const text = error instanceof Error ? error.message : String(error);
  switch (name) {
    case 'NotAllowedError':
    case 'PermissionDeniedError':
    case 'SecurityError':
      return new MicError('denied', text);
    case 'NotFoundError':
    case 'DevicesNotFoundError':
    case 'OverconstrainedError':
    case 'ConstraintNotSatisfiedError':
      return new MicError('missing', text);
    case 'NotReadableError':
    case 'TrackStartError':
    case 'AbortError':
      return new MicError('busy', text);
    default:
      return new MicError('other', text);
  }
}

let open = false;

export function microphoneSupported(): boolean {
  if (typeof navigator === 'undefined' || typeof window === 'undefined') return false;
  if (!window.isSecureContext) return false;
  if (!navigator.mediaDevices || typeof navigator.mediaDevices.getUserMedia !== 'function') {
    return false;
  }
  const Ctx = window.AudioContext;
  return typeof Ctx === 'function' && 'audioWorklet' in Ctx.prototype;
}

/**
 * Open the microphone and start delivering 100 ms PCM16 chunks to `onChunk`.
 * Rejects with a MicError naming the reason, never with a bare DOMException.
 */
export async function openMicrophone(onChunk: (chunk: MicChunk) => void): Promise<MicHandle> {
  if (open) throw new MicError('other', 'the microphone is already open');
  if (!microphoneSupported()) {
    throw new MicError(
      'unsupported',
      window.isSecureContext === false
        ? 'insecure context: getUserMedia needs https or localhost'
        : 'getUserMedia or AudioWorklet is not available in this browser',
    );
  }

  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getUserMedia(CONSTRAINTS);
  } catch (error) {
    throw classify(error);
  }

  const track = stream.getAudioTracks()[0];
  if (!track) {
    stream.getTracks().forEach((t) => t.stop());
    throw new MicError('missing', 'the stream carried no audio track');
  }

  // Not { sampleRate: 16000 }: asking the context for 16 kHz makes Chrome
  // resample the device stream itself with an unspecified filter, and Firefox
  // refuses the option on a live input. The worklet owns the resampling so
  // its filter is the one in the measurement.
  const context = new AudioContext();
  try {
    await context.audioWorklet.addModule(WORKLET_URL);
  } catch (error) {
    stream.getTracks().forEach((t) => t.stop());
    await context.close().catch(() => undefined);
    throw new MicError('unsupported', `the audio worklet could not be loaded: ${String(error)}`);
  }
  if (context.state === 'suspended') {
    // A context created outside a user gesture starts suspended in Safari and
    // sometimes Chrome. The click that started the session is that gesture,
    // but the await on the network call between it and here can lose it.
    await context.resume().catch(() => undefined);
  }

  const source = context.createMediaStreamSource(stream);
  const node = new AudioWorkletNode(context, WORKLET_NAME, {
    numberOfInputs: 1,
    numberOfOutputs: 0,
    channelCount: 1,
    channelCountMode: 'explicit',
    channelInterpretation: 'speakers',
  });

  let muted = false;
  let closed = false;

  node.port.onmessage = (event: MessageEvent<{ pcm: ArrayBuffer; peak: number }>) => {
    if (closed || muted) return; // dropped, never queued
    const data = event.data;
    if (data && data.pcm instanceof ArrayBuffer) onChunk({ pcm: data.pcm, peak: data.peak });
  };

  source.connect(node);
  open = true;

  const settings = track.getSettings();
  const granted: MicGranted = {
    sampleRate: typeof settings.sampleRate === 'number' ? settings.sampleRate : null,
    channelCount: typeof settings.channelCount === 'number' ? settings.channelCount : null,
    echoCancellation:
      typeof settings.echoCancellation === 'boolean' ? settings.echoCancellation : null,
    noiseSuppression:
      typeof settings.noiseSuppression === 'boolean' ? settings.noiseSuppression : null,
    autoGainControl: typeof settings.autoGainControl === 'boolean' ? settings.autoGainControl : null,
    deviceLabel: track.label,
    contextSampleRate: context.sampleRate,
  };

  const close = async () => {
    if (closed) return;
    closed = true;
    open = false;
    try {
      node.port.postMessage('stop');
      node.port.onmessage = null;
      source.disconnect();
      node.disconnect();
    } catch {
      /* already torn down */
    }
    stream.getTracks().forEach((t) => t.stop());
    await context.close().catch(() => undefined);
  };

  // The device being unplugged mid-call ends the track; treat it as a close so
  // the session hook sees the chunks stop rather than a silent stream.
  track.addEventListener('ended', () => {
    void close();
  });

  return {
    granted,
    mute() {
      muted = true;
    },
    unmute() {
      muted = false;
    },
    get muted() {
      return muted;
    },
    close,
  };
}
