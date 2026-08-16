"""
experiments.py — runs the simulator across conditions and produces the plots.

Two headline experiments, both straight out of the prep doc's "design tradeoff
analysis" theme:

  A) Write amplification vs. over-provisioning, for each workload.
     Shows the capacity-vs-endurance tradeoff: more spare NAND -> lower WA.

  B) Wear distribution across blocks, with vs. without the effect of GC,
     for a hot/cold workload. Shows why wear leveling matters.

Run:  python experiments.py
"""

import matplotlib
matplotlib.use("Agg")  # headless
import matplotlib.pyplot as plt

from ftl import FTL
import workloads


def run_once(logical_pages, num_blocks, pages_per_block, trace):
    ftl = FTL(num_blocks, pages_per_block, logical_pages)
    for lpn in trace:
        ftl.write(lpn)
    return ftl


def experiment_wa_vs_op(outfile="wa_vs_op.png"):
    pages_per_block = 64
    logical_pages = 4000          # host-visible capacity (fixed)
    num_ops = 60000               # ~15x the logical size, so GC is well exercised
    op_ratios = [0.07, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50]

    patterns = {
        "sequential": lambda lp: workloads.sequential(num_ops, lp),
        "uniform":    lambda lp: workloads.uniform(num_ops, lp),
        "hot/cold 80-20": lambda lp: workloads.hot_cold(num_ops, lp),
    }

    results = {name: [] for name in patterns}
    for name, make_trace in patterns.items():
        for op in op_ratios:
            # Over-provisioning: physical capacity = logical / (1 - op).
            phys_pages = int(logical_pages / (1 - op))
            num_blocks = -(-phys_pages // pages_per_block) + 2  # ceil + a little slack
            ftl = run_once(logical_pages, num_blocks, pages_per_block, make_trace(logical_pages))
            results[name].append(ftl.dev.write_amplification())
            print(f"{name:16s} OP={op:4.0%}  WA={ftl.dev.write_amplification():.3f}")

    plt.figure(figsize=(8, 5))
    for name, ys in results.items():
        plt.plot([o * 100 for o in op_ratios], ys, marker="o", label=name)
    plt.xlabel("Over-provisioning (%)")
    plt.ylabel("Write amplification")
    plt.title("Write amplification vs. over-provisioning")
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(outfile, dpi=130)
    plt.close()
    print(f"saved {outfile}")


def experiment_wear_distribution(outfile="wear_distribution.png"):
    pages_per_block = 64
    logical_pages = 4000
    op = 0.15
    phys_pages = int(logical_pages / (1 - op))
    num_blocks = -(-phys_pages // pages_per_block) + 2
    num_ops = 80000

    ftl = run_once(logical_pages, num_blocks, pages_per_block,
                   workloads.hot_cold(num_ops, logical_pages))
    pe = ftl.dev.pe_cycles

    plt.figure(figsize=(8, 5))
    plt.bar(range(len(pe)), pe)
    plt.xlabel("Physical block index")
    plt.ylabel("Program/erase cycles")
    plt.title(f"Per-block wear under a hot/cold workload "
              f"(WA={ftl.dev.write_amplification():.2f})")
    plt.tight_layout()
    plt.savefig(outfile, dpi=130)
    plt.close()
    print(f"saved {outfile}")
    print(f"P/E spread: min={min(pe)} max={max(pe)} "
          f"ratio={max(pe)/max(1,min(pe)):.1f}x")


if __name__ == "__main__":
    print("=== Experiment A: write amplification vs. over-provisioning ===")
    experiment_wa_vs_op()
    print("\n=== Experiment B: wear distribution ===")
    experiment_wear_distribution()
