import os
import sys

os.environ.setdefault("ASK_URL", "http://x"); os.environ.setdefault("ASK_WORKER_TOKEN", "t")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "cloud", "pod"))
import supervise as sv  # noqa: E402

HZ = sv.TICK_HZ


def series(cpu_per_s, bytes_per_s, n=8, step=15):
    return [(i * step, int(i * step * cpu_per_s * HZ), int(i * step * bytes_per_s)) for i in range(n)]


def test_working_edge_is_not_stuck():
    s = series(0.4, 150_000)
    assert not sv.stuck(s, s[-1][0])


def test_no_cpu_while_stream_receives_is_stuck():
    s = series(0.0, 150_000)
    assert sv.stuck(s, s[-1][0])


def test_quiet_stream_is_not_the_edges_fault():
    s = series(0.0, 0)                 # camera dark / path not ready: nothing to analyse, never killed
    assert not sv.stuck(s, s[-1][0])


def test_needs_the_full_window():
    s = series(0.0, 150_000, n=4)      # 45 s of samples < 90 s
    assert not sv.stuck(s, s[-1][0])


def test_proc_stat_reads_self():
    st, ticks = sv.proc_stat(os.getpid())
    assert st in "RS" and ticks >= 0
