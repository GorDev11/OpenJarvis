import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  isAutoUpdateDisabled,
  setAutoUpdateDisabled,
} from './UpdateChecker';

describe('signed desktop auto-install preferences', () => {
  const values = new Map<string, string>();
  const dispatch = vi.fn();
  beforeEach(() => {
    values.clear();
    dispatch.mockClear();
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => { values.set(key, value); },
    });
    vi.stubGlobal('window', { dispatchEvent: dispatch });
    vi.stubGlobal('Event', class {
      constructor(public readonly type: string) {}
    });
  });

  afterEach(() => { vi.unstubAllGlobals(); });

  it('requires explicit consent before enabling automatic installation', () => {
    expect(isAutoUpdateDisabled()).toBe(true);
    setAutoUpdateDisabled(false);
    expect(isAutoUpdateDisabled()).toBe(false);
    setAutoUpdateDisabled(true);
    expect(isAutoUpdateDisabled()).toBe(true);
  });

  it('notifies a mounted updater immediately when the preference changes', () => {
    setAutoUpdateDisabled(false);
    expect(dispatch).toHaveBeenCalledTimes(1);
    expect(dispatch.mock.calls[0][0]).toMatchObject({
      type: 'openjarvis-auto-install-setting-changed',
    });
  });
});
