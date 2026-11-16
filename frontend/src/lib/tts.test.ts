import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('./api', () => ({
  synthesizeSpeech: vi.fn(),
  fetchTtsHealth: vi.fn(),
}));

import { synthesizeSpeech, fetchTtsHealth } from './api';
import { useTtsStore, __resetTtsForTests, shouldAutoplayFinishedReply } from './tts';
import { splitSpeechText } from './speech-chunks';

const synth = vi.mocked(synthesizeSpeech);
const health = vi.mocked(fetchTtsHealth);

/** Minimal HTMLAudioElement stand-in; jsdom cannot decode or play real audio. */
class FakeAudio {
  static instances: FakeAudio[] = [];
  onended: (() => void) | null = null;
  onerror: (() => void) | null = null;
  src: string;
  paused = false;
  playCalls = 0;

  constructor(src: string) {
    this.src = src;
    FakeAudio.instances.push(this);
  }

  play(): Promise<void> {
    this.playCalls += 1;
    return Promise.resolve();
  }

  pause(): void {
    this.paused = true;
  }
}

const created: string[] = [];
const revoked: string[] = [];
let urlCounter = 0;

beforeEach(() => {
  vi.stubGlobal('Audio', FakeAudio as unknown as typeof Audio);
  vi.stubGlobal('URL', {
    createObjectURL: () => {
      const url = `blob:fake/${++urlCounter}`;
      created.push(url);
      return url;
    },
    revokeObjectURL: (url: string) => {
      revoked.push(url);
    },
  });

  synth.mockReset();
  health.mockReset();

  // Reset the store first: it tears down whatever the previous test left
  // playing, and that teardown revokes a URL. Clearing the ledgers afterwards
  // keeps that bookkeeping out of this test's assertions.
  __resetTtsForTests();
  FakeAudio.instances = [];
  created.length = 0;
  revoked.length = 0;
  urlCounter = 0;
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe('shared voice output', () => {
  it('plays one utterance and reports which message owns it', async () => {
    synth.mockResolvedValue(new Blob(['wav']));

    await useTtsStore.getState().speak('m1', 'Hallo');

    expect(FakeAudio.instances).toHaveLength(1);
    expect(FakeAudio.instances[0].playCalls).toBe(1);
    expect(useTtsStore.getState().state).toBe('speaking');
    expect(useTtsStore.getState().speakingId).toBe('m1');
  });

  it('starting a second message stops the first instead of overlapping it', async () => {
    synth.mockResolvedValue(new Blob(['wav']));

    await useTtsStore.getState().speak('m1', 'Erste');
    const first = FakeAudio.instances[0];

    await useTtsStore.getState().speak('m2', 'Zweite');

    expect(first.paused).toBe(true);
    expect(useTtsStore.getState().speakingId).toBe('m2');
    expect(revoked).toContain(created[0]);
  });

  it('starts Armenian playback after the first WAV while prefetching the next', async () => {
    useTtsStore.setState({ backend: 'armenian_pocket' });
    const first = deferred<Blob>();
    const second = deferred<Blob>();
    synth.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    // Exactly two chunks: the mock only prepares two audio responses.
    // Using a much longer reply accidentally triggered a third mock call
    // with no return value, preventing the second audio.play() from running.
    const text = Array(8).fill('Բարև, ես Ջարվիսն եմ։').join(' ');
    expect(splitSpeechText(text)).toHaveLength(2);

    const playing = useTtsStore.getState().speak('m1', text);
    expect(synth).toHaveBeenCalledTimes(1);
    first.resolve(new Blob(['first']));
    await playing;

    expect(FakeAudio.instances).toHaveLength(1);
    expect(FakeAudio.instances[0].playCalls).toBe(1);
    expect(synth).toHaveBeenCalledTimes(2);

    second.resolve(new Blob(['second']));
    await Promise.resolve();
    FakeAudio.instances[0].onended?.();

    await vi.waitFor(() => {
      expect(FakeAudio.instances).toHaveLength(2);
      // The audio element may be constructed before its async play() begins.
      expect(FakeAudio.instances[1].playCalls).toBe(1);
    });
    expect(useTtsStore.getState().speakingId).toBe('m1');

    FakeAudio.instances[1].onended?.();
    expect(useTtsStore.getState().state).toBe('idle');
    expect(useTtsStore.getState().error).toBeNull();
  });

  it('stopping during a prefetched segment prevents further playback', async () => {
    useTtsStore.setState({ backend: 'armenian_pocket' });
    const next = deferred<Blob>();
    synth.mockResolvedValueOnce(new Blob(['first']));
    synth.mockReturnValueOnce(next.promise);

    await useTtsStore.getState().speak(
      'm1', Array(30).fill('Հայերեն արագ ձայն։').join(' '),
    );
    expect(synth).toHaveBeenCalledTimes(2);

    const nextSignal = synth.mock.calls[1][1]?.signal as AbortSignal;
    useTtsStore.getState().stop();
    expect(nextSignal.aborted).toBe(true);

    next.resolve(new Blob(['late']));
    await Promise.resolve();
    expect(FakeAudio.instances).toHaveLength(1);
    expect(useTtsStore.getState().state).toBe('idle');
  });

  it('aborts a synthesis that is superseded before it resolves', async () => {
    const pending = deferred<Blob>();
    synth.mockReturnValueOnce(pending.promise);
    synth.mockResolvedValueOnce(new Blob(['wav']));

    const firstCall = useTtsStore.getState().speak('m1', 'Erste');
    const signal = synth.mock.calls[0][1]?.signal as AbortSignal;
    expect(signal.aborted).toBe(false);

    await useTtsStore.getState().speak('m2', 'Zweite');
    expect(signal.aborted).toBe(true);

    // The stale response must not start playback or leak its blob URL.
    pending.resolve(new Blob(['stale']));
    await firstCall;

    expect(FakeAudio.instances).toHaveLength(1);
    expect(useTtsStore.getState().speakingId).toBe('m2');
  });

  it('stop() halts playback and revokes the blob URL', async () => {
    synth.mockResolvedValue(new Blob(['wav']));

    await useTtsStore.getState().speak('m1', 'Hallo');
    useTtsStore.getState().stop();

    expect(FakeAudio.instances[0].paused).toBe(true);
    expect(revoked).toEqual(created);
    expect(useTtsStore.getState().state).toBe('idle');
    expect(useTtsStore.getState().speakingId).toBeNull();
  });

  it('finishing playback leaves no error behind', async () => {
    synth.mockResolvedValue(new Blob(['wav']));

    await useTtsStore.getState().speak('m1', 'Hallo');
    const el = FakeAudio.instances[0];

    el.onended?.();
    // Clearing src fires a media error; the handler must already be detached.
    el.onerror?.();

    expect(useTtsStore.getState().error).toBeNull();
    expect(useTtsStore.getState().state).toBe('idle');
    expect(revoked).toEqual(created);
  });

  it('surfaces a synthesis failure', async () => {
    synth.mockRejectedValue(new Error('No text-to-speech backend available'));

    await useTtsStore.getState().speak('m1', 'Hallo');

    expect(useTtsStore.getState().error).toBe('No text-to-speech backend available');
    expect(useTtsStore.getState().errorId).toBe('m1');
    expect(useTtsStore.getState().state).toBe('idle');
  });

  it('ignores empty text', async () => {
    await useTtsStore.getState().speak('m1', '   ');
    expect(synth).not.toHaveBeenCalled();
  });

  it('probes the backend once no matter how many callers ask', () => {
    health.mockResolvedValue({ available: true });

    useTtsStore.getState().ensureHealth();
    useTtsStore.getState().ensureHealth();
    useTtsStore.getState().ensureHealth();

    expect(health).toHaveBeenCalledTimes(1);
  });

  it('shares a pending health probe so autoplay can wait for model loading', async () => {
    const pending = deferred<{ available: boolean }>();
    health.mockReturnValue(pending.promise);

    const first = useTtsStore.getState().ensureHealth();
    const second = useTtsStore.getState().ensureHealth();
    expect(second).toBe(first);
    expect(health).toHaveBeenCalledTimes(1);

    pending.resolve({ available: true });
    await first;
    expect(useTtsStore.getState().available).toBe(true);
  });

  it('retries health after an unavailable response', async () => {
    health.mockResolvedValueOnce({ available: false });
    health.mockResolvedValueOnce({ available: true });

    await useTtsStore.getState().ensureHealth();
    expect(useTtsStore.getState().available).toBe(false);
    await useTtsStore.getState().ensureHealth();

    expect(health).toHaveBeenCalledTimes(2);
    expect(useTtsStore.getState().available).toBe(true);
  });

  it('retries health after a network error', async () => {
    health.mockRejectedValueOnce(new Error('offline'));
    health.mockResolvedValueOnce({ available: true });

    await useTtsStore.getState().ensureHealth();
    expect(useTtsStore.getState().available).toBe(false);
    await useTtsStore.getState().ensureHealth();

    expect(health).toHaveBeenCalledTimes(2);
    expect(useTtsStore.getState().available).toBe(true);
  });
});

describe('live sentence playback before completion', () => {
  it('starts the first sentence before the full response is available', async () => {
    useTtsStore.setState({ backend: 'armenian_pocket' });
    const first = deferred<Blob>();
    const second = deferred<Blob>();
    synth.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const store = useTtsStore.getState();
    store.beginLive('live');
    const started = store.appendLive('live', 'Բարև։');
    expect(synth).toHaveBeenCalledTimes(1);
    first.resolve(new Blob(['first']));
    await started;
    expect(FakeAudio.instances).toHaveLength(1);
    expect(useTtsStore.getState().state).toBe('speaking');

    // The stream is still open, yet the next sentence may already be prepared.
    void store.appendLive('live', 'Այսօր կարող եմ օգնել։');
    expect(synth).toHaveBeenCalledTimes(2);
    second.resolve(new Blob(['second']));
    await Promise.resolve();
    store.finishLive('live');
    FakeAudio.instances[0].onended?.();
    await vi.waitFor(() => expect(FakeAudio.instances).toHaveLength(2));
    expect(FakeAudio.instances[1].playCalls).toBe(1);
    FakeAudio.instances[1].onended?.();
    expect(useTtsStore.getState().state).toBe('idle');
  });

  it('waits for new sentences rather than ending an open live stream', async () => {
    synth.mockResolvedValue(new Blob(['one']));
    const store = useTtsStore.getState();
    store.beginLive('live');
    await store.appendLive('live', 'Բարև։');
    FakeAudio.instances[0].onended?.();
    expect(useTtsStore.getState().speakingId).toBe('live');
    expect(synth).toHaveBeenCalledTimes(1);
    await store.appendLive('live', 'Շարունակությունը։');
    expect(FakeAudio.instances).toHaveLength(2);
    store.finishLive('live');
    FakeAudio.instances[1].onended?.();
    expect(useTtsStore.getState().state).toBe('idle');
  });

  it('stops all queued live audio when cancelled', async () => {
    const first = deferred<Blob>();
    synth.mockReturnValueOnce(first.promise);
    const store = useTtsStore.getState();
    store.beginLive('live');
    const job = store.appendLive('live', 'Բարև։');
    const signal = synth.mock.calls[0][1]?.signal as AbortSignal;
    store.stop();
    expect(signal.aborted).toBe(true);
    first.resolve(new Blob(['late']));
    await job;
    expect(FakeAudio.instances).toHaveLength(0);
    expect(useTtsStore.getState().state).toBe('idle');
  });

  it('ignores old stream chunks after switching sessions', async () => {
    synth.mockResolvedValue(new Blob(['wav']));
    const store = useTtsStore.getState();
    store.beginLive('first');
    await store.appendLive('first', 'Հին պատասխան։');
    const oldAudio = FakeAudio.instances[0];
    store.beginLive('second');
    expect(oldAudio.paused).toBe(true);
    await store.appendLive('first', 'Սա չպետք է հնչի։');
    await store.appendLive('second', 'Նոր պատասխան։');
    expect(FakeAudio.instances).toHaveLength(2);
    expect(useTtsStore.getState().speakingId).toBe('second');
  });
});

describe('autoplay gating', () => {
  it('stays silent when a finished conversation is merely restored', () => {
    expect(
      shouldAutoplayFinishedReply(null, 'chat-1', false, { role: 'assistant', id: 'old' }, null),
    ).toBe(false);
  });

  it('speaks when a stream finishes', () => {
    expect(
      shouldAutoplayFinishedReply('chat-1', 'chat-1', false, { role: 'assistant', id: 'fresh' }, null),
    ).toBe(true);
  });

  it('stays silent while the reply is still streaming', () => {
    expect(
      shouldAutoplayFinishedReply('chat-1', 'chat-1', true, { role: 'assistant', id: 'fresh' }, null),
    ).toBe(false);
  });

  it('never repeats a message it already spoke', () => {
    expect(
      shouldAutoplayFinishedReply('chat-1', 'chat-1', false, { role: 'assistant', id: 'fresh' }, 'fresh'),
    ).toBe(false);
  });

  it('ignores a trailing user message', () => {
    expect(
      shouldAutoplayFinishedReply('chat-1', 'chat-1', false, { role: 'user', id: 'u1' }, null),
    ).toBe(false);
  });

  it('does not speak an old reply when the user switches conversations mid-stream', () => {
    expect(
      shouldAutoplayFinishedReply('chat-1', 'chat-2', true, { role: 'assistant', id: 'old' }, null),
    ).toBe(false);
  });
});
