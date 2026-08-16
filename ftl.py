"""
ftl.py — a page-mapped Flash Translation Layer.

The FTL presents a normal "overwrite-in-place" logical disk to the host while,
underneath, only ever writing to freshly-erased pages (Section 5.2 of the doc).

Design choices worth being able to defend in interview:

  * PAGE-mapped (one table entry per logical page). Simplest to reason about and
    it minimises write amplification. The real-world cost is RAM: the map is huge,
    which is why production drives use hybrid/block mapping — a genuine
    performance vs. controller-DRAM tradeoff you can raise unprompted.

  * TWO append-only write frontiers — one for host writes, one for GC copy-out.
    Keeping them separate is what lets us guarantee GC makes forward progress:
    host writes can never steal the block GC is copying into, and vice-versa.

  * GREEDY garbage collection: when the free-block pool runs low, reclaim the
    block with the FEWEST valid pages. That block gives back the most free space
    for the fewest copy-writes, i.e. the least write amplification.

Over-provisioning is modelled by making the physical device bigger than the
logical capacity exposed to the host. That spare space is what GC breathes with.
"""

from nand import NANDDevice, PageState


class DeviceFull(RuntimeError):
    """Raised only when GC genuinely cannot reclaim a block (near-zero OP)."""


class FTL:
    def __init__(self, num_blocks, pages_per_block, logical_pages,
                 gc_free_block_threshold=3):
        self.dev = NANDDevice(num_blocks, pages_per_block)
        self.ppb = pages_per_block
        self.logical_pages = logical_pages           # capacity the host sees
        self.gc_threshold = gc_free_block_threshold   # GC when free blocks <= this

        # Logical -> physical map. -1 means "never written".
        self.map = [-1] * logical_pages

        # Free-block pool (a stack) plus the two independent write frontiers.
        self.free_blocks = list(range(num_blocks))
        self.host_block = self.free_blocks.pop()
        self.host_offset = 0
        self.gc_block = self.free_blocks.pop()
        self.gc_offset = 0

    # ---- low-level page allocation on each frontier ------------------------
    def _pop_free_block(self):
        if not self.free_blocks:
            raise DeviceFull("no free block available — over-provisioning too low")
        return self.free_blocks.pop()

    def _alloc_host_page(self):
        """Next page on the host frontier; runs GC before rolling to a new block."""
        if self.host_offset >= self.ppb:
            if len(self.free_blocks) <= self.gc_threshold:
                self._garbage_collect()
            self.host_block = self._pop_free_block()
            self.host_offset = 0
        ppn = self.host_block * self.ppb + self.host_offset
        self.host_offset += 1
        return ppn

    def _alloc_gc_page(self):
        """Next page on the GC copy-out frontier. Never triggers GC (no recursion)."""
        if self.gc_offset >= self.ppb:
            self.gc_block = self._pop_free_block()
            self.gc_offset = 0
        ppn = self.gc_block * self.ppb + self.gc_offset
        self.gc_offset += 1
        return ppn

    # ---- host-facing write -------------------------------------------------
    def write(self, lpn):
        """Host writes logical page `lpn`."""
        # 1. Invalidate the previous physical location, if this LPN was live.
        old_ppn = self.map[lpn]
        if old_ppn != -1:
            self.dev.invalidate(old_ppn)

        # 2. Program a fresh page on the host frontier (may trigger GC).
        ppn = self._alloc_host_page()
        self.dev.program(ppn, lpn)
        self.map[lpn] = ppn
        self.dev.host_page_writes += 1

    # ---- garbage collection ------------------------------------------------
    def _select_victim(self):
        """Greedy: eligible block with the fewest valid pages (best reclaim ratio)."""
        excluded = set(self.free_blocks)
        excluded.add(self.host_block)
        excluded.add(self.gc_block)

        best_block, best_valid = None, None
        for b in range(self.dev.num_blocks):
            if b in excluded:
                continue
            v = self.dev.valid_count[b]
            if best_valid is None or v < best_valid:
                best_block, best_valid = b, v
        return best_block

    def _garbage_collect(self):
        """Reclaim victims until the free pool is rebuilt above the threshold.

        Looping (rather than one victim per call) is what keeps the pool from
        slowly draining under heavy random traffic: each reclaimed block nets
        (pages_per_block - valid_pages) of free space, so as long as some block
        is not 100% valid, the pool grows back to a safe buffer.
        """
        target = self.gc_threshold + 1
        while len(self.free_blocks) < target:
            victim = self._select_victim()
            if victim is None:
                break
            if self.dev.valid_count[victim] >= self.ppb:
                break  # every candidate is completely full — genuinely out of room

            base = victim * self.ppb
            for ppn in range(base, base + self.ppb):
                if self.dev.state[ppn] == PageState.VALID:
                    lpn = self.dev.lpn_of[ppn]
                    dst = self._alloc_gc_page()
                    self.dev.program(dst, lpn, is_gc_copy=True)
                    self.map[lpn] = dst

            self.dev.erase_block(victim)
            self.free_blocks.append(victim)
