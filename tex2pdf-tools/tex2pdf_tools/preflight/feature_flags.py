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

# When a file is flagged as obfuscated source (see preflight.obfuscation), also
# flip the overall preflight status to "suspicious".  The per-file issue is
# always attached regardless; this only controls the top-level status surfacing
# so it can be toggled without disturbing downstream pipelines.
# Defaults to False (per env_flag)
OBFUSCATION_SETS_SUSPICIOUS_STATUS: bool = env_flag("PREFLIGHT_OBFUSCATION_SUSPICIOUS")
