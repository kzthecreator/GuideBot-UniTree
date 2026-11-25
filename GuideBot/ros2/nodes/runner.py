"""One process per ROS node, launched exclusively by guidebot.launch.py."""
import argparse
from .common import *


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--node', required=True, choices=('planner','scheduler','interaction','motion','bridge','session'))
    args, ros_args = parser.parse_known_args()
    config = Path(os.environ['GUIDEBOT_PLANNER_ENV']) if os.environ.get('GUIDEBOT_PLANNER_ENV') else Path('/nonexistent')
    if args.node in {'planner','scheduler'} and config.is_file():
        from dotenv import load_dotenv
        load_dotenv(config, override=False, interpolate=False)
    rclpy.init(args=ros_args)
    if args.node == 'planner':
        from .planner import PlanningNode as Implementation
    elif args.node == 'scheduler':
        from .scheduler import SchedulerNode as Implementation
    elif args.node == 'interaction':
        from .interaction import InteractionNode as Implementation
    elif args.node == 'motion':
        from .motion_gateway import MotionNode as Implementation
    elif args.node == 'bridge':
        from .voice_gateway import BridgeNode as Implementation
    else:
        from .session_manager import SessionManager as Implementation
    manifest = Path(os.environ['GUIDEBOT_SESSION_DIR'])/('node-'+args.node+'.json')
    import sys
    manifest.write_text(json.dumps(dict(pid=os.getpid(), python=sys.executable, version=sys.version.split()[0], role=args.node)))
    node = Implementation()
    executor = MultiThreadedExecutor(num_threads=6)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        if hasattr(node, 'server') and isinstance(node.server, Server):
            node.server.close()
        if getattr(node, 'service', None):
            node.service.close()
        executor.shutdown(timeout_sec=5)
        if hasattr(node, 'session_state'):
            node.session_state.close()
        # Foxy does not destroy action waitables with the node.
        for waitable in list(node.waitables):
            if isinstance(waitable, (ActionClient, ActionServer)):
                waitable.destroy()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
