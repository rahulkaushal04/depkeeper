"""
Progress tracking utilities.

Provides progress bars, spinners, and nested progress tracking using rich library.
"""

from __future__ import annotations

from typing import Optional, Any
from contextlib import contextmanager

from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
    TimeRemainingColumn,
    TaskID,
)

from depkeeper.utils.console import get_raw_console
from depkeeper.utils.logger import get_logger

logger = get_logger("progress")


# ============================================================================
# Progress Tracker
# ============================================================================


class ProgressTracker:
    """
    Track operations progress with rich progress bars.

    Supports:
    - Determinate progress (known total)
    - Indeterminate progress (spinner for unknown total)
    - Nested progress (subtasks)
    - Context manager support

    Attributes
    ----------
    progress : Progress
        Rich Progress instance.
    transient : bool
        Whether progress bar disappears when complete.
    """

    def __init__(
        self,
        transient: bool = True,
        show_time: bool = True,
        disable: bool = False,
    ) -> None:
        """
        Initialize progress tracker.

        Parameters
        ----------
        transient : bool, optional
            If True, progress bar disappears when complete. Default is True.
        show_time : bool, optional
            If True, show estimated time remaining. Default is True.
        disable : bool, optional
            If True, disable progress output. Default is False.
        """
        self.transient = transient
        self.show_time = show_time
        self.disable = disable
        self._progress: Optional[Progress] = None
        self._tasks: dict[str, TaskID] = {}

    # -------------------------------------------------------------------------
    # Context Manager
    # -------------------------------------------------------------------------

    def __enter__(self) -> "ProgressTracker":
        """Enter context manager."""
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit context manager."""
        self.stop()

    # -------------------------------------------------------------------------
    # Start/Stop
    # -------------------------------------------------------------------------

    def start(self) -> None:
        """Start the progress tracker."""
        if self.disable:
            logger.debug("Progress tracking disabled")
            return

        if self._progress is not None:
            logger.warning("Progress tracker already started")
            return

        # Build columns
        columns = [
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
        ]

        if self.show_time:
            columns.append(TimeRemainingColumn())

        self._progress = Progress(
            *columns,
            console=get_raw_console(),
            transient=self.transient,
        )
        self._progress.start()
        logger.debug("Progress tracker started")

    def stop(self) -> None:
        """Stop the progress tracker."""
        if self._progress is not None:
            self._progress.stop()
            self._progress = None
            self._tasks.clear()
            logger.debug("Progress tracker stopped")

    # -------------------------------------------------------------------------
    # Task Management
    # -------------------------------------------------------------------------

    def add_task(
        self,
        description: str,
        total: Optional[float] = None,
        task_id: Optional[str] = None,
        **kwargs: Any,
    ) -> TaskID:
        """
        Add a new task to track.

        Parameters
        ----------
        description : str
            Task description to display.
        total : float, optional
            Total units of work. If None, shows spinner (indeterminate).
        task_id : str, optional
            Custom task identifier for later reference.
        **kwargs : Any
            Additional arguments passed to Progress.add_task.

        Returns
        -------
        TaskID
            Rich TaskID for this task.

        Examples
        --------
        >>> tracker = ProgressTracker()
        >>> tracker.start()
        >>> task = tracker.add_task("Processing files", total=100)
        >>> tracker.update(task, advance=1)
        """
        if self._progress is None:
            raise RuntimeError("Progress tracker not started. Call start() first.")

        rich_task_id = self._progress.add_task(description, total=total, **kwargs)

        if task_id:
            self._tasks[task_id] = rich_task_id

        logger.debug(f"Added task: {description} (total={total})")
        return rich_task_id

    def update(
        self,
        task: TaskID | str,
        advance: Optional[float] = None,
        completed: Optional[float] = None,
        description: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """
        Update task progress.

        Parameters
        ----------
        task : TaskID | str
            Rich TaskID or custom task_id string.
        advance : float, optional
            Amount to advance progress.
        completed : float, optional
            Set absolute completed amount.
        description : str, optional
            Update task description.
        **kwargs : Any
            Additional arguments passed to Progress.update.

        Examples
        --------
        >>> tracker.update(task, advance=1)
        >>> tracker.update(task, description="Processing file 2/10")
        """
        if self._progress is None:
            logger.debug("Progress tracker not started, skipping update")
            return

        # Resolve task ID
        if isinstance(task, str):
            if task not in self._tasks:
                logger.warning(f"Task '{task}' not found")
                return
            task = self._tasks[task]

        self._progress.update(
            task,
            advance=advance,
            completed=completed,
            description=description,
            **kwargs,
        )

    def get_task(self, task_id: str) -> Optional[TaskID]:
        """
        Get Rich TaskID by custom task_id.

        Parameters
        ----------
        task_id : str
            Custom task identifier.

        Returns
        -------
        TaskID, optional
            Rich TaskID if found, None otherwise.
        """
        return self._tasks.get(task_id)

    def remove_task(self, task: TaskID | str) -> None:
        """
        Remove a task from progress tracking.

        Parameters
        ----------
        task : TaskID | str
            Rich TaskID or custom task_id string.
        """
        if self._progress is None:
            return

        # Resolve task ID
        if isinstance(task, str):
            if task not in self._tasks:
                logger.warning(f"Task '{task}' not found")
                return
            rich_task_id = self._tasks.pop(task)
        else:
            rich_task_id = task
            # Remove from custom tasks if present
            for tid, rtid in list(self._tasks.items()):
                if rtid == rich_task_id:
                    del self._tasks[tid]
                    break

        self._progress.remove_task(rich_task_id)
        logger.debug(f"Removed task: {task}")


# ============================================================================
# Convenience Functions
# ============================================================================


@contextmanager
def create_spinner(description: str, transient: bool = True):
    """
    Create a simple spinner for indeterminate tasks.

    Parameters
    ----------
    description : str
        Description to display next to spinner.
    transient : bool, optional
        If True, spinner disappears when complete. Default is True.

    Yields
    ------
    ProgressTracker
        Progress tracker with a spinner task.

    Examples
    --------
    >>> with create_spinner("Fetching data...") as spinner:
    ...     # Do work
    ...     pass
    """
    tracker = ProgressTracker(transient=transient, show_time=False)
    tracker.start()
    tracker.add_task(description, total=None)

    try:
        yield tracker
    finally:
        tracker.stop()


@contextmanager
def create_progress(
    description: str,
    total: float,
    transient: bool = True,
):
    """
    Create a simple progress bar for determinate tasks.

    Parameters
    ----------
    description : str
        Description to display.
    total : float
        Total units of work.
    transient : bool, optional
        If True, progress bar disappears when complete. Default is True.

    Yields
    ------
    tuple[ProgressTracker, TaskID]
        Progress tracker and task ID.

    Examples
    --------
    >>> with create_progress("Processing", total=100) as (tracker, task):
    ...     for i in range(100):
    ...         # Do work
    ...         tracker.update(task, advance=1)
    """
    tracker = ProgressTracker(transient=transient)
    tracker.start()
    task = tracker.add_task(description, total=total)

    try:
        yield tracker, task
    finally:
        tracker.stop()
