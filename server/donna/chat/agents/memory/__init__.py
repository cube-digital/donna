"""Memory primitives — Plan 13 §4.

§4.1 — ``extract.extract_session_memory`` runs after every turn and
emits scoped notes onto ``SessionMemory``.

§4.2 — ``autodream.run_autodream_for_workspace`` is the daily
consolidator that groups by ``(scope, scope_ref)`` and writes
``CortexEntity`` rows back through ``CortexService``.

§4.4 — ``shard.load_scoped_memory_for_session`` returns the curated
memory slice the system prompt should see for this turn.
"""
