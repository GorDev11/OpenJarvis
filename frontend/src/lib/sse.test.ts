import { afterEach, describe, expect, it, vi } from 'vitest';

import { cancelChat, streamChat } from './sse';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('streamChat SSE framing', () => {
  it('adds request ID and calls the separate cancellation endpoint', async () => {
    const requestId = '5ec5c546-f2b3-4fc4-b9bd-ab2d01437df4';
    const fakeFetch = vi.fn()
      .mockResolvedValueOnce(new Response('data: [DONE]\n\n', { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ status: 'cancelling' }), { status: 200 }));
    vi.stubGlobal('fetch', fakeFetch);

    for await (const event of streamChat({
      model: 'qwen3.6-colibri',
      messages: [{ role: 'user', content: 'Hello' }],
      stream: true,
    }, undefined, requestId)) {
      expect(event).toBeDefined();
    }
    expect(fakeFetch.mock.calls[0][1].headers['X-OpenJarvis-Request-ID']).toBe(requestId);
    expect(await cancelChat(requestId)).toBe(true);
    expect(fakeFetch.mock.calls[1][0]).toContain(`/v1/chat/cancel/${requestId}`);
  });

  it('preserves a named event when event and data arrive in different reads', async () => {
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('event: tool_call_start\n'));
        controller.enqueue(
          encoder.encode('data: {"tool":"network_diagnostics","arguments":"{}"}\n\n'),
        );
        controller.enqueue(encoder.encode('data: [DONE]\n\n'));
        controller.close();
      },
    });
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(body, { status: 200 })),
    );

    const events = [];
    for await (const event of streamChat({
      model: 'test-model',
      messages: [{ role: 'user', content: 'Ստուգիր ինտերնետս' }],
      stream: true,
    })) {
      events.push(event);
    }

    expect(events).toEqual([
      {
        event: 'tool_call_start',
        data: '{"tool":"network_diagnostics","arguments":"{}"}',
      },
    ]);
  });
});
