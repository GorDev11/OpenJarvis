import { describe, expect, it } from 'vitest';
import { splitSpeechText } from './speech-chunks';

describe('Armenian progressive speech segments', () => {
  it('returns no segments for empty input', () => {
    expect(splitSpeechText(' \n \t ')).toEqual([]);
  });

  it('keeps a short Armenian phrase intact', () => {
    expect(splitSpeechText('Բարև, ես Ջարվիսն եմ։')).toEqual([
      'Բարև, ես Ջարվիսն եմ։',
    ]);
  });

  it('splits long replies on sentence boundaries', () => {
    const text = 'Բարև, ես Ջարվիսն եմ։ Ինչպե՞ս կարող եմ օգնել ձեզ։ ' +
      'Հիմա ես արագ եմ խոսում հայերեն։';
    const result = splitSpeechText(text, 42);
    expect(result.length).toBeGreaterThan(1);
    expect(result.every((part) => part.length <= 42)).toBe(true);
    expect(result.join(' ')).toBe(text);
  });

  it('splits overlong unpunctuated text on spaces', () => {
    const text = Array(55).fill('բառ').join(' ');
    const result = splitSpeechText(text);
    expect(result.length).toBeGreaterThan(1);
    expect(result.every((part) => part.length <= 120)).toBe(true);
    expect(result.join(' ')).toBe(text);
  });

  it('preserves dotted Latin product names for backend pronunciation', () => {
    const text = 'Ես օգտագործում եմ Node.js։ Այն աշխատում է։';
    const segments = splitSpeechText(text, 28);
    expect(segments).toEqual([
      'Ես օգտագործում եմ Node.js։',
      'Այն աշխատում է։',
    ]);
  });

  it('validates the segment size', () => {
    expect(() => splitSpeechText('Բարև', 8)).toThrow('maxChars');
  });
});
