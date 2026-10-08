"""Stable error codes; exception messages never include browser content or input values."""


class ExecutionError(Exception):
    def __init__(self, code: str, expected: str | None = None, observed: str | None = None):
        super().__init__(code)
        self.code = code
        self.expected = expected
        self.observed = observed


class BusinessOutcome(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code
