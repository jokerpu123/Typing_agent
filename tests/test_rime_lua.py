import importlib.util
from pathlib import Path
import tempfile
import unittest

from typing_agent.rime_bridge import Request, response_bytes


@unittest.skipUnless(importlib.util.find_spec('lupa'), 'Install lupa for Lua runtime tests')
class LuaBridgeTests(unittest.TestCase):
    def setUp(self):
        from lupa import LuaRuntime
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'typing-agent-ipc').mkdir()
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.globals().user_dir = self.root.as_posix()
        self.lua.execute('''
          rime_api = {get_user_data_dir=function() return user_dir end}
          received = {}
          function Candidate(kind, start, finish, text, comment)
            return {type=kind, start=start, _end=finish, text=text, comment=comment}
          end
          function yield(candidate) table.insert(received, candidate) end
          function Set(values) return values end
          function Segment(start, finish)
            return {start=start, _end=finish, has_tag=function(self, tag)
              for _, item in ipairs(self.tags or {}) do if item==tag then return true end end
              return false
            end}
          end
          function notifier()
            return {connect=function(self, fn)
              self.callback=fn
              return {disconnect=function() end}
            end}
          end
          ctx = {input='pingguo', props={}, commit_notifier=notifier(), update_notifier=notifier(), refreshes=0}
          function ctx:get_property(key) return self.props[key] or '' end
          function ctx:set_property(key, value) self.props[key]=value end
          function ctx:get_option(key) return key=='next_word_prediction' and self.prediction_enabled end
          function ctx:get_commit_text() return self.committed or '' end
          function ctx:refresh_non_confirmed_composition() self.refreshes=self.refreshes+1 end
          ctx.composition = {push_back=function(self, segment) self[#self+1]=segment end}
          function ctx:push_input(text)
            self.input=self.input..text
            self.update_notifier.callback(self)
          end
          function ctx:clear()
            self.input=''
            for i=#self.composition,1,-1 do self.composition[i]=nil end
            self.update_notifier.callback(self)
          end
          env = {engine={context=ctx}}
          seg = {start=0, _end=7, has_tag=function() return false end}
        ''')
        self.module = self.lua.execute(Path('integration/rime/lua/typing_agent.lua').read_text(encoding='utf-8'))
        self.lua.globals().bridge = self.module
        self.lua.execute("bridge.processor.init(env); ctx.committed='我想吃'; ctx.commit_notifier.callback(ctx); bridge.translator(ctx.input, seg, env)")
        self.request_path = next((self.root / 'typing-agent-ipc').glob('*.req'))

    def tearDown(self):
        self.lua.execute('bridge.processor.fini(env)')
        self.temp.cleanup()

    def test_roundtrip_and_stale_rejection(self):
        request = Request.decode(self.request_path.read_bytes())
        self.request_path.with_suffix('.res').write_bytes(response_bytes(request, ['苹果'], 10))
        self.lua.execute('bridge.translator(ctx.input, seg, env)')
        self.assertEqual(self.lua.globals().received[1].text, '苹果')
        self.lua.execute("received={}; ctx.input='gongyuan'; seg._end=8; bridge.translator(ctx.input,seg,env)")
        self.assertEqual(len(self.lua.globals().received), 0)
        updated = Request.decode(self.request_path.read_bytes())
        self.assertGreater(updated.revision, request.revision)

    def test_commit_history_and_clear_shortcut(self):
        self.assertEqual(Request.decode(self.request_path.read_bytes()).context, '我想吃')
        self.lua.execute('''
          key={keycode=0xffc3, release=function() return false end, ctrl=function() return true end}
          assert(bridge.processor.func(key,env)==1)
          bridge.translator(ctx.input,seg,env)
        ''')
        self.assertFalse(self.request_path.exists())
        self.assertEqual(self.lua.globals().ctx.refreshes, 1)

    def test_cancel_removes_request(self):
        self.lua.execute("ctx.input=''; ctx.update_notifier.callback(ctx)")
        self.assertFalse(self.request_path.exists())

    def test_auto_prediction_without_pinyin_and_dismiss_on_typing(self):
        self.lua.execute("ctx.prediction_enabled=true; ctx.committed='苹果'; ctx.commit_notifier.callback(ctx)")
        prediction_path = next((self.root/'typing-agent-ipc').glob('*-next.req'))
        request = Request.decode(prediction_path.read_bytes())
        self.assertEqual(request.pinyin, '@next')
        self.assertEqual(request.context, '我想吃苹果')
        prediction_path.with_suffix('.res').write_bytes(response_bytes(request, ['香蕉','面条'], 12))
        self.lua.execute("received={}; ctx:clear(); bridge.translator('',ctx.composition[1],env)")
        self.assertEqual(self.lua.globals().ctx.input, '')
        self.assertEqual(self.lua.globals().received[1].text, '香蕉')
        self.assertEqual(self.lua.globals().received[1].type, 'prediction')
        self.lua.execute('''
          key={keycode=110,release=function() return false end,ctrl=function() return false end}
          assert(bridge.processor.func(key,env)==2)
        ''')
        self.assertEqual(len(self.lua.globals().ctx.composition), 0)
