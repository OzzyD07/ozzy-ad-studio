import React from 'react';
import {AbsoluteFill, OffthreadVideo, useVideoConfig} from 'remotion';
import {src} from '../lib/media';
import type {Clip as ClipProps} from '../types';

/** One video clip. "contain-blur" fits other aspect ratios over a blurred copy instead of black bars. */
export const Clip: React.FC<{clip: ClipProps; muted?: boolean}> = ({clip, muted}) => {
  const {fps} = useVideoConfig();
  const common = {
    src: src(clip.src),
    trimBefore: Math.round((clip.trimBefore ?? 0) * fps),
  };
  if (clip.fit === 'contain-blur') {
    return (
      <AbsoluteFill style={{backgroundColor: '#000'}}>
        <OffthreadVideo {...common} muted style={{width: '100%', height: '100%', objectFit: 'cover', filter: 'blur(40px) brightness(.6)', transform: 'scale(1.15)'}} />
        <OffthreadVideo {...common} muted={muted || clip.muted} volume={clip.volume ?? 1} style={{width: '100%', height: '100%', objectFit: 'contain'}} />
      </AbsoluteFill>
    );
  }
  return (
    <AbsoluteFill style={{backgroundColor: '#000'}}>
      <OffthreadVideo {...common} muted={muted || clip.muted} volume={clip.volume ?? 1} style={{width: '100%', height: '100%', objectFit: 'cover'}} />
    </AbsoluteFill>
  );
};
