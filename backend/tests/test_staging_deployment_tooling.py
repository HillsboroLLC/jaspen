"""Repository-only checks for the fail-closed, operator-run staging deployment tooling."""

import importlib.util
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
STAGING_DIR = REPO_ROOT / "deploy" / "staging"
WRAPPER = STAGING_DIR / "jaspen-staging-deploy"
STAGE_RELEASE = STAGING_DIR / "stage-release.sh"
SMOKE = STAGING_DIR / "staging-smoke.sh"
CONFIG_CHECK = STAGING_DIR / "staging_config_check.py"
DATABASE_HELPER = STAGING_DIR / "staging_database.py"
BASH_SCRIPTS = (WRAPPER, STAGE_RELEASE, SMOKE)


def staging_files():
    """Tracked-style files in deploy/staging (no Python caches)."""
    return sorted(
        path
        for path in STAGING_DIR.iterdir()
        if path.is_file() and path.suffix != ".pyc" and "__pycache__" not in path.parts
    )

# Built from parts so this file never contains a literal key-shaped value.
TEST_SECRET_PREFIX = "sk_" + "test_"
LIVE_SECRET_PREFIX = "sk_" + "live_"


def text(path):
    return path.read_text(encoding="utf-8")


def code_lines(path):
    """Script lines without comments, for checks about what the code does."""
    return [line for line in text(path).splitlines() if not line.lstrip().startswith("#")]


@pytest.mark.parametrize("script", BASH_SCRIPTS, ids=lambda path: path.name)
def test_bash_scripts_are_valid_and_executable(script):
    result = subprocess.run(["bash", "-n", str(script)], check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert script.stat().st_mode & stat.S_IXUSR
    assert "set -euo pipefail" in text(script)


def test_wrapper_validates_exact_release_sha_and_loads_root_owned_config():
    wrapper = text(WRAPPER)
    assert '[[ "$1" =~ ^[0-9a-f]{40}$ ]]' in wrapper
    assert "readonly RELEASE_SHA_PATTERN='^[0-9a-f]{40}$'" in wrapper
    assert 'readonly CONFIG_FILE="/etc/jaspen-staging/deploy.conf"' in wrapper
    assert "stat -c '%u' \"${CONFIG_FILE}\"" in wrapper
    assert "status --porcelain --untracked-files=all" in wrapper
    assert "merge-base --is-ancestor \"${PREVIOUS_SHA}\" \"${RELEASE_SHA}\"" in wrapper
    assert "checkout --quiet --detach \"${RELEASE_SHA}\"" in wrapper
    assert "--no-index --find-links" in wrapper
    assert "bundle verify" in wrapper


@pytest.mark.parametrize("path", staging_files(), ids=lambda path: path.name)
def test_staging_tooling_never_dumps_environment_or_removes_runtime_data(path):
    body = "\n".join(code_lines(path))
    assert "printenv" not in body
    assert "set -x" not in body
    assert not re.search(r"\bgit\s+(?:clean|rm)\b", body)
    assert not re.search(r"\b(?:cat|less|more|head|tail)\b[^\n]*(?:\.env|ENV_FILE)", body)
    assert "--property=Environment " not in body


def test_quarantine_is_only_counted_never_listed_or_changed():
    lines = [line for line in code_lines(WRAPPER) if "QUARANTINE_DIR" in line]
    assert lines, "the preflight must check the quarantine directory"
    for line in lines:
        assert not re.search(r"\b(?:rm|mv|cp|ls|cat|tar|chmod|chown)\b", line), line
    count_lines = [line for line in lines if "find " in line]
    assert count_lines and all("-printf '.'" in line and "wc -c" in line for line in count_lines)
    for path in staging_files():
        if path.name != WRAPPER.name and path.suffix != ".md":
            assert "QUARANTINE" not in text(path) or path.name == "deploy.conf.example"


def test_migrations_need_explicit_flag_and_record_timestamp_before_migrating():
    wrapper = text(WRAPPER)
    assert '--allow-migrations' in wrapper
    assert 'MIGRATIONS_ALLOWED="true"' in wrapper
    refusal = wrapper.index('[[ "${MIGRATIONS_ALLOWED}" == "true" ]]')
    checkout = wrapper.index('git_app checkout --quiet --detach "${RELEASE_SHA}"')
    assert refusal < checkout, "pending migrations must be refused before anything changes"

    timestamp = wrapper.index('PRE_MIGRATION_UTC="$(date -u')
    record = wrapper.index('write_record "migrating"')
    migrate = wrapper.index('"${DEPLOY_ROOT}/backend/migrate_production.py"')
    counts = wrapper.index('d1_copied_users_check || after_checkout_failure "D1 copied users"')
    restart = wrapper.index('systemctl restart "${RUNTIME_UNIT}" || after_checkout_failure')
    health = wrapper.index("if ! wait_for_health; then")
    rollback = wrapper.index('code_rollback "G5 health check failed after restart"')
    assert timestamp < record < migrate < counts < restart < health < rollback


def test_migration_ignores_signals_until_it_completes():
    wrapper = text(WRAPPER)
    ignore = wrapper.index("trap '' HUP INT TERM\n      run_with_staging_env")
    migrate = wrapper.index('"${DEPLOY_ROOT}/backend/migrate_production.py"')
    restore = wrapper.index("install_deploy_traps\n      echo \"PASS G4 migrations applied\"")
    assert ignore < migrate < restore


def test_d1_check_runs_in_preflight_and_after_migrations():
    wrapper = text(WRAPPER)
    preflight = wrapper[wrapper.index("run_check() {"):wrapper.index('echo "PASS G2 staging isolation preflight"')]
    assert "d1_copied_users_check" in preflight
    assert "COPIED_USERS_CREATED_BEFORE_UTC" in wrapper and "EXPECTED_COPIED_USERS" in wrapper
    assert "EXPECTED_ACTIVE_USERS" not in wrapper


def test_wrapper_rejects_artifact_files_not_listed_in_checksums():
    wrapper = text(WRAPPER)
    unlisted = wrapper.index('fail "artifacts contain files not listed in SHA256SUMS"')
    wheel_copy = wrapper.index("-name '*.whl' -exec cp -n")
    assert wrapper.index("sha256sum --quiet --strict -c SHA256SUMS") < unlisted < wheel_copy


def test_rollback_mode_checks_database_history_and_never_migrates():
    wrapper = text(WRAPPER)
    assert 'git_app merge-base --is-ancestor "${RELEASE_SHA}" "${PREVIOUS_SHA}"' in wrapper
    assert "db_helper in-history" in wrapper
    assert "schema stays at" in wrapper
    assert '[[ "$1" == "deploy" && "$5" == "--allow-migrations" ]]' in wrapper
    assert "Database changes are NOT rolled back" in wrapper


def test_health_check_uses_only_the_local_socket():
    wrapper = text(WRAPPER)
    curl_lines = [line for line in code_lines(WRAPPER) if "curl " in line]
    assert curl_lines and all("--unix-socket" in line for line in curl_lines)
    assert "jaspen.ai" not in wrapper
    assert "journalctl" in wrapper and "grep -cE 'Traceback|ERROR'" in wrapper


def test_staging_venv_keeps_the_r2_driver_extra():
    for path in (WRAPPER, STAGE_RELEASE):
        body = text(path)
        assert 'readonly STAGING_EXTRA_REQUIREMENT="psycopg2-binary==2.9.11"' in body
        assert "R-2" in body
    assert "greenlet" in text(STAGE_RELEASE)


def test_smoke_script_is_read_only():
    body = text(SMOKE)
    assert not re.search(r"\b(?:POST|PUT|PATCH|DELETE)\b", body)
    assert not re.search(r"(?:--data|--form|--upload-file|--json)", body)
    curl_calls = re.findall(r"curl [^\n]*", body)
    assert curl_calls and not any(re.search(r"\s-(?:d|F|T)\s", call) for call in curl_calls)
    methods = re.findall(r"-X\s+(\S+)", body)
    assert methods and set(methods) == {"OPTIONS"}
    assert "ls-remote origin refs/heads/main" in body
    assert "EXPECTED_MAIN_SHA (40-hex production main baseline) is required" in body
    assert 'echo "000"' not in body and "connection error" in body


def test_smoke_reports_connection_errors_and_requires_baselines(tmp_path):
    # Port 9 on localhost refuses connections: no network leaves this machine.
    dead = "http://127.0.0.1:9"
    result = subprocess.run(
        ["bash", str(SMOKE), dead, dead, dead, dead],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(tmp_path)},
    )
    assert result.returncode == 1
    output = result.stdout + result.stderr
    assert "000" not in output
    assert "FAIL G6 staging /api/v1/auth/me returned connection error, expected 401" in output
    assert "FAIL G7 production /health returned connection error" in output
    assert "FAIL G7 EXPECTED_MAIN_SHA (40-hex production main baseline) is required" in output
    assert "FAIL G7 production CSP header missing" in output
    assert "FAIL G7 production preflight from https://staging.jaspen.ai: connection error" in output
    assert "PASS" not in output


