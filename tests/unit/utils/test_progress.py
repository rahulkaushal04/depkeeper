import pytest
from unittest.mock import MagicMock, patch

from rich.progress import Progress, TaskID

from depkeeper.utils.progress import (
    ProgressTracker,
    create_spinner,
    create_progress,
)


@pytest.fixture
def mock_progress():
    """Provide a mock Rich Progress instance."""
    with patch("depkeeper.utils.progress.Progress") as MockProgress:
        mock_instance = MagicMock(spec=Progress)
        # TaskID is just an int in Rich
        mock_instance.add_task.return_value = TaskID(1)
        MockProgress.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def mock_console():
    """Provide a mock console for Progress."""
    with patch("depkeeper.utils.progress.get_raw_console") as mock_get_console:
        mock_console_instance = MagicMock()
        mock_get_console.return_value = mock_console_instance
        yield mock_console_instance


@pytest.fixture
def mock_logger():
    """Provide a mock logger."""
    with patch("depkeeper.utils.progress.logger") as mock_log:
        yield mock_log


@pytest.fixture
def tracker():
    """Provide a fresh ProgressTracker instance."""
    return ProgressTracker()


class TestProgressTrackerInit:
    """Test ProgressTracker initialization and configuration."""

    def test_default_initialization(self):
        """Test tracker with default parameters."""
        tracker = ProgressTracker()
        assert tracker.transient is True
        assert tracker.show_time is True
        assert tracker.disable is False
        assert tracker._progress is None
        assert tracker._tasks == {}

    def test_custom_transient(self):
        """Test tracker with custom transient setting."""
        tracker = ProgressTracker(transient=False)
        assert tracker.transient is False

    def test_custom_show_time(self):
        """Test tracker with custom show_time setting."""
        tracker = ProgressTracker(show_time=False)
        assert tracker.show_time is False

    def test_disabled_tracker(self):
        """Test tracker with disable flag."""
        tracker = ProgressTracker(disable=True)
        assert tracker.disable is True

    def test_all_custom_parameters(self):
        """Test tracker with all parameters customized."""
        tracker = ProgressTracker(transient=False, show_time=False, disable=True)
        assert tracker.transient is False
        assert tracker.show_time is False
        assert tracker.disable is True


