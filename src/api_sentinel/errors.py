class Problem(Exception):
    def __init__(self, status: int, code: str, detail: str, retry_after: int | None = None) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail
        self.retry_after = retry_after
