import argparse
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import media
import minimax
import mcp_bridge
import pipeline


class PipelineTests(unittest.TestCase):
    def test_srt_unicode_and_bounds(self):
        segments = media.read_srt('examples/demo.srt')
        media.validate_segments(segments, 6)
        self.assertIn('Türkçe', segments[1]['text'])
        with self.assertRaises(ValueError):
            media.validate_segments(segments, 2)

    def test_ass_text_cannot_inject_commands(self):
        text = media.escape_ass(r'{\pos(1,2)}click\Nnow')
        self.assertNotIn('{', text)
        self.assertNotIn('\\', text)

    def test_styled_subtitles_highlight_each_word(self):
        segments = media.read_srt('examples/demo.srt')
        ass = media.make_ass(segments, 6, 'Hemen keşfet', 4, 'pop')
        events = [l for l in ass.splitlines() if l.startswith('Dialogue: 1,')]
        words = sum(len(s['text'].split()) for s in segments)
        self.assertEqual(len(events), words)  # one event per spoken word
        self.assertIn('TÜRKÇE', ass)
        self.assertIn('KEŞFET', ass)
        self.assertEqual(media.upper_tr('bilgi ılık'), 'BİLGİ ILIK')
        for g in media.word_groups(segments):
            self.assertLessEqual(len(g), 3)
        with self.assertRaises(ValueError):
            media.make_ass(segments, 6, None, 4, 'unknown')

    def test_english_subtitles_use_plain_uppercase(self):
        ass = media.make_ass([{'start': 0, 'end': 2, 'text': 'Write it in MentorAi'}], 3, 'Try MentorAi', 1,
                             'pop', 'en')
        self.assertIn('WRITE', ass)
        self.assertIn('MENTORAI', ass)
        self.assertNotIn('İ', ass)

    def test_script_alignment_fixes_misheard_words(self):
        heard = [{'start': 0, 'end': 3, 'text': 'What do you want to revente',
                  'words': [{'start': i*.5, 'end': i*.5+.4, 'text': w} for i, w in
                            enumerate('What do you want to revente'.split())]},
                 {'start': 3, 'end': 5, 'text': 'on Stick Day? Open Mentor AI,',
                  'words': [{'start': 3+i*.3, 'end': 3+i*.3+.25, 'text': w} for i, w in
                            enumerate('on Stick Day? Open Mentor AI,'.split())]}]
        out = media.align_script(heard, 'What do you want to remember about today? Open MentorAi.')
        self.assertEqual(out[0]['text'], 'What do you want to remember about today?')
        self.assertEqual(out[1]['text'], 'Open MentorAi.')
        self.assertEqual(out[0]['start'], 0)
        media.validate_segments(out, 5)

    def test_plan_from_english_scripts(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            script = {'angle': 'A', 'hook': 'Hook?', 'voiceover': 'Hook? Try Demo.',
                      'visual': 'Desk.', 'caption': 'Caption'}
            p = ws/'product.json'; r = ws/'research.json'
            pipeline.write(p, {'name': 'Demo', 'language': 'en', 'audience': 'users', 'features': ['f'],
                               'cta': 'Try Demo', 'url': 'https://example.com', 'scripts': [script]*2})
            pipeline.write(r, {'findings': [{'finding': 'x', 'implication': 'y', 'url': 'https://example.com',
                                             'checked_on': '2026-10-19'}]})
            pipeline.plan(p, r, '2026-10-20', 2, ws)
            jobs = [pipeline.read(j) for j in sorted((ws/'jobs').glob('*.json'))]
            self.assertEqual([j['language'] for j in jobs], ['en', 'en'])
            self.assertIn('English-language', jobs[0]['prompt'])
            self.assertEqual(jobs[0]['prompt'].count('Demo'), jobs[0]['voiceover'].count('Demo'))
            self.assertIn('https://example.com', jobs[0]['caption'])
            self.assertTrue((ws/'plans'/'plan-2026-10-20-en.md').exists())
            with self.assertRaises(ValueError):
                pipeline.plan(p, r, '2026-10-20', 3, ws)

    def test_timestamp_carry(self):
        self.assertEqual(media.timestamp(59.9999), '00:01:00,000')
        self.assertEqual(media.timestamp(59.9999, True), '0:01:00.00')

    def test_mcp_mapping(self):
        self.assertEqual(mcp_bridge.expand({'p': ['{{prompt}}']}, {'prompt': 'Türkçe'}), {'p': ['Türkçe']})
        self.assertEqual(mcp_bridge.lookup({'a': [{'url': 'x'}]}, 'a.0.url'), 'x')
        with self.assertRaises(ValueError):
            mcp_bridge.expand('{{missing}}', {})

    def test_path_traversal(self):
        with self.assertRaises(ValueError):
            pipeline.job_path(Path('.'), '../outside')

    def test_minimax_policy_blocks_other_model_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            pipeline.write(ws/'jobs'/'test.json', {'id': 'test', 'status': 'planned'})
            cfg = {'model_policy': 'minimax_h3', 'mcp': {'generate_tool': 'generate_video', 'generate_arguments': {}}}
            with patch('mcp_bridge.call') as call:
                with self.assertRaisesRegex(ValueError, 'MiniMax'):
                    pipeline.generate(argparse.Namespace(id='test', poll=False), cfg, ws)
                call.assert_not_called()

    def test_uncertain_generation_is_not_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            path = ws/'jobs'/'test.json'
            pipeline.write(path, {'id': 'test', 'status': 'planned', 'prompt': 'demo'})
            cfg = {'mcp': {'generate_tool': 'generate', 'generate_arguments': {'prompt': '{{prompt}}'}}}
            args = argparse.Namespace(id='test', poll=False)
            with patch('mcp_bridge.call', side_effect=TimeoutError('unknown result')) as call:
                with self.assertRaises(TimeoutError):
                    pipeline.generate(args, cfg, ws)
                self.assertEqual(pipeline.read(path)['status'], 'submitting')
                with self.assertRaises(ValueError):
                    pipeline.generate(args, cfg, ws)
                self.assertEqual(call.call_count, 1)

    def test_result_persisted_before_failed_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            path = ws/'jobs'/'test.json'
            pipeline.write(path, {'id': 'test', 'status': 'planned', 'prompt': 'demo'})
            cfg = {'mcp': {'generate_tool': 'gen', 'generate_arguments': {},
                           'result_path': 'video_path', 'remote_id_path': 'job_id'}}
            with patch('mcp_bridge.call', return_value={'video_path': 'missing.mp4', 'job_id': 'remote'}):
                with patch('pipeline.acquire', side_effect=OSError('download failed')):
                    with self.assertRaises(OSError):
                        pipeline.generate(argparse.Namespace(id='test', poll=False), cfg, ws)
            job = pipeline.read(path)
            self.assertEqual(job['status'], 'waiting')
            self.assertEqual(job['remote_id'], 'remote')
            self.assertEqual(job['mcp_result']['video_path'], 'missing.mp4')

    def test_lock_exclusion_and_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            with pipeline.lock(tmp):
                with self.assertRaises(ValueError):
                    with pipeline.lock(tmp):
                        pass
            self.assertFalse((Path(tmp)/'.queue.lock').exists())

    def test_batch_resumes_saved_download_without_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            path = ws/'jobs'/'test.json'
            pipeline.write(path, {'id': 'test', 'status': 'waiting',
                                  'mcp_result': {'video_path': 'saved.mp4'}})
            cfg = {'mcp': {'result_path': 'video_path'}}
            with patch('pipeline.acquire', return_value='local.mp4') as acquire:
                with patch('pipeline.generate') as generate, patch('pipeline.render_job') as render:
                    pipeline.run_queue(argparse.Namespace(limit=1), cfg, ws)
                    acquire.assert_called_once()
                    generate.assert_not_called()
                    render.assert_called_once()
            self.assertEqual(pipeline.read(path)['status'], 'raw_ready')

    def test_plan_preserves_existing_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws/'plans').mkdir()
            p = ws/'product.json'; r = ws/'research.json'
            pipeline.write(p, {'name': 'Demo', 'audience': 'users', 'features': ['feature'], 'cta': 'Open', 'url': 'https://example.com'})
            pipeline.write(r, {'findings': [{'finding': 'test', 'implication': 'demo', 'url': 'https://example.com', 'checked_on': '2026-10-18'}]})
            pipeline.plan(p, r, '2026-10-19', 2, ws)
            jobfile = next((ws/'jobs').glob('*.json'))
            job = pipeline.read(jobfile); job['status'] = 'done'; pipeline.write(jobfile, job)
            pipeline.plan(p, r, '2026-10-19', 2, ws)
            self.assertEqual(pipeline.read(jobfile)['status'], 'done')
            self.assertEqual(len(list((ws/'jobs').glob('*.json'))), 2)

    def test_minimax_prompt_structure(self):
        product = {'name': 'Demo', 'look': {'character': 'a man in a grey hoodie'}}
        shot = {'duration': 8, 'camera': ['Push in', 'Pan left'], 'visual': 'He opens a notebook.',
                'voiceover': 'Try Demo tonight.'}
        prompt = minimax.build_prompt(product, shot, index=2, total=2, language='en',
                                      references=[{'role': 'character'}], continuity=True, voice_reference=True)
        self.assertIn('[Push in,Pan left] He opens a notebook.', prompt)
        self.assertIn('<Picture 1> is the character reference', prompt)
        self.assertIn('<Picture 2> is the last frame', prompt)
        self.assertIn('<Audio 1>', prompt)
        self.assertIn('<d>[English] Try Demo tonight.</d>', prompt)
        self.assertEqual(minimax.lint_prompt(prompt, 'Demo', images=2, audios=1), [])
        self.assertTrue(any(l == 'error' for l, _ in minimax.lint_prompt(prompt, 'Demo', images=1, audios=1)))
        with self.assertRaises(ValueError):
            minimax.camera(['Fly around'])

    def test_minimax_lint_catches_known_failures(self):
        errors = lambda issues: [m for l, m in issues if l == 'error']
        self.assertTrue(errors(minimax.lint_prompt('A Demo logo on a mug. <d>[English] Hi.</d>', 'Demo')))
        long_vo = ' '.join(['word'] * 40)
        self.assertTrue(errors(minimax.lint_shot({'duration': 8, 'visual': 'x', 'voiceover': long_vo}, {})))
        self.assertTrue(errors(minimax.lint_copy(['Unlimited AI for everyone'])))
        self.assertFalse(errors(minimax.lint_copy(['AI coach, not a therapist.'])))

    def test_plan_multishot_shares_body_between_hook_variants(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            r = ws/'research.json'
            pipeline.write(r, {'findings': [{'finding': 'x', 'implication': 'y', 'url': 'https://example.com',
                                             'checked_on': '2026-10-19'}]})
            pipeline.plan('examples/product.multishot.example.json', r, '2026-11-01', 1, ws)
            jobs = {j['id']: j for j in map(pipeline.read, (ws/'jobs').glob('*.json'))}
            parents = [j for j in jobs.values() if j.get('role') == 'edit']
            self.assertEqual(sorted(p['variant'] for p in parents), ['A', 'B'])
            self.assertEqual(parents[0]['shots'][1:], parents[1]['shots'][1:])
            body = jobs[parents[0]['shots'][1]]
            self.assertEqual(body['continuity_from'], jobs[parents[0]['shots'][0]]['id'].replace('-hb', '-ha'))
            self.assertTrue(body['voice_from_previous'])
            self.assertNotIn('DemoApp', minimax.outside_speech(body['prompt']))
            self.assertTrue(all(p['voiceover'].endswith('Try DemoApp.') for p in parents))
            # Re-planning keeps the existing ad for that day.
            pipeline.plan('examples/product.multishot.example.json', r, '2026-11-01', 1, ws)
            self.assertEqual(len(list((ws/'jobs').glob('*.json'))), len(jobs))

    def test_shot_waits_for_continuity_and_sends_references(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            pipeline.write(ws/'jobs'/'a.json', {'id': 'a', 'role': 'shot', 'status': 'waiting'})
            path = ws/'jobs'/'b.json'
            pipeline.write(path, {'id': 'b', 'role': 'shot', 'status': 'planned', 'prompt': 'p',
                                  'continuity_from': 'a', 'voice_from_previous': True, 'duration_seconds': 9})
            cfg = {'mcp': {'generate_tool': 'gen', 'generate_arguments': {'prompt': '{{prompt}}', 'images': [],
                                                                           'audios': [], 'duration': 15}}}
            with patch('mcp_bridge.call') as call:
                with self.assertRaises(pipeline.Pending):
                    pipeline.generate(argparse.Namespace(id='b', poll=False), cfg, ws)
                call.assert_not_called()
            self.assertEqual(pipeline.read(path)['status'], 'planned')
            pipeline.write(ws/'jobs'/'a.json', {'id': 'a', 'role': 'shot', 'status': 'raw_ready', 'raw_video': 'a.mp4'})
            with patch('pipeline.continuity_refs', return_value=(Path('f.png'), Path('v.mp3'))), \
                    patch('pipeline.upload', side_effect=lambda f, c, w: 'id_' + Path(f).name), \
                    patch('mcp_bridge.call', return_value={'job_id': 'r1'}) as call:
                pipeline.generate(argparse.Namespace(id='b', poll=False), cfg, ws)
            sent = call.call_args[0][2]
            self.assertEqual((sent['images'], sent['audios'], sent['duration']), (['id_f.png'], ['id_v.mp3'], 9))

    def test_queue_treats_ready_shots_as_complete(self):
        self.assertTrue(pipeline.complete({'role': 'shot', 'status': 'raw_ready'}))
        self.assertFalse(pipeline.complete({'role': 'edit', 'status': 'raw_ready'}))
        self.assertEqual(pipeline.clip_spec('examples/demo.srt@1.5-4')['end'], 4.0)

    def test_end_card_draws_missing_badges_and_stops_captions(self):
        segments = [{'start': 0, 'end': 3, 'text': 'Write three lines tonight'},
                    {'start': 3.2, 'end': 4.4, 'text': 'Try Demo.'}]
        spoken = media.drop_spoken_cta(segments, 'Try Demo', 1)
        self.assertEqual(len(spoken), 1)
        clipped = media.clip_segments(segments, 2)
        self.assertLessEqual(clipped[-1]['end'], 2)
        card = {'start': 3.2, 'end': 6, 'app_name': 'Demo', 'headline': 'Try Demo',
                'stores': ['app_store', 'google_play'], 'drawn': ['google_play']}
        ass = media.make_ass(clipped, 6, None, 3, 'hormozi', 'en', hook_text='Hook!', emphasis=['Demo'],
                             end_card=card)
        self.assertIn('Google Play', ass)
        self.assertNotIn('App Store', ass)  # The official PNG is overlaid by FFmpeg instead.
        self.assertIn('TRY DEMO', ass)
        self.assertIn('Hook!', ass)
        for name in media.SUBTITLE_STYLES:
            media.make_ass(segments, 6, 'Try Demo', 3, name, 'en')

    def test_badges_are_trimmed_to_one_height_and_centred(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            ffmpeg(d, 'app-store.png', ['-f', 'lavfi', '-i', 'color=black:s=564x168,format=rgba'])
            # Google's PNG ships with transparent clear-space around the badge.
            ffmpeg(d, 'google-play.png', ['-f', 'lavfi', '-i', 'color=black@0:s=646x250,format=rgba', '-f', 'lavfi',
                                          '-i', 'color=black:s=564x168', '-filter_complex',
                                          '[0][1]overlay=41:41,format=rgba'])
            card = {'start': 1.0}
            stage = d/'stage'
            stage.mkdir()
            overlays = media.end_card_assets(card, {'badges_dir': str(d)}, stage)
            sizes = [media.probe_image(stage/f) for f, *_ in overlays]
            self.assertEqual(sizes[0], sizes[1])
            self.assertEqual(sizes[0][1], media.BADGE_H)
            left, right = card['badge_x']['app_store'], card['badge_x']['google_play'] + sizes[1][0]
            self.assertLessEqual(abs((left + right) / 2 - 540), 1)

    def test_plan_with_image_video_audio_references_and_real_footage(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            sheet = ffmpeg(ws, 'sheet.png', ['-f', 'lavfi', '-i', 'color=gray:s=64x64'])
            motion = ffmpeg(ws, 'motion.mp4', ['-f', 'lavfi', '-i', 'color=blue:s=64x64:d=4'])
            music = ffmpeg(ws, 'music.mp3', ['-f', 'lavfi', '-i', 'sine=d=5'])
            demo = ffmpeg(ws, 'demo.mp4', ['-f', 'lavfi', '-i', 'color=red:s=64x112:d=8'])
            shot = lambda **k: {'duration': 6, 'camera': ['Push in'], 'visual': 'A woman writes at a desk.',
                                'voiceover': 'Three lines tonight.', **k}
            product = {'name': 'DemoApp', 'cta': 'Try DemoApp', 'language': 'en', 'audience': 'students',
                       'features': ['journal'], 'url': 'https://example.com',
                       'look': {'references': [{'file': sheet, 'role': 'character'}]},
                       'scripts': [{'angle': 'ref test', 'caption': 'c', 'framework': 'free', 'shots': [
                           shot(references=[{'file': motion, 'role': 'trend'}]),
                           {'clip': demo + '@1-6', 'voiceover': 'One tap.'},
                           shot(references=[{'file': music, 'role': 'music'}])]}]}
            pipeline.write(ws/'product.json', product)
            pipeline.write(ws/'research.json', {'findings': [{'finding': 'x', 'implication': 'y', 'checked_on':
                                                              '2026-10-19', 'url': 'https://example.com'}]})
            pipeline.plan(ws/'product.json', ws/'research.json', '2026-11-01', 1, ws)
            jobs = {j['id'][-2:]: j for j in map(pipeline.read, (ws/'jobs').glob('*.json'))}
            hook, clip, last = jobs['ha'], jobs['s2'], jobs['s3']
            self.assertIn('<Video 1> is the trend reference', hook['prompt'])
            self.assertEqual((clip['source'], clip['status'], clip['trim'], clip['duration_seconds']),
                             ('clip', 'raw_ready', [1.0, 6.0], 5.0))
            self.assertEqual(last['continuity_from'], hook['id'])  # skips the screen recording
            self.assertIn('timbre of <Audio 1>', last['prompt'])
            self.assertIn('<Audio 2>: the background music', last['prompt'])
            self.assertIn('gerçek görüntü', (ws/'plans'/'plan-2026-11-01-en.md').read_text(encoding='utf-8'))
            pipeline.write(ws/'jobs'/f"{hook['id']}.json", {**hook, 'status': 'raw_ready', 'raw_video': 'h.mp4'})
            cfg = {'mcp': {'generate_tool': 'gen', 'generate_arguments': {
                'prompt': '{{prompt}}', 'images': [], 'videos': [], 'audios': [], 'duration': 15}}}
            with patch('pipeline.continuity_refs', return_value=(Path('f.png'), Path('v.mp3'))), \
                    patch('pipeline.upload', side_effect=lambda f, c, w: Path(f).name), \
                    patch('mcp_bridge.call', return_value={'job_id': 'r1'}) as call:
                pipeline.generate(argparse.Namespace(id=last['id'], poll=False), cfg, ws)
            sent = call.call_args[0][2]
            self.assertEqual((sent['images'], sent['audios']), (['sheet.png', 'f.png'], ['v.mp3', 'music.mp3']))
            with patch('pipeline.upload', side_effect=lambda f, c, w: Path(f).name), \
                    patch('mcp_bridge.call', return_value={'job_id': 'r2'}) as call:
                pipeline.write(ws/'jobs'/f"{hook['id']}.json", hook)
                pipeline.generate(argparse.Namespace(id=hook['id'], poll=False), cfg, ws)
            self.assertEqual(call.call_args[0][2]['videos'], ['motion.mp4'])
            bad = {**product, 'scripts': [{**product['scripts'][0], 'shots': [shot(references=[
                {'file': motion, 'role': 'character'}])]}]}
            with self.assertRaises(ValueError):
                pipeline.shot_references(bad, bad['scripts'][0]['shots'][0])

    def test_each_app_has_its_own_folder_icon_and_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {'workspace': tmp, 'end_card': {'icon': 'assets/app-icon.png', 'seconds': 3},
                   'subtitles': {'style': 'pop'}}
            pipeline.new_app(cfg, 'fitlog', 'FitLog')
            with self.assertRaises(ValueError):
                pipeline.new_app(cfg, 'fitlog', 'FitLog')
            with self.assertRaises(ValueError):
                pipeline.new_app(cfg, '../x', 'X')
            ws, app_cfg = pipeline.open_app(cfg)  # the only app is the default
            self.assertEqual(ws, Path(tmp)/'apps'/'fitlog')
            self.assertEqual(pipeline.app_file(ws, app_cfg, None, 'product'), ws/'product.json')
            pipeline.new_app(cfg, 'demo', 'Demo')
            with self.assertRaises(ValueError):
                pipeline.open_app(cfg)  # two apps: --app is required
            meta = pipeline.read(ws/'app.json')
            pipeline.write(ws/'app.json', {**meta, 'config': {'subtitles': {'style': 'hormozi'}}})
            ffmpeg(ws/'assets', 'app-icon.png', ['-f', 'lavfi', '-i', 'color=red:s=64x64'])
            ffmpeg(ws/'assets'/'refs', 'face.png', ['-f', 'lavfi', '-i', 'color=red:s=64x64'])
            ws, app_cfg = pipeline.open_app(cfg, 'fitlog')
            self.assertEqual(app_cfg['subtitles']['style'], 'hormozi')
            self.assertEqual(cfg['subtitles']['style'], 'pop')  # the shared config is untouched
            self.assertEqual(app_cfg['end_card'], {'icon': str(ws/'assets'/'app-icon.png'), 'seconds': 3})
            self.assertEqual(pipeline.resolve_asset('assets/refs/face.png', ws), ws/'assets'/'refs'/'face.png')
            self.assertEqual(pipeline.resolve_asset('assets/badges', ws), pipeline.ROOT/'assets'/'badges')
            self.assertEqual(pipeline.apps(cfg), ['demo', 'fitlog'])

    def test_strategy_schedules_trends_and_lists_references(self):
        import strategy
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            refs = ws/'refs'
            refs.mkdir()
            ffmpeg(refs, 'screen.mp4', ['-f', 'lavfi', '-i', 'color=red:s=64x112:d=5'])
            product = pipeline.read('examples/product.multishot.example.json')
            research = {'findings': [{'implication': 'y'}], 'trends': [
                {'topic': 'Old', 'expires': '2026-10-01'},
                {'topic': 'Exam week', 'angle': 'study stress', 'date': '2026-11-03', 'expires': '2026-11-05'}]}
            concepts = strategy.build(product, research, '2026-11-01', 9, ws, refs_dir=refs)
            by_day = {c['day']: c for c in concepts}
            self.assertEqual(by_day['2026-11-03']['framework'], 'trend')
            self.assertEqual(sum(c['framework'] == 'trend' for c in concepts), 1)
            self.assertIn('demo', {c['framework'] for c in concepts})  # footage exists
            text = (ws/'plans'/'strategy-2026-11-01.md').read_text(encoding='utf-8')
            self.assertIn('screen.mp4', text)
            self.assertIn('Exam week', text)
            self.assertIn('free-form', text)
            empty = ws/'none'
            empty.mkdir()
            concepts = strategy.build(product, {'findings': []}, '2026-11-01', 9, ws, refs_dir=empty)
            self.assertNotIn('demo', {c['framework'] for c in concepts})

    def test_montage_cut_keeps_every_clip_on_screen(self):
        import re
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            clips = [ffmpeg(tmp, f'{c}.mp4', ['-f', 'lavfi', '-i', f'color={c}:s=96x168:r=24:d=2', '-f', 'lavfi',
                                              '-i', 'sine=d=2', '-shortest']) for c in ('red', 'blue', 'green')]
            cfg = {'video': {'width': 96, 'height': 168, 'fps': 24}, 'edit': {'transition_seconds': .3}}
            for transitions in (['cut', 'cut'], ['cut', 'fade'], ['fade', 'cut']):
                spec = [{'path': clips[0]}] + [{'path': p, 'transition': t} for p, t in zip(clips[1:], transitions)]
                out = media.assemble(spec, Path(tmp)/f"{'-'.join(transitions)}.mp4", cfg)
                run = subprocess.run([media.ffmpeg(), '-hide_banner', '-i', out['path'], '-map', '0:v', '-f',
                                      'null', '-'], capture_output=True, text=True)
                seconds = int(re.findall(r'frame=\s*(\d+)', run.stderr)[-1]) / 24
                # Before the fix a cut dropped all later video frames while the audio played on.
                self.assertAlmostEqual(seconds, out['duration'], delta=.15, msg=transitions)


def ffmpeg(folder, name, args):
    import subprocess
    out = Path(folder)/name
    single = ['-frames:v', '1'] if name.endswith('.png') else []
    subprocess.run([media.ffmpeg(), '-hide_banner', '-loglevel', 'error', '-y', *args, *single, str(out)],
                   check=True)
    return str(out)


if __name__ == '__main__':
    unittest.main()