@pytest.mark.parametrize("path", staging_files(), ids=lambda path: path.name)
def test_staging_files_contain_no_host_specific_or_secret_values(path):
    body = text(path)
    assert not re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", body)
    assert "@gmail.com" not in body
    assert "sekki-prod" not in body
    assert not re.search(r"(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{4,}", body)
    assert not re.search(r"whsec_[A-Za-z0-9]{4,}", body)
    assert "BEGIN OPENSSH PRIVATE KEY" not in body
    assert "/Users/" not in body
    assert "doadmin" not in body
    assert "ondigitalocean" not in body


def test_stage_release_defaults_to_dry_run_and_gates_before_building():
    body = text(STAGE_RELEASE)
    assert "EXECUTE=0" in body
    assert re.search(r"--execute\) EXECUTE=1 ;;", body)
    assert body.count("EXECUTE=1") == 1
    assert "DRY RUN: nothing was copied" in body
    dry_run_exit = body.index("if (( EXECUTE == 0 )); then\n  echo\n  echo \"DRY RUN")
    first_remote = body.index('remote sudo -n "${REMOTE_WRAPPER}" --check')
    assert dry_run_exit < first_remote
    assert "--deploy-detached" in body and "--rollback-detached \"${PREVIOUS_SHA}\"" in body
    assert "print_rollback_command" in body
    assert "systemd-run" not in body and "journalctl" not in body
    gate = body.index('REF_GATE="$(release_ref_gate "${SHA}")"')
    ci = body.index("check-runs")
    build = body.index("bundle create")
    assert gate < ci < build
    assert "--local-suites-evidence" in body
    assert 'select(.app.slug == "github-actions")' in body
    assert "readonly REQUIRED_CI_JOBS=(backend backend-postgres frontend secret-scan)" in body
    assert "readonly ADVISORY_CI_JOBS=(security-audit)" in body
    assert 'echo "ci_advisory ${CI_ADVISORY}"' in body
    assert "artifacts directory must be outside the repository" in body


