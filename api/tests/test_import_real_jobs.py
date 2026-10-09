from pathlib import Path

from localjobtracker.import_real_jobs import import_job
from localjobtracker.job_applications import get_job_application_detail
from localjobtracker.storage import connect

LISTING_FIXTURES = (
    Path(__file__).parent.parent.parent / "tests" / "fixtures" / "synthetic" / "job_listing"
)


def test_import_job_extracts_a_listing_file_the_same_way_an_upload_does(
    db_path: Path, tmp_path: Path
) -> None:
    files_root = tmp_path / "files"
    conn = connect(db_path)
    try:
        import_job(
            conn,
            files_root,
            {
                "company": "Acme Corp",
                "role_title": "Data Analyst",
                "description": "A role.",
                "requirements": ["SQL"],
                "files": [{"kind": "listing", "source": str(LISTING_FIXTURES / "listing.pdf")}],
            },
        )
        detail = get_job_application_detail(conn, 1)
    finally:
        conn.close()

    assert detail is not None
    listing_files = [file for file in detail.files if file.kind == "listing"]
    assert len(listing_files) == 1
    assert listing_files[0].extraction_status == "ok"
