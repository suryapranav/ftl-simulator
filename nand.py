"""
nand.py — a minimal but honest model of a NAND flash device.

Models the one asymmetry that drives every clever thing an SSD controller does
(Section 5.1 of the prep doc):

    * You PROGRAM (write) at PAGE granularity.
    * You ERASE at BLOCK granularity (a block holds many pages).
    * A page cannot be re-programmed until its whole block is erased.

Everything above this layer (the FTL) exists to hide that asymmetry from the host.

Physical addressing is a single integer PPN (physical page number). A block is
just a contiguous run of PPNs: block_id = ppn // pages_per_block.
"""

from enum import Enum


class PageState(Enum):
    FREE = 0      # erased, ready to be programmed
    VALID = 1     # holds live data that the mapping table points at
    INVALID = 2   # holds stale data (host overwrote this LPN elsewhere)


class NANDDevice:
    def __init__(self, num_blocks, pages_per_block):
        self.num_blocks = num_blocks
        self.pages_per_block = pages_per_block
        self.num_pages = num_blocks * pages_per_block

        # Per-page physical state and the LPN currently stored there (-1 = none).
        self.state = [PageState.FREE] * self.num_pages
        self.lpn_of = [-1] * self.num_pages

        # Per-block bookkeeping.
        self.valid_count = [0] * num_blocks      # live pages, for GC victim choice
        self.pe_cycles = [0] * num_blocks        # program/erase count, for wear leveling

        # Global counters — the raw material for write amplification.
        self.host_page_writes = 0                # pages the HOST asked us to write
        self.nand_page_writes = 0                # pages actually PROGRAMMED to NAND
        self.gc_page_copies = 0                  # subset of the above caused by GC
        self.erase_count = 0                     # total block erases

    # ---- helpers -----------------------------------------------------------
    def block_of(self, ppn):
        return ppn // self.pages_per_block

    def is_free(self, ppn):
        return self.state[ppn] == PageState.FREE

    # ---- the two primitive NAND operations ---------------------------------
    def program(self, ppn, lpn, is_gc_copy=False):
        """Write one page. Enforces 'can only program a FREE page'."""
        if self.state[ppn] != PageState.FREE:
            raise RuntimeError(f"program to non-free page {ppn} — FTL bug")
        self.state[ppn] = PageState.VALID
        self.lpn_of[ppn] = lpn
        self.valid_count[self.block_of(ppn)] += 1

        self.nand_page_writes += 1
        if is_gc_copy:
            self.gc_page_copies += 1

    def invalidate(self, ppn):
        """Mark a live page stale (its LPN was overwritten elsewhere)."""
        if self.state[ppn] != PageState.VALID:
            return
        self.state[ppn] = PageState.INVALID
        self.valid_count[self.block_of(ppn)] -= 1

    def erase_block(self, block_id):
        """Erase a whole block: every page goes FREE, one P/E cycle is spent."""
        base = block_id * self.pages_per_block
        for ppn in range(base, base + self.pages_per_block):
            self.state[ppn] = PageState.FREE
            self.lpn_of[ppn] = -1
        self.valid_count[block_id] = 0
        self.pe_cycles[block_id] += 1
        self.erase_count += 1

    # ---- metrics -----------------------------------------------------------
    def write_amplification(self):
        if self.host_page_writes == 0:
            return 0.0
        return self.nand_page_writes / self.host_page_writes
