"""The README's numbers are load-bearing.

This product's entire pitch is that every number it prints is checkable. A test
count that drifts is the one error that costs more than the thing it misstates:
a judge who runs the suite and sees a different number has been handed a reason
to doubt every other figure in the repo.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import config


def _collected_test_count() -> int:
    """Ask pytest how many tests exist, without running them.

    `--collect-only` imports the test modules but executes no test bodies, so
    this cannot recurse into itself. Never shell out to a full `pytest` run
    from inside a test.
    """
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("PYTHONPATH", "AMENT_PREFIX_PATH")
    }
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
        capture_output=True,
        text=True,
        cwd=config.ROOT,
        env=env,
    ).stdout
    match = re.search(r"(\d+) tests? collected", out)
    assert match, f"could not parse a collection count from:\n{out[-2000:]}"
    return int(match.group(1))


def test_readme_test_count_is_true():
    actual = _collected_test_count()
    readme = (Path(config.ROOT) / "README.md").read_text()
    claimed = {int(m) for m in re.findall(r"(\d+) tests", readme)}
    assert claimed == {actual}, f"README claims {claimed or '{}'}, suite has {actual}"


def test_every_provider_row_is_complete():
    """`MODEL` is no longer dead config -- `ledgerlens/llm.py` calls the API through
    it. It is also no longer a vendor string: pinning one here would re-hardcode the
    coupling that `config.PROVIDERS` exists to remove, so the guard moved to the seam.

    What must stay true is that every declared provider is USABLE: a model id, the env
    var that unlocks it, and both prices, or the telemetry panel divides by a missing
    number the first time someone switches vendor on stage.
    """
    assert config.PROVIDERS, "at least one provider must be declared"
    for name, spec in config.PROVIDERS.items():
        assert spec.name == name, f"{name!r} keys a row named {spec.name!r}"
        assert spec.model, f"{name} declares no model id"
        assert spec.api_key_env.endswith("_API_KEY"), f"{name}: {spec.api_key_env} is not an api-key env var"
        assert spec.price_in_per_mtok > 0 and spec.price_out_per_mtok > 0, f"{name} is unpriced"


def test_every_provider_has_a_transport():
    """A row in the table with no adapter behind it is a provider that resolves to a
    clean error message instead of an LLM -- the failure is graceful, which is exactly
    why it would ship unnoticed."""
    from ledgerlens import llm

    assert set(config.PROVIDERS) == set(llm._ADAPTERS), (
        f"providers {sorted(config.PROVIDERS)} but transports {sorted(llm._ADAPTERS)}"
    )


def test_readme_documents_the_default_provider():
    """The README tells a judge which vendor runs by default and which env var turns
    it on. Both are claims about config, so both are assertions."""
    readme = (Path(config.ROOT) / "README.md").read_text()
    spec = config.provider_spec()
    assert spec is not None, f"default provider {config.LLM_PROVIDER!r} is not in the table"
    assert spec.model in readme, f"README never names the default model {spec.model}"
    assert spec.api_key_env in readme, f"README never names {spec.api_key_env}"
