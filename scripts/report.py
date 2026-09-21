"""Gera gráfico e tabela a partir dos JSON do k6."""

import json
from pathlib import Path

import matplotlib.pyplot as plt

plt.switch_backend("Agg")

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path("/artifacts") if Path("/artifacts").is_dir() else ROOT / "artifacts"


def main() -> None:
    scenarios = [
        "baseline-sql-one",
        "warm-one",
        "warm-two",
        "quota-one",
        "quota-two",
        "traces-down",
        "pool-pressure",
    ]
    rows = []
    for name in scenarios:
        data = json.loads((OUTPUT / f"load-{name}.json").read_text())
        metrics = data["metrics"]

        def count(metric: str, source: dict = metrics) -> int:
            return int(source.get(metric, {}).get("values", {}).get("count", 0))

        latency = metrics.get("success_latency", {}).get("values", {})
        rows.append(
            {
                "name": name,
                "rate": data["sentinel"]["offered_rate"],
                "offered": data["sentinel"]["offered_iterations"],
                "completed": count("iterations"),
                "dropped": count("dropped_iterations"),
                "success": count("accepted"),
                "quota": count("quota_rejected"),
                "service": count("service_rejected"),
                "p50": latency.get("med"),
                "p95": latency.get("p(95)"),
                "p99": latency.get("p(99)"),
            }
        )
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11})
    fig, axes = plt.subplots(1, 2, figsize=(13, 5), gridspec_kw={"width_ratios": [1, 1.2]})
    fig.patch.set_facecolor("#f3f6fa")
    fig.suptitle("API Sentinel | teste de carga", fontsize=21, fontweight="bold", x=0.07, ha="left")
    first = rows[:3]
    labels = [
        "SQL • 1 réplica\n5 req/s",
        "Cache • 1 réplica\n20 req/s",
        "Cache • 2 réplicas\n20 req/s",
    ]
    bars = axes[0].bar(
        labels, [row["p95"] for row in first], color=["#607d99", "#147d92", "#1ba887"], width=0.58
    )
    axes[0].set_ylabel("p95 apenas das respostas 200 (ms)")
    axes[0].bar_label(bars, fmt="%.1f ms", padding=5)
    axes[0].set_ylim(0, max(row["p95"] for row in first) * 1.35)
    quota = rows[3:5]
    names = ["1 réplica", "2 réplicas"]
    axes[1].barh(names, [r["success"] for r in quota], color="#1ba887", label="200 atendidas")
    axes[1].barh(
        names,
        [r["quota"] for r in quota],
        left=[r["success"] for r in quota],
        color="#d49d39",
        label="429 quota",
    )
    for index, row in enumerate(quota):
        axes[1].text(
            row["success"] / 2,
            index,
            str(row["success"]),
            ha="center",
            va="center",
            color="white",
            fontweight="bold",
        )
        axes[1].text(
            row["success"] + row["quota"] / 2,
            index,
            str(row["quota"]),
            ha="center",
            va="center",
            fontweight="bold",
        )
    axes[1].set_xlabel("Consultas em 20s oferecendo 60 req/s")
    axes[1].legend(loc="upper center", bbox_to_anchor=(0.5, -0.18), ncol=2, frameon=False)
    for axis in axes:
        axis.set_facecolor("#f3f6fa")
        axis.spines[["top", "right"]].set_visible(False)
    fig.text(
        0.07,
        0.035,
        "Fonte: artifacts/load-*.json • outras stacks ativas",
        fontsize=10,
        color="#48596c",
    )
    fig.tight_layout(rect=(0.03, 0.08, 0.98, 0.88))
    fig.savefig(OUTPUT / "performance-real.png", dpi=150)
    plt.close(fig)
    header = (
        "| Cenário | req/s | Oferta nominal | Completas | 200 | 429 | 503 | Drops | "
        "p50 (ms) | p95 (ms) | p99 (ms) |\n"
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n"
    )
    for row in rows:
        values = [
            row[key]
            for key in (
                "name",
                "rate",
                "offered",
                "completed",
                "success",
                "quota",
                "service",
                "dropped",
                "p50",
                "p95",
                "p99",
            )
        ]
        header += (
            "| "
            + " | ".join(
                f"{v:.2f}" if isinstance(v, float) else "—" if v is None else str(v) for v in values
            )
            + " |\n"
        )
    (OUTPUT / "load-table.md").write_text(header, encoding="utf-8")
    (OUTPUT / "load-summary.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
