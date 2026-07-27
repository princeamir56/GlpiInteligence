"""GLPI Connector — Layer 1 of the Sartex Group intelligent pipeline."""
from .client import GLPIClient
from .config import GLPIConfig
from .exceptions import (
    GLPIAPIError,
    GLPIAuthError,
    GLPIRateLimited,
    GLPISessionExpired,
    GLPIUnavailable,
)
from .extractors import (
    TICKET_FIELD_MAP,
    extract_categories,
    extract_entities,
    extract_groups,
    extract_ticket_followups,
    extract_tickets,
    extract_users,
)

__all__ = [
    "GLPIClient",
    "GLPIConfig",
    "GLPIAPIError",
    "GLPIAuthError",
    "GLPIRateLimited",
    "GLPISessionExpired",
    "GLPIUnavailable",
    "TICKET_FIELD_MAP",
    "extract_tickets",
    "extract_users",
    "extract_entities",
    "extract_categories",
    "extract_groups",
    "extract_ticket_followups",
]
