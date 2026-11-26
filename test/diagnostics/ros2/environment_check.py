"""Read-only interpreter/ABI checks. No DDS initialization or device access."""
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from runtime.app.environment import ros_environment, sdk_environment


def main():
    probes = {
      'ros': (ros_environment(), '''import sys,json,rclpy,numpy
from guidebot_interfaces.action import ExecuteGesture
from guidebot_interfaces.msg import ConversationInput
from rosidl_runtime_py.set_message import set_message_fields
value=ConversationInput();set_message_fields(value,{'session_id':'abi-probe'})
print(json.dumps(dict(python=sys.executable,version=sys.version.split()[0],numpy=numpy.__version__,rclpy=rclpy.__file__,message=value.session_id)))'''),
      'sdk': (sdk_environment(), '''import sys,json,cyclonedds
from GuideBot.robot.audio.runtime import load_audio_sdk
load_audio_sdk()
print(json.dumps(dict(python=sys.executable,version=sys.version.split()[0],cyclonedds=cyclonedds.__file__,sdk_import=True)))''')}
    for name, (env, code) in probes.items():
        result = subprocess.run([sys.executable,'-c',code],env=env,text=True,capture_output=True)
        if result.returncode:
            print(result.stderr,file=sys.stderr)
            raise RuntimeError(name+' ABI check failed')
        print(name+': '+result.stdout.strip())


if __name__ == '__main__':
    main()
