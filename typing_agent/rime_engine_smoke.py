"""Integration test against the installed librime DLL (no Windows UI automation).

Run with WeaselServer stopped so the user dictionary is not opened twice.
The model worker must be running for the same RIME user directory.
"""
import ctypes as C
import json
import os
from pathlib import Path
import time
import argparse


class Traits(C.Structure):
    _fields_ = [('data_size', C.c_int)] + [(n, C.c_char_p) for n in
        ('shared_data_dir', 'user_data_dir', 'distribution_name', 'distribution_code_name',
         'distribution_version', 'app_name')] + [('modules', C.POINTER(C.c_char_p)),
         ('min_log_level', C.c_int), ('log_dir', C.c_char_p), ('prebuilt_data_dir', C.c_char_p),
         ('staging_dir', C.c_char_p)]


class Composition(C.Structure):
    _fields_ = [(n, C.c_int) for n in ('length', 'cursor_pos', 'sel_start', 'sel_end')] + [('preedit', C.c_char_p)]


class Candidate(C.Structure):
    _fields_ = [('text', C.c_char_p), ('comment', C.c_char_p), ('reserved', C.c_void_p)]


class Menu(C.Structure):
    _fields_ = [(n, C.c_int) for n in ('page_size', 'page_no', 'is_last_page', 'highlighted_candidate_index', 'num_candidates')] + [
        ('candidates', C.POINTER(Candidate)), ('select_keys', C.c_char_p)]


class Context(C.Structure):
    _fields_ = [('data_size', C.c_int), ('composition', Composition), ('menu', Menu),
                ('commit_text_preview', C.c_char_p), ('select_labels', C.POINTER(C.c_char_p))]


class Commit(C.Structure):
    _fields_ = [('data_size', C.c_int), ('text', C.c_char_p)]


API_NAMES = '''setup set_notification_handler initialize finalize start_maintenance
is_maintenance_mode join_maintenance_thread deployer_initialize prebuild deploy deploy_schema
deploy_config_file sync_user_data create_session find_session destroy_session cleanup_stale_sessions
cleanup_all_sessions process_key commit_composition clear_composition get_commit free_commit
get_context free_context get_status free_status set_option get_option set_property get_property
get_schema_list free_schema_list get_current_schema select_schema'''.split()


