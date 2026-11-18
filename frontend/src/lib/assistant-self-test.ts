import { cancelChat, streamChat } from './sse';

export interface AssistantSelfTestResult {
  model: string;
  reply: string;
  totalMs: number;
  firstTokenMs: number;
  inferenceStartMs: number | null;
  finishReason: string;
  toolEvents: number;
}

/**
 * A user-triggered end-to-end probe through the *configured server agent*.
 * This is not a fast-chat bypass: it sends the same stream:true request as
 * InputArea, with no client-supplied tools, so the server's Orchestrator and
 * security/approval gates remain active.
 */
export async function runAssistantSelfTest(
  model: string,
  onPhase: (phase: string) => void = () => {},
  timeoutMs = 180_000,
): Promise<AssistantSelfTestResult> {
  if (!model) throw new Error('Choose a model before running the self-test.');
  const controller = new AbortController();
  const requestId = crypto.randomUUID();
  const start = performance.now();
  let timedOut = false;
  const timeout = setTimeout(() => {
    timedOut = true;
    void cancelChat(requestId);
    controller.abort();
  }, timeoutMs);

  let reply = '';
  let firstTokenMs = -1;
  let inferenceStartMs: number | null = null;
  let finishReason = '';
  let toolEvents = 0;

  try {
    onPhase('Connecting to OpenJarvis...');
    // Use a fixed harmless greeting. Never include personal chat history in
    // diagnostics or send credentials to a third-party service.
    for await (const event of streamChat({
      model,
      messages: [{ role: 'user', content: 'Բարև' }],
      stream: true,
      max_tokens: 128,
      temperature: 0,
    }, controller.signal, requestId)) {
      if (event.event === 'agent_turn_start') {
        onPhase('Orchestrator started; waiting for inference...');
      } else if (event.event === 'inference_start') {
        if (inferenceStartMs === null) inferenceStartMs = Math.round(performance.now() - start);
        onPhase('Inference started; waiting for the first token...');
      } else if (event.event === 'tool_call_start') {
        toolEvents += 1;
        onPhase('Orchestrator is using a tool...');
      }
      if (event.event) continue;
      try {
        const payload = JSON.parse(event.data) as {
          choices?: Array<{ delta?: { content?: string | null }; finish_reason?: string | null }>;
        };
        const choice = payload.choices?.[0];
        if (choice?.delta?.content) {
          if (firstTokenMs < 0) firstTokenMs = Math.round(performance.now() - start);
          reply += choice.delta.content;
          onPhase('Receiving the response...');
        }
        if (choice?.finish_reason) finishReason = choice.finish_reason;
      } catch {
        // Ignore non-JSON metadata: streamChat separately verifies [DONE].
      }
    }

    if (!finishReason || !reply.trim()) {
      throw new Error('Orchestrator completed without a textual reply or finish_reason.');
    }
    return {
      model,
      reply,
      totalMs: Math.round(performance.now() - start),
      firstTokenMs,
      inferenceStartMs,
      finishReason,
      toolEvents,
    };
  } catch (error) {
    if (timedOut) throw new Error('Self-test timed out; server-side cancellation requested.');
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}
