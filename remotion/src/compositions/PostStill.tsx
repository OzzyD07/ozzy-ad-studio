import React from 'react';
import {AbsoluteFill, Img, useCurrentFrame} from 'remotion';
import {outline} from '../components/Captions';
import {Rich} from '../components/Rich';
import {src} from '../lib/media';
import {FONTS, Theme, theme as makeTheme} from '../theme';
import type {CarouselProps, PostProps} from '../types';

type Slide = Omit<PostProps, 'width' | 'height' | 'theme'>;

/** One static post. AI images come in text-free; all text, logo and badges are laid out here. */
export const PostView: React.FC<{post: Slide; theme: Theme; width: number; footer?: React.ReactNode}> = ({post, theme, width, footer}) => {
  const k = width / 1080; // sizes are designed at 1080 px wide
  const layout = post.layout ?? 'bottom';
  const shade = post.shade ?? (post.background ? 0.55 : 0);
  const fade = layout === 'top' ? 'to bottom' : 'to top';
  return (
    <AbsoluteFill style={{background: `linear-gradient(160deg, ${theme.background}, ${theme.backgroundAlt})`}}>
      {post.background && <Img src={src(post.background)} style={{width: '100%', height: '100%', objectFit: 'cover'}} />}
      {shade > 0 && <AbsoluteFill style={{background: layout === 'center'
        ? `rgba(0,0,0,${shade})`
        : `linear-gradient(${fade}, rgba(0,0,0,${Math.min(1, shade + 0.3)}) 0%, rgba(0,0,0,${shade}) 45%, rgba(0,0,0,0) 75%)`}} />}
      <AbsoluteFill style={{
        padding: `${90 * k}px ${80 * k}px ${(footer ? 150 : 90) * k}px`, gap: 26 * k,
        justifyContent: layout === 'top' ? 'flex-start' : layout === 'center' ? 'center' : 'flex-end',
        alignItems: layout === 'center' ? 'center' : 'flex-start', textAlign: layout === 'center' ? 'center' : 'left',
      }}>
        {post.kicker && (
          <div style={{fontFamily: FONTS.heading, fontWeight: 800, fontSize: 34 * k, letterSpacing: 4 * k, color: theme.text,
            background: theme.primary, padding: `${8 * k}px ${20 * k}px`, borderRadius: 10 * k, textTransform: 'uppercase'}}>
            {post.kicker}
          </div>
        )}
        <div style={{fontFamily: FONTS.heading, fontWeight: 900, fontSize: 92 * k, lineHeight: 1.04, color: theme.text,
          letterSpacing: -1.5 * k, textShadow: post.background ? `${outline(2 * k, 'rgba(0,0,0,.35)')}, 0 ${6 * k}px ${24 * k}px rgba(0,0,0,.45)` : 'none'}}>
          <Rich text={post.title} highlight={theme.highlight} />
        </div>
        {post.body && (
          <div style={{fontFamily: FONTS.body, fontWeight: 400, fontSize: 40 * k, lineHeight: 1.35, color: theme.text, opacity: 0.92, maxWidth: 900 * k}}>
            <Rich text={post.body} highlight={theme.highlight} />
          </div>
        )}
        {(post.cta || post.icon || post.appName) && (
          <div style={{display: 'flex', alignItems: 'center', gap: 22 * k, marginTop: 14 * k}}>
            {post.icon && <Img src={src(post.icon)} style={{width: 96 * k, height: 96 * k, borderRadius: 24 * k}} />}
            {post.appName && <div style={{fontFamily: FONTS.heading, fontWeight: 800, fontSize: 44 * k, color: theme.text}}>{post.appName}</div>}
            {post.cta && (
              <div style={{fontFamily: FONTS.heading, fontWeight: 900, fontSize: 36 * k, color: '#FFF', background: theme.primary,
                padding: `${16 * k}px ${34 * k}px`, borderRadius: 999, textTransform: 'uppercase'}}>{post.cta}</div>
            )}
          </div>
        )}
        {!!post.badges?.length && (
          <div style={{display: 'flex', gap: 22 * k}}>
            {post.badges.map((b) => <Img key={b} src={src(b)} style={{height: 84 * k}} />)}
          </div>
        )}
      </AbsoluteFill>
      {footer}
    </AbsoluteFill>
  );
};

export const PostStill: React.FC<PostProps> = (props) => (
  <PostView post={props} theme={makeTheme(props.theme)} width={props.width ?? 1080} />
);

/** Frame N = slide N, so render.mjs exports each slide as its own PNG. */
export const Carousel: React.FC<CarouselProps> = (props) => {
  const frame = useCurrentFrame();
  const t = makeTheme(props.theme);
  const width = props.width ?? 1080;
  const k = width / 1080;
  const i = Math.min(props.slides.length - 1, frame);
  return (
        <PostView post={props.slides[i]} theme={t} width={width} footer={props.showIndex === false ? null : (
          <AbsoluteFill style={{justifyContent: 'flex-end', alignItems: 'center', paddingBottom: 56 * k}}>
            <div style={{display: 'flex', gap: 14 * k, alignItems: 'center'}}>
              {props.slides.map((_, j) => (
                <div key={j} style={{width: j === i ? 44 * k : 14 * k, height: 14 * k, borderRadius: 7 * k,
                  background: j === i ? t.highlight : 'rgba(255,255,255,.45)'}} />
              ))}
              {i < props.slides.length - 1 && (
                <div style={{fontFamily: FONTS.heading, fontWeight: 800, fontSize: 30 * k, color: t.text, marginLeft: 18 * k}}>{props.swipeLabel ?? 'SWIPE →'}</div>
              )}
            </div>
          </AbsoluteFill>
        )} />
  );
};