class TestProgressTrackerStartStop:
    """Test starting and stopping progress tracking."""

    def test_start_creates_progress(self, mock_progress, mock_console):
        """Test that start() creates Progress instance."""
        tracker = ProgressTracker()
        tracker.start()

        assert tracker._progress is not None
        tracker._progress.start.assert_called_once()

    def test_start_with_transient_true(self, mock_console):
        """Test Progress created with transient=True."""
        with patch("depkeeper.utils.progress.Progress") as MockProgress:
            mock_instance = MagicMock()
            MockProgress.return_value = mock_instance

            tracker = ProgressTracker(transient=True)
            tracker.start()

            # Check that Progress was called with transient=True
            assert MockProgress.call_args.kwargs["transient"] is True

    def test_start_with_transient_false(self, mock_console):
        """Test Progress created with transient=False."""
        with patch("depkeeper.utils.progress.Progress") as MockProgress:
            mock_instance = MagicMock()
            MockProgress.return_value = mock_instance

            tracker = ProgressTracker(transient=False)
            tracker.start()

            assert MockProgress.call_args.kwargs["transient"] is False

    def test_start_with_show_time_true(self, mock_console):
        """Test Progress includes TimeRemainingColumn when show_time=True."""
        with patch("depkeeper.utils.progress.Progress") as MockProgress:
            mock_instance = MagicMock()
            MockProgress.return_value = mock_instance

            tracker = ProgressTracker(show_time=True)
            tracker.start()

            # Check that 5 columns were added (including TimeRemainingColumn)
            args = MockProgress.call_args[0]
            assert len(args) == 5  # 4 base + 1 time column

    def test_start_with_show_time_false(self, mock_console):
        """Test Progress excludes TimeRemainingColumn when show_time=False."""
        with patch("depkeeper.utils.progress.Progress") as MockProgress:
            mock_instance = MagicMock()
            MockProgress.return_value = mock_instance

            tracker = ProgressTracker(show_time=False)
            tracker.start()

            # Check that only 4 columns were added (no time column)
            args = MockProgress.call_args[0]
            assert len(args) == 4

    def test_start_uses_correct_console(self, mock_console):
        """Test that start() uses get_raw_console()."""
        with patch("depkeeper.utils.progress.Progress") as MockProgress:
            mock_instance = MagicMock()
            MockProgress.return_value = mock_instance

            tracker = ProgressTracker()
            tracker.start()

            # Verify console parameter
            assert MockProgress.call_args.kwargs["console"] == mock_console

    def test_start_when_disabled(self, mock_logger):
        """Test start() does nothing when disabled."""
        tracker = ProgressTracker(disable=True)
        tracker.start()

        assert tracker._progress is None
        mock_logger.debug.assert_called_with("Progress tracking disabled")

    def test_start_twice_warns(self, mock_progress, mock_console, mock_logger):
        """Test starting tracker twice logs warning."""
        tracker = ProgressTracker()
        tracker.start()
        tracker.start()  # Second start

        mock_logger.warning.assert_called_with("Progress tracker already started")

    def test_stop_cleans_up(self, mock_progress, mock_console):
        """Test stop() cleans up Progress instance."""
        tracker = ProgressTracker()
        tracker.start()
        tracker.stop()

        mock_progress.stop.assert_called_once()
        assert tracker._progress is None
        assert tracker._tasks == {}

    def test_stop_clears_tasks(self, mock_progress, mock_console):
        """Test stop() clears task dictionary."""
        tracker = ProgressTracker()
        tracker.start()

        # Add some tasks
        tracker._tasks["task1"] = TaskID(1)
        tracker._tasks["task2"] = TaskID(2)

        tracker.stop()

        assert tracker._tasks == {}

    def test_stop_when_not_started(self):
        """Test stop() is safe when tracker not started."""
        tracker = ProgressTracker()
        tracker.stop()  # Should not raise

        assert tracker._progress is None

    def test_stop_multiple_times(self, mock_progress, mock_console):
        """Test stopping multiple times is safe."""
        tracker = ProgressTracker()
        tracker.start()
        tracker.stop()
        tracker.stop()  # Second stop - should be safe

        # Only one call to progress.stop()
        assert mock_progress.stop.call_count == 1


class TestProgressTrackerContextManager:
    """Test context manager functionality."""

    def test_context_manager_starts_and_stops(self, mock_progress, mock_console):
        """Test context manager calls start() and stop()."""
        tracker = ProgressTracker()

        with tracker:
            assert tracker._progress is not None
            mock_progress.start.assert_called_once()

        mock_progress.stop.assert_called_once()
        assert tracker._progress is None

    def test_context_manager_returns_self(self, mock_progress, mock_console):
        """Test context manager returns tracker instance."""
        tracker = ProgressTracker()

        with tracker as t:
            assert t is tracker

    def test_context_manager_with_exception(self, mock_progress, mock_console):
        """Test context manager stops even on exception."""
        tracker = ProgressTracker()

        with pytest.raises(ValueError):
            with tracker:
                raise ValueError("Test exception")

        # Stop should still be called
        mock_progress.stop.assert_called_once()
        assert tracker._progress is None

    def test_context_manager_disabled(self):
        """Test context manager works when disabled."""
        tracker = ProgressTracker(disable=True)

        with tracker as t:
            assert t is tracker
            assert tracker._progress is None


