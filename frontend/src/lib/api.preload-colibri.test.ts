import { afterEach, describe, expect, it, vi } from 'vitest';
import { preloadModel } from './api';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('model preloading', () => {
  it('never sends the Colibri model to the Ollama server', async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
    // The model list may omit owned_by in a mixed-engine backend.
    await preloadModel('qwen3.6-colibri');
    await preloadModel('other-colibri-model', 'colibri');
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('keeps the existing Ollama preload path for actual Ollama models', async () => {
    const fetchSpy = vi.fn().mockResolvedValue(new Response('', { status: 200 }));
    vi.stubGlobal('fetch', fetchSpy);
    await preloadModel('qwen3-vl:8b-instruct', 'ollama');
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(fetchSpy.mock.calls[0][0]).toBe('http://127.0.0.1:11434/api/generate');
    const body = JSON.parse(fetchSpy.mock.calls[0][1].body);
    expect(body.model).toBe('qwen3-vl:8b-instruct');
  });
});
