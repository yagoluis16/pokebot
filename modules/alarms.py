# pokebot/modules/alarms.py
"""Alarms module: death/disconnect/GM detection with sound/webhook."""

from __future__ import annotations
import logging
import re
import threading
import time
import winsound
from modules.base import Module

log = logging.getLogger("pokebot.modules.alarms")


class Alarms(Module):
    name = "alarms"
    config_key = "alarms"

    def __init__(self, ctx=None, bus=None, resolver=None):
        super().__init__(ctx, bus)
        self.resolver = resolver
        self._was_online = True
        self._was_dead = False
        self._last_gm_check = 0.0
        self._disconnect_grace = 0.0
        self._gm_patterns = [
            re.compile(p) for p in self.ctx.get("alarms", "gm_name_patterns", default=[])
        ]

    def tick(self):
        if not self.resolver:
            return

        import time
        now = time.monotonic()

        # Death check
        if self.ctx.get("alarms", "beep_on", default=[]):
            dead = self.resolver.read_field("player", "is_dead")
            if dead and not self._was_dead:
                log.warning("ALARM: Death detected!")
                self._was_dead = True
                self._trigger("death")
            elif not dead:
                self._was_dead = False

        # Disconnect check
        online = self.resolver.read_field("player", "is_online")
        if online is not None:
            if not online and self._was_online:
                if self._disconnect_grace == 0:
                    self._disconnect_grace = now + self.ctx.get("alarms", "disconnect_grace_seconds", default=8)
                elif now > self._disconnect_grace:
                    log.warning("ALARM: Disconnect detected!")
                    self._trigger("disconnect")
                    self._disconnect_grace = 0
            elif online:
                self._was_online = True
                self._disconnect_grace = 0

        # GM detection
        if self._gm_patterns:
            scan_radius = self.ctx.get("alarms", "gm_scan_radius_tiles", default=12)
            if now - self._last_gm_check > 5.0:  # check every 5s
                self._last_gm_check = now
                if self._check_gm(scan_radius):
                    log.warning("ALARM: GM detected!")
                    self._trigger("gm_detected")

        # Low HP warning
        low_hp = self.ctx.get("alarms", "low_hp_percent", default=20)
        hp = self.resolver.read_field("player", "hp")
        hp_max = self.resolver.read_field("player", "hp_max")
        if hp is not None and hp_max and hp_max > 0:
            hp_pct = (hp * 100) // hp_max
            if hp_pct <= low_hp:
                self._trigger("low_hp")

    def _check_gm(self, radius: int) -> bool:
        """Scan nearby creatures for GM name patterns. Placeholder."""
        # PLACEHOLDER — needs entity list offsets, not yet reversed
        # TODO: reverse entity enumeration, names and positions before matching nearby GM names.
        # Requires creature_list block calibrated
        return False

    def _trigger(self, event: str):
        beep_on = self.ctx.get("alarms", "beep_on", default=[])
        webhook_on = self.ctx.get("alarms", "webhook_on", default=[])

        if event in beep_on:
            self._beep()

        if event in webhook_on:
            self._send_webhook(event)

    def _beep(self):
        pattern = self.ctx.get("alarms", "beep_pattern", default={"count": 5, "interval_ms": 180})
        count = pattern.get("count", 5)
        interval = pattern.get("interval_ms", 180)
        for _ in range(count):
            winsound.Beep(1000, 100)
            time.sleep(interval / 1000.0)

    def _send_webhook(self, event: str):
        if not self.ctx.get("notify", "webhook_enabled", default=False):
            return
        url = self.ctx.get("notify", "webhook_url", default="")
        if not url:
            return
        # Fire and forget in background
        threading.Thread(target=self._post_webhook, args=(event, url), daemon=True).start()

    def _post_webhook(self, event: str, url: str):
        try:
            import urllib.request
            import json
            data = {
                "username": self.ctx.get("notify", "webhook_username", default="PokeAlliance Bot"),
                "content": f"🚨 **{event.upper()}** detected!",
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(data).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=self.ctx.get("notify", "timeout_seconds", default=8))
        except Exception as exc:
            log.debug("Webhook failed: %s", exc)
