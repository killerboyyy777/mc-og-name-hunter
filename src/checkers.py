"""Availability checkers for Minecraft usernames - Async with multiple endpoints."""

import asyncio
import aiohttp
import random
import re
import time
from datetime import datetime
from typing import Optional, List
from dataclasses import dataclass
from contextlib import asynccontextmanager

from src.models import CheckResult, CheckStatus, RarityTier, UsernameCandidate
from src.rate_limiter import get_rate_limiter


# A legal Minecraft Java username: 3-16 chars of [A-Za-z0-9_].
# Anything else can never be registered; Mojang returns 404 for such
# strings, which must NOT be mistaken for "available".
_VALID_USERNAME = re.compile(r"^[A-Za-z0-9_]{3,16}$")


# Canonical public Mojang endpoint.
# This is the only username->UUID endpoint whose 200/404 semantics can be
# trusted for availability. In particular, the similarly named legacy
# "/user/profile/agent/minecraft/name/" endpoint may return 404 even for
# taken names, so it must never be used for availability decisions.
CANONICAL_PUBLIC_ENDPOINT = "https://api.mojang.com/users/profiles/minecraft/"

# Public Mojang API endpoints that may be used for final availability checks.
PUBLIC_API_ENDPOINTS = [
    CANONICAL_PUBLIC_ENDPOINT,
]

# Alternative third-party APIs (no auth, often higher rate limits).
# These only support simple alphanumeric usernames and are treated as hints:
# a third-party AVAILABLE result must be confirmed by the canonical endpoint.
THIRD_PARTY_ENDPOINTS = [
    "https://mc-api.bisai.dev/v1/name/",
    "https://api.minecraftapi.net/v3/profile/",
]

# Default endpoints to use. Third-party endpoints may speed up screening for
# pure alphabetic names, but final AVAILABLE decisions require canonical
# confirmation.
DEFAULT_ENDPOINTS = PUBLIC_API_ENDPOINTS + THIRD_PARTY_ENDPOINTS[:2]

# Provenance labels stored with results.
SOURCE_MOJANG_PRIMARY = "mojang-primary"
SOURCE_BISAI = "bisai"
SOURCE_MINECRAFT_API = "minecraftapi"
SOURCE_UNKNOWN = "unknown"


@dataclass
class EndpointStats:
    """Track endpoint health."""
    url: str
    requests: int = 0
    errors: int = 0
    rate_limited: int = 0
    last_used: float = 0
    last_error: Optional[str] = None
    
    @property
    def error_rate(self) -> float:
        return self.errors / max(self.requests, 1)
    
    @property
    def is_healthy(self) -> bool:
        return self.error_rate < 0.5 and self.rate_limited < 10


