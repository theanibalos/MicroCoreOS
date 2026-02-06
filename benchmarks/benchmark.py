# benchmark.py
# Script to compare token usage and ceremony between architectures.

import os

def count_tokens_approx(text):
    # Rough approximation: 1 token ~= 4 characters for code
    return len(text) // 4

def analyze_path(base_path):
    stats = {"files": 0, "lines": 0, "tokens": 0, "content": ""}
    
    for root, dirs, files in os.walk(base_path):
        for file in files:
            if file.endswith(".py") and not file.startswith("__"):
                stats["files"] += 1
                file_path = os.path.join(root, file)
                with open(file_path, 'r') as f:
                    content = f.read()
                    stats["content"] += content
                    stats["lines"] += len(content.splitlines())
                    stats["tokens"] += count_tokens_approx(content)
    
    return stats

def run_benchmark():
    clean_stats = analyze_path("clean_arch_fastapi")
    micro_stats = analyze_path("micro_core_os")
    
    print("\n" + "="*50)
    print("        MICRO-CORE-OS TOKEN BENCHMARK")
    print("="*50)
    print(f"{'Metric':<20} | {'Clean Arch':<12} | {'MicroCoreOS':<12} | {'Saving'}")
    print("-" * 65)
    
    metrics = [
        ("Files", "files", ""),
        ("Lines", "lines", ""),
        ("Tokens (Est)", "tokens", "tokens")
    ]
    
    for label, key, unit in metrics:
        v1 = clean_stats[key]
        v2 = micro_stats[key]
        saving = ((v1 - v2) / v1 * 100) if v1 > 0 else 0
        print(f"{label:<20} | {v1:<12} | {v2:<12} | {saving:.1f}%")
    
    print("-" * 65)
    print("\nDIAGNOSIS FOR AI DEVELOPMENT:")
    print(f"- Clean Arch forces AI to track {clean_stats['files']} contexts across directories.")
    print(f"- MicroCoreOS keeps AI in {micro_stats['files']} focused context.")
    print(f"- TOTAL CONTEXT REDUCTION: {((clean_stats['tokens'] - micro_stats['tokens']) / clean_stats['tokens'] * 100):.1f}%")
    print("="*50 + "\n")

if __name__ == "__main__":
    if not os.path.exists("clean_arch_fastapi"):
        print("Error: Run this script from the benchmarks/ directory.")
    else:
        run_benchmark()
