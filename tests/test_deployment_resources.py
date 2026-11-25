"""Cross-account resource integrity, without running installers or hardware."""
import json
from pathlib import Path
import platform
import tempfile
import unittest

from tools.deployment.setup import MODEL, digest, verify_resources


class DeploymentResourcesTests(unittest.TestCase):
    def package(self, root):
        names = ['localvqe/' + MODEL, 'localvqe/liblocalvqe.so', 'timestamps/model.pt',
                 'timestamps/config.yaml', 'timestamps/am.mvn', 'timestamps/tokens.json',
                 'agc2/libguidebot_agc2.so', 'agc2/libwebrtc-audio-processing-1.so.3']
        files = {}
        for name in names:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'non-secret-fixture')
            files[name] = digest(path)
        manifest = dict(schema_version=1, platform=platform.system(),
                        machine=platform.machine(), files=files)
        (root / 'manifest.json').write_text(json.dumps(manifest))
        return manifest

    def test_modified_model_is_rejected_before_install(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.package(root)
            self.assertEqual(verify_resources(root), manifest['files'])
            (root / 'timestamps/model.pt').write_bytes(b'corrupted-model')
            with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
                verify_resources(root)

    def test_other_architecture_and_incomplete_packages_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.package(root)
            manifest['machine'] = 'different-machine'
            (root / 'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'platform mismatch'):
                verify_resources(root)
            manifest['machine'] = platform.machine()
            del manifest['files']['timestamps/model.pt']
            (root / 'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                verify_resources(root)

    def test_manifest_cannot_escape_resource_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'public'
            root.mkdir()
            manifest = self.package(root)
            private = Path(directory) / 'private'
            private.write_bytes(b'private-fixture')
            manifest['files']['../private'] = digest(private)
            (root / 'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'escapes'):
                verify_resources(root)


if __name__ == '__main__':
    unittest.main()
