import React from 'react';
import {AbsoluteFill, Freeze, Sequence, useVideoConfig} from 'remotion';
import {TransitionPresentation, TransitionSeries, linearTiming} from '@remotion/transitions';
import {fade} from '@remotion/transitions/fade';
import {slide} from '@remotion/transitions/slide';
import {wipe} from '@remotion/transitions/wipe';
import {flip} from '@remotion/transitions/flip';
import {Captions} from '../components/Captions';
import {Clip} from '../components/Clip';
import {EndCard} from '../components/EndCard';
import {HookText} from '../components/HookText';
import {Music, Voiceover} from '../components/Sound';
import {frames, transitionFrames} from '../lib/media';
import {theme as makeTheme} from '../theme';
import type {AdVideoProps, Transition} from '../types';

// eslint-disable-next-line @typescript-eslint/no-explicit-any -- the four presentations have different prop types
export const presentation = (t?: Transition): TransitionPresentation<any> => {
  switch (t?.type ?? 'fade') {
    case 'slide': return slide({direction: 'from-bottom'});
    case 'wipe': return wipe({direction: 'from-left'});
    case 'flip': return flip();
    default: return fade();
  }
};

/** Timeline in frames; shared by calculateMetadata and the component so they never disagree. */
export const adTimeline = (p: AdVideoProps, fps: number) => {
  const overlap = transitionFrames(p.transition, fps);
  const clipFrames = p.clips.map((c) => frames(c.duration, fps));
  const clipsTotal = clipFrames.reduce((a, b) => a + b, 0) - overlap * Math.max(0, p.clips.length - 1);
  const extend = p.endCard ? frames(p.endCard.extendSeconds ?? 1.5, fps) : 0;
  const total = clipsTotal + extend;
  const cardFrames = p.endCard ? Math.min(total, frames(p.endCard.seconds ?? 3, fps)) : 0;
  return {overlap, clipFrames, clipsTotal, extend, total, cardStart: total - cardFrames};
};

export const AdVideo: React.FC<AdVideoProps> = (props) => {
  const {fps} = useVideoConfig();
  const t = makeTheme(props.theme);
  const tl = adTimeline(props, fps);
  const last = props.clips[props.clips.length - 1];
  return (
    <AbsoluteFill style={{backgroundColor: '#000'}}>
      <TransitionSeries>
        {props.clips.map((clip, i) => (
          <React.Fragment key={i}>
            {i > 0 && tl.overlap > 0 && (
              <TransitionSeries.Transition presentation={presentation(props.transition)} timing={linearTiming({durationInFrames: tl.overlap})} />
            )}
            <TransitionSeries.Sequence durationInFrames={tl.clipFrames[i]}>
              <Clip clip={clip} />
            </TransitionSeries.Sequence>
          </React.Fragment>
        ))}
      </TransitionSeries>
      {tl.extend > 0 && last && (
        // The speech must not be cut: hold the last frame while the end card finishes.
        <Sequence from={tl.clipsTotal} durationInFrames={tl.extend}>
          <Freeze frame={tl.clipFrames[tl.clipFrames.length - 1] - 1}>
            <Clip clip={last} muted />
          </Freeze>
        </Sequence>
      )}
      {props.voiceover && <Voiceover track={props.voiceover} />}
      {props.music && <Music track={props.music} words={props.captions?.words} fps={fps} durationInFrames={tl.total} />}
      {props.captions && (
        <Captions captions={{...props.captions, until: props.endCard ? tl.cardStart / fps : props.captions.until}} theme={t} />
      )}
      {props.hookText && <HookText text={props.hookText} />}
      {props.endCard && (
        <Sequence from={tl.cardStart}>
          <EndCard card={props.endCard} theme={t} />
        </Sequence>
      )}
    </AbsoluteFill>
  );
};
