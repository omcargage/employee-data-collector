"""macOS platform implementation providing input monitoring permission checks and Quartz event tap provider."""
from .permissions import (
    INPUT_MONITORING_EXPLANATION,
    check_input_monitoring_permission,
    is_input_monitoring_granted,
    request_input_monitoring_permission,
)
from .provider import MacOSInputProvider

__all__ = [
    "MacOSInputProvider",
    "is_input_monitoring_granted",
    "request_input_monitoring_permission",
    "check_input_monitoring_permission",
    "INPUT_MONITORING_EXPLANATION",
]
