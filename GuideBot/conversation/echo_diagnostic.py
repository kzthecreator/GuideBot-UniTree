"""Reference/raw-microphone diagnostics without AEC or noise suppression."""

import json
from pathlib import Path
import wave

import numpy as np

RATE = 16000


def load(path):
    with wave.open(str(path)) as source:
        if (source.getframerate(), source.getnchannels(), source.getsampwidth()) != (RATE, 1, 2):
            raise ValueError("Expected 16 kHz mono PCM16")
        return np.frombuffer(source.readframes(source.getnframes()), dtype='<i2').astype(float)


def correlate(search, reference):
    """Normalized, mean-centered correlation at every valid sample offset."""
    if len(search) < len(reference) or len(reference) == 0:
        raise ValueError("Insufficient samples for cross-correlation")
    reference = reference - np.mean(reference)
    energy = float(np.sum(reference**2))
    if energy < 1:
        return None
    size = 1 << (len(search) + len(reference) - 2).bit_length()
    cross = np.fft.irfft(np.fft.rfft(search, size) *
                        np.fft.rfft(reference[::-1], size), size)
    cross = cross[len(reference)-1:len(search)]
    sums = np.concatenate(([0.], np.cumsum(search)))
    squares = np.concatenate(([0.], np.cumsum(search**2)))
    n = len(reference)
    variance = np.maximum(squares[n:] - squares[:-n] - (sums[n:]-sums[:-n])**2/n, 0)
    scores = cross / np.sqrt(np.maximum(variance*energy, 1e-20))
    best = int(np.argmax(np.abs(scores)))
    return best, float(scores[best])


def bandpass(samples, low, high):
    frequencies = np.fft.rfftfreq(len(samples), 1/RATE)
    spectrum = np.fft.rfft(samples)
    spectrum[(frequencies < low) | (frequencies >= high)] = 0
    return np.fft.irfft(spectrum, n=len(samples))


def dbfs(samples):
    return float(10*np.log10(max(float(np.mean(samples**2)), 1e-20)/32768**2)) if len(samples) else None


def spectral_relationship(reference, microphone, frame=4096, hop=2048):
    """Welch cross-spectrum and magnitude-squared coherence; relative digital gain."""
    length = min(len(reference), len(microphone))
    if length < frame + hop*7:
        raise ValueError("At least eight Welch segments required")
    window = np.hanning(frame)
    xx, yy, xy = [], [], []
    for start in range(0, length-frame+1, hop):
        a, b = reference[start:start+frame], microphone[start:start+frame]
        x = np.fft.rfft((a-a.mean())*window)
        y = np.fft.rfft((b-b.mean())*window)
        xx.append(np.abs(x)**2)
        yy.append(np.abs(y)**2)
        xy.append(np.conj(x)*y)
    pxx, pyy, pxy = np.mean(xx, axis=0), np.mean(yy, axis=0), np.mean(xy, axis=0)
    coherence = np.clip(np.abs(pxy)**2/np.maximum(pxx*pyy, 1e-30), 0, 1)
    response = pxy/np.maximum(pxx, 1e-30)
    frequencies = np.fft.rfftfreq(frame, 1/RATE)
    bands = {}
    for low, high in ((150, 800), (800, 2000), (2000, 6500)):
        mask = (frequencies >= low) & (frequencies < high) & (pxx > pxx.max()*1e-6)
        bands[f'{low}-{high}Hz'] = {'median_coherence': float(np.median(coherence[mask])) if np.any(mask) else None}
    return {'frequencies_hz': frequencies.tolist(), 'coherence': coherence.tolist(),
            'h1_gain_db': (20*np.log10(np.maximum(np.abs(response), 1e-15))).tolist(),
            'cross_spectrum_real': pxy.real.tolist(), 'cross_spectrum_imag': pxy.imag.tolist(),
            'welch_segments': len(xx), 'frame_samples': frame, 'hop_samples': hop,
            'bands': bands,
            'interpretation': 'Digital H1 estimate, not calibrated acoustic response. Low coherence makes H1 unreliable; alignment, drift and processing affect estimates.'}


