"""Bounded native v2ProPlus adaptation, executed only in the resident GPU API.

No speaker-specific checkpoint or experiment output is used as an initializer.
The caller must serialize this operation with inference and model switching.
"""
from collections import OrderedDict
from copy import copy, deepcopy
import gc
import hashlib
import json
from pathlib import Path
import random
import time


def sha256(path):
    with Path(path).open('rb') as stream:
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def trainable_parameter(name):
    return (not name.startswith(('enc_p.', 'ssl_proj.', 'quantizer.'))
            or name.startswith(('enc_p.mrte.c_post.', 'enc_p.encoder2.', 'enc_p.proj.')))


def adapt_resident(pipeline, gpt_root, records, output_dir, *, seconds=30., max_steps=24, progress=None):
    """Always restore the previously resident model, including on numerical failure.

    The budget is a soft resident-work target, not an upload-to-ready promise.
    Decoding, reload and I/O can exceed it; actual wall time is reported.
    """
    import numpy as np
    import torch
    started = time.perf_counter()
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    base_path = Path(gpt_root) / 'GPT_SoVITS/pretrained_models/v2Pro/s2Gv2ProPlus.pth'
    report = {'method': 'native-fp32-broad-v1', 'initial_checkpoint': str(base_path),
              'initial_sha256': sha256(base_path), 'budget_s': seconds, 'max_steps': max_steps,
              'updates': [], 'records': [], 'skipped_generator_steps': 0, 'skipped_discriminator_steps': 0,
              'completed': False, 'scope': 'resident adaptation; excludes queue, upload and synthesis acceptance'}
    previous_model = pipeline.vits_model
    previous_config = pipeline.configs
    previous_pro = pipeline.is_v2pro
    # Copying config also avoids overwriting the production runtime YAML when
    # native init_vits_weights saves its configuration during this request.
    temporary_config = copy(previous_config)
    # The upstream config also holds a derived GPT embedding tensor. It is
    # not a leaf, so deepcopy(config) raises after the first model warmup.
    temporary_config.__dict__ = {key: value.detach().clone() if torch.is_tensor(value) else deepcopy(value)
                                 for key, value in previous_config.__dict__.items()}
    temporary_config.configs_path = str(output / 'training-runtime.yaml')
    others = [pipeline.bert_model, pipeline.t2s_model, pipeline.cnhuhbert_model,
              pipeline.sv_model.embedding_model]
    placement = [(module, next(module.parameters()).device, next(module.parameters()).dtype,
                  module.training) for module in others]
    cpu_rng, gpu_rng = torch.get_rng_state(), torch.cuda.get_rng_state_all()
    py_rng, np_rng = random.getstate(), np.random.get_state()
    error = None

    def stage(name):
        report['stage'] = name
        report['elapsed_s'] = time.perf_counter() - started
        atomic_json(output / 'report.json', report)
        if progress:
            progress({'stage': name, 'elapsed_s': report['elapsed_s'], 'steps': len(report['updates'])})

    try:
        if str(pipeline.configs.device) == 'cpu' or pipeline.configs.version != 'v2ProPlus':
            raise RuntimeError('短时适配需要当前 GPU 上的 v2ProPlus 模型')
        previous_model.cpu()
        pipeline.configs = temporary_config
        pipeline.init_vits_weights(str(base_path))
        torch.manual_seed(1234)
        stage('reference_features')
        # Keep training in a separate frame: all autograd/optimizer references
        # are released before restoring inference, also after an exception.
        _train(pipeline, Path(gpt_root), records, output, report, started, seconds, max_steps, stage)
    except Exception as exc:
        error = f'{type(exc).__name__}: {exc}'
        report['error'] = error
    finally:
        pipeline.vits_model = None
        gc.collect()
        torch.cuda.empty_cache()
        pipeline.configs = previous_config
        pipeline.is_v2pro = previous_pro
        pipeline.vits_model = previous_model.to(previous_config.device)
        for module, device, dtype, training in placement:
            module.to(device=device, dtype=dtype).train(training)
        pipeline._voice_cache = OrderedDict()
        pipeline._speaker_anchor_cache = OrderedDict()
        pipeline._voice_cache_epoch = getattr(pipeline, '_voice_cache_epoch', 0) + 1
        pipeline.prompt_cache['ref_audio_path'] = None
        pipeline.prompt_cache['prompt_text'] = None
        torch.set_rng_state(cpu_rng)
        torch.cuda.set_rng_state_all(gpu_rng)
        random.setstate(py_rng)
        np.random.set_state(np_rng)
        torch.cuda.synchronize()
        report['resident_seconds'] = time.perf_counter() - started
        report['within_resident_budget'] = report['resident_seconds'] <= seconds
        report['restored_sovits_weights'] = str(previous_config.vits_weights_path)
        stage('failed' if error else 'complete')
    if error:
        raise RuntimeError(error)
    return report


