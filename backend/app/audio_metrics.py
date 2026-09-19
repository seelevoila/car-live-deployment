"""PCM diagnostics shared by calibration, reference checks and prompt validation."""
import array
import io
import math
import wave
from pathlib import Path


def wav_metrics(payload: bytes) -> dict:
    with wave.open(io.BytesIO(payload), 'rb') as reader:
        rate, channels, width = reader.getframerate(), reader.getnchannels(), reader.getsampwidth()
        if width != 2 or not rate:
            raise ValueError('Expected PCM16 WAV')
        samples = array.array('h', reader.readframes(reader.getnframes()))
    mono = [sum(samples[i:i+channels]) / channels / 32768 for i in range(0, len(samples), channels)]
    step = max(1, round(rate * .02))
    rms = math.sqrt(sum(x*x for x in mono) / max(1, len(mono)))
    quiet = [math.sqrt(sum(x*x for x in mono[i:i+step]) / len(mono[i:i+step])) < 10**(-42/20)
             for i in range(0, len(mono), step)]
    active = [i for i, silent in enumerate(quiet) if not silent]
    internal = quiet[active[0]:active[-1]+1] if active else []
    spans, run = [], 0
    for silent in internal + [False]:
        if silent:
            run += 1
        elif run:
            spans.append(round(run * .02, 3)); run = 0
    return {'duration_s': len(mono)/rate, 'rms_db': 20*math.log10(max(rms, 1e-10)),
            'peak_db': 20*math.log10(max(max(map(abs, mono), default=0), 1e-10)),
            'internal_silences_s': spans, 'max_internal_silence_s': max(spans, default=0),
            'silence_ratio': sum(quiet)/max(1,len(quiet)),
            'internal_silence_s': sum(spans)}


def compress_internal_pauses(source: Path, target: Path, maximum_s: float = .34) -> dict:
    """Write a separate WAV, retaining outer silence and all audible samples."""
    if source.resolve() == target.resolve():
        raise ValueError('Pause compression must preserve the original reference')
    payload = source.read_bytes()
    with wave.open(io.BytesIO(payload), 'rb') as reader:
        params = reader.getparams()
        if params.nchannels != 1 or params.sampwidth != 2:
            raise ValueError('Pause compression requires normalized mono PCM16')
        samples = array.array('h', reader.readframes(reader.getnframes()))
    step = max(1, round(params.framerate * .02))
    threshold = 32768 * 10 ** (-42/20)
    quiet = [math.sqrt(sum(x*x for x in samples[i:i+step])/len(samples[i:i+step])) < threshold
             for i in range(0, len(samples), step)]
    active = [i for i, value in enumerate(quiet) if not value]
    cuts = []
    if active:
        first, last = active[0], active[-1]
        keep = max(1, int(round(maximum_s/.02)))
        cursor = first
        while cursor < last:
            if not quiet[cursor]:
                cursor += 1; continue
            end = cursor
            while end < last and quiet[end]:end += 1
            if end-cursor > keep:
                cuts.append(((cursor+keep//2)*step, (end-(keep-keep//2))*step))
            cursor = end
    result = array.array('h');cursor = 0
    for start, end in cuts:
        result.extend(samples[cursor:start]);cursor = end
    result.extend(samples[cursor:])
    target.parent.mkdir(parents=True,exist_ok=True)
    with wave.open(str(target),'wb') as writer:
        writer.setparams(params);writer.writeframes(result.tobytes())
    return {'source':str(source),'target':str(target),'removed_ranges_samples':cuts,
            'before':wav_metrics(payload),'after':wav_metrics(target.read_bytes())}
