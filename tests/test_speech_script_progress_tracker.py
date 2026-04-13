from landppt.services.progress_tracker import ProgressInfo


def test_progress_percentage_counts_failed_and_skipped_slides():
    progress = ProgressInfo(
        task_id="task-1",
        project_id="project-1",
        total_slides=5,
        completed_slides=2,
        failed_slides=1,
        skipped_slides=1,
    )

    assert progress.processed_slides == 4
    assert progress.progress_percentage == 80


def test_progress_percentage_is_capped_by_total_slides():
    progress = ProgressInfo(
        task_id="task-2",
        project_id="project-2",
        total_slides=2,
        completed_slides=2,
        failed_slides=1,
        skipped_slides=1,
    )

    assert progress.processed_slides == 2
    assert progress.progress_percentage == 100
