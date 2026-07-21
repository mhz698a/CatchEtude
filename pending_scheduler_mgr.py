from __future__ import annotations

from PyQt6 import QtCore
from utils import run_in_threadpool
from typing import Callable


class PendingScheduler(QtCore.QObject):
    def __init__(
        self,
        trigger: Callable[[], None],
        parent=None,
        check_interval_ms: int = 15000,
    ):
        super().__init__(parent)
        self._trigger = trigger
        self._enabled = False
        self._scheduled_time = QtCore.QTime(20, 15)
        self._last_fired_date = None

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(check_interval_ms)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def configure(self, enabled: bool, time_obj: QtCore.QTime):
        self._enabled = bool(enabled)
        if time_obj.isValid():
            self._scheduled_time = time_obj

    def _tick(self):
        if not self._enabled:
            return

        now = QtCore.QTime.currentTime()
        today = QtCore.QDate.currentDate()

        if self._last_fired_date == today:
            return

        if (
            now.hour() == self._scheduled_time.hour()
            and now.minute() == self._scheduled_time.minute()
        ):
            self._last_fired_date = today
            run_in_threadpool(self._trigger)