def diagnose(directory, window_seconds=5, search_seconds=1):
    directory = Path(directory)
    records = [json.loads(line) for line in (directory/'audio-index.jsonl').read_text().splitlines()]
    microphones = [r for r in records if r['track'] == 'microphone']
    speakers = [r for r in records if r['track'] == 'speaker' and r.get('code') == 0]
    if not microphones or not speakers:
        raise ValueError("Both microphone and successful speaker records are required")
    mic, ref = load(directory/'microphone-16k.wav'), load(directory/'speaker-16k.wav')
    # These are arrival/submission clock estimates, not hardware ADC/DAC time.
    anchor = microphones[0]['elapsed'] - microphones[0]['samples']/RATE
    stamps = np.array([r['elapsed'] - (r['sample_offset']+r['samples'])/RATE for r in microphones])
    ref_offsets = np.array([r['sample_offset'] for r in speakers])

    def reference_time(sample):
        i = max(0, int(np.searchsorted(ref_offsets, sample, side='right'))-1)
        return speakers[i]['elapsed'] + (sample-speakers[i]['sample_offset'])/RATE

    window = round(window_seconds*RATE)
    tracks = {'full': (mic, ref)}
    for low, high in ((200, 800), (800, 2000), (2000, 6000)):
        tracks[f'{low}-{high}Hz'] = (bandpass(mic, low, high), bandpass(ref, low, high))
    windows = []
    for start in range(0, len(ref), window):
        length = min(window, len(ref)-start)
        if length < window*.9:
            continue
        submitted = reference_time(start)
        left = max(0, round((submitted-anchor-search_seconds)*RATE))
        right = min(len(mic), round((submitted-anchor+search_seconds)*RATE)+length)
        entry = {'reference_second': start/RATE, 'duration_seconds': length/RATE,
                 'submitted_elapsed': submitted, 'bands': {}}
        for name, (x, y) in tracks.items():
            result = correlate(x[left:right], y[start:start+length])
            if result is None:
                continue
            offset, coefficient = result
            delay = anchor + (left+offset)/RATE - submitted
            entry['bands'][name] = {'correlation': round(coefficient, 5), 'delay_ms': round(delay*1000, 3)}
        windows.append(entry)
        full = entry['bands'].get('full', {})
        print(f"reference={start/RATE:5.1f}s  correlation={full.get('correlation')}  "
              f"offset={full.get('delay_ms')} ms")
    first = speakers[0]['elapsed']
    end = max(r['elapsed']+r['samples']/RATE for r in speakers)
    # Margins avoid startup and unknown device playback tails.
    baseline = mic[:max(0, round((first-anchor-.5)*RATE))]
    playing = mic[max(0, round((first-anchor+2)*RATE)):max(0, round((end-anchor-1)*RATE))]
    gaps = [(b['elapsed']-a['elapsed']) - a['samples']/RATE for a,b in zip(speakers, speakers[1:])]
    delays = [w['bands']['full']['delay_ms'] for w in windows if 'full' in w['bands']]
    median_delay = float(np.median(delays)) if delays else 0.
    offset = round((first-anchor+median_delay/1000)*RATE)
    # Coherence uses continuous sample streams, not zero-filled arrival-time blocks.
    reference_start = max(0, -offset)
    mic_start = max(0, offset)
    spectral = spectral_relationship(ref[reference_start:], mic[mic_start:])
    spectral['alignment_offset_samples'] = offset
    spectral['estimated_clock_delay_ms'] = median_delay
    (directory/'raw-spectral-report.json').write_text(json.dumps(spectral, indent=2), encoding='utf-8')
    report = {'windows': windows, 'baseline_dbfs': dbfs(baseline), 'playback_dbfs': dbfs(playing),
              'microphone_clock_offset_range_ms': [float(stamps.min()*1000), float(stamps.max()*1000)],
              'speaker_submission_gap_range_ms': [min(gaps)*1000, max(gaps)*1000] if gaps else [],
              'notes': ["Microphone is unprocessed by this application; firmware preprocessing is unknown.",
                        "Reference contains final SDK-submitted PCM; successful RPC is not DAC confirmation.",
                        "Offsets include buffering and timestamp uncertainty, not just sound propagation.",
                        "Low correlation peaks are not reliable delay/drift estimates.",
                        "Repeated source audio creates ambiguous correlation peaks.",
                        "Band differences alone do not identify nonlinearity or reverberation."]}
    report['spectral_bands'] = spectral['bands']
    (directory/'raw-signal-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f"Baseline={report['baseline_dbfs']:.2f} dBFS; playback={report['playback_dbfs']:.2f} dBFS")
    print('Mic arrival-clock offset range ms:', report['microphone_clock_offset_range_ms'])
    print('SDK submission gap range ms:', report['speaker_submission_gap_range_ms'])
    print('Welch band median coherence:', spectral['bands'])
    print('Low correlation cannot establish drift or a unique delay. Full report:', directory/'raw-signal-report.json')
    return report
