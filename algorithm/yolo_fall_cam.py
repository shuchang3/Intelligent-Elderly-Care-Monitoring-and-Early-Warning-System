"""Legacy entrypoint removed: use app.py and algorithm.runtime.AlgorithmRuntime.
The runtime owns capture and sends every event through the durable Java outbox.
"""
from .runtime import AlgorithmRuntime
