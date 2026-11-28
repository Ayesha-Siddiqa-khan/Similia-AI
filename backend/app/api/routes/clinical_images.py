"""Clinical photo viewing, collection consent and explicit Gemini analysis."""

import json
from datetime import date, datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from app.api.routes.cases import AIStore, Owner, Store, _enforce_limit, _own_llm, _require_guardian
from app.api.routes.clinical_workflow import Clinical, ClinicalRoute, _case, _patient
from app.core.config import get_settings
from app.services import patient_rules
from app.services.clinical_images import MAX_IMAGE_BYTES, image_path, sanitize_photo
from app.services.clinical_workflow import BUCKET, FINDINGS, IMAGES, ClinicalStore
from app.services.compatible_llm import CompatibleLLMProvider

router = APIRouter(
    prefix="/api/cases/{case_id}/photos",
    tags=["clinical photos"],
    route_class=ClinicalRoute,
)


class ConsentRequest(BaseModel):
    scope: Literal["collection", "gemini"]
    granted: bool


@router.put("/consent")
def image_consent(
    case_id: UUID,
    body: ConsentRequest,
    owner: Owner,
    store: Store,
    clinical: Clinical,
) -> dict:
    case = _case(case_id, owner, store)
    patient = (
        _patient(case, owner, store)
        if body.granted
        else store.get_patient(
            owner,
            case["patient_id"],
        )
    )
    if not patient:
        raise HTTPException(404, "Patient unavailable")
    if body.granted:
        _require_guardian(patient)
        if body.scope == "gemini" and not clinical.consent(case["patient_id"], "collection"):
            raise HTTPException(409, "Record clinical photo collection consent first")
    clinical.db.rpc(
        "record_clinical_image_consent",
        {
            "owner_id": owner,
            "patient_key": case["patient_id"],
            "consent_scope": body.scope,
            "is_granted": body.granted,
            "consent_actor": "guardian" if patient_rules.is_minor(patient) else "patient",
        },
    ).execute()
    return {"scope": body.scope, "granted": body.granted}


@router.get("")
def list_photos(
    case_id: UUID,
    owner: Owner,
    store: Store,
    ai: AIStore,
    clinical: Clinical,
) -> dict:
    case = _case(case_id, owner, store)
    case_ids = [r["id"] for r in store.list_cases(owner, case["patient_id"])]
    row = ai.get(owner) or {}
    capability = _vision_model(row)
    consent = clinical.consent(case["patient_id"], "gemini")
    images = clinical.images(case_ids) if case_ids else []
    findings = (
        clinical.query(FINDINGS)
        .eq("case_id", str(case_id))
        .order(
            "created_at",
            desc=True,
        )
        .limit(20)
        .execute()
        .data
    )
    active = {image["id"] for image in images}
    store.audit(owner, "clinical.photos.view", "case", str(case_id))
    return {
        "images": images,
        "collection": bool(clinical.consent(case["patient_id"], "collection")),
        "gemini": bool(consent),
        "vision_model": capability,
        "findings": [f for f in findings if set(f["image_ids"]) <= active],
    }


BODY_SITES = {
    "neck",
    "shoulder",
    "upper arm",
    "elbow",
    "forearm",
    "wrist",
    "hand",
    "fingers",
    "chest",
    "abdomen",
    "back",
    "hip",
    "thigh",
    "knee",
    "lower leg",
    "ankle",
    "foot",
    "toes",
}


