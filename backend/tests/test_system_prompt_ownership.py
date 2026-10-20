import re
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1] / "app"
CLIENT_SYSTEM_PROMPT_READ = re.compile(
    r"(?:\.get\(\s*|\[\s*)['\"](?:systemPrompt|system_prompt)['\"]"
)


def test_backend_never_reads_a_client_supplied_system_prompt():
    violations = []

    for path in sorted(APP_ROOT.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        for match in CLIENT_SYSTEM_PROMPT_READ.finditer(source):
            line_number = source.count("\n", 0, match.start()) + 1
            violations.append(f"{path.relative_to(APP_ROOT)}:{line_number}")

    assert not violations, (
        "Backend code must own every system prompt; remove client-payload reads at: "
        + ", ".join(violations)
    )