class Api(C.Structure):
    _fields_ = [('data_size', C.c_int)] + [(name, C.c_void_p) for name in API_NAMES]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--predict', action='store_true')
    args = parser.parse_args()
    root = Path('D:/Rime/weasel-0.17.4')
    user = Path('D:/typing-agent/rime-user')
    # Keep DLL search-directory handle alive until finalization.
    dll_directory = os.add_dll_directory(str(root))
    lib = C.CDLL(str(root / 'rime.dll'))
    lib.rime_get_api.restype = C.POINTER(Api)
    api = lib.rime_get_api().contents
    if api.data_size < C.sizeof(Api) - C.sizeof(C.c_int):
        raise RuntimeError('librime API is too old')

    def function(name, result, *args):
        pointer = getattr(api, name)
        if not pointer:
            raise RuntimeError(f'Missing API: {name}')
        return C.CFUNCTYPE(result, *args)(pointer)

    traits = Traits(); traits.data_size = C.sizeof(Traits)-C.sizeof(C.c_int)
    traits.shared_data_dir = str(root / 'data').encode()
    traits.user_data_dir = str(user).encode()
    traits.app_name = b'rime.typing_agent_smoke'
    traits.distribution_name = b'Typing Agent'
    traits.distribution_code_name = b'TypingAgent'
    traits.distribution_version = b'0.1'
    traits.min_log_level = 1
    traits.log_dir = b'D:/typing-agent/logs'
    modules = (C.c_char_p * 3)(b'default', b'lua', None)
    traits.modules = modules
    setup = function('setup', None, C.POINTER(Traits)); setup(C.byref(traits))
    initialize = function('initialize', None, C.POINTER(Traits)); initialize(C.byref(traits))
    sid = function('create_session', C.c_size_t)()
    key = function('process_key', C.c_int, C.c_size_t, C.c_int, C.c_int)
    get_context = function('get_context', C.c_int, C.c_size_t, C.POINTER(Context))
    free_context = function('free_context', C.c_int, C.POINTER(Context))

    def candidates():
        ctx = Context(); ctx.data_size = C.sizeof(Context)-C.sizeof(C.c_int)
        if not get_context(sid, C.byref(ctx)):
            raise RuntimeError('get_context failed')
        try:
            return [{'text': (ctx.menu.candidates[i].text or b'').decode(),
                     'comment': (ctx.menu.candidates[i].comment or b'').decode()}
                    for i in range(ctx.menu.num_candidates)]
        finally:
            free_context(C.byref(ctx))

    try:
        if not function('select_schema', C.c_int, C.c_size_t, C.c_char_p)(sid, b'typing_agent'):
            raise RuntimeError('Cannot select typing_agent schema')
        function('set_option', None, C.c_size_t, C.c_char_p, C.c_int)(sid, b'ascii_mode', 0)
        # Feed context through the actual input-method commit path, not a test hook.
        for char in 'woxiangchi':
            key(sid, ord(char), 0)
        context_candidates = candidates()
        if not context_candidates or context_candidates[0]['text'] != '我想吃':
            raise AssertionError(f'Unexpected context candidate: {context_candidates}')
        commit_start = time.perf_counter()
        key(sid, 0x20, 0)
        commit_ms = (time.perf_counter()-commit_start)*1000
        initial_commit = Commit(); initial_commit.data_size = C.sizeof(Commit)-C.sizeof(C.c_int)
        if not function('get_commit', C.c_int, C.c_size_t, C.POINTER(Commit))(sid, C.byref(initial_commit)):
            raise AssertionError('Missing context commit')
        context_text = (initial_commit.text or b'').decode()
        function('free_commit', C.c_int, C.POINTER(Commit))(C.byref(initial_commit))
        if context_text != '我想吃':
            raise AssertionError(context_text)
        if args.predict:
            predicted = candidates()
            if not predicted or not all('预测' in item['comment'] for item in predicted):
                raise AssertionError(f'No automatic next-word predictions: {predicted}')
            expected = predicted[0]['text']
            key(sid, 0x20, 0)
            followup = Commit(); followup.data_size = C.sizeof(Commit)-C.sizeof(C.c_int)
            if not function('get_commit', C.c_int, C.c_size_t, C.POINTER(Commit))(sid, C.byref(followup)):
                raise AssertionError('Prediction did not commit')
            actual = (followup.text or b'').decode()
            function('free_commit', C.c_int, C.POINTER(Commit))(C.byref(followup))
            if actual != expected:
                raise AssertionError((actual, expected))
            key(sid, 0xff1b, 0)  # dismiss any chained prediction
            for char in 'nihao':
                key(sid, ord(char), 0)
            typed = candidates()
            if not typed or typed[0]['text'] != '你好':
                raise AssertionError(f'Typing after dismissal failed: {typed}')
            report = {'scope': 'Automatic zero-input prediction in actual librime; no F6 or next-word pinyin',
                      'context': context_text, 'predictions': predicted, 'accepted': actual,
                      'commit_and_prediction_ms': commit_ms, 'typing_after_dismissal': typed}
            Path('benchmarks/rime-prediction-smoke.json').write_text(json.dumps(report, ensure_ascii=False, indent=2),encoding='utf-8')
            print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
            return
        start = time.perf_counter()
        for char in 'pingguo':
            key(sid, ord(char), 0)
        key_ms = (time.perf_counter()-start)*1000
        before = candidates()
        print(json.dumps({'fallback_candidates': before, 'key_processing_ms': key_ms}, ensure_ascii=False), flush=True)
        if not before:
            raise AssertionError('Traditional candidates missing')
        deadline = time.monotonic()+30
        after = []
        while time.monotonic() < deadline:
            key(sid, 0xffc3, 0)
            after = candidates()
            if any('AI' in c['comment'] and c['text'] == '苹果' for c in after):
                break
            time.sleep(0.2)
        else:
            raise AssertionError(f'No AI apple candidate: {after}')
        if after[0]['text'] != '苹果':
            raise AssertionError(f'AI candidate not first: {after}')
        key(sid, 0x20, 0)
        commit = Commit(); commit.data_size = C.sizeof(Commit)-C.sizeof(C.c_int)
        if not function('get_commit', C.c_int, C.c_size_t, C.POINTER(Commit))(sid, C.byref(commit)):
            raise AssertionError('No committed text')
        committed = (commit.text or b'').decode()
        function('free_commit', C.c_int, C.POINTER(Commit))(C.byref(commit))
        if committed != '苹果':
            raise AssertionError(committed)
        report = {'scope': 'Installed librime + Lua + real Qwen worker; no Windows window screenshot',
                  'context': context_text, 'fallback': before, 'ai_candidates': after, 'committed': committed, 'key_processing_ms': key_ms}
        Path('benchmarks/rime-engine-smoke.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    finally:
        function('destroy_session', C.c_int, C.c_size_t)(sid)
        function('finalize', None)()
        dll_directory.close()


if __name__ == '__main__':
    main()
