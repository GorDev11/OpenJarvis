import { useCallback, useEffect, useRef, useState } from 'react';
import { CheckCircle2, AlertTriangle, RefreshCw, Download, Wrench } from 'lucide-react';
import { isTauri } from '../../lib/api';

type ColibriStatus = {
  ready: boolean;
  installing: boolean;
  model: string | null;
  message: string;
  error: string | null;
  log_tail: string;
};

type ToolCheck = { success: boolean; detail: string };

export function ColibriSetup({ onReady }: { onReady: (model: string | null) => void }) {
  const [status, setStatus] = useState<ColibriStatus | null>(null);
  const [error, setError] = useState('');
  const [toolResult, setToolResult] = useState<ToolCheck | null>(null);
  const [checkingTools, setCheckingTools] = useState(false);
  const [starting, setStarting] = useState(false);
  const busy = useRef(false);

  const refresh = useCallback(async () => {
    if (!isTauri() || busy.current) return;
    busy.current = true;
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      const result = await invoke<ColibriStatus>('colibri_status');
      setStatus(result);
      onReady(result.ready ? result.model : null);
    } catch (e) {
      setError(String(e));
      onReady(null);
    } finally {
      busy.current = false;
    }
  }, [onReady]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => { void refresh(); }, 5000);
    const focus = () => { void refresh(); };
    window.addEventListener('focus', focus);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener('focus', focus);
    };
  }, [refresh]);

  const start = async () => {
    const approved = window.confirm(
      'Install Colibri and Qwen3.6-35B-A3B locally? The model download is about 23 GB. ' +
      'Installation is resumable and may require additional tools for Windows GPU acceleration.',
    );
    if (!approved) return;
    setStarting(true);
    setError('');
    setToolResult(null);
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      await invoke('start_colibri_setup');
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setStarting(false);
    }
  };

  const testTools = async () => {
    setCheckingTools(true);
    setToolResult(null);
    setError('');
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      setToolResult(await invoke<ToolCheck>('colibri_test_tools'));
    } catch (e) {
      setError(String(e));
    } finally {
      setCheckingTools(false);
    }
  };

  return (
    <div className="w-full rounded-xl border p-4 flex flex-col gap-3" style={{
      background: 'var(--color-bg-secondary)', borderColor: 'var(--color-border)',
    }}>
      <div className="flex items-center gap-2">
        {status?.ready
          ? <CheckCircle2 size={18} style={{ color: 'var(--color-success)' }} />
          : <AlertTriangle size={18} style={{ color: 'var(--color-text-tertiary)' }} />}
        <strong className="text-sm">Colibri · Qwen3.6-35B-A3B</strong>
      </div>
      <div className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
        {status?.message ?? 'Checking local Colibri server…'}
        {status?.model ? ` · Model: ${status.model}` : ''}
      </div>
      <div className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
        Local only · 127.0.0.1:19000 · ~23 GB model download · Ollama remains available
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {!status?.ready && (
          <button type="button" disabled={starting || status?.installing || !isTauri()}
            onClick={() => { void start(); }} className="rounded-lg px-3 py-2 text-xs font-semibold disabled:opacity-50"
            style={{ background: 'var(--color-accent)', color: 'white' }}>
            <Download size={13} className="inline mr-1" />
            {status?.installing ? 'Installing Colibri…' : starting ? 'Starting…' : 'Install / Resume (~23 GB)'}
          </button>
        )}
        <button type="button" onClick={() => { void refresh(); }}
          className="rounded-lg border px-3 py-2 text-xs" style={{ borderColor: 'var(--color-border)' }}>
          <RefreshCw size={13} className="inline mr-1" /> Check connection
        </button>
        {status?.ready && (
          <button type="button" disabled={checkingTools} onClick={() => { void testTools(); }}
            className="rounded-lg border px-3 py-2 text-xs disabled:opacity-50"
            style={{ borderColor: 'var(--color-accent)' }}>
            <Wrench size={13} className="inline mr-1" />
            {checkingTools ? 'Testing tool call…' : 'Test tool calling'}
          </button>
        )}
      </div>
      {toolResult && (
        <div role="status" className="text-xs"
          style={{ color: toolResult.success ? 'var(--color-success)' : 'var(--color-error)' }}>
          {toolResult.detail}
        </div>
      )}
      {(error || status?.error) && (
        <div role="alert" className="text-xs" style={{ color: 'var(--color-error)' }}>
          {error || status?.error}
        </div>
      )}
      {status?.log_tail && (
        <details>
          <summary className="cursor-pointer text-xs" style={{ color: 'var(--color-text-secondary)' }}>
            Installation log
          </summary>
          <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap break-all text-[10px]">
            {status.log_tail}
          </pre>
        </details>
      )}
      <div className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
        Once Ready, click Save inference source below and restart OpenJarvis.
        If Windows GPU setup needs MSYS2/CUDA, the installer log will explain the missing dependency.
      </div>
      <a href="https://github.com/JustVugg/colibri" target="_blank" rel="noreferrer"
        className="text-xs underline" style={{ color: 'var(--color-accent)' }}>
        Official Colibri project
      </a>
    </div>
  );
}
