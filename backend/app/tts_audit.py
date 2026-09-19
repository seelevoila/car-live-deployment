"""Opt-in measurement only; never modifies tensors, sampling or audio."""
from functools import wraps
import json
from pathlib import Path
import time
from uuid import uuid4


def instrument_pipeline(pipeline, output):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    active = [None]
    decoder_class = type(pipeline.t2s_model.model)
    original_semantic = decoder_class.infer_panel_naive

    @wraps(original_semantic)
    def semantic(self, *args, **kwargs):
        for tokens, final in original_semantic(self, *args, **kwargs):
            if active[0] is not None and kwargs.get('streaming_mode'):
                active[0]['semantic_chunks'].append({
                    'tokens': int(tokens.shape[-1]) if tokens is not None else 0,
                    'final': bool(final),
                    'elapsed_ms': round((time.perf_counter()-active[0]['started'])*1000,3),
                })
            yield tokens, final
    decoder_class.infer_panel_naive = semantic

    for name in ('decode','decode_streaming'):
        original = getattr(pipeline.vits_model,name)
        def decode(*args,_original=original,_name=name,**kwargs):
            start=time.perf_counter()
            result=_original(*args,**kwargs)
            if active[0] is not None:
                active[0]['acoustic_calls'].append({'method':_name,'input_tokens':int(args[0].shape[-1]),
                    'result_length':kwargs.get('result_length'),'ms':round((time.perf_counter()-start)*1000,3)})
            return result
        setattr(pipeline.vits_model,name,decode)

    original_run=pipeline.run
    @wraps(original_run)
    def run(inputs):
        state={'request_id':uuid4().hex,'started':time.perf_counter(),'params':inputs,
               'semantic_chunks':[],'acoustic_calls':[],'audio_chunks':[]}
        active[0]=state
        try:
            for rate,audio in original_run(inputs):
                state['audio_chunks'].append({'samples':len(audio),'sample_rate':rate,
                    'elapsed_ms':round((time.perf_counter()-state['started'])*1000,3)})
                yield rate,audio
        except Exception as exc:
            state['error']=f'{type(exc).__name__}: {exc}'
            raise
        finally:
            state['total_ms']=round((time.perf_counter()-state.pop('started'))*1000,3)
            active[0]=None
            with output.open('a',encoding='utf-8') as stream:
                stream.write(json.dumps(state,ensure_ascii=False,default=str)+'\n')
    pipeline.run=run
