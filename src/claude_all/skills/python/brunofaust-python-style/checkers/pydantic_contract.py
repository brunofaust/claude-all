from typing import Any

from pydantic import BaseModel, validator


class FreeThreadCheck(BaseModel):
    python_version: str
    asyncio_support: bool

    @validator('python_version')
    def check_python_version(cls, v: str):
        if not v.startswith('3.14'):
            raise ValueError('Python 3.14 or newer required for free-thread')
        return v

    @validator('asyncio_support')
    def check_asyncio_support(cls, v: bool):
        if not v:
            raise ValueError('Asyncio free-thread support required')
        return v

class CodeConformanceCheck(BaseModel):
    free_thread_check: FreeThreadCheck
    custom_hooks: list[str] = []
    issues: list[str] = []

    def validate(self, context: dict[str, Any]) -> None:
        # Example validation logic
        if not context.get('has_free_threaddoors', False):
            self.issues.append('Missing free-thread setup')

    def dict(self) -> dict[str, Any]:
        return super().dict()
