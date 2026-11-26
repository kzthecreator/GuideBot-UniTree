"""Exercise real SDK initialization with DDS constructors replaced; no network or audio."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from runtime.app.environment import sdk_environment


@unittest.skipUnless(Path(os.environ.get('UNITREE_SDK_PATH',
    '/opt/unitree_robotics/unitree_sdk2_python')).is_dir(), 'Shared Unitree SDK not installed')
class DDSLoggingTests(unittest.TestCase):
    def test_sdk_uses_writable_process_log_in_account_state_directory(self):
        source = r'''
import os
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET
from GuideBot.robot.audio.runtime import load_audio_sdk
initialize, _ = load_audio_sdk()
from unitree_sdk2py.core import channel
paths = []
def domain(domain_id, config):
    output = Path(ET.fromstring(config).find('.//Tracing/OutputFile').text)
    expected = Path(os.environ['XDG_STATE_HOME'])/'guidebot'/'dds'
    assert output.parent == expected, 'DDS still uses shared log '+str(output)
    assert str(os.getpid()) in output.name
    assert str(os.getuid()) in output.name
    with output.open('a') as log:
        log.write('isolated validation; no DDS or audio started\n')
    paths.append(output)
    return object()
with patch.object(channel,'Domain',side_effect=domain), patch.object(channel,'DomainParticipant'):
    initialize(0,'eth0')
assert len(paths) == 1
print('PASS: private DDS tracing output is writable; no DDS participant created')
'''
        with tempfile.TemporaryDirectory() as root:
            env = sdk_environment()
            env['XDG_STATE_HOME'] = str(Path(root)/'state & logs')
            result = subprocess.run([os.sys.executable,'-c',source],env=env,
                                    stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stdout)
            self.assertIn('private DDS tracing output is writable',result.stdout)


class DDSConfigurationTests(unittest.TestCase):
    def test_only_trace_filename_changes_and_untraced_configuration_is_preserved(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from xml.etree import ElementTree as ET
        from GuideBot.robot.audio.runtime import _configure_dds_logging
        interface = ('<CycloneDDS><Domain Id="any"><General><Interfaces>'
                     '<NetworkInterface name="$__IF_NAME__$" priority="default"/>'
                     '</Interfaces></General><Tracing><Verbosity>config</Verbosity>'
                     '<OutputFile>/tmp/cdds.LOG</OutputFile></Tracing></Domain></CycloneDDS>')
        automatic = '<CycloneDDS><Domain><General/></Domain></CycloneDDS>'
        channel = SimpleNamespace(ChannelConfigHasInterface=interface, ChannelConfigAutoDetermine=automatic)
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'XDG_STATE_HOME':root}):
            _configure_dds_logging(channel)
            first = channel.ChannelConfigHasInterface
            _configure_dds_logging(channel)
            self.assertEqual(channel.ChannelConfigHasInterface,first)
            tree = ET.fromstring(first)
            self.assertEqual(tree.find('.//Tracing/Verbosity').text,'config')
            self.assertEqual(tree.find('.//NetworkInterface').get('name'),'$__IF_NAME__$')
            output = Path(tree.find('.//Tracing/OutputFile').text)
            self.assertEqual(output.parent,Path(root)/'guidebot/dds')
            self.assertTrue(output.parent.is_dir())
            tree.find('.//Tracing/OutputFile').text = '/tmp/cdds.LOG'
            self.assertEqual(ET.tostring(tree),ET.tostring(ET.fromstring(interface)))
        self.assertEqual(channel.ChannelConfigAutoDetermine,automatic)
