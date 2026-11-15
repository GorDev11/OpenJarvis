import { describe, expect, it } from 'vitest';
import { finishStreamingSpeech, safeStreamingText, takeStableStreamingSpeech } from './streaming-speech';

describe('live Armenian text stream', () => {
  it('waits for a completed sentence and then emits it once', () => {
    const first = takeStableStreamingSpeech('Բարև։ Ես Ջարվ');
    expect(first.chunks).toEqual(['Բարև։']);
    const second = takeStableStreamingSpeech('Բարև։ Ես Ջարվիսն եմ։ Հիմա', first.consumed);
    expect(second.chunks).toEqual(['Ես Ջարվիսն եմ։']);
    expect(takeStableStreamingSpeech('Բարև։ Ես Ջարվիսն եմ։ Հիմա', second.consumed).chunks).toEqual([]);
    expect(finishStreamingSpeech('Բարև։ Ես Ջարվիսն եմ։ Հիմա', second.consumed)).toBe('Հիմա');
  });

  it('does not speak hidden or unfinished thinking', () => {
    const a = takeStableStreamingSpeech('<think>Գաղտնի դատողություն։ դեռ շարունակում եմ');
    expect(a.chunks).toEqual([]);
    const b = takeStableStreamingSpeech('<think>Գաղտնի դատողություն։</think> Բարև։ Ես');
    expect(b.chunks).toEqual(['Բարև։']);
    expect(safeStreamingText('Արդյունք։ <think>փակ չեղած գաղտնի միտք։')).toBe('Արդյունք։ ');
  });

  it('waits for a space after punctuation to avoid splitting Node.js', () => {
    const x = takeStableStreamingSpeech('Ես օգտագործում եմ Node.js։ Այն աշխատում է։ Ավարտ');
    expect(x.chunks).toEqual(['Ես օգտագործում եմ Node.js։', 'Այն աշխատում է։']);
  });

  it('does not speak unclosed fenced code', () => {
    const p = takeStableStreamingSpeech('Բարև։ Հետո ```python\nprint(1). Այժմ');
    expect(p.chunks).toEqual(['Բարև։']);
  });

  it('flushes a long sentence at whole words without waiting indefinitely', () => {
    const raw = Array(55).fill('բարև').join(' ');
    const r = takeStableStreamingSpeech(raw);
    expect(r.chunks.length).toBeGreaterThan(0);
    expect(r.chunks.every((s) => s.length <= 120)).toBe(true);
    const combined = [...r.chunks, finishStreamingSpeech(raw, r.consumed)].join(' ');
    expect(combined).toBe(raw);
  });

  it('waits for the word after the sentence-ending punctuation', () => {
    const r = takeStableStreamingSpeech('Բարև։');
    expect(r.chunks).toEqual([]);
    expect(finishStreamingSpeech('Բարև։', r.consumed)).toBe('Բարև։');
  });
});
