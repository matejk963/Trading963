"""
Build MKTT dataflow DAGs using Hamilton.
Generates SVG/PNG visualizations of the data pipeline and runtime flow.

Run: cd sandbox/analysis/mktt_dataflow && python build_dag.py
"""
from pathlib import Path
from hamilton import driver
import transforms
import transforms_runtime

OUT = Path("output")
OUT.mkdir(parents=True, exist_ok=True)

# 1. Data pipeline DAG (what data flows where)
print("Rendering data pipeline DAG...")
dr1 = driver.Builder().with_modules(transforms).build()
dr1.display_all_functions(str(OUT / "mktt_dataflow.svg"))
dr1.display_all_functions(str(OUT / "mktt_dataflow.png"))
print(f"  Saved: mktt_dataflow.svg/png")

# 2. Runtime flow DAG (user actions → routes → data → responses)
print("Rendering runtime flow DAG...")
dr2 = driver.Builder().with_modules(transforms_runtime).build()
dr2.display_all_functions(str(OUT / "mktt_runtime_flow.svg"))
dr2.display_all_functions(str(OUT / "mktt_runtime_flow.png"))
print(f"  Saved: mktt_runtime_flow.svg/png")

print("\nDone! Open SVGs in browser for interactive viewing.")
