import { describe, expect, it } from 'vitest';
import { COLIBRI_HOST, colibriInferenceSource, isColibriInferenceSource } from './colibri';

describe('Colibri as a first-class local inference choice', () => {
  it('keeps the source protocol compatible with native custom host persistence', () => {
    expect(colibriInferenceSource('qwen3.6-35b-a3b')).toEqual({
      kind: 'custom', engine: 'colibri', host: COLIBRI_HOST, model: 'qwen3.6-35b-a3b',
    });
  });
  it('prevents selecting a model before the server is ready', () => {
    expect(() => colibriInferenceSource('')).toThrow('not loaded');
  });
  it('preserves Ollama and other custom inference choices', () => {
    expect(isColibriInferenceSource({ kind: 'ollama' })).toBe(false);
    expect(isColibriInferenceSource({ kind: 'custom', engine: 'lmstudio' })).toBe(false);
    expect(isColibriInferenceSource(colibriInferenceSource('qwen36-35b'))).toBe(true);
  });
});
