from lambda_function import evaluate_spans


def test_passes_a_successful_trace() -> None:
    result = evaluate_spans([{"status": "OK"}])
    assert result.label == "Pass"
    assert result.value == 1


def test_fails_a_terminal_error_trace() -> None:
    result = evaluate_spans([{"attributes": {"status": "ERROR"}}])
    assert result.label == "Fail"
    assert result.value == 0
