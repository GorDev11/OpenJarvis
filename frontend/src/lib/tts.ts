import { create } from 'zustand';
import { synthesizeSpeech, fetchTtsHealth } from './api';
import { toSpeakableText } from './message-text';
import { splitSpeechText } from './speech-chunks';

export type TtsState = 'idle' | 'loading' | 'speaking';

/** Single shared voice output for chat, including early streaming segments. */
interface TtsStore {
  state: TtsState;
  speakingId: string | null;
  error: string | null;
  errorId: string | null;
  available: boolean | null;
  backend: string | null;
  autoSpokenId: string | null;
  speak: (id: string, text: string) => Promise<void>;
  stop: () => void;
  ensureHealth: () => Promise<void>;
  markAutoSpoken: (id: string) => void;
  /** Start a streaming reply; enqueue only complete sentences. */
  beginLive: (id: string) => void;
  appendLive: (id: string, segment: string) => Promise<void>;
  /** Flush the last segment, then finish when queued WAVs have played. */
  finishLive: (id: string) => void;
}

let audio: HTMLAudioElement | null = null;
let objectUrl: string | null = null;
let controller: AbortController | null = null;
let token = 0;
let healthProbe: Promise<void> | null = null;
let sessionId: string | null = null;
let liveOpen = false;
let queue: string[] = [];
let queueIndex = 0;
let busy = false; // includes first synthesis and audio playback
let prefetch: Promise<LoadedChunk> | null = null;
let prefetchIndex = -1;

type LoadedChunk = { blob: Blob } | { error: unknown };

/** Only a stream ending in the active conversation may trigger autoplay. */
export function shouldAutoplayFinishedReply(
  previousStreamingConversationId: string | null,
  activeId: string | null,
  streamIsActive: boolean,
  lastMessage: { id: string; role: string } | undefined,
  autoSpokenId: string | null,
): boolean {
  return previousStreamingConversationId !== null
    && previousStreamingConversationId === activeId
    && !streamIsActive
    && lastMessage !== undefined
    && lastMessage.role === 'assistant'
    && lastMessage.id !== autoSpokenId;
}

function releaseAudio(): void {
  if (audio) {
    audio.onended = null;
    audio.onerror = null;
    audio.pause();
    audio.src = '';
    audio = null;
  }
  if (objectUrl) {
    URL.revokeObjectURL(objectUrl);
    objectUrl = null;
  }
}

function teardown(): void {
  releaseAudio();
  controller?.abort();
  controller = null;
  sessionId = null;
  queue = [];
  queueIndex = 0;
  busy = false;
  liveOpen = false;
  prefetch = null;
  prefetchIndex = -1;
}

function finishSession(): void {
  teardown();
  useTtsStore.setState({ state: 'idle', speakingId: null });
}

function failSession(err: unknown, id: string, mine: number): void {
  if (mine !== token) return;
  if (typeof DOMException !== 'undefined' && err instanceof DOMException && err.name === 'AbortError') return;
  teardown();
  useTtsStore.setState({
    state: 'idle',
    speakingId: null,
    error: err instanceof Error ? err.message : 'Speech synthesis failed',
    errorId: id,
  });
}

/** Prepare only the immediate next chunk while the current WAV is playing. */
function maybePrefetch(): void {
  if (!sessionId || !controller || !audio || prefetch || queueIndex + 1 >= queue.length) return;
  const idx = queueIndex + 1;
  prefetchIndex = idx;
  prefetch = synthesizeSpeech(queue[idx], { signal: controller.signal })
    .then<LoadedChunk, LoadedChunk>(
      (blob) => ({ blob }),
      (error) => ({ error }),
    );
}

/** Returns once the current chunk starts playing, not when playback ends. */
async function playCurrent(): Promise<void> {
  if (!sessionId || !controller || busy) return;
  if (queueIndex >= queue.length) {
    if (!liveOpen) finishSession();
    return;
  }
  busy = true;
  const mine = token;
  const id = sessionId;
  const idx = queueIndex;
  const ac = controller;
  const ready = prefetch && prefetchIndex === idx
    ? prefetch
    : synthesizeSpeech(queue[idx], { signal: ac.signal })
        .then<LoadedChunk, LoadedChunk>((blob) => ({ blob }), (error) => ({ error }));
  prefetch = null;
  prefetchIndex = -1;
  try {
    const result = await ready;
    if (mine !== token) return;
    if ('error' in result) throw result.error;
    releaseAudio();
    objectUrl = URL.createObjectURL(result.blob);
    const el = new Audio(objectUrl);
    audio = el;

    el.onended = () => {
      if (mine !== token) return;
      releaseAudio();
      queueIndex += 1;
      busy = false;
      useTtsStore.setState({ state: 'loading', speakingId: id });
      void playCurrent();
    };
    el.onerror = () => failSession(new Error('Playback failed'), id, mine);
    await el.play();
    if (mine !== token) return;
    useTtsStore.setState({ state: 'speaking', speakingId: id });
    maybePrefetch();
  } catch (err) {
    failSession(err, id, mine);
  }
}

export const useTtsStore = create<TtsStore>((set, get) => ({
  state: 'idle',
  speakingId: null,
  error: null,
  errorId: null,
  available: null,
  backend: null,
  autoSpokenId: null,

  ensureHealth: () => {
    if (healthProbe) return healthProbe;
    healthProbe = fetchTtsHealth()
      .then((health) => {
        set({ available: health.available, backend: health.available ? (health.backend ?? null) : null });
        if (!health.available) healthProbe = null;
      })
      .catch(() => {
        set({ available: false, backend: null });
        healthProbe = null;
      });
    return healthProbe;
  },

  markAutoSpoken: (id: string) => set({ autoSpokenId: id }),

  beginLive: (id: string) => {
    token += 1;
    teardown();
    sessionId = id;
    liveOpen = true;
    controller = new AbortController();
    set({ state: 'loading', speakingId: id, error: null, errorId: null });
  },

  appendLive: (id: string, segment: string) => {
    if (sessionId !== id || !liveOpen) return Promise.resolve();
    const clean = toSpeakableText(segment);
    if (!clean) return Promise.resolve();
    queue.push(clean);
    if (busy) {
      maybePrefetch();
      return Promise.resolve();
    }
    return playCurrent();
  },

  finishLive: (id: string) => {
    if (sessionId !== id) return;
    liveOpen = false;
    if (!busy) void playCurrent();
  },

  speak: async (id: string, text: string) => {
    const trimmed = toSpeakableText(text);
    if (!trimmed) return;
    get().beginLive(id);
    const segments = get().backend === 'armenian_pocket'
      ? splitSpeechText(trimmed)
      : [trimmed];
    let first: Promise<void> = Promise.resolve();
    segments.forEach((part, i) => {
      const job = get().appendLive(id, part);
      if (i === 0) first = job;
    });
    get().finishLive(id);
    await first;
  },

  stop: () => {
    token += 1;
    teardown();
    set({ state: 'idle', speakingId: null, error: null, errorId: null });
  },
}));

/** Test seam: reset playback handles between cases. */
export function __resetTtsForTests(): void {
  token += 1;
  teardown();
  token = 0;
  healthProbe = null;
  useTtsStore.setState({
    state: 'idle',
    speakingId: null,
    error: null,
    errorId: null,
    available: null,
    backend: null,
    autoSpokenId: null,
  });
}
