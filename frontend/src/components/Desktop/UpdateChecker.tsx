import React, { useState, useEffect, useCallback, useRef } from 'react';

type UpdateState = 'idle' | 'available' | 'downloading' | 'syncing' | 'installing' | 'ready' | 'error';

const CHECK_INTERVAL_MS = 30 * 60 * 1000; // 30 minutes
const DISABLED_KEY = 'oj-auto-update-disabled';

export function isUpdaterBuildDisabled(): boolean {
  const value = (import.meta as any).env?.VITE_OPENJARVIS_NO_UPDATER;
  return value === '1' || value === 'true';
}

export function isAutoUpdateDisabled(): boolean {
  try {
    return localStorage.getItem(DISABLED_KEY) === '1';
  } catch {
    return false;
  }
}

export function setAutoUpdateDisabled(disabled: boolean): void {
  try {
    if (disabled) {
      localStorage.setItem(DISABLED_KEY, '1');
    } else {
      localStorage.removeItem(DISABLED_KEY);
    }
  } catch {}
}

export function UpdateChecker() {
  const [state, setState] = useState<UpdateState>('idle');
  const [version, setVersion] = useState('');
  const [progress, setProgress] = useState(0);
  const [errorMsg, setErrorMsg] = useState('');
  const [dismissed, setDismissed] = useState(false);
  const updateRef = useRef<any>(null);

  const checkForUpdate = useCallback(async () => {
    if (isUpdaterBuildDisabled() || isAutoUpdateDisabled()) return;
    try {
      const { check } = await import('@tauri-apps/plugin-updater');
      const update = await check();
      if (update) {
        updateRef.current = update;
        setVersion(update.version);
        setState('available');
        setDismissed(false);
      }
    } catch {
      // Silently ignore — likely running in browser or no update available
    }
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined' || !(window as any).__TAURI_INTERNALS__) {
      return;
    }
    // Preview builds compile this flag in and have no updater endpoint. Keep
    // both automatic and manual update paths inert so an isolated preview can
    // never cross into the stable channel.
    if (isUpdaterBuildDisabled() || isAutoUpdateDisabled()) return;

    checkForUpdate();
    const interval = setInterval(checkForUpdate, CHECK_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [checkForUpdate]);

  const handleDownload = useCallback(async () => {
    const update = updateRef.current;
    if (!update) return;

    setState('downloading');
    setProgress(0);
    setErrorMsg('');

    try {
      let downloaded = 0;
      let contentLength = 0;

      // Download and verify the signed binary before mutating the source.
      // Tauri's Windows install() exits the app, so sync must happen first.
      await update.download((event: any) => {
        if (event.event === 'Started') {
          contentLength = event.data?.contentLength ?? 0;
        } else if (event.event === 'Progress') {
          downloaded += event.data?.chunkLength ?? 0;
          if (contentLength > 0) {
            setProgress(Math.min(100, Math.round((downloaded / contentLength) * 100)));
          }
        } else if (event.event === 'Finished') {
          setProgress(100);
        }
      });

      setState('syncing');
      try {
        const { invoke } = await import('@tauri-apps/api/core');
        const source = await invoke<{
          latest_sha: string; update_available: boolean; can_update: boolean;
        }>('check_main_update');
        if (source.update_available && source.can_update) {
          await invoke('apply_main_update', { expectedSha: source.latest_sha });
        } else if (source.update_available) {
          setErrorMsg('Desktop update ready; backend source has local changes and needs review.');
        }
      } catch (syncError) {
        // A dirty or offline Git checkout must not block a verified Desktop update.
        setErrorMsg('Desktop update ready; backend source sync did not finish: ' + String(syncError));
      }

      setState('installing');
      await update.install();
      // Windows quits during install. Other platforms can relaunch manually.
      setState('ready');
    } catch (e: any) {
      setErrorMsg(e?.message || 'Download or installation failed');
      setState('error');
      setTimeout(() => setState('idle'), 5000);
    }
  }, []);

  const handleRelaunch = useCallback(async () => {
    try {
      const { relaunch } = await import('@tauri-apps/plugin-process');
      await relaunch();
    } catch {
      setErrorMsg('Please restart the application manually');
      setState('error');
      setTimeout(() => setState('idle'), 5000);
    }
  }, []);

  const handleDisable = useCallback(() => {
    setAutoUpdateDisabled(true);
    setState('idle');
    setDismissed(false);
  }, []);

  if (state === 'idle' || dismissed) return null;

  return (
    <div style={styles.banner}>
      {state === 'available' && (
        <div style={styles.row}>
          <span>Update available: <strong>v{version}</strong></span>
          <div style={styles.actions}>
            <button style={styles.primaryBtn} onClick={handleDownload}>Թարմացնել / Update</button>
            <button style={styles.secondaryBtn} onClick={() => setDismissed(true)}>Later</button>
            <button style={styles.muteBtn} onClick={handleDisable}>Disable auto-updates</button>
          </div>
        </div>
      )}

      {state === 'downloading' && (
        <div style={styles.row}>
          <span>Downloading update... {progress}%</span>
          <div style={styles.progressBar}>
            <div style={{ ...styles.progressFill, width: `${progress}%` }} />
          </div>
        </div>
      )}

      {(state === 'syncing' || state === 'installing') && (
        <div style={styles.row}>
          <span>{state === 'syncing' ? 'Թարմացվում է GitHub main-ի Backend-ը...' : 'Տեղադրվում է ստորագրված Desktop թարմացումը...'}</span>
          {errorMsg && <span style={{ color: '#f9e2af', fontSize: 12 }}>{errorMsg}</span>}
        </div>
      )}

      {state === 'ready' && (
        <div style={styles.row}>
          <span style={{ color: '#a6e3a1' }}>Update installed.</span>
          {errorMsg && <span style={{ color: '#f9e2af', fontSize: 12 }}>{errorMsg}</span>}
          <div style={styles.actions}>
            <button style={styles.successBtn} onClick={handleRelaunch}>Relaunch now</button>
            <button style={styles.secondaryBtn} onClick={() => setDismissed(true)}>Later</button>
          </div>
        </div>
      )}

      {state === 'error' && (
        <div style={styles.row}>
          <span style={{ color: '#f38ba8' }}>Update error: {errorMsg}</span>
        </div>
      )}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  banner: {
    padding: '10px 24px',
    backgroundColor: '#181825',
    borderBottom: '1px solid #313244',
  },
  row: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: '16px',
    fontSize: '13px',
  },
  actions: {
    display: 'flex',
    gap: '8px',
    alignItems: 'center',
  },
  primaryBtn: {
    padding: '4px 14px',
    border: 'none',
    borderRadius: '4px',
    backgroundColor: '#89b4fa',
    color: '#1e1e2e',
    fontSize: '12px',
    fontWeight: 600,
    cursor: 'pointer',
  },
  successBtn: {
    padding: '4px 14px',
    border: 'none',
    borderRadius: '4px',
    backgroundColor: '#a6e3a1',
    color: '#1e1e2e',
    fontSize: '12px',
    fontWeight: 600,
    cursor: 'pointer',
  },
  secondaryBtn: {
    padding: '4px 14px',
    border: '1px solid #45475a',
    borderRadius: '4px',
    backgroundColor: 'transparent',
    color: '#a6adc8',
    fontSize: '12px',
    cursor: 'pointer',
  },
  muteBtn: {
    padding: '0',
    border: 'none',
    backgroundColor: 'transparent',
    color: '#585b70',
    fontSize: '11px',
    cursor: 'pointer',
    textDecoration: 'underline',
  },
  progressBar: {
    flex: 1,
    maxWidth: '300px',
    height: '6px',
    backgroundColor: '#313244',
    borderRadius: '3px',
    overflow: 'hidden',
  },
  progressFill: {
    height: '100%',
    backgroundColor: '#89b4fa',
    borderRadius: '3px',
    transition: 'width 0.3s ease',
  },
};
