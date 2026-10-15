"""FastAPI application factory. Every route requires the per-launch token."""

import secrets
import sqlite3
import webbrowser
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from sqlite3 import Connection
from typing import Annotated, Final
from urllib.parse import quote, unquote

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

from llmjobtracker.claude_code_runner import ClaudeCodeRunner
from llmjobtracker.claude_code_runner import auth_status as claude_code_auth_status
from llmjobtracker.claude_code_runner import logout as claude_code_logout
from llmjobtracker.claude_job_queue import ClaudeJobQueue, PromptRejected
from llmjobtracker.claude_jobs import (
    ClaudeJob,
    PromptExchange,
    get_claude_job,
    list_claude_jobs,
    prompt_exchange,
    recover_interrupted,
)
from llmjobtracker.codex_runner import CodexRunner
from llmjobtracker.codex_runner import auth_status as codex_auth_status
from llmjobtracker.codex_runner import logout as codex_logout
from llmjobtracker.export_llm_bundle import LlmAppStatus, export_llm_bundle, llm_app_status
from llmjobtracker.file_preview import UnsupportedPreview, preview_for
from llmjobtracker.job_applications import (
    InvalidRoleTitle,
    JobApplication,
    JobApplicationDetail,
    JobApplicationEdit,
    MasterCvSelection,
    NoStatusEntries,
    StatusHistoryEdit,
    UnknownField,
    delete_job_application,
    get_job_application_detail,
    insert_job_application,
    list_job_applications,
    replace_status_history,
    set_master_cv,
    update_job_application,
)
from llmjobtracker.job_files import (
    DuplicateListingMatch,
    JobApplicationFile,
    JobFileUploadError,
    delete_job_file,
    find_duplicate_listing,
    insert_job_file,
    listing_text_sha256,
    managed_folder,
    store_job_file,
)
from llmjobtracker.job_pipeline import (
    ADD_JOB_WORKFLOWS,
    JobIdentityAnswer,
    JobStepNotReady,
    clear_match_score,
    clear_positioning,
    parse_identity_answer,
    queue_add_job_chain,
    submit_check_job_listing_text,
    submit_extract_job_identity,
    submit_generate_application_history,
    submit_generate_cover_letter,
    submit_generate_interview_prep,
    submit_generate_job_details,
    submit_generate_job_listing,
    submit_generate_positioning,
    submit_generate_tailored_cv,
)
from llmjobtracker.job_revise_pipeline import (
    JobReviseNotReady,
    make_pipeline,
    submit_job_revise_turn,
)
from llmjobtracker.job_revise_turns import (
    JobReviseTurn,
    turns_for_section,
)
from llmjobtracker.job_revise_turns import (
    turn_for_job as job_revise_turn_for_job,
)
from llmjobtracker.langgraph_runner import LangGraphRunner
from llmjobtracker.listing_intake import (
    ListingExtraction,
    ListingFetchError,
    extract_from_paste,
    extract_from_upload,
    extract_from_url,
)
from llmjobtracker.migrations import JOB_REVISE_SECTION_KINDS as SECTION_KINDS
from llmjobtracker.migrations import RUNNER_BACKENDS
from llmjobtracker.pricing import (
    ModelPrice,
    delete_model_price,
    get_pricing_url,
    list_model_prices,
    rename_model_price,
    set_pricing_url,
    upsert_model_price,
)
from llmjobtracker.pricing_pipeline import (
    ParsedModelPrice,
    parse_fetch_prices_answer,
    submit_fetch_model_prices,
)
from llmjobtracker.profile_files import (
    ProfileFile,
    ProfileFileText,
    ProfileUploadError,
    delete_profile_file,
    list_profile_files,
    open_in_default_app,
    profile_file_name,
    profile_file_path,
    profile_file_text,
    reveal_in_file_manager,
    store_profile_file,
)
from llmjobtracker.profile_pipeline import (
    PROMPT_KIND_FOR_OWN,
    PROMPT_KINDS,
    ProfileBusy,
    ProfileNotReady,
    ProfileOutput,
    clear_output,
    list_latest_outputs,
    submit_profile_analysis,
)
from llmjobtracker.revise_pipeline import submit_revise_turn
from llmjobtracker.revise_turns import ReviseTurn, turn_for_job, turns_for_kind
from llmjobtracker.runner import AuthStatus, Runner, RunResult
from llmjobtracker.settings import Settings, get_settings, save_settings
from llmjobtracker.storage import connect

# The one prompt the Phase 1 button sends. It contains no personal data.
CHECK_PROMPT = "Reply with the single word OK."

TOKEN_HEADER = "X-Launch-Token"

# "Open LLM app" (D-202, D-210): the deep link each backend's desktop app answers to, confirmed
# live against both apps - q/prompt prefills the composer (never auto-sent), folder/path roots
# the new session at the exported bundle (the user still confirms that folder once, per app).
LLM_APP_DEEP_LINKS: Final[dict[str, str]] = {
    "claude_code": "claude://code/new?q={prompt}&folder={path}",
    "codex": "codex://new?prompt={prompt}&path={path}",
}
# Kept short deliberately (D-202's 14,000-character q limit) - the actual context lives in the
# exported files, not the URL.
LLM_APP_PROMPT = (
    "I've exported my job tracker data into this folder. Please read seed.md first, then "
    "help me think through my applications."
)

# The content type the browser is told for each file_preview.Preview.kind (D-107). The frontend
# picks how to render a preview from this header, not from the file's own extension.
PREVIEW_MEDIA_TYPES: Final[dict[str, str]] = {
    "pdf": "application/pdf",
    "text": "text/plain; charset=utf-8",
    "markdown": "text/markdown; charset=utf-8",
    "html": "text/html; charset=utf-8",
}


class SettingsEdit(BaseModel):
    user_name: str
    # None keeps the stored value - a rename need not also restate the Phase 7 fields (D-195,
    # D-201, D-206), and a Phase 7 settings save need not restate the name.
    backend: str | None = None
    retry_policy: str | None = None
    retry_interval_minutes: int | None = None
    retry_max_attempts: int | None = None
    claude_code_model: str | None = None
    codex_model: str | None = None


