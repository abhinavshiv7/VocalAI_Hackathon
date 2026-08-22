from app.services.knowledge import retrieve_target_knowledge


def test_lab_retrieval_is_target_scoped_and_contains_only_approved_paths():
    chunks = retrieve_target_knowledge("lab-web-01")

    assert {chunk["path"] for chunk in chunks} == {"/admin", "/api/status", "/api/debug"}
    assert retrieve_target_knowledge("unknown-target") == []