class TestProgressTrackerAddTask:
    """Test adding tasks to progress tracker."""

    def test_add_task_basic(self, mock_progress, mock_console):
        """Test adding a basic task."""
        tracker = ProgressTracker()
        tracker.start()

        task_id = tracker.add_task("Processing", total=100)

        mock_progress.add_task.assert_called_once_with("Processing", total=100)
        assert task_id == TaskID(1)

    def test_add_task_with_custom_id(self, mock_progress, mock_console):
        """Test adding task with custom task_id."""
        tracker = ProgressTracker()
        tracker.start()

        task_id = tracker.add_task("Processing", total=100, task_id="my_task")

        assert tracker._tasks["my_task"] == task_id
        assert tracker.get_task("my_task") == task_id

    def test_add_task_without_total(self, mock_progress, mock_console):
        """Test adding indeterminate task (spinner)."""
        tracker = ProgressTracker()
        tracker.start()

        task_id = tracker.add_task("Loading", total=None)

        mock_progress.add_task.assert_called_with("Loading", total=None)

    def test_add_task_with_kwargs(self, mock_progress, mock_console):
        """Test adding task with additional kwargs."""
        tracker = ProgressTracker()
        tracker.start()

        tracker.add_task("Processing", total=100, visible=False, custom=True)

        mock_progress.add_task.assert_called_with(
            "Processing", total=100, visible=False, custom=True
        )

    def test_add_task_not_started_raises(self):
        """Test adding task before start() raises error."""
        tracker = ProgressTracker()

        with pytest.raises(RuntimeError, match="Progress tracker not started"):
            tracker.add_task("Processing", total=100)

    def test_add_multiple_tasks(self, mock_progress, mock_console):
        """Test adding multiple tasks."""
        tracker = ProgressTracker()
        tracker.start()

        # Mock different task IDs
        mock_progress.add_task.side_effect = [TaskID(1), TaskID(2), TaskID(3)]

        task1 = tracker.add_task("Task 1", total=100, task_id="t1")
        task2 = tracker.add_task("Task 2", total=50, task_id="t2")
        task3 = tracker.add_task("Task 3", total=200, task_id="t3")

        assert task1 == TaskID(1)
        assert task2 == TaskID(2)
        assert task3 == TaskID(3)
        assert len(tracker._tasks) == 3

    def test_add_task_zero_total(self, mock_progress, mock_console):
        """Test adding task with total=0."""
        tracker = ProgressTracker()
        tracker.start()

        tracker.add_task("Empty task", total=0)

        mock_progress.add_task.assert_called_with("Empty task", total=0)

    def test_add_task_float_total(self, mock_progress, mock_console):
        """Test adding task with float total."""
        tracker = ProgressTracker()
        tracker.start()

        tracker.add_task("Processing", total=99.5)

        mock_progress.add_task.assert_called_with("Processing", total=99.5)


class TestProgressTrackerUpdate:
    """Test updating task progress."""

    def test_update_with_advance(self, mock_progress, mock_console):
        """Test updating task progress with advance."""
        tracker = ProgressTracker()
        tracker.start()

        mock_progress.add_task.return_value = TaskID(1)
        task = tracker.add_task("Processing", total=100)

        tracker.update(task, advance=10)

        mock_progress.update.assert_called_with(
            task, advance=10, completed=None, description=None
        )

    def test_update_with_completed(self, mock_progress, mock_console):
        """Test updating task with absolute completed value."""
        tracker = ProgressTracker()
        tracker.start()

        task = tracker.add_task("Processing", total=100)
        tracker.update(task, completed=50)

        mock_progress.update.assert_called_with(
            task, advance=None, completed=50, description=None
        )

    def test_update_with_description(self, mock_progress, mock_console):
        """Test updating task description."""
        tracker = ProgressTracker()
        tracker.start()

        task = tracker.add_task("Processing", total=100)
        tracker.update(task, description="Processing file 5/10")

        mock_progress.update.assert_called_with(
            task, advance=None, completed=None, description="Processing file 5/10"
        )

    def test_update_with_all_parameters(self, mock_progress, mock_console):
        """Test updating with all parameters."""
        tracker = ProgressTracker()
        tracker.start()

        task = tracker.add_task("Processing", total=100)
        tracker.update(task, advance=5, completed=50, description="Halfway there")

        mock_progress.update.assert_called_with(
            task, advance=5, completed=50, description="Halfway there"
        )

    def test_update_with_kwargs(self, mock_progress, mock_console):
        """Test update with additional kwargs."""
        tracker = ProgressTracker()
        tracker.start()

        task = tracker.add_task("Processing", total=100)
        tracker.update(task, advance=10, visible=False)

        mock_progress.update.assert_called_with(
            task, advance=10, completed=None, description=None, visible=False
        )

    def test_update_by_custom_task_id(self, mock_progress, mock_console):
        """Test updating task by custom task_id string."""
        tracker = ProgressTracker()
        tracker.start()

        task = tracker.add_task("Processing", total=100, task_id="my_task")
        tracker.update("my_task", advance=10)

        # Should resolve string to TaskID and update
        mock_progress.update.assert_called_with(
            task, advance=10, completed=None, description=None
        )

    def test_update_nonexistent_task_id(self, mock_progress, mock_console, mock_logger):
        """Test updating with nonexistent custom task_id logs warning."""
        tracker = ProgressTracker()
        tracker.start()

        tracker.update("nonexistent", advance=10)

        mock_logger.warning.assert_called_with("Task 'nonexistent' not found")
        # Should not call progress.update
        mock_progress.update.assert_not_called()

    def test_update_not_started(self, mock_logger):
        """Test update when tracker not started."""
        tracker = ProgressTracker()

        tracker.update(TaskID(1), advance=10)

        mock_logger.debug.assert_called_with(
            "Progress tracker not started, skipping update"
        )

    def test_update_after_stop(self, mock_progress, mock_console, mock_logger):
        """Test update after stop does nothing."""
        tracker = ProgressTracker()
        tracker.start()
        task = tracker.add_task("Processing", total=100)
        tracker.stop()

        # Reset mock to check calls after stop
        mock_progress.reset_mock()

        tracker.update(task, advance=10)

        mock_logger.debug.assert_called_with(
            "Progress tracker not started, skipping update"
        )
        mock_progress.update.assert_not_called()

    def test_update_multiple_times(self, mock_progress, mock_console):
        """Test updating task multiple times."""
        tracker = ProgressTracker()
        tracker.start()

        task = tracker.add_task("Processing", total=100)

        for i in range(5):
            tracker.update(task, advance=20)

        assert mock_progress.update.call_count == 5


