# tests/conftest.py
import pytest
import pytest_asyncio
import asyncio
from a2a.server.methods import cancel_pending_tasks

@pytest_asyncio.fixture(scope="function", autouse=True)
async def cleanup_background_tasks():
    """Clean up any background tasks after each test."""
    yield
    # Cancel all pending background tasks
    await cancel_pending_tasks()
    
    # Make sure we clean up any other asyncio tasks as well
    tasks = [t for t in asyncio.all_tasks() 
             if t is not asyncio.current_task() and not t.done()]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)