import React from 'react';
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {FONTS} from '../theme';

/** Native-looking text hook at the top for the first seconds (sound-off viewers). */
export const HookText: React.FC<{text: string; seconds?: number}> = ({text, seconds = 2.8}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const end = seconds * fps;
  if (frame >= end) return null;
  const enter = spring({frame, fps, config: {damping: 12, stiffness: 200}, durationInFrames: 8});
  const exit = interpolate(frame, [end - 6, end], [1, 0], {extrapolateLeft: 'clamp'});
  return (
    <AbsoluteFill style={{alignItems: 'center', paddingTop: 260}}>
      <div style={{
        background: '#FFFFFF', color: '#111111', fontFamily: FONTS.heading, fontWeight: 900, fontSize: 64,
        lineHeight: 1.15, padding: '18px 34px', borderRadius: 20, maxWidth: 860, textAlign: 'center',
        transform: `scale(${interpolate(enter, [0, 1], [0.7, 1])})`, opacity: Math.min(enter, exit),
        boxShadow: '0 10px 30px rgba(0,0,0,.35)',
      }}>
        {text}
      </div>
    </AbsoluteFill>
  );
};
