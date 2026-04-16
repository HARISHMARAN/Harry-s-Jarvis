/**
 * Voice input (Web Speech API) and audio output (AudioContext) for JARVIS.
 */

// ---------------------------------------------------------------------------
// Speech Recognition
// ---------------------------------------------------------------------------

export interface VoiceInput {
  start(): void;
  stop(): void;
  pause(): void;
  resume(): void;
}

export interface VoiceDiagnostics {
  supported: boolean;
  secureContext: boolean;
  permissionState: "granted" | "denied" | "prompt" | "unknown";
  audioInputCount: number | null;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
declare const webkitSpeechRecognition: any;

export function createVoiceInput(
  onTranscript: (text: string) => void,
  onError: (msg: string) => void
): VoiceInput {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const SR = (window as any).SpeechRecognition || (typeof webkitSpeechRecognition !== "undefined" ? webkitSpeechRecognition : null);
  if (!SR) {
    onError("Speech recognition not supported in this browser");
    return { start() {}, stop() {}, pause() {}, resume() {} };
  }

  const recognition = new SR();
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.maxAlternatives = 1;
  recognition.lang = "en-US";

  let shouldListen = false;
  let paused = false;
  let restartTimer: number | null = null;

  function scheduleRestart() {
    if (!shouldListen || paused) return;
    if (restartTimer !== null) window.clearTimeout(restartTimer);
    restartTimer = window.setTimeout(() => {
      restartTimer = null;
      if (!shouldListen || paused) return;
      try {
        recognition.start();
      } catch {
        // Chrome throws if recognition is already running or starting.
      }
    }, 250);
  }

  recognition.onstart = () => {
    console.log("[voice] recognition started");
  };

  recognition.onspeechstart = () => {
    console.log("[voice] speech detected");
  };

  recognition.onspeechend = () => {
    console.log("[voice] speech ended");
  };

  recognition.onresult = (event: any) => {
    for (let i = event.resultIndex; i < event.results.length; i++) {
      if (event.results[i].isFinal) {
        const text = event.results[i][0].transcript.trim();
        if (text) onTranscript(text);
      }
    }
  };

  recognition.onend = () => {
    scheduleRestart();
  };

  recognition.onerror = (event: any) => {
    const errorCode = event?.error ?? event?.message ?? event?.type ?? "unknown";
    const details = {
      error: event?.error ?? null,
      message: event?.message ?? null,
      type: event?.type ?? null,
      target: event?.target ? "[SpeechRecognition]" : null,
      secureContext: window.isSecureContext,
      supported: Boolean(SR),
    };
    console.warn(`[voice] recognition error event: ${errorCode}`, details);

    if (errorCode === "not-allowed") {
      onError("Microphone access denied. Please allow microphone access.");
      paused = true;
    } else if (errorCode === "no-speech") {
      scheduleRestart();
    } else if (errorCode === "aborted") {
      scheduleRestart();
    } else if (errorCode === "audio-capture") {
      onError("No microphone found. Check your input device.");
    } else if (errorCode === "network") {
      onError("Speech recognition network error. Check your connection.");
      scheduleRestart();
    } else if (errorCode === "service-not-allowed") {
      onError("Speech recognition blocked by the browser.");
    } else {
      onError(`Speech recognition error: ${String(errorCode)}`);
      scheduleRestart();
    }
  };

  return {
    start() {
      shouldListen = true;
      paused = false;
      try {
        recognition.start();
      } catch {
        // Chrome throws if recognition is already running or starting.
      }
    },
    stop() {
      shouldListen = false;
      paused = false;
      if (restartTimer !== null) {
        window.clearTimeout(restartTimer);
        restartTimer = null;
      }
      recognition.stop();
    },
    pause() {
      paused = true;
      if (restartTimer !== null) {
        window.clearTimeout(restartTimer);
        restartTimer = null;
      }
      recognition.stop();
    },
    resume() {
      paused = false;
      if (shouldListen) {
        try {
          recognition.start();
        } catch {
          // Already started
        }
      }
    },
  };
}

export async function diagnoseVoiceInput(): Promise<VoiceDiagnostics> {
  const supported = Boolean((window as any).SpeechRecognition || (typeof webkitSpeechRecognition !== "undefined"));
  let permissionState: VoiceDiagnostics["permissionState"] = "unknown";

  try {
    if (navigator.permissions?.query) {
      const status = await navigator.permissions.query({ name: "microphone" as PermissionName });
      permissionState = status.state as VoiceDiagnostics["permissionState"];
    }
  } catch {
    permissionState = "unknown";
  }

  let audioInputCount: number | null = null;
  try {
    if (navigator.mediaDevices?.enumerateDevices) {
      const devices = await navigator.mediaDevices.enumerateDevices();
      audioInputCount = devices.filter((d) => d.kind === "audioinput").length;
    }
  } catch {
    audioInputCount = null;
  }

  return {
    supported,
    secureContext: window.isSecureContext,
    permissionState,
    audioInputCount,
  };
}

// ---------------------------------------------------------------------------
// Audio Player
// ---------------------------------------------------------------------------

export interface AudioPlayer {
  enqueue(base64: string): Promise<void>;
  stop(): void;
  getAnalyser(): AnalyserNode;
  onFinished(cb: () => void): void;
}

export function createAudioPlayer(): AudioPlayer {
  const audioCtx = new AudioContext();
  const analyser = audioCtx.createAnalyser();
  analyser.fftSize = 256;
  analyser.smoothingTimeConstant = 0.8;
  analyser.connect(audioCtx.destination);

  const queue: AudioBuffer[] = [];
  let isPlaying = false;
  let currentSource: AudioBufferSourceNode | null = null;
  let finishedCallback: (() => void) | null = null;

  function playNext() {
    if (queue.length === 0) {
      isPlaying = false;
      currentSource = null;
      finishedCallback?.();
      return;
    }

    isPlaying = true;
    const buffer = queue.shift()!;
    const source = audioCtx.createBufferSource();
    source.buffer = buffer;
    source.connect(analyser);
    currentSource = source;

    source.onended = () => {
      if (currentSource === source) {
        playNext();
      }
    };

    source.start();
  }

  return {
    async enqueue(base64: string) {
      // Resume audio context (browser autoplay policy)
      if (audioCtx.state === "suspended") {
        await audioCtx.resume();
      }

      try {
        const binary = atob(base64);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) {
          bytes[i] = binary.charCodeAt(i);
        }
        const audioBuffer = await audioCtx.decodeAudioData(bytes.buffer.slice(0));
        queue.push(audioBuffer);
        if (!isPlaying) playNext();
      } catch (err) {
        console.error("[audio] decode error:", err);
        // Skip bad audio, continue
        if (!isPlaying && queue.length > 0) playNext();
      }
    },

    stop() {
      queue.length = 0;
      if (currentSource) {
        try {
          currentSource.stop();
        } catch {
          // Already stopped
        }
        currentSource = null;
      }
      isPlaying = false;
    },

    getAnalyser() {
      return analyser;
    },

    onFinished(cb: () => void) {
      finishedCallback = cb;
    },
  };
}
