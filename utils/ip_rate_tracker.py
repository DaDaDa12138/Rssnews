"""
Attack payload detection and IP banning.

utils/ip_rate_tracker.py: AttackDetector scans query strings, paths and form bodies
for exploit signatures and bans the source address. apps/profile/middleware.py::
AttackBanMiddleware calls it for anonymous traffic. The reader rate limiting and the
fail2ban-style 404 counting this module used to carry are gone; only the detector and
the client IP helper remain.
"""
import ipaddress
import re
import time
from urllib.parse import unquote_plus

import redis
from django.conf import settings

# How many of our own proxies sit in front of Django, each appending one
# X-Forwarded-For entry for the peer it saw. Overridable with
# settings.ATTACK_BAN_PROXY_HOPS for deployments with a different chain.
DEFAULT_PROXY_HOPS = 1


def _proxy_hops():
    try:
        return max(0, int(getattr(settings, "ATTACK_BAN_PROXY_HOPS", DEFAULT_PROXY_HOPS)))
    except (TypeError, ValueError):
        return DEFAULT_PROXY_HOPS


def _parse_ip(value):
    try:
        return ipaddress.ip_address((value or "").strip())
    except ValueError:
        return None


def _get_client_ip(request):
    """
    Extract the client IP from a proxied request without trusting the client.

    Every proxy appends one X-Forwarded-For entry for the peer it saw, so the
    entries written by our own infrastructure are the rightmost ones. Counting
    from the right (ATTACK_BAN_PROXY_HOPS, one for the single openresty hop in
    front of this deployment) is the only spoof-resistant read: a client can
    prepend entries but cannot insert one to the right of ours. Reading the
    leftmost entry, or index -2 regardless of chain length, hands the ban list
    to whoever writes the header.
    """
    remote = request.META.get("REMOTE_ADDR", "unknown")
    hops = _proxy_hops()
    if hops == 0:
        return remote

    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    entries = [entry.strip() for entry in forwarded.split(",") if entry.strip()]
    if not entries:
        return remote

    # The entry our outermost proxy saw is the client; when the header is shorter
    # than the chain, the leftmost entry is the only candidate left.
    candidate = entries[-1 - hops] if len(entries) >= hops + 1 else entries[0]
    return candidate if _parse_ip(candidate) else remote


def is_bannable_ip(value):
    """
    True only for globally routable addresses.

    Private, loopback, link-local and CGNAT ranges carry shared infrastructure: the
    docker gateway, a load balancer, a corporate NAT. Banning one blocks every user
    behind it, and a single spoofed header could otherwise take the site down.
    """
    address = _parse_ip(value)
    return bool(address and address.is_global)


