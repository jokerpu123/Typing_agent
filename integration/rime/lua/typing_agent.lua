-- Local file mailboxes only: never launch processes or wait for model inference here.
local M = {}
local states = {}
local counter = 0

local function hex(s)
  return (s:gsub('.', function(c) return string.format('%02x', string.byte(c)) end))
end

local function unhex(s)
  if #s % 2 ~= 0 or s:find('[^0-9a-f]') then return nil end
  return (s:gsub('..', function(c) return string.char(tonumber(c, 16)) end))
end

local function state(env)
  local ctx = env.engine.context
  local id = ctx:get_property('typing_agent_session')
  if id == '' then
    counter = counter + 1
    id = tostring(os.time()) .. '-' .. tostring(env):gsub('[^%w]', '') .. '-' .. counter
    ctx:set_property('typing_agent_session', id)
  end
  if not states[id] then
    local root = rime_api.get_user_data_dir() .. '/typing-agent-ipc/'
    states[id] = {id=id, revision=0, history='', signature='', request=root .. id .. '.req', response=root .. id .. '.res',
      worker_status=root .. 'worker-status.json', predicting=false, pending_prediction=false, self_updating=false}
    states[id].next = {id=id .. '-next', revision=0, history='', signature='',
      request=root .. id .. '-next.req', response=root .. id .. '-next.res'}
  end
  return states[id]
end

local function cancel(s)
  s.signature = ''
  os.remove(s.request)
  os.remove(s.response)
end

local function submit(s, input)
  local signature = input .. '\n' .. s.history
  local existing = io.open(s.request, 'rb')
  if existing then existing:close() end
  if s.signature == signature and existing then return end
  s.revision = s.revision + 1
  local body = table.concat({'TA1', s.id, tostring(s.revision), hex(input), hex(s.history)}, '\n') .. '\n'
  local temporary = s.request .. '.new'
  local f = io.open(temporary, 'wb')
  if not f then return end
  f:write(body); f:close()
  os.remove(s.request)
  if os.rename(temporary, s.request) then s.signature = signature end
end

local function read_result(s, input)
  local f = io.open(s.response, 'rb')
  if not f then return {} end
  local text = f:read(8193); f:close()
  if not text or #text > 8192 then return {} end
  local lines = {}
  for line in (text):gmatch('([^\n]*)\n') do lines[#lines+1] = line:gsub('\r$', '') end
  if lines[1] ~= 'TA1' or lines[2] ~= s.id or tonumber(lines[3]) ~= s.revision or
     lines[4] ~= hex(input) or lines[5] ~= hex(s.history) or lines[6] ~= 'ok' then return {} end
  local result = {}
  for i = 8, math.min(#lines, 12) do
    local value = unhex(lines[i])
    if value and value ~= '' then result[#result+1] = value end
  end
  return result, true
end

local function tail(text)
  local count = utf8.len(text)
  if count and count > 256 then return text:sub(utf8.offset(text, count - 255)) end
  return text
end

local function prefetch(s, text)
  if text == '' then return end
  s.next.history = tail(text)
  submit(s.next, '@next')
end

local function now_ms()
  if rime_api.get_time_ms then return rime_api.get_time_ms() end
  return math.floor(os.clock() * 1000)
end

local function worker_ready(s)
  local f = io.open(s.worker_status, 'rb')
  if not f then return false end
  local text = f:read(1024) or ''; f:close()
  return text:find('"state":%s*"ready"') ~= nil
end

local function show_prediction(ctx, s, wait_ms)
  if s.history == '' or ctx:get_option('ascii_mode') or not ctx:get_option('next_word_prediction') then return false end
  prefetch(s, s.history)
  local result, valid = read_result(s.next, '@next')
  -- No indefinite waits. Prefetch usually finishes before the user commits.
  -- On cache miss this prototype allows up to 400ms at commit, never per letter.
  if not valid and worker_ready(s) then
    local deadline = now_ms() + wait_ms
    repeat result, valid = read_result(s.next, '@next') until valid or now_ms() >= deadline
  end
  if #result == 0 then return false end
  s.predictions = result
  s.predicting = true
  local segment = Segment(0, 0)
  segment.tags = Set{'prediction', 'placeholder'}
  ctx.composition:push_back(segment)
  s.self_updating = true
  ctx:push_input('') -- notify the engine, translating a zero-length prediction segment
  s.self_updating = false
  return true
end

local function dismiss_prediction(ctx, s)
  s.predicting = false
  s.pending_prediction = false
  s.self_updating = true
  ctx:clear()
  s.self_updating = false
end

M.processor = {
  init = function(env)
    local s = state(env)
    env.connection = env.engine.context.commit_notifier:connect(function(ctx)
      local committed = ctx:get_commit_text()
      s.history = tail(s.history .. committed)
      s.predicting = false
      s.pending_prediction = committed ~= '' and ctx:get_option('next_word_prediction')
      cancel(s)
      if s.pending_prediction then prefetch(s, s.history) end
    end)
    env.update_connection = env.engine.context.update_notifier:connect(function(ctx)
      if s.self_updating then return end
      if ctx.input == '' then
        cancel(s)
        if s.pending_prediction then
          s.pending_prediction = false
          show_prediction(ctx, s, 400)
        end
      elseif ctx:get_option('next_word_prediction') then
        local preview = ctx:get_commit_text()
        if preview ~= '' then prefetch(s, s.history .. preview) end
      end
    end)
  end,
  func = function(key, env)
    if key:release() then return 2 end -- kNoop
    local ctx = env.engine.context
    local s = state(env)
    if s.predicting then
      if key.keycode == 0xff1b or key.keycode == 0xff08 then
        dismiss_prediction(ctx, s); return 1 -- Escape/Backspace dismiss, no extra deletion
      end
      if (key.keycode >= 0x21 and key.keycode <= 0x7e and not (key.keycode >= 0x31 and key.keycode <= 0x39)) then
        dismiss_prediction(ctx, s) -- normal typing starts a new composition
      end
    end
    if key.keycode == 0xffc3 then -- F6, X11 keysym used by librime
      if key:ctrl() then
        s.history = ''; cancel(s); cancel(s.next)
        s.pending_prediction = false
        if s.predicting then dismiss_prediction(ctx, s) end
      end
      if ctx.input ~= '' then
        ctx:refresh_non_confirmed_composition()
      elseif not s.predicting and not key:ctrl() then
        show_prediction(ctx, s, 400)
      end
      return 1 -- kAccepted
    end
    return 2
  end,
  fini = function(env)
    if env.connection then env.connection:disconnect() end
    if env.update_connection then env.update_connection:disconnect() end
    local s = state(env); cancel(s); cancel(s.next); states[s.id] = nil
  end,
}

M.translator = function(input, seg, env)
  local ctx = env.engine.context
  local s = state(env)
  if seg:has_tag('prediction') and s.predicting then
    for _, text in ipairs(s.predictions or {}) do
      yield(Candidate('prediction', seg._end, seg._end, text, ' 预测'))
    end
    return
  end
  if ctx:get_option('ascii_mode') or seg.start ~= 0 or seg._end ~= #ctx.input or input ~= ctx.input then return end
  if #input > 64 or not input:match("^[a-z' ]+$") then return end
  -- A Base model at BOS is not a useful IME prior. Use the stock dictionary
  -- until this session has some committed context.
  if s.history == '' then cancel(s); return end
  submit(s, input)
  for _, text in ipairs(read_result(s, input)) do
    local candidate = Candidate('typing_agent', seg.start, seg._end, text, ' AI')
    candidate.quality = 100
    yield(candidate)
  end
end

return M
