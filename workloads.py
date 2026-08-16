"""
workloads.py — synthetic host write traces.

Write amplification is entirely workload-dependent, so the whole point of the
simulator is to feed it different patterns and watch WA move.

  * sequential   : LPNs 0,1,2,... — the easy case. Whole blocks go stale together,
                   so GC finds near-empty victims and WA stays close to 1.0.
  * uniform      : every LPN equally likely — valid and invalid pages get mixed
                   inside every block, so GC has to copy a lot. WA rises.
  * hot_cold     : a small "hot" fraction of LPNs takes most of the writes (e.g.
                   20% of the space sees 80% of writes). This is the realistic
                   case and the one that stresses GC hardest.
"""

import random


def sequential(num_ops, logical_pages):
    for i in range(num_ops):
        yield i % logical_pages


def uniform(num_ops, logical_pages, seed=0):
    rng = random.Random(seed)
    for _ in range(num_ops):
        yield rng.randrange(logical_pages)


def hot_cold(num_ops, logical_pages, hot_fraction=0.2, hot_prob=0.8, seed=0):
    """`hot_prob` of writes hit the first `hot_fraction` of the address space."""
    rng = random.Random(seed)
    hot_cut = max(1, int(logical_pages * hot_fraction))
    for _ in range(num_ops):
        if rng.random() < hot_prob:
            yield rng.randrange(0, hot_cut)
        else:
            yield rng.randrange(hot_cut, logical_pages)