def _run_ci_gate(lines):
    body = text(STAGE_RELEASE)
    constants = "\n".join(re.findall(r"(?m)^readonly (?:REQUIRED|ADVISORY)_CI_JOBS=.*$", body))
    function = re.search(r"(?ms)^evaluate_ci_check_runs\(\) \{.*?^\}$", body).group(0)
    script = f"set -euo pipefail\n{constants}\n{function}\nevaluate_ci_check_runs\n"
    return subprocess.run(
        ["bash", "-c", script],
        input="".join(f"{line}\n" for line in lines),
        check=False,
        capture_output=True,
        text=True,
    )


REQUIRED_SUCCESS = [
    "completed success backend",
    "completed success backend-postgres",
    "completed success frontend",
    "completed success secret-scan",
]


def test_ci_gate_passes_when_required_jobs_succeed_and_warns_on_advisory_audit():
    result = _run_ci_gate([*REQUIRED_SUCCESS, "completed failure security-audit"])
    assert result.returncode == 0, result.stderr
    assert "WARNING advisory CI job security-audit is completed failure" in result.stdout
    assert "SUMMARY 5 GitHub Actions CI run(s)" in result.stdout

    clean = _run_ci_gate([*REQUIRED_SUCCESS, "completed success security-audit"])
    assert clean.returncode == 0
    assert "WARNING" not in clean.stdout


@pytest.mark.parametrize(
    "lines, reason",
    [
        (REQUIRED_SUCCESS[:-1], "required CI job missing or not successful: secret-scan"),
        ([*REQUIRED_SUCCESS[:-1], "completed failure secret-scan"], "not successful: secret-scan"),
        ([*REQUIRED_SUCCESS[1:], "in_progress null backend"], "not successful: backend"),
        ([*REQUIRED_SUCCESS, "completed failure unknown-new-job"], "not successful: unknown-new-job"),
        ([*REQUIRED_SUCCESS[:-1], "completed failure secret-scan", "completed failure security-audit"],
         "not successful: secret-scan"),
    ],
)
def test_ci_gate_stops_on_missing_required_or_unknown_failed_jobs(lines, reason):
    result = _run_ci_gate(lines)
    assert result.returncode == 1
    assert reason in result.stderr
    assert "SUMMARY" not in result.stdout


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def _throwaway_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "base")
    develop = _git(repo, "rev-parse", "HEAD")
    _git(repo, "update-ref", "refs/remotes/origin/develop", develop)
    _git(repo, "checkout", "-q", "-b", "staging")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "staging only")
    staging_tip = _git(repo, "rev-parse", "HEAD")
    _git(repo, "update-ref", "refs/remotes/origin/staging", staging_tip)
    _git(repo, "checkout", "-q", "-b", "feature", develop)
    _git(repo, "commit", "-q", "--allow-empty", "-m", "unreviewed")
    feature = _git(repo, "rev-parse", "HEAD")
    return repo, feature


def _stage_release(repo, *args, tmp_path):
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path),
        "JASPEN_STAGE_ARTIFACTS_DIR": str(tmp_path / "artifacts"),
        "JASPEN_STAGING_OPERATOR_CONFIG": str(tmp_path / "missing.conf"),
    }
    return subprocess.run(
        ["bash", str(STAGE_RELEASE), *args],
        cwd=repo,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def test_stage_release_refuses_a_sha_not_on_develop_or_staging(tmp_path):
    repo, feature = _throwaway_repo(tmp_path)
    result = _stage_release(repo, feature, "--no-fetch", tmp_path=tmp_path)
    assert result.returncode == 1
    assert "is not on origin/develop and is not the origin/staging tip" in result.stderr
    assert not (tmp_path / "artifacts").exists()


@pytest.mark.parametrize("bad_sha", ["abc123", "A" * 40, "g" * 40])
def test_stage_release_refuses_malformed_sha(tmp_path, bad_sha):
    repo, _ = _throwaway_repo(tmp_path)
    result = _stage_release(repo, bad_sha, "--no-fetch", tmp_path=tmp_path)
    assert result.returncode == 1
    assert "exactly 40 lowercase hex characters" in result.stderr


def test_stage_release_refuses_combining_dry_run_and_execute(tmp_path):
    repo, feature = _throwaway_repo(tmp_path)
    result = _stage_release(repo, feature, "--dry-run", "--execute", "--no-fetch", tmp_path=tmp_path)
    assert result.returncode == 1
    assert "cannot be combined" in result.stderr


# --- staging_config_check.py ------------------------------------------------

SYNTHETIC_SECRET = "synthetic-" + "jwt-secret-value"
SYNTHETIC_STRIPE = TEST_SECRET_PREFIX + "synthetic" + "stagingvalue"
STAGING_COOKIES = {
    "JWT_ACCESS_COOKIE_NAME": "jaspen_staging_access",
    "JWT_ACCESS_CSRF_COOKIE_NAME": "staging_csrf_access_token",
    "GOOGLE_MFA_PENDING_COOKIE_NAME": "jaspen_staging_mfa_pending",
    "SSO_STATE_COOKIE_NAME": "jaspen_staging_sso_state",
}


def _staging_env(tmp_path):
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path),
        "APP_ENV": "staging",
        "SENTRY_ENVIRONMENT": "staging",
        "DATABASE_URL": f"sqlite:///{tmp_path / 'synthetic.db'}",
        "JASPEN_DATABASE_URL_FILE": str(tmp_path / "no-database-url-file"),
        "SECRET_KEY": SYNTHETIC_SECRET,
        "JWT_SECRET_KEY": SYNTHETIC_SECRET,
        "STRIPE_SECRET_KEY": SYNTHETIC_STRIPE,
        "FRONTEND_BASE_URL": "https://staging.jaspen.ai",
        "CORS_ORIGINS": "https://staging.jaspen.ai",
        "ENABLE_FLASK_CORS": "false",
        "JWT_COOKIE_DOMAIN": ".jaspen.ai",
        "RATELIMIT_STORAGE_URI": "memory://",
        "REQUIRE_EMAIL_VERIFICATION": "false",
        **STAGING_COOKIES,
    }
    return env


