"""
Schemas for the workplace-content import feature.

Two distinct flows live in one file because they're tightly coupled:

  (1) An OWNER creates an ImportShare — a time-limited public publication
      of their workplace. They get back a friendly `code` to share.
  (2) Anyone with the code can preview what's inside the share and then
      apply a subset of it to their OWN current workplace.

Layouts (saved table arrangements) ride along with their parent hall.
There is no separate flag for them — picking a hall implies picking its
layouts. This matches the UX decision we locked in.
"""
from typing import List, Optional

from pydantic import Field

from .common import APIModel, NanoID


# ============================================================
# Creating / managing shares (owner-side)
# ============================================================

class ImportShareCreate(APIModel):
    """
    POST /workplaces/{id}/import-shares

    Owner picks a TTL in hours. We default to 24h; the UI lets users edit
    the number freely up to a week (above that you should probably revoke
    and create a fresh one). Server clamps to a safe range regardless of
    what the client sends.
    """
    ttl_hours: int = Field(default=24, ge=1, le=168)


class ImportShareOut(APIModel):
    """Owner-side view of one share."""
    id: str
    code: str
    workplace_id: str
    created_by_user_id: int
    created_at: int
    expires_at: int
    revoked_at: Optional[int] = None
    import_count: int
    is_active: bool  # derived: revoked_at is None AND expires_at > now()


# ============================================================
# Previewing a share (importer-side, before they decide)
# ============================================================

class ImportPreviewHall(APIModel):
    """A hall available in the share. Counts let the UI render summaries
    without re-fetching."""
    id: str
    name: str
    tables_count: int
    layouts_count: int


class ImportPreviewCategory(APIModel):
    id: str
    title: str
    items_count: int


class ImportPreviewOut(APIModel):
    """
    GET /import/{code}/preview

    Returns the minimal info needed to render the import screen:
    workplace title (so the importer knows where the content came from),
    plus the lists of selectable halls and menu categories. No prices,
    no positions — those come in on apply.
    """
    source_workplace_title: str
    halls: List[ImportPreviewHall] = []
    categories: List[ImportPreviewCategory] = []


# ============================================================
# Applying — actually copying selected content
# ============================================================

class ImportApplyRequest(APIModel):
    """
    POST /import/{code}/apply

    `target_workplace_id`: where the copy goes. Must be a workplace the
    caller has access to (any role is fine — we're writing into the
    importer's own space, not anything the share owns).

    `hall_ids` / `category_ids`: subset of what came back from preview.
    Empty lists are valid — e.g. import only menu, or only halls.
    """
    target_workplace_id: NanoID
    hall_ids: List[NanoID] = Field(default_factory=list)
    category_ids: List[NanoID] = Field(default_factory=list)


class ImportApplyResult(APIModel):
    """Summary for the success toast on the client."""
    halls_imported: int
    tables_imported: int
    layouts_imported: int
    categories_imported: int
    items_imported: int