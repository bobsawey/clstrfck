"""Single source of truth for the pipeline's own version string.

Bump this whenever normalize/extract logic changes in a way that should
invalidate cached representations or artifacts (it participates in
extractor_version / config_hash for the internal text-norm path).
"""

PIPELINE_VERSION = "0.1.0"