def _train(pipeline, gpt_root, records, output, report, started, seconds, max_steps, stage):
    import librosa
    import numpy as np
    import torch
    import torch.nn.functional as F
    from module import commons
    from module.models import MultiPeriodDiscriminator
    from module.data_utils import TextAudioSpeakerCollate
    from module.losses import discriminator_loss, generator_loss, feature_loss, kl_loss
    from module.mel_processing import spectrogram_torch, spec_to_mel_torch, mel_spectrogram_torch
    from text.cleaner import clean_text
    from text import cleaned_text_to_sequence
    from tools.my_utils import load_audio
    from process_ckpt import load_sovits_new, my_save2, get_sovits_version_from_path_fast
    from .gpt_sovits_runtime import _original_speaker_embedding

    net = pipeline.vits_model
    base = {key: value.detach().cpu().clone() for key, value in net.state_dict().items()}
    anchor = _original_speaker_embedding(pipeline, records[0]['audio']).detach().float()
    batches = []
    for recording in records:
        audio = load_audio(recording['audio'], 32000)
        peak = float(np.max(np.abs(audio)))
        if not np.isfinite(audio).all() or peak < 1e-5 or not 3 <= len(audio) / 32000 <= 15:
            raise ValueError('训练录音需为 3–15 秒的有效单人语音')
        wav = torch.from_numpy(audio / peak * .475 + .5 * audio).cuda().float().unsqueeze(0)
        with torch.no_grad():
            # Same independent HuBERT gain as upstream dataset preparation.
            ssl32 = audio / peak * (.475 * 1145.14) + (.5 * 1145.14) * audio
            ssl16 = torch.from_numpy(librosa.resample(ssl32, orig_sr=32000, target_sr=16000)).to(
                device='cuda', dtype=next(pipeline.cnhuhbert_model.parameters()).dtype).unsqueeze(0)
            ssl = pipeline.cnhuhbert_model.model(ssl16)['last_hidden_state'].transpose(1, 2).float()
            spec = spectrogram_torch(wav, 2048, 32000, 640, 2048, center=False)
            if ssl.shape[-1] != spec.shape[-1]:
                ssl = F.pad(ssl, (0, 1), mode='replicate')
            if ssl.shape[-1] != spec.shape[-1]:
                raise ValueError('HuBERT 与频谱帧数不一致')
            phones, _, normalized = clean_text(recording['transcript'], recording.get('language', 'zh'), 'v2ProPlus')
            ids = torch.tensor(cleaned_text_to_sequence(phones, 'v2ProPlus'), dtype=torch.long)
            packed = TextAudioSpeakerCollate(version='v2ProPlus')([
                (ssl.cpu(), spec[0].cpu(), wav.cpu(), ids, anchor.cpu())])
            ssl, _, spec, spec_len, wav, _, ids, ids_len, sv = [t.cuda() for t in packed]
            batches.append((ssl, spec, spec_len, wav, ids, ids_len, sv))
        report['records'].append({**recording, 'sha256': sha256(recording['audio']),
                                  'duration_s': len(audio) / 32000, 'normalized_transcript': normalized})
    for module in (pipeline.bert_model, pipeline.t2s_model, pipeline.cnhuhbert_model, pipeline.sv_model.embedding_model):
        module.cpu()
    gc.collect()
    torch.cuda.empty_cache()
    net.float().train()
    for name, parameter in net.named_parameters():
        parameter.requires_grad_(trainable_parameter(name))
    trainable = [p for p in net.parameters() if p.requires_grad]
    disc = MultiPeriodDiscriminator(False, version='v2ProPlus').cuda().train()
    disc.load_state_dict(torch.load(gpt_root / 'GPT_SoVITS/pretrained_models/v2Pro/s2Dv2ProPlus.pth',
                                   map_location='cpu', weights_only=False)['weight'], strict=True)
    optim_g = torch.optim.AdamW(trainable, lr=3e-5, betas=(.8, .99), eps=1e-9)
    optim_d = torch.optim.AdamW(disc.parameters(), lr=3e-5, betas=(.8, .99), eps=1e-9)
    stage('training')
    estimate = 1.
    for step in range(max_steps):
        if time.perf_counter() - started + max(estimate * 1.25, 1.) >= seconds - 5:
            break
        step_start = time.perf_counter()
        ssl, spec, lengths, wav, phones, phone_lengths, sv = batches[step % len(batches)]
        optim_g.zero_grad(set_to_none=True)
        optim_d.zero_grad(set_to_none=True)
        y_hat, commit, ids, _, mask, latent, _ = net(ssl, spec, lengths, phones, phone_lengths, sv)
        _, z_p, m_p, logs_p, _, logs_q = latent
        mel = spec_to_mel_torch(spec, 2048, 128, 32000, 0, None)
        real_mel = commons.slice_segments(mel, ids, 32)
        generated_mel = mel_spectrogram_torch(y_hat.squeeze(1), 2048, 128, 32000, 640, 2048, 0, None)
        real = commons.slice_segments(wav, ids * 640, 20480)
        pred_real, pred_fake, _, _ = disc(real, y_hat.detach())
        loss_d, _, _ = discriminator_loss(pred_real, pred_fake)
        loss_d.backward()
        # Fail BEFORE stepping: a nonfinite FP32 update must never corrupt a
        # candidate (GradScaler is intentionally not involved).
        if not torch.isfinite(loss_d) or not all(torch.isfinite(p.grad).all() for p in disc.parameters() if p.grad is not None):
            raise RuntimeError('Nonfinite discriminator gradient; candidate rejected')
        optim_d.step()
        _, pred_fake, features_real, features_fake = disc(real, y_hat)
        loss_mel = F.l1_loss(real_mel.float(), generated_mel.float()) * 45
        loss_gan, _ = generator_loss(pred_fake)
        loss_g = loss_gan + feature_loss(features_real, features_fake) + loss_mel + kl_loss(z_p, logs_q, m_p, logs_p, mask) + commit
        loss_g.backward()
        if not torch.isfinite(loss_g) or not all(torch.isfinite(p.grad).all() for p in trainable if p.grad is not None):
            raise RuntimeError('Nonfinite generator gradient; candidate rejected')
        optim_g.step()
        torch.cuda.synchronize()
        estimate = time.perf_counter() - step_start
        report['updates'].append({'step': step + 1, 'recording_index': step % len(batches),
                                  'seconds': estimate, 'generator_loss': float(loss_g.detach()),
                                  'discriminator_loss': float(loss_d.detach())})
        stage('training')
    if not report['updates']:
        raise RuntimeError('创建预算内未完成有效更新；未安装权重')
    candidate = {key: value.detach().cpu().half().clone() for key, value in net.state_dict().items()}
    changed = [key for key in candidate if not torch.equal(candidate[key], base[key])]
    frozen = [key for key in changed if not trainable_parameter(key)]
    if not changed or frozen:
        raise RuntimeError('权重变更或冻结层检查失败')
    report.update(effective_steps=len(report['updates']), changed_tensor_count=len(changed), frozen_tensors_changed=frozen)
    stage('packaging')
    native = load_sovits_new(report['initial_checkpoint'])
    checkpoint = output / 'acoustic.pth'
    my_save2({'weight': candidate, 'config': native['config'], 'info': 'per-voice bounded FP32 adaptation'}, str(checkpoint), 'v2ProPlus')
    loaded = load_sovits_new(str(checkpoint))['weight']
    if set(loaded) != set(candidate) or not all(torch.equal(loaded[k], v) for k, v in candidate.items()):
        raise RuntimeError('安装包张量校验失败')
    if list(get_sovits_version_from_path_fast(str(checkpoint))) != ['v2', 'v2ProPlus', False]:
        raise RuntimeError('安装包模型版本校验失败')
    report.update(checkpoint=str(checkpoint), sha256=sha256(checkpoint), completed=True)
