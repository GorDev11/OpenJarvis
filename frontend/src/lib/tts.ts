import { create } from 'zustand';
import { synthesizeSpeech, fetchTtsHealth } from './api';
import { toSpeakableText } from './message-text';
import { splitSpeechText } from './speech-chunks';

export type TtsState = 'idle' | 'loading' | 'speaking';

/**
 * Voice output is a single shared resource: one utterance at a time, for the
 * whole app. The state lives in one store rather than per component, because a
 * per-component hook would give every message its own audio element -- two
 * replies would then talk over each other, and autoplay would make that the
 * normal case rather than the exception.
 */
interface TtsStore {
  state: TtsState;
  /** id of the message currently loading or speaking, if any. */
  speakingId: string | null;
  error: string | null;
  /** Message whose read-aloud attempt failed, if any. */
  errorId: string | null;
  /** null until the health probe has answered. */
  available: boolean | null;
  /** Active backend name; progressive playback is enabled for Armenian TTS only. */
  backend: string | null;
  /** Last message spoken by autoplay, so a re-render never repeats it. */
  autoSpokenId: string | null;
  speak: (id: string, text: string) => Promise<void>;
  stop: () => void;
  ensureHealth: () => Promise<void>;
  markAutoSpoken: (id: string) => void;
}

// Playback handles are not render state -- keeping them out of the store avoids
// re-rendering every subscriber when an audio element is swapped.
let audio: HTMLAudioElement | null = null;
let objectUrl: string | null = null;
let controller: AbortController | null = null;
let token = 0;
let healthProbe: Promise<void> | null = null;

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
    // Detach first: clearing src re-runs the media load algorithm, which fails
    // on an empty source and dispatches an `error` event. With the handler
    // still attached that surfaces as a bogus "Playback failed" after every
    // successful utterance.
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
  if (controller) {
    controller.abort();
    controller = null;
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

  speak: async (id: string, text: string) => {
    const trimmed = toSpeakableText(text);
    if (!trimmed) return;

    // The original whole-WAV flow is retained for every other TTS backend.
    // Armenian speech plays short WAV segments in order; the next segment
    // is synthesized during the current segment's playback.
    const segments = get().backend === 'armenian_pocket'
      ? splitSpeechText(trimmed)
      : [trimmed];

    token += 1;
    const mine = token;
    teardown();
    set({ state: 'loading', speakingId: id, error: null, errorId: null });

    const ac = new AbortController();
    controller = ac;

    const fail = (err: unknown) => {
      if (mine !== token) return;
      if (err instanceof DOMException && err.name === 'AbortError') return;
      teardown();
      set({
        state: 'idle',
        speakingId: null,
        error: err instanceof Error ? err.message : 'Speech synthesis failed',
        errorId: id,
      });
    };

    const playSegment = async (index: number, prefetched?: Promise<LoadedChunk>): Promise<void> => {
      try {
        const result: LoadedChunk = prefetched
          ? await prefetched
          : { blob: await synthesizeSpeech(segments[index], { signal: ac.signal }) };
        if (mine !== token) return;
        if ('error' in result) throw result.error;

        releaseAudio();
        const url = URL.createObjectURL(result.blob);
        objectUrl = url;
        const el = new Audio(url);
        audio = el;

        // Catch prefetch errors in a settled result: stopping or changing a
        // message must not leave an unhandled rejected promise.
        const next = index + 1 < segments.length
          ? synthesizeSpeech(segments[index + 1], { signal: ac.signal })
              .then<LoadedChunk, LoadedChunk>(
                (blob) => ({ blob }),
                (error) => ({ error }),
              )
          : undefined;

        el.onended = () => {
          if (mine !== token) return;
          if (index + 1 === segments.length) {
            teardown();
            set({ state: 'idle', speakingId: null });
          } else {
            releaseAudio();
            set({ state: 'loading', speakingId: id });
            void playSegment(index + 1, next);
          }
        };
        el.onerror = () => fail(new Error('Playback failed'));

        await el.play();
        if (mine === token) set({ state: 'speaking', speakingId: id });
      } catch (err) {
        fail(err);
      }
    };

    await playSegment(0);
  },

  stop: () => {
    token += 1;
    teardown();
    set({ state: 'idle', speakingId: null, error: null, errorId: null });
  },
}));

/** Test seam: reset module-level playback handles between cases. */
export function __resetTtsForTests(): void {
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
