"""Delivery solver implementations and the shared evaluator."""
"""Lightweight solver kernel used by online serving and OJ export."""

from .parser import Candidate, Problem, Solution, TaskKey, parse_problem

__all__ = ["Candidate", "Problem", "Solution", "TaskKey", "parse_problem"]
