"""Progress tracking utilities for depkeeper.

This module provides a comprehensive progress tracking interface using the Rich
library for displaying progress bars, spinners, and task completion status in
the terminal. It supports both determinate (known total) and indeterminate
(spinner) progress tracking with automatic color handling.

The module respects terminal capabilities and environment settings (NO_COLOR,
CI environments) through the console module integration, making it suitable
for both interactive CLI usage and automated CI/CD pipelines.

Examples
--------
Basic progress bar with context manager:

    >>> from depkeeper.utils.progress import ProgressTracker
    >>> with ProgressTracker() as tracker:
    ...     task = tracker.add_task("Checking packages", total=10)
    ...     for i in range(10):
    ...         # Do work
    ...         tracker.update(task, advance=1)

Indeterminate spinner for unknown duration:

    >>> from depkeeper.utils.progress import create_spinner
    >>> with create_spinner("Fetching from PyPI...") as spinner:
    ...     # Fetch data from API
    ...     response = requests.get("https://pypi.org/...")

Simple progress bar with convenience function:

    >>> from depkeeper.utils.progress import create_progress
    >>> with create_progress("Processing files", total=100) as (tracker, task):
    ...     for i in range(100):
    ...         process_file(i)
    ...         tracker.update(task, advance=1)

Multiple concurrent tasks:

    >>> with ProgressTracker() as tracker:
    ...     download_task = tracker.add_task("Downloading", total=1000)
    ...     process_task = tracker.add_task("Processing", total=500)
    ...
    ...     for i in range(1000):
    ...         download_data(i)
    ...         tracker.update(download_task, advance=1)
    ...
    ...         if i < 500:
    ...             process_data(i)
    ...             tracker.update(process_task, advance=1)

Named tasks for easier management:

    >>> with ProgressTracker() as tracker:
    ...     tracker.add_task("Main task", total=100, task_id="main")
    ...     tracker.add_task("Sub task", total=50, task_id="sub")
    ...
    ...     tracker.update("main", advance=10)
    ...     tracker.update("sub", advance=5)

Disable progress for non-interactive environments:

    >>> import os
    >>> disable = os.environ.get("CI") or not sys.stdout.isatty()
    >>> tracker = ProgressTracker(disable=disable)
    >>> with tracker:
    ...     task = tracker.add_task("Processing", total=100)
    ...     # Progress bar only shows in interactive terminals

Notes
-----
The progress tracker automatically:

- Respects NO_COLOR environment variable
- Detects CI environments and adjusts output
- Handles terminal resize events
- Cleans up properly on context manager exit
- Supports both transient (disappearing) and persistent progress bars

Progress bars use the Rich library's Progress class internally, providing:

- Smooth progress updates
- Time remaining estimation
- Percentage completion
- Custom spinners and styling
- Multi-line progress display

See Also
--------
depkeeper.utils.logger : Logging configuration
depkeeper.utils.console : Console output and styling
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Optional, Any, Union, Dict, Generator, Tuple

from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
    TimeRemainingColumn,
    TaskID,
)

from depkeeper.utils.logger import get_logger
from depkeeper.utils.console import get_raw_console

logger = get_logger("progress")


class ProgressTracker:
    """Track operations progress with rich progress bars.

    A comprehensive progress tracking class that provides an intuitive interface
    for displaying operation progress in the terminal. Supports both determinate
    progress (known total work) and indeterminate progress (spinners for unknown
    duration tasks).

    The tracker uses Rich's Progress class internally to provide smooth, visually
    appealing progress bars with automatic time estimation. It integrates with
    depkeeper's console module to respect color settings and terminal capabilities.

    Features:
        - Determinate progress bars with known totals
        - Indeterminate spinners for unknown duration
        - Multiple concurrent tasks in a single progress display
        - Named tasks for easier reference and updates
        - Context manager support for automatic cleanup
        - Transient mode (progress disappears when complete)
        - Persistent mode (progress remains visible after completion)
        - Time remaining estimation
        - Automatic terminal color detection

    Parameters
    ----------
    transient : bool, optional
        If True, the progress display disappears after completion, leaving a
        clean terminal. If False, the final progress state remains visible.
        Default is True. Use False when you want to keep a record of completed
        operations visible.
    show_time : bool, optional
        If True, displays estimated time remaining for tasks with known totals.
        If False, omits time estimation (useful for very fast operations).
        Default is True.
    disable : bool, optional
        If True, completely disables progress output. Useful for non-interactive
        environments, logging to files, or when quiet mode is needed. When
        disabled, all operations are no-ops. Default is False.

    Attributes
    ----------
    transient : bool
        Whether progress bar disappears when complete.
    show_time : bool
        Whether to show time remaining estimates.
    disable : bool
        Whether progress tracking is disabled.

    Examples
    --------
    Basic usage with context manager (recommended):

    >>> from depkeeper.utils.progress import ProgressTracker
    >>> with ProgressTracker() as tracker:
    ...     task = tracker.add_task("Processing", total=100)
    ...     for i in range(100):
    ...         # Perform work
    ...         tracker.update(task, advance=1)

    Manual start/stop (advanced usage):

    >>> tracker = ProgressTracker(transient=False)
    >>> tracker.start()
    >>> task = tracker.add_task("Working", total=50)
    >>> for i in range(50):
    ...     do_work()
    ...     tracker.update(task, advance=1)
    >>> tracker.stop()

    Persistent progress for record keeping:

    >>> with ProgressTracker(transient=False) as tracker:
    ...     task = tracker.add_task("Installation", total=10)
    ...     for pkg in packages:
    ...         install(pkg)
    ...         tracker.update(task, advance=1)
    ...     # Progress remains visible after completion

    Disable in non-interactive environments:

    >>> import sys
    >>> tracker = ProgressTracker(disable=not sys.stdout.isatty())
    >>> with tracker:
    ...     task = tracker.add_task("Processing", total=100)
    ...     # Progress only shown if stdout is a terminal

    Multiple concurrent tasks:

    >>> with ProgressTracker() as tracker:
    ...     download = tracker.add_task("Download", total=1000)
    ...     process = tracker.add_task("Process", total=500)
    ...     verify = tracker.add_task("Verify", total=100)
    ...
    ...     # Update tasks independently
    ...     tracker.update(download, advance=100)
    ...     tracker.update(process, advance=50)
    ...     tracker.update(verify, advance=10)

    Using named tasks:

    >>> with ProgressTracker() as tracker:
    ...     tracker.add_task("Main", total=100, task_id="main")
    ...     tracker.add_task("Sub", total=50, task_id="sub")
    ...
    ...     # Update by name instead of TaskID
    ...     tracker.update("main", advance=10)
    ...     tracker.update("sub", completed=25)

    Notes
    -----
    The ProgressTracker should be used with a context manager whenever possible
    to ensure proper cleanup of terminal resources. If using manual start/stop,
    always call stop() in a finally block to prevent terminal corruption.

    When disable=True, all methods become no-ops for performance. This is useful
    when running in:
        - CI/CD pipelines (no interactive terminal)
        - Logging to files (progress bars don't render well)
        - Background processes
        - Unit tests

    The tracker respects the NO_COLOR environment variable through integration
    with depkeeper.utils.console, automatically disabling color output when
    appropriate.

    See Also
    --------
    create_spinner : Convenience function for simple spinners
    create_progress : Convenience function for simple progress bars
    depkeeper.utils.console.get_raw_console : Access to Rich Console instance
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
        self._tasks: Dict[str, TaskID] = {}

    # Context Manager
    def __enter__(self) -> "ProgressTracker":
        """Enter context manager."""
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit context manager."""
        self.stop()

    # Start/Stop
    def start(self) -> None:
        """Start the progress tracker and begin displaying progress.

        Initializes the Rich Progress instance with configured columns and
        begins live rendering in the terminal. This must be called before
        adding any tasks (automatically called when using context manager).

        The progress display includes:
            - Spinner animation (for activity indication)
            - Task description text
            - Progress bar visualization
            - Percentage completion
            - Time remaining (if show_time=True)

        Returns
        -------
        None

        Examples
        --------
        Explicit start (manual control):

        >>> from depkeeper.utils.progress import ProgressTracker
        >>> tracker = ProgressTracker()
        >>> tracker.start()
        >>> task = tracker.add_task("Working", total=100)
        >>> # ... do work ...
        >>> tracker.stop()

        With context manager (automatic start):

        >>> with ProgressTracker() as tracker:
        ...     # tracker.start() called automatically
        ...     task = tracker.add_task("Working", total=100)

        Notes
        -----
        Calling start() multiple times is safe but logs a warning. The second
        and subsequent calls are ignored without error.

        If disable=True was passed to __init__, this method returns immediately
        without creating the Progress instance, making all subsequent operations
        no-ops.

        The method configures Rich Progress with these columns:
            1. SpinnerColumn: Animated spinner for visual feedback
            2. TextColumn: Task description display
            3. BarColumn: Visual progress bar
            4. TaskProgressColumn: Percentage text (e.g., "45%")
            5. TimeRemainingColumn: ETA (if show_time=True)

        See Also
        --------
        stop : Stop the progress tracker
        add_task : Add a task after starting
        """
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
        """Stop the progress tracker and clean up resources.

        Stops the live progress rendering and releases terminal resources.
        If transient=True, removes the progress display from the terminal.
        If transient=False, leaves the final progress state visible.

        Also clears all internal task tracking state. After calling stop(),
        the tracker can be restarted with start() for reuse.

        Returns
        -------
        None

        Examples
        --------
        Manual lifecycle management:

        >>> from depkeeper.utils.progress import ProgressTracker
        >>> tracker = ProgressTracker()
        >>> tracker.start()
        >>> task = tracker.add_task("Working", total=100)
        >>> # ... do work ...
        >>> tracker.stop()  # Clean up

        Automatic with context manager (recommended):

        >>> with ProgressTracker() as tracker:
        ...     task = tracker.add_task("Working", total=100)
        ...     # tracker.stop() called automatically on exit

        Reusing a tracker:

        >>> tracker = ProgressTracker()
        >>> tracker.start()
        >>> task1 = tracker.add_task("First", total=10)
        >>> # ... work ...
        >>> tracker.stop()
        >>>
        >>> # Later, reuse the same tracker
        >>> tracker.start()
        >>> task2 = tracker.add_task("Second", total=20)
        >>> # ... work ...
        >>> tracker.stop()

        Notes
        -----
        Calling stop() when the tracker hasn't been started is safe and does
        nothing. This allows unconditional cleanup in finally blocks.

        All internal task state is cleared on stop, including custom task_id
        mappings. Tasks must be re-added after a subsequent start().

        Always call stop() in interactive terminals to prevent:
            - Terminal corruption from incomplete ANSI sequences
            - Cursor positioning issues
            - Broken terminal state

        The context manager pattern handles this automatically and is
        strongly recommended.

        See Also
        --------
        start : Start the progress tracker
        __enter__ : Context manager entry (calls start)
        __exit__ : Context manager exit (calls stop)
        """
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

        return rich_task_id

    def update(
        self,
        task: Union[TaskID, str],
        advance: Optional[float] = None,
        completed: Optional[float] = None,
        description: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """
        Update task progress.

        Parameters
        ----------
        task : Union[TaskID, str]
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

    def remove_task(self, task: Union[TaskID, str]) -> None:
        """
        Remove a task from progress tracking.

        Parameters
        ----------
        task : Union[TaskID, str]
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


@contextmanager
def create_spinner(
    description: str, transient: bool = True
) -> Generator[ProgressTracker, None, None]:
    """Create a simple spinner for indeterminate tasks.

    A convenience context manager that creates a ProgressTracker with a single
    indeterminate task (spinner). Perfect for operations where the total work
    is unknown or irrelevant, such as network requests, waiting for external
    processes, or initialization tasks.

    The spinner provides visual feedback that work is in progress without
    showing a progress bar or percentage. This is ideal for operations that:
        - Have unknown duration
        - Don't have quantifiable progress
        - Complete quickly but need visual feedback
        - Are I/O bound (network, disk)

    Parameters
    ----------
    description : str
        Description text to display next to the spinner. Should be concise
        and descriptive of the ongoing operation. Examples: "Connecting to
        PyPI...", "Fetching package metadata", "Validating requirements".
    transient : bool, optional
        If True, the spinner disappears when the context exits, leaving no
        trace. If False, the final spinner state remains visible in the
        terminal. Default is True, which is recommended for clean output.

    Yields
    ------
    ProgressTracker
        A started ProgressTracker instance with one indeterminate task
        already added. You can add more tasks to this tracker if needed,
        though for simple cases the single spinner is sufficient.

    Examples
    --------
    Basic spinner for network operations:

    >>> from depkeeper.utils.progress import create_spinner
    >>> with create_spinner("Connecting to PyPI..."):
    ...     response = requests.get("https://pypi.org/pypi/requests/json")
    ...     data = response.json()

    Spinner for file operations:

    >>> with create_spinner("Reading requirements.txt"):
    ...     with open("requirements.txt") as f:
    ...         content = f.read()

    Persistent spinner (keeps final state visible):

    >>> with create_spinner("Initializing cache", transient=False):
    ...     setup_cache_directory()
    ...     load_cache_index()
    ...     # Spinner state remains after completion

    Nested spinners with additional tasks:

    >>> with create_spinner("Processing packages") as tracker:
    ...     fetch_metadata()
    ...     # Add another task to the same tracker
    ...     task = tracker.add_task("Validating", total=10)
    ...     for i in range(10):
    ...         validate_package(i)
    ...         tracker.update(task, advance=1)

    Exception handling (spinner stops gracefully):

    >>> try:
    ...     with create_spinner("Fetching data"):
    ...         risky_operation()
    ... except Exception as e:
    ...     print(f"Operation failed: {e}")
    ...     # Spinner cleans up automatically

    Notes
    -----
    The spinner animation runs continuously regardless of your code's actual
    activity. It's purely visual feedback for the user.

    Time remaining is never shown for spinners (disabled automatically) since
    the total work is unknown.

    The spinner respects NO_COLOR and CI environment settings through the
    console module integration.

    For operations with known totals, use create_progress() instead to show
    actual progress with a bar and percentage.

    The context manager ensures the spinner is properly stopped and cleaned
    up even if exceptions occur within the context.

    See Also
    --------
    create_progress : For tasks with known totals
    ProgressTracker : For advanced multi-task progress tracking
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
) -> Generator[Tuple[ProgressTracker, TaskID], None, None]:
    """Create a simple progress bar for determinate tasks.

    A convenience context manager that creates a ProgressTracker with a single
    determinate task (progress bar). Perfect for operations where you know the
    total amount of work upfront and want to show completion progress.

    The progress bar displays:
        - Task description
        - Visual progress bar
        - Percentage complete (e.g., "45%")
        - Estimated time remaining
        - Spinner animation (for visual activity)

    This is ideal for:
        - Processing a known number of files
        - Iterating over a fixed collection
        - Multi-step operations with known steps
        - Any task where total work is quantifiable

    Parameters
    ----------
    description : str
        Description text to display above/beside the progress bar. Should
        clearly indicate what operation is in progress. Examples:
        "Processing packages", "Downloading files", "Running tests".
    total : float
        Total units of work to complete. This is the denominator for
        percentage calculation. Can be:
        - Number of items (files, packages, records)
        - Bytes (for file downloads)
        - Arbitrary units (steps, iterations)
        Must be > 0. Use create_spinner() for unknown totals.
    transient : bool, optional
        If True, the progress bar disappears when complete, leaving a clean
        terminal. If False, the final 100% state remains visible as a record.
        Default is True. Use False when you want to show completion status.

    Yields
    ------
    tuple[ProgressTracker, TaskID]
        A tuple containing:
        - ProgressTracker: The tracker instance for updates
        - TaskID: The task identifier for the progress bar

        Unpack these to update progress:
        >>> with create_progress(...) as (tracker, task):
        ...     tracker.update(task, advance=1)

    Examples
    --------
    Basic progress bar for iteration:

    >>> from depkeeper.utils.progress import create_progress
    >>> files = ["file1.txt", "file2.txt", "file3.txt"]
    >>> with create_progress("Processing files", total=len(files)) as (tracker, task):
    ...     for file in files:
    ...         process_file(file)
    ...         tracker.update(task, advance=1)

    Progress with incremental updates:

    >>> with create_progress("Downloading", total=1000) as (tracker, task):
    ...     for chunk in download_chunks():
    ...         save_chunk(chunk)
    ...         tracker.update(task, advance=len(chunk))

    Setting absolute progress:

    >>> with create_progress("Processing", total=100) as (tracker, task):
    ...     for i in range(100):
    ...         do_work(i)
    ...         # Set absolute position instead of advancing
    ...         tracker.update(task, completed=i+1)

    Persistent progress (keep final state visible):

    >>> packages = ["requests", "click", "rich"]
    >>> with create_progress("Installing", total=len(packages), transient=False) as (t, task):
    ...     for pkg in packages:
    ...         install_package(pkg)
    ...         t.update(task, advance=1)
    ...     # Final "100% complete" remains visible

    Dynamic description updates:

    >>> with create_progress("Processing", total=10) as (tracker, task):
    ...     for i in range(10):
    ...         tracker.update(
    ...             task,
    ...             advance=1,
    ...             description=f"Processing item {i+1}/10"
    ...         )

    Exception handling (progress stops gracefully):

    >>> try:
    ...     with create_progress("Risky operation", total=100) as (tracker, task):
    ...         for i in range(100):
    ...             if i == 50:
    ...                 raise ValueError("Something went wrong")
    ...             tracker.update(task, advance=1)
    ... except ValueError:
    ...     print("Operation failed at 50%")
    ...     # Progress bar cleaned up automatically

    Notes
    -----
    The total parameter must be known upfront. If you don't know the total
    work until runtime, either:
        1. Calculate it before entering the context
        2. Use create_spinner() for indeterminate progress
        3. Use ProgressTracker directly for more control

    Progress updates must not exceed the total. If you advance past the total,
    the progress bar will show >100%, which looks incorrect.

    For very fast operations (<0.1 seconds), the progress bar may not be
    visible to users. Consider skipping progress tracking for trivial
    operations.

    The progress bar respects terminal capabilities:
        - NO_COLOR environment variable (disables colors)
        - CI environment detection (simplified output)
        - Terminal width (adapts bar width)

    Time remaining estimates improve as more work completes. Initial estimates
    may be inaccurate.

    See Also
    --------
    create_spinner : For tasks with unknown duration
    ProgressTracker : For advanced multi-task scenarios
    ProgressTracker.update : For all update options
    """
    tracker = ProgressTracker(transient=transient)
    tracker.start()
    task = tracker.add_task(description, total=total)

    try:
        yield tracker, task
    finally:
        tracker.stop()
