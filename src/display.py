"""Clean live display for snipe progress - single screen update."""

import sys
import time
import threading
from datetime import datetime
from typing import List, Tuple
from src.models import RarityTier, CheckStatus, rarity_points


class CleanDisplay:
    """Clean single-screen live display using ANSI escape codes."""
    
    def __init__(self, total_candidates: int, target_hits: int, tiers: list, force_tui: bool = False):
        self.total = total_candidates
        self.target_hits = target_hits
        self.tiers = tiers
        
        # Stats
        self.checked = 0
        self.hits = 0
        self.taken = 0
        self.errors = 0
        self.rate_limited = 0
        self.start_time = time.time()
        self.hits_detail: List[Tuple[str, RarityTier, int, datetime]] = []
        
        # Display state
        self._first_render = True
        self._screen_lines = 0
        self._enabled = sys.stdout.isatty() or force_tui
        
        # Colors
        self.C = {
            'reset': '\033[0m',
            'bold': '\033[1m',
            'green': '\033[92m',
            'red': '\033[91m',
            'yellow': '\033[93m',
            'blue': '\033[94m',
            'cyan': '\033[96m',
            'magenta': '\033[95m',
            'gray': '\033[90m',
            'gold': '\033[33m',
            'white': '\033[97m',
        }
        
        self.tier_colors = {
            RarityTier.TOP: self.C['magenta'],
            RarityTier.OG: self.C['blue'],
            RarityTier.SEMI_OG: self.C['cyan'],
        }
        
        # Auto-refresh thread
        self._refresh_thread = None
        self._stop_refresh = threading.Event()
        
        if self._enabled:
            self._hide_cursor()
            self._clear_screen()
            self._start_refresh_thread()
    
    def _c(self, text: str, color: str) -> str:
        return f"{color}{text}{self.C['reset']}"
    
    def _hide_cursor(self):
        sys.stdout.write('\033[?25l')
        sys.stdout.flush()
    
    def _show_cursor(self):
        sys.stdout.write('\033[?25h')
        sys.stdout.flush()
    
    def _clear_screen(self):
        sys.stdout.write('\033[2J\033[H')
        sys.stdout.flush()
    
    def _move_up(self, lines: int):
        if lines > 0:
            sys.stdout.write(f'\033[{lines}A')
            sys.stdout.flush()
    
    def _clear_line(self):
        sys.stdout.write('\033[2K')
        sys.stdout.flush()
    
    def _save_cursor(self):
        sys.stdout.write('\033[s')
        sys.stdout.flush()
    
    def _restore_cursor(self):
        sys.stdout.write('\033[u')
        sys.stdout.flush()
    
    def update_checked(self, checked: int):
        self.checked = checked
        self._render()
    
    def update_stats(self, taken: int = None, errors: int = None, rate_limited: int = None):
        if taken is not None:
            self.taken = taken
        if errors is not None:
            self.errors = errors
        if rate_limited is not None:
            self.rate_limited = rate_limited
        self._render()
    
    def add_hit(self, username: str, tier: RarityTier, points: int):
        self.hits += 1
        self.hits_detail.append((username, tier, points, datetime.now()))
        self._render()
    
    def _render(self):
        if not self._enabled:
            # Non-TTY fallback: simple progress line (ASCII only)
            elapsed = time.time() - self.start_time
            speed = self.checked / elapsed if elapsed > 0 else 0
            pct = (self.checked / self.total * 100) if self.total > 0 else 0
            bar_width = 30
            filled = int(bar_width * pct / 100)
            bar = '#' * filled + '-' * (bar_width - filled)
            
            hits_str = f"HITS:{self.hits}"
            taken_str = f"TAKEN:{self.taken}"
            errors_str = f"ERR:{self.errors}"
            
            sys.stdout.write(f'\rProgress: [{bar}] {pct:5.1f}% ({self.checked}/{self.total})  {speed:5.1f}/s  HITS:{self.hits}  TAKEN:{self.taken}  ERR:{self.errors}')
            sys.stdout.flush()
            return
        
        if not self._first_render:
            # Move cursor up to overwrite previous frame
            self._move_up(self._screen_lines)
        else:
            self._first_render = False
        
        lines = []
        
        # Header
        elapsed = time.time() - self.start_time
        speed = self.checked / elapsed if elapsed > 0 else 0
        pct = (self.checked / self.total * 100) if self.total > 0 else 0
        
        # Progress bar
        bar_width = 50
        filled = int(bar_width * pct / 100)
        bar = '#' * filled + '-' * (bar_width - filled)
        
        lines.append(f"+{'-'*70}+")
        lines.append(f"| {self._c('MCUSER SNIPE', self.C['bold'] + self.C['cyan']):<60} |")
        lines.append(f"+{'-'*70}+")
        
        # Progress
        lines.append(f"| Progress: [{self._c(bar, self.C['cyan'])}] {pct:5.1f}% ({self.checked:,}/{self.total:,})  {speed:5.1f} names/s |")
        
        # Stats row - compute plain lengths for alignment
        hits_val = f"HITS: {self.hits}"
        taken_val = f"TAKEN: {self.taken:,}"
        errors_val = f"ERRORS: {self.errors}"
        rl_val = f"RATE LIMITED: {self.rate_limited}"
        target_val = f"TARGET: {self.target_hits}"
        
        hits_str = self._c(hits_val, self.C['green'] + self.C['bold'])
        taken_str = self._c(taken_val, self.C['red'])
        errors_str = self._c(errors_val, self.C['yellow'])
        rl_str = self._c(rl_val, self.C['magenta'])
        target_str = self._c(target_val, self.C['gold'])
        
        # Pad to visual lengths (without ANSI codes)
        lines.append(f"| {hits_str}  {taken_str}  {errors_str}  {rl_str}  {target_str} |")
        lines.append(f"+{'-'*70}+")
        
        # Top 5 Hits by Rarity
        lines.append(f"| {self._c('TOP 5 HITS BY RARITY', self.C['bold'] + self.C['magenta']):<68} |")
        
        if self.hits_detail:
            # Community rarity points first, then shorter names.
            sorted_hits = sorted(
                self.hits_detail,
                key=lambda x: (-rarity_points(x[0]), len(x[0])),
            )
            
            for i, (username, tier, points, ts) in enumerate(sorted_hits[:5], 1):
                tier_color = self.tier_colors.get(tier, self.C['green'])
                rank_color = self.C['gold'] if i <= 3 else self.C['white']
                time_str = ts.strftime('%H:%M:%S')
                
                # Truncate username to 14 chars for alignment
                display_name = username[:14]
                tier_display = tier.value.upper()[:7]  # TOP/OG/SEMI-OG fit in 7
                
                hit_line = (f"  {self._c(f'#{i}', rank_color + self.C['bold'])}  "
                           f"{self._c(display_name, tier_color + self.C['bold']):<14s}  "
                           f"{self._c(tier_display, tier_color):<7s}  "
                           f"{self._c(f'{points}', self.C['gray']):>5s}  "
                           f"{self._c(time_str, self.C['gray'])}")
                lines.append(f"|{hit_line:<68} |")
            
            # Fill remaining slots
            for i in range(len(sorted_hits[:5]), 5):
                lines.append(f"|  {self._c(f'#{i+1}', self.C['gray'])}  {'-'*14}  {'-'*7}  {'-'*5}  {'-'*8} |")
        else:
            for i in range(5):
                lines.append(f"|  {self._c(f'#{i+1}', self.C['gray'])}  {'-'*14}  {'-'*7}  {'-'*5}  {'-'*8} |")
        
        # Footer
        elapsed_str = self._format_time(elapsed)
        eta = (self.total - self.checked) / (self.checked / elapsed) if self.checked > 0 and elapsed > 0 else 0
        eta_str = self._format_time(eta) if eta > 0 else "--:--:--"
        
        lines.append(f"+{'-'*70}+")
        lines.append(f"| Elapsed: {elapsed_str}  ETA: {eta_str}  Tier order: {self._c('TOP', self.C['magenta'])} > {self._c('OG', self.C['blue'])} > {self._c('SEMI-OG', self.C['cyan'])}  |")
        lines.append(f"| Press Ctrl+C to pause gracefully (saves progress)                          |")
        lines.append(f"+{'-'*70}+")
        
        self._screen_lines = len(lines)
        
        # Output all lines
        output = '\n'.join(lines) + '\n'
        sys.stdout.write(output)
        sys.stdout.flush()
    
    def _format_time(self, seconds: float) -> str:
        if seconds < 60:
            return f"{seconds:.0f}s"
        elif seconds < 3600:
            return f"{seconds/60:.0f}m {seconds%60:.0f}s"
        else:
            h = int(seconds // 3600)
            m = int((seconds % 3600) // 60)
            return f"{h}h {m}m"
    
    def _start_refresh_thread(self):
        """Start background thread to refresh display every second."""
        self._stop_refresh.clear()
        self._refresh_thread = threading.Thread(target=self._refresh_loop, daemon=True)
        self._refresh_thread.start()
    
    def _refresh_loop(self):
        """Background loop to refresh display every second."""
        while not self._stop_refresh.wait(1.0):
            if self._enabled and not self._first_render:
                self._render()
    
    def finish(self, message: str = ""):
        # Stop refresh thread
        self._stop_refresh.set()
        if self._refresh_thread and self._refresh_thread.is_alive():
            self._refresh_thread.join(timeout=2.0)
        
        if self._enabled:
            self._show_cursor()
            # Move below the display
            sys.stdout.write(f'\n{message}\n')
            sys.stdout.flush()
        else:
            sys.stdout.write('\n')
            if message:
                sys.stdout.write(f'{message}\n')
            sys.stdout.flush()
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        self.finish()


class SimpleLineDisplay:
    """Simple line-based progress display using carriage return (default mode)."""
    
    def __init__(self, total_candidates: int, target_hits: int, tiers: list):
        self.total = total_candidates
        self.target_hits = target_hits
        self.tiers = tiers
        
        # Stats
        self.checked = 0
        self.hits = 0
        self.taken = 0
        self.errors = 0
        self.rate_limited = 0
        self.start_time = time.time()
        self.hits_detail: List[Tuple[str, RarityTier, int, datetime]] = []
        self._first_update = True
    
    def _c(self, text: str, color: str) -> str:
        if sys.stdout.isatty():
            colors = {
                'reset': '\033[0m',
                'bold': '\033[1m',
                'green': '\033[92m',
                'red': '\033[91m',
                'yellow': '\033[93m',
                'blue': '\033[94m',
                'cyan': '\033[96m',
                'magenta': '\033[95m',
                'gray': '\033[90m',
                'gold': '\033[33m',
            }
            return f"{colors.get(color, '')}{text}{colors['reset']}"
        return text
    
    def update_checked(self, checked: int):
        self.checked = checked
        self._render()
    
    def update_stats(self, taken: int = None, errors: int = None, rate_limited: int = None):
        if taken is not None:
            self.taken = taken
        if errors is not None:
            self.errors = errors
        if rate_limited is not None:
            self.rate_limited = rate_limited
        self._render()
    
    def add_hit(self, username: str, tier: RarityTier, score: int):
        self.hits += 1
        self.hits_detail.append((username, tier, score, datetime.now()))
        self._render()
    
    def _render(self):
        elapsed = time.time() - self.start_time
        speed = self.checked / elapsed if elapsed > 0 else 0
        pct = (self.checked / self.total * 100) if self.total > 0 else 0
        bar_width = 30
        filled = int(bar_width * pct / 100)
        bar = '#' * filled + '-' * (bar_width - filled)
        
        # Build stats string
        hits_str = f"HITS:{self.hits}"
        taken_str = f"TAKEN:{self.taken}"
        errors_str = f"ERR:{self.errors}"
        
        # Elapsed + ETA (remaining estimate from current speed)
        elapsed_str = self._format_time(elapsed)
        if speed > 0 and self.checked < self.total:
            eta_str = self._format_time((self.total - self.checked) / speed)
        else:
            eta_str = "--"
        
        # Build the progress line
        line = (f'\rProgress: [{bar}] {pct:5.1f}% ({self.checked}/{self.total})  {speed:5.1f}/s  '
                f'{hits_str}  {taken_str}  {errors_str}  ELAPSED:{elapsed_str}  ETA:{eta_str}')
        
        if self._first_update:
            self._first_update = False
        else:
            # Just overwrite the line
            pass
        
        sys.stdout.write(line)
        sys.stdout.flush()
    
    def _format_time(self, seconds: float) -> str:
        if seconds < 60:
            return f"{seconds:.0f}s"
        elif seconds < 3600:
            return f"{seconds/60:.0f}m {seconds%60:.0f}s"
        else:
            h = int(seconds // 3600)
            m = int((seconds % 3600) // 60)
            return f"{h}h {m}m"
    
    def finish(self, message: str = ""):
        sys.stdout.write('\n')
        if message:
            sys.stdout.write(f'{message}\n')
        sys.stdout.flush()
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        self.finish()


def format_hit_line(username: str, tier: RarityTier, hit_num: int, points: int, colors: dict, tier_colors: dict) -> str:
    """Format a hit line for display."""
    tier_color = tier_colors.get(tier, colors['green'])
    rank_color = colors['gold'] if hit_num <= 3 else colors.get('white', colors['reset'])
    score_str = f" ({points} pts)" if points > 0 else ""
    return (f"\n{colors['green']}{colors['bold']}[HIT #{hit_num}]{colors['reset']} "
            f"{tier_color}{colors['bold']}{username}{colors['reset']} "
            f"({tier_color}{tier.value.upper()}{colors['reset']})"
            f"{colors['gray']}{score_str}{colors['reset']} "
            f"{colors['green']}- VERIFIED AVAILABLE!{colors['reset']}")