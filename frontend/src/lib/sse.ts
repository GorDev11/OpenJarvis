import type { ResearchEvent, SSEEvent } from '../types';
import { getBase, authHeaders } from './api';

export interface ChatRequest {
  model: string;
  messages: Array<{ role: string; content: string }>;
  stream: true;
  temperature?: number;
  max_tokens?: number;
}

export async function* streamChat(
  request: ChatRequest,
  signal?: AbortSignal,
  requestId?: string,
): AsyncGenerator<SSEEvent> {
  const base = getBase();
  const response = await fetch(`${base}/v1/chat/completions`, {
    method: 'POST',
    headers: authHeaders({
      'Content-Type': 'application/json',
      ...(requestId ? { 'X-OpenJarvis-Request-ID': requestId } : {}),
    }),
    body: JSON.stringify(request),
    signal,
  });

  if (!response.ok) {
    throw new Error(`Chat request failed: ${response.status}`);
  }

  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  // SSE fields may be split across arbitrary network reads. Keep the named
  // event outside the read loop so `event:` in one chunk still applies to a
  // `data:` line received in the next chunk.
  let currentEvent: string | undefined;
  // Abort must release a pending reader, not only dismiss the chat spinner.
  const onAbort = () => { void reader.cancel().catch(() => {}); };
  signal?.addEventListener('abort', onAbort, { once: true });
  if (signal?.aborted) onAbort();

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        if (signal?.aborted) {
          throw new DOMException('Chat request was cancelled', 'AbortError');
        }
        // A clean HTTP EOF is not an OpenAI-compatible completion.
        // The server must send [DONE]; otherwise surface the disconnect.
        throw new Error('Chat stream ended before [DONE]; backend disconnected or was restarted.');
      }

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (line.startsWith('event: ')) {
          currentEvent = line.slice(7).trim();
        } else if (line.startsWith('data: ')) {
          const data = line.slice(6);
          if (data === '[DONE]') {
            if (signal?.aborted) {
              throw new DOMException('Chat request was cancelled', 'AbortError');
            }
            return;
          }
          yield { event: currentEvent, data };
          currentEvent = undefined;
        } else if (line.trim() === '') {
          currentEvent = undefined;
        }
      }
    }
  } finally {
    signal?.removeEventListener('abort', onAbort);
    if (signal?.aborted) {
      try { await reader.cancel(); } catch { /* already closed */ }
    }
    reader.releaseLock();
  }
}

/** Cancel the server-side agent independently of the aborted SSE connection. */
export async function cancelChat(requestId: string): Promise<boolean> {
  try {
    const response = await fetch(`${getBase()}/v1/chat/cancel/${encodeURIComponent(requestId)}`, {
      method: 'POST',
      headers: authHeaders(),
      signal: AbortSignal.timeout(4000),
      keepalive: true,
    });
    if (!response.ok) return false;
    const result = await response.json() as { status?: string };
    // Stop may arrive before the stream is registered; that early
    // cancellation is retained by the backend until registration.
    return result.status === 'cancelling' || result.status === 'pending';
  } catch {
    return false;
  }
}

export async function* streamResearch(
  query: string,
  model?: string,
  signal?: AbortSignal,
): AsyncGenerator<ResearchEvent> {
  // /api/research is mounted at the server root — strip any trailing /v1
  // from the base so configurations like "http://host:8000/v1" still resolve.
  const base = getBase().replace(/\/v1\/?$/, '');
  const response = await fetch(`${base}/api/research`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ query, ...(model ? { model } : {}) }),
    signal,
  });

  if (!response.ok) {
    throw new Error(`Research request failed: ${response.status}`);
  }

  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const data = line.slice(6);
        if (data === '[DONE]') return;
        try {
          const parsed = JSON.parse(data) as ResearchEvent;
          yield parsed;
          if (parsed.type === 'done') return;
        } catch {
          // skip malformed chunks
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