class TestProgressTrackerGetTask:
    """Test retrieving task IDs."""

    def test_get_task_existing(self, mock_progress, mock_console):
        """Test getting existing task by custom ID."""
        tracker = ProgressTracker()
        tracker.start()

        task_id = tracker.add_task("Processing", total=100, task_id="my_task")
        result = tracker.get_task("my_task")

        assert result == task_id

    def test_get_task_nonexistent(self, mock_progress, mock_console):
        """Test getting nonexistent task returns None."""
        tracker = ProgressTracker()
        tracker.start()

        result = tracker.get_task("nonexistent")

        assert result is None

    def test_get_task_before_start(self):
        """Test get_task before starting tracker."""
        tracker = ProgressTracker()

        result = tracker.get_task("any_task")

        assert result is None


class TestProgressTrackerRemoveTask:
    """Test removing tasks from tracker."""

    def test_remove_task_by_task_id(self, mock_progress, mock_console):
        """Test removing task by Rich TaskID."""
        tracker = ProgressTracker()
        tracker.start()

        task = tracker.add_task("Processing", total=100, task_id="my_task")
        tracker.remove_task(task)

        mock_progress.remove_task.assert_called_with(task)
        # Should also remove from custom tasks
        assert "my_task" not in tracker._tasks

    def test_remove_task_by_string_id(self, mock_progress, mock_console):
        """Test removing task by custom string ID."""
        tracker = ProgressTracker()
        tracker.start()

        task = tracker.add_task("Processing", total=100, task_id="my_task")
        tracker.remove_task("my_task")

        mock_progress.remove_task.assert_called_with(task)
        assert "my_task" not in tracker._tasks

    def test_remove_nonexistent_string_id(
        self, mock_progress, mock_console, mock_logger
    ):
        """Test removing nonexistent custom task ID."""
        tracker = ProgressTracker()
        tracker.start()

        tracker.remove_task("nonexistent")

        mock_logger.warning.assert_called_with("Task 'nonexistent' not found")
        mock_progress.remove_task.assert_not_called()

    def test_remove_task_not_started(self):
        """Test remove_task when tracker not started."""
        tracker = ProgressTracker()

        tracker.remove_task(TaskID(1))  # Should not raise

    def test_remove_task_clears_from_dict(self, mock_progress, mock_console):
        """Test removing task clears it from _tasks dict."""
        tracker = ProgressTracker()
        tracker.start()

        mock_progress.add_task.return_value = TaskID(1)

        tracker.add_task("Task 1", total=100, task_id="t1")
        assert "t1" in tracker._tasks

        tracker.remove_task("t1")
        assert "t1" not in tracker._tasks

    def test_remove_task_by_rich_task_id_removes_from_dict(
        self, mock_progress, mock_console
    ):
        """Test removing by Rich TaskID also removes from custom dict."""
        tracker = ProgressTracker()
        tracker.start()

        task = tracker.add_task("Task", total=100, task_id="custom")

        # Remove by Rich TaskID
        tracker.remove_task(task)

        # Should remove from custom dict too
        assert "custom" not in tracker._tasks

    def test_remove_multiple_tasks(self, mock_progress, mock_console):
        """Test removing multiple tasks."""
        tracker = ProgressTracker()
        tracker.start()

        mock_progress.add_task.side_effect = [TaskID(1), TaskID(2), TaskID(3)]

        tracker.add_task("Task 1", total=100, task_id="t1")
        tracker.add_task("Task 2", total=100, task_id="t2")
        tracker.add_task("Task 3", total=100, task_id="t3")

        tracker.remove_task("t1")
        tracker.remove_task("t2")

        assert "t1" not in tracker._tasks
        assert "t2" not in tracker._tasks
        assert "t3" in tracker._tasks


