"""The single production process graph. Any node exit shuts down the graph."""
from pathlib import Path
import sys
from launch import LaunchDescription
from launch.actions import EmitEvent, ExecuteProcess, RegisterEventHandler
from launch.event_handlers import OnProcessExit
from launch.events import Shutdown


def generate_launch_description():
    config = str(Path(__file__).resolve().parents[1]/'config/guidebot.yaml')
    processes = [ExecuteProcess(
        cmd=[sys.executable, '-m', 'GuideBot.ros2.nodes.runner', '--node', role,
             '--ros-args', '--params-file', config],
        name='guidebot_'+role, output='screen', sigterm_timeout='10', sigkill_timeout='10')
        for role in ('session','conversation','gesture','motion')]
    handlers = [RegisterEventHandler(OnProcessExit(target_action=process,
        on_exit=[EmitEvent(event=Shutdown(reason='Required GuideBot node exited'))]))
        for process in processes]
    return LaunchDescription([*handlers, *processes])
