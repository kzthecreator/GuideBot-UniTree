"""Bounded StepFun file TTS; this client never starts a speaker."""
import time
import requests

ENDPOINT = 'https://api.stepfun.com/v1/audio/speech'


class StepFunTTS:
    def __init__(self, secret, session=None):
        if not secret:
            raise ValueError('STEP_SECRET is required')
        self.secret = secret
        self.session = session or requests.Session()
        self.owned = session is None

    def synthesize(self, text, settings):
        if not text.strip() or len(text) > 1000:
            raise ValueError('TTS text must contain 1..1000 characters')
        payload = dict(settings, input=text)
        started = time.monotonic()
        try:
            with self.session.post(ENDPOINT, headers={'Authorization': 'Bearer '+self.secret},
                                   json=payload, stream=True, timeout=(5, 60)) as response:
                if response.status_code != 200:
                    raise RuntimeError('StepFun TTS HTTP {}'.format(response.status_code))
                body = bytearray()
                for part in response.iter_content(65536):
                    body.extend(part)
                    if len(body) > 32*1024*1024 or time.monotonic()-started > 180:
                        raise RuntimeError('StepFun TTS response exceeded limit')
        except requests.RequestException:
            raise RuntimeError('StepFun TTS network failure') from None
        return bytes(body)

    def close(self):
        if self.owned:
            self.owned = False
            self.session.close()
