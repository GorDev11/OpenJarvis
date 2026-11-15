/** Split a completed assistant reply into early playable TTS segments.
 *
 * This is progressive playback over the existing WAV endpoint, not a new
 * streaming protocol: a short first segment may play before later segments
 * have finished synthesizing.
 */
export function splitSpeechText(text: string, maxChars = 120): string[] {
  const normalized = text.trim().replace(/\s+/g, ' ');
  if (!normalized) return [];
  if (maxChars < 16) throw new Error('maxChars must be at least 16');

  // Break at sentence punctuation only when followed by whitespace.
  // Internal dots in names like Node.js / Next.js are not sentence ends:
  // splitting there prevents the Armenian backend from recognizing the name.
  const sentences = normalized.split(/(?<=[.!?։])\s+/u);
  const segments: string[] = [];
  let pending = '';

  for (const raw of sentences) {
    let remaining = raw.trim();
    while (remaining) {
      const needed = pending ? pending.length + 1 + remaining.length : remaining.length;
      if (needed <= maxChars) {
        pending = pending ? pending + ' ' + remaining : remaining;
        break;
      }
      if (pending) {
        segments.push(pending);
        pending = '';
        continue;
      }

      // Prefer breaking at a word boundary, but still cap unusually long words.
      const lastSpace = remaining.lastIndexOf(' ', maxChars);
      const splitAt = lastSpace >= Math.floor(maxChars / 3) ? lastSpace : maxChars;
      segments.push(remaining.slice(0, splitAt).trim());
      remaining = remaining.slice(splitAt).trim();
    }
  }
  if (pending) segments.push(pending);
  return segments;
}
