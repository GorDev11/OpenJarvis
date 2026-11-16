import { useEffect, useState } from 'react';
import { Outlet, useNavigate } from 'react-router';
import { ApprovalBell } from './ApprovalBell';
import { Sidebar } from './Sidebar/Sidebar';
import { SystemPulse } from './SystemPulse';
import { useAppStore } from '../lib/store';
import { checkHealth } from '../lib/api';
import { MainSourceUpdate } from './Desktop/MainSourceUpdate';

export function Layout() {
  const sidebarOpen = useAppStore((s) => s.sidebarOpen);
  const [apiReachable, setApiReachable] = useState<boolean | null>(null);
  const [backendRestarting, setBackendRestarting] = useState(false);

  useEffect(() => {
    let mounted = true;
    let checking = false;
    let stage: 'idle' | 'updating' | 'waiting' = 'idle';
    let graceDeadline = 0;
    let waitingSince = 0;

    const check = async () => {
      if (checking) return;
      checking = true;
      try {
        const reachable = await checkHealth();
        if (!mounted) return;
        setApiReachable(reachable);
        if (stage === 'waiting' && reachable && Date.now() - waitingSince >= 1500) {
          stage = 'idle';
          setBackendRestarting(false);
          window.dispatchEvent(new Event('openjarvis-backend-ready'));
        } else if (stage !== 'idle' && Date.now() >= graceDeadline) {
          stage = 'idle';
          setBackendRestarting(false);
          window.dispatchEvent(new Event('openjarvis-backend-timeout'));
        }
      } finally {
        checking = false;
      }
    };

    const onBackendUpdate = (event: Event) => {
      const next = (event as CustomEvent<string>).detail;
      if (next !== 'updating' && next !== 'waiting') return;
      stage = next;
      graceDeadline = Date.now() + 5 * 60 * 1000;
      setBackendRestarting(true);
      if (next === 'updating') {
        setApiReachable(null);
      } else {
        waitingSince = Date.now();
        void check();
      }
    };

    void check();
    const normalTimer = window.setInterval(() => {
      if (stage === 'idle') void check();
    }, 30000);
    const recoveryTimer = window.setInterval(() => {
      if (stage !== 'idle') void check();
    }, 2500);
    const onFocus = () => { void check(); };
    window.addEventListener('openjarvis-backend-update', onBackendUpdate);
    window.addEventListener('focus', onFocus);
    return () => {
      mounted = false;
      window.clearInterval(normalTimer);
      window.clearInterval(recoveryTimer);
      window.removeEventListener('openjarvis-backend-update', onBackendUpdate);
      window.removeEventListener('focus', onFocus);
    };
  }, []);

  const navigate = useNavigate();

  return (
    <div className="flex flex-col h-full w-full overflow-hidden relative" style={{ paddingTop: '3px' }}>
      <div className="hud-backdrop" aria-hidden="true" />
      <SystemPulse apiReachable={apiReachable} />
      <ApprovalBell />

      {/* Health check banner */}
      {apiReachable === false && !backendRestarting && (
        <div
          className="flex items-center gap-3 px-4 py-2 text-sm shrink-0"
          style={{
            background: 'color-mix(in srgb, var(--color-error) 8%, transparent)',
            borderBottom: '1px solid color-mix(in srgb, var(--color-error) 15%, transparent)',
            color: 'var(--color-text)',
          }}
        >
          <span
            className="w-1.5 h-1.5 rounded-full shrink-0"
            style={{ background: 'var(--color-error)' }}
          />
          <span>Cannot reach OpenJarvis backend</span>
          <button
            onClick={() => navigate('/settings')}
            className="text-sm underline cursor-pointer ml-auto shrink-0"
            style={{ color: 'var(--color-accent)' }}
          >
            Change URL
          </button>
        </div>
      )}

      {/* Keep update actions inside the viewport on every route, including Settings. */}
      <div className="relative z-30 shrink-0">
        <MainSourceUpdate />
      </div>

      <div className="flex flex-1 min-h-0 relative z-10">
        <Sidebar />
        {sidebarOpen && (
          <div
            className="fixed inset-0 z-20 bg-black/40 md:hidden"
            onClick={() => useAppStore.getState().setSidebarOpen(false)}
          />
        )}
        <main className="flex-1 flex flex-col min-w-0 h-full relative overflow-hidden" style={{ background: 'transparent' }}>
          <div className="flex-1 flex flex-col min-w-0 min-h-0 relative z-[2]">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
