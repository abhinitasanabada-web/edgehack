"""Exercise upload authorization without Docker, training, credentials or networking."""
import os
from pathlib import Path
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]

@pytest.mark.parametrize('opt_in,repo,expected', [
    (None, 'example/model', False),
    ('false', 'example/model', False),
    ('true', 'example/model', True),
    ('true', '', None),
    ('typo', 'example/model', None),
])
def test_upload_requires_explicit_opt_in(tmp_path, opt_in, repo, expected):
    scripts = tmp_path / 'finetune'
    (scripts / 'data').mkdir(parents=True)
    (scripts / 'data' / 'sft.jsonl').write_text('{}\n')
    script = scripts / 'run_finetune.sh'
    script.write_text((ROOT / 'finetune/run_finetune.sh').read_text())
    fake = tmp_path / 'docker'
    fake.write_text('#!/bin/sh\nprintf "%s\\n" "$@" >> "$DOCKER_LOG"\n')
    fake.chmod(0o755)
    log = tmp_path / 'docker.log'
    env = {**os.environ, 'STAGE': 'train', 'DOCKER': str(fake), 'DOCKER_LOG': str(log),
           'ALLOW_SERVING': '1', 'HF_REPO_ID': repo, 'HF_TOKEN': ''}
    env.pop('PUSH_TO_HF', None)
    if opt_in is not None:
        env['PUSH_TO_HF'] = opt_in
    result = subprocess.run(['bash', str(script)], env=env, capture_output=True, text=True)
    if expected is None:
        assert result.returncode != 0
        assert not log.exists()  # Reject invalid upload configuration before any Docker work.
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert ('--push' in log.read_text()) is expected
