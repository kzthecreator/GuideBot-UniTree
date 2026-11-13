import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'GuideBot/conversation'))
import knowledge as kb
import conversation
from stepfun import RealtimeSession


class FakeAPI:
    def __init__(self):
        self.uploads = []
        self.remote = set()
        self.stores = 0
        self.fail_wait = False
        self.fail_remove = False
        self.missing = set()

    def request(self, method, path, payload=None):
        assert (method,path) == ('POST','/vector_stores')
        self.stores += 1
        return {'id':'kb-test'}

    def upload(self, path, content):
        self.uploads.append((path.name,content))
        return 'file-' + str(len(self.uploads))

    def wait_file(self, file_id):
        if file_id in self.missing:
            raise kb.KnowledgeAPIError(404,'missing')
        if self.fail_wait:
            raise TimeoutError('parse timeout')

    def associations(self, store_id):
        assert store_id=='kb-test'
        return set(self.remote)

    def attach(self, store_id, file_id):
        self.remote.add(file_id)

    def remove(self, store_id, file_id):
        if self.fail_remove:
            raise RuntimeError('detach failed')
        self.remote.discard(file_id)


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.docs = self.root/'knowledge'
        self.docs.mkdir()
        (self.docs/'a.md').write_text('alpha')
        (self.docs/'b.txt').write_text('beta')
        self.api = FakeAPI()
        self.mock = patch('knowledge.KnowledgeAPI',return_value=self.api)
        self.factory = self.mock.start()
        self.addCleanup(self.mock.stop)
        self.addCleanup(self.temp.cleanup)

    def sync(self, **kwargs):
        return kb.sync_knowledge(self.docs,secret='dummy',state_dir=self.root/'state',**kwargs)

    def load(self):
        return kb.load_knowledge(self.docs,state_dir=self.root/'state')

    def test_initial_sync_then_idempotent_run(self):
        result = self.sync()
        self.assertEqual(result.added,('a.md','b.txt'))
        self.assertEqual(self.load(),'kb-test')
        self.assertEqual(self.api.remote,{'file-1','file-2'})
        result = self.sync()
        self.assertFalse(result.added or result.modified or result.deleted)
        self.assertEqual(len(self.api.uploads),2)
        self.assertEqual(self.api.stores,1)

    def test_modify_add_delete_keeps_store_id(self):
        self.sync()
        (self.docs/'a.md').write_text('alpha updated')
        (self.docs/'b.txt').unlink()
        (self.docs/'nested').mkdir()
        (self.docs/'nested/c.md').write_text('gamma')
        result = self.sync()
        self.assertEqual(result.modified,('a.md',))
        self.assertEqual(result.deleted,('b.txt',))
        self.assertEqual(result.added,('nested/c.md',))
        self.assertEqual(self.api.remote,{'file-3','file-4'})
        self.assertEqual(result.vector_store_id,'kb-test')

    def test_preview_never_contacts_cloud(self):
        result = self.sync(dry_run=True)
        self.assertTrue(result.dry_run)
        self.factory.assert_not_called()
        with self.assertRaises(RuntimeError): self.load()

    def test_parse_failure_resumes_uploaded_file(self):
        self.api.fail_wait = True
        with self.assertRaises(TimeoutError): self.sync()
        with self.assertRaises(RuntimeError): self.load()
        self.assertEqual(len(self.api.uploads),1)
        self.api.fail_wait = False
        self.sync()
        self.assertEqual(len(self.api.uploads),2)
        self.assertEqual(self.load(),'kb-test')

    def test_removal_failure_resumes_cleanup(self):
        self.sync()
        (self.docs/'a.md').write_text('new')
        self.api.fail_remove = True
        with self.assertRaises(RuntimeError): self.sync()
        with self.assertRaises(RuntimeError): self.load()
        self.api.fail_remove = False
        self.sync()
        self.assertEqual(len(self.api.uploads),3)
        self.assertEqual(self.api.remote,{'file-2','file-3'})

    def test_missing_association_repaired_without_upload(self):
        self.sync()
        self.api.remote.remove('file-1')
        result = self.sync()
        self.assertEqual(result.repaired,('a.md',))
        self.assertEqual(len(self.api.uploads),2)
        self.assertIn('file-1',self.api.remote)

    def test_deleted_cloud_file_uploaded_again(self):
        self.sync()
        self.api.remote.remove('file-1')
        self.api.missing.add('file-1')
        self.sync()
        self.assertEqual(self.api.remote,{'file-2','file-3'})

    def test_unmanaged_cloud_file_is_never_deleted(self):
        self.sync()
        self.api.remote.add('not-ours')
        with self.assertRaisesRegex(RuntimeError,'unmanaged'): self.sync()
        self.assertIn('not-ours',self.api.remote)
        with self.assertRaises(RuntimeError): self.load()

    def test_changed_pending_upload_discarded_after_local_rollback(self):
        self.sync()
        (self.docs/'a.md').write_text('updated')
        self.api.fail_wait = True
        with self.assertRaises(TimeoutError): self.sync()
        self.api.remote.add('file-3')
        (self.docs/'a.md').write_text('alpha')
        self.api.fail_wait = False
        self.sync()
        self.assertEqual(self.api.remote,{'file-1','file-2'})

    def test_final_rescan_detects_changes_during_upload(self):
        original = self.api.attach
        def attach(*args):
            original(*args)
            (self.docs/'a.md').write_text('concurrent edit')
        self.api.attach = attach
        with self.assertRaisesRegex(RuntimeError,'changed during'): self.sync()
        with self.assertRaises(RuntimeError): self.load()

    def test_empty_directory_not_uploaded(self):
        for path in self.docs.iterdir(): path.unlink()
        with self.assertRaisesRegex(ValueError,'empty'): self.sync()
        self.factory.assert_not_called()

    def test_symlink_and_unsupported_formats_rejected(self):
        (self.docs/'bad.wav').write_bytes(b'123')
        with self.assertRaisesRegex(ValueError,'Unsupported'): self.sync()
        (self.docs/'bad.wav').unlink()
        (self.docs/'link.md').symlink_to(self.docs/'a.md')
        with self.assertRaisesRegex(ValueError,'symlinks'): self.sync()

    def test_manifest_does_not_store_secret_and_is_private(self):
        self.sync()
        path = kb._manifest_path(self.docs.resolve(),self.root/'state')
        self.assertNotIn('dummy',path.read_text())
        self.assertEqual(path.stat().st_mode & 0o777,0o600)


