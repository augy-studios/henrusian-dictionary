"""The bot and the website must hash a recovery code identically.

If these two drift, a code created on the site stops redeeming in Telegram, and the failure
looks like a mistyped code rather than a bug. The check shells out to Node so both
implementations are exercised for real. It is skipped where Node is not installed, which is
the normal case on the VPS.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from services import backup_codes

SITE = Path(__file__).resolve().parent.parent.parent / "main-site"
LIB = SITE / "api" / "_lib.js"

SAMPLES = [
    "abcd-efgh-jkmn",
    "ABCDEFGHJKMN",
    "  abcd efgh jkmn  ",
    "ILOU00000000",
    "7qk4xm2p",
    "0000-0000-0000",
]

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not LIB.exists(),
    reason="Node, or the website source, is not available here",
)


def node_digests(pepper):
    # A file URL rather than a path, since Windows drive letters are not a valid ESM specifier.
    script = (
        f"import {{ digestCode, normaliseCode }} from {json.dumps(LIB.as_uri())};"
        f"const samples = {json.dumps(SAMPLES)};"
        "console.log(JSON.stringify(samples.map((s) => "
        "[normaliseCode(s), digestCode(s)])));"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        env={**os.environ, "BACKUP_CODE_PEPPER": pepper},
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


class TestCrossLanguageHashing:
    def test_the_digests_match(self, monkeypatch):
        import config

        pepper = config.BACKUP_CODE_PEPPER
        for sample, (normalised, digest) in zip(SAMPLES, node_digests(pepper)):
            assert backup_codes.normalise(sample) == normalised, sample
            assert backup_codes.digest(sample) == digest, sample

    def test_they_match_without_a_pepper_too(self, monkeypatch):
        import config

        monkeypatch.setattr(config, "BACKUP_CODE_PEPPER", "")
        for sample, (_, digest) in zip(SAMPLES, node_digests("")):
            assert backup_codes.digest(sample) == digest, sample

    def test_a_different_pepper_gives_a_different_digest(self, monkeypatch):
        import config

        monkeypatch.setattr(config, "BACKUP_CODE_PEPPER", "one")
        first = backup_codes.digest("ABCD-EFGH-JKMN")
        monkeypatch.setattr(config, "BACKUP_CODE_PEPPER", "two")
        assert backup_codes.digest("ABCD-EFGH-JKMN") != first
