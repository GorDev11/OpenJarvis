import type { InferenceSource } from './api';

export const COLIBRI_HOST = 'http://127.0.0.1:19000';
export const COLIBRI_DOWNLOAD_GB = 23.1;

export function colibriInferenceSource(model: string): InferenceSource {
  const selected = model.trim();
  if (!selected) throw new Error('Colibri Qwen3.6 model is not loaded. Install or start Colibri first.');
  return { kind: 'custom', engine: 'colibri', host: COLIBRI_HOST, model: selected };
}

export function isColibriInferenceSource(source: InferenceSource): boolean {
  return source.kind === 'custom' && source.engine === 'colibri';
}
