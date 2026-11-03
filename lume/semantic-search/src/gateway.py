"""Coordinate retries across workers instead of retrying a gateway outage in bulk."""
from collections import deque
from contextlib import contextmanager
import threading
import time


class GatewayGuard:
    def __init__(self,maximum=64,clock=time.monotonic,cooldown=15,recovery=60):
        self.maximum=maximum;self.clock=clock;self.cooldown=cooldown;self.recovery=recovery
        self.condition=threading.Condition();self.errors=deque();self.limited_at=0.
        self.until=0.;self.active=0;self.waiting=0

    def _limit(self,now):
        if not self.limited_at:return self.maximum
        age=now-self.limited_at
        if age<self.recovery:return min(4,self.maximum)
        return min(self.maximum,4*2**min(5,int((age-self.recovery)/15)))

    def error(self,status,retry_after=0):
        now=self.clock()
        with self.condition:
            self.errors.append(now)
            while self.errors and self.errors[0]<now-30:self.errors.popleft()
            if status==429 or len(self.errors)>=3:
                self.limited_at=now
                self.until=max(self.until,now+max(self.cooldown,min(120,retry_after)))
            self.condition.notify_all()

    def snapshot(self):
        with self.condition:
            now=self.clock()
            return {'http_inflight':self.active,'workers_waiting':self.waiting,
                'http_concurrency_limit':self._limit(now),'cooldown_seconds':max(0,self.until-now),
                'degraded':bool(self.limited_at and now-self.limited_at<self.recovery)}

    @contextmanager
    def slot(self,check):
        with self.condition:
            self.waiting+=1
            try:
                while True:
                    check();now=self.clock()
                    if now>=self.until and self.active<self._limit(now):
                        self.active+=1;break
                    self.condition.wait(timeout=.5)
            finally:self.waiting-=1
        try:yield
        finally:
            with self.condition:
                self.active-=1;self.condition.notify_all()
