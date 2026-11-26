"""Offline registration, immutable assets, and HTTP TTS protocol boundaries."""
import io
import json
from pathlib import Path
import tempfile
import unittest
import wave
from unittest.mock import MagicMock

from GuideBot.tour.assets import plan, load_bundle, read_pcm
from GuideBot.tour.registration import prepare
from GuideBot.conversation.stepfun_tts import StepFunTTS


def wav():
    out = io.BytesIO()
    with wave.open(out, 'wb') as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(24000)
        f.writeframes(b'\0\0'*2400)
    return out.getvalue()


def config(root, scripts=None):
    root = Path(root); root.mkdir(exist_ok=True)
    scripts = scripts or ['欢迎来到我们的展厅。这里展示机器人。','下面请看沙盘。']
    (root/'points.json').write_text(json.dumps(dict(schema_version=1, points=[
        dict(id='p'+str(i),name='点'+str(i),script=s) for i,s in enumerate(scripts)])))
    (root/'speech.json').write_text(json.dumps(dict(model='stepaudio-3-tts',voice='cixingnansheng',
        speed=1.,sample_rate=24000,response_format='wav',max_segment_chars=180)))
    return root


class RegistrationTests(unittest.TestCase):
    def test_dry_run_no_credentials_no_network_no_output_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = config(Path(tmp)/'config'); root = Path(tmp)/'assets'
            result = prepare(cfg, root, dry_run=True)
            self.assertEqual(result['to_generate'], 3)
            self.assertFalse(root.exists())

    def test_cache_reuse_change_invalidation_and_integrity(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = config(Path(tmp)/'config'); root = Path(tmp)/'assets'
            client = MagicMock(); client.synthesize.return_value = wav()
            prepare(cfg, root, client=client)
            self.assertEqual(client.synthesize.call_count, 3)
            bundle = load_bundle(cfg, root)
            key = bundle['definition']['points'][0]['segments'][0]['key']
            self.assertEqual(len(read_pcm(bundle, key)), 4800)
            prepare(cfg, root, client=client)
            self.assertEqual(client.synthesize.call_count, 3)
            data = json.loads((cfg/'points.json').read_text()); data['points'][0]['script'] += '新增内容。'
            (cfg/'points.json').write_text(json.dumps(data))
            with self.assertRaisesRegex(RuntimeError, 'missing or stale'): load_bundle(cfg, root)
            prepare(cfg, root, client=client)
            self.assertEqual(client.synthesize.call_count, 4)
            self.assertTrue((bundle['path']/'manifest.json').exists())
            new = load_bundle(cfg, root)
            (new['path']/'audio'/(key+'.wav')).write_bytes(b'not audio')
            with self.assertRaises(ValueError): load_bundle(cfg, root)

    def test_failed_synthesis_not_published_and_retry_reuses_completed_segment(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = config(Path(tmp)/'config'); root = Path(tmp)/'assets'
            client = MagicMock(); client.synthesize.side_effect = [wav(), RuntimeError('fail')]
            with self.assertRaises(RuntimeError): prepare(cfg, root, client=client)
            self.assertFalse(list((root/'bundles').glob('*/manifest.json')))
            self.assertEqual(len(list((root/'cache').glob('*.wav'))), 1)
            client.synthesize.side_effect = None; client.synthesize.return_value = wav()
            prepare(cfg, root, client=client)
            self.assertEqual(client.synthesize.call_count, 4)
            load_bundle(cfg, root)

    def test_duplicate_point_and_unsafe_id_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = config(tmp)
            original = json.loads((cfg/'points.json').read_text())
            for bad in ('p0', '../escape'):
                data = json.loads(json.dumps(original)); data['points'][1]['id'] = bad
                (cfg/'points.json').write_text(json.dumps(data))
                with self.assertRaises(ValueError): plan(cfg)

    def test_split_preserves_original_and_enforces_tts_length(self):
        with tempfile.TemporaryDirectory() as tmp:
            text = '甲'*1201+'。后一句！'
            cfg = config(tmp, [text]); value = plan(cfg)
            rows = value['points'][0]['segments']
            self.assertEqual(''.join(s['text'] for s in rows), text)
            self.assertTrue(all(len(s['text']) <= 180 for s in rows))
            for row in rows: self.assertEqual(text[row['start']:row['end']], row['text'])

    def test_configuration_change_during_synthesis_never_publishes(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = config(Path(tmp)/'config'); root = Path(tmp)/'assets'
            client = MagicMock()
            def synth(text, settings):
                config(cfg, ['已经改稿。'])
                return wav()
            client.synthesize.side_effect = synth
            with self.assertRaisesRegex(RuntimeError, 'changed during'): prepare(cfg, root, client=client)
            self.assertFalse(list((root/'bundles').glob('*/manifest.json')))

    def test_tts_http_contract_and_sanitized_errors(self):
        session = MagicMock(); response = session.post.return_value.__enter__.return_value
        response.status_code = 200; response.iter_content.return_value = [wav()]
        client = StepFunTTS('private-key', session)
        settings = dict(model='stepaudio-3-tts',voice='cixingnansheng',response_format='wav',sample_rate=24000,speed=1.)
        self.assertEqual(client.synthesize('欢迎。',settings), wav())
        self.assertEqual(session.post.call_args.kwargs['json'], dict(settings,input='欢迎。'))
        response.status_code = 401; response.text = 'private-key sensitive body'
        with self.assertRaisesRegex(RuntimeError, '^StepFun TTS HTTP 401$'): client.synthesize('欢迎。',settings)
        client.close(); session.close.assert_not_called()