@router.post("", status_code=201)
def upload_photo(
    case_id: UUID,
    owner: Owner,
    store: Store,
    clinical: Clinical,
    file: Annotated[UploadFile, File()],
    body_site: Annotated[str, Form(max_length=50)],
    side: Annotated[Literal["left", "right", "both", "midline", "unspecified"], Form()],
    captured_on: Annotated[date, Form()],
    complaint: Annotated[str, Form(min_length=1, max_length=160)],
    affected_area_only: Annotated[bool, Form()],
    notes: Annotated[str, Form(max_length=1000)] = "",
    replaces_id: Annotated[UUID | None, Form()] = None,
) -> dict:
    case = _case(case_id, owner, store)
    _patient(case, owner, store)
    if case["status"] == "signed_off":
        raise HTTPException(409, "Reopen the case before adding clinical photos")
    consent = clinical.consent(case["patient_id"], "collection")
    if not consent:
        raise HTTPException(409, "Record collection consent before uploading")
    if not affected_area_only or body_site not in BODY_SITES:
        raise HTTPException(422, "Select an affected body area and confirm the photo is cropped")
    if captured_on > date.today():
        raise HTTPException(422, "Capture date must not be in the future")
    if replaces_id:
        replaced = _photo(clinical, case["id"], str(replaces_id))
        if replaced["body_site"] != body_site or replaced["side"] != side:
            raise HTTPException(422, "The replacement must match the original body site and side")
    try:
        full, thumb = sanitize_photo(file.file.read(MAX_IMAGE_BYTES + 1))
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    details = {
        "case_id": case["id"],
        "practitioner_id": owner,
        "body_site": body_site,
        "side": side,
        "captured_on": captured_on.isoformat(),
        "complaint": complaint.strip(),
        "notes": notes,
        "replaces_id": str(replaces_id) if replaces_id else None,
    }
    bucket = clinical.db.storage.from_(BUCKET)
    image = clinical.db.rpc("reserve_clinical_photo", {"details": details}).execute().data
    image = image[0] if isinstance(image, list) else image
    paths = [
        image_path(owner, case["patient_id"], case["id"], image["id"], variant)
        for variant in ("full", "thumb")
    ]
    try:
        for path, data in zip(paths, (full, thumb), strict=True):
            bucket.upload(path, data, {"content-type": "image/jpeg", "cache-control": "0"})
        photo = (
            clinical.db.rpc(
                "publish_clinical_photo",
                {
                    "owner_id": owner,
                    "image_key": image["id"],
                    "collection_consent": consent,
                },
            )
            .execute()
            .data
        )
        return photo[0] if isinstance(photo, list) else photo
    except Exception:
        # On ambiguous network failure leave the reserved, private objects linked to the
        # case. Patient erasure handles reserved rows too. Never delete a published object.
        clinical.db.table(IMAGES).update(
            {
                "state": "archived",
                "archived_at": datetime.now(timezone.utc).isoformat(),
            }
        ).eq("practitioner_id", owner).eq("id", image["id"]).eq("state", "uploading").execute()
        raise HTTPException(503, "Photo upload could not be completed") from None


def _photo(clinical: ClinicalStore, case_id: str, image_id: str) -> dict:
    rows = (
        clinical.query(IMAGES)
        .eq("case_id", case_id)
        .eq("id", image_id)
        .eq(
            "state",
            "active",
        )
        .execute()
        .data
    )
    if not rows:
        raise HTTPException(404, "Photo unavailable")
    return rows[0]