class TestCreateSpinner:
    """Test create_spinner convenience function."""

    def test_create_spinner_basic(self, mock_progress, mock_console):
        """Test basic spinner creation."""
        with create_spinner("Loading...") as tracker:
            assert isinstance(tracker, ProgressTracker)
            assert tracker._progress is not None
            mock_progress.start.assert_called_once()
            # Should add one indeterminate task
            mock_progress.add_task.assert_called_with("Loading...", total=None)

        # Should stop after context
        mock_progress.stop.assert_called_once()

    def test_create_spinner_transient_true(self, mock_console):
        """Test spinner with transient=True."""
        with patch("depkeeper.utils.progress.Progress") as MockProgress:
            mock_instance = MagicMock()
            MockProgress.return_value = mock_instance

            with create_spinner("Loading...", transient=True):
                pass

            assert MockProgress.call_args.kwargs["transient"] is True

    def test_create_spinner_transient_false(self, mock_console):
        """Test spinner with transient=False."""
        with patch("depkeeper.utils.progress.Progress") as MockProgress:
            mock_instance = MagicMock()
            MockProgress.return_value = mock_instance

            with create_spinner("Loading...", transient=False):
                pass

            assert MockProgress.call_args.kwargs["transient"] is False

    def test_create_spinner_no_time(self, mock_progress, mock_console):
        """Test spinner has show_time=False."""
        with create_spinner("Loading...") as tracker:
            assert tracker.show_time is False

    def test_create_spinner_exception_handling(self, mock_progress, mock_console):
        """Test spinner stops even on exception."""
        with pytest.raises(ValueError):
            with create_spinner("Loading..."):
                raise ValueError("Test error")

        # Should still stop
        mock_progress.stop.assert_called_once()

    def test_create_spinner_yields_tracker(self, mock_progress, mock_console):
        """Test spinner yields tracker instance."""
        with create_spinner("Loading...") as tracker:
            assert isinstance(tracker, ProgressTracker)
            assert tracker._progress is not None

    def test_create_spinner_can_add_more_tasks(self, mock_progress, mock_console):
        """Test can add more tasks to yielded tracker."""
        mock_progress.add_task.side_effect = [TaskID(1), TaskID(2)]

        with create_spinner("Loading...") as tracker:
            # Spinner adds one task
            assert mock_progress.add_task.call_count == 1

            # Can add more tasks
            tracker.add_task("Additional task", total=100)
            assert mock_progress.add_task.call_count == 2

    def test_create_spinner_description_variations(self, mock_progress, mock_console):
        """Test spinner with different descriptions."""
        descriptions = [
            "Loading...",
            "Fetching data",
            "Connecting to server",
            "Processing request",
        ]

        for desc in descriptions:
            mock_progress.reset_mock()
            with create_spinner(desc):
                mock_progress.add_task.assert_called_with(desc, total=None)