def _run_app_check(env):
    return subprocess.run(
        [sys.executable, str(CONFIG_CHECK), "app", "--backend-dir", str(BACKEND_DIR)],
        cwd=BACKEND_DIR,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )


def _assert_no_synthetic_values(result):
    for value in (SYNTHETIC_SECRET, SYNTHETIC_STRIPE):
        assert value not in result.stdout
        assert value not in result.stderr


def test_config_check_passes_with_staging_values(tmp_path):
    result = _run_app_check(_staging_env(tmp_path))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "FAIL" not in result.stdout
    for name in STAGING_COOKIES:
        assert f"PASS cookie_name {name}" in result.stdout
    assert "PASS cors_origins_staging_only" in result.stdout
    assert "PASS flask_cors_disabled" in result.stdout
    _assert_no_synthetic_values(result)


def test_config_check_fails_with_production_cookie_names(tmp_path):
    env = _staging_env(tmp_path)
    for name in STAGING_COOKIES:
        env.pop(name)
    env["CORS_ORIGINS"] = "https://jaspen.ai,https://staging.jaspen.ai"
    result = _run_app_check(env)
    assert result.returncode == 1
    for name in STAGING_COOKIES:
        assert f"FAIL cookie_name {name}" in result.stdout
    assert "FAIL cors_origins_staging_only" in result.stdout
    _assert_no_synthetic_values(result)


def test_config_check_reports_only_an_error_class_when_the_app_cannot_build(tmp_path):
    env = _staging_env(tmp_path)
    env.pop("STRIPE_SECRET_KEY")
    result = _run_app_check(env)
    assert result.returncode == 2
    assert result.stdout.strip() == "FAIL app_factory_builds (RuntimeError)"
    _assert_no_synthetic_values(result)


def _write_env_file(path, values):
    path.write_text("".join(f"{name}={value}\n" for name, value in values.items()), encoding="utf-8")


