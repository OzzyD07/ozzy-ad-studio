import {loadFont as loadMontserrat} from '@remotion/google-fonts/Montserrat';
import {loadFont as loadInter} from '@remotion/google-fonts/Inter';

// latin-ext carries the Turkish letters (ğ, ş, İ, ı).
const montserrat = loadMontserrat('normal', {weights: ['600', '800', '900'], subsets: ['latin', 'latin-ext']});
const inter = loadInter('normal', {weights: ['400', '600'], subsets: ['latin', 'latin-ext']});

export const FONTS = {heading: montserrat.fontFamily, body: inter.fontFamily};

export type Theme = {
  primary: string; // CTA pill, accents
  highlight: string; // active caption word, *emphasis* in titles
  text: string;
  background: string;
  backgroundAlt: string; // second gradient stop for template scenes
};

// Same colours as the FFmpeg/ASS pipeline: TikTok red accent, yellow highlight.
export const DEFAULT_THEME: Theme = {
  primary: '#FE2C55',
  highlight: '#FFE500',
  text: '#FFFFFF',
  background: '#0B0B12',
  backgroundAlt: '#2A1640',
};

export const theme = (t?: Partial<Theme>): Theme => ({...DEFAULT_THEME, ...(t ?? {})});
