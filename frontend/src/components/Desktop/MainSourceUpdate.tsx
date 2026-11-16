import { useCallback, useEffect, useRef, useState } from 'react';
import { Download, RefreshCw, CheckCircle2, AlertTriangle, LoaderCircle, X } from 'lucide-react';
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

type Phase = 'idle' | 'checking' | 'available' | 'updating' | 'restarting' | 'updated' | 'error';

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

  useEffect(() => {
    if (!isTauri()) return;
    const onReady = () => {
      if (!updating.current) return;
      updating.current = false;
      setPhase(prev => prev === 'updating' || prev === 'restarting' ? 'updated' : prev);
    };
    const onTimeout = () => {
      if (!updating.current) return;
      updating.current = false;
      setError('Backend-ի վերագործարկումը երկար է տևում։ Ստուգիր կապը կամ Logs-ը։');
      setPhase('error');
    };
    window.addEventListener('openjarvis-backend-ready', onReady);
    window.addEventListener('openjarvis-backend-timeout', onTimeout);
    return () => {
      window.removeEventListener('openjarvis-backend-ready', onReady);
      window.removeEventListener('openjarvis-backend-timeout', onTimeout);
    };
  }, []);

  useEffect(() => {
    if (phase !== 'updated') return;
    const timer = window.setTimeout(() => setDismissed(true), 8000);
    return () => window.clearTimeout(timer);
  }, [phase]);

  const update = useCallback(async () => {
    if (!status?.can_update || updating.current) return;
    updating.current = true;
    setDismissed(false);
    setPhase('updating');
    setError('');
    window.dispatchEvent(new CustomEvent('openjarvis-backend-update', { detail: 'updating' }));
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      await invoke<string>('apply_main_update', { expectedSha: status.latest_sha });
      try { localStorage.removeItem(DISMISSED_KEY); } catch { /* private mode */ }
      setStatus(prev => prev ? { ...prev, current_sha: prev.latest_sha, branch: 'main', update_available: false } : prev);
      setPhase('restarting');
    } catch (e) {
      setError(String(e));
      setPhase('error');
    } finally {
      // Native apply can return before the managed Python backend is healthy.
      window.dispatchEvent(new CustomEvent('openjarvis-backend-update', { detail: 'waiting' }));
    }
  }, [status]);

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
          <button type="button" onClick={() => void update()} disabled={!status.can_update || updating.current}
            className="rounded-lg border px-3 py-1.5 flex items-center gap-1.5"
            style={{ borderColor: 'var(--color-accent)', color: 'var(--color-text)' }}>
            <Download size={12} /> {phase === 'updating' || phase === 'restarting' ? 'Թարմացվում է...' : 'Թարմացնել / Update'}
          </button>
        )}
        <span style={{ color: 'var(--color-text-tertiary)' }}>
          {status?.branch === 'main' ? 'main' : status?.branch || 'GitHub'} · {status?.current_sha?.slice(0, 7)}
          {status?.update_available ? ` → ${status.latest_sha.slice(0, 7)}` : ''}
        </span>
        {lastCheckedAt && <span style={{ color: 'var(--color-text-tertiary)' }}>Ստուգվել է՝ {lastCheckedAt}</span>}
        {status && <span style={{ color: 'var(--color-text-secondary)' }}>{status.message}</span>}
        {(phase === 'updating' || phase === 'restarting') && <span>Backend-ը վերագործարկվում է...</span>}
        {error && <span role="alert" style={{ color: 'var(--color-error)' }}>{error}</span>}
      </div>
    );
  }

  if (dismissed || (phase !== 'available' && phase !== 'updating' && phase !== 'restarting' && phase !== 'updated' && phase !== 'error')) {
    return null;
  }

  return (
    <div className="pointer-events-none flex shrink-0 justify-center px-3 pt-2 pb-1">
      <div
        role="status"
        aria-live="polite"
        className="pointer-events-auto flex w-full max-w-[520px] items-start gap-3 rounded-2xl border px-3 py-3 shadow-lg"
        style={{
          background: 'var(--color-surface)',
          borderColor: 'var(--color-border)',
          boxShadow: '0 8px 24px rgba(0, 0, 0, 0.10)',
        }}
      >
        <span
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl"
          style={{ background: 'var(--color-accent-subtle)', color: 'var(--color-accent)' }}
        >
          {phase === 'updated' ? <CheckCircle2 size={18} /> :
            phase === 'updating' || phase === 'restarting'
              ? <LoaderCircle size={18} className="animate-spin" />
              : phase === 'error' ? <AlertTriangle size={18} /> : <Download size={18} />}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
                {phase === 'updated' ? 'Թարմացումը հաջող ավարտվեց'
                  : phase === 'restarting' ? 'Backend-ը վերագործարկվում է'
                    : phase === 'updating' ? 'Թարմացվում է OpenJarvis-ը'
                      : phase === 'error' ? 'Թարմացման ընթացքում խնդիր առաջացավ'
                        : 'Նոր թարմացում կա'}
              </div>
              <div className="mt-0.5 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                {phase === 'updating' ? 'GitHub main-ից ներբեռնվում է նոր կոդը...'
                  : phase === 'restarting' ? 'Սպասում ենք Backend-ի կապի վերականգնմանը...'
                    : phase === 'updated' ? 'Backend-ը կրկին հասանելի է։'
                      : status
                        ? <>GitHub main · {status.current_sha.slice(0, 7)} → {status.latest_sha.slice(0, 7)}</>
                        : 'GitHub main'}
              </div>
            </div>
            {phase !== 'updating' && phase !== 'restarting' && (
              <button type="button" onClick={dismiss} aria-label="Փակել թարմացման ծանուցումը"
                className="shrink-0 rounded-lg p-1.5 transition-opacity hover:opacity-60"
                style={{ color: 'var(--color-text-tertiary)' }}>
                <X size={14} />
              </button>
            )}
          </div>
          {error && (
            <p role="alert" className="mt-1 text-xs" style={{ color: 'var(--color-error)' }}>
              {error}
            </p>
          )}
          {(phase === 'available' || phase === 'error') && status?.update_available && (
            <div className="mt-2 flex items-center gap-2">
              <button type="button" onClick={() => void update()} disabled={!status.can_update}
                className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold disabled:opacity-50"
                style={{ background: 'var(--color-accent)', color: 'white' }}>
                <Download size={13} /> Թարմացնել / Update
              </button>
              {!status.can_update && (
                <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                  {status.message}
                </span>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
