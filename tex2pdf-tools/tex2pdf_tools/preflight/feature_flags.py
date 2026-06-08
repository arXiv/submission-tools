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

# When the produced/uploaded PDF hides text behind an opaque image (see
# preflight.occluded_text), this controls the action:
#   * default (False): non-blocking warning -- surfaced (outcome["problems"] /
#     preflight "suspicious" status), PDF kept.
#   * True: hard QA error -- the service deletes the PDF and fails, and preflight
#     raises CheckPreflightException.
# Enable rejection with PREFLIGHT_OCCLUDED_TEXT_REJECT=1 (or true/yes/on/y).
OCCLUDED_TEXT_REJECTS: bool = env_flag("PREFLIGHT_OCCLUDED_TEXT_REJECT")
