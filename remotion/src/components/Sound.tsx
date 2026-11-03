import React from 'react';
import {Audio, interpolate} from 'remotion';
import {src} from '../lib/media';
import type {AudioTrack, MusicTrack, Word} from '../types';

export const Voiceover: React.FC<{track: AudioTrack}> = ({track}) => {
  return <Audio src={src(track.src)} volume={track.volume ?? 1} />;
};

/** Background music that dips under speech (the FFmpeg pipeline's sidechain, done with word timings). */
export const Music: React.FC<{track: MusicTrack; words?: Word[]; fps: number; durationInFrames: number}> = ({track, words = [], fps, durationInFrames}) => {
  const base = track.volume ?? 0.22;
  const duck = track.duck ?? 0.35;
  const fadeOut = Math.round(fps * 1.2);
  return (
    <Audio
      src={src(track.src)}
      loop
      trimBefore={Math.round((track.trimBefore ?? 0) * fps)}
      volume={(f) => {
        const t = f / fps;
        // Distance (s) to the nearest spoken word; fully ducked inside speech, back up over 0.4 s.
        const near = words.reduce((d, w) => Math.min(d, t < w.start ? w.start - t : t > w.end ? t - w.end : 0), Infinity);
        const speech = interpolate(near, [0, 0.4], [duck, 1], {extrapolateRight: 'clamp'});
        const fade = interpolate(f, [0, 8, durationInFrames - fadeOut, durationInFrames], [0, 1, 1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
        return base * speech * fade;
      }}
    />
  );
};
