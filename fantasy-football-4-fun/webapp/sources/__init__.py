"""External, non-Sleeper data-source integrations used only by the webapp.

ffadp/ (cross-platform ADP comparison) and nflref/ (nflverse stat releases)
are both webapp-only, explicitly outside the parity-gated sleepermetrics
engine -- see CLAUDE.md. Grouped here rather than left as instance-root
siblings since nothing else in the project imports them.
"""
