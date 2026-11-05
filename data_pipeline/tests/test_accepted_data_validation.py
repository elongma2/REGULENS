from data_pipeline.scripts.validate_accepted_data import validate_accepted_data


def test_accepted_data_audit_has_no_confirmed_errors_and_retains_pending_signoff():
    report = validate_accepted_data()
    assert report["errors"] == []
    assert report["classifications"]["SOURCE VERIFICATION REQUIRED"] == 1
    assert report["counts"]["candidate_identity_linkages"] == 1
    assert report["counts"]["accepted_identity_linkages"] == 2
    assert report["counts"]["json_files_checked"] > 20
