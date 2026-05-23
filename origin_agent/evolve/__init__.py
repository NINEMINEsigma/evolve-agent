"""Code evolution subsystem — validate + trigger the fast-slow-fallback cycle.

This package handles the final step of the evolution cycle: validate that
evolved code (in the fork: namespace) passes syntax and import checks,
then signal the orchestrator to perform the hot swap.
"""