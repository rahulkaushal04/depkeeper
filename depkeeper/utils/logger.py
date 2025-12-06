from __future__ import annotations

import logging
from typing import Optional

# ============================================================================
# Logger Access (Primary API)
# ============================================================================


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """
    Retrieve a logger from the depkeeper hierarchy.

    Parameters
    ----------
    name:
        Optional submodule logger name: e.g. "resolver", "parser".

    Returns
    -------
    logging.Logger
    """
    if not name or name == "depkeeper":
        logger = logging.getLogger("depkeeper")
    else:
        logger = logging.getLogger(f"depkeeper.{name}")

    if not logger.handlers and (not logger.parent or not logger.parent.handlers):
        logger.addHandler(logging.NullHandler())

    return logger
