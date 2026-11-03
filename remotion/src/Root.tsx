import React from 'react';
import {CalculateMetadataFunction, Composition, Still} from 'remotion';
import {AdVideo, adTimeline} from './compositions/AdVideo';
import {Carousel, PostStill} from './compositions/PostStill';
import {TemplatePromo, promoTimeline} from './compositions/TemplatePromo';
import type {AdVideoProps, CarouselProps, PostProps, TemplatePromoProps} from './types';

// Defaults keep Remotion Studio usable without props; real renders always pass props from render.py.
const demoWords = 'Your week feels blurry? Write one line a day and see the pattern.'
  .split(' ').map((text, i) => ({text, start: 0.3 + i * 0.42, end: 0.3 + i * 0.42 + 0.38}));

const adDefaults: AdVideoProps = {
  clips: [], captions: {words: demoWords, style: 'pop', emphasis: ['pattern']}, hookText: 'POV: you finally get it',
  endCard: {appName: 'App Name', headline: 'Try it free', seconds: 3, extendSeconds: 1.5},
};
const promoDefaults: TemplatePromoProps = {
  scenes: [
    {duration: 2.5, kicker: 'New', title: 'Your days, *one* score'},
    {duration: 3, title: 'Write one line', body: 'We turn it into a weekly *pattern*.'},
  ],
  captions: {words: demoWords, style: 'box'},
  endCard: {appName: 'App Name', headline: 'Download now', seconds: 3},
};
const postDefaults: PostProps = {title: 'Find *calm* in five minutes a day', kicker: 'Tip', body: 'One line. Every night.', cta: 'Try free'};
const carouselDefaults: CarouselProps = {slides: [
  {title: '3 signs you need a *reset*', layout: 'center'},
  {kicker: '1', title: 'Every day feels the *same*'},
  {kicker: '2', title: 'You forget what made you *happy*'},
]};

const size = (p: {width?: number; height?: number}, w: number, h: number) => ({width: p.width ?? w, height: p.height ?? h});

const adMeta: CalculateMetadataFunction<AdVideoProps> = ({props}) => {
  const fps = props.fps ?? 30;
  return {fps, durationInFrames: Math.max(1, adTimeline(props, fps).total || 150), ...size(props, 1080, 1920)};
};
const promoMeta: CalculateMetadataFunction<TemplatePromoProps> = ({props}) => {
  const fps = props.fps ?? 30;
  return {fps, durationInFrames: Math.max(1, promoTimeline(props, fps).total), ...size(props, 1080, 1920)};
};
const postMeta: CalculateMetadataFunction<PostProps> = ({props}) => size(props, 1080, 1350);
const carouselMeta: CalculateMetadataFunction<CarouselProps> = ({props}) =>
  ({durationInFrames: Math.max(1, props.slides.length), fps: 1, ...size(props, 1080, 1350)});

export const Root: React.FC = () => (
  <>
    <Composition id="AdVideo" component={AdVideo} width={1080} height={1920} fps={30} durationInFrames={150}
      defaultProps={adDefaults} calculateMetadata={adMeta} />
    <Composition id="TemplatePromo" component={TemplatePromo} width={1080} height={1920} fps={30} durationInFrames={150}
      defaultProps={promoDefaults} calculateMetadata={promoMeta} />
    <Still id="PostStill" component={PostStill} width={1080} height={1350} defaultProps={postDefaults} calculateMetadata={postMeta} />
    <Composition id="Carousel" component={Carousel} width={1080} height={1350} fps={1} durationInFrames={3}
      defaultProps={carouselDefaults} calculateMetadata={carouselMeta} />
  </>
);
