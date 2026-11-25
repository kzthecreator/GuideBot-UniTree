"""GuideBot's only production entrypoint; bootstrap the ROS2-managed system."""
import signal
import sys

from GuideBot.runtime.launcher import main

if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as error:
        raise SystemExit(str(error))
