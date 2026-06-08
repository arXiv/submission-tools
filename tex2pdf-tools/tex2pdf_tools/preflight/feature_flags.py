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

# When hidden/invisible text is detected in the produced (or uploaded) PDF
# (see preflight.hidden_text_pdf), this controls the action:
#   * default (False): treat as a non-blocking warning -- the finding is
#     surfaced (outcome["problems"] / preflight "suspicious" status) but the PDF
#     is kept.
#   * True: treat as a hard QA error -- the service deletes the PDF and fails,
#     and preflight raises CheckPreflightException.
# Enable rejection with PREFLIGHT_HIDDEN_TEXT_REJECT=1 (or true/yes/on/y).
HIDDEN_TEXT_REJECTS: bool = env_flag("PREFLIGHT_HIDDEN_TEXT_REJECT")
