import { useCallback, useEffect, useRef, useState } from 'react';
import { Download, RefreshCw, CheckCircle2, AlertTriangle } from 'lucide-react';
import { isTauri } from '../../lib/api';

// Direct GitHub WebSockets are unavailable to installed clients; use fast, bounded polling.
const CHECK_EVERY_MS = 15 * 1000;
const DISMISSED_KEY = 'oj-main-update-dismissed-sha';

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
  const updating = useRef(false);
  const checking = useRef(false);
  const [lastCheckedAt, setLastCheckedAt] = useState('');

  const check = useCallback(async () => {
    if (!isTauri() || updating.current || checking.current) return;
    checking.current = true;
    setPhase(prev => prev === 'available' || prev === 'updated' ? prev : 'checking');
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      const result = await invoke<MainSourceStatus>('check_main_update');
      if (updating.current) return;
      setLastCheckedAt(new Date().toLocaleTimeString());
      setStatus(result);
      setError('');
      setPhase(result.update_available ? 'available' : 'idle');
      if (result.update_available) {
        const suppressed = (() => {
          try { return localStorage.getItem(DISMISSED_KEY) === result.latest_sha; } catch { return false; }
        })();
        setDismissed(suppressed);
      } else {
        setDismissed(false);
      }
    } catch (e) {
      const msg = String(e);
      // Only report errors when the user explicitly asks to check or when
      // an update is already visible. Regular offline polling is silent.
      if (!updating.current) {
        setError(msg);
        setPhase(prev => prev === 'available' || prev === 'updated' ? prev : 'idle');
      }
    } finally {
      checking.current = false;
    }
  }, []);

  useEffect(() => {
    if (!isTauri()) return;
    void check();
    const timer = window.setInterval(() => { void check(); }, CHECK_EVERY_MS);
    const onFocusOrOnline = () => { void check(); };
    const onVisibilityChange = () => {
      if (!document.hidden) void check();
    };
    window.addEventListener('focus', onFocusOrOnline);
    window.addEventListener('online', onFocusOrOnline);
    document.addEventListener('visibilitychange', onVisibilityChange);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener('focus', onFocusOrOnline);
      window.removeEventListener('online', onFocusOrOnline);
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }, [check]);

  const update = useCallback(async () => {
    if (!status?.can_update || phase === 'updating') return;
    updating.current = true;
    setPhase('updating');
    setError('');
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      await invoke<string>('apply_main_update', { expectedSha: status.latest_sha });
      setPhase('updated');
      try { localStorage.removeItem(DISMISSED_KEY); } catch { /* private mode */ }
      setStatus(prev => prev ? { ...prev, current_sha: prev.latest_sha, branch: 'main', update_available: false } : prev);
    } catch (e) {
      setError(String(e));
      setPhase('error');
    } finally {
      updating.current = false;
    }
  }, [status, phase]);

  if (!isTauri()) return null;

  const dismiss = () => {
    setDismissed(true);
    if (status?.latest_sha) {
      try { localStorage.setItem(DISMISSED_KEY, status.latest_sha); } catch { /* private mode */ }
    }
  };

  // Compact variant for the settings screen: provides a manual check even
  // when GitHub has no update.
  if (compact) {
    return (
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="inline-flex items-center gap-1.5 font-medium" role="status"
          style={{ color: 'var(--color-text-secondary)' }}>
          <RefreshCw size={12} className={phase === 'checking' ? 'animate-spin' : ''} />
          Ավտոմատ ստուգում՝ յուրաքանչյուր 15 վայրկյանը մեկ
        </span>
        {status?.update_available && (
          <button type="button" onClick={() => void update()} disabled={!status.can_update || phase === 'updating'}
            className="rounded-lg border px-3 py-1.5 flex items-center gap-1.5"
            style={{ borderColor: 'var(--color-accent)', color: 'var(--color-text)' }}>
            <Download size={12} /> {phase === 'updating' ? 'Թարմացվում է...' : 'Թարմացնել / Update'}
          </button>
        )}
        <span style={{ color: 'var(--color-text-tertiary)' }}>
          {status?.branch === 'main' ? 'main' : status?.branch || 'GitHub'} · {status?.current_sha?.slice(0, 7)}
          {status?.update_available ? ` → ${status.latest_sha.slice(0, 7)}` : ''}
        </span>
        {lastCheckedAt && <span style={{ color: 'var(--color-text-tertiary)' }}>Ստուգվել է՝ {lastCheckedAt}</span>}
        {status && <span style={{ color: 'var(--color-text-secondary)' }}>{status.message}</span>}
        {error && <span role="alert" style={{ color: 'var(--color-error)' }}>{error}</span>}
      </div>
    );
  }

  if (dismissed || (phase !== 'available' && phase !== 'updating' && phase !== 'updated' && phase !== 'error')) {
    return null;
  }

  return (
    <div role="alert" aria-live="assertive" className="flex flex-wrap gap-3 items-center justify-between px-5 py-3"
      style={{
        background: 'var(--color-bg-secondary)',
        borderBottom: '2px solid var(--color-accent)',
        boxShadow: '0 4px 14px rgba(0, 0, 0, 0.10)',
      }}>
      <div className="flex gap-2 items-center text-sm">
        {phase === 'updated' ? <CheckCircle2 size={17} /> : <AlertTriangle size={17} />}
        <div>
          <div className="font-semibold">
            {phase === 'updated' ? 'Backend-ը թարմացվեց GitHub main-ից' : 'Նոր թարմացում կա · GitHub main'}
          </div>
          <div className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
            {phase === 'updated'
              ? 'Python backend is restarting. Compiled Desktop UI updates require a separate signed installer.'
              : status
                ? `Նոր commit՝ ${status.latest_sha.slice(0, 7)} (տեղադրված՝ ${status.current_sha.slice(0, 7)}). ${status.can_update ? 'Սեղմիր «Թարմացնել»՝ այն կիրառելու համար։' : status.message}`
                : 'Cannot check for updates'}
          </div>
          {error && <div role="alert" className="text-xs" style={{ color: 'var(--color-error)' }}>{error}</div>}
        </div>
      </div>
      <div className="flex gap-2 items-center">
        {(phase === 'available' || phase === 'error') && status?.update_available && (
          <button type="button" onClick={() => void update()} disabled={!status.can_update}
            className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold"
            style={{ background: 'var(--color-accent)', color: 'var(--color-bg-primary)' }}>
            <Download size={14} /> Թարմացնել / Update
          </button>
        )}
        {phase === 'updating' && <span className="text-xs">Downloading from main and restarting...</span>}
        {phase === 'updated' && <button type="button" onClick={() => void check()} className="text-xs underline">Check again</button>}
        <button type="button" onClick={dismiss} aria-label="Dismiss GitHub update"
          className="px-2 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>Ավելի ուշ</button>
      </div>
    </div>
  );
}