class ModelPriceEdit(BaseModel):
    input_price_per_token: float
    output_price_per_token: float


class ModelPriceUpsert(ModelPriceEdit):
    provider: str
    model: str


class ModelPriceRename(BaseModel):
    new_model: str


class PricingUrlEdit(BaseModel):
    pricing_url: str | None = None


class LlmAppOpened(BaseModel):
    backend: str
    bundle_path: str


class ListingUrlRequest(BaseModel):
    url: str


class ListingPasteRequest(BaseModel):
    text: str


class ListingCheckRequest(BaseModel):
    text: str


class ListingGenerateRequest(BaseModel):
    method: str
    text: str


class DuplicateCheckRequest(BaseModel):
    text: str
    source_url: str | None = None


class IdentityRequest(BaseModel):
    text: str


class CreateJobApplicationRequest(BaseModel):
    """Add Job's confirmation stage (Agent/specs/intake-steps.md): the identity fields the user
    confirmed or typed by hand, the reviewed listing text and how it was obtained, the chosen
    workflow, and an optional Master CV reference."""

    company: str
    role_title: str
    lane: str | None = None
    location: str | None = None
    portal_name: str | None = None
    portal_url: str | None = None
    listing_method: str  # "url" | "paste" | "upload"
    listing_text: str
    listing_source_url: str | None = None
    workflow: str  # one of job_pipeline.ADD_JOB_WORKFLOWS
    master_cv_profile_file_id: int | None = None


class AddJobResult(BaseModel):
    application_id: int
    claude_job_ids: list[int]  # in queued order: Listing, Job details, then the rest (D-144)


class ReviseTurnCreate(BaseModel):
    message: str


class ReviseTurnView(BaseModel):
    """One chat turn and the Claude Job it queued (D-106)."""

    id: int
    message: str
    created_at: str
    job: ClaudeJob


class JobReviseTurnCreate(BaseModel):
    message: str
    # A job_files row already filed before this request (D-138) - only Application history's
    # chat reads it today.
    attachment_job_file_id: int | None = None


class JobReviseTurnView(BaseModel):
    """One chat turn revising a job-page section, and the Claude Job it queued (D-136)."""

    id: int
    message: str
    created_at: str
    job: ClaudeJob


def _rebuild_runner(existing: Runner, model: str) -> Runner:
    """A real ClaudeCodeRunner/CodexRunner, reconstructed with `model` if it differs from what
    it already has (D-206) - keeps its own workdir/timeout unchanged. Anything else (a
    FakeRunner in tests, for example) has no model to select, so it is returned as-is."""
    if isinstance(existing, ClaudeCodeRunner) and existing.model != model:
        return ClaudeCodeRunner(workdir=existing.workdir, model=model, timeout_s=existing.timeout_s)
    if isinstance(existing, CodexRunner) and existing.model != model:
        return CodexRunner(workdir=existing.workdir, model=model, timeout_s=existing.timeout_s)
    return existing


