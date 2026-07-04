class BackendUnavailableError(RuntimeError):
    def __init__(self, message: str = "The backend service is currently unavailable.") -> None:
        super().__init__(message)