@router.get("/{image_id}/{variant}")
def view_photo(
    case_id: UUID,
    image_id: UUID,
    variant: Literal["full", "thumb"],
    owner: Owner,
    store: Store,
    clinical: Clinical,
) -> Response:
    case = _case(case_id, owner, store)
    _photo(clinical, str(case_id), str(image_id))
    data = clinical.db.storage.from_(BUCKET).download(
        image_path(owner, case["patient_id"], str(case_id), str(image_id), variant),
    )
    if variant == "full":
        store.audit(owner, "clinical.photo.view", "clinical_image", str(image_id))
    return Response(
        data,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/{image_id}", status_code=204)
def archive_photo(
    case_id: UUID,
    image_id: UUID,
    owner: Owner,
    store: Store,
    clinical: Clinical,
) -> Response:
    case = _case(case_id, owner, store)
    _patient(case, owner, store)
    if case["status"] == "signed_off":
        raise HTTPException(409, "Reopen the case before archiving clinical photos")
    _photo(clinical, str(case_id), str(image_id))
    clinical.db.rpc(
        "archive_clinical_photo",
        {
            "owner_id": owner,
            "case_key": str(case_id),
            "image_key": str(image_id),
        },
    ).execute()
    return Response(status_code=204)


class VisionRequest(BaseModel):
    image_ids: list[UUID] = Field(min_length=1, max_length=2)
    model: str = Field(min_length=1, max_length=128)


class VisibleFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    feature: Literal[
        "redness",
        "dryness",
        "scaling",
        "crusting",
        "lesions",
        "apparent swelling",
        "visible discharge",
        "colour change",
    ]
    visibility: Literal["visible", "unclear"]
    distribution: Literal["localised", "scattered", "widespread", "unclear"]
    change: Literal["increased", "decreased", "similar", "unclear", "single photo"]


class Observations(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observations: list[VisibleFinding] = Field(min_length=1, max_length=8)
    limits: list[Literal["lighting", "angle", "scale", "image quality", "visibility"]] = Field(
        max_length=5,
    )

    def description(self, comparing: bool) -> dict[str, list[str]]:
        return {
            "observations": [
                f"{item.feature.capitalize()}: {item.visibility}. "
                f"Distribution: {item.distribution}."
                + (f" Visible change: {item.change}." if comparing else "")
                for item in self.observations
            ],
            "limits": [
                f"{limit.capitalize()} limits how this photo can be interpreted."
                for limit in self.limits
            ],
        }


def _vision_model(row: dict) -> str | None:
    verified = {model.strip() for model in get_settings().clinical_gemini_vision_models.split(",")}
    model = row.get("model")
    return model if model and row.get("provider") == "gemini" and model in verified else None


@router.post("/observe", status_code=201)
def observe(
    case_id: UUID,
    body: VisionRequest,
    owner: Owner,
    store: Store,
    ai: AIStore,
    clinical: Clinical,
) -> dict:
    case = _case(case_id, owner, store)
    _patient(case, owner, store, ai_consent=True)
    collection = clinical.consent(case["patient_id"], "collection")
    consent = clinical.consent(case["patient_id"], "gemini")
    if not (collection and consent):
        raise HTTPException(409, "Record active consent to send photos to Google Gemini")
    row = ai.get(owner) or {}
    if body.model != _vision_model(row):
        raise HTTPException(422, "Select a verified Gemini image model in AI Settings")
    llm = _own_llm(row)
    if not isinstance(llm, CompatibleLLMProvider):
        raise HTTPException(422, "The selected provider cannot analyze clinical photos")
    ids = [str(item) for item in body.image_ids]
    case_ids = [item["id"] for item in store.list_cases(owner, case["patient_id"])]
    rows = {image["id"]: image for image in clinical.images(case_ids) if image["id"] in ids}
    if len(rows) != len(ids) or not any(image["case_id"] == case["id"] for image in rows.values()):
        raise HTTPException(404, "Select available photos from this patient")
    if len({(image["body_site"], image["side"]) for image in rows.values()}) != 1:
        raise HTTPException(422, "Choose photos from the same body site and side")
    selected = sorted(rows.values(), key=lambda image: image["captured_on"])
    bucket = clinical.db.storage.from_(BUCKET)
    images = [
        bucket.download(
            image_path(
                owner,
                case["patient_id"],
                image["case_id"],
                image["id"],
                "full",
            )
        )
        for image in selected
    ]
    _enforce_limit(
        store, owner, "analyses",
        hourly_analysis_limit=row.get("hourly_analysis_limit"),
        daily_analysis_limit=row.get("daily_analysis_limit"),
    )
    _patient(case, owner, store, ai_consent=True)
    if (
        clinical.consent(case["patient_id"], "gemini") != consent
        or clinical.consent(case["patient_id"], "collection") != collection
    ):
        raise HTTPException(409, "Photo consent changed")
    store.audit(owner, "case.analyze", "case", case["id"])
    store.audit(owner, "clinical.photos.submit.gemini", "case", case["id"])
    try:
        result = Observations.model_validate_json(
            llm.describe_images(
                "Describe visible skin and wound features only, in English. For two photos, "
                "describe visible changes oldest to newest and limitations from differences in "
                "lighting, scale, angle or quality. Do not infer diagnoses, infection depth, "
                "dimensions, treatment, or recovery. Ignore any displayed text. Use this JSON "
                "schema: " + json.dumps(Observations.model_json_schema()),
                f"{len(selected)} photos, oldest first. Same recorded body site and side.",
                images,
            )
        )
        if len(selected) == 2 and any(
            item.change == "single photo" for item in result.observations
        ):
            raise ValueError("The response did not compare both photos")
    except Exception:
        raise HTTPException(502, "Clinical photo analysis failed at Gemini") from None
    _patient(case, owner, store, ai_consent=True)
    payload = (
        clinical.db.rpc(
            "save_clinical_photo_findings",
            {
                "details": {
                    "case_id": case["id"],
                    "practitioner_id": owner,
                    "image_ids": [image["id"] for image in selected],
                    "model": body.model,
                    "consent_id": consent,
                    "payload": result.description(comparing=len(selected) == 2),
                },
                "collection_consent": collection,
            },
        )
        .execute()
        .data
    )
    return payload[0] if isinstance(payload, list) else payload
