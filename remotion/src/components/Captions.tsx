import React, {useMemo} from 'react';
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {cleanWord, norm, wordGroups} from '../lib/captions';
import {FONTS, Theme} from '../theme';
import type {CaptionStyle, Captions as CaptionsProps} from '../types';

type Look = {size: number; outline: number; highlight: string; maxWords: number; activeScale: number;
  font: string; box?: boolean; glow?: boolean; plain?: boolean};

// Mirrors SUBTITLE_STYLES in media.py (ASS &HBBGGRR colours converted to CSS).
const looks = (t: Theme): Record<CaptionStyle, Look> => ({
  pop: {size: 92, outline: 7, highlight: '#FFE500', maxWords: 3, activeScale: 1.16, font: FONTS.heading},
  tiktok: {size: 92, outline: 7, highlight: '#FE2C55', maxWords: 3, activeScale: 1.16, font: FONTS.heading},
  hormozi: {size: 104, outline: 8, highlight: '#5BF241', maxWords: 2, activeScale: 1.25, font: FONTS.heading},
  neon: {size: 92, outline: 6, highlight: '#39FF14', maxWords: 3, activeScale: 1.16, font: FONTS.heading, glow: true},
  box: {size: 80, outline: 0, highlight: '#FFE500', maxWords: 3, activeScale: 1.12, font: FONTS.heading, box: true},
  classic: {size: 60, outline: 3, highlight: '#FFFFFF', maxWords: 7, activeScale: 1, font: FONTS.body, plain: true},
  brand: {size: 92, outline: 7, highlight: t.highlight, maxWords: 3, activeScale: 1.16, font: FONTS.heading},
});

// A thick outside stroke built from shadows: crisp on any background, unlike -webkit-text-stroke.
export const outline = (px: number, color = '#000') => {
  if (!px) return 'none';
  const steps = 16;
  return Array.from({length: steps}, (_, i) => {
    const a = (i / steps) * Math.PI * 2;
    return `${(Math.cos(a) * px).toFixed(1)}px ${(Math.sin(a) * px).toFixed(1)}px 0 ${color}`;
  }).join(', ');
};

export const Captions: React.FC<{captions: CaptionsProps; theme: Theme}> = ({captions, theme}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const look = looks(theme)[captions.style ?? 'pop'];
  const language = captions.language ?? 'en';
  const groups = useMemo(() => wordGroups(captions.words, look.maxWords, look.plain ? 42 : 16),
    [captions.words, look.maxWords, look.plain]);
  const keys = useMemo(() => new Set((captions.emphasis ?? []).flatMap((p) => p.split(/\s+/)).map(norm).filter(Boolean)),
    [captions.emphasis]);
  const t = frame / fps;
  if (captions.until !== undefined && t >= captions.until) return null;
  const group = groups.find((g) => g.start <= t && t < g.end);
  if (!group) return null;

  const enter = spring({frame: frame - Math.round(group.start * fps), fps, config: {damping: 12, stiffness: 220}, durationInFrames: 8});
  const groupScale = look.plain ? 1 : interpolate(enter, [0, 1], [0.7, 1]);
  const activeIndex = group.words.reduce((found, w, i) => (w.start <= t ? i : found), 0);
  const shadow = look.glow
    ? `${outline(look.outline, '#001A0A')}, 0 0 28px ${look.highlight}, 0 0 54px ${look.highlight}`
    : look.box ? 'none' : `${outline(look.outline)}, 0 6px 10px rgba(0,0,0,.55)`;

  return (
    <AbsoluteFill style={{justifyContent: 'flex-end', alignItems: 'center', paddingBottom: captions.bottom ?? 640}}>
      <div style={{
        display: 'flex', flexWrap: 'wrap', justifyContent: 'center', gap: look.plain ? '0 16px' : '0 22px',
        maxWidth: 900, transform: `scale(${groupScale})`, opacity: look.plain ? 1 : interpolate(enter, [0, 1], [0.4, 1]),
        padding: look.box ? '14px 30px' : 0, borderRadius: 22,
        background: look.box ? 'rgba(0,0,0,.85)' : look.plain ? 'rgba(0,0,0,.5)' : 'transparent',
      }}>
        {group.words.map((w, i) => {
          const marked = keys.has(norm(w.text)) || /\d/.test(w.text);
          const active = !look.plain && i === activeIndex;
          const pop = active ? spring({frame: frame - Math.round(w.start * fps), fps, config: {damping: 10, stiffness: 260}, durationInFrames: 6}) : 0;
          // Font size, not transform: the line reflows like ASS \fscx, so a big word never covers its neighbours.
          const scale = active ? interpolate(pop, [0, 1], [1, look.activeScale]) : marked ? 1.06 : 1;
          return (
            <span key={i} style={{
              fontFamily: look.font, fontWeight: look.plain ? 600 : 900, fontSize: look.size * scale, lineHeight: 1.12,
              color: active || marked ? look.highlight : theme.text, textShadow: shadow,
              display: 'inline-block', letterSpacing: look.plain ? 0 : -1,
            }}>
              {look.plain ? w.text : cleanWord(w.text, language)}
            </span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
