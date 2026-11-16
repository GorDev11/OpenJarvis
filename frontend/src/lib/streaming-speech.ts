import { toSpeakableText } from './message-text';
import { splitSpeechText } from './speech-chunks';

/** Hide incomplete <think> blocks. Never read private reasoning aloud. */
export function safeStreamingText(content: string): string {
  let visible = content.replace(/<think>[\s\S]*?<\/think>\s*/gi, '');
  visible = visible.replace(/^[\s\S]*?<\/think>\s*/i, '');
  const openThink = visible.toLowerCase().lastIndexOf('<think>');
  if (openThink !== -1) visible = visible.slice(0, openThink);

  // Don't read an incomplete fenced code block while it is being generated.
  visible = visible.replace(/```[\s\S]*?```/g, ' (code block omitted). ');
  const openFence = visible.lastIndexOf('```');
  if (openFence !== -1) visible = visible.slice(0, openFence);
  return visible;
}

export interface SpeechProgress {
  chunks: string[];
  consumed: number;
}

/**
 * Commit only complete sentences (punctuation followed by whitespace).
 * For an extremely long sentence, cut at a whole word after 120 chars.
 * "Node.js" and fractional numbers are not mistaken for full stops.
 *
 * consumed indexes the visible, reasoning-stripped text, not raw SSE bytes.
 */
export function takeStableStreamingSpeech(
  content: string,
  consumed = 0,
  maxChars = 120,
): SpeechProgress {
  const visible = safeStreamingText(content);
  let cursor = Math.min(Math.max(0, consumed), visible.length);
  const chunks: string[] = [];

  while (cursor < visible.length) {
    const tail = visible.slice(cursor);
    const sentence = /[.!?։]+\s+/u.exec(tail);
    let length = sentence ? sentence.index + sentence[0].length : 0;

    // Don't block forever on a long unpunctuated response.
    if (!length || length > maxChars) {
      if (tail.length <= maxChars + 30 && !length) break;
      const atSpace = tail.lastIndexOf(' ', maxChars);
      if (atSpace >= Math.floor(maxChars / 2)) length = atSpace + 1;
      else if (!length) break;
    }

    const ready = tail.slice(0, length).trim();
    if (ready) {
      const spoken = toSpeakableText(ready);
      if (spoken) chunks.push(...splitSpeechText(spoken, maxChars));
    }
    cursor += length;
  }

  return { chunks, consumed: cursor };
}

/** Return the unfinished tail exactly once after the SSE stream ends. */
export function finishStreamingSpeech(content: string, consumed: number): string {
  return toSpeakableText(safeStreamingText(content).slice(consumed));
}
