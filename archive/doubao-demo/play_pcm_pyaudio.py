#!/usr/bin/env python3
"""用 PyAudio 流式消费 output.pcm（24kHz / 16bit / mono 裸 PCM）。"""
import sys
import time
from pathlib import Path

import pyaudio

PCM_PATH = Path("output.pcm")
SAMPLE_RATE = 24000
CHANNELS = 1
CHUNK = 4096  # 字节数，约 85ms

def main() -> int:
    if not PCM_PATH.exists():
        print(f"找不到 {PCM_PATH}", file=sys.stderr)
        return 1
    data = PCM_PATH.read_bytes()
    if not data:
        print(f"{PCM_PATH} 是空文件", file=sys.stderr)
        return 1

    print(f"{PCM_PATH}: {len(data)} bytes, 约 {len(data)/(SAMPLE_RATE*2):.1f} 秒")

    pa = pyaudio.PyAudio()
    try:
        stream = pa.open(
            format=pyaudio.paInt16,
            channels=CHANNELS,
            rate=SAMPLE_RATE,
            output=True,
            frames_per_buffer=1024,
        )
    except Exception as e:
        print(f"打开输出流失败: {e}", file=sys.stderr)
        pa.terminate()
        return 1

    try:
        pos = 0
        while pos < len(data):
            chunk = data[pos:pos + CHUNK]
            pos += len(chunk)
            try:
                stream.write(chunk)
            except Exception as e:
                print(f"write 失败: {e}", file=sys.stderr)
                break
        # 给声卡一点时间把缓冲区播完
        time.sleep(0.3)
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())