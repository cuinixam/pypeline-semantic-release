import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from py_app_dev.core.exceptions import UserNotificationException
from py_app_dev.core.logging import logger
from pypeline.domain.execution_context import ExecutionContext
from pypeline.domain.pipeline import PipelineStep


@contextmanager
def change_directory(path: Path) -> Iterator[None]:
    """Temporarily change the working directory to the given path and revert to the original directory when done."""
    original_path = Path.cwd()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(original_path)


class BaseStep(PipelineStep[ExecutionContext]):
    """Base step defining all required methods."""

    def __init__(self, execution_context: ExecutionContext, group_name: str | None = None, config: dict[str, Any] | None = None) -> None:
        super().__init__(execution_context, group_name, config)
        self.logger = logger.bind()

    def run(self) -> None:
        pass

    def get_inputs(self) -> list[Path]:
        return []

    def get_outputs(self) -> list[Path]:
        return []

    def get_name(self) -> str:
        return self.__class__.__name__

    def update_execution_context(self) -> None:
        pass

    def get_needs_dependency_management(self) -> bool:
        """It shall always run, independent off any dependencies."""
        return False

    def execute_process(self, command: list[str | Path], error_msg: str) -> None:
        proc_executor = self.execution_context.create_process_executor(command)
        # When started from a shell (e.g. cmd on Jenkins) the shell parameter must be set to True
        proc_executor.shell = True if os.name == "nt" else False
        process = proc_executor.execute(handle_errors=False)
        if process and process.returncode != 0:
            raise UserNotificationException(f"{error_msg} Return code: {process.returncode}")
