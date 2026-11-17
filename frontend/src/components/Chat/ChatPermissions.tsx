import { useCallback, useEffect, useState } from 'react';
import { ShieldCheck, ShieldAlert, Loader2 } from 'lucide-react';
import {
  getChatToolMode,
  getPendingChatToolPermissions,
  resolveChatToolPermission,
  setChatToolMode,
  type ChatToolMode,
  type ChatToolPermission,
  isTauri,
} from '../../lib/api';

export function ChatPermissionMode() {
  const [mode, setMode] = useState<ChatToolMode>('autonomous');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    if (!isTauri()) return;
    let live = true;
    void getChatToolMode()
      .then(value => { if (live) setMode(value); })
      .catch(() => { if (live) setError('Կարգավորումը հասանելի չէ'); });
    return () => { live = false; };
  }, []);

  if (!isTauri()) return null;
  return (
    <div className="flex items-center gap-2 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
      <ShieldCheck size={14} />
      <label htmlFor="chat-tool-permission-mode">Գործիքներ</label>
      <select
        id="chat-tool-permission-mode"
        value={mode}
        disabled={saving}
        title="Ավտոմատ՝ անվտանգ ընթերցումները առանց հարցնելու։ Հարցնել ինձ՝ հաստատել յուրաքանչյուր գործիք։"
        onChange={async e => {
          const next = e.target.value as ChatToolMode;
          const previous = mode;
          setMode(next);
          setSaving(true);
          setError('');
          try {
            await setChatToolMode(next);
          } catch {
            setMode(previous);
            setError('Չհաջողվեց պահպանել');
          } finally {
            setSaving(false);
          }
        }}
        className="rounded-md border px-2 py-1 text-xs cursor-pointer"
        style={{
          borderColor: 'var(--color-border)',
          background: 'var(--color-bg-secondary)',
          color: 'var(--color-text)',
        }}
      >
        <option value="autonomous">Ավտոմատ</option>
        <option value="guided">Հարցնել ինձ</option>
      </select>
      {error && <span role="alert" style={{ color: 'var(--color-error)' }}>{error}</span>}
    </div>
  );
}

/** Always visible immediately above the chat input when the agent is blocked. */
export function InlineChatToolApprovals() {
  const [pending, setPending] = useState<ChatToolPermission[]>([]);
  const [acting, setActing] = useState<string | null>(null);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      const requests = await getPendingChatToolPermissions();
      setPending(requests);
    } catch {
      // Transient restarts must not discard a visible decision card.
      // Server-side permissions expire and deny if the backend disappears.
    }
  }, []);

  useEffect(() => {
    if (!isTauri()) return;
    void load();
    const timer = window.setInterval(() => { void load(); }, 750);
    return () => window.clearInterval(timer);
  }, [load]);

  if (!isTauri() || pending.length === 0) return null;

  const decide = async (request: ChatToolPermission, allow: boolean) => {
    setActing(request.id);
    setError('');
    try {
      await resolveChatToolPermission(request.id, allow);
      setPending(current => current.filter(x => x.id !== request.id));
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setActing(null);
    }
  };

  return (
    <div
      className="mx-auto w-full max-w-[var(--chat-max-width)] px-4 pb-3 shrink-0"
      role="region"
      aria-label="Tool permission requests"
    >
      {pending.map(request => (
        <div
          key={request.id}
          className="rounded-xl border px-4 py-3 my-1.5 flex flex-col gap-2"
          style={{
            borderColor: 'var(--color-warning, var(--color-border))',
            background: 'var(--color-bg-secondary)',
          }}
        >
          <div className="flex gap-2 items-center text-sm font-semibold">
            <ShieldAlert size={16} />
            <span>Jarvis-ը խնդրում է թույլտվություն · {request.tool}</span>
          </div>
          <p className="text-xs whitespace-pre-wrap break-words"
            style={{ color: 'var(--color-text-secondary)' }}>
            {request.prompt}
          </p>
          <div className="flex flex-wrap gap-2 items-center justify-end">
            <span className="text-[11px] mr-auto"
              style={{ color: 'var(--color-text-tertiary)' }}>
              Առանց հաստատման գործողությունը չի կատարվի։
            </span>
            <button
              type="button"
              disabled={acting !== null}
              onClick={() => void decide(request, false)}
              className="px-3 py-1.5 rounded-md border text-xs font-semibold disabled:opacity-50"
              style={{ borderColor: 'var(--color-border)' }}
            >
              Մերժել
            </button>
            <button
              type="button"
              disabled={acting !== null}
              onClick={() => void decide(request, true)}
              className="px-3 py-1.5 rounded-md text-xs font-semibold disabled:opacity-50"
              style={{
                background: 'var(--color-accent)',
                color: 'var(--color-on-accent, #fff)',
              }}
            >
              {acting === request.id ? <Loader2 className="inline animate-spin" size={13} /> : null}
              Թույլատրել մեկ անգամ
            </button>
          </div>
        </div>
      ))}
      {error && <p role="alert" className="text-xs" style={{ color: 'var(--color-error)' }}>{error}</p>}
    </div>
  );
}
