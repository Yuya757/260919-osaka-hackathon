"""Deterministic domain rules.

Split out of the former ``enrichment.py``, which had grown to hold five
unrelated sets of rules under a name that described none of them.

This file stays empty on purpose. ``schemas`` imports :mod:`domain.normalize`,
and :mod:`domain.validation` imports ``schemas``; re-exporting the submodules
here would run that second import whenever the first one resolved the package,
and the cycle would be back. Import the module you need directly.

Layering, leaves first:

``normalize``    strings and URLs. No project imports.
``confidence``   §7.5 の信頼度。No project imports.
``validation``   §6.6 のステータス判定。Uses ``schemas`` and ``confidence``.
``ranking``      §6.8 の推薦スコア。Uses ``schemas`` and ``confidence``.
``dedup``        §6.7 の重複検出とマージ。Uses ``schemas`` and ``normalize``.
"""
