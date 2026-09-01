"""Editing the photographs a filed scan was judged from.

Every route here re-runs the pipeline before it returns. That is the point: an image
set and the findings read from it are one thing, and letting them drift apart — even
for the moment between "photograph deleted" and "someone remembers to re-check" — puts
a violation on screen that the current evidence does not support.

Who may edit: the officer who filed the scan, or an administrator. Photographs are the
evidence behind a finding, so changing them is a change to the record, not a tidy-up.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from starlette.concurrency import run_in_threadpool

from app.api.deps import ADMIN, AnyOfficer, DbSession, WritableDb
from app.models.enums import ImageKind
from app.models.tables import Scan, ScanImage, User
from app.schemas.scan import ScanResultOut, ScanRevisionOut
from app.services import imageedit, persistence, scanning, storage
from app.services.imaging import MAX_IMAGES, ScanInputError, decode

log = logging.getLogger(__name__)

router = APIRouter(prefix="/scans/{scan_id}/images", tags=["scan images"])


def _load(db, scan_id: str) -> Scan:
    scan = persistence.load_scan(db, scan_id)
    if scan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No scan {scan_id!r}.")
    if scan.deleted_at is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This scan has been deleted; its photographs cannot be changed.",
        )
    return scan


def _may_edit(scan: Scan, officer: User) -> None:
    """An officer edits their own scans; an administrator edits any.

    Photographs are the evidence a finding rests on. One officer silently replacing
    another's evidence is the kind of change a record has to be able to rule out.
    """
    if officer.role == ADMIN or scan.created_by_id == officer.id:
        return
    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        "This scan was filed by another officer. Ask them, or an administrator, to "
        "change its photographs.",
    )


def _respond(db, scan: Scan) -> ScanResultOut:
    db.commit()
    reopened = persistence.load_scan(db, scan.id)
    assert reopened is not None
    return persistence.to_response(reopened, imageedit.ruleset_for(reopened))


async def _decode_upload(upload: UploadFile, kind: str) -> tuple[bytes, str]:
    if kind.upper() not in {k.value for k in ImageKind}:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"{kind!r} is not a kind of image; expected one of "
            f"{sorted(k.value for k in ImageKind)}.",
        )
    data = await upload.read()
    try:
        decode(data, filename=upload.filename, content_type=upload.content_type)
    except ScanInputError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return data, kind.upper()


@router.post(
    "",
    response_model=ScanResultOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a photograph to a filed scan and re-judge it",
)
async def add_image(
    scan_id: str,
    db: WritableDb,
    officer: AnyOfficer,
    image: Annotated[UploadFile, File()],
    kind: Annotated[str, Form()] = ImageKind.SIDE.value,
) -> ScanResultOut:
    scan = _load(db, scan_id)
    _may_edit(scan, officer)
    if len(scan.images) >= MAX_IMAGES:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"This scan already holds {MAX_IMAGES} photographs. Remove one first.",
        )

    data, kind_value = await _decode_upload(image, kind)
    decoded = decode(data, filename=image.filename, content_type=image.content_type)
    height, width = decoded.shape[:2]

    image_id = scanning.new_image_id()
    row = ScanImage(
        id=image_id,
        scan_id=scan.id,
        kind=kind_value,
        storage_key=storage.put_image(decoded, scan_id=scan.id, image_id=image_id),
        original_filename=image.filename,
        width=int(width),
        height=int(height),
        ocr_blocks=[],
    )
    db.add(row)
    db.flush()
    db.refresh(scan)

    edit = imageedit.Edit(
        action="IMAGE_ADDED",
        reason="image added",
        detail=f"{image.filename or image_id[:8]} added as {kind_value}",
    )
    try:
        await run_in_threadpool(imageedit.apply, db, scan, edit, officer)
    except imageedit.ImageEditError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return _respond(db, scan)


@router.delete(
    "/{image_id}",
    response_model=ScanResultOut,
    summary="Remove a photograph from a filed scan and re-judge it",
)
async def remove_image(
    scan_id: str, image_id: str, db: WritableDb, officer: AnyOfficer
) -> ScanResultOut:
    scan = _load(db, scan_id)
    _may_edit(scan, officer)

    try:
        row = imageedit.find_image(scan, image_id)
    except imageedit.ImageEditError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    if len(scan.images) <= imageedit.MIN_IMAGES:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A scan must keep at least one photograph. Add a replacement first, or "
            "delete the whole scan.",
        )

    detail = f"{row.original_filename or row.id[:8]} ({row.kind}) removed"
    db.delete(row)
    db.flush()
    db.refresh(scan)

    edit = imageedit.Edit(action="IMAGE_REMOVED", reason="image removed", detail=detail)
    try:
        await run_in_threadpool(imageedit.apply, db, scan, edit, officer)
    except imageedit.ImageEditError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return _respond(db, scan)


@router.post(
    "/{image_id}:replace",
    response_model=ScanResultOut,
    summary="Retake a photograph on a filed scan and re-judge it",
)
async def replace_image(
    scan_id: str,
    image_id: str,
    db: WritableDb,
    officer: AnyOfficer,
    image: Annotated[UploadFile, File()],
) -> ScanResultOut:
    scan = _load(db, scan_id)
    _may_edit(scan, officer)

    try:
        row = imageedit.find_image(scan, image_id)
    except imageedit.ImageEditError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    data, _ = await _decode_upload(image, str(row.kind))
    decoded = decode(data, filename=image.filename, content_type=image.content_type)
    height, width = decoded.shape[:2]

    was = row.original_filename or row.id[:8]
    # The row keeps its id so findings still cite the same slot on the pack; only the
    # pixels behind it change.
    row.storage_key = storage.put_image(decoded, scan_id=scan.id, image_id=row.id)
    row.original_filename = image.filename
    row.width = int(width)
    row.height = int(height)
    row.ocr_blocks = []
    db.flush()
    db.refresh(scan)

    edit = imageedit.Edit(
        action="IMAGE_REPLACED",
        reason="image replaced",
        detail=f"{was} retaken as {image.filename or 'a new photograph'}",
    )
    try:
        await run_in_threadpool(imageedit.apply, db, scan, edit, officer)
    except imageedit.ImageEditError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return _respond(db, scan)


# Mounted separately: the history of a scan is not a sub-resource of its images, even
# though editing images is what creates it.
revisions_router = APIRouter(prefix="/scans/{scan_id}/revisions", tags=["scan images"])


@revisions_router.get(
    "",
    response_model=list[ScanRevisionOut],
    summary="What this scan said before its photographs were edited",
)
def list_revisions(
    scan_id: str, db: DbSession, officer: AnyOfficer
) -> list[ScanRevisionOut]:
    """Superseded readings, oldest first.

    Each entry is the whole result as it stood before an edit — verdict, score,
    findings and any officer decisions recorded against them. Nothing is discarded by
    an edit; it is moved here.
    """
    scan = _load(db, scan_id)
    return [
        ScanRevisionOut(
            revision=row.revision,
            reason=row.reason,
            detail=row.detail,
            superseded_at=row.created_at,
            superseded_by_id=row.superseded_by_id,
            snapshot=row.snapshot,
        )
        for row in scan.revisions
    ]
