"""Knowledge-base REST endpoints: book upload, ingestion control, inspection, search.

Database writes use the server-only secret key and RLS denies direct client access. Every endpoint
here needs a verified Supabase identity with a trusted operator role. See docs/ingestion-api.md.
"""

import logging
from functools import lru_cache
from typing import Annotated, NoReturn
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)

from app.ai.ingestion.extraction import ExtractionError
from app.ai.ingestion.service import (
    BookNotFoundError,
    BudgetExhaustedError,
    ConfirmationRequiredError,
    DuplicateBookError,
    IngestionError,
    IngestionService,
    ProviderPausedError,
)
from app.ai.rag.coverage import book_completeness, page_range
from app.ai.rag.guard import embedding_paused, pause_reason
from app.ai.rag.retrieval import FallbackRetriever, KeywordRetriever, Retriever, VectorRetriever
from app.api.auth import require_operator
from app.core.config import get_settings
from app.schemas.ingestion import (
    BookIngestionOut,
    ChunkPage,
    EventOut,
    JobOut,
    OverviewOut,
    PlanOut,
    StartRequest,
    TextPreview,
)
from app.schemas.knowledge import BookOut, PassageOut, SearchRequest, SearchResponse
from app.services import knowledge_db
from app.services.embeddings import VOYAGE_DEFAULT_DIMENSION, get_embedding_provider
from app.services.supabase import get_supabase_admin_client

router = APIRouter(prefix="/api", tags=["knowledge"], dependencies=[Depends(require_operator)])

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
logger = logging.getLogger(__name__)


def _provider_pause_reason() -> str | None:
    """While the owner's provider stop is set no website job may start, and running jobs pause."""
    reason = pause_reason()
    if reason:
        return f"{reason} Only the owner can clear it, after checking the provider account."
    return None


def _provider_info() -> dict[str, object]:
    """Which provider receives the tokens, by the key's prefix (the key is never shown)."""
    settings = get_settings()
    key = settings.voyage_api_key
    if not key:
        host, provider = "not configured", "Voyage AI embeddings"
    elif key.startswith("al-"):
        host, provider = "ai.mongodb.com", "MongoDB Atlas AI Model APIs (Voyage models)"
    else:
        host, provider = "api.voyageai.com", "Voyage AI embeddings"
    return {
        "provider": provider,
        "endpoint_host": host,
        "model": settings.voyage_model,
        "dimension": VOYAGE_DEFAULT_DIMENSION,
    }


@lru_cache
def get_ingestion_service() -> IngestionService:
    settings = get_settings()
    return IngestionService(
        db=get_supabase_admin_client(),
        embedder=get_embedding_provider(),
        max_tokens=settings.max_run_embedding_tokens,
        budget_tokens=settings.embedding_budget_tokens,
        batch_tokens=settings.embedding_batch_tokens,
        requests_per_minute=settings.embedding_requests_per_minute,
        provider_pause=_provider_pause_reason,
        provider_info=_provider_info(),
    )


Service = Annotated[IngestionService, Depends(get_ingestion_service)]


def _require_db_config() -> None:
    if not get_settings().supabase_url or not get_settings().supabase_secret_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Knowledge base is not configured (SUPABASE_URL / SUPABASE_SECRET_KEY missing)",
        )


def _fail(exc: Exception) -> NoReturn:
    """One place that turns ingestion errors into HTTP answers the screens can show."""
    if isinstance(exc, BookNotFoundError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    if isinstance(exc, (BudgetExhaustedError, ProviderPausedError)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc)) from exc
    if isinstance(exc, (ConfirmationRequiredError, IngestionError)):
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    if isinstance(exc, knowledge_db.KnowledgeDBError):
        logger.error("Ingestion database operation failed")
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "The database is temporarily unavailable."
        ) from exc
    raise exc


# -- upload and listing ---------------------------------------------------------


@router.post("/books", response_model=BookOut, status_code=status.HTTP_201_CREATED)
def register_book(
    service: Service,
    file: Annotated[UploadFile, File(description="PDF or TXT source file")],
    category: Annotated[str, Form(description="materia_medica | repertory | organon | general")],
    title: Annotated[str, Form(min_length=1, max_length=300)],
    author: Annotated[str | None, Form(max_length=300)] = None,
    publisher: Annotated[str | None, Form(max_length=300)] = None,
    publication_year: Annotated[int | None, Form(ge=0, le=2100)] = None,
    language: Annotated[str, Form(max_length=20)] = "en",
    source_uri: Annotated[str | None, Form(max_length=500)] = None,
) -> BookOut:
    """Upload and register a book; text is extracted now. Calls no provider."""
    _require_db_config()
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds the 50 MB upload limit")
    try:
        book = service.register_book(
            filename=file.filename or "upload",
            data=data,
            category=category,
            title=title,
            author=author,
            publisher=publisher,
            publication_year=publication_year,
            language=language,
            source_uri=source_uri,
        )
    except DuplicateBookError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ExtractionError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except knowledge_db.KnowledgeDBError as exc:
        # Two identical uploads at once both pass the duplicate check; the database's unique
        # constraint catches the second one. That is a duplicate (409), not a server error.
        if "content_hash" in str(exc) or "duplicate key" in str(exc).lower():
            raise HTTPException(
                status_code=409, detail="This book is already registered (identical content)"
            ) from exc
        logger.error("Book registration failed in the database")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The book could not be saved. Try again later.",
        ) from exc
    return BookOut(**book)


@router.get("/books", response_model=list[BookOut])
def list_books() -> list[BookOut]:
    """List registered books (without extracted text)."""
    _require_db_config()
    return [BookOut(**row) for row in knowledge_db.list_books(get_supabase_admin_client())]


# -- ingestion controls -----------------------------------------------------------


