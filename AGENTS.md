# Agent entry point

Read `docs/AGENT_HANDOFF.md` when taking over this project. Its opening summary
contains current progress, validated limits, and links to detailed evidence.
This timestamp optimization round is closed; follow the user's next task.

The user restores downloaded audio manually at `~/GuideBot-UniTree/recordings`.
Use `docs/AGENT_HANDOFF.md` as the authoritative handoff, independently of that folder.

Keep runtime audio manually triggered by Enter. Use the named GuideBot Conda
environment; store SDKs/models outside business code and credentials/recordings
outside Git. For installation or dependency changes, read `docs/setup.md` and use
the Python 3.8 environment and pinned `requirements.txt` (`requirement.txt` is an alias).
