import time

print("========================")
print("Local Time", time.localtime())

clock_init = time.perf_counter_ns()
time.sleep(1)
min_ticks = max_ticks = 0
sleep_seconds = 0.1

for z in range(10):
    start_clock = time.perf_counter_ns()
    start_time = time.time()
    print("Start Clock", start_clock)
    print("Start Time", start_time)

    print("Sleeping for", sleep_seconds)
    time.sleep(sleep_seconds)
    stop_clock = time.perf_counter_ns()
    stop_time = time.time()
    clock_ticks = stop_clock - start_clock
    print("Clock", stop_clock, clock_ticks)
    print("Time", stop_time, stop_time - start_time)
    if min_ticks == 0:
        min_ticks = clock_ticks
    if clock_ticks < min_ticks:
        min_ticks = clock_ticks
    if clock_ticks > max_ticks:
        max_ticks = clock_ticks

print("TICKS", min_ticks, max_ticks, max_ticks - min_ticks)
print("TICKS/SEC", min_ticks / sleep_seconds, max_ticks / sleep_seconds)
