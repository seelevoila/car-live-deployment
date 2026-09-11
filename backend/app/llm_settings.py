"""Persist local model settings without returning credentials to the browser."""
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit

from dotenv import dotenv_values
from dotenv.parser import parse_stream
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from .config import ROOT, settings
from . import llm_gateway

router = APIRouter(prefix='/api/llm')
ENV_PATH = ROOT / 'backend' / '.env'
ALLOWED_ORIGINS = {'http://127.0.0.1:5173', 'http://localhost:5173',
                   'http://127.0.0.1:8000', 'http://localhost:8000'}


class ModelConfiguration(BaseModel):
    model_config = ConfigDict(extra='forbid', hide_input_in_errors=True)
    base_url: str = Field(min_length=1, max_length=2000)
    model: str = Field(min_length=1, max_length=200)
    api_key: SecretStr | None = None
    clear_api_key: bool = False
    timeout_seconds: float = Field(default=12, ge=1, le=120, allow_inf_nan=False)


def public_configuration():
    config = llm_gateway.configuration_snapshot()
    return {'base_url': config.base_url, 'model': config.model,
            'api_key_configured': bool(config.api_key),
            'timeout_seconds': config.timeout, 'status': llm_gateway.status()}


def _origin(url):
    parsed = urlsplit(url)
    return parsed.scheme, parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80)


def _validate_url(value):
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme in {'http', 'https'} and parsed.hostname
                 and not parsed.username and not parsed.password
                 and not parsed.query and not parsed.fragment)
        parsed.port  # Validate malformed/out-of-range ports without echoing input.
    except ValueError:
        valid = False
    if not valid or any(c.isspace() or ord(c) < 32 for c in value):
        raise HTTPException(422, '服务地址须为有效的 http:// 或 https:// 地址，不包含密钥、查询参数或片段')


def _persist(values):
    path = Path(ENV_PATH)
    if path.exists():
        with path.open(encoding='utf-8-sig', newline='') as source:
            original = source.read()
    else:
        original = ''
    newline = '\r\n' if path.exists() and b'\r\n' in path.read_bytes() else '\n'
    replacements = {}
    for key, value in values.items():
        escaped = str(value).replace('\\', '\\\\').replace("'", "\\'")
        replacements[key] = f"{key}='{escaped}'{newline}"
    pieces, written = [], set()
    for binding in parse_stream(StringIO(original)):
        if binding.key in replacements:
            if binding.key not in written:
                pieces.append(replacements[binding.key])
                written.add(binding.key)
        else:
            pieces.append(binding.original.string)
    result = ''.join(pieces)
    if result and not result.endswith(('\r', '\n')):
        result += newline
    result += ''.join(line for key, line in replacements.items() if key not in written)
    # Check dotenv escaping/interpolation before committing the file.
    parsed = dotenv_values(stream=StringIO(result))
    if any(parsed.get(key) != str(value) for key, value in values.items()):
        raise HTTPException(422, '配置包含不能按原值保存的变量占位符，请填写实际配置值')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='',
                                         prefix='.llm-', suffix='.tmp', dir=path.parent, delete=False) as output:
            temporary = Path(output.name)
            output.write(result)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def save_configuration(req):
    base_url, model = req.base_url.strip().rstrip('/'), req.model.strip()
    key = req.api_key.get_secret_value().strip() if req.api_key else ''
    _validate_url(base_url)
    if not model or any(ord(c) < 32 for c in model):
        raise HTTPException(422, '请填写有效模型名称，不包含换行或控制字符')
    if len(key) > 4096 or any(c.isspace() or ord(c) < 32 for c in key):
        raise HTTPException(422, 'API Key格式无效，请确认没有空白或控制字符')
    if key and req.clear_api_key:
        raise HTTPException(422, '不能同时填写新密钥并选择无需密钥')
    with llm_gateway.CONFIG_LOCK:
        previous = llm_gateway.configuration_snapshot()
        if previous.api_key and not key and not req.clear_api_key and previous.base_url:
            try:
                previous_origin = _origin(previous.base_url)
            except ValueError:
                previous_origin = None
            if previous_origin != _origin(base_url):
                raise HTTPException(422, '更换服务地址时，请填写该服务的API Key，或选择“此服务无需密钥”')
        next_key = '' if req.clear_api_key else key or previous.api_key
        values = {'LLM_BASE_URL': base_url, 'LLM_MODEL': model,
                  'LLM_API_KEY': next_key, 'LLM_TIMEOUT_SECONDS': str(req.timeout_seconds)}
        try:
            _persist(values)
        except OSError:
            raise HTTPException(503, '配置保存失败，请检查后端配置文件是否可写；原配置继续有效') from None
        # Apply only after the complete file was atomically committed. Each
        # inference captures one snapshot, so an in-flight request stays coherent.
        settings.llm_base_url = base_url
        settings.llm_model = model
        settings.llm_api_key = next_key
        settings.llm_timeout_seconds = req.timeout_seconds
        return {**public_configuration(), 'saved': True, 'message': '配置已保存并立即生效，无需重启后端'}


@router.get('/config')
def model_configuration():
    return public_configuration()


@router.put('/config')
async def update_model_configuration(request: Request):
    origin = request.headers.get('origin')
    if origin and origin not in ALLOWED_ORIGINS:
        raise HTTPException(403, '请从本项目页面保存配置')
    if request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
        raise HTTPException(415, '配置须以JSON提交')
    body = await request.body()
    if len(body) > 16384:
        raise HTTPException(413, '配置内容过长')
    try:
        req = ModelConfiguration.model_validate(json.loads(body))
    except (ValueError, ValidationError):
        # Default validation errors may echo the submitted API key in `input`.
        raise HTTPException(422, '请填写服务地址、模型名及1–120秒的超时；检查配置字段格式') from None
    return save_configuration(req)
