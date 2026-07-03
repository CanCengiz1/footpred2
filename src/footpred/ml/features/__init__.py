"""Importing this package registers all built-in feature groups."""
from footpred.ml.features import odds_features  # noqa: F401
from footpred.ml.features.base import (  # noqa: F401
    FeatureContext,
    FeatureGroup,
    available_feature_groups,
    get_feature_group,
    register_feature_group,
)
