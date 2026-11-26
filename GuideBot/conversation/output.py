"""One narration producer, sharing the Realtime speaker and its AEC reference."""
from GuideBot.tour.assets import read_pcm


def play_segment(speaker, bundle, key, response_id):
    pcm = read_pcm(bundle, key)
    # feed expects the same 24kHz PCM16 used by cloud replies.
    for offset in range(0, len(pcm), 48000):
        speaker.feed(response_id, pcm[offset:offset+48000])
    speaker.finish(response_id)
