"""Route-level tests for Open Applications (D-248 to D-254): the FastAPI surface, not the
pipeline internals already covered by test_open_application_pipeline.py.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import llmjobtracker.app as app_module


def test_list_is_empty_on_a_new_database(client: TestClient) -> None:
    response = client.get("/open-applications")
    assert response.status_code == 200
    assert response.json() == []


def test_create_rejects_an_empty_request(client: TestClient) -> None:
    response = client.post("/open-applications", json={})
    assert response.status_code == 400


def test_create_with_a_research_item_creates_the_row(client: TestClient) -> None:
    response = client.post(
        "/open-applications",
        json={"research_items": [{"source_type": "text", "content": "Acme is hiring."}]},
    )
    assert response.status_code == 201
    body = response.json()
    assert "application_id" in body

    detail = client.get(f"/open-applications/{body['application_id']}").json()
    assert detail["status"] == "Identified"
    assert len(detail["status_history"]) == 1


def test_research_items_route_lists_what_was_saved(client: TestClient) -> None:
    created = client.post(
        "/open-applications",
        json={
            "research_items": [
                {"source_type": "text", "content": "Acme is hiring data analysts."},
                {"source_type": "text", "content": "Acme just raised a Series B."},
            ]
        },
    ).json()
    application_id = created["application_id"]

    response = client.get(f"/open-applications/{application_id}/research-items")

    assert response.status_code == 200
    items = response.json()
    assert len(items) == 2
    assert [item["position"] for item in items] == [1, 2]
    assert items[0]["content"] == "Acme is hiring data analysts."


def test_research_items_for_a_missing_application_404s(client: TestClient) -> None:
    response = client.get("/open-applications/999/research-items")
    assert response.status_code == 404


def test_intake_extract_reads_pasted_text(client: TestClient) -> None:
    response = client.post(
        "/open-applications/intake/extract",
        json={"items": [{"source_type": "text", "content": "Acme is hiring data analysts."}]},
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["extraction_status"] == "ok"
    assert body[0]["extracted_text"] == "Acme is hiring data analysts."


def test_intake_extract_rejects_too_many_items(client: TestClient) -> None:
    response = client.post(
        "/open-applications/intake/extract",
        json={"items": [{"source_type": "text", "content": f"item {i}"} for i in range(6)]},
    )
    assert response.status_code == 400


def test_intake_identity_queues_with_no_application(client: TestClient) -> None:
    started = client.post(
        "/open-applications/intake/identity",
        json={"text": "Acme is a talent pool for data analysts."},
    )
    assert started.status_code == 201
    assert started.json()["open_application_id"] is None


def test_intake_identity_result_for_an_unknown_job_404s(client: TestClient) -> None:
    assert client.get("/open-applications/intake/identity/999").status_code == 404


def test_create_with_only_manual_fields_is_accepted(client: TestClient) -> None:
    response = client.post("/open-applications", json={"target_name": "Acme"})
    assert response.status_code == 201


def test_get_a_missing_application_404s(client: TestClient) -> None:
    assert client.get("/open-applications/999").status_code == 404


def test_patch_updates_a_field(client: TestClient) -> None:
    created = client.post("/open-applications", json={"target_name": "Acme"}).json()
    response = client.patch(
        f"/open-applications/{created['application_id']}",
        json={"angle": "A mutual contact introduced me."},
    )
    assert response.status_code == 200
    assert response.json()["angle"] == "A mutual contact introduced me."


def test_patch_ignores_a_field_the_edit_model_does_not_declare(client: TestClient) -> None:
    """Pydantic drops a key the request body model doesn't declare before it ever reaches
    update_open_application, so this is a no-op PATCH (200, target_name unchanged) rather than
    the 400 a genuinely unknown *column* would raise if ever passed through by hand."""
    created = client.post("/open-applications", json={"target_name": "Acme"}).json()
    response = client.patch(
        f"/open-applications/{created['application_id']}", json={"match_score": 90}
    )
    assert response.status_code == 200
    assert response.json()["target_name"] == "Acme"


def test_status_history_replace_recomputes_status(client: TestClient) -> None:
    created = client.post("/open-applications", json={"target_name": "Acme"}).json()
    response = client.put(
        f"/open-applications/{created['application_id']}/status-history",
        json={
            "entries": [
                {"status": "Identified", "changed_at": "2026-10-01T00:00:00Z"},
                {"status": "Applied", "changed_at": "2026-10-05T00:00:00Z"},
            ]
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "Applied"


def test_status_history_replace_with_no_entries_400s(client: TestClient) -> None:
    created = client.post("/open-applications", json={"target_name": "Acme"}).json()
    response = client.put(
        f"/open-applications/{created['application_id']}/status-history", json={"entries": []}
    )
    assert response.status_code == 400


def test_delete_removes_the_application(client: TestClient) -> None:
    created = client.post("/open-applications", json={"target_name": "Acme"}).json()
    application_id = created["application_id"]
    assert client.delete(f"/open-applications/{application_id}").status_code == 204
    assert client.get(f"/open-applications/{application_id}").status_code == 404


def test_delete_a_missing_application_404s(client: TestClient) -> None:
    assert client.delete("/open-applications/999").status_code == 404


def test_upload_an_additional_file(client: TestClient) -> None:
    created = client.post("/open-applications", json={"target_name": "Acme"}).json()
    application_id = created["application_id"]
    response = client.post(
        f"/open-applications/{application_id}/files/other",
        headers={"X-File-Name": "notes.txt"},
        content=b"some notes",
    )
    assert response.status_code == 201
    file = response.json()
    assert file["kind"] == "other"

    preview = client.get(f"/open-applications/{application_id}/files/{file['id']}/preview")
    assert preview.status_code == 200

    removed = client.delete(f"/open-applications/{application_id}/files/{file['id']}")
    assert removed.status_code == 200


def test_reveal_shows_the_copy_in_the_file_manager(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = client.post("/open-applications", json={"target_name": "Acme"}).json()
    application_id = created["application_id"]
    file = client.post(
        f"/open-applications/{application_id}/files/other",
        headers={"X-File-Name": "notes.txt"},
        content=b"some notes",
    ).json()
    revealed: list[Path] = []
    monkeypatch.setattr(app_module, "reveal_in_file_manager", revealed.append)

    response = client.post(f"/open-applications/{application_id}/files/{file['id']}/reveal")

    assert response.status_code == 204
    assert len(revealed) == 1
    assert revealed[0].name == "notes.txt"


def test_reveal_of_a_missing_file_404s(client: TestClient) -> None:
    created = client.post("/open-applications", json={"target_name": "Acme"}).json()
    application_id = created["application_id"]

    response = client.post(f"/open-applications/{application_id}/files/999/reveal")

    assert response.status_code == 404


def test_upload_rejects_a_non_other_kind(client: TestClient) -> None:
    created = client.post("/open-applications", json={"target_name": "Acme"}).json()
    response = client.post(
        f"/open-applications/{created['application_id']}/files/tailored_cv",
        headers={"X-File-Name": "cv.docx"},
        content=b"not a real docx",
    )
    assert response.status_code == 400


def test_generate_cv_before_ready_400s(client: TestClient) -> None:
    created = client.post("/open-applications", json={"target_name": "Acme"}).json()
    response = client.post(f"/open-applications/{created['application_id']}/tailored-cv/generate")
    assert response.status_code == 400


def test_generate_cv_for_a_missing_application_404s(client: TestClient) -> None:
    assert client.post("/open-applications/999/tailored-cv/generate").status_code == 404


def test_revise_turns_round_trip_for_an_unready_section(client: TestClient) -> None:
    created = client.post("/open-applications", json={"target_name": "Acme"}).json()
    application_id = created["application_id"]
    listed = client.get(f"/open-applications/{application_id}/revise/tailored_cv/turns")
    assert listed.status_code == 200
    assert listed.json() == []

    started = client.post(
        f"/open-applications/{application_id}/revise/tailored_cv/turns",
        json={"message": "Reword the tagline"},
    )
    assert started.status_code == 400  # no Tailored CV yet to revise


def test_revise_turns_unknown_section_404s(client: TestClient) -> None:
    created = client.post("/open-applications", json={"target_name": "Acme"}).json()
    application_id = created["application_id"]
    response = client.get(f"/open-applications/{application_id}/revise/not_a_section/turns")
    assert response.status_code == 404