@router.get("/ingestion/overview", response_model=OverviewOut)
def ingestion_overview(service: Service) -> OverviewOut:
    """Every book with REAL index counts from the database, active jobs, and the spending limits."""
    _require_db_config()
    try:
        data = service.overview()
    except Exception as exc:
        _fail(exc)
    return OverviewOut(**data)


@router.get("/books/{book_id}/ingestion", response_model=BookIngestionOut)
def book_ingestion(book_id: UUID, service: Service) -> BookIngestionOut:
    _require_db_config()
    try:
        data = service.book_ingestion(str(book_id))
    except Exception as exc:
        _fail(exc)
    return BookIngestionOut(**data)


@router.post("/books/{book_id}/prepare", response_model=PlanOut)
def prepare_book(book_id: UUID, service: Service) -> PlanOut:
    """Extract the book's text into chunks. Free: no provider call is made."""
    _require_db_config()
    try:
        service.prepare_book(str(book_id))
        return PlanOut(**service.plan(str(book_id)))
    except Exception as exc:
        _fail(exc)


@router.post("/books/{book_id}/ingest", response_model=JobOut, status_code=202)
def start_ingestion(
    book_id: UUID, body: StartRequest, background_tasks: BackgroundTasks, service: Service
) -> JobOut:
    """Start, resume or retry embedding. Spends provider tokens, so it needs confirmed=true."""
    _require_db_config()
    try:
        job = service.start_ingestion(
            str(book_id), confirmed=body.confirmed, max_tokens=body.max_tokens
        )
    except Exception as exc:
        _fail(exc)
    background_tasks.add_task(service.run_ingestion, job["id"])
    return JobOut(**job)


@router.post("/ingestion-jobs/{job_id}/pause", response_model=JobOut)
def pause_ingestion_job(job_id: UUID, service: Service) -> JobOut:
    """The job finishes its current batch, then stops safely. It can be resumed later."""
    _require_db_config()
    try:
        return JobOut(**service.pause_job(str(job_id)))
    except Exception as exc:
        _fail(exc)


@router.get("/ingestion-jobs/{job_id}", response_model=JobOut)
def get_ingestion_job(job_id: UUID) -> JobOut:
    """Read ingestion progress: stage, chunk counters, tokens, errors."""
    _require_db_config()
    job = knowledge_db.get_ingestion_job(get_supabase_admin_client(), str(job_id))
    if job is None:
        raise HTTPException(status_code=404, detail=f"Ingestion job {job_id} not found")
    return JobOut(**job)


@router.get("/ingestion-jobs/{job_id}/events", response_model=list[EventOut])
def ingestion_job_events(
    job_id: UUID, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> list[EventOut]:
    """History and errors of one job, newest first."""
    _require_db_config()
    rows = knowledge_db.list_ingestion_events(
        get_supabase_admin_client(), job_id=str(job_id), limit=limit
    )
    return [EventOut(**row) for row in rows]


@router.get("/books/{book_id}/chunks", response_model=ChunkPage)
def book_chunks(
    book_id: UUID,
    service: Service,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    q: Annotated[str | None, Query(max_length=200)] = None,
    embedded: Annotated[bool | None, Query()] = None,
) -> ChunkPage:
    """Inspect how a book was split. Vectors are never returned."""
    _require_db_config()
    try:
        data = service.chunk_page(
            str(book_id), offset=offset, limit=limit, query=q, embedded=embedded
        )
    except Exception as exc:
        _fail(exc)
    return ChunkPage(**data)


@router.get("/books/{book_id}/text", response_model=TextPreview)
def book_text(
    book_id: UUID,
    service: Service,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
) -> TextPreview:
    """Inspect the extracted text, page by page (PDF page numbers)."""
    _require_db_config()
    try:
        return TextPreview(**service.text_preview(str(book_id), offset=offset, limit=limit))
    except Exception as exc:
        _fail(exc)


# -- search -------------------------------------------------------------------------


@router.post("/search", response_model=SearchResponse)
def search_knowledge_base(request: SearchRequest) -> SearchResponse:
    """Meaning-based search, or labelled keyword matching when that is unavailable."""
    _require_db_config()
    db = get_supabase_admin_client()
    keyword = KeywordRetriever(db)
    # Meaning-based search when allowed and reachable; otherwise word matching, clearly labelled.
    retriever: Retriever = (
        keyword
        if embedding_paused()
        else FallbackRetriever(VectorRetriever(db=db, embedder=get_embedding_provider()), keyword)
    )
    passages, latency_ms = retriever.search(
        query=request.query,
        k=request.k,
        category=request.category.value if request.category else None,
        threshold=request.threshold,
    )
    mode = getattr(retriever, "mode", "semantic")
    knowledge_db.save_retrieval_evaluation(
        db,
        {
            "query_text": request.query,
            "category_filter": request.category.value if request.category else None,
            "k": request.k,
            "results": [
                {"chunk_id": p.chunk_id, "book_id": p.book_id, "score": p.similarity}
                for p in passages
            ],
            "embedding_model": "keyword" if mode == "keyword" else get_settings().voyage_model,
            "latency_ms": latency_ms,
        },
    )
    complete = book_completeness(db)
    results: list[PassageOut] = []
    incomplete: set[str] = set()
    for p in passages:
        start, end = page_range(p.metadata)
        is_complete = complete.get(p.book_id, False)
        if not is_complete:
            incomplete.add(p.book_title)
        results.append(
            PassageOut(**p.__dict__, page_start=start, page_end=end, book_complete=is_complete)
        )
    return SearchResponse(
        query=request.query,
        k=request.k,
        latency_ms=latency_ms,
        results=results,
        incomplete_books=sorted(incomplete),
        retrieval_mode=mode,
    )