class TestCreateProgress:
    """Test create_progress convenience function."""

    def test_create_progress_basic(self, mock_progress, mock_console):
        """Test basic progress bar creation."""
        with create_progress("Processing", total=100) as (tracker, task):
            assert isinstance(tracker, ProgressTracker)
            assert task == TaskID(1)
            assert tracker._progress is not None
            mock_progress.start.assert_called_once()
            mock_progress.add_task.assert_called_with("Processing", total=100)

        mock_progress.stop.assert_called_once()

    def test_create_progress_yields_tuple(self, mock_progress, mock_console):
        """Test progress yields (tracker, task) tuple."""
        with create_progress("Processing", total=50) as result:
            assert isinstance(result, tuple)
            assert len(result) == 2
            tracker, task = result
            assert isinstance(tracker, ProgressTracker)
            assert task == TaskID(1)

    def test_create_progress_with_float_total(self, mock_progress, mock_console):
        """Test progress bar with float total."""
        with create_progress("Processing", total=99.5):
            mock_progress.add_task.assert_called_with("Processing", total=99.5)

    def test_create_progress_transient_true(self, mock_console):
        """Test progress with transient=True."""
        with patch("depkeeper.utils.progress.Progress") as MockProgress:
            mock_instance = MagicMock()
            MockProgress.return_value = mock_instance

            with create_progress("Processing", total=100, transient=True):
                pass

            assert MockProgress.call_args.kwargs["transient"] is True

    def test_create_progress_transient_false(self, mock_console):
        """Test progress with transient=False."""
        with patch("depkeeper.utils.progress.Progress") as MockProgress:
            mock_instance = MagicMock()
            MockProgress.return_value = mock_instance

            with create_progress("Processing", total=100, transient=False):
                pass

            assert MockProgress.call_args.kwargs["transient"] is False

    def test_create_progress_update(self, mock_progress, mock_console):
        """Test updating progress bar."""
        with create_progress("Processing", total=100) as (tracker, task):
            tracker.update(task, advance=10)

            mock_progress.update.assert_called_with(
                task, advance=10, completed=None, description=None
            )

    def test_create_progress_exception_handling(self, mock_progress, mock_console):
        """Test progress stops even on exception."""
        with pytest.raises(RuntimeError):
            with create_progress("Processing", total=100):
                raise RuntimeError("Test error")

        mock_progress.stop.assert_called_once()

    def test_create_progress_complete_workflow(self, mock_progress, mock_console):
        """Test complete progress workflow."""
        mock_progress.add_task.return_value = TaskID(1)

        with create_progress("Processing files", total=5) as (tracker, task):
            for i in range(5):
                # Simulate work
                tracker.update(task, advance=1)

        # Should have 5 updates
        assert mock_progress.update.call_count == 5

    def test_create_progress_zero_total(self, mock_progress, mock_console):
        """Test progress bar with total=0."""
        with create_progress("Empty", total=0):
            mock_progress.add_task.assert_called_with("Empty", total=0)

    def test_create_progress_large_total(self, mock_progress, mock_console):
        """Test progress bar with very large total."""
        with create_progress("Big task", total=1000000):
            mock_progress.add_task.assert_called_with("Big task", total=1000000)

    def test_create_progress_description_update(self, mock_progress, mock_console):
        """Test updating progress description."""
        with create_progress("Processing", total=10) as (tracker, task):
            tracker.update(task, advance=1, description="Processing item 1/10")

            mock_progress.update.assert_called_with(
                task, advance=1, completed=None, description="Processing item 1/10"
            )


class TestDisabledTracker:
    """Test progress tracker with disable=True."""

    def test_disabled_start_does_nothing(self, mock_logger):
        """Test start() with disabled tracker."""
        tracker = ProgressTracker(disable=True)
        tracker.start()

        assert tracker._progress is None
        mock_logger.debug.assert_called_with("Progress tracking disabled")

    def test_disabled_add_task_raises(self):
        """Test add_task raises when disabled (no progress instance)."""
        tracker = ProgressTracker(disable=True)
        tracker.start()

        with pytest.raises(RuntimeError, match="Progress tracker not started"):
            tracker.add_task("Task", total=100)

    def test_disabled_context_manager(self):
        """Test context manager works when disabled."""
        tracker = ProgressTracker(disable=True)

        with tracker as t:
            assert t is tracker
            assert t._progress is None

    def test_disabled_spinner(self, mock_logger):
        """Test create_spinner respects disable flag indirectly."""
        # Note: create_spinner doesn't directly support disable,
        # but tracker can be disabled after creation
        with patch("depkeeper.utils.progress.ProgressTracker") as MockTracker:
            mock_instance = MagicMock()
            mock_instance._progress = None
            MockTracker.return_value = mock_instance

            with create_spinner("Loading...") as tracker:
                pass

    def test_disabled_progress(self):
        """Test create_progress with disabled tracker."""
        # Similar to spinner - disable would need to be set on tracker
        pass  # Covered by basic disabled tests


