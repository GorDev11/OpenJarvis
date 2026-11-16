import { afterEach, describe, expect, it, vi } from 'vitest';

import { streamChat } from './sse';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('streamChat SSE framing', () => {
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