class AttackDetector:
    """
    Detect malicious payloads in request query strings, POST bodies, and paths.

    Bans escalate: ten minutes for a first offense, an hour for a second, a day from
    the third on. A shared NAT or a client that mangles one URL should not lose a
    day of access over a single bad request, and repeat offenders still get stopped.
    Subsequent requests from banned IPs are rejected without payload inspection.

    Redis keys (db 3, REDIS_STATISTICS_POOL):
    - atk:ban:{ip} -> "1" with the ban's TTL (banned IP marker)
    - atk:strikes:{ip} -> offense counter, outlives the ban (decides the next rung)
    - atk:log:{ip} -> hash with attack details (for investigation)
    """

    BAN_LADDER_SECONDS = (600, 3600, 86400)  # 10 minutes, 1 hour, 24 hours
    STRIKE_TTL_SECONDS = 7 * 86400

    # Content types where POST body should be scanned (text-based only).
    # Multipart uploads (file uploads) are skipped to avoid buffering large files.
    SCANNABLE_CONTENT_TYPES = (
        "application/x-www-form-urlencoded",
        "application/json",
        "text/plain",
        "text/xml",
        "application/xml",
    )

    # Max POST body bytes to read for scanning
    MAX_BODY_SCAN_BYTES = 8192

    # Attack patterns grouped by type for logging.
    # Keep these tight to avoid false positives on legitimate content
    # (archived web pages, RSS feeds, user comments often contain code snippets).
    ATTACK_PATTERNS = {
        "jndi": [
            r"\$\{jndi:",  # Log4Shell: ${jndi:ldap://...} (was \$\{ which matched JS template literals)
        ],
        "xss": [
            r"<\s*script[^a-zA-Z]",  # <script> tags (require non-alpha after to avoid <scriptName)
        ],
        "sqli": [
            r"(?:UNION\s+(?:ALL\s+)?SELECT)",  # UNION SELECT
            r"(?:;\s*DROP\s+TABLE)",  # ; DROP TABLE
        ],
        "traversal": [
            r"\.\./\.\./\.\./",  # Path traversal (require 3+ levels to reduce false positives)
        ],
        "nullbyte": [
            r"\x00",  # Null byte injection
            r"%00",  # URL-encoded null byte
        ],
    }

    def __init__(self):
        self._redis = None
        # Compile all patterns into a single regex for fast matching, plus keep
        # individual type regexes for classification
        self._type_patterns = {}
        all_patterns = []
        for attack_type, patterns in self.ATTACK_PATTERNS.items():
            combined = "|".join(patterns)
            self._type_patterns[attack_type] = re.compile(combined, re.IGNORECASE)
            all_patterns.extend(patterns)
        self._combined_re = re.compile("|".join(all_patterns), re.IGNORECASE)

    @property
    def redis(self):
        if self._redis is None:
            self._redis = redis.Redis(connection_pool=settings.REDIS_STATISTICS_POOL)
        return self._redis

    def get_ip(self, request):
        return _get_client_ip(request)

    def is_banned(self, ip):
        """Check if an IP is currently banned. Fast Redis GET."""
        try:
            return bool(self.redis.get(f"atk:ban:{ip}"))
        except Exception:
            return False

    def ban_ip(self, ip, attack_type, payload_sample, request):
        """Ban an IP, escalating on repeat offenses, and log the attack. Returns the TTL."""
        strike_key = f"atk:strikes:{ip}"
        strikes = int(self.redis.incr(strike_key) or 1)
        self.redis.expire(strike_key, self.STRIKE_TTL_SECONDS)
        rung = min(strikes, len(self.BAN_LADDER_SECONDS)) - 1
        duration = self.BAN_LADDER_SECONDS[rung]

        pipe = self.redis.pipeline()

        # Set ban marker with the rung's TTL
        ban_key = f"atk:ban:{ip}"
        pipe.set(ban_key, "1", ex=duration)

        # Store attack log for investigation
        log_key = f"atk:log:{ip}"
        log_data = {
            "attack_type": attack_type,
            "payload_sample": payload_sample[:500],
            "path": request.path[:200],
            "user_agent": request.META.get("HTTP_USER_AGENT", "")[:200],
            "banned_at": str(int(time.time())),
            "strikes": str(strikes),
            "ban_seconds": str(duration),
        }
        pipe.hset(log_key, mapping=log_data)
        pipe.expire(log_key, duration)

        pipe.execute()
        return duration

    def classify_attack(self, payload):
        """Return the attack type if payload matches, or None."""
        for attack_type, pattern in self._type_patterns.items():
            if pattern.search(payload):
                return attack_type
        return None

    def _check_payload(self, payload):
        """Check a single payload string for attack patterns. Returns (attack_type, sample) or (None, None)."""
        if payload and self._combined_re.search(payload):
            attack_type = self.classify_attack(payload)
            if attack_type:
                return attack_type, payload[:200]
        return None, None

    def check_request(self, request):
        """
        Inspect request for malicious payloads.

        Checks raw and URL-decoded query strings, URL path, and POST body.
        Returns (attack_type, payload_sample) if attack detected, or (None, None).
        """
        # Check query string (raw first, then decoded to catch encoded payloads).
        # unquote_plus handles both %XX encoding and + as space (form encoding).
        query_string = request.META.get("QUERY_STRING", "")
        if query_string:
            result = self._check_payload(query_string)
            if result[0]:
                return result
            decoded_qs = unquote_plus(query_string)
            if decoded_qs != query_string:
                result = self._check_payload(decoded_qs)
                if result[0]:
                    return result

        # Check URL path
        result = self._check_payload(request.path)
        if result[0]:
            return result

        # Check POST body for text-based content types only.
        # Skip multipart/form-data (file uploads) to avoid buffering large files.
        if request.method == "POST":
            content_type = request.META.get("CONTENT_TYPE", "").split(";")[0].strip().lower()
            if content_type in self.SCANNABLE_CONTENT_TYPES:
                try:
                    # Scan first MAX_BODY_SCAN_BYTES of any text POST. Django buffers
                    # the full body for these content types anyway (request.POST / json),
                    # so this adds no extra memory cost. Slicing limits regex work, not I/O.
                    body = request.body[: self.MAX_BODY_SCAN_BYTES].decode("utf-8", errors="replace")
                    result = self._check_payload(body)
                    if result[0]:
                        return result
                    # Decode form bodies with unquote_plus (+ → space, %XX → char).
                    # jQuery $.ajax default POSTs are form-encoded, so attack payloads
                    # like %27+OR+1%3D1 must be decoded to ' OR 1=1 for regex matching.
                    if content_type == "application/x-www-form-urlencoded":
                        decoded_body = unquote_plus(body)
                        if decoded_body != body:
                            result = self._check_payload(decoded_body)
                            if result[0]:
                                return result
                except Exception:
                    pass

        return None, None
