"""Client access to the shared understanding protocol, without server runtime imports."""
from ..agent_contracts import (  # noqa: F401
    EvidenceRef,
    MessageIntent,
    MissingInput,
    TaskUnderstanding,
    UnderstandingDecision,
    UnderstandingRequest,
    validate_understanding,
)
