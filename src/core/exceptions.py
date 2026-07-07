class XinDLError(Exception):
    """Base exception for XinDL errors."""
    pass

class ValidationError(XinDLError):
    """Raised when media validation fails and cannot be recovered."""
    def __init__(self, message: str, fallback_suggested: bool = False):
        super().__init__(message)
        self.message = message
        self.fallback_suggested = fallback_suggested

class RepairFailedError(ValidationError):
    """Raised when an automated repair attempt fails."""
    pass
