"""Download pinned public ONNX models; inference itself is strictly local.

Usage: .venv/Scripts/python scripts/setup_rag_models.py [--endpoint https://hf-mirror.com]
The mirror serves the same pinned Hugging Face objects, verified against LFS SHA256.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time

MODELS = {
    'embedding': ('Xenova/bge-small-zh-v1.5', '75c43b069aac4d136ba6bc1122f995fedcfd2781'),
    'reranker': ('Xenova/bge-reranker-base', '280bcc27a84e0b898c251e06fddb25171bd9b101'),
}


def materialize_bundled_parts(directory: Path):
    """Join repository-hosted model parts before attempting a network download."""
    for role in MODELS:
        folder = directory / role
        target = folder / 'model_quantized.onnx'
        parts = sorted(folder.glob('model_quantized.onnx.part-*'))
        if target.is_file() or not parts:
            continue
        temporary = target.with_name(target.name + '.assembling')
        with temporary.open('wb') as output:
            for part in parts:
                with part.open('rb') as source:
                    while True:
                        block = source.read(1024 * 1024)
                        if not block:
                            break
                        output.write(block)
        temporary.replace(target)
        print(f'{role}/{target.name}: assembled from {len(parts)} repository parts', flush=True)


def bundled_role_is_valid(directory: Path, role: str) -> bool:
    """Validate a bundled role from its local manifest without network access."""
    folder = directory / role
    manifest_path = folder / 'manifest.json'
    try:
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        for filename in ['config.json', 'tokenizer.json', 'tokenizer_config.json', 'model_quantized.onnx']:
            path = folder / filename
            expected = manifest['files'][filename]['sha256']
            if not path.is_file() or hashlib.file_digest(path.open('rb'), 'sha256').hexdigest() != expected:
                return False
    except (OSError, KeyError, TypeError, ValueError):
        return False
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--endpoint', default='https://huggingface.co')
    parser.add_argument('--directory', type=Path, default=Path(__file__).resolve().parents[1] / 'models' / 'rag')
    args = parser.parse_args()
    materialize_bundled_parts(args.directory)
    pending = {role: details for role, details in MODELS.items() if not bundled_role_is_valid(args.directory, role)}
    if not pending:
        print('All bundled RAG models passed local manifest checks; no download needed.', flush=True)
        return
    import httpx
    with httpx.Client(timeout=httpx.Timeout(60, connect=20), follow_redirects=True, trust_env=False) as client:
        for role, (repo, revision) in pending.items():
            folder = args.directory / role
            folder.mkdir(parents=True, exist_ok=True)
            response = client.get(f'{args.endpoint}/api/models/{repo}/revision/{revision}?blobs=true')
            response.raise_for_status()
            siblings = {x['rfilename']: x for x in response.json()['siblings']}
            manifest = {'repository': repo, 'revision': revision, 'files': {}}
            for filename in ['config.json', 'tokenizer.json', 'tokenizer_config.json', 'onnx/model_quantized.onnx']:
                target = folder / Path(filename).name
                expected = siblings[filename].get('lfs', {}).get('sha256')
                if target.exists() and expected and hashlib.file_digest(target.open('rb'), 'sha256').hexdigest() == expected:
                    print(f'{role}/{target.name}: already verified', flush=True)
                else:
                    partial = target.with_suffix(target.suffix + '.part')
                    for attempt in range(4):
                        try:
                            with client.stream('GET', f'{args.endpoint}/{repo}/resolve/{revision}/{filename}') as r:
                                r.raise_for_status()
                                with partial.open('wb') as f:
                                    for block in r.iter_bytes(1024 * 1024):
                                        f.write(block)
                            digest = hashlib.file_digest(partial.open('rb'), 'sha256').hexdigest()
                            if expected and digest != expected:
                                raise ValueError('LFS SHA256 mismatch')
                            partial.replace(target)
                            break
                        except (httpx.HTTPError, ValueError):
                            if attempt == 3:
                                raise
                            time.sleep(2)
                    print(f'{role}/{target.name}: {target.stat().st_size / 1024**2:.1f} MiB', flush=True)
                manifest['files'][target.name] = {'sha256': hashlib.file_digest(target.open('rb'), 'sha256').hexdigest(),
                                                  'lfs_verified': bool(expected)}
            (folder / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
