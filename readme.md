# SSD Flash Translation Layer (FTL) Simulator

A from-scratch simulator of the core logic inside an SSD controller: a page-mapped
Flash Translation Layer with garbage collection, wear-leveling accounting, and
write-amplification measurement. Built to explore the storage-system design
tradeoffs that a System Design role at a NAND/SSD company works with daily.

## What it models

NAND flash has one defining asymmetry: you **write at page granularity** but
**erase at block granularity**, and a page cannot be rewritten until its whole
block is erased. Every clever thing an SSD controller does follows from hiding
that asymmetry from the host. This simulator implements that hiding:

| Layer | File | Responsibility |
|-------|------|----------------|
| Physical device | `nand.py` | Page states (free/valid/invalid), program & erase primitives, per-block P/E counters, write counters |
| Translation layer | `ftl.py` | Logical→physical mapping, append-only write frontiers, greedy garbage collection |
| Workloads | `workloads.py` | Sequential, uniform-random, and hot/cold (80-20) host traces |
| Experiments | `experiments.py` | Sweeps and plots (write amplification vs. over-provisioning; per-block wear) |
| Sanity demo | `demo.py` | Tiny trace with a self-consistency check on the mapping table |

## Run it

```
python demo.py          # quick sanity check
python experiments.py   # produces wa_vs_op.png and wear_distribution.png
```

## Key design decisions

- **Page-mapped FTL.** One mapping entry per logical page. Simplest to reason
  about and it minimises write amplification. The real cost is RAM — the map is
  large — which is why production drives use hybrid/block mapping. That's a
  genuine *performance vs. controller-DRAM* tradeoff, not a detail.
- **Two independent write frontiers** (host + GC copy-out). Separating them is
  what guarantees garbage collection always has somewhere to copy live pages,
  so it can't deadlock against host writes.
- **Greedy victim selection.** GC reclaims the block with the fewest valid
  pages, because that returns the most free space for the fewest copy-writes —
  directly minimising write amplification.
- **Over-provisioning is modelled physically:** physical capacity = logical /
  (1 − OP). The spare capacity is the room GC needs to work.

## Results

**Write amplification vs. over-provisioning** (`wa_vs_op.png`)

| Workload | WA @ 7% OP | WA @ 20% OP | WA @ 50% OP |
|----------|-----------:|------------:|------------:|
| Sequential | 1.00 | 1.00 | 1.00 |
| Uniform random | 6.34 | 2.43 | 1.21 |
| Hot/cold 80-20 | 3.23 | 1.94 | 1.21 |

Three things worth noticing, each of which is an interview talking point:

1. **Sequential writes give WA = 1.0.** Whole blocks turn stale together, so GC
   always finds fully-invalid victims and never copies anything.
2. **Less over-provisioning → higher WA.** Squeezing the spare space forces GC
   to reclaim blocks that still hold live data, inflating writes. This is the
   capacity-vs-endurance tradeoff behind why enterprise SSDs reserve more NAND.
3. **Hot/cold beats uniform.** Counterintuitive but correct: access locality
   makes hot blocks fill with stale pages quickly (cheap to reclaim), while
   uniform traffic leaves every block a half-valid mess (expensive to reclaim).

**Per-block wear** (`wear_distribution.png`) under a hot/cold workload shows a
large spread in program/erase cycles across blocks — the direct motivation for
wear leveling, which spreads writes so no single block wears out early.
