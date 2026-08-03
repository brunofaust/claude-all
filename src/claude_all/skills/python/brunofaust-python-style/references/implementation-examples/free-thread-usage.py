# Free-Thread Feature Usage Examples

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor


def heavy_computation(data):
    # Simulate CPU work
    return data * 2

async def cpu_bound_task(data):
    # CPU-intensive work
    result = heavy_computation(data)
    return result

async def main_correct():
    # Use free-thread for CPU-bound tasks
    with ThreadPoolExecutor() as executor:
        result = await asyncio.to_thread(executor.submit, cpu_bound_task, 42)
    return result

## Incorrect Usage
async def io_bound_task():
    # I/O operation
    await asyncio.sleep(1)

async def main_incorrect():
    with ThreadPoolExecutor() as executor:
        # This is unnecessary and may introduce thread safety issues
        result = await asyncio.to_thread(executor.submit, io_bound_task)
    return result

## Thread Safety Example

class SharedResource:
    def __init__(self):
        self.lock = threading.Lock()
        self.value = 0

    def increment(self):
        with self.lock:
            self.value += 1

# Usage in free-thread context
def thread_worker(resource: SharedResource):
    resource.increment()

async def main_thread_safety():
    resource = SharedResource()
    with ThreadPoolExecutor() as executor:
        tasks = [executor.submit(thread_worker, resource) for _ in range(100)]
        await asyncio.gather(*tasks)
    print(resource.value)  # Should print 100
