import type {Theme} from './theme';

export type Word = {text: string; start: number; end: number}; // seconds

export type CaptionStyle = 'pop' | 'tiktok' | 'hormozi' | 'neon' | 'box' | 'classic' | 'brand';

export type Captions = {
  words: Word[];
  style?: CaptionStyle;
  emphasis?: string[]; // brand names, keywords: always highlighted
  language?: string; // 'tr' uses Turkish upper-casing
  bottom?: number; // px from the bottom edge (ASS margin_v was 640)
  until?: number; // seconds: captions stop here (end card start)
};

export type AudioTrack = {src: string; volume?: number; trimBefore?: number};

export type MusicTrack = AudioTrack & {duck?: number}; // volume factor while someone speaks

export type EndCard = {
  seconds?: number; // how long the card is visible
  extendSeconds?: number; // AdVideo: frozen extra time after the last clip
  appName?: string;
  headline?: string; // CTA pill text
  icon?: string;
  badges?: string[]; // trimmed official store badge images
  brandStyle?: 'full' | 'logo_only';
};

export type Clip = {
  src: string;
  duration: number; // seconds played from trimBefore
  trimBefore?: number; // seconds
  fit?: 'cover' | 'contain-blur';
  muted?: boolean;
  volume?: number;
};

export type Transition = {type?: 'cut' | 'fade' | 'slide' | 'wipe' | 'flip'; seconds?: number};

export type AdVideoProps = {
  width?: number;
  height?: number;
  fps?: number;
  clips: Clip[];
  transition?: Transition;
  voiceover?: AudioTrack;
  music?: MusicTrack;
  captions?: Captions;
  hookText?: string;
  endCard?: EndCard | null;
  theme?: Partial<Theme>;
};

export type SceneMedia = {src: string; kind?: 'image' | 'video'; device?: 'phone' | 'none'; duration?: number};

export type Scene = {
  duration: number; // seconds
  kicker?: string;
  title?: string; // *word* = highlighted
  body?: string;
  media?: SceneMedia;
  align?: 'top' | 'center';
};

export type TemplatePromoProps = {
  width?: number;
  height?: number;
  fps?: number;
  scenes: Scene[];
  transition?: Transition;
  voiceover?: AudioTrack;
  music?: MusicTrack;
  captions?: Captions;
  endCard?: EndCard | null;
  theme?: Partial<Theme>;
};

export type PostProps = {
  width?: number;
  height?: number;
  background?: string | null; // image (e.g. Qwen output, text-free)
  layout?: 'bottom' | 'center' | 'top';
  kicker?: string;
  title: string; // *word* = highlighted
  body?: string;
  cta?: string;
  icon?: string;
  appName?: string;
  badges?: string[];
  shade?: number; // 0..1 darkening over the background
  theme?: Partial<Theme>;
};

export type CarouselProps = {
  width?: number;
  height?: number;
  slides: Omit<PostProps, 'width' | 'height' | 'theme'>[];
  showIndex?: boolean;
  swipeLabel?: string; // e.g. 'KAYDIR →' for Turkish posts
  theme?: Partial<Theme>;
};