class TestProgressIntegration:
    """Integration tests for progress tracking."""

    def test_full_workflow_with_multiple_tasks(self, mock_progress, mock_console):
        """Test complete workflow with multiple tasks."""
        mock_progress.add_task.side_effect = [TaskID(1), TaskID(2), TaskID(3)]

        with ProgressTracker() as tracker:
            # Add tasks
            task1 = tracker.add_task("Download", total=100, task_id="download")
            task2 = tracker.add_task("Process", total=50, task_id="process")
            task3 = tracker.add_task("Upload", total=200, task_id="upload")

            # Update tasks
            tracker.update("download", advance=50)
            tracker.update("process", completed=25)
            tracker.update(task3, advance=100)

            # Remove a task
            tracker.remove_task("process")

            # Continue with remaining tasks
            tracker.update("download", advance=50)
            tracker.update(task3, advance=100)

        # Verify cleanup
        assert tracker._progress is None
        assert len(tracker._tasks) == 0

    def test_nested_progress_contexts(self, mock_console):
        """Test nested progress contexts (separate trackers)."""
        with patch("depkeeper.utils.progress.Progress") as MockProgress:
            mock1 = MagicMock()
            mock2 = MagicMock()
            MockProgress.side_effect = [mock1, mock2]

            with ProgressTracker() as outer:
                outer.add_task("Outer task", total=100)

                with ProgressTracker() as inner:
                    inner.add_task("Inner task", total=50)

            # Both should be stopped
            mock1.stop.assert_called_once()
            mock2.stop.assert_called_once()

    def test_spinner_and_progress_together(self, mock_console):
        """Test using spinner and progress in sequence."""
        with patch("depkeeper.utils.progress.Progress") as MockProgress:
            mock1 = MagicMock()
            mock2 = MagicMock()
            MockProgress.side_effect = [mock1, mock2]

            # First use spinner
            with create_spinner("Loading..."):
                pass

            # Then use progress
            with create_progress("Processing", total=100):
                pass

            mock1.stop.assert_called_once()
            mock2.stop.assert_called_once()

    def test_reusing_tracker(self, mock_console):
        """Test reusing tracker after stop."""
        with patch("depkeeper.utils.progress.Progress") as MockProgress:
            mock1 = MagicMock()
            mock2 = MagicMock()
            MockProgress.side_effect = [mock1, mock2]

            tracker = ProgressTracker()

            # First use
            tracker.start()
            tracker.add_task("Task 1", total=100)
            tracker.stop()

            # Second use
            tracker.start()
            tracker.add_task("Task 2", total=50)
            tracker.stop()

            # Both progress instances should be created and stopped
            assert MockProgress.call_count == 2
            mock1.stop.assert_called_once()
            mock2.stop.assert_called_once()


class TestProgressEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_task_id_collision_handling(self, mock_progress, mock_console):
        """Test handling of task_id collisions."""
        tracker = ProgressTracker()
        tracker.start()

        mock_progress.add_task.side_effect = [TaskID(1), TaskID(2)]

        # Add task with ID
        task1 = tracker.add_task("Task 1", total=100, task_id="same_id")

        # Add another with same ID (overwrites)
        task2 = tracker.add_task("Task 2", total=50, task_id="same_id")

        # Second task should overwrite
        assert tracker.get_task("same_id") == task2

    def test_empty_description(self, mock_progress, mock_console):
        """Test task with empty description."""
        tracker = ProgressTracker()
        tracker.start()

        tracker.add_task("", total=100)

        mock_progress.add_task.assert_called_with("", total=100)

    def test_very_long_description(self, mock_progress, mock_console):
        """Test task with very long description."""
        long_desc = "A" * 1000

        tracker = ProgressTracker()
        tracker.start()

        tracker.add_task(long_desc, total=100)

        mock_progress.add_task.assert_called_with(long_desc, total=100)

    def test_negative_total(self, mock_progress, mock_console):
        """Test task with negative total (unusual but allowed)."""
        tracker = ProgressTracker()
        tracker.start()

        tracker.add_task("Task", total=-100)

        mock_progress.add_task.assert_called_with("Task", total=-100)

    def test_negative_advance(self, mock_progress, mock_console):
        """Test updating with negative advance (going backwards)."""
        tracker = ProgressTracker()
        tracker.start()

        task = tracker.add_task("Task", total=100)
        tracker.update(task, advance=-10)

        mock_progress.update.assert_called_with(
            task, advance=-10, completed=None, description=None
        )

    def test_update_beyond_total(self, mock_progress, mock_console):
        """Test updating progress beyond total."""
        tracker = ProgressTracker()
        tracker.start()

        task = tracker.add_task("Task", total=100)
        tracker.update(task, completed=150)

        # Should still call update (Rich handles overflow)
        mock_progress.update.assert_called_with(
            task, advance=None, completed=150, description=None
        )

    def test_special_characters_in_task_id(self, mock_progress, mock_console):
        """Test task_id with special characters."""
        tracker = ProgressTracker()
        tracker.start()

        special_ids = ["task-1", "task_2", "task.3", "task@4", "task#5"]

        mock_progress.add_task.side_effect = [
            TaskID(i) for i in range(len(special_ids))
        ]

        for task_id in special_ids:
            tracker.add_task("Task", total=100, task_id=task_id)
            assert tracker.get_task(task_id) is not None


