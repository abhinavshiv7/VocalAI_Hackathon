from dataclasses import dataclass
from threading import RLock

from ..schemas import FailureInjection


@dataclass
class FailureState:
    kind: str = "none"
    subject: str | None = None
    enabled: bool = False


class FailureController:
    def __init__(self) -> None:
        self._state = FailureState()
        self._lock = RLock()

    def configure(self, injection: FailureInjection) -> FailureState:
        with self._lock:
            self._state = FailureState(
                kind=injection.kind,
                subject=injection.subject,
                enabled=injection.enabled and injection.kind != "none",
            )
            return self.snapshot()

    def snapshot(self) -> FailureState:
        with self._lock:
            return FailureState(**self._state.__dict__)

    def matches(self, kind: str, subject: str) -> bool:
        state = self._state
        return state.enabled and state.kind == kind and state.subject in (None, "all", subject)


failure_controller = FailureController()
