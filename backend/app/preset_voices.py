"""Bundled speaker identities, independent of mutable uploaded clones."""

import json
from pathlib import Path

PRESET_DIR = Path(__file__).resolve().parents[2] / 'data' / 'preset_voices'
_catalog = json.loads((PRESET_DIR / 'catalog.json').read_text(encoding='utf-8'))
PRESET_VOICES = {voice['id']: voice for voice in _catalog['voices']}


def reference_paths(voice_id):
    return [str(PRESET_DIR / asset['file']) for asset in PRESET_VOICES[voice_id]['assets']]


def install_presets(c, created_at):
    """Keep stable legacy IDs, replace clone aliases with portable assets."""
    for voice in PRESET_VOICES.values():
        paths = reference_paths(voice['id'])
        sampling = voice['sampling']
        c.execute('''
            INSERT INTO voices(id,name,style,provider,reference_path,prompt_text,prompt_lang,
                aux_reference_paths,validated_aux_reference_paths,reference_voice_id,
                model_profile,sampling_seed,sampling_top_k,sampling_top_p,sampling_temperature,created_at)
            VALUES(?,?,?,'gpt-sovits',?,?,?,?,?,'','base',?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,style=excluded.style,provider=excluded.provider,
                reference_path=excluded.reference_path,prompt_text=excluded.prompt_text,
                prompt_lang=excluded.prompt_lang,aux_reference_paths=excluded.aux_reference_paths,
                validated_aux_reference_paths=excluded.validated_aux_reference_paths,
                reference_voice_id='',model_profile='base',sampling_seed=excluded.sampling_seed,
                sampling_top_k=excluded.sampling_top_k,sampling_top_p=excluded.sampling_top_p,
                sampling_temperature=excluded.sampling_temperature,
                sampling_model_version=NULL,calibration_details=NULL
        ''', (voice['id'], voice['name'], voice['tag'], paths[0], voice['prompt_text'],
              voice['prompt_lang'], json.dumps(paths[1:]), json.dumps(paths[1:]),
              sampling['seed'], sampling['top_k'], sampling['top_p'], sampling['temperature'], created_at))
