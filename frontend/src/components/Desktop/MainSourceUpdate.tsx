import { useCallback, useEffect, useRef, useState } from 'react';
import { Download, RefreshCw, CheckCircle2, AlertTriangle, LoaderCircle, X } from 'lucide-react';
import { isTauri } from '../../lib/api';
import { isAutoUpdateDisabled, isUpdaterBuildDisabled } from './UpdateChecker';
import { useAppStore } from '../../lib/store';

// Direct GitHub WebSockets are unavailable to installed clients; use fast, bounded polling.
const CHECK_EVERY_MS = 15 * 1000;
const CHECK_SIGNED_EVERY_MS = 60 * 1000;
const DISMISSED_KEY = 'oj-main-update-dismissed-sha';

export type MainSourceStatus = {
  current_sha: string;
  latest_sha: string;
  branch: string;
  update_available: boolean;
  can_update: boolean;
  message: string;
};

type Phase = 'idle' | 'checking' | 'available' | 'downloading' | 'installing' | 'updating' | 'restarting' | 'updated' | 'error';

/** A single update surface for GitHub main source and Tauri-signed releases.
 * Never accepts arbitrary executable downloads or unverified updates.
 */
export function MainSourceUpdate({ compact = false }: { compact?: boolean }) {
  const [phase, setPhase] = useState<Phase>('idle');
  const [status, setStatus] = useState<MainSourceStatus | null>(null);
  const [error, setError] = useState('');
  const [dismissed, setDismissed] = useState(false);
  const updating = useRef(false);
  const checking = useRef(false);
  const [lastCheckedAt, setLastCheckedAt] = useState('');
  const [desktopVersion, setDesktopVersion] = useState('');
  const [downloadProgress, setDownloadProgress] = useState(0);
  const signedUpdate = useRef<any>(null);
  const checkingSigned = useRef(false);
  const installingDesktop = useRef(false);
  const [autoInstallEnabled, setAutoInstallEnabled] = useState(() => !isAutoUpdateDisabled());
  const isStreaming = useAppStore(s => s.streamState.isStreaming);

  useEffect(() => {
    const onSettingChanged = () => setAutoInstallEnabled(!isAutoUpdateDisabled());
    window.addEventListener('openjarvis-auto-install-setting-changed', onSettingChanged);
    return () => window.removeEventListener('openjarvis-auto-install-setting-changed', onSettingChanged);
  }, []);

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
      setPhase(result.update_available || signedUpdate.current ? 'available' : 'idle');
      if (result.update_available) {
        const suppressed = (() => {
          try { return localStorage.getItem(DISMISSED_KEY) === result.latest_sha; } catch { return false; }
        })();
        if (!signedUpdate.current) setDismissed(suppressed);
      } else if (!signedUpdate.current) {
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

  // The preview has no signing key and cannot install an executable.
  // The signed channel is checked independently from the main Git ref;
  // CI may still be building when a new source commit is first detected.
  const checkDesktop = useCallback(async () => {
    // Checks continue even when automatic installation is disabled: the user
    // can still choose a one-click manual update in the banner.
    if (!isTauri() || isUpdaterBuildDisabled() ||
        updating.current || checkingSigned.current) return;
    checkingSigned.current = true;
    try {
      const { check } = await import('@tauri-apps/plugin-updater');
      const release = await check({ timeout: 30000 });
      if (!release) {
        if (signedUpdate.current) {
          try { await signedUpdate.current.close(); } catch { /* already closed */ }
          signedUpdate.current = null;
          setDesktopVersion('');
        }
        return;
      }
      if (signedUpdate.current?.version === release.version) {
        try { await release.close(); } catch { /* already closed */ }
        return;
      }
      if (signedUpdate.current) {
        try { await signedUpdate.current.close(); } catch { /* already closed */ }
      }
      signedUpdate.current = release;
      setDesktopVersion(release.version);
      setPhase(prev => prev === 'updating' || prev === 'restarting' ? prev : 'available');
      let suppressed = false;
      try { suppressed = localStorage.getItem(DISMISSED_KEY) === `desktop:${release.version}`; } catch { /* private mode */ }
      setDismissed(suppressed);
    } catch {
      // No published release yet, or temporarily offline. Never download an
      // unsigned Actions artifact or fall back to an upstream release feed.
    } finally {
      checkingSigned.current = false;
    }
  }, []);

  useEffect(() => {
    if (!isTauri() || isUpdaterBuildDisabled()) return;
    void checkDesktop();
    const timer = window.setInterval(() => { void checkDesktop(); }, CHECK_SIGNED_EVERY_MS);
    const onFocus = () => { void checkDesktop(); };
    window.addEventListener('focus', onFocus);
    window.addEventListener('online', onFocus);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener('focus', onFocus);
      window.removeEventListener('online', onFocus);
    };
  }, [checkDesktop]);

  useEffect(() => {
    if (!isTauri()) return;
    const onReady = () => {
      if (!updating.current || installingDesktop.current) return;
      updating.current = false;
      setPhase(prev => prev === 'updating' || prev === 'restarting' ? 'updated' : prev);
    };
    const onTimeout = () => {
      if (!updating.current || installingDesktop.current) return;
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
    if (updating.current || isStreaming) return;
    const release = signedUpdate.current;
    if (!release && !status?.can_update) return;
    updating.current = true;
    installingDesktop.current = !!release;
    setDismissed(false);
    setError('');

    if (release) {
      // Download and verify the release before changing local source.
      setPhase('downloading');
      setDownloadProgress(0);
      let downloaded = 0;
      let total = 0;
      try {
        await release.download((event: any) => {
          if (event.event === 'Started') total = event.data?.contentLength || 0;
          if (event.event === 'Progress') {
            downloaded += event.data?.chunkLength || 0;
            if (total > 0) setDownloadProgress(Math.min(100, Math.round(100 * downloaded / total)));
          }
          if (event.event === 'Finished') setDownloadProgress(100);
        });

        // Fast-forward the owned Python checkout before Windows quits in
        // update.install(). Reject dirty/diverged checkouts: never reset.
        const { invoke } = await import('@tauri-apps/api/core');
        const source = await invoke<MainSourceStatus>('check_main_update');
        if (source.update_available) {
          if (!source.can_update) {
            throw new Error('Backend-ը փոփոխված է տեղում։ Պահպանիր փոփոխությունները՝ մինչև Desktop թարմացնելը։');
          }
          window.dispatchEvent(new CustomEvent('openjarvis-backend-update', { detail: 'updating' }));
          await invoke('apply_main_update', {
            expectedSha: source.latest_sha,
            restartBackend: false,
          });
        } else {
          // Even when the Python checkout is already current, the signed
          // installer will terminate this Desktop. Reap its owned backend
          // first so the relaunched binary does not find stale port 18761.
          await invoke('stop_backend');
        }
        setPhase('installing');
        await release.install({ restartAfterInstall: true });
        // Windows normally exits during installation and relaunches the app.
        setPhase('updated');
      } catch (e) {
        setError(String(e));
        setPhase('error');
      } finally {
        updating.current = false;
        installingDesktop.current = false;
      }
      return;
    }

    // No signed Desktop binary is currently published: update Python only.
    setPhase('updating');
    window.dispatchEvent(new CustomEvent('openjarvis-backend-update', { detail: 'updating' }));
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      await invoke<string>('apply_main_update', {
        expectedSha: status!.latest_sha,
        restartBackend: true,
      });
      try { localStorage.removeItem(DISMISSED_KEY); } catch { /* private mode */ }
      setStatus(prev => prev ? {
        ...prev, current_sha: prev.latest_sha, branch: 'main', update_available: false,
      } : prev);
      setPhase('restarting');
      window.dispatchEvent(new CustomEvent('openjarvis-backend-update', { detail: 'waiting' }));
    } catch (e) {
      updating.current = false;
      setError(String(e));
      setPhase('error');
      // The launcher retries its owned backend even when Git refuses an update.
      window.dispatchEvent(new CustomEvent('openjarvis-backend-update', { detail: 'waiting' }));
    }
  }, [status, isStreaming]);

  // Owner opt-in: install an available, signature-verified Desktop release
  // only after one minute without keyboard/pointer activity, and never while
  // a chat response streams. No unsigned Preview can enter this path.
  useEffect(() => {
    if (compact || !isTauri() || isUpdaterBuildDisabled() ||
        !autoInstallEnabled || !desktopVersion || phase !== 'available' ||
        isStreaming) return;
    let lastActivity = Date.now();
    const activity = () => { lastActivity = Date.now(); };
    window.addEventListener('keydown', activity);
    window.addEventListener('pointerdown', activity);
    const timer = window.setInterval(() => {
      if (updating.current || Date.now() - lastActivity < 60_000) return;
      // Avoid closing the app while the user is editing an unsent message.
      const focused = document.activeElement as HTMLInputElement | null;
      if (focused?.matches('textarea, input, [contenteditable="true"]')) {
        const unsent = 'value' in focused && typeof focused.value === 'string'
          ? focused.value.trim()
          : focused.textContent?.trim();
        if (unsent) return;
      }
      void update();
    }, 5000);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener('keydown', activity);
      window.removeEventListener('pointerdown', activity);
    };
  }, [compact, autoInstallEnabled, desktopVersion, phase, isStreaming, update]);

  if (!isTauri()) return null;

  const dismiss = () => {
    setDismissed(true);
    const key = desktopVersion ? `desktop:${desktopVersion}` : status?.latest_sha;
    if (key) {
      try { localStorage.setItem(DISMISSED_KEY, key); } catch { /* private mode */ }
    }
  };

  // Compact Settings view is read-only; the visible action lives in one card above.
  if (compact) {
    return (
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="inline-flex items-center gap-1.5 font-medium" role="status"
          style={{ color: 'var(--color-text-secondary)' }}>
          <RefreshCw size={12} className={phase === 'checking' ? 'animate-spin' : ''} />
          Ավտոմատ ստուգում՝ յուրաքանչյուր 15 վայրկյանը մեկ
        </span>
        {(status?.update_available || desktopVersion) && (
          <span style={{ color: 'var(--color-accent)' }}>
            Նոր տարբերակ կա · Թարմացման կոճակը վերևում է
          </span>
        )}
        <span style={{ color: 'var(--color-text-tertiary)' }}>
          {desktopVersion ? `Desktop v${desktopVersion}` : (status?.branch === 'main' ? 'main' : status?.branch || 'GitHub')} · {status?.current_sha?.slice(0, 7)}
          {status?.update_available ? ` → ${status.latest_sha.slice(0, 7)}` : ''}
        </span>
        {lastCheckedAt && <span style={{ color: 'var(--color-text-tertiary)' }}>Ստուգվել է՝ {lastCheckedAt}</span>}
        {status && <span style={{ color: 'var(--color-text-secondary)' }}>{status.message}</span>}
        {(phase === 'updating' || phase === 'restarting') && <span>Backend-ը վերագործարկվում է...</span>}
        {error && <span role="alert" style={{ color: 'var(--color-error)' }}>{error}</span>}
      </div>
    );
  }

  if (dismissed || (phase !== 'available' && phase !== 'downloading' && phase !== 'installing' && phase !== 'updating' && phase !== 'restarting' && phase !== 'updated' && phase !== 'error')) {
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
            phase === 'downloading' || phase === 'installing' || phase === 'updating' || phase === 'restarting'
              ? <LoaderCircle size={18} className="animate-spin" />
              : phase === 'error' ? <AlertTriangle size={18} /> : <Download size={18} />}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
                {phase === 'updated' ? 'Թարմացումը հաջող ավարտվեց'
                  : phase === 'downloading' ? 'Ներբեռնվում է ստորագրված Desktop թարմացումը'
                    : phase === 'installing' ? 'Տեղադրվում է OpenJarvis Desktop-ը'
                    : phase === 'restarting' ? 'Backend-ը վերագործարկվում է'
                    : phase === 'updating' ? 'Թարմացվում է OpenJarvis-ը'
                      : phase === 'error' ? 'Թարմացման ընթացքում խնդիր առաջացավ'
                        : 'Նոր թարմացում կա'}
              </div>
              <div className="mt-0.5 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                {phase === 'downloading' ? `Ներբեռնում՝ ${downloadProgress}% · ստորագրությունը ստուգվում է`
                  : phase === 'installing' ? 'Windows-ը կտեղադրի նոր .exe-ն։ Ծրագիրը կարող է փակվել։'
                  : phase === 'updating' ? 'GitHub main-ից ներբեռնվում է նոր կոդը...'
                  : phase === 'restarting' ? 'Սպասում ենք Backend-ի կապի վերականգնմանը...'
                    : phase === 'updated' ? 'Backend-ը կրկին հասանելի է։'
                      : desktopVersion
                        ? <>GitHub main · ստորագրված Desktop v{desktopVersion}</>
                        : status
                        ? <>GitHub main · {status.current_sha.slice(0, 7)} → {status.latest_sha.slice(0, 7)}</>
                        : 'GitHub main'}
              </div>
            </div>
            {phase !== 'downloading' && phase !== 'installing' && phase !== 'updating' && phase !== 'restarting' && (
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
          {(phase === 'available' || phase === 'error') && (status?.update_available || desktopVersion) && (
            <div className="mt-2 flex items-center gap-2">
              <button type="button" onClick={() => void update()} disabled={(!desktopVersion && !status?.can_update) || isStreaming}
                className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold disabled:opacity-50"
                style={{ background: 'var(--color-accent)', color: 'white' }}>
                <Download size={13} /> {desktopVersion ? 'Թարմացնել ամբողջ ծրագիրը' : 'Թարմացնել միայն Backend-ը'}
              </button>
              {!desktopVersion && status && !status.can_update && (
                <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                  {status.message}
                </span>
              )}
              {isStreaming && <span className="text-xs">Սպասիր՝ պատասխանը ավարտվի</span>}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
