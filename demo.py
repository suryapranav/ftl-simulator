"""
demo.py — a tiny, eyeball-able sanity check.

Run:  python demo.py

Writes a small trace and prints what the FTL did, so you can verify the core
behaviour by hand before trusting the big experiments.
"""

from ftl import FTL
import workloads

# Small device sized for a moderate ~15% over-provisioning:
# 22 blocks x 4 pages = 88 physical pages, 75 logical pages.
ftl = FTL(num_blocks=22, pages_per_block=4, logical_pages=75, gc_free_block_threshold=2)

# Uniform-random overwrites mix valid and stale pages inside every block, so
# greedy GC is forced to copy live pages out -> write amplification rises above
# 1.0 and the copy path is exercised.
for lpn in workloads.uniform(2000, 75, seed=1):
    ftl.write(lpn)

d = ftl.dev
print(f"host page writes : {d.host_page_writes}")
print(f"NAND page writes : {d.nand_page_writes}  (host + GC copies)")
print(f"GC copy writes   : {d.gc_page_copies}")
print(f"block erases      : {d.erase_count}")
print(f"write amplification: {d.write_amplification():.3f}")
print(f"per-block P/E cycles: {d.pe_cycles}")

# Correctness check: every live logical page must map to a VALID physical page
# holding that same LPN. If this passes, the mapping table is self-consistent.
ok = all(
    ftl.map[lpn] == -1 or d.lpn_of[ftl.map[lpn]] == lpn
    for lpn in range(ftl.logical_pages)
)
print("mapping self-consistent:", ok)
