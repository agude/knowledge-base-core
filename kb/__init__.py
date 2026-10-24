"""The knowledge base runtime: the Python implementation of the executables.

Standard library only. Executables in python/ start a module in
kb.commands through kb._bootstrap; see kb/executables.py.

This file must stay importable by old interpreters (see kb/_bootstrap.py).
"""
