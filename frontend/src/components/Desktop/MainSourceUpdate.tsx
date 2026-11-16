import { useCallback, useEffect, useState } from 'react';
import { Download, RefreshCw, CheckCircle2, AlertTriangle } from 'lucide-react';
import { isTauri } from '../../lib/api';

const CHECK_EVERY_MS = 10 * 60 * 1000;

export type MainSourceStatus = {
  current_sha: string;
  latest_sha: string;
  branch: string;
  update_available: boolean;
  can_update: boolean;
  message: string;
};

type Phase = 'idle' | 'checking' | 'available' | 'updating' | 'updated' | 'error';

/** Check and apply the user's GorDev11/OpenJarvis main Python backend update.
 * This does not silently install unsigned desktop executables.
 */
export function MainSourceUpdate({ compact = false }: { compact?: boolean }) {
  const [phase, setPhase] = useState<Phase>('idle');
  const [status, setStatus] = useState<MainSourceStatus | null>(null);
  const [error, setError] = useState('');
  const [dismissed, setDismissed] = useState(false);

  const check = useCallback(async () => {
    if (!isTauri()) return;
    setPhase(old => old === 'updating' ? old : 'checking');
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      const result = await invoke<MainSourceStatus>('check_main_update');
      setStatus(result);
      setError('');
      setPhase(result.update_available ? 'available' : 'idle');
      if (result.update_available) setDismissed(false);
    } catch (e) {
      const msg = String(e);
      // Only report errors when the user explicitly asks to check or when
      // an update is already visible. Regular offline polling is silent.
      setError(msg);
      setPhase('idle');
    }
  }, []);

  useEffect(() => {
    if (!isTauri()) return;
    void check();
    const timer = window.setInterval(() => { void check(); }, CHECK_EVERY_MS);
    return () => window.clearInterval(timer);
  }, [check]);

  const update = useCallback(async () => {
    if (!status?.can_update || phase === 'updating') return;
    setPhase('updating');
    setError('');
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      await invoke<string>('apply_main_update', { expectedSha: status.latest_sha });
      setPhase('updated');
      setStatus(prev => prev ? { ...prev, current_sha: prev.latest_sha, branch: 'main', update_available: false } : prev);
    } catch (e) {
      setError(String(e));
      setPhase('error');
    }
  }, [status, phase]);

  if (!isTauri()) return null;

  // Compact variant for the settings screen: provides a manual check even
  // when GitHub has no update.
  if (compact) {
    return (
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <button type="button" onClick={() => void check()} disabled={phase === 'checking' || phase === 'updating'}
          className="rounded-lg border px-3 py-1.5 flex items-center gap-1.5"
          style={{ borderColor: 'var(--color-border)', color: 'var(--color-text)' }}>
          <RefreshCw size={12} className={phase === 'checking' ? 'animate-spin' : ''} />
          Check GitHub main
        </button>
        {status?.update_available && (
          <button type="button" onClick={() => void update()} disabled={!status.can_update || phase === 'updating'}
            className="rounded-lg border px-3 py-1.5 flex items-center gap-1.5"
            style={{ borderColor: 'var(--color-accent)', color: 'var(--color-text)' }}>
            <Download size={12} /> {phase === 'updating' ? 'Updating...' : 'Update'}
          </button>
        )}
        <span style={{ color: 'var(--color-text-tertiary)' }}>
          {status?.branch === 'main' ? 'main' : status?.branch || 'GitHub'} · {status?.current_sha?.slice(0, 7)}
        </span>
        {status && <span style={{ color: 'var(--color-text-secondary)' }}>{status.message}</span>}
        {error && <span role="alert" style={{ color: 'var(--color-error)' }}>{error}</span>}
      </div>
    );
  }

  if (dismissed || (phase !== 'available' && phase !== 'updating' && phase !== 'updated' && phase !== 'error')) {
    return null;
  }

  return (
    <div role="status" className="flex flex-wrap gap-3 items-center justify-between px-5 py-3"
      style={{ background: 'var(--color-bg-secondary)', borderBottom: '1px solid var(--color-border)' }}>
      <div className="flex gap-2 items-center text-sm">
        {phase === 'updated' ? <CheckCircle2 size={17} /> : <AlertTriangle size={17} />}
        <div>
          <div className="font-semibold">
            {phase === 'updated' ? 'Backend source updated from GitHub main' : 'New changes available on GitHub main'}
          </div>
          <div className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
            {phase === 'updated'
              ? 'Python backend is restarting. Compiled Desktop UI updates require a separate signed installer.'
              : status?.message || 'Cannot check for updates'}
          </div>
          {error && <div role="alert" className="text-xs" style={{ color: 'var(--color-error)' }}>{error}</div>}
        </div>
      </div>
      <div className="flex gap-2 items-center">
        {(phase === 'available' || phase === 'error') && status?.update_available && (
          <button type="button" onClick={() => void update()} disabled={!status.can_update}
            className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold"
            style={{ background: 'var(--color-accent)', color: 'var(--color-bg-primary)' }}>
            <Download size={14} /> Update
          </button>
        )}
        {phase === 'updating' && <span className="text-xs">Downloading from main and restarting...</span>}
        {phase === 'updated' && <button type="button" onClick={() => void check()} className="text-xs underline">Check again</button>}
        <button type="button" onClick={() => setDismissed(true)} aria-label="Dismiss GitHub update"
          className="px-2 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>Later</button>
      </div>
    </div>
  );
}
