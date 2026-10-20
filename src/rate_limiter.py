"""Token bucket rate limiter with persistence."""

from typing import Optional
import time
import threading
from pathlib import Path
import json


class TokenBucket:
    """Thread-safe token bucket rate limiter."""
    
    def __init__(
        self,
        rate: float = 3.0,        # tokens per second
        burst: int = 10,          # max bucket size
        state_file: str = "data/rate_limit_state.json"
    ):
        self.rate = rate
        self.burst = burst
        self.state_file = Path(state_file)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        
        self._tokens = burst
        self._last_update = time.monotonic()
        self._lock = threading.Lock()
        self._load_state()
    
    def _load_state(self):
        """Load persisted state from file."""
        if self.state_file.exists():
            try:
                with open(self.state_file) as f:
                    data = json.load(f)
                self._tokens = data.get("tokens", self.burst)
                # Account for time passed since last save
                elapsed = time.monotonic() - data.get("timestamp", time.monotonic())
                self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
            except Exception:
                pass  # Use defaults on error
    
    def _save_state(self):
        """Persist state to file."""
        try:
            with open(self.state_file, 'w') as f:
                json.dump({
                    "tokens": self._tokens,
                    "timestamp": time.monotonic(),
                }, f)
        except Exception:
            pass  # Best effort
    
    def take(self, tokens: int = 1, block: bool = True) -> bool:
        """
        Try to take tokens from the bucket.
        Returns True if successful, False if not enough tokens and block=False.
        """
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_update
            self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
            self._last_update = now
            
            if self._tokens >= tokens:
                self._tokens -= tokens
                self._save_state()
                return True
            
            if not block:
                return False
            
            # Calculate wait time
            needed = tokens - self._tokens
            wait_time = needed / self.rate
        
        # Wait outside lock
        time.sleep(wait_time)
        
        # Retry after wait
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_update
            self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
            self._last_update = now
            
            if self._tokens >= tokens:
                self._tokens -= tokens
                self._save_state()
                return True
            
            return False  # Should not happen with proper wait
    
    def wait_if_needed(self):
        """Block until at least one token is available."""
        self.take(1, block=True)
    
    @property
    def available_tokens(self) -> float:
        """Get current available tokens (approximate)."""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_update
            return min(self.burst, self._tokens + elapsed * self.rate)


class RateLimiter:
    """High-level rate limiter with 429 handling and exponential backoff."""
    
    def __init__(
        self,
        requests_per_second: float = 1.5,
        burst: int = 10,
        backoff_base: float = 2.0,
        max_backoff: float = 60.0,
    ):
        self.bucket = TokenBucket(rate=requests_per_second, burst=burst)
        self.backoff_base = backoff_base
        self.max_backoff = max_backoff
        self._current_backoff = 0.0
        self._lock = threading.Lock()
    
    def acquire(self):
        """Acquire permission to make a request."""
        self.bucket.wait_if_needed()
        
        # Apply any pending backoff
        backoff = 0.0
        with self._lock:
            if self._current_backoff > 0:
                backoff = self._current_backoff
                self._current_backoff = 0.0
        
        if backoff > 0:
            time.sleep(backoff)
    
    def handle_429(self, retry_after: Optional[float] = None):
        """Handle a 429 response with exponential backoff."""
        with self._lock:
            if retry_after and retry_after > 0:
                self._current_backoff = min(retry_after, self.max_backoff)
            else:
                self._current_backoff = min(
                    self._current_backoff * self.backoff_base if self._current_backoff else self.backoff_base,
                    self.max_backoff
                )
    
    def reset_backoff(self):
        """Reset backoff after successful request."""
        with self._lock:
            self._current_backoff = 0.0


# Global instance
_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter(
    requests_per_second: float = 1.5,
    burst: int = 10,
    backoff_base: float = 2.0,
) -> RateLimiter:
    """Get or create the global rate limiter instance."""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter(
            requests_per_second=requests_per_second,
            burst=burst,
            backoff_base=backoff_base,
        )
    return _rate_limiter