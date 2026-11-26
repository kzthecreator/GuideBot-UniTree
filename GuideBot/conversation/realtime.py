"""Realtime adapter allowing non-retrieval services without weakening conversation defaults."""
from GuideBot.conversation.stepfun import RealtimeSession


class ServiceRealtimeSession(RealtimeSession):
    requires_knowledge = False