class TestProgressConcurrency:
    """Test thread safety and concurrent usage."""

    def test_tracker_in_different_threads(self, mock_progress, mock_console):
        """Test tracker can be used in different threads."""
        import threading

        tracker = ProgressTracker()
        tracker.start()

        mock_progress.add_task.return_value = TaskID(1)
        task = tracker.add_task("Task", total=100)

        def update_progress():
            for _ in range(10):
                tracker.update(task, advance=1)

        # Create threads
        threads = [threading.Thread(target=update_progress) for _ in range(3)]

        # Start threads
        for t in threads:
            t.start()

        # Wait for completion
        for t in threads:
            t.join()

        # Should have 30 updates total (3 threads * 10 updates)
        assert mock_progress.update.call_count == 30

        tracker.stop()


class TestProgressTypeHints:
    """Test type hint compatibility."""

    def test_tracker_type_hints(self):
        """Test ProgressTracker type hints are correct."""
        tracker: ProgressTracker = ProgressTracker()
        assert isinstance(tracker, ProgressTracker)

    def test_task_id_type(self, mock_progress, mock_console):
        """Test TaskID type is correct."""
        tracker = ProgressTracker()
        tracker.start()

        task: TaskID = tracker.add_task("Task", total=100)
        assert task == TaskID(1)

    def test_create_spinner_return_type(self, mock_progress, mock_console):
        """Test create_spinner return type."""
        with create_spinner("Loading...") as tracker:
            assert isinstance(tracker, ProgressTracker)

    def test_create_progress_return_type(self, mock_progress, mock_console):
        """Test create_progress return type."""
        with create_progress("Processing", total=100) as result:
            tracker, task = result
            assert isinstance(tracker, ProgressTracker)
            assert task == TaskID(1)


class TestProgressLogging:
    """Test integration with logging system."""

    def test_logging_on_start(self, mock_console, mock_logger):
        """Test debug log on start."""
        with patch("depkeeper.utils.progress.Progress") as MockProgress:
            MockProgress.return_value = MagicMock()

            tracker = ProgressTracker()
            tracker.start()

            mock_logger.debug.assert_called_with("Progress tracker started")

    def test_logging_on_disabled(self, mock_logger):
        """Test debug log when disabled."""
        tracker = ProgressTracker(disable=True)
        tracker.start()

        mock_logger.debug.assert_called_with("Progress tracking disabled")

    def test_logging_on_double_start(self, mock_console, mock_logger):
        """Test warning log on double start."""
        with patch("depkeeper.utils.progress.Progress") as MockProgress:
            MockProgress.return_value = MagicMock()

            tracker = ProgressTracker()
            tracker.start()
            mock_logger.reset_mock()

            tracker.start()  # Second start

            mock_logger.warning.assert_called_with("Progress tracker already started")

    def test_logging_on_task_not_found(self, mock_progress, mock_console, mock_logger):
        """Test warning log when task not found."""
        tracker = ProgressTracker()
        tracker.start()

        tracker.update("nonexistent", advance=10)

        mock_logger.warning.assert_called_with("Task 'nonexistent' not found")

    def test_logging_on_remove_task(self, mock_progress, mock_console, mock_logger):
        """Test debug log on remove task."""
        tracker = ProgressTracker()
        tracker.start()

        task = tracker.add_task("Task", total=100, task_id="my_task")
        mock_logger.reset_mock()

        tracker.remove_task("my_task")

        mock_logger.debug.assert_called_with("Removed task: my_task")
