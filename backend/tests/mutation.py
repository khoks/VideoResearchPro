"""Mutation checks on the real code: run a production function with an edit.

A mutation case shows that a check refuses the code it guards against. It
runs the production function from its own source with one change, rather
than a stand-in written for the test, so the check is held to what the code
really does (T-5.2.30, T-5.2.32, T-5.2.34).
"""
from __future__ import annotations

import inspect
import textwrap


def mutant(monkeypatch, func, *edits: tuple[str, str]) -> None:
    """Run ``func`` from its own source with each ``(old, new)`` edit made,
    until the test ends: a change to the production code, not a stand-in.

    The edited source is compiled in a copy of the function's module namespace
    and only its code object is kept, so the function object stays the one
    FastAPI registered and every caller already holds, and it still reads the
    real module's globals (a fake publisher included). Every edit goes in
    one call: the source is read from the file at the function's first line."""
    source = textwrap.dedent(inspect.getsource(func))
    for old, new in edits:
        assert source.count(old) == 1, f"the mutation's anchor is not in {func.__name__} exactly once: {old!r}"
        source = source.replace(old, new)
    lines = source.splitlines(keepends=True)
    while lines[0].lstrip().startswith("@"):  # a route's decorator: registered once, already
        lines.pop(0)
    assert lines[0].startswith("def "), lines[0]
    namespace = dict(vars(inspect.getmodule(func)))
    exec(compile("".join(lines), inspect.getsourcefile(func), "exec", dont_inherit=True), namespace)
    monkeypatch.setattr(func, "__code__", namespace[func.__name__].__code__)
