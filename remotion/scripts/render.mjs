// Renders one job written by render.py: bundle once, then a video (renderMedia) or PNG stills (renderStill).
// Usage: node scripts/render.mjs job.json
// Job: {composition, props, output, publicDir, frames?: number[], crf?, x264Preset?, audioBitrate?}
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {bundle} from '@remotion/bundler';
import {renderMedia, renderStill, selectComposition} from '@remotion/renderer';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const job = JSON.parse(fs.readFileSync(process.argv[2], 'utf-8'));
const log = (event) => console.log(JSON.stringify(event));

const serveUrl = await bundle({entryPoint: path.join(root, 'src', 'index.ts'), publicDir: job.publicDir});
const composition = await selectComposition({serveUrl, id: job.composition, inputProps: job.props});
log({event: 'composition', id: composition.id, width: composition.width, height: composition.height,
  fps: composition.fps, durationInFrames: composition.durationInFrames});

if (job.frames) {
  // Stills: output is a directory for carousels (01.png, 02.png …) or a file for a single still.
  const outputs = [];
  for (const frame of job.frames) {
    const output = job.frames.length > 1 ? path.join(job.output, `${String(frame + 1).padStart(2, '0')}.png`) : job.output;
    fs.mkdirSync(path.dirname(output), {recursive: true});
    await renderStill({composition, serveUrl, output, frame, inputProps: job.props, imageFormat: 'png'});
    outputs.push(output);
  }
  log({event: 'done', outputs});
} else {
  fs.mkdirSync(path.dirname(job.output), {recursive: true});
  let last = -1;
  await renderMedia({
    composition, serveUrl, codec: 'h264', outputLocation: job.output, inputProps: job.props,
    crf: job.crf ?? 16, x264Preset: job.x264Preset ?? 'slow', audioBitrate: job.audioBitrate ?? '320k',
    pixelFormat: 'yuv420p', concurrency: job.concurrency ?? null,
    onProgress: ({progress}) => {
      const pct = Math.floor(progress * 10) * 10;
      if (pct !== last) { last = pct; log({event: 'progress', percent: pct}); }
    },
  });
  log({event: 'done', outputs: [job.output]});
}
