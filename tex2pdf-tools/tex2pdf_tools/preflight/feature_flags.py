"""This module implements feature flags based on environment variables."""

import os


def env_flag(env_var: str, default: bool = False) -> bool:
    environ_string = os.environ.get(env_var, "").strip().lower()
    if not environ_string:
        return default
    return environ_string in ["1", "true", "yes", "on", "y"]


# Feature flag style: enable features via environment variables
ENABLE_LUALATEX: bool = env_flag("ENABLE_LUALATEX")

# Enable JavaScript checks
ENABLE_JS_CHECKS: bool = env_flag("ENABLE_JS_CHECKS")

# When a source-check plugin flags a file (e.g. obfuscated source), also flip the
# overall preflight status to "suspicious".  The per-file issues are attached
# regardless; this only controls the top-level status surfacing.  Opt-in
# (default False), consistent with the other PREFLIGHT_* flags -- set
# PREFLIGHT_SOURCE_SUSPICIOUS=1 in the deployment env to enable.
SOURCE_CHECK_SETS_SUSPICIOUS: bool = env_flag("PREFLIGHT_SOURCE_SUSPICIOUS")
