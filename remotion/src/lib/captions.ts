import type {Word} from '../types';

// Port of media.py word_groups/upper_word so both pipelines caption the same way.

export const upperWord = (word: string, language = 'tr') => {
  if (language !== 'tr') return word.toUpperCase();
  // Brand names with inner capitals (MentorAi'yi) keep Latin I; the Turkish suffix does not.
  const cut = word.search(/['’]/);
  const stem = cut < 0 ? word : word.slice(0, cut);
  const suffix = cut < 0 ? '' : word.slice(cut);
  if (/[a-zçğıöşü][A-ZÇĞİÖŞÜ]/.test(stem)) return stem.toUpperCase() + suffix.toLocaleUpperCase('tr-TR');
  return word.toLocaleUpperCase('tr-TR');
};

// Trailing commas/periods look noisy at caption size; keep ! and ? for tone.
export const cleanWord = (text: string, language = 'tr') => upperWord(text.replace(/[.,;:…]+$/, '') || text, language);

export const norm = (text: string) => text.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, '');

export type Group = {words: Word[]; start: number; end: number};

/** Short punchy groups of 1–3 words, held until the next group (short gaps) so captions don't flicker. */
export const wordGroups = (words: Word[], maxWords = 3, maxChars = 16): Group[] => {
  const groups: Word[][] = [];
  let current: Word[] = [];
  for (const raw of words) {
    const w = {...raw, text: raw.text.trim()};
    if (!w.text) continue;
    if (current.length && (current.length >= maxWords ||
        [...current, w].map((x) => x.text).join(' ').length > maxChars ||
        w.start - current[current.length - 1].end > 0.6)) {
      groups.push(current);
      current = [];
    }
    current.push(w);
    if (/[.!?,;:]$/.test(w.text)) {
      groups.push(current);
      current = [];
    }
  }
  if (current.length) groups.push(current);
  return groups.map((g, i) => {
    const next = i + 1 < groups.length ? groups[i + 1][0].start : Infinity;
    const last = g[g.length - 1].end;
    return {words: g, start: g[0].start, end: next - last < 0.8 ? next : last + 0.35};
  });
};
