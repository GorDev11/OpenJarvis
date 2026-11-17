import { describe, expect, it, vi } from 'vitest';
import type { ModelInfo } from '../types';

// These are store transition tests. No Tauri, browser or model server needed.
const storage = new Map<string, string>();
vi.stubGlobal('localStorage', {
  getItem: (key: string) => storage.get(key) ?? null,
  setItem: (key: string, value: string) => { storage.set(key, value); },
  removeItem: (key: string) => { storage.delete(key); },
  clear: () => { storage.clear(); },
});

describe('model catalog changes and explicit selection', () => {
  it('does not treat an automatic fallback as a manual model switch', async () => {
    const { useAppStore } = await import('./store');
    const initialStream = useAppStore.getState().streamState;
    try {
      useAppStore.setState({
        selectedModel: '',
        modelSelectionEpoch: 0,
        models: [],
        streamState: { ...initialStream, isStreaming: true },
      });
      const colibri = { id: 'qwen3.6-colibri' } as ModelInfo;
      const other = { id: 'qwen3-vl:8b-instruct' } as ModelInfo;

      useAppStore.getState().setModels([colibri]);
      expect(useAppStore.getState().selectedModel).toBe(colibri.id);
      expect(useAppStore.getState().modelSelectionEpoch).toBe(0);

      // Transient model discovery update during a live answer. The selected
      // model can change, but the intentional-selection epoch must not.
      useAppStore.getState().setModels([other]);
      expect(useAppStore.getState().selectedModel).toBe(other.id);
      expect(useAppStore.getState().modelSelectionEpoch).toBe(0);
      expect(useAppStore.getState().streamState.isStreaming).toBe(true);

      // Re-selecting the same model is not a switch.
      useAppStore.getState().setSelectedModel(other.id);
      expect(useAppStore.getState().modelSelectionEpoch).toBe(0);

      // An actual user selection increments the epoch exactly once.
      useAppStore.getState().setSelectedModel(colibri.id);
      expect(useAppStore.getState().modelSelectionEpoch).toBe(1);
      useAppStore.getState().setSelectedModel(colibri.id);
      expect(useAppStore.getState().modelSelectionEpoch).toBe(1);
    } finally {
      useAppStore.setState({
        selectedModel: '',
        modelSelectionEpoch: 0,
        models: [],
        streamState: initialStream,
      });
    }
  });
});
