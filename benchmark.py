import time
from orchestrator import TaskOrchestrator

EXAMPLES = [
    # Prompts chosen to require up-to-date information so that
    # the asynchronous search DAG provides a real advantage.
    "Research the impact of AI on renewable energy.",
    "Find recent developments in clean energy policy worldwide.",
    "Gather the latest statistics on global electric vehicle adoption."
]


def benchmark():
    rows = []
    for prompt in EXAMPLES:
        orch_tygent = TaskOrchestrator(silent=True, use_tygent=True)
        start = time.perf_counter()
        try:
            orch_tygent.orchestrate(prompt)
        except Exception:
            pass
        tygent_time = time.perf_counter() - start

        orch_thread = TaskOrchestrator(silent=True, use_tygent=False)
        start = time.perf_counter()
        try:
            orch_thread.orchestrate(prompt)
        except Exception:
            pass
        thread_time = time.perf_counter() - start

        rows.append((prompt, tygent_time, thread_time))

    print("Benchmark Results (seconds)")
    print(f"{'Prompt':<40} {'Tygent':>10} {'Threads':>10}")
    for prompt, t_time, thr_time in rows:
        label = (prompt[:37] + '...') if len(prompt) > 40 else prompt
        print(f"{label:<40} {t_time:>10.2f} {thr_time:>10.2f}")


if __name__ == '__main__':
    benchmark()