class AsyncPublicChecker:
    """Async public API checker with multiple endpoints, retry, and stats."""
    
    def __init__(
        self,
        endpoints: List[str] = None,
        rate_limiter=None,
        max_concurrent: int = 10,
        max_retries: int = 5,
        base_backoff: float = 1.0,
        max_backoff: float = 60.0,
    ):
        self.endpoints = endpoints or DEFAULT_ENDPOINTS
        self.rate_limiter = rate_limiter or get_rate_limiter()
        self.max_concurrent = max_concurrent
        self.max_retries = max_retries
        self.base_backoff = base_backoff
        self.max_backoff = max_backoff
        
        # Endpoint stats for health monitoring
        self.endpoint_stats = {url: EndpointStats(url) for url in self.endpoints}
        
        # Shared session
        self._session: Optional[aiohttp.ClientSession] = None
        self._semaphore: Optional[asyncio.Semaphore] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create shared aiohttp session."""
        if self._session is None or self._session.closed:
            # Longer timeout for Mojang API which can be slow
            timeout = aiohttp.ClientTimeout(total=30, connect=10)
            connector = aiohttp.TCPConnector(
                limit=self.max_concurrent,
                limit_per_host=self.max_concurrent,
                ttl_dns_cache=300,
            )
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
                headers={"User-Agent": "mcusersnipe/1.0"}
            )
        return self._session
    
    async def close(self):
        """Close the shared session."""
        if self._session and not self._session.closed:
            await self._session.close()
    
    def _select_endpoint(self, username: str = "") -> str:
        """Select best endpoint based on health and username format.
        
        Third-party APIs only support simple alphanumeric usernames.
        Mojang endpoints support all valid username formats.
        """
        # Third-party endpoints only support simple alphanumeric usernames
        can_use_third_party = username.isalpha()
        
        if can_use_third_party:
            # Can use any endpoint
            healthy = [s for s in self.endpoint_stats.values() if s.is_healthy]
        else:
            # Only use Mojang endpoints for usernames with special chars
            healthy = [s for s in self.endpoint_stats.values() 
                      if s.is_healthy and ("mojang.com" in s.url)]
        
        if not healthy:
            healthy = list(self.endpoint_stats.values())
        
        # Prefer least recently used among healthy endpoints
        return min(healthy, key=lambda s: (s.error_rate, s.last_used)).url
    
    def _record_request(self, endpoint: str, success: bool, rate_limited: bool = False):
        """Record request outcome for endpoint health tracking."""
        stats = self.endpoint_stats[endpoint]
        stats.requests += 1
        stats.last_used = time.time()
        if not success:
            stats.errors += 1
        if rate_limited:
            stats.rate_limited += 1
    
    def _endpoint_source(self, endpoint: str) -> str:
        """Return a stable provenance label for an endpoint."""
        if endpoint == CANONICAL_PUBLIC_ENDPOINT:
            return SOURCE_MOJANG_PRIMARY
        if "mc-api.bisai.dev" in endpoint:
            return SOURCE_BISAI
        if "api.minecraftapi.net" in endpoint:
            return SOURCE_MINECRAFT_API
        return SOURCE_UNKNOWN
    
    def _is_canonical(self, endpoint: str) -> bool:
        """Only the canonical endpoint may decide availability by itself."""
        return endpoint == CANONICAL_PUBLIC_ENDPOINT
    
    async def check(
        self,
        username: str,
        tier: RarityTier,
    ) -> CheckResult:
        """Check a single username with retry logic."""
        return await self._check_with_retry(username, tier)
    
    def _final_result(
        self,
        username: str,
        tier: RarityTier,
        status: CheckStatus,
        endpoint: str,
        verified: bool = False,
        error_message: Optional[str] = None,
    ) -> CheckResult:
        """Create a final result with endpoint provenance attached."""
        return CheckResult(
            username=username,
            status=status,
            tier=tier,
            checked_at=datetime.now(),
            verified=verified,
            error_message=error_message,
            source=self._endpoint_source(endpoint),
        )
    
    async def _check_with_retry(self, username: str, tier: RarityTier) -> CheckResult:
        """Check with exponential backoff retry. Never returns RATE_LIMITED - keeps retrying."""
        # Reject names that cannot be Minecraft usernames before spending a
        # request: Mojang 404s them, which would otherwise read as available.
        if not _VALID_USERNAME.match(username):
            return self._final_result(
                username,
                tier,
                CheckStatus.INVALID,
                SOURCE_UNKNOWN,
                error_message="invalid username format (3-16 of [A-Za-z0-9_])",
            )

        last_error = None
        max_total_retry_time = 300  # 5 minutes max total retry time
        start_time = time.time()
        
        for attempt in range(self.max_retries + 1):
            # Check if we've exceeded max total retry time
            if time.time() - start_time > max_total_retry_time:
                return self._final_result(
                    username,
                    tier,
                    CheckStatus.ERROR,
                    SOURCE_UNKNOWN,
                    error_message="Max total retry time exceeded",
                )
            
            # Rate limit per endpoint
            self.rate_limiter.acquire()
            
            endpoint = self._select_endpoint(username)
            url = f"{endpoint}{username}"
            
            try:
                session = await self._get_session()
                async with session.get(url) as response:
                    # Handle different API response formats
                    is_taken, is_available, error_msg = await self._parse_response(
                        response, endpoint, username
                    )
                    
                    if is_taken:
                        self.rate_limiter.reset_backoff()
                        self._record_request(endpoint, success=True)
                        return self._final_result(
                            username, tier, CheckStatus.TAKEN, endpoint
                        )
                    elif is_available:
                        if self._is_canonical(endpoint):
                            self.rate_limiter.reset_backoff()
                            self._record_request(endpoint, success=True)
                            return self._final_result(
                                username, tier, CheckStatus.AVAILABLE, endpoint
                            )
                        # Third-party mirrors can be stale or incompatible.
                        # Never trust a non-canonical AVAILABLE without
                        # canonical confirmation.
                        confirmed = await self._confirm_available_with_canonical(
                            username, tier
                        )
                        if confirmed.status == CheckStatus.AVAILABLE:
                            self._record_request(endpoint, success=True)
                        else:
                            self._record_request(endpoint, success=False)
                        return confirmed
                    elif response.status == 429:
                        # Rate limited - don't return, keep retrying with longer backoff
                        retry_after = response.headers.get("Retry-After")
                        retry_after = float(retry_after) if retry_after else None
                        self.rate_limiter.handle_429(retry_after)
                        self._record_request(endpoint, success=False, rate_limited=True)
                        
                        # Use longer backoff for rate limits
                        backoff = min(
                            self.base_backoff * (4 ** attempt) + random.uniform(1, 5),
                            self.max_backoff
                        )
                        await asyncio.sleep(backoff)
                        continue
                    elif response.status >= 500:
                        # Server error - retry
                        self._record_request(endpoint, success=False)
                        last_error = f"HTTP {response.status}"
                        if attempt < self.max_retries:
                            backoff = min(
                                self.base_backoff * (2 ** attempt) + random.uniform(0, 1),
                                self.max_backoff
                            )
                            await asyncio.sleep(backoff)
                            continue
                    elif error_msg and "unsupported" in error_msg:
                        # Endpoint doesn't support this username format, or it
                        # is not a trusted availability endpoint. Try another
                        # endpoint rather than trusting the response.
                        self._record_request(endpoint, success=False)
                        # Force endpoint rotation by temporarily marking as unhealthy
                        if endpoint in self.endpoint_stats:
                            self.endpoint_stats[endpoint].errors += 10
                        # Short backoff before trying next endpoint
                        await asyncio.sleep(0.5)
                        continue
                    else:
                        # Client error (4xx except 404/429) - don't retry
                        self._record_request(endpoint, success=False)
                        self.rate_limiter.reset_backoff()
                        return self._final_result(
                            username,
                            tier,
                            CheckStatus.ERROR,
                            endpoint,
                            error_message=error_msg or f"HTTP {response.status}",
                        )
                        
            except asyncio.TimeoutError:
                self._record_request(endpoint, success=False)
                last_error = "Timeout"
            except aiohttp.ClientError as e:
                self._record_request(endpoint, success=False)
                last_error = f"Client error: {e}"
            except Exception as e:
                self._record_request(endpoint, success=False)
                last_error = f"Unexpected error: {e}"
            
            # Exponential backoff before retry
            if attempt < self.max_retries:
                backoff = min(
                    self.base_backoff * (2 ** attempt) + random.uniform(0, 1),
                    self.max_backoff
                )
                await asyncio.sleep(backoff)
        
        # All retries exhausted
        self.rate_limiter.reset_backoff()
        return self._final_result(
            username,
            tier,
            CheckStatus.ERROR,
            SOURCE_UNKNOWN,
            error_message=last_error or "Max retries exceeded",
        )
    
    async def _confirm_available_with_canonical(
        self, username: str, tier: RarityTier
    ) -> CheckResult:
        """Confirm a mirror-reported AVAILABLE name against canonical Mojang.

        Third-party mirrors may be stale or incompatible, so a non-canonical
        AVAILABLE is only a screening hint. The canonical endpoint decides.
        """
        endpoint = CANONICAL_PUBLIC_ENDPOINT
        url = f"{endpoint}{username}"
        last_error: Optional[str] = None

        for attempt in range(3):
            self.rate_limiter.acquire()
            try:
                session = await self._get_session()
                async with session.get(url) as response:
                    is_taken, is_available, error_msg = await self._parse_response(
                        response, endpoint, username
                    )
                    if is_taken:
                        self.rate_limiter.reset_backoff()
                        self._record_request(endpoint, success=True)
                        return self._final_result(
                            username, tier, CheckStatus.TAKEN, endpoint
                        )
                    if is_available:
                        self.rate_limiter.reset_backoff()
                        self._record_request(endpoint, success=True)
                        return self._final_result(
                            username, tier, CheckStatus.AVAILABLE, endpoint
                        )
                    if response.status == 429:
                        retry_after = response.headers.get("Retry-After")
                        retry_after = float(retry_after) if retry_after else None
                        self.rate_limiter.handle_429(retry_after)
                        self._record_request(
                            endpoint, success=False, rate_limited=True
                        )
                    else:
                        self._record_request(endpoint, success=False)
                        last_error = error_msg or f"HTTP {response.status}"
            except asyncio.TimeoutError:
                self._record_request(endpoint, success=False)
                last_error = "Timeout"
            except aiohttp.ClientError as e:
                self._record_request(endpoint, success=False)
                last_error = f"Client error: {e}"
            except Exception as e:
                self._record_request(endpoint, success=False)
                last_error = f"Unexpected error: {e}"

            await asyncio.sleep(
                min(self.base_backoff * (2 ** attempt) + random.uniform(0, 1), 10.0)
            )

        # Do not trust the mirror if canonical confirmation is unavailable.
        self.rate_limiter.reset_backoff()
        return self._final_result(
            username,
            tier,
            CheckStatus.ERROR,
            endpoint,
            error_message=last_error or "Canonical confirmation unavailable",
        )

    async def _parse_response(self, response: aiohttp.ClientResponse, endpoint: str, username: str):
        """
        Parse response from different API endpoints.
        Returns: (is_taken: bool, is_available: bool, error_msg: Optional[str])
        """
        if "mc-api.bisai.dev" in endpoint:
            # Third-party API returns JSON - but only supports simple alphanumeric names
            # Skip for names with underscores, numbers, or special chars
            if not username.isalpha():
                return False, False, "bisai: unsupported username format"
            if response.status == 200:
                try:
                    data = await response.json()
                    if data.get("available") is True:
                        return False, True, None
                    elif data.get("available") is False:
                        return True, False, None
                    return False, False, f"Unexpected bisai response: {data}"
                except Exception:
                    return False, False, "Failed to parse bisai response"
            elif response.status == 404:
                return False, True, None
            return False, False, f"bisai HTTP {response.status}"
        
        elif endpoint == CANONICAL_PUBLIC_ENDPOINT:
            # Canonical Mojang API: 200 = taken, 404 = available.
            if response.status == 200:
                return True, False, None
            elif response.status == 404:
                return False, True, None
            return False, False, f"Mojang HTTP {response.status}"
        elif "mojang.com" in endpoint:
            # A non-canonical Mojang-shaped endpoint must not decide
            # availability: at least one legacy endpoint returns 404 for
            # taken names.
            return False, False, f"unsupported endpoint: {endpoint}"
        
        elif "minecraftapi.net" in endpoint:
            # minecraftapi.net: 200 = taken (returns profile), 404 = available
            if response.status == 200:
                return True, False, None
            elif response.status == 404:
                return False, True, None
            return False, False, f"minecraftapi.net HTTP {response.status}"
        
        else:
            # Default: assume 200 = taken, 404 = available
            if response.status == 200:
                return True, False, None
            elif response.status == 404:
                return False, True, None
            return False, False, f"HTTP {response.status}"
    
    async def check_batch(
        self,
        candidates: List[UsernameCandidate],
        progress_callback=None,
    ) -> List[CheckResult]:
        """Check multiple candidates concurrently with semaphore limiting."""
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.max_concurrent)
        
        async def check_one(candidate: UsernameCandidate) -> CheckResult:
            async with self._semaphore:
                result = await self._check_with_retry(candidate.username, candidate.tier)
                if progress_callback:
                    progress_callback(result)
                return result
        
        tasks = [check_one(c) for c in candidates]
        return await asyncio.gather(*tasks)
    
    def get_endpoint_stats(self) -> dict:
        """Get health stats for all endpoints."""
        return {
            url: {
                "requests": stats.requests,
                "errors": stats.errors,
                "rate_limited": stats.rate_limited,
                "error_rate": stats.error_rate,
                "healthy": stats.is_healthy,
            }
            for url, stats in self.endpoint_stats.items()
        }


class AsyncAuthChecker:
    """Async authenticated API checker."""
    
    BASE_URL = "https://api.minecraftservices.com/minecraft/profile/name/"
    
    def __init__(
        self,
        access_token: str,
        rate_limiter=None,
        max_concurrent: int = 5,
    ):
        self.access_token = access_token
        self.rate_limiter = rate_limiter or get_rate_limiter()
        self.max_concurrent = max_concurrent
        self._session: Optional[aiohttp.ClientSession] = None
        self._semaphore: Optional[asyncio.Semaphore] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=10, connect=5)
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "User-Agent": "mcusersnipe/1.0"
                }
            )
        return self._session
    
    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
    
    async def check(self, username: str, tier: RarityTier) -> CheckResult:
        """Check a single username via authenticated API."""
        self.rate_limiter.acquire()
        
        url = f"{self.BASE_URL}{username}/available"
        
        try:
            session = await self._get_session()
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    status = data.get("status", "").upper()
                    
                    self.rate_limiter.reset_backoff()
                    
                    if status == "AVAILABLE":
                        return CheckResult(
                            username=username,
                            status=CheckStatus.VERIFIED_AVAILABLE,
                            tier=tier,
                            checked_at=datetime.now(),
                            verified=True,
                        )
                    elif status == "DUPLICATE":
                        return CheckResult(
                            username=username,
                            status=CheckStatus.VERIFIED_TAKEN,
                            tier=tier,
                            checked_at=datetime.now(),
                            verified=True,
                        )
                    elif status == "NOT_ALLOWED":
                        return CheckResult(
                            username=username,
                            status=CheckStatus.BLOCKED,
                            tier=tier,
                            checked_at=datetime.now(),
                            verified=True,
                        )
                    else:
                        return CheckResult(
                            username=username,
                            status=CheckStatus.ERROR,
                            tier=tier,
                            checked_at=datetime.now(),
                            verified=True,
                            error_message=f"Unknown status: {status}",
                        )
                
                elif response.status == 401:
                    return CheckResult(
                        username=username,
                        status=CheckStatus.ERROR,
                        tier=tier,
                        checked_at=datetime.now(),
                        verified=False,
                        error_message="Invalid or expired auth token",
                    )
                elif response.status == 429:
                    retry_after = response.headers.get("Retry-After")
                    retry_after = float(retry_after) if retry_after else None
                    self.rate_limiter.handle_429(retry_after)
                    return CheckResult(
                        username=username,
                        status=CheckStatus.RATE_LIMITED,
                        tier=tier,
                        checked_at=datetime.now(),
                        verified=False,
                        error_message="Rate limited by auth API",
                    )
                else:
                    self.rate_limiter.reset_backoff()
                    return CheckResult(
                        username=username,
                        status=CheckStatus.ERROR,
                        tier=tier,
                        checked_at=datetime.now(),
                        verified=False,
                        error_message=f"HTTP {response.status}",
                    )
                    
        except asyncio.TimeoutError:
            return CheckResult(
                username=username,
                status=CheckStatus.ERROR,
                tier=tier,
                checked_at=datetime.now(),
                verified=False,
                error_message="Timeout",
            )
        except Exception as e:
            return CheckResult(
                username=username,
                status=CheckStatus.ERROR,
                tier=tier,
                checked_at=datetime.now(),
                verified=False,
                error_message=str(e),
            )
    
    async def check_batch(
        self,
        candidates: List[UsernameCandidate],
    ) -> List[CheckResult]:
        """Check multiple candidates concurrently."""
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.max_concurrent)
        
        async def check_one(candidate: UsernameCandidate) -> CheckResult:
            async with self._semaphore:
                return await self.check(candidate.username, candidate.tier)
        
        tasks = [check_one(c) for c in candidates]
        return await asyncio.gather(*tasks)


class AsyncCheckerManager:
    """Manages async public and auth checkers with verification flow."""
    
    def __init__(
        self,
        public_checker: AsyncPublicChecker,
        auth_checker: Optional[AsyncAuthChecker] = None,
        verify_on_hit: bool = True,
        verify_all_available: bool = False,
    ):
        self.public_checker = public_checker
        self.auth_checker = auth_checker
        self.verify_on_hit = verify_on_hit and auth_checker is not None
        self.verify_all_available = verify_all_available and auth_checker is not None
    
    async def check_batch(
        self,
        candidates: List[UsernameCandidate],
        progress_callback=None,
    ) -> List[CheckResult]:
        """Check batch with public API, then verify available ones with auth API."""
        # Phase 1: Public API batch check
        public_results = await self.public_checker.check_batch(
            candidates, progress_callback
        )
        
        # Phase 2: Verify with auth API if needed
        if self.verify_on_hit or self.verify_all_available:
            # Find candidates that need verification
            to_verify = []
            for i, (candidate, result) in enumerate(zip(candidates, public_results)):
                should_verify = (
                    (self.verify_on_hit and result.status == CheckStatus.AVAILABLE) or
                    (self.verify_all_available and result.status in (
                        CheckStatus.AVAILABLE, CheckStatus.TAKEN
                    ))
                )
                if should_verify:
                    to_verify.append((i, candidate))
            
            if to_verify:
                # Verify in batch
                verify_candidates = [c for _, c in to_verify]
                auth_results = await self.auth_checker.check_batch(verify_candidates)
                
                # Replace public results with verified results
                for (idx, _), auth_result in zip(to_verify, auth_results):
                    public_results[idx] = auth_result
        
        return public_results
    
    async def close(self):
        """Close all sessions."""
        await self.public_checker.close()
        if self.auth_checker:
            await self.auth_checker.close()


# Backward compatibility: synchronous wrapper
class PublicAPIChecker:
    """Sync wrapper for backward compatibility."""
    
    def __init__(self, rate_limiter=None):
        self.async_checker = AsyncPublicChecker(rate_limiter=rate_limiter)
        self.rate_limiter = rate_limiter or get_rate_limiter()
    
    def check(self, username: str, tier: RarityTier) -> CheckResult:
        return asyncio.run(self.async_checker.check(username, tier))


class AuthAPIChecker:
    """Sync wrapper for backward compatibility."""
    
    def __init__(self, access_token: str, rate_limiter=None):
        self.async_checker = AsyncAuthChecker(access_token, rate_limiter=rate_limiter)
        self.rate_limiter = rate_limiter or get_rate_limiter()
    
    def check(self, username: str, tier: RarityTier) -> CheckResult:
        return asyncio.run(self.async_checker.check(username, tier))


class CheckerManager:
    """Sync wrapper for backward compatibility."""
    
    def __init__(
        self,
        public_checker: PublicAPIChecker,
        auth_checker: Optional[AuthAPIChecker] = None,
        verify_on_hit: bool = True,
    ):
        self.async_manager = AsyncCheckerManager(
            public_checker.async_checker,
            auth_checker.async_checker if auth_checker else None,
            verify_on_hit,
        )
        self.public_checker = public_checker
        self.auth_checker = auth_checker
        self.verify_on_hit = verify_on_hit
    
    def check(self, candidate: UsernameCandidate) -> CheckResult:
        return asyncio.run(
            self.async_manager.check_batch([candidate])
        )[0]
    
    async def check_batch(
        self,
        candidates: List[UsernameCandidate],
        concurrency: int = 5,
    ) -> List[CheckResult]:
        return await self.async_manager.check_batch(candidates)


def get_microsoft_token(client_id: str, client_secret: str, refresh_token: str) -> Optional[str]:
    """Get Microsoft access token for Mojang API (placeholder)."""
    return None