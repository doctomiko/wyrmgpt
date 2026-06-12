from server.routes.base import app
from server.api_helpers import promote_targets_for_scope
from server.db import db_update_conversation_scaffold_event
from server.logging_helper import log_warn


def attach_scaffold_events_to_message(event_ids: list[int], message_id: int | None) -> None:
    """
    Temporary compatibility shim while route modules still import this from server.main.
    """
    if not message_id:
        return
    for event_id in event_ids:
        try:
            db_update_conversation_scaffold_event(event_id=event_id, message_id=message_id)
        except Exception as exc:
            log_warn(f"Tool scaffold event attachment failed for event {event_id}: {exc}")


# Import route modules for side effects so their @app decorators register endpoints.
import server.routes.artifacts  # noqa: F401
import server.routes.chat  # noqa: F401
import server.routes.conversations  # noqa: F401
import server.routes.deployments  # noqa: F401
import server.routes.files  # noqa: F401
import server.routes.library  # noqa: F401
import server.routes.memories  # noqa: F401
import server.routes.projects  # noqa: F401
import server.routes.search  # noqa: F401
import server.routes.sharing  # noqa: F401
import server.routes.tooling  # noqa: F401

__all__ = ["app"]