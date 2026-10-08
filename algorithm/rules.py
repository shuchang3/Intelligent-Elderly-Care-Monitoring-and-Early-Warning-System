"""Time-based rules independent of cameras/models, suitable for deterministic tests."""
from dataclasses import dataclass

@dataclass
class SustainedRule:
    enter_seconds: float
    exit_seconds: float = 2.0
    missing_seconds: float = 5.0
    started: float | None = None
    exited: float | None = None
    last_seen: float | None = None
    active: bool = False

    def update(self, positive: bool, now: float) -> bool:
        self.expire_missing(now)
        self.last_seen=now
        if positive:
            self.exited=None
            if self.started is None:
                self.started=now
            if not self.active and now-self.started >= self.enter_seconds:
                self.active=True
                return True
        else:
            self.started=None
            if self.exited is None:
                self.exited=now
            if now-self.exited >= self.exit_seconds:
                self.active=False
        return False

    def expire_missing(self, now: float) -> bool:
        """Clear accumulated state when observations have stopped."""
        if self.last_seen is None or now-self.last_seen <= self.missing_seconds:
            return False
        self.started=self.exited=None
        self.last_seen=None
        self.active=False
        return True

@dataclass
class CooldownGate:
    seconds: float
    last_allowed: float | None = None

    def allow(self, now: float) -> bool:
        if self.last_allowed is not None and now-self.last_allowed < self.seconds:
            return False
        self.last_allowed=now
        return True

def point_in_polygon(x, y, polygon):
    inside=False
    if len(polygon)<3:
        return False
    j=len(polygon)-1
    for i,(xi,yi) in enumerate(polygon):
        xj,yj=polygon[j]
        if (yi>y)!=(yj>y) and x < (xj-xi)*(y-yi)/(yj-yi)+xi:
            inside=not inside
        j=i
    return inside
