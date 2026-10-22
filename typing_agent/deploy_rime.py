"""Copy our independent RIME schema; back up each existing changed file."""
import argparse
from datetime import datetime
from pathlib import Path
import shutil


def main():
    import yaml
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user-dir', default='D:/typing-agent/rime-user')
    args = parser.parse_args()
    user = Path(args.user_dir).resolve()
    source = Path(__file__).resolve().parent.parent / 'integration' / 'rime'
    backup = user / 'typing-agent-backups' / datetime.now().strftime('%Y%m%d-%H%M%S')
    user.mkdir(parents=True, exist_ok=True)
    (user / 'typing-agent-ipc').mkdir(exist_ok=True)
    for relative in ('typing_agent.schema.yaml', 'lua/typing_agent.lua'):
        target = user / relative
        if target.exists():
            saved = backup / relative
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, saved)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, target)
    custom = user / 'default.custom.yaml'
    content = yaml.safe_load(custom.read_text(encoding='utf-8')) if custom.exists() else {}
    content = content or {}
    patch = content.setdefault('patch', {})
    if not isinstance(patch, dict):
        raise ValueError('Existing default.custom.yaml uses unsupported patch format; retained unchanged')
    key = 'schema_list' if isinstance(patch.get('schema_list'), list) else 'schema_list/+'
    schemas = patch.setdefault(key, [])
    if not isinstance(schemas, list):
        raise ValueError('Unsupported schema list; retained unchanged')
    if not any(isinstance(item, dict) and item.get('schema') == 'typing_agent' for item in schemas):
        if custom.exists():
            backup.mkdir(parents=True, exist_ok=True)
            shutil.copy2(custom, backup / custom.name)
        schemas.append({'schema': 'typing_agent'})
        custom.write_text(yaml.safe_dump(content, allow_unicode=True, sort_keys=False), encoding='utf-8')
    print(f'Deployed files to {user}; run WeaselDeployer.exe /deploy to compile')


if __name__ == '__main__':
    main()
