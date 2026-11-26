"""Register tour scripts and pre-generate StepFun TTS; never starts hardware."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from GuideBot.tour.assets import CONFIG
from GuideBot.tour.registration import prepare


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=CONFIG)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if args.dry_run:
        result = prepare(args.config, dry_run=True)
    else:
        from GuideBot.conversation.knowledge import load_secret
        from GuideBot.conversation.stepfun_tts import StepFunTTS
        client = StepFunTTS(load_secret())
        try:
            result = prepare(args.config, client=client)
        finally:
            client.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
