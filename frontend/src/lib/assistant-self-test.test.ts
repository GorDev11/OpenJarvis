import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAssistantSelfTest } from './assistant-self-test';
import { streamChat } from './sse';

vi.mock('./sse', () => ({
  streamChat: vi.fn(),
  cancelChat: vi.fn().mockResolvedValue(true),
}));

beforeEach(() => {
  vi.clearAllMocks();
});

describe('Orchestrator one-click diagnostic', () => {
  it('uses the normal agent streaming endpoint and requires a real final answer', async () => {
    vi.mocked(streamChat).mockImplementation(async function* () {
      yield { event: 'agent_turn_start', data: '{"agent":"orchestrator"}' };
      yield { event: 'inference_start', data: '{"model":"qwen3.6-colibri"}' };
      yield { data: '{"choices":[{"delta":{"content":"Բարև Ձեզ"}}]}' };
      yield { data: '{"choices":[{"delta":{},"finish_reason":"stop"}]}' };
    });
    const phases: string[] = [];
    const result = await runAssistantSelfTest('qwen3.6-colibri', (phase) => phases.push(phase));

    expect(result.model).toBe('qwen3.6-colibri');
    expect(result.reply).toBe('Բարև Ձեզ');
    expect(result.finishReason).toBe('stop');
    expect(result.firstTokenMs).toBeGreaterThanOrEqual(0);
    expect(phases).toContain('Inference started; waiting for the first token...');
    expect(streamChat).toHaveBeenCalledWith(
      expect.objectContaining({
        model: 'qwen3.6-colibri',
        messages: [{ role: 'user', content: 'Բարև' }],
        stream: true,
      }),
      expect.any(AbortSignal),
      expect.any(String),
    );
  });

  it('does not report success for a stream with no final reply', async () => {
    vi.mocked(streamChat).mockImplementation(async function* () {
      yield { event: 'agent_turn_start', data: '{}' };
    });
    await expect(runAssistantSelfTest('qwen3.6-colibri'))
      .rejects.toThrow('without a textual reply or finish_reason');
  });

  it('rejects an unselected model without contacting the server', async () => {
    await expect(runAssistantSelfTest('')).rejects.toThrow('Choose a model');
    expect(streamChat).not.toHaveBeenCalled();
  });
});
