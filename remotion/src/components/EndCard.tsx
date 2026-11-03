import React from 'react';
import {AbsoluteFill, Img, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {src} from '../lib/media';
import {FONTS, Theme} from '../theme';
import type {EndCard as EndCardProps} from '../types';

// Both store badges share one height (Apple's rule: equal size, neither store favoured).
const BADGE_HEIGHT = 118;

export const Badges: React.FC<{badges: string[]; delay?: number; height?: number}> = ({badges, delay = 0, height = BADGE_HEIGHT}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  return (
    <div style={{display: 'flex', gap: 28, justifyContent: 'center', alignItems: 'center'}}>
      {badges.map((b, i) => {
        const p = spring({frame: frame - delay - i * 4, fps, config: {damping: 14}, durationInFrames: 12});
        return <Img key={b} src={src(b)} style={{height, transform: `translateY(${(1 - p) * 50}px)`, opacity: p}} />;
      })}
    </div>
  );
};

/** Blurs whatever is underneath, then brings in icon, app name, pulsing CTA pill and store badges. */
export const EndCard: React.FC<{card: EndCardProps; theme: Theme; blurBackdrop?: boolean}> = ({card, theme, blurBackdrop = true}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const at = (s: number) => frame - Math.round(s * fps);
  const blur = interpolate(frame, [0, 10], [0, 26], {extrapolateRight: 'clamp'});
  const icon = spring({frame: at(0.15), fps, config: {damping: 11}, durationInFrames: 14});
  const name = spring({frame: at(0.3), fps, config: {damping: 14}, durationInFrames: 12});
  const pill = spring({frame: at(0.45), fps, config: {damping: 9, stiffness: 180}, durationInFrames: 12});
  const pulse = 1 + 0.05 * Math.max(0, Math.sin(Math.max(0, at(1.1)) / fps * Math.PI * 2 / 0.9));
  const logoOnly = card.brandStyle === 'logo_only' && card.icon;
  return (
    <AbsoluteFill>
      {blurBackdrop && <AbsoluteFill style={{backdropFilter: `blur(${blur}px)`, background: `rgba(0,0,0,${blur / 26 * 0.45})`}} />}
      <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center', gap: 34, paddingBottom: 120}}>
        {card.icon && (
          <Img src={src(card.icon)} style={{
            width: 280, height: 280, borderRadius: 64, boxShadow: '0 18px 50px rgba(0,0,0,.5)',
            transform: `scale(${interpolate(icon, [0, 1], [0.4, 1])})`, opacity: icon,
          }} />
        )}
        {card.appName && !logoOnly && (
          <div style={{fontFamily: FONTS.heading, fontWeight: 900, fontSize: 84, color: theme.text,
            textShadow: '0 4px 14px rgba(0,0,0,.5)', transform: `translateY(${(1 - name) * 40}px)`, opacity: name}}>
            {card.appName}
          </div>
        )}
        {card.headline && !logoOnly && (
          <div style={{fontFamily: FONTS.heading, fontWeight: 900, fontSize: 56, color: '#FFFFFF', background: theme.primary,
            padding: '20px 52px', borderRadius: 999, textTransform: 'uppercase',
            transform: `scale(${interpolate(pill, [0, 1], [0.6, 1]) * pulse})`, opacity: pill}}>
            {card.headline}
          </div>
        )}
        {!!card.badges?.length && <div style={{marginTop: 30}}><Badges badges={card.badges} delay={Math.round(0.55 * fps)} /></div>}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
