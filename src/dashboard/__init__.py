"""A statically generated home dashboard.

Every half hour cron runs ``python -m dashboard.generate``, which collects data
from each registered source, renders charts to inline SVG, and writes a single
self-contained ``index.html``.  ``python -m dashboard.serve`` serves that file.
"""

__version__ = "0.1.0"