def _run_env_audit(tmp_path, values, *, database_host="staging-fork.example.invalid", url_host=None):
    env_file = tmp_path / "backend.env"
    _write_env_file(env_file, values)
    url_file = tmp_path / "migration_database_url"
    url_file.write_text(
        f"postgresql://owner:{SYNTHETIC_SECRET}@{url_host or database_host}:25060/defaultdb\n",
        encoding="utf-8",
    )
    return subprocess.run(
        [
            sys.executable,
            "-I",
            str(CONFIG_CHECK),
            "env-file",
            "--env-file",
            str(env_file),
            "--database-host",
            database_host,
            "--url-file",
            str(url_file),
            "--forbidden-keys",
            "MAIL_PASSWORD ANTHROPIC_API_KEY",
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def _audit_values():
    return {
        "APP_ENV": "staging",
        "SENTRY_ENVIRONMENT": "staging",
        "STRIPE_SECRET_KEY": SYNTHETIC_STRIPE,
        "JWT_SECRET_KEY": SYNTHETIC_SECRET,
        "JWT_COOKIE_DOMAIN": ".jaspen.ai",
        "JASPEN_APP_DB_HOST": "staging-fork.example.invalid",
        "MAIL_PASSWORD": "",
        **STAGING_COOKIES,
    }


def test_env_audit_passes_for_isolated_staging_values(tmp_path):
    result = _run_env_audit(tmp_path, _audit_values())
    assert result.returncode == 0, result.stdout
    assert "PASS database_host_is_staging_fork (2 source(s))" in result.stdout
    _assert_no_synthetic_values(result)


def test_env_audit_names_live_keys_and_filled_secrets_without_values(tmp_path):
    values = _audit_values()
    live_value = LIVE_SECRET_PREFIX + "synthetic" + "livevalue"
    values["STRIPE_SECRET_KEY"] = live_value
    values["ANTHROPIC_API_KEY"] = SYNTHETIC_SECRET
    result = _run_env_audit(tmp_path, values, url_host="production-host.example.invalid")
    assert result.returncode == 1
    assert "FAIL no_live_stripe_values (STRIPE_SECRET_KEY)" in result.stdout
    assert "FAIL disabled_integration_secrets_empty (ANTHROPIC_API_KEY)" in result.stdout
    assert "FAIL database_host_is_staging_fork" in result.stdout
    assert live_value not in result.stdout + result.stderr
    assert "production-host" not in result.stdout + result.stderr
    _assert_no_synthetic_values(result)


# --- staging_database.py (pure Alembic logic, no database) --------------------

def _database_helper():
    spec = importlib.util.spec_from_file_location("staging_database", DATABASE_HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pending_and_history_logic_against_the_real_migrations():
    helper = _database_helper()
    script = helper.script_directory(str(BACKEND_DIR / "migrations"))
    (head,) = script.get_heads()
    parent = script.get_revision(head).down_revision
    assert isinstance(parent, str)

    assert helper.pending_revisions(script, [head]) == []
    assert helper.pending_revisions(script, [parent]) == [head]
    with pytest.raises(Exception):
        helper.pending_revisions(script, ["notarevision0"])

    # An older target head is in the newer database's history; a newer one is not.
    assert helper.heads_missing_from_history(script, [head], [parent]) == []
    assert helper.heads_missing_from_history(script, [parent], [head]) == [head]


# --- behavior of the post-checkout trap (stubbed commands) -------------------

TRAP_FUNCTIONS = (
    "report_database_state",
    "code_rollback",
    "after_checkout_failure",
    "on_deploy_exit",
    "on_deploy_signal",
    "install_deploy_traps",
)


def _wrapper_functions(names):
    body = text(WRAPPER)
    return "\n".join(
        re.search(rf"(?ms)^{name}\(\) \{{.*?^\}}$", body).group(0) for name in names
    )


def _run_trap_scenario(tmp_path, scenario, *, rollback_install_ok=True):
    log = tmp_path / "calls.log"
    stubs = f"""
set -euo pipefail
LOG={log}
PREVIOUS_SHA={"a" * 40}
MIGRATIONS_RAN=false; ALEMBIC_AFTER=""; PRE_MIGRATION_UTC=""; RUNTIME_UNIT=unit
CHECKED_OUT=false; DEPLOY_COMPLETED=false; ROLLBACK_STARTED=false; INTERRUPTED_BY=""
git_app() {{ echo "git $*" >>"$LOG"; [[ "$1" != rev-parse ]] || echo "$PREVIOUS_SHA"; }}
install_requirements() {{ echo "install" >>"$LOG"; {"true" if rollback_install_ok else "false"}; }}
systemctl() {{ echo "systemctl $*" >>"$LOG"; }}
wait_for_health() {{ echo "health" >>"$LOG"; }}
journal_error_count() {{ echo 0; }}
write_record() {{ echo "record $1" >>"$LOG"; }}
fail() {{ echo "FAIL: $1" >&2; exit 1; }}
"""
    script = stubs + _wrapper_functions(TRAP_FUNCTIONS) + "\ninstall_deploy_traps\n" + scenario + "\n"
    result = subprocess.run(["bash", "-c", script], check=False, capture_output=True, text=True, timeout=30)
    calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return result, calls


def test_unguarded_failure_after_checkout_rolls_back_and_records_interrupted(tmp_path):
    result, calls = _run_trap_scenario(tmp_path, "CHECKED_OUT=true\nfalse\necho unreachable")
    assert result.returncode != 0
    assert "unreachable" not in result.stdout
    assert calls.count(f"git checkout --quiet --detach {'a' * 40}") == 1
    assert calls[-1] == "record interrupted"


def test_signal_after_checkout_rolls_back_once_and_records_interrupted(tmp_path):
    result, calls = _run_trap_scenario(tmp_path, "CHECKED_OUT=true\nkill -HUP $$\nsleep 0.2\necho unreachable")
    assert result.returncode != 0
    assert "signal HUP" in result.stderr
    assert "unreachable" not in result.stdout
    assert [call for call in calls if call.startswith("record")] == ["record interrupted"]
    assert calls.count(f"git checkout --quiet --detach {'a' * 40}") == 1


def test_failed_rollback_is_recorded_as_rollback_failed(tmp_path):
    result, calls = _run_trap_scenario(tmp_path, "CHECKED_OUT=true\nfalse", rollback_install_ok=False)
    assert result.returncode != 0
    assert calls[-1] == "record rollback_failed"
    assert "systemctl restart unit" not in calls


def test_guarded_failure_rolls_back_exactly_once(tmp_path):
    result, calls = _run_trap_scenario(tmp_path, 'CHECKED_OUT=true\nafter_checkout_failure "pip check"')
    assert result.returncode == 1
    assert [call for call in calls if call.startswith("record")] == ["record rolled_back_code"]
    assert calls.count(f"git checkout --quiet --detach {'a' * 40}") == 1


@pytest.mark.parametrize("scenario", ["false", "CHECKED_OUT=true\nDEPLOY_COMPLETED=true\nexit 0"])
def test_no_rollback_before_checkout_or_after_completion(tmp_path, scenario):
    _, calls = _run_trap_scenario(tmp_path, scenario)
    assert calls == []


# --- D1 copied-user check (sqlite stand-in, no production data) --------------

def test_d1_copied_users_check_counts_only_copied_accounts():
    from sqlalchemy import create_engine, text as sql

    helper = _database_helper()
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sql(
            "CREATE TABLE users (id TEXT, created_at TEXT, deactivated_at TEXT, password_hash TEXT)"
        ))
        rows = [
            ("c1", "2026-11-01T00:00:00Z", "2026-11-20T00:00:00Z", "!disabled"),
            ("c2", "2026-11-02T00:00:00Z", "2026-11-20T00:00:00Z", "!disabled"),
            ("s1", "2026-11-23T00:00:00Z", None, "scrypt:32768:8:1$salt$hash"),
        ]
        for row in rows:
            connection.execute(sql("INSERT INTO users VALUES (:a, :b, :c, :d)"), dict(zip("abcd", row)))
    cutoff = "2026-11-22T00:00:00Z"

    counts = helper.copied_user_counts(engine, cutoff)
    assert counts == {"copied": 2, "copied_active": 0, "copied_valid_password_hashes": 0, "active_total": 1}
    assert helper.copied_users_pass(counts, 2)
    assert not helper.copied_users_pass(counts, 3)

    with engine.begin() as connection:
        connection.execute(sql("UPDATE users SET password_hash = 'pbkdf2:sha256:600000$s$h' WHERE id = 'c1'"))
        connection.execute(sql("UPDATE users SET deactivated_at = NULL WHERE id = 'c2'"))
    counts = helper.copied_user_counts(engine, cutoff)
    assert counts["copied_active"] == 1 and counts["copied_valid_password_hashes"] == 1
    assert not helper.copied_users_pass(counts, 2)


# --- detached runs: fixed systemd-run/journalctl lines, strict validation ------

def _pattern(name):
    return re.search(rf"(?m)^readonly {name}='([^']+)'$", text(WRAPPER)).group(1)


def _bash_matches(pattern, value):
    result = subprocess.run(
        ["bash", "-c", 'p="$1"; [[ "$2" =~ $p ]]', "_", pattern, value],
        check=False,
    )
    return result.returncode == 0


def test_unit_name_pattern_rejects_spaces_and_options():
    pattern = _pattern("UNIT_NAME_PATTERN")
    assert _bash_matches(pattern, "jaspen-staging-deploy-2222b8addbf9-20261123T034442Z")
    for bad in (
        "jaspen-staging-deploy-2222b8addbf9-20261123T034442Z --vacuum-size=1",
        "--setenv=BASH_ENV=/tmp/x",
        "-u ssh",
        "jaspen-staging-deploy-*",
        "jaspen-staging-other-2222b8addbf9-20261123T034442Z",
        "sshd.service",
    ):
        assert not _bash_matches(pattern, bad), bad


def test_release_argument_patterns_reject_spaces_and_options():
    sha, path = _pattern("RELEASE_SHA_PATTERN"), _pattern("ARTIFACT_PATH_PATTERN")
    assert _bash_matches(sha, "a" * 40)
    assert _bash_matches(path, "/srv/uploads/release/wheelhouse")
    for bad in ("-" + "a" * 39, "a" * 40 + " x", "--setenv=X"):
        assert not _bash_matches(sha, bad), bad
    for bad in ("--setenv=BASH_ENV=/tmp/x", "/srv/a b", "relative/path", "/srv/x;id"):
        assert not _bash_matches(path, bad), bad


def test_detached_and_log_modes_use_fixed_command_lines():
    wrapper = text(WRAPPER)
    systemd_runs = [line for line in code_lines(WRAPPER) if "systemd-run --unit=" in line]
    assert systemd_runs == [
        '  systemd-run --unit="${unit}" --wait --collect --quiet -p TimeoutStopSec=15min \\'
    ]
    assert '-- "${WRAPPER_PATH}" "--${mode}" "$@" || status=$?' in wrapper
    journal = [line.strip() for line in code_lines(WRAPPER) if "journalctl " in line]
    assert len(journal) == 2
    assert 'journalctl -u "$1" -f --no-pager -o cat' in journal
    assert any(line.startswith('count="$(journalctl --unit="${RUNTIME_UNIT}"') for line in journal)
    follow = wrapper[wrapper.index("follow_unit_log() {"):]
    assert follow.index("=~ ${UNIT_NAME_PATTERN}") < follow.index("journalctl -u")
    detached = wrapper[wrapper.index("run_detached() {"):]
    assert detached.index('validate_release_args "${mode}" "$@"') < detached.index("systemd-run")


def test_readme_sudoers_allows_only_the_wrapper():
    readme = text(STAGING_DIR / "README.md")
    block = re.search(r"```sudoers\n(.*?)```", readme, re.S).group(1)
    rules = [line.strip() for line in block.splitlines() if line.strip() and not line.strip().startswith("#")]
    assert rules and all(rule.endswith("NOPASSWD: /usr/local/sbin/jaspen-staging-deploy") for rule in rules)
    assert "systemd-run" not in block and "journalctl" not in block and "*" not in block
    assert "currently root" in readme


def test_failed_migration_reports_unchanged_schema_without_restore(tmp_path):
    script = (
        "set -euo pipefail\nMIGRATIONS_RAN=true; ALEMBIC_BEFORE=f3a5c7e9b1d2; PRE_MIGRATION_UTC=2026-11-23T00:00:00Z\n"
        + 'db_helper() { echo "$CURRENT"; }\n'
        + _wrapper_functions(["report_database_state"])
        + "\nreport_database_state\n"
    )
    same = subprocess.run(["bash", "-c", script], env={"CURRENT": "f3a5c7e9b1d2", "PATH": os.environ["PATH"]},
                          check=True, capture_output=True, text=True).stdout
    assert "stayed at f3a5c7e9b1d2; no database restore is needed" in same and "point-in-time" not in same
    changed = subprocess.run(["bash", "-c", script], env={"CURRENT": "a1b2c3d4e5f6", "PATH": os.environ["PATH"]},
                             check=True, capture_output=True, text=True).stdout
    assert "schema is at a1b2c3d4e5f6" in changed and "point-in-time restore" in changed


def test_exit_trap_ignores_signals_first_and_artifacts_reject_non_regular_files():
    wrapper = text(WRAPPER)
    exit_trap = wrapper[wrapper.index("on_deploy_exit() {"):]
    assert exit_trap.splitlines()[1].strip() == "local status=$?; trap '' HUP INT TERM"
    assert "find . ! -type d ! -type f" in wrapper
    assert "find . ! -type d ! -path ./SHA256SUMS" in wrapper


# --- G7 CORS and CSP checks with a fake curl (no network) --------------------

FAKE_CURL = r'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
method, origin, write_out, dump_headers, url = "GET", "-", None, False, None
i = 0
while i < len(args):
    a = args[i]
    if a == "-X":
        method = args[i + 1]; i += 2; continue
    if a == "-H":
        h = args[i + 1]
        if h.lower().startswith("origin:"):
            origin = h.split(":", 1)[1].strip()
        i += 2; continue
    if a == "-w":
        write_out = args[i + 1]; i += 2; continue
    if a == "-D":
        dump_headers = args[i + 1] == "-"; i += 2; continue
    if a in ("-o", "--max-time"):
        i += 2; continue
    if a.startswith("-"):
        i += 1; continue
    url = a; i += 1
responses = json.load(open(os.environ["FAKE_SCENARIO"]))
r = responses.get(f"{method} {url} {origin}") or responses.get(f"{method} {url} *")
if r is None:
    sys.stderr.write("curl: (7) Failed to connect\n")
    sys.exit(7)
if dump_headers:
    sys.stdout.write(f"HTTP/2 {r['status']}\r\n")
    for line in r.get("headers", []):
        sys.stdout.write(line.replace("{origin}", origin) + "\r\n")
    sys.stdout.write("\r\n")
if write_out:
    sys.stdout.write(write_out.replace("%{http_code}", str(r["status"])))
elif not dump_headers:
    sys.stdout.write(r.get("body", ""))
'''

FAKE_GIT = """#!/bin/sh
printf '%s\\trefs/heads/main\\n' "${FAKE_MAIN_SHA}"
"""

STAGING_API = "https://staging-api.invalid"
STAGING_WEB = "https://staging-web.invalid"
PROD_API = "https://prod-api.invalid"
PROD_WEB = "https://prod-web.invalid"
MAIN_SHA = "a" * 40
CSP_VALUE = "default-src 'self'"
R3_HEADERS = [
    "access-control-allow-origin: {origin}",
    "access-control-allow-credentials: true",
    "access-control-allow-methods: GET, " + ", ".join(["PO" + "ST", "PU" + "T", "PAT" + "CH", "DEL" + "ETE"]) + ", OPTIONS",
    "access-control-allow-headers: Authorization, Content-Type, X-Requested-With, X-Session-ID, X-CSRF-TOKEN, X-Jaspen-Idempotency-Key",
    "access-control-max-age: 86400",
]


def smoke_scenario(prod_preflight=None, prod_actual=None):
    staging_me = f"{STAGING_API}/api/v1/auth/me"
    prod_me = f"{PROD_API}/api/v1/auth/me"
    responses = {
        f"GET {STAGING_API}/health -": {
            "status": 200,
            "body": '{"database":"ok","status":"ok"}',
            "headers": ["x-robots-tag: noindex", "strict-transport-security: max-age=31536000"],
        },
        f"OPTIONS {staging_me} https://staging.jaspen.ai": {
            "status": 204,
            "headers": ["access-control-allow-origin: https://staging.jaspen.ai"],
        },
        f"OPTIONS {staging_me} *": {"status": 204, "headers": []},
        f"GET {STAGING_WEB} -": {"status": 302},
        f"GET {PROD_API}/health -": {"status": 200},
        f"GET {PROD_WEB} -": {"status": 200, "headers": [f"content-security-policy: {CSP_VALUE}"]},
        f"GET {prod_me} *": prod_actual or {"status": 401, "headers": []},
        f"OPTIONS {prod_me} *": prod_preflight or {"status": 204, "headers": R3_HEADERS},
    }
    for path in ("/api/v1/auth/me", "/api/v1/billing/status", "/api/v1/admin/capabilities"):
        responses[f"GET {STAGING_API}{path} -"] = {"status": 401}
    return responses


def run_smoke(tmp_path, scenario, csp_sha=None, extra_env=None):
    import hashlib
    import json

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name, body in (("curl", FAKE_CURL), ("git", FAKE_GIT)):
        stub = bin_dir / name
        stub.write_text(body, encoding="utf-8")
        stub.chmod(0o755)
    scenario_file = tmp_path / "scenario.json"
    scenario_file.write_text(json.dumps(scenario), encoding="utf-8")
    env = {
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        "HOME": str(tmp_path),
        "FAKE_SCENARIO": str(scenario_file),
        "FAKE_MAIN_SHA": MAIN_SHA,
        "EXPECTED_MAIN_SHA": MAIN_SHA,
        "PROD_CSP_SHA256": csp_sha or hashlib.sha256(CSP_VALUE.encode()).hexdigest(),
    }
    env.update(extra_env or {})
    result = subprocess.run(
        ["bash", str(SMOKE), STAGING_API, STAGING_WEB, PROD_API, PROD_WEB],
        check=False, capture_output=True, text=True, timeout=120, env=env,
    )
    return result.returncode, result.stdout + result.stderr


def test_smoke_accepts_only_the_documented_r3_preflight(tmp_path):
    code, output = run_smoke(tmp_path, smoke_scenario())
    assert code == 0, output
    assert "FAIL" not in output
    for origin in ("https://staging.jaspen.ai", "https://unrelated-origin.example"):
        assert f"PASS G7 production actual response from {origin} grants no allow-origin (401)" in output
        assert f"WARN G7 KNOWN R-3 (not resolved): production preflight echoes {origin}" in output
    assert "PASS G7 production CSP sha256" in output


def test_smoke_passes_and_flags_removal_when_r3_is_no_longer_observed(tmp_path):
    code, output = run_smoke(tmp_path, smoke_scenario(prod_preflight={"status": 204, "headers": []}))
    assert code == 0, output
    assert "PASS G7 production preflight from https://staging.jaspen.ai returns no allow-origin" in output
    assert "R-3 preflight reflection not observed" in output and "remove the R-3 exception" in output


@pytest.mark.parametrize(
    "case, preflight, actual, env, expected",
    [
        ("exception disabled", None, None, {"JASPEN_SMOKE_R3_EXCEPTION": "0"}, "(R-3 exception disabled)"),
        ("wildcard", {"status": 204, "headers": ["access-control-allow-origin: *"] + R3_HEADERS[1:]}, None, {}, "granted a different origin (*)"),
        ("other origin", {"status": 204, "headers": ["access-control-allow-origin: https://jaspen.ai"] + R3_HEADERS[1:]}, None, {}, "granted a different origin (https://jaspen.ai)"),
        ("repeated origin", {"status": 204, "headers": R3_HEADERS[:1] + R3_HEADERS}, None, {}, "returned 2 Access-Control-Allow-Origin values"),
        ("wider headers", {"status": 204, "headers": R3_HEADERS[:3] + ["access-control-allow-headers: *", R3_HEADERS[4]]}, None, {}, "changed header signature"),
        ("no max-age", {"status": 204, "headers": R3_HEADERS[:4]}, None, {}, "changed header signature"),
        ("actual grants", None, {"status": 401, "headers": ["access-control-allow-origin: {origin}"]}, {}, "actual response grants Access-Control-Allow-Origin"),
        ("actual not 401", None, {"status": 200, "headers": []}, {}, "returned 200, expected 401"),
        ("echo only", {"status": 204, "headers": R3_HEADERS[:1]}, None, {}, "changed header signature"),
        ("redirected preflight", {"status": 301, "headers": R3_HEADERS}, None, {}, "status 301, expected 204 or 200"),
    ],
)
def test_smoke_fails_closed_on_production_cors_changes(tmp_path, case, preflight, actual, env, expected):
    code, output = run_smoke(tmp_path, smoke_scenario(prod_preflight=preflight, prod_actual=actual), extra_env=env)
    assert code == 1, (case, output)
    assert expected in output, (case, output)
    assert "STAGING SMOKE FAILED" in output
    # The second origin is always checked and reported (no silent abort).
    assert "G7 production" in output and "https://unrelated-origin.example" in output.split("G7", 1)[1], (case, output)


def test_smoke_reflection_is_not_excused_when_the_actual_check_fails(tmp_path):
    scenario = smoke_scenario()
    del scenario[f"GET {PROD_API}/api/v1/auth/me *"]
    code, output = run_smoke(tmp_path, scenario)
    assert code == 1
    assert "production actual response from https://staging.jaspen.ai: connection error" in output
    assert "reflects the origin and the actual response check did not pass" in output
    assert "KNOWN R-3" not in output


@pytest.mark.parametrize("baseline", ["1e7e557686c26b60", "5C20" + "0" * 60, ""])
def test_smoke_requires_a_full_lowercase_csp_sha256_baseline(tmp_path, baseline):
    import hashlib

    current = hashlib.sha256(CSP_VALUE.encode()).hexdigest()
    code, output = run_smoke(tmp_path, smoke_scenario(), csp_sha=baseline or None)
    if baseline:
        assert code == 1
        assert f"PROD_CSP_SHA256 must be the full 64-hex sha256 (current production CSP sha256 is {current})" in output
    else:
        assert code == 0, output


def test_smoke_fails_when_the_csp_changes(tmp_path):
    code, output = run_smoke(tmp_path, smoke_scenario(), csp_sha="0" * 64)
    assert code == 1
    assert "differs from the baseline" in output


def test_r3_signature_constant_matches_the_documented_headers():
    import hashlib

    lines = sorted(
        f"{h.split(':', 1)[0].lower()}: {h.split(':', 1)[1].strip()}"
        for h in R3_HEADERS[1:]
    )
    expected = hashlib.sha256("".join(line + "\n" for line in lines).encode()).hexdigest()
    assert f'readonly R3_PREFLIGHT_SIGNATURE_SHA256="{expected}"' in text(SMOKE)
    assert "readonly R3_EXCEPTION_DEFAULT=1" in text(SMOKE)
