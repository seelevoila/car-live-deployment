"""Score cloned candidates against a reference speaker embedding.

This helper intentionally lives outside the API environment: the project
backend stays lightweight, while the GPT-SoVITS virtualenv already contains
torch, torchaudio, Kaldi and the ERes2NetV2 checkpoint.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import urllib.request
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
import torchaudio


def _load_model(gpt_root: Path, checkpoint: Path):
    sys.path.insert(0, str(gpt_root / "GPT_SoVITS" / "eres2net"))
    from ERes2NetV2 import ERes2NetV2
    import kaldi

    state = torch.load(checkpoint, map_location="cpu")
    model = ERes2NetV2(baseWidth=24, scale=4, expansion=4)
    model.load_state_dict(state)
    model.eval()
    return model, kaldi


def _embedding(path: Path, model, kaldi):
    audio, sample_rate = sf.read(path, dtype="float32", always_2d=True)
    # Speaker encoders are more reliable on the speech-bearing region than on
    # a six-second clip padded with room tone. This matters especially for
    # lower-pitched voices, whose quiet consonants can otherwise be diluted by
    # leading/trailing silence. Keep a small boundary margin so plosives are
    # not clipped and never crop a clip when no stable active region exists.
    mono = audio.mean(axis=1)
    frame_size = max(1, int(sample_rate * 0.02))
    hop_size = max(1, int(sample_rate * 0.01))
    if mono.size >= frame_size:
        frames = np.lib.stride_tricks.sliding_window_view(mono, frame_size)[::hop_size]
        energy = np.sqrt(np.mean(np.square(frames), axis=1))
        threshold = max(0.0015, float(np.quantile(energy, 0.75)) * 0.12)
        active = np.flatnonzero(energy >= threshold)
        if active.size >= 8:
            start = max(0, int(active[0] * hop_size - sample_rate * 0.08))
            end = min(mono.size, int(active[-1] * hop_size + frame_size + sample_rate * 0.08))
            if end - start >= int(sample_rate * 0.5):
                audio = audio[start:end]
    waveform = torch.from_numpy(audio.T)
    if sample_rate != 16000:
        waveform = torchaudio.functional.resample(waveform, sample_rate, 16000)
    features = torch.stack(
        [
            kaldi.fbank(channel.unsqueeze(0), num_mel_bins=80, sample_frequency=16000, dither=0)
            for channel in waveform
        ]
    )
    with torch.no_grad():
        vector = model.forward3(features).float().mean(dim=0).flatten()
    return vector / (vector.norm() + 1e-8)


def reference_weights(reference_scores, threshold):
    """Weights in primary/accepted-auxiliary order, shared with inference."""
    accepted = [item['score'] for item in reference_scores if item.get('accepted')]
    if not accepted:
        return [1.0]
    strongest = max(accepted, default=threshold)
    primary = .50 if strongest >= .92 else (.58 if strongest >= .88 else .68)
    return [primary] + [(1.0-primary)/len(accepted)] * len(accepted)


def _reference_target(paths: list[Path], model, kaldi, threshold: float):
    """Keep only auxiliary clips that agree with the transcript-bearing clip."""
    vectors = [_embedding(path, model, kaldi) for path in paths]
    primary = vectors[0]
    accepted_paths = [paths[0]]
    accepted_vectors = [primary]
    reference_scores = []
    for path, vector in zip(paths[1:], vectors[1:]):
        score = float(torch.dot(primary, vector))
        accepted = score >= threshold
        reference_scores.append({"path": str(path), "score": round(score, 6), "accepted": accepted})
        if accepted:
            accepted_paths.append(path)
            accepted_vectors.append(vector)
    # The transcript-bearing clip is still the semantic anchor used by
    # GPT-SoVITS, but it should not dominate the speaker target when an
    # auxiliary recording strongly agrees with it.  A fixed 0.65 primary
    # weight made low-pitched speakers particularly sensitive to one emotional
    # prompt clip: the scorer then selected a candidate that matched that
    # clip's delivery rather than the speaker across recordings.  Increase
    # auxiliary weight only when its embedding agrees closely, and keep a
    # conservative primary weight for borderline matches.
    weights = reference_weights(reference_scores, threshold)
    target = accepted_vectors[0] * weights[0]
    for vector, weight in zip(accepted_vectors[1:], weights[1:]):
        target = target + vector * weight
    target = target / (target.norm() + 1e-8)
    return target, accepted_paths, reference_scores


def _prosody_features(path: Path, *, include_curve=False):
    """Measure pitch motion without assuming a particular gender or role."""
    audio, sample_rate = sf.read(path, dtype="float32", always_2d=True)
    waveform = torch.from_numpy(audio.mean(axis=1)).unsqueeze(0)
    if sample_rate != 16000:
        waveform = torchaudio.functional.resample(waveform, sample_rate, 16000)
        sample_rate = 16000
    frame_size = max(1, int(sample_rate * 0.03))
    hop_size = max(1, int(sample_rate * 0.02))
    if waveform.shape[-1] < frame_size:
        return {"duration": round(waveform.shape[-1] / sample_rate, 3), "voiced_ratio": 0.0, "available": False}
    energy = waveform.unfold(-1, frame_size, hop_size).square().mean(dim=-1).sqrt().flatten()
    energy_threshold = max(0.0015, float(torch.quantile(energy, 0.75)) * 0.12)
    active = energy >= energy_threshold
    active_indices = torch.nonzero(active, as_tuple=False).flatten()
    if active_indices.numel():
        duration = (int(active_indices[-1] - active_indices[0]) * hop_size + frame_size) / sample_rate
    else:
        duration = waveform.shape[-1] / float(sample_rate or 1)
    if duration < 0.35:
        return {"duration": round(duration, 3), "voiced_ratio": 0.0, "available": False}

    try:
        f0 = torchaudio.functional.detect_pitch_frequency(
            waveform,
            sample_rate,
            frame_time=0.02,
            win_length=7,
            freq_low=65,
            freq_high=700,
        ).flatten()
    except (RuntimeError, ValueError, FloatingPointError):
        return {"duration": round(duration, 3), "voiced_ratio": 0.0, "available": False}
    if not f0.numel():
        return {"duration": round(duration, 3), "voiced_ratio": 0.0, "available": False}
    # Pitch extraction and RMS framing differ by a few boundary frames. Map
    # active speech to the pitch timeline and reject silence-generated F0.
    active_for_pitch = torch.nn.functional.interpolate(
        active.float().view(1, 1, -1), size=f0.numel(), mode="nearest"
    ).flatten().bool()
    voiced = active_for_pitch & torch.isfinite(f0) & (f0 >= 65) & (f0 <= 700)
    f0 = f0.detach().cpu().numpy()
    voiced = voiced.detach().cpu().numpy()
    if int(voiced.sum()) < 12:
        return {
            "duration": round(duration, 3),
            "voiced_ratio": round(float(voiced.mean()), 4),
            "available": False,
        }

    semitones = np.full(f0.shape, np.nan, dtype=np.float64)
    semitones[voiced] = 12.0 * np.log2(f0[voiced])
    # A short median filter removes isolated pitch-detector octave errors but
    # keeps genuine word-level rises and falls.
    smoothed = semitones.copy()
    for index in np.flatnonzero(voiced):
        neighborhood = semitones[max(0, index - 2):index + 3]
        neighborhood = neighborhood[np.isfinite(neighborhood)]
        if neighborhood.size >= 2:
            smoothed[index] = float(np.median(neighborhood))
    valid_pitch = smoothed[np.isfinite(smoothed)]
    adjacent = np.isfinite(smoothed[:-1]) & np.isfinite(smoothed[1:])
    jumps = np.abs(np.diff(smoothed)[adjacent])
    median_st = float(np.median(valid_pitch))
    median_hz = 2.0 ** (median_st / 12.0)
    pitch_span = float(np.percentile(valid_pitch, 90) - np.percentile(valid_pitch, 10))
    jump_p95 = float(np.percentile(jumps, 95)) if jumps.size else 0.0

    frame_time = 0.02
    times = np.arange(smoothed.size) * frame_time
    ending = smoothed[(times >= max(0.0, duration - 0.45)) & np.isfinite(smoothed)]
    before = smoothed[
        (times >= max(0.0, duration - 1.15))
        & (times < max(0.0, duration - 0.45))
        & np.isfinite(smoothed)
    ]
    ending_shift = float(np.median(ending) - np.median(before)) if ending.size >= 3 and before.size >= 4 else 0.0
    # Use the final voiced frame as the ending anchor, preserving the existing
    # similarity/penalty fields for historical score comparability.
    finite = np.flatnonzero(np.isfinite(smoothed))
    end_at = times[finite[-1]]
    tail = (times >= end_at - .45) & np.isfinite(smoothed)
    ending_slope = float(np.polyfit(times[tail], smoothed[tail], 1)[0]) if tail.sum() >= 3 else None
    # Count reversals over 100ms intervals with a 0.5-semitone deadband.
    # Chinese lexical tones also turn: this is a measurement, not a defect score.
    turns, previous_sign, previous_time = 0, 0, -1.0
    for index in range(5, smoothed.size, 5):
        segment = smoothed[index-5:index+1]
        if not np.isfinite(segment).all():
            previous_sign = 0
            continue
        delta = smoothed[index] - smoothed[index-5]
        sign = 1 if delta > .5 else -1 if delta < -.5 else 0
        if sign:
            if previous_sign and sign != previous_sign and times[index] - previous_time <= .3:
                turns += 1
            previous_sign, previous_time = sign, times[index]
    # Speaker cosine similarity does not expose a noisy tail or clipped
    # consonant. These small waveform diagnostics let calibration reject a
    # buzzy candidate even when its timbre embedding is close to the target.
    sample_mono = waveform.flatten().detach().cpu().numpy()
    clipped_ratio = float(np.mean(np.abs(sample_mono) >= 0.995)) if sample_mono.size else 0.0
    dc_offset = float(abs(np.mean(sample_mono))) if sample_mono.size else 0.0
    energy_np = energy.detach().cpu().numpy()
    active_np = active.detach().cpu().numpy()
    active_rms = energy_np[active_np]
    quiet_rms = energy_np[~active_np]
    speech_level = float(np.percentile(active_rms, 75)) if active_rms.size else 0.0
    noise_level = float(np.percentile(quiet_rms, 50)) if quiet_rms.size else 0.0
    snr_db = 20.0 * math.log10((speech_level + 1e-6) / (noise_level + 1e-6)) if speech_level else 0.0
    features = {
        "available": True,
        "duration": round(duration, 3),
        "voiced_ratio": round(float(voiced.mean()), 4),
        "median_hz": round(median_hz, 2),
        "pitch_span_st": round(pitch_span, 3),
        "pitch_jump_p95_st": round(jump_p95, 3),
        "ending_shift_st": round(ending_shift, 3),
        "snr_db": round(snr_db, 2),
        "clipped_ratio": round(clipped_ratio, 5),
        "dc_offset": round(dc_offset, 5),
        "pitch_turn_count": turns,
        "ending_slope_st_per_s": round(ending_slope, 3) if ending_slope is not None else None,
    }
    if include_curve:
        features['f0_curve'] = [{'time_s': round(float(t), 3),
                                'hz': round(float(2 ** (pitch/12)), 2) if np.isfinite(pitch) else None}
                               for t, pitch in zip(times, smoothed)]
    return features


def _reference_prosody_risk(features: dict):
    if not features.get("available"):
        return {"level": "unknown", "reasons": ["pitch-unavailable"]}
    reasons = []
    if features.get("pitch_span_st", 0) > 12:
        reasons.append("wide-pitch-range")
    if features.get("pitch_jump_p95_st", 0) > 3.5:
        reasons.append("abrupt-pitch-motion")
    if features.get("ending_shift_st", 0) > 4:
        reasons.append("strong-ending-rise")
    return {"level": "high" if reasons else "normal", "reasons": reasons}


def _prosody_penalty(candidate: dict, reference: dict):
    """Return a small identity-score deduction for objectively unstable speech."""
    if not candidate.get("available"):
        return 0.04
    penalty = 0.0
    penalty += max(0.0, candidate.get("pitch_span_st", 0) - 10.0) * 0.006
    penalty += max(0.0, candidate.get("pitch_jump_p95_st", 0) - 2.0) * 0.012
    penalty += max(0.0, candidate.get("ending_shift_st", 0) - 2.5) * 0.010
    duration = candidate.get("duration", 0)
    penalty += max(0.0, 1.05 - duration) * 0.025
    penalty += max(0.0, duration - 3.2) * 0.012
    if reference.get("available") and candidate.get("median_hz") and reference.get("median_hz"):
        pitch_gap = abs(12.0 * math.log2(candidate["median_hz"] / reference["median_hz"]))
        penalty += max(0.0, pitch_gap - 3.0) * 0.006
    penalty += max(0.0, 16.0 - candidate.get("snr_db", 16.0)) * 0.004
    penalty += max(0.0, candidate.get("clipped_ratio", 0.0) - 0.002) * 4.0
    penalty += max(0.0, candidate.get("dc_offset", 0.0) - 0.02) * 0.5
    return round(penalty, 6)


def _sampling_penalty(spec: dict, reference_risk: dict):
    """Prefer low-entropy sampling when identity scores are close.

    Speaker cosine similarity alone often rewards an expressive candidate that
    has the right broad spectrum but introduces unstable consonants or octave
    jumps.  Sampling is therefore a tie-breaker, not a hard filter: a clearly
    better identity score can still win, while a near-tie uses the more stable
    profile.  References with strong pitch motion get a slightly larger tie
    break because their prompt prosody is more likely to leak into new copy.
    """
    try:
        top_k = float(spec.get("top_k", 15))
        top_p = float(spec.get("top_p", 0.65))
        temperature = float(spec.get("temperature", 0.60))
    except (TypeError, ValueError):
        return 0.0
    # top-k is a secondary tie-breaker.  Do not hard-code a low value because
    # some speakers lose plosive detail when the candidate pool is too narrow.
    penalty = max(0.0, top_k - 18.0) * 0.0008
    penalty += max(0.0, 0.65 - top_k) * 0.002
    penalty += max(0.0, top_p - 0.70) * 0.055
    penalty += max(0.0, temperature - 0.62) * 0.085
    if reference_risk.get("level") == "high":
        penalty *= 1.35
    return round(penalty, 6)


def _synthesize_candidates(endpoint: str, request_path: Path, specs: list[dict], target_dir: Path):
    request_data = json.loads(request_path.read_text(encoding="utf-8"))
    target_dir.mkdir(parents=True, exist_ok=True)
    candidates = []
    for index, spec in enumerate(specs):
        payload = dict(request_data)
        payload.update({key: value for key, value in spec.items() if key in {"seed", "top_k", "top_p", "temperature", "repetition_penalty"}})
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(endpoint, data=body, headers={"Content-Type": "application/json; charset=utf-8"})
        with urllib.request.urlopen(request, timeout=180) as response:
            audio = response.read()
        if len(audio) <= 128:
            raise RuntimeError("GPT-SoVITS returned no usable audio")
        label = str(spec.get("label") or spec.get("seed") or index)
        safe_label = re.sub(r"[^A-Za-z0-9_.-]+", "-", label).strip("-.") or str(index)
        path = target_dir / f"candidate-{safe_label}.wav"
        path.write_bytes(audio)
        candidates.append((label, path, dict(spec)))
    return candidates


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gpt-root", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--reference", action="append", required=True)
    parser.add_argument("--candidate", action="append", default=[], help="label=wav path")
    parser.add_argument("--aux-threshold", type=float, default=0.85)
    parser.add_argument("--endpoint")
    parser.add_argument("--request-json", type=Path)
    parser.add_argument("--candidate-seed", action="append", type=int, default=[])
    parser.add_argument("--candidate-spec", action="append", default=[], help="JSON candidate sampling profile")
    parser.add_argument("--candidate-specs-json", help="JSON list mapping labels to sampling profiles")
    parser.add_argument("--candidate-dir", type=Path)
    args = parser.parse_args()
    model, kaldi = _load_model(args.gpt_root, args.checkpoint)
    reference_paths = [Path(path) for path in args.reference]
    reference, accepted_paths, reference_scores = _reference_target(
        reference_paths, model, kaldi, args.aux_threshold
    )
    reference_prosody = _prosody_features(reference_paths[0])
    reference_risk = _reference_prosody_risk(reference_prosody)
    candidates = []
    candidate_specs = [json.loads(item) for item in args.candidate_spec]
    if args.candidate_specs_json:
        candidate_specs.extend(json.loads(args.candidate_specs_json))
    candidate_specs.extend({"label": str(seed), "seed": seed} for seed in args.candidate_seed)
    if args.endpoint or args.request_json or args.candidate_spec or args.candidate_seed:
        if not (args.endpoint and args.request_json and (args.candidate_spec or args.candidate_seed) and args.candidate_dir):
            raise ValueError("endpoint, request-json, candidate spec and candidate-dir must be supplied together")
        request_data = json.loads(args.request_json.read_text(encoding="utf-8"))
        request_data["aux_ref_audio_paths"] = [str(path) for path in accepted_paths[1:]]
        args.request_json.write_text(json.dumps(request_data, ensure_ascii=False), encoding="utf-8")
        candidates.extend(_synthesize_candidates(args.endpoint, args.request_json, candidate_specs, args.candidate_dir))
    specs_by_label = {str(spec.get("label")): spec for spec in candidate_specs}
    for item in args.candidate:
        label, separator, path = item.partition("=")
        if not separator:
            raise ValueError(f"invalid candidate: {item}")
        candidates.append((label, Path(path), dict(specs_by_label.get(label) or {"label": label})))
    if not candidates:
        print(json.dumps({
            "accepted_aux_paths": [str(path) for path in accepted_paths[1:]],
            "reference_scores": reference_scores,
            "reference_prosody": reference_prosody,
            "reference_prosody_risk": reference_risk,
        }, ensure_ascii=False))
        return
    scores = []
    for label, path, spec in candidates:
        score = float(torch.dot(reference, _embedding(path, model, kaldi)))
        prosody = _prosody_features(path)
        penalty = _prosody_penalty(prosody, reference_prosody)
        sampling_penalty = _sampling_penalty(spec, reference_risk)
        scores.append({
            "label": label,
            "score": round(score, 6),
            "selection_score": round(score - penalty - sampling_penalty, 6),
            "prosody_penalty": penalty,
            "sampling_penalty": sampling_penalty,
            "prosody": prosody,
            "sampling": spec,
        })
    scores.sort(key=lambda item: (item["selection_score"], item["score"]), reverse=True)
    print(json.dumps({
        "best_label": scores[0]["label"],
        "best_candidate": scores[0],
        "scores": scores,
        "accepted_aux_paths": [str(path) for path in accepted_paths[1:]],
        "reference_scores": reference_scores,
        "reference_prosody": reference_prosody,
        "reference_prosody_risk": reference_risk,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
