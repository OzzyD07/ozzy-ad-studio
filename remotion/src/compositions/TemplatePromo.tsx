import React from 'react';
import {AbsoluteFill, Img, OffthreadVideo, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {TransitionSeries, linearTiming} from '@remotion/transitions';
import {Captions} from '../components/Captions';
import {EndCard} from '../components/EndCard';
import {Rich} from '../components/Rich';
import {Music, Voiceover} from '../components/Sound';
import {frames, isVideo, src, transitionFrames} from '../lib/media';
import {FONTS, Theme, theme as makeTheme} from '../theme';
import type {Scene, SceneMedia, TemplatePromoProps} from '../types';
import {presentation} from './AdVideo';

export const promoTimeline = (p: TemplatePromoProps, fps: number) => {
  const overlap = transitionFrames(p.transition ?? {type: 'slide'}, fps);
  const sceneFrames = p.scenes.map((s) => frames(s.duration, fps));
  const cardFrames = p.endCard ? frames(p.endCard.seconds ?? 3, fps) : 0;
  const parts = [...sceneFrames, ...(cardFrames ? [cardFrames] : [])];
  const total = parts.reduce((a, b) => a + b, 0) - overlap * Math.max(0, parts.length - 1);
  return {overlap, sceneFrames, cardFrames, total, cardStart: total - cardFrames};
};

const Background: React.FC<{theme: Theme}> = ({theme}) => {
  const frame = useCurrentFrame();
  const angle = 160 + Math.sin(frame / 90) * 20;
  return <AbsoluteFill style={{background: `linear-gradient(${angle}deg, ${theme.background} 20%, ${theme.backgroundAlt} 100%)`}} />;
};

const Media: React.FC<{media: SceneMedia}> = ({media}) => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const enter = spring({frame: frame - 6, fps, config: {damping: 16}, durationInFrames: 18});
  const zoom = interpolate(frame, [0, durationInFrames], [1, 1.06]);
  const inner = isVideo(media.src) || media.kind === 'video'
    ? <OffthreadVideo src={src(media.src)} muted style={{width: '100%', height: '100%', objectFit: 'cover'}} />
    : <Img src={src(media.src)} style={{width: '100%', height: '100%', objectFit: 'cover', transform: `scale(${zoom})`}} />;
  const phone = media.device !== 'none';
  return (
    <div style={{
      width: phone ? 550 : 940, height: phone ? 1080 : 940, borderRadius: phone ? 70 : 36, overflow: 'hidden',
      border: phone ? '14px solid #111' : 'none', boxShadow: '0 40px 90px rgba(0,0,0,.55)', background: '#000',
      transform: `translateY(${(1 - enter) * 220}px) rotate(${(1 - enter) * -4}deg)`, opacity: enter,
    }}>
      {inner}
    </div>
  );
};

const SceneView: React.FC<{scene: Scene; theme: Theme}> = ({scene, theme}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  // Split into words but keep *multi word* highlights: each word carries its own flag.
  const words = (scene.title ?? '').split(/(\*[^*]+\*)/).flatMap((part) => {
    const starred = part.length > 2 && part.startsWith('*') && part.endsWith('*');
    return (starred ? part.slice(1, -1) : part).split(' ').filter(Boolean).map((w) => (starred ? `*${w}*` : w));
  });
  const kicker = spring({frame, fps, config: {damping: 14}, durationInFrames: 12});
  const body = spring({frame: frame - 10, fps, config: {damping: 16}, durationInFrames: 14});
  const top = scene.align === 'top' || !!scene.media;
  return (
    <AbsoluteFill>
      <Background theme={theme} />
      <AbsoluteFill style={{alignItems: 'center', justifyContent: top ? 'flex-start' : 'center', padding: top ? '170px 80px 0' : '0 80px', gap: 28}}>
        {scene.kicker && (
          <div style={{fontFamily: FONTS.heading, fontWeight: 800, fontSize: 40, letterSpacing: 4, color: theme.highlight,
            textTransform: 'uppercase', opacity: kicker, transform: `translateY(${(1 - kicker) * 20}px)`}}>
            {scene.kicker}
          </div>
        )}
        {scene.title && (
          <div style={{fontFamily: FONTS.heading, fontWeight: 900, fontSize: scene.media ? 78 : 104, lineHeight: 1.05,
            color: theme.text, textAlign: 'center', display: 'flex', flexWrap: 'wrap', justifyContent: 'center', gap: '0 22px'}}>
            {words.map((w, i) => {
              // Words land one after another (kinetic typography).
              const p = spring({frame: frame - 3 - i * 3, fps, config: {damping: 13, stiffness: 160}, durationInFrames: 12});
              return <span key={i} style={{display: 'inline-block', opacity: p, transform: `translateY(${(1 - p) * 60}px)`}}><Rich text={w} highlight={theme.highlight} /></span>;
            })}
          </div>
        )}
        {scene.body && (
          <div style={{fontFamily: FONTS.body, fontWeight: 400, fontSize: 44, lineHeight: 1.35, color: theme.text,
            opacity: body * 0.9, textAlign: 'center', maxWidth: 880}}>
            <Rich text={scene.body} highlight={theme.highlight} />
          </div>
        )}
        {scene.media && <div style={{marginTop: 30}}><Media media={scene.media} /></div>}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

/** AI-free promo: kinetic type + screenshots/recordings + voiceover; ends on the brand card. */
export const TemplatePromo: React.FC<TemplatePromoProps> = (props) => {
  const {fps} = useVideoConfig();
  const t = makeTheme(props.theme);
  const tl = promoTimeline(props, fps);
  const pres = presentation(props.transition ?? {type: 'slide'});
  return (
    <AbsoluteFill style={{backgroundColor: t.background}}>
      <TransitionSeries>
        {props.scenes.map((scene, i) => (
          <React.Fragment key={i}>
            {i > 0 && tl.overlap > 0 && <TransitionSeries.Transition presentation={pres} timing={linearTiming({durationInFrames: tl.overlap})} />}
            <TransitionSeries.Sequence durationInFrames={tl.sceneFrames[i]}>
              <SceneView scene={scene} theme={t} />
            </TransitionSeries.Sequence>
          </React.Fragment>
        ))}
        {props.endCard && tl.overlap > 0 && <TransitionSeries.Transition presentation={pres} timing={linearTiming({durationInFrames: tl.overlap})} />}
        {props.endCard && (
          <TransitionSeries.Sequence durationInFrames={tl.cardFrames}>
            <Background theme={t} />
            <EndCard card={props.endCard} theme={t} blurBackdrop={false} />
          </TransitionSeries.Sequence>
        )}
      </TransitionSeries>
      {props.voiceover && <Voiceover track={props.voiceover} />}
      {props.music && <Music track={props.music} words={props.captions?.words} fps={fps} durationInFrames={tl.total} />}
      {props.captions && <Captions captions={{bottom: 260, ...props.captions, until: props.endCard ? tl.cardStart / fps : props.captions.until}} theme={t} />}
    </AbsoluteFill>
  );
};