def create_app(
    launch_token: str,
    db_path: Path,
    runner: Runner,
    *,
    run_worker: bool = False,
    codex_runner: Runner | None = None,
) -> FastAPI:
    """Build the app. Requests must send `launch_token` in the X-Launch-Token header.

    `run_worker` starts the Claude Jobs worker with the app. Tests leave it off and step the
    queue themselves (ClaudeJobQueue.process_next), so the results are repeatable.

    `runner` is always registered under the `claude_code` backend. `codex_runner`, when given,
    is registered under `codex` (D-195: one global backend for the whole app, chosen in
    Settings) - tests that only care about one backend can leave it out.
    """
    # A Job Application's own files live under files/<company>/<role_title>/ (files.md),
    # alongside but separate from profile/ (db_path.parent is the data folder itself).
    files_root = db_path.parent / "files"
    render, on_result = make_pipeline(db_path.parent, files_root)

    # A stopped worker can leave jobs half done. Put them back in the queue (D-62).
    startup_conn = connect(db_path)
    try:
        recover_interrupted(startup_conn)
        startup_settings = get_settings(startup_conn)
    finally:
        startup_conn.close()

    # Each registered runner is rebuilt to the stored model (D-206, a restart must not silently
    # drop a previously-selected one) and wrapped once in LangGraphRunner (D-191, D-196), so the
    # queue's own dispatch (claude_job_queue.py) stays unaware of LangGraph entirely, same as it
    # stays unaware of Claude Code/Codex (D-20).
    runner = _rebuild_runner(runner, startup_settings.claude_code_model)
    if codex_runner is not None:
        codex_runner = _rebuild_runner(codex_runner, startup_settings.codex_model)
    runners: dict[str, Runner] = {"claude_code": LangGraphRunner(runner)}
    if codex_runner is not None:
        runners["codex"] = LangGraphRunner(codex_runner)

    queue = ClaudeJobQueue(
        db_path,
        runners.get(startup_settings.backend, runners["claude_code"]),
        on_result=on_result,
        render=render,
    )

    def require_token(x_launch_token: str | None = Header(default=None)) -> None:
        if x_launch_token is None or not secrets.compare_digest(x_launch_token, launch_token):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    def get_db() -> Iterator[Connection]:
        # FastAPI may set this dependency up and close it on different worker threads. The
        # connection serves one request, so it is safe to let it cross threads.
        conn = connect(db_path, check_same_thread=False)
        try:
            yield conn
        finally:
            conn.close()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if run_worker:
            queue.start()
        yield
        queue.stop()

    app = FastAPI(
        title="LlmJobTracker",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.queue = queue

    @app.get("/health", dependencies=[Depends(require_token)])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/settings", response_model=Settings, dependencies=[Depends(require_token)])
    def read_settings(conn: Annotated[Connection, Depends(get_db)]) -> Settings:
        return get_settings(conn)

    @app.put("/settings", response_model=Settings, dependencies=[Depends(require_token)])
    def update_settings(
        edit: SettingsEdit, conn: Annotated[Connection, Depends(get_db)]
    ) -> Settings:
        nonlocal runner, codex_runner
        current = get_settings(conn)
        new_backend = edit.backend if edit.backend is not None else current.backend
        new_claude_model = (
            edit.claude_code_model
            if edit.claude_code_model is not None
            else current.claude_code_model
        )
        new_codex_model = edit.codex_model if edit.codex_model is not None else current.codex_model
        try:
            saved = save_settings(
                conn,
                edit.user_name,
                new_backend,
                edit.retry_policy if edit.retry_policy is not None else current.retry_policy,
                edit.retry_interval_minutes
                if edit.retry_interval_minutes is not None
                else current.retry_interval_minutes,
                edit.retry_max_attempts
                if edit.retry_max_attempts is not None
                else current.retry_max_attempts,
                new_claude_model,
                new_codex_model,
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        # D-206: a changed model rebuilds that provider's runner, the same way a changed backend
        # (D-195) already does - both just mean "what the next queued job uses" now points
        # somewhere new.
        if new_claude_model != current.claude_code_model:
            runner = _rebuild_runner(runner, new_claude_model)
            runners["claude_code"] = LangGraphRunner(runner)
        if codex_runner is not None and new_codex_model != current.codex_model:
            codex_runner = _rebuild_runner(codex_runner, new_codex_model)
            runners["codex"] = LangGraphRunner(codex_runner)
        if (
            new_backend != current.backend
            or new_claude_model != current.claude_code_model
            or new_codex_model != current.codex_model
        ) and new_backend in runners:
            queue.set_runner(runners[new_backend])
        return saved

    @app.get(
        "/settings/prices", response_model=list[ModelPrice], dependencies=[Depends(require_token)]
    )
    def read_prices(conn: Annotated[Connection, Depends(get_db)]) -> list[ModelPrice]:
        return list_model_prices(conn)

    @app.put(
        "/settings/prices", response_model=list[ModelPrice], dependencies=[Depends(require_token)]
    )
    def save_prices(
        rows: list[ModelPriceUpsert], conn: Annotated[Connection, Depends(get_db)]
    ) -> list[ModelPrice]:
        """Writes every row given, in one call - used both to confirm a scraped proposal and to
        save several hand-edited rows at once (D-198)."""
        try:
            for row in rows:
                upsert_model_price(
                    conn,
                    row.provider,
                    row.model,
                    row.input_price_per_token,
                    row.output_price_per_token,
                )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return list_model_prices(conn)

    @app.put(
        "/settings/prices/{provider}/{model}",
        response_model=ModelPrice,
        dependencies=[Depends(require_token)],
    )
    def save_one_price(
        provider: str,
        model: str,
        edit: ModelPriceEdit,
        conn: Annotated[Connection, Depends(get_db)],
    ) -> ModelPrice:
        try:
            return upsert_model_price(
                conn, provider, model, edit.input_price_per_token, edit.output_price_per_token
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.put(
        "/settings/prices/{provider}/{model}/rename",
        response_model=ModelPrice,
        dependencies=[Depends(require_token)],
    )
    def rename_price(
        provider: str,
        model: str,
        edit: ModelPriceRename,
        conn: Annotated[Connection, Depends(get_db)],
    ) -> ModelPrice:
        try:
            renamed = rename_model_price(conn, provider, model, edit.new_model)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        # D-206: if the renamed row was the provider's active model, carry the rename into
        # Settings too, so the runner keeps calling the same model id it already is.
        current = get_settings(conn)
        if provider == "claude_code" and current.claude_code_model == model:
            update_settings(
                SettingsEdit(user_name=current.user_name, claude_code_model=renamed.model), conn
            )
        elif provider == "codex" and current.codex_model == model:
            update_settings(
                SettingsEdit(user_name=current.user_name, codex_model=renamed.model), conn
            )
        return renamed

    @app.delete(
        "/settings/prices/{provider}/{model}",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[Depends(require_token)],
    )
    def remove_price(
        provider: str, model: str, conn: Annotated[Connection, Depends(get_db)]
    ) -> Response:
        delete_model_price(conn, provider, model)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get(
        "/settings/pricing-urls",
        response_model=dict[str, str | None],
        dependencies=[Depends(require_token)],
    )
    def read_pricing_urls(conn: Annotated[Connection, Depends(get_db)]) -> dict[str, str | None]:
        return {backend: get_pricing_url(conn, backend) for backend in RUNNER_BACKENDS}

    @app.put(
        "/settings/pricing-urls/{provider}",
        response_model=dict[str, str | None],
        dependencies=[Depends(require_token)],
    )
    def save_pricing_url(
        provider: str, edit: PricingUrlEdit, conn: Annotated[Connection, Depends(get_db)]
    ) -> dict[str, str | None]:
        try:
            set_pricing_url(conn, provider, edit.pricing_url)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {provider: get_pricing_url(conn, provider)}

    @app.post(
        "/settings/prices/{provider}/fetch",
        response_model=ClaudeJob,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_token)],
    )
    def fetch_prices(provider: str, conn: Annotated[Connection, Depends(get_db)]) -> ClaudeJob:
        try:
            job_id = submit_fetch_model_prices(conn, queue, provider)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return _job_or_404(conn, job_id)

    @app.get(
        "/settings/prices/{provider}/fetch/{job_id}",
        response_model=list[ParsedModelPrice],
        dependencies=[Depends(require_token)],
    )
    def fetch_prices_result(
        provider: str, job_id: int, conn: Annotated[Connection, Depends(get_db)]
    ) -> list[ParsedModelPrice]:
        exchange = prompt_exchange(conn, job_id, 0)
        if exchange is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        try:
            return parse_fetch_prices_answer(conn, provider, exchange.result_text or "")
        except PromptRejected as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.get(
        "/settings/auth-status",
        response_model=dict[str, AuthStatus],
        dependencies=[Depends(require_token)],
    )
    def read_auth_status() -> dict[str, AuthStatus]:
        return {"claude_code": claude_code_auth_status(), "codex": codex_auth_status()}

    @app.post(
        "/settings/{backend}/logout",
        response_model=AuthStatus,
        dependencies=[Depends(require_token)],
    )
    def backend_logout(backend: str) -> AuthStatus:
        if backend == "claude_code":
            claude_code_logout()
            return claude_code_auth_status()
        if backend == "codex":
            codex_logout()
            return codex_auth_status()
        raise HTTPException(status_code=404, detail=f"Unknown backend: {backend!r}")

    @app.get(
        "/job-applications",
        response_model=list[JobApplication],
        dependencies=[Depends(require_token)],
    )
    def job_applications(
        conn: Annotated[Connection, Depends(get_db)],
    ) -> list[JobApplication]:
        return list_job_applications(conn)

    @app.post(
        "/job-applications",
        response_model=AddJobResult,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_token)],
    )
    def create_job_application(
        body: CreateJobApplicationRequest, conn: Annotated[Connection, Depends(get_db)]
    ) -> AddJobResult:
        company = body.company.strip()
        role_title = body.role_title.strip()
        listing_text = body.listing_text.strip()
        if not company or not role_title:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Company and role title are required.",
            )
        if not listing_text:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="There is no reviewed listing text.",
            )
        if body.workflow not in ADD_JOB_WORKFLOWS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown workflow: {body.workflow}.",
            )
        if body.workflow != "basic" and body.master_cv_profile_file_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Positioning analysis needs a Master CV selected.",
            )
        _require_master_cv_kind(conn, body.master_cv_profile_file_id)

        application_id = insert_job_application(
            conn,
            {
                "company": company,
                "role_title": role_title,
                "lane": body.lane,
                "location": body.location,
                "portal_name": body.portal_name,
                "portal_url": body.portal_url,
            },
        )
        if body.master_cv_profile_file_id is not None:
            set_master_cv(conn, application_id, body.master_cv_profile_file_id)

        # A placeholder listing row carries the reviewed text's dedup fingerprint (D-146)
        # forward until generate_job_listing replaces it with the model's own cleaned-up
        # version - _store_generated_listing preserves it rather than recomputing it from the
        # generated content.
        source_url = body.listing_source_url if body.listing_method == "url" else None
        folder = managed_folder(files_root, company, role_title)
        insert_job_file(
            conn,
            application_id,
            kind="listing",
            name="Job Listing.md",
            stored_path=(folder / "Job Listing.md").relative_to(files_root).as_posix(),
            sha256=listing_text_sha256(listing_text),
            source_url=source_url,
        )
        conn.commit()

        try:
            claude_job_ids = queue_add_job_chain(
                conn, queue, application_id, body.listing_method, listing_text, body.workflow
            )
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
            ) from error
        return AddJobResult(application_id=application_id, claude_job_ids=claude_job_ids)

    @app.get(
        "/job-applications/{application_id}",
        response_model=JobApplicationDetail,
        dependencies=[Depends(require_token)],
    )
    def job_application_detail(
        application_id: int, conn: Annotated[Connection, Depends(get_db)]
    ) -> JobApplicationDetail:
        detail = get_job_application_detail(conn, application_id)
        if detail is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return detail

    @app.delete(
        "/job-applications/{application_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[Depends(require_token)],
    )
    def delete_job_application_route(
        application_id: int, conn: Annotated[Connection, Depends(get_db)]
    ) -> None:
        if not delete_job_application(conn, files_root, application_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    @app.patch(
        "/job-applications/{application_id}",
        response_model=JobApplicationDetail,
        dependencies=[Depends(require_token)],
    )
    def edit_job_application(
        application_id: int,
        edit: JobApplicationEdit,
        conn: Annotated[Connection, Depends(get_db)],
    ) -> JobApplicationDetail:
        if get_job_application_detail(conn, application_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        try:
            detail = update_job_application(
                conn, application_id, edit.model_dump(exclude_unset=True), files_root
            )
        except UnknownField as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown field: {error}."
            ) from error
        except InvalidRoleTitle as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
            ) from error
        except sqlite3.IntegrityError as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
            ) from error
        assert detail is not None  # the 404 check above already confirmed the row exists
        return detail

    @app.post(
        "/job-applications/{application_id}/master-cv",
        response_model=JobApplicationDetail,
        dependencies=[Depends(require_token)],
    )
    def choose_master_cv(
        application_id: int,
        selection: MasterCvSelection,
        conn: Annotated[Connection, Depends(get_db)],
    ) -> JobApplicationDetail:
        if get_job_application_detail(conn, application_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        _require_master_cv_kind(conn, selection.profile_file_id)
        detail = set_master_cv(conn, application_id, selection.profile_file_id)
        assert detail is not None
        return detail

    @app.put(
        "/job-applications/{application_id}/status-history",
        response_model=JobApplicationDetail,
        dependencies=[Depends(require_token)],
    )
    def edit_status_history(
        application_id: int,
        edit: StatusHistoryEdit,
        conn: Annotated[Connection, Depends(get_db)],
    ) -> JobApplicationDetail:
        try:
            detail = replace_status_history(
                conn, application_id, [(entry.status, entry.changed_at) for entry in edit.entries]
            )
        except NoStatusEntries as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="At least one stage needs a date."
            ) from error
        except sqlite3.IntegrityError as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
            ) from error
        if detail is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return detail

    @app.post(
        "/job-applications/{application_id}/files/{kind}",
        response_model=JobApplicationFile,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_token)],
    )
    async def upload_job_file(
        application_id: int, kind: str, request: Request
    ) -> JobApplicationFile:
        name = unquote(request.headers.get("X-File-Name", ""))
        content = await request.body()
        conn = connect(db_path)
        try:
            return store_job_file(conn, files_root, application_id, kind, name, content)
        except JobFileUploadError as error:
            raise HTTPException(status_code=error.status, detail=error.message) from error
        finally:
            conn.close()

    @app.post(
        "/job-applications/{application_id}/files/{file_id}/open",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[Depends(require_token)],
    )
    def open_job_file(
        application_id: int, file_id: int, conn: Annotated[Connection, Depends(get_db)]
    ) -> None:
        path = _job_file_or_404(conn, files_root, application_id, file_id)
        open_in_default_app(path)

    @app.post(
        "/job-applications/{application_id}/files/{file_id}/reveal",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[Depends(require_token)],
    )
    def reveal_job_file(
        application_id: int, file_id: int, conn: Annotated[Connection, Depends(get_db)]
    ) -> None:
        path = _job_file_or_404(conn, files_root, application_id, file_id)
        reveal_in_file_manager(path)

    @app.get(
        "/job-applications/{application_id}/files/{file_id}/download",
        dependencies=[Depends(require_token)],
    )
    def download_job_file(
        application_id: int, file_id: int, conn: Annotated[Connection, Depends(get_db)]
    ) -> FileResponse:
        path = _job_file_or_404(conn, files_root, application_id, file_id)
        return FileResponse(path, filename=path.name)

    @app.get(
        "/job-applications/{application_id}/files/{file_id}/preview",
        dependencies=[Depends(require_token)],
    )
    def job_file_preview(
        application_id: int, file_id: int, conn: Annotated[Connection, Depends(get_db)]
    ) -> Response:
        path = _job_file_or_404(conn, files_root, application_id, file_id)
        try:
            preview = preview_for(path.name, path.read_bytes())
        except UnsupportedPreview as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
            ) from error
        content = (
            preview.content
            if isinstance(preview.content, bytes)
            else preview.content.encode("utf-8")
        )
        return Response(content=content, media_type=PREVIEW_MEDIA_TYPES[preview.kind])

    @app.delete(
        "/job-applications/{application_id}/files/{file_id}",
        dependencies=[Depends(require_token)],
    )
    def remove_job_file(
        application_id: int, file_id: int, conn: Annotated[Connection, Depends(get_db)]
    ) -> None:
        try:
            kind = delete_job_file(conn, files_root, application_id, file_id)
        except JobFileUploadError as error:
            raise HTTPException(status_code=error.status, detail=error.message) from error
        if kind == "positioning_breakdown":
            # The breakdown document is what match_score/positioning_scores were computed from
            # (D-47) - removing just the file would otherwise leave a score with nothing to
            # back it up (D-211).
            clear_match_score(conn, application_id)

    @app.post(
        "/job-applications/{application_id}/listing/extract-url",
        response_model=ListingExtraction,
        dependencies=[Depends(require_token)],
    )
    def extract_listing_from_url(
        application_id: int, body: ListingUrlRequest, conn: Annotated[Connection, Depends(get_db)]
    ) -> ListingExtraction:
        if get_job_application_detail(conn, application_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        try:
            return extract_from_url(body.url)
        except ListingFetchError as error:
            raise HTTPException(status_code=error.status, detail=error.message) from error

    @app.post(
        "/job-applications/{application_id}/listing/extract-paste",
        response_model=ListingExtraction,
        dependencies=[Depends(require_token)],
    )
    def extract_listing_from_paste(
        application_id: int,
        body: ListingPasteRequest,
        conn: Annotated[Connection, Depends(get_db)],
    ) -> ListingExtraction:
        if get_job_application_detail(conn, application_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return extract_from_paste(body.text)

    @app.post(
        "/job-applications/{application_id}/listing/extract-upload",
        response_model=ListingExtraction,
        dependencies=[Depends(require_token)],
    )
    async def extract_listing_from_upload(
        application_id: int, request: Request
    ) -> ListingExtraction:
        # Async, like upload_job_file/upload_profile_file below, so it opens its own connection
        # rather than sharing one across threads via Depends(get_db).
        name = unquote(request.headers.get("X-File-Name", ""))
        content = await request.body()
        conn = connect(db_path)
        try:
            if get_job_application_detail(conn, application_id) is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
            return extract_from_upload(name, content)
        except ListingFetchError as error:
            raise HTTPException(status_code=error.status, detail=error.message) from error
        finally:
            conn.close()

    @app.post(
        "/job-applications/{application_id}/listing/check",
        response_model=ClaudeJob,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_token)],
    )
    def check_listing_text(
        application_id: int,
        body: ListingCheckRequest,
        conn: Annotated[Connection, Depends(get_db)],
    ) -> ClaudeJob:
        if get_job_application_detail(conn, application_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        try:
            job_id = submit_check_job_listing_text(conn, queue, application_id, body.text)
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
            ) from error
        return _job_or_404(conn, job_id)

    @app.post(
        "/job-applications/{application_id}/listing/generate",
        response_model=ClaudeJob,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_token)],
    )
    def generate_listing(
        application_id: int,
        body: ListingGenerateRequest,
        conn: Annotated[Connection, Depends(get_db)],
    ) -> ClaudeJob:
        if get_job_application_detail(conn, application_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        try:
            job_id = submit_generate_job_listing(
                conn, queue, application_id, body.method, body.text
            )
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
            ) from error
        return _job_or_404(conn, job_id)

    # --- Add Job intake (Agent/specs/intake-steps.md): the same extraction and sanity check as
    # Listing's own routes above, run before a row exists (D-143 to D-146). -----------------------

    @app.post(
        "/job-applications/intake/extract-url",
        response_model=ListingExtraction,
        dependencies=[Depends(require_token)],
    )
    def intake_extract_from_url(body: ListingUrlRequest) -> ListingExtraction:
        try:
            return extract_from_url(body.url)
        except ListingFetchError as error:
            raise HTTPException(status_code=error.status, detail=error.message) from error

    @app.post(
        "/job-applications/intake/extract-paste",
        response_model=ListingExtraction,
        dependencies=[Depends(require_token)],
    )
    def intake_extract_from_paste(body: ListingPasteRequest) -> ListingExtraction:
        return extract_from_paste(body.text)

    @app.post(
        "/job-applications/intake/extract-upload",
        response_model=ListingExtraction,
        dependencies=[Depends(require_token)],
    )
    async def intake_extract_from_upload(request: Request) -> ListingExtraction:
        name = unquote(request.headers.get("X-File-Name", ""))
        content = await request.body()
        try:
            return extract_from_upload(name, content)
        except ListingFetchError as error:
            raise HTTPException(status_code=error.status, detail=error.message) from error

    @app.post(
        "/job-applications/intake/check",
        response_model=ClaudeJob,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_token)],
    )
    def intake_check_listing_text(
        body: ListingCheckRequest, conn: Annotated[Connection, Depends(get_db)]
    ) -> ClaudeJob:
        try:
            job_id = submit_check_job_listing_text(conn, queue, None, body.text)
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
            ) from error
        return _job_or_404(conn, job_id)

    @app.post(
        "/job-applications/intake/duplicate-check",
        response_model=DuplicateListingMatch | None,
        dependencies=[Depends(require_token)],
    )
    def intake_duplicate_check(
        body: DuplicateCheckRequest, conn: Annotated[Connection, Depends(get_db)]
    ) -> DuplicateListingMatch | None:
        return find_duplicate_listing(
            conn, sha256=listing_text_sha256(body.text), source_url=body.source_url
        )

    @app.post(
        "/job-applications/intake/identity",
        response_model=ClaudeJob,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_token)],
    )
    def intake_extract_identity(
        body: IdentityRequest, conn: Annotated[Connection, Depends(get_db)]
    ) -> ClaudeJob:
        try:
            job_id = submit_extract_job_identity(conn, queue, body.text)
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
            ) from error
        return _job_or_404(conn, job_id)

    @app.get(
        "/job-applications/intake/identity/{job_id}",
        response_model=JobIdentityAnswer,
        dependencies=[Depends(require_token)],
    )
    def intake_identity_result(
        job_id: int, conn: Annotated[Connection, Depends(get_db)]
    ) -> JobIdentityAnswer:
        exchange = prompt_exchange(conn, job_id, 0)
        if exchange is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        try:
            return parse_identity_answer(exchange.result_text or "")
        except PromptRejected as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
            ) from error

    @app.post(
        "/job-applications/{application_id}/job-details/generate",
        response_model=ClaudeJob,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_token)],
    )
    def generate_job_details(
        application_id: int, conn: Annotated[Connection, Depends(get_db)]
    ) -> ClaudeJob:
        if get_job_application_detail(conn, application_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        try:
            job_id = submit_generate_job_details(conn, queue, application_id)
        except JobStepNotReady as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
            ) from error
        return _job_or_404(conn, job_id)

    @app.post(
        "/job-applications/{application_id}/positioning/generate",
        response_model=ClaudeJob,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_token)],
    )
    def generate_positioning(
        application_id: int, conn: Annotated[Connection, Depends(get_db)]
    ) -> ClaudeJob:
        if get_job_application_detail(conn, application_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        try:
            job_id = submit_generate_positioning(conn, queue, application_id)
        except JobStepNotReady as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
            ) from error
        return _job_or_404(conn, job_id)

    @app.post(
        "/job-applications/{application_id}/positioning/clear",
        response_model=JobApplicationDetail,
        dependencies=[Depends(require_token)],
    )
    def clear_positioning_route(
        application_id: int, conn: Annotated[Connection, Depends(get_db)]
    ) -> JobApplicationDetail:
        """Positioning analysis's Edit dialog "Clear all" (D-208) - not a PATCH, since match_score
        and the breakdown document aren't columns an Edit form may touch (job_applications.py's
        _EDITABLE_COLUMNS)."""
        detail = clear_positioning(conn, files_root, application_id)
        if detail is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return detail

    @app.post(
        "/job-applications/{application_id}/application-history/generate",
        response_model=ClaudeJob,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_token)],
    )
    def generate_application_history(
        application_id: int, conn: Annotated[Connection, Depends(get_db)]
    ) -> ClaudeJob:
        if get_job_application_detail(conn, application_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        try:
            job_id = submit_generate_application_history(conn, queue, application_id)
        except JobStepNotReady as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
            ) from error
        return _job_or_404(conn, job_id)

    @app.post(
        "/job-applications/{application_id}/tailored-cv/generate",
        response_model=ClaudeJob,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_token)],
    )
    def generate_tailored_cv(
        application_id: int, conn: Annotated[Connection, Depends(get_db)]
    ) -> ClaudeJob:
        if get_job_application_detail(conn, application_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        try:
            job_id = submit_generate_tailored_cv(conn, queue, application_id)
        except JobStepNotReady as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
            ) from error
        return _job_or_404(conn, job_id)

    @app.post(
        "/job-applications/{application_id}/cover-letter/generate",
        response_model=ClaudeJob,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_token)],
    )
    def generate_cover_letter(
        application_id: int, conn: Annotated[Connection, Depends(get_db)]
    ) -> ClaudeJob:
        if get_job_application_detail(conn, application_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        try:
            job_id = submit_generate_cover_letter(conn, queue, application_id)
        except JobStepNotReady as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
            ) from error
        return _job_or_404(conn, job_id)

    @app.post(
        "/job-applications/{application_id}/interview-prep/generate",
        response_model=ClaudeJob,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_token)],
    )
    def generate_interview_prep(
        application_id: int, conn: Annotated[Connection, Depends(get_db)]
    ) -> ClaudeJob:
        if get_job_application_detail(conn, application_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        try:
            job_id = submit_generate_interview_prep(conn, queue, application_id)
        except JobStepNotReady as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
            ) from error
        return _job_or_404(conn, job_id)

    @app.get(
        "/job-applications/{application_id}/revise/{section_kind}/turns",
        response_model=list[JobReviseTurnView],
        dependencies=[Depends(require_token)],
    )
    def job_revise_turns_route(
        application_id: int, section_kind: str, conn: Annotated[Connection, Depends(get_db)]
    ) -> list[JobReviseTurnView]:
        if get_job_application_detail(conn, application_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        if section_kind not in SECTION_KINDS:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return [
            _job_revise_turn_view(queue, conn, turn)
            for turn in turns_for_section(conn, application_id, section_kind)
        ]

    @app.post(
        "/job-applications/{application_id}/revise/{section_kind}/turns",
        response_model=JobReviseTurnView,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_token)],
    )
    def start_job_revise_turn(
        application_id: int,
        section_kind: str,
        body: JobReviseTurnCreate,
        conn: Annotated[Connection, Depends(get_db)],
    ) -> JobReviseTurnView:
        if get_job_application_detail(conn, application_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        if section_kind not in SECTION_KINDS:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        try:
            job_id = submit_job_revise_turn(
                conn,
                queue,
                application_id,
                section_kind,
                body.message,
                body.attachment_job_file_id,
            )
        except JobReviseNotReady as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
            ) from error
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
            ) from error
        turn = job_revise_turn_for_job(conn, job_id)
        if turn is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return _job_revise_turn_view(queue, conn, turn)

    @app.post("/runs/check", response_model=RunResult, dependencies=[Depends(require_token)])
    def run_check(conn: Annotated[Connection, Depends(get_db)]) -> RunResult:
        """Checks whichever backend and model are currently selected (D-195, D-206) - the same
        one the next queued job would actually use."""
        backend = get_settings(conn).backend
        active = runner if backend == "claude_code" else codex_runner
        if active is None:
            raise HTTPException(status_code=400, detail="Codex is not installed.")
        return active.run(CHECK_PROMPT)

    @app.get(
        "/llm-app/status",
        response_model=dict[str, LlmAppStatus],
        dependencies=[Depends(require_token)],
    )
    def llm_app_status_route() -> dict[str, LlmAppStatus]:
        """Whether each backend's desktop app is installed (D-210) - checked fresh each call,
        the same way auth-status checks each backend's CLI fresh rather than caching it."""
        return llm_app_status()

    @app.post("/llm-app/open", response_model=LlmAppOpened, dependencies=[Depends(require_token)])
    def open_llm_app(conn: Annotated[Connection, Depends(get_db)]) -> LlmAppOpened:
        """Rebuilds the full-data export and launches it in whichever desktop app the
        selected backend (D-195) points at (D-202, D-210)."""
        backend = get_settings(conn).backend
        if not llm_app_status()[backend].installed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="That backend's desktop app does not appear to be installed.",
            )
        bundle_root = export_llm_bundle(conn, db_path.parent)
        link = LLM_APP_DEEP_LINKS[backend].format(
            prompt=quote(LLM_APP_PROMPT), path=quote(str(bundle_root))
        )
        webbrowser.open(link)
        return LlmAppOpened(backend=backend, bundle_path=str(bundle_root))

    @app.get("/claude-jobs", response_model=list[ClaudeJob], dependencies=[Depends(require_token)])
    def claude_jobs(conn: Annotated[Connection, Depends(get_db)]) -> list[ClaudeJob]:
        return [_with_live_text(queue, job) for job in list_claude_jobs(conn)]

    @app.post(
        "/claude-jobs/{job_id}/resume",
        response_model=ClaudeJob,
        dependencies=[Depends(require_token)],
    )
    def resume_claude_job(job_id: int, conn: Annotated[Connection, Depends(get_db)]) -> ClaudeJob:
        if not queue.resume(conn, job_id):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Not paused.")
        return _with_live_text(queue, _job_or_404(conn, job_id))

    @app.get(
        "/claude-jobs/{job_id}/prompts/{position}",
        response_model=PromptExchange,
        dependencies=[Depends(require_token)],
    )
    def claude_job_exchange(
        job_id: int, position: int, conn: Annotated[Connection, Depends(get_db)]
    ) -> PromptExchange:
        exchange = prompt_exchange(conn, job_id, position)
        if exchange is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return exchange

    @app.post(
        "/claude-jobs/{job_id}/cancel",
        response_model=ClaudeJob,
        dependencies=[Depends(require_token)],
    )
    def cancel_claude_job(job_id: int, conn: Annotated[Connection, Depends(get_db)]) -> ClaudeJob:
        if not queue.cancel(conn, job_id):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Already finished.")
        return _with_live_text(queue, _job_or_404(conn, job_id))

    @app.get(
        "/profile/files",
        response_model=list[ProfileFile],
        dependencies=[Depends(require_token)],
    )
    def profile_files(conn: Annotated[Connection, Depends(get_db)]) -> list[ProfileFile]:
        return list_profile_files(conn)

    @app.post(
        "/profile/files/{file_id}/open",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[Depends(require_token)],
    )
    def open_profile_file(file_id: int, conn: Annotated[Connection, Depends(get_db)]) -> None:
        path = profile_file_path(conn, db_path.parent, file_id)
        if path is None or not path.exists():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        open_in_default_app(path)

    @app.post(
        "/profile/files/{file_id}/reveal",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[Depends(require_token)],
    )
    def reveal_profile_file(file_id: int, conn: Annotated[Connection, Depends(get_db)]) -> None:
        path = profile_file_path(conn, db_path.parent, file_id)
        if path is None or not path.exists():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        reveal_in_file_manager(path)

    @app.get(
        "/profile/files/{file_id}/download",
        dependencies=[Depends(require_token)],
    )
    def download_profile_file(
        file_id: int, conn: Annotated[Connection, Depends(get_db)]
    ) -> FileResponse:
        path = profile_file_path(conn, db_path.parent, file_id)
        if path is None or not path.exists():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        name = profile_file_name(conn, file_id) or path.name
        return FileResponse(path, filename=name)

    @app.delete(
        "/profile/files/{file_id}",
        dependencies=[Depends(require_token)],
    )
    def remove_profile_file(file_id: int, conn: Annotated[Connection, Depends(get_db)]) -> None:
        try:
            deleted = delete_profile_file(conn, db_path.parent, file_id)
        except ProfileUploadError as error:
            raise HTTPException(status_code=error.status, detail=error.message) from error
        if deleted.generated:
            # The file was the readable copy of a generated document (D-84). Removing it should
            # remove the document too, not just leave it quietly in place (D-95).
            kind = PROMPT_KIND_FOR_OWN.get(deleted.kind)
            if kind is not None:
                clear_output(conn, kind)

    @app.get(
        "/profile/files/{file_id}/text",
        response_model=ProfileFileText,
        dependencies=[Depends(require_token)],
    )
    def profile_file_text_route(
        file_id: int, conn: Annotated[Connection, Depends(get_db)]
    ) -> ProfileFileText:
        text = profile_file_text(conn, file_id)
        if text is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return text

    @app.get("/profile/files/{file_id}/preview", dependencies=[Depends(require_token)])
    def profile_file_preview(
        file_id: int, conn: Annotated[Connection, Depends(get_db)]
    ) -> Response:
        path = profile_file_path(conn, db_path.parent, file_id)
        if path is None or not path.exists():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        try:
            preview = preview_for(path.name, path.read_bytes())
        except UnsupportedPreview as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
            ) from error
        content = (
            preview.content
            if isinstance(preview.content, bytes)
            else preview.content.encode("utf-8")
        )
        return Response(content=content, media_type=PREVIEW_MEDIA_TYPES[preview.kind])

    @app.get(
        "/profile/outputs",
        response_model=list[ProfileOutput],
        dependencies=[Depends(require_token)],
    )
    def profile_outputs(conn: Annotated[Connection, Depends(get_db)]) -> list[ProfileOutput]:
        return list_latest_outputs(conn)

    @app.post(
        "/profile/analysis",
        response_model=ClaudeJob,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_token)],
    )
    def start_profile_analysis(conn: Annotated[Connection, Depends(get_db)]) -> ClaudeJob:
        try:
            job_id = submit_profile_analysis(conn, queue, db_path.parent)
        except ProfileNotReady as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
            ) from error
        except ProfileBusy as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
        return _job_or_404(conn, job_id)

    @app.get(
        "/profile/revise/{output_kind}/turns",
        response_model=list[ReviseTurnView],
        dependencies=[Depends(require_token)],
    )
    def revise_turns_route(
        output_kind: str, conn: Annotated[Connection, Depends(get_db)]
    ) -> list[ReviseTurnView]:
        if output_kind not in PROMPT_KINDS:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return [_revise_turn_view(queue, conn, turn) for turn in turns_for_kind(conn, output_kind)]

    @app.post(
        "/profile/revise/{output_kind}/turns",
        response_model=ReviseTurnView,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_token)],
    )
    def start_revise_turn(
        output_kind: str, body: ReviseTurnCreate, conn: Annotated[Connection, Depends(get_db)]
    ) -> ReviseTurnView:
        if output_kind not in PROMPT_KINDS:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        try:
            job_id = submit_revise_turn(conn, queue, output_kind, body.message)
        except ProfileNotReady as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
            ) from error
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
            ) from error
        turn = turn_for_job(conn, job_id)
        if turn is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return _revise_turn_view(queue, conn, turn)

    @app.post(
        "/profile/files/{kind}",
        response_model=ProfileFile,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_token)],
    )
    async def upload_profile_file(kind: str, request: Request) -> ProfileFile:
        # The body is the file's bytes. Its name comes in a header, URL-encoded. The request
        # is async, so it opens its own connection: a SQLite connection must stay in one thread.
        name = unquote(request.headers.get("X-File-Name", ""))
        content = await request.body()
        conn = connect(db_path)
        try:
            return store_profile_file(conn, db_path.parent, kind, name, content)
        except ProfileUploadError as error:
            raise HTTPException(status_code=error.status, detail=error.message) from error
        finally:
            conn.close()

    return app


