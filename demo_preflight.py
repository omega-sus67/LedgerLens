"""Pre-flight for the demo recording. Run this before `streamlit run app.py`.

The demo is the one artefact that cannot be corrected after the fact. A stale verdict
row shifts the prior and beat 11 opens on the wrong number; an unset API key makes
beats 5 and 6 unfilmable and you find out mid-take; a regenerated dataset moves a
figure the script quotes and nobody notices until it is on camera.

So this checks what can be checked and FIXES what can be fixed, then prints the short
list of things only a human can do.

What it deliberately does NOT do: warm the app's cache. `Store._q_cache` is
per-process and Streamlit's `load_payload` is `@st.cache_resource`, so a diagnosis run
here warms nothing the browser will use. That step stays manual, and is printed as
such rather than silently claimed.

Run it BEFORE starting Streamlit -- DuckDB's file lock is exclusive, so this cannot
open the database while the app holds it.

    env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/python demo_preflight.py
"""

from __future__ import annotations

import os
import subprocess
import sys

import config

OK = "\033[32m  OK  \033[0m"
BAD = "\033[31m FAIL \033[0m"

REQUIRED_DATA = [
    "metrics.parquet",
    "ground_truth.json",
    "events_deploys.json",
    "events_flags.json",
    "events_campaigns.json",
    "events_pricing.json",
    "tickets.json",
]

failures: list[str] = []


def report(status: str, label: str, detail: str = "") -> None:
    print(f"[{status}] {label}" + (f"  --  {detail}" if detail else ""))


def check_provider() -> None:
    """Beats 5 and 6 are the AI half of the demo. Without a resolvable provider they
    cannot be filmed at all, and the sidebar simply renders the toggle disabled --
    which is easy to miss until you are recording."""
    from ledgerlens import llm

    provider, reason = llm.resolve()
    spec = config.provider_spec()
    if provider is None:
        failures.append("no LLM provider")
        env = spec.api_key_env if spec else "GEMINI_API_KEY"
        report(BAD, "AI investigator", f"{reason} -- export {env} or beats 5-6 are unfilmable")
        return
    report(OK, "AI investigator", f"{spec.name} / {spec.model}")


def check_data() -> None:
    missing = [f for f in REQUIRED_DATA if not (config.DATA_DIR / f).exists()]
    if missing:
        failures.append("missing data")
        report(BAD, "Generated data", f"missing {', '.join(missing)} -- run `python -m ledgerlens.gen_data`")
        return
    report(OK, "Generated data", f"{len(REQUIRED_DATA)} files in {config.DATA_DIR.name}/")


def reset_prior() -> None:
    """`verdict` is the only table the app writes to, and the database persists between
    runs. A verdict left by a rehearsal moves P off 0.50, so beat 11's "watch it move"
    opens on an already-moved number."""
    from ledgerlens import learning
    from ledgerlens.store import Store

    try:
        s = Store()
    except Exception as exc:  # noqa: BLE001 -- the lock message is the useful part
        failures.append("database locked")
        report(BAD, "Prior reset", f"cannot open the database ({exc.__class__.__name__}) -- close Streamlit and any pytest run")
        return
    try:
        before = s.con.execute("SELECT COUNT(*) FROM verdict").fetchone()[0]
        s.con.execute("DELETE FROM verdict")
        s.invalidate(learning.PRIOR_LABEL)
        report(OK, "Prior reset", f"cleared {before} stray verdict row(s); P starts at 0.50")
    finally:
        s.close()


def verify_figures() -> None:
    """Every figure the script quotes, against a live diagnosis. This is the check that
    matters -- the others are setup."""
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "AMENT_PREFIX_PATH")}
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_demo_script.py", "-q",
         "-p", "no:cacheprovider", "--no-header", "-x"],
        capture_output=True, text=True, cwd=config.ROOT, env=env,
    )
    if proc.returncode == 0:
        last = [ln for ln in proc.stdout.strip().splitlines() if ln.strip()][-1]
        report(OK, "Script figures", last.strip())
        return
    failures.append("figures drifted")
    report(BAD, "Script figures", "a number in docs/demo_script.md no longer matches the app")
    for line in proc.stdout.splitlines():
        if "AssertionError" in line or "script quotes" in line:
            print(f"        {line.strip()}")


MANUAL = [
    "Load the page once and let the first diagnosis finish -- cold is ~1.3 s, warm ~0.5 s.",
    "Sidebar: metric `mrr_renewals`, as-of 2026-08-17, persona `Revenue Analyst`, both toggles OFF.",
    "Browser ~90% zoom, window ~1600x1000, bookmarks hidden.",
    "Close every other Streamlit and pytest process -- DuckDB's lock is exclusive.",
]


def main() -> int:
    print("\nLedgerLens -- demo pre-flight\n" + "=" * 60)
    check_provider()
    check_data()
    reset_prior()
    verify_figures()

    print("=" * 60)
    if failures:
        print(f"\n{BAD} {len(failures)} blocker(s): {', '.join(failures)}.")
        print("      Fix these before recording -- each one is visible on camera.\n")
        return 1

    print(f"\n{OK} Everything checkable is green. Four things only you can do:\n")
    for i, item in enumerate(MANUAL, 1):
        print(f"      {i}. {item}")
    print("\n      Then: .venv/bin/python -m streamlit run app.py\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