class SessionTests(unittest.TestCase):
    def session(self):
        s = RealtimeSession('dummy',Path('/tmp/unused-knowledge-test'),
                            instructions='custom soul',vector_store_id='kb-test')
        s.ws = Mock()
        s.speaker = Mock()
        return s

    def test_instructions_and_retrieval_sent_to_cloud(self):
        s = self.session()
        s.on_event({'type':'session.created'})
        payload = json.loads(s.ws.send.call_args.args[0])['session']
        self.assertEqual(payload['instructions'],'custom soul')
        self.assertEqual(payload['tools'][0]['type'],'retrieval')
        self.assertEqual(payload['tools'][0]['function']['options']['vector_store_id'],'kb-test')

    def test_missing_retrieval_confirmation_does_not_start_audio(self):
        s = self.session()
        s.on_event({'type':'session.updated','session':{'turn_detection':{'type':'server_vad'}}})
        self.assertTrue(s.stopping.is_set())
        s.speaker.start.assert_not_called()

    def test_confirmed_retrieval_starts_audio(self):
        s = self.session()
        tools = [{'type':'retrieval','function':{'options':{'vector_store_id':'kb-test'}}}]
        with patch('stepfun.threading.Thread'):
            s.on_event({'type':'session.updated','session':{
                'turn_detection':{'type':'server_vad'},'tools':tools}})
        self.assertTrue(s.ready.is_set())

    def test_sync_failure_never_constructs_audio_session(self):
        with patch('conversation.read_soul',return_value='soul'), \
             patch('conversation.load_secret',return_value='dummy'), \
             patch('conversation.sync_knowledge',side_effect=RuntimeError('sync failed')), \
             patch('conversation.RealtimeSession') as session:
            with self.assertRaisesRegex(RuntimeError,'sync failed'):
                conversation.start_conversation(sync_knowledge_before_start=True)
        session.assert_not_called()

    def test_optional_sync_precedes_manual_audio_start(self):
        for enabled in (False,True):
            with self.subTest(enabled=enabled), \
                 patch('conversation.read_soul',return_value='soul'), \
                 patch('conversation.load_secret',return_value='dummy'), \
                 patch('conversation.sync_knowledge',return_value=kb.SyncResult('kb-test',(),(),())) as sync, \
                 patch('conversation.load_knowledge',return_value='kb-test') as load, \
                 patch('conversation.wait_for_enter',side_effect=RuntimeError('cancel')), \
                 patch('conversation.RealtimeSession') as session:
                with self.assertRaisesRegex(RuntimeError,'cancel'):
                    conversation.start_conversation(sync_knowledge_before_start=enabled)
                self.assertEqual(sync.call_count,int(enabled))
                self.assertEqual(load.call_count,int(not enabled))
                session.return_value.start.assert_not_called()

    def test_soul_requires_nonempty_utf8_file(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)/'soul.md'
            path.write_text('custom persona',encoding='utf-8')
            self.assertEqual(kb.read_soul(root),'custom persona')
            path.write_text(' \n')
            with self.assertRaises(ValueError): kb.read_soul(root)


class TransportTests(unittest.TestCase):
    def test_requests_builds_multipart_upload(self):
        api = kb.KnowledgeAPI('dummy')
        with patch.object(api,'request',return_value={'id':'file-1'}) as request:
            self.assertEqual(api.upload(Path('facts.md'),b'facts'),'file-1')
        self.assertEqual(request.call_args.kwargs['data'],{'purpose':'retrieval-text'})
        self.assertEqual(request.call_args.kwargs['files']['file'][1],b'facts')

    def test_errors_redact_secret(self):
        response = Mock(ok=False,status_code=403,text='dummy invalid')
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch('knowledge.requests.request',return_value=response):
            with self.assertRaises(kb.KnowledgeAPIError) as error:
                kb.KnowledgeAPI('dummy').request('GET','/files/file-1')
        self.assertNotIn('dummy',str(error.exception))


if __name__ == '__main__':
    unittest.main()