def _job_or_404(conn: Connection, job_id: int) -> ClaudeJob:
    job = get_claude_job(conn, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return job


def _require_master_cv_kind(conn: Connection, profile_file_id: int | None) -> None:
    """Shared by the Master CV selector (D-116) and Add Job's creation request
    (Agent/specs/intake-steps.md): None clears the selection, so only a given id is checked."""
    if profile_file_id is None:
        return
    row = conn.execute("SELECT kind FROM profile_files WHERE id = ?", (profile_file_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such file.")
    if row["kind"] != "master_cv":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="That file isn't a master CV."
        )


def _job_file_or_404(conn: Connection, files_root: Path, application_id: int, file_id: int) -> Path:
    """The on-disk path for one of a Job Application's own files, checking it actually belongs
    to that application (not just that the id exists) before handing back a path to read."""
    row = conn.execute(
        "SELECT job_application_id, stored_path FROM job_files WHERE id = ?", (file_id,)
    ).fetchone()
    if row is None or row["job_application_id"] != application_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    path = files_root / str(row["stored_path"])
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return path


def _with_live_text(queue: ClaudeJobQueue, job: ClaudeJob) -> ClaudeJob:
    """Fill in each running prompt's streamed-so-far text from the queue's live state (D-105)."""
    for prompt in job.prompts:
        if prompt.status == "running":
            prompt.live_text = queue.live_text(job.id, prompt.position)
    return job


def _revise_turn_view(queue: ClaudeJobQueue, conn: Connection, turn: ReviseTurn) -> ReviseTurnView:
    job = _job_or_404(conn, turn.claude_job_id)
    return ReviseTurnView(
        id=turn.id,
        message=turn.message,
        created_at=turn.created_at,
        job=_with_live_text(queue, job),
    )


def _job_revise_turn_view(
    queue: ClaudeJobQueue, conn: Connection, turn: JobReviseTurn
) -> JobReviseTurnView:
    job = _job_or_404(conn, turn.claude_job_id)
    return JobReviseTurnView(
        id=turn.id,
        message=turn.message,
        created_at=turn.created_at,
        job=_with_live_text(queue, job),
    )
