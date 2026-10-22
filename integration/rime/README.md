# RIME 接入与排查

当前桥接面向 Windows 小狼毫。历史联调环境为小狼毫 0.17.4、librime-lua 和本地 Qwen3-1.7B-Base；其他版本需要自行验证。

## 部署

1. 安装小狼毫，确认普通 `luna_pinyin_simp` 方案可用。
2. 从小狼毫菜单打开“用户文件夹”，记下真实路径。
3. 在项目虚拟环境安装 `.[model,rime]`，准备完整本地模型。
4. 部署方案后，通过小狼毫菜单执行“重新部署”。

```powershell
.\.venv\Scripts\python.exe -m typing_agent.deploy_rime --user-dir D:\typing-agent\rime-user
```

D 盘路径仅为示例，必须换成实际用户目录。部署程序复制方案和 Lua 扩展、更新方案列表，覆盖前备份到 `typing-agent-backups`，不会安装小狼毫或修改注册表。

## 启动

```powershell
.\.venv\Scripts\python.exe -m typing_agent.rime_service --model D:\models\Qwen3-1.7B-Base --mailbox D:\typing-agent\rime-user\typing-agent-ipc
```

消息目录必须是实际用户目录下的 `typing-agent-ipc`，与 Lua 一致。等待 `RIME worker ready`，关闭前台服务可按 Ctrl+C。服务通过进程锁避免同一目录运行多个工作进程。

`scripts/start-rime-model.ps1` 和 `restart-rime-model.ps1` 是开发机便捷脚本，默认使用 D 盘路径，并依赖项目 `.venv`；其他机器建议先使用上述显式参数命令。

## 使用

- F4 选择“智能拼音 · Qwen”，开启“续写开”。
- 先提交“我想吃”，再输入 `pingguo`，稍候 F6 刷新 AI 候选。
- 提交文字后尝试自动预测下一词；空格或数字接受，Esc 关闭，字母开始新拼音。
- Ctrl+F6 清空历史；无拼音时 F6 可重试预测。
- 没有历史或服务不可用时，普通词库仍可输入。

## 没有预测时

1. 检查方案与续写开关。
2. 检查 Python 模型服务是否仍在运行、是否完成加载；服务没有开机自启。
3. 确认 `--mailbox` 与真实用户目录一致。
4. 检查 `worker-status.json` 的状态、更新时间和 PID。异常退出可能留下旧的 `ready`，不能只看字符串。
5. 提交短文本后 F6 重试；改动 Lua 或方案后需重新部署。

拼音 AI 候选目前不自动轮询刷新；自动预测在缓存未命中时最多同步等待 400 ms，超时可能需要手动重试。

## 实现与测试边界

- Lua 通过本地文件通信，模型在独立 Python 进程运行。
- 拼音防抖 150 ms，下一词优先处理、防抖 50 ms；每个会话保留最新请求。
- Python 发布前、Lua 显示前检查请求是否过期。
- 最近 256 字符只来自提交事件，不读取其他应用文档。
- 结果缓存最多 64 项，消息取消/提交后清理，后台另清理过期消息。
- `typing_agent.rime_engine_smoke` 使用真实 librime DLL；需先调整其中的开发机绝对路径，且运行前停止使用同一用户词库的小狼毫服务，结束后恢复。
- 历史报告验证引擎调用链，不等于所有 Windows 应用兼容性和候选窗口外观验收。

切回原方案即可停止使用扩展；停止模型服务不会删除普通词库。
