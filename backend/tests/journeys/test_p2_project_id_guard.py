"""H-2e-4: a project id taken from a request must pass the access seam first.

H-2R found three defects (F1 to F3) on routes that took the project id from a
request body, a form field or a header instead of the URL path. The guards
that existed then covered path parameters in ``strategy.py`` and the tool
executors only. This guard covers every route module.

**Where a project id comes from.** A function in ``backend/app/routes/*.py``
takes a project id (keys ``thread_id``, ``session_id``, ``project_id``, their
camelCase forms, ``X-Session-ID``, ``X-Thread-ID``, ``X-Project-ID``) when it
has a route path parameter of that name, or reads one of those keys
(``.get``, ``[...]``, ``.pop``) from a *request container*:

* ``request.args``, ``.form``, ``.values``, ``.headers``, ``.json``,
  ``.view_args``, ``request.get_json()`` and ``.to_dict()`` of any of them;
* a local name bound to a container by ``=``, tuple unpacking, an annotated
  assignment or ``:=``;
* a nested dict of a container (``data.get("context")``);
* the return value of a same-module helper that returns a container, alone or
  inside a tuple (``data, files = _payload()``);
* a same-module helper's parameter that a caller passes a container to,
  positionally or by keyword.

An id read inside a same-module helper that *returns* it (``tid = _tid()``)
makes the caller a function that takes a project id.

**What it must do with it.** Before anything else touches a project, the
function must call an approved seam, directly or through anything it calls
(resolved through imports across ``backend/app``), and pass that call the
request's id (or its container):

* ``project_scope.authorized_thread_scope``, ``authorized_export_scope``,
  ``readable_project_row``, ``scenarios_for_thread``;
* ``session_access.resolve_session_for_actor``;
* or a ``NAMED_WRAPPERS`` entry.

Calls inside nested functions, lambdas and constant-false branches do not
count. Nothing *unsafe* may run before that call: a personal-row loader, a
save, ``canonical_row``, a model entry point, a direct ``UserSession`` /
``Scorecard`` ORM query, or a call to any function that itself does one of
those before reaching a seam.

**Exceptions** are explicit: ``EXEMPTIONS`` (takes an id but touches no
project; whole function), ``ORDERING_EXEMPTIONS`` (names the exact unsafe
operations, with counts, that may precede the seam; everything else still
fails) and ``SAFE_LOADERS`` (read shims that filter by the access rule
themselves). Stale entries fail. The self-tests plant each bypass pattern the
H-2e-4 audit found, unsafe and protected.

What static analysis cannot prove (the seam's *result* being what is used,
dynamic dispatch, conditional seams around an existence probe) is covered by
the dynamic cells in ``test_p2_access_regression_net.py`` named in
``DYNAMIC_COVERAGE``.

Journeys (blueprint acceptance matrix): section 4, Nov 14 additions.
"""

import ast
import functools
import pathlib
import textwrap

import pytest

APP_ROOT = pathlib.Path(__file__).resolve().parents[2] / "app"

ID_KEYS = {
    "thread_id", "session_id", "project_id", "threadid", "sessionid", "projectid",
    "x-session-id", "x-thread-id", "x-project-id",
}
REQUEST_ATTRS = {"args", "form", "values", "headers", "json", "view_args"}
ROUTE_DECORATORS = {"route", "get", "post", "put", "patch", "delete"}
CONTAINER_METHODS = {"get", "pop", "copy", "to_dict", "setdefault"}
ORM_MODELS = {"UserSession", "Scorecard"}

APPROVED_SEAMS = {
    ("app.project_scope", "authorized_thread_scope"),
    ("app.project_scope", "authorized_export_scope"),
    ("app.project_scope", "readable_project_row"),
    ("app.project_scope", "scenarios_for_thread"),
    ("app.session_access", "resolve_session_for_actor"),
}

# Wrappers that authorize by a rule other than the five seams, each already
# approved and tested elsewhere.
NAMED_WRAPPERS = {
    ("app.decision_records", "can_read_record"):
        "P2e-C1 record-bound read: the record's own organization and project "
        "(record_project_row), not the active organization",
    ("app.decision_records", "can_write_record"):
        "P2e-C1 record-bound write, including the orphaned-record rule",
    ("app.routes.team", "_can_access_project"):
        "team page: can_read_session on the active organization's canonical "
        "row (_get_project_row, oldest first) with active membership required",
}

# Read shims that add a project row only when the access rule allows it.
# Calling one before the seam is not an unsafe read; it is not a seam either.
SAFE_LOADERS = {
    ("app.routes.sessions", "load_sessions_for_thread"):
        "the caller's own rows plus the canonical row only when can_read_session "
        "passes; endpoints still authorize through resolve_session_for_actor",
}

# Functions that take a project id but read no other member's project and
# write no project.
EXEMPTIONS = {
    ("app.routes.ai_agent", "readiness_audit"):
        "reads readiness from the caller's own attributed rows only "
        "(load_user_sessions); never another member's project, never writes",
    ("app.routes.billing", "get_checkout_session"):
        "session_id is a Stripe checkout session, not a project",
    ("app.routes.connectors", "get_connector_audit"):
        "the caller's own connector audit log, filtered by thread id",
    ("app.routes.connectors", "upsert_thread_sync"):
        "per-user sync profile keyed by thread id (H-2R I3); no project data",
    ("app.routes.connectors", "set_preferred_pm_tool"):
        "per-user sync profile keyed by thread id (H-2R I3); no project data",
    ("app.routes.monitoring", "connector_insights"):
        "the caller's own connector events, filtered by thread id",
    ("app.routes.pm_sync", "list_bindings"):
        "bindings owned by the caller (PmSyncBinding.user_id); personal by design",
    ("app.routes.sharing", "list_shares"):
        "share links owned by the caller, filtered by thread id",
    ("app.routes.decision_records", "search_records"):
        "record search filtered per record by can_read_record (decision_records.search)",
    ("app.routes.strategy", "get_ai_wbs_job"):
        "the caller's own PlanBuildJob row; reachability rechecked with load_sessions_for_thread "
        "(can_read_session); a stale-job restart re-enters _build_execution_plan, which "
        "authorizes with require_write",
}

_TEAM_ROW_LOOKUP = (
    "the active organization's canonical row (_get_project_row, oldest first; _auth_context "
    "has verified active membership), then _can_access_project before any field is read or written"
)

# The exact unsafe operations each function may run before its seam, with how
# many times. Any other unsafe operation before the seam still fails, and so
# does an extra call of a permitted one.
ORDERING_EXEMPTIONS = {
    ("app.routes.sessions", "save_session"): {
        "permits": {"canonical_row": 1},
        "reason": "create-or-update existence probe; an existing row is authorized with "
                  "resolve_session_for_actor(require_write) before any load or save (P1)",
    },
    ("app.routes.strategy", "analyze_project"): {
        "permits": {"canonical_row": 1},
        "reason": "existence probe; an existing project is authorized with "
                  "_thread_scope(require_write, pin) before its conversation is read or "
                  "the model runs (P2b)",
    },
    ("app.routes.strategy", "update_strategy_thread"): {
        "permits": {"canonical_row": 1},
        "reason": "existence probe; an organization row is authorized with "
                  "resolve_session_for_actor(require_write) before it is loaded (P2b)",
    },
    ("app.routes.ai_agent", "conversation_start"): {
        "permits": {"load_user_sessions": 1, "canonical_row": 1},
        "reason": "the caller's own rows (to spot a stale attribution row) and an existence "
                  "probe; an existing project is authorized with "
                  "resolve_session_for_actor(require_write) before any save, reservation "
                  "or model call (P2a)",
    },
    ("app.routes.team", "update_project_sharing"): {
        "permits": {"_get_project_row": 1},
        "reason": _TEAM_ROW_LOOKUP,
    },
    ("app.routes.team", "get_project_activity"): {
        "permits": {"_get_project_row": 1},
        "reason": _TEAM_ROW_LOOKUP,
    },
    ("app.routes.team", "get_project_comments"): {
        "permits": {"_get_project_row": 1},
        "reason": _TEAM_ROW_LOOKUP,
    },
    ("app.routes.team", "add_project_comment"): {
        "permits": {"_get_project_row": 1},
        "reason": _TEAM_ROW_LOOKUP,
    },
    ("app.routes.strategy", "adopt_scenario"): {
        "permits": {"_load_scenarios": 1},
        "reason": "only when no thread id is sent: searches the caller's own scenario data for "
                  "the scenario's thread, then _thread_scope(require_write) authorizes it before "
                  "any read or write (P2b)",
    },
}

UNSAFE_CALLS = {
    "load_user_sessions", "load_scenarios_data", "save_user_sessions",
    "save_scenarios_data", "save_project_scenarios_data", "canonical_row",
    "execute_customer_operation", "execute_customer_text_operation", "get_llm_client",
}

# Behavior static analysis cannot prove, and the dynamic cells that prove it.
DYNAMIC_COVERAGE = {
    "conditional seam after an existence probe (ORDERING_EXEMPTIONS)":
        "test_p2_access_regression_net.py::test_existence_probe_routes_follow_write_access",
    "the seam's result is the project used afterwards (F3 class)":
        "test_p2_access_regression_net.py::test_thread_reads_follow_read_access, "
        "::test_same_id_in_another_organization_never_reaches_this_one",
    "conflicting ids: which request field wins":
        "test_p2_access_regression_net.py::test_conflicting_ids_never_redirect_a_refused_write",
}


# --- Module index -------------------------------------------------------------

def _module_name(path):
    rel = path.relative_to(APP_ROOT.parent).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


class _Module:
    def __init__(self, name, tree):
        self.name = name
        self.tree = tree
        self.functions = {}
        self.imports = {}   # local name -> (module, attr or None)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.functions.setdefault(node.name, node)
            elif isinstance(node, ast.ImportFrom):
                source = node.module or ""
                if node.level:
                    base = name.split(".")[: -node.level]
                    source = ".".join(base + ([node.module] if node.module else []))
                for alias in node.names:
                    self.imports[alias.asname or alias.name] = (source, alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    self.imports[alias.asname or alias.name.split(".")[0]] = (alias.name, None)


@functools.lru_cache(maxsize=1)
def _real_index():
    modules = {}
    for path in sorted(APP_ROOT.rglob("*.py")):
        name = _module_name(path)
        modules[name] = _Module(name, ast.parse(path.read_text()))
    return modules


@functools.lru_cache(maxsize=1)
def _real_scan():
    modules = _real_index()
    return _violations(modules, _route_modules(modules))


def _index(sources=None):
    if sources is None:
        return dict(_real_index())
    modules = {}
    for name, source in sources.items():
        modules[name] = _Module(name, ast.parse(textwrap.dedent(source)))
    return modules


def _call_name(call):
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _call_targets(module, call):
    func = call.func
    if isinstance(func, ast.Name):
        if func.id in module.imports:
            source, attr = module.imports[func.id]
            return {(source, attr)} if attr is not None else set()
        if func.id in module.functions:
            return {(module.name, func.id)}
        return set()
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        owner = func.value.id
        if owner in module.imports:
            source, attr = module.imports[owner]
            return {(f"{source}.{attr}" if attr else source, func.attr)}
    return set()


def _falsy_constant(test):
    return isinstance(test, ast.Constant) and not test.value


def _truthy_constant(test):
    return isinstance(test, ast.Constant) and bool(test.value)


def _own_nodes(fn):
    """Nodes that run as part of this function: not nested defs, lambdas or
    classes, and not constant-false branches."""
    out = []
    stack = list(reversed(fn.body))
    while stack:
        node = stack.pop()
        out.append(node)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        if isinstance(node, (ast.If, ast.While)):
            stack.append(node.test)
            if not _falsy_constant(node.test):
                stack.extend(reversed(node.body))
            if not _truthy_constant(node.test):
                stack.extend(reversed(node.orelse))
            continue
        if isinstance(node, ast.IfExp):
            stack.append(node.test)
            if not _falsy_constant(node.test):
                stack.append(node.body)
            if not _truthy_constant(node.test):
                stack.append(node.orelse)
            continue
        stack.extend(reversed(list(ast.iter_child_nodes(node))))
    return out


def _own_calls(fn):
    return [n for n in _own_nodes(fn) if isinstance(n, ast.Call)]


def _unsafe_orm(node):
    return (isinstance(node, ast.Attribute) and node.attr == "query"
            and isinstance(node.value, ast.Name) and node.value.id in ORM_MODELS)


# --- Seam reachability and unsafe-first ---------------------------------------

def _analysis(modules):
    """``good``: functions that reach a seam or wrapper. ``unsafe_first``:
    functions that run an unsafe operation before their first seam-reaching
    call (or without one)."""
    graph = {}
    for module in modules.values():
        for fname, fn in module.functions.items():
            targets = set()
            for call in _own_calls(fn):
                targets |= _call_targets(module, call)
            graph[(module.name, fname)] = targets
    good = set(APPROVED_SEAMS) | set(NAMED_WRAPPERS)
    changed = True
    while changed:
        changed = False
        for key, targets in graph.items():
            if key not in good and targets & good:
                good.add(key)
                changed = True

    unsafe_first = set()
    changed = True
    while changed:
        changed = False
        for module in modules.values():
            for fname, fn in module.functions.items():
                key = (module.name, fname)
                if key in unsafe_first or key in SAFE_LOADERS or key in good and key in APPROVED_SEAMS:
                    continue
                seam_line = _first_seam_line(module, fn, good)
                for line, _what in _unsafe_ops(module, fn, unsafe_first):
                    if seam_line is None or line < seam_line:
                        unsafe_first.add(key)
                        changed = True
                        break
    return good, unsafe_first


def _first_seam_line(module, fn, good, require_id=None):
    lines = []
    for call in _own_calls(fn):
        if not (_call_targets(module, call) & good):
            continue
        if require_id is not None and not require_id(call):
            continue
        lines.append(call.lineno)
    return min(lines) if lines else None


def _unsafe_ops(module, fn, unsafe_first):
    """(line, label) for every unsafe operation this function runs itself."""
    ops = []
    for node in _own_nodes(fn):
        if isinstance(node, ast.Call):
            name = _call_name(node)
            targets = _call_targets(module, node)
            if targets & set(SAFE_LOADERS):
                continue
            if name in UNSAFE_CALLS:
                ops.append((node.lineno, name))
            elif targets & unsafe_first:
                ops.append((node.lineno, name))
        elif _unsafe_orm(node):
            ops.append((node.lineno, f"{node.value.id}.query"))
    return sorted(ops)


# --- Request-derived project ids ------------------------------------------------

def _is_route(fn):
    for d in fn.decorator_list:
        if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in ROUTE_DECORATORS:
            if d.func.attr == "route" or (d.args and isinstance(d.args[0], ast.Constant)
                                          and isinstance(d.args[0].value, str)):
                return True
    return False


def _key(node):
    """(base, key) for ``base.get(KEY)``, ``base.pop(KEY)`` or ``base[KEY]``."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
            and node.func.attr in ("get", "pop") and node.args and isinstance(node.args[0], ast.Constant):
        return node.func.value, node.args[0].value
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
        return node.value, node.slice.value
    return None, None


def _is_id_key(key):
    return isinstance(key, str) and key.lower() in ID_KEYS


class _Taint:
    """Per-module fixpoint: helper returns and helper parameters."""

    def __init__(self, module):
        self.module = module
        self.returns_container = set()
        self.returns_id = set()
        self.param_container = {}
        self.param_id = {}
        changed = True
        while changed:
            changed = False
            for fname, fn in module.functions.items():
                containers, ids = self.names(fn)
                for node in _own_nodes(fn):
                    if isinstance(node, ast.Return) and node.value is not None:
                        values = node.value.elts if isinstance(node.value, ast.Tuple) else [node.value]
                        if fname not in self.returns_container and any(
                                self.container(v, containers) for v in values):
                            self.returns_container.add(fname)
                            changed = True
                        if fname not in self.returns_id and any(self.has_id(v, containers, ids) for v in values):
                            self.returns_id.add(fname)
                            changed = True
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                            and node.func.id in module.functions:
                        helper = module.functions[node.func.id]
                        params = [a.arg for a in helper.args.args]
                        pairs = list(zip(params, node.args)) + [(k.arg, k.value) for k in node.keywords if k.arg]
                        for param, arg in pairs:
                            if self.container(arg, containers):
                                bucket = self.param_container.setdefault(helper.name, set())
                                if param not in bucket:
                                    bucket.add(param)
                                    changed = True
                            elif self.has_id(arg, containers, ids):
                                bucket = self.param_id.setdefault(helper.name, set())
                                if param not in bucket:
                                    bucket.add(param)
                                    changed = True

    def container(self, expr, containers):
        if isinstance(expr, ast.Name):
            return expr.id in containers
        if isinstance(expr, ast.Attribute):
            return isinstance(expr.value, ast.Name) and expr.value.id == "request" and expr.attr in REQUEST_ATTRS
        if isinstance(expr, ast.BoolOp):
            if any(self.container(v, containers) for v in expr.values):
                return True
            # ``data.get("context") or {}``: a nested dict of a container.
            return any(isinstance(v, ast.Dict) for v in expr.values) and any(
                self.nested(v, containers) for v in expr.values)
        if isinstance(expr, ast.IfExp):
            return self.container(expr.body, containers) or self.container(expr.orelse, containers)
        if isinstance(expr, ast.NamedExpr):
            return self.container(expr.value, containers)
        if isinstance(expr, ast.Call):
            func = expr.func
            if isinstance(func, ast.Attribute):
                if func.attr == "get_json" and isinstance(func.value, ast.Name) and func.value.id == "request":
                    return True
                if func.attr in ("copy", "to_dict") and self.container(func.value, containers):
                    return True
                # ``data.get("context", {})``
                if func.attr == "get" and len(expr.args) > 1 and isinstance(expr.args[1], ast.Dict):
                    return self.nested(expr, containers)
            if isinstance(func, ast.Name):
                if func.id in self.returns_container:
                    return True
                if func.id == "dict" and expr.args and self.container(expr.args[0], containers):
                    return True
        return False

    def nested(self, expr, containers):
        """``container.get(k)`` / ``container[k]`` for a non-id key."""
        base, key = _key(expr)
        if base is None or _is_id_key(key):
            return False
        return self.container(base, containers) or self.nested(base, containers)

    def id_read(self, node, containers):
        base, key = _key(node)
        return base is not None and _is_id_key(key) and (
            self.container(base, containers) or self.nested(base, containers))

    def has_id(self, expr, containers, ids):
        """True when ``expr`` IS the project id, or a string made from it
        (``str()``, ``.strip()``, ``or`` fallbacks), not anything looked up
        with it."""
        if self.id_read(expr, containers):
            return True
        if isinstance(expr, ast.Name):
            return expr.id in ids
        if isinstance(expr, ast.NamedExpr):
            return self.has_id(expr.value, containers, ids)
        if isinstance(expr, ast.BoolOp):
            return any(self.has_id(v, containers, ids) for v in expr.values)
        if isinstance(expr, ast.IfExp):
            return self.has_id(expr.body, containers, ids) or self.has_id(expr.orelse, containers, ids)
        if isinstance(expr, ast.Call):
            func = expr.func
            if isinstance(func, ast.Name):
                if func.id in self.returns_id:
                    return True
                if func.id == "str" and expr.args:
                    return self.has_id(expr.args[0], containers, ids)
            if isinstance(func, ast.Attribute) and func.attr in ("strip", "lower", "upper", "lstrip", "rstrip"):
                return self.has_id(func.value, containers, ids)
        return False

    def derived(self, fn, containers, ids):
        """Names computed from the project id or its container (rows looked
        up with it, records read for it): what a seam may be called with."""
        derived = set(ids) | set(containers)
        for _round in range(3):
            for node in _own_nodes(fn):
                if isinstance(node, (ast.For, ast.comprehension)) and self.mentions(node.iter, containers, derived):
                    derived |= {n.id for n in ast.walk(node.target) if isinstance(n, ast.Name)}
                    continue
                if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)) and getattr(node, "value", None) is not None:
                    if self.mentions(node.value, containers, derived):
                        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                        for target in targets:
                            derived |= {n.id for n in ast.walk(target) if isinstance(n, ast.Name)}
        return derived

    def mentions(self, expr, containers, names):
        for node in ast.walk(expr):
            if isinstance(node, ast.Name) and node.id in names:
                return True
            if self.id_read(node, containers) or self.container(node, containers):
                return True
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in self.returns_id:
                return True
        return False

    def names(self, fn):
        """Local names bound to a request container and to a project id."""
        containers = set(self.param_container.get(fn.name, ()))
        ids = set()
        if _is_route(fn):
            ids |= {a.arg for a in fn.args.args if _is_id_key(a.arg)}
        for _round in range(3):
            for node in _own_nodes(fn):
                targets, value = [], None
                if isinstance(node, ast.Assign):
                    targets, value = node.targets, node.value
                elif isinstance(node, ast.AnnAssign) and node.value is not None:
                    targets, value = [node.target], node.value
                elif isinstance(node, ast.NamedExpr):
                    targets, value = [node.target], node.value
                if value is None:
                    continue
                names = set()
                for target in targets:
                    for sub in ast.walk(target):
                        if isinstance(sub, ast.Name):
                            names.add(sub.id)
                if self.container(value, containers):
                    containers |= names
                elif self.has_id(value, containers, ids):
                    ids |= names
        return containers, ids


def _project_id_sources(fn, taint):
    """Where this function takes a project id (empty when it does not)."""
    containers, ids = taint.names(fn)
    found = []
    if _is_route(fn):
        found += [f"path:{a.arg}" for a in fn.args.args if _is_id_key(a.arg)]
    for node in _own_nodes(fn):
        if taint.id_read(node, containers):
            found.append(f"read:{ast.unparse(node)[:80]}")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in taint.returns_id:
            found.append(f"helper:{node.func.id}()")
    return found, containers, ids


def _violations(modules, route_modules, exemptions=None, ordering_exemptions=None):
    exemptions = EXEMPTIONS if exemptions is None else exemptions
    ordering_exemptions = ORDERING_EXEMPTIONS if ordering_exemptions is None else ordering_exemptions
    good, unsafe_first = _analysis(modules)
    out, checked, pre_seam = [], [], {}
    for name in route_modules:
        module = modules[name]
        taint = _Taint(module)
        for fname, fn in module.functions.items():
            sources, containers, ids = _project_id_sources(fn, taint)
            if not sources:
                continue
            # A helper that only extracts the id and returns it is checked at
            # its callers, which take the id from it.
            if fname in taint.returns_id and not _unsafe_ops(module, fn, unsafe_first):
                continue
            key = (name, fname)
            checked.append(key)
            if key in exemptions:
                continue

            derived = taint.derived(fn, containers, ids)

            def carries_id(call):
                args = list(call.args) + [k.value for k in call.keywords]
                return any(taint.mentions(a, containers, derived) for a in args)

            # A helper that reads the id but runs nothing unsafe hands the
            # decision to its caller, which is checked where it calls it.
            if not _is_route(fn) and not _unsafe_ops(module, fn, unsafe_first) \
                    and _first_seam_line(module, fn, good) is None:
                continue

            seam_line = _first_seam_line(module, fn, good, require_id=carries_id)
            if seam_line is None:
                why = ("access seam not called with the request's project id"
                       if _first_seam_line(module, fn, good) is not None else "no access seam")
                out.append((name, fname, why, sources))
                continue
            before = [(line, what) for line, what in _unsafe_ops(module, fn, unsafe_first) if line < seam_line]
            pre_seam[key] = before
            permits = dict((ordering_exemptions.get(key) or {}).get("permits", {}))
            unexcused = []
            for _line, what in before:
                if permits.get(what, 0) > 0:
                    permits[what] -= 1
                else:
                    unexcused.append(what)
            if unexcused:
                out.append((name, fname, f"unsafe before the access seam: {', '.join(unexcused)}", sources))
                continue
    return out, checked, pre_seam


def _route_modules(modules):
    return sorted(name for name in modules if name.startswith("app.routes.") and name != "app.routes")


# --- The guard -------------------------------------------------------------------

def test_every_request_project_id_reaches_the_access_seam_first():
    violations, checked, _pre = _real_scan()
    assert checked, "the guard found no project-id reads at all; its scan is broken"
    assert not violations, "\n".join(
        f"{module}.{fn}: {why} ({', '.join(src)})" for module, fn, why, src in violations
    )


@pytest.mark.parametrize("route", [
    ("app.routes.ai_agent", "conversation_start"),
    ("app.routes.ai_agent", "conversation_continue"),
    ("app.routes.ai_agent", "conversation_regenerate"),
    ("app.routes.ai_agent", "conversation_undo_mutations"),
    ("app.routes.ai_agent", "analyze_data"),
    ("app.routes.decision_shares", "_prepare"),
    ("app.routes.sharing", "_prepare"),
    ("app.routes.strategy", "analyze_project"),
    ("app.routes.sessions", "save_session"),
])
def test_body_and_helper_routes_are_in_the_inventory(route):
    """The routes that take the id from a body, a form or a helper are
    scanned, not silently skipped (audit finding 1: conversation/start)."""
    _violations_found, checked, _pre = _real_scan()
    assert route in checked, f"{route} takes a project id but the guard does not scan it"


def test_exemptions_wrappers_and_loaders_are_real_and_still_needed():
    """A stale entry hides nothing today but would hide a regression later."""
    modules = _index()
    _violations_found, checked, pre_seam = _real_scan()
    for key in EXEMPTIONS:
        assert key[0] in modules and key[1] in modules[key[0]].functions, f"unknown exemption {key}"
        assert key in checked, f"exemption {key} no longer reads a project id; remove it"
        fn = modules[key[0]].functions[key[1]]
        names = {_call_name(c) for c in ast.walk(fn) if isinstance(c, ast.Call)}
        assert not names & {
            "save_user_sessions", "save_scenarios_data", "save_project_scenarios_data",
            "execute_customer_operation", "execute_customer_text_operation", "get_llm_client",
        }, (key, "an exempted function saves or calls the model")
    for key, entry in ORDERING_EXEMPTIONS.items():
        assert key in checked, f"ordering exemption {key} no longer reads a project id; remove it"
        assert set(entry) == {"permits", "reason"} and entry["permits"], key
        counts = {}
        for _line, what in pre_seam[key]:
            counts[what] = counts.get(what, 0) + 1
        assert counts == entry["permits"], (
            f"ordering exemption {key} permits {entry['permits']} but the code runs {counts} "
            "before its seam; narrow or remove the entry")
    for key in list(NAMED_WRAPPERS) + list(SAFE_LOADERS):
        assert key[0] in modules and key[1] in modules[key[0]].functions, f"unknown entry {key}"


def test_named_wrappers_and_safe_loaders_check_access_themselves():
    modules = _index()

    def calls(module_name, fname):
        return {_call_name(c) for c in ast.walk(modules[module_name].functions[fname]) if isinstance(c, ast.Call)}

    assert {"record_project_row", "active_membership_for_user"} <= calls("app.decision_records", "can_read_record")
    assert {"can_read_record", "can_write_session"} <= calls("app.decision_records", "can_write_record")
    assert "can_read_session" in calls("app.routes.team", "_can_access_project")
    assert {"can_read_session", "is_hidden_for"} <= calls("app.routes.sessions", "load_sessions_for_thread")


def test_every_input_location_in_the_route_modules_is_scanned():
    modules = _index()
    seen = set()
    for name in _route_modules(modules):
        module = modules[name]
        taint = _Taint(module)
        for fn in module.functions.values():
            sources, _c, _i = _project_id_sources(fn, taint)
            for source in sources:
                if source.startswith("read:request."):
                    seen.add("request." + source.split("request.", 1)[1].split(".", 1)[0].split("[", 1)[0])
                else:
                    seen.add(source.split(":", 1)[0])
    for location in ("path", "read", "request.args", "request.form", "request.headers"):
        assert location in seen, f"no {location} project-id read found; the scan regressed"


def test_dynamic_coverage_pointers_exist():
    import re

    here = pathlib.Path(__file__).resolve().parent
    for gap, pointer in DYNAMIC_COVERAGE.items():
        current = None
        for part in re.split(r",\s*", pointer):
            match = re.match(r"(test_[a-z0-9_]+\.py)?::(\w+)", part.strip())
            assert match, (gap, part)
            if match.group(1):
                current = here / match.group(1)
            assert current is not None and f"def {match.group(2)}(" in current.read_text(), (gap, part)


# --- Self-test: the audit's 14 bypass patterns, unsafe and protected ----------------

PLANTED_LIB = {
    "app.project_scope": """
        def authorized_thread_scope(user_id, thread_id, require_write=False):
            return None, {}, None
    """,
    "app.routes.sessions": """
        def load_user_sessions(user_id):
            return {}

        def canonical_row(user, thread_id):
            return None
    """,
    "app.models": """
        class UserSession:
            query = None
    """,
}

PLANTED_HEADER = """
    from flask import request
    from app.project_scope import authorized_thread_scope
    from app.routes.sessions import load_user_sessions, canonical_row
    from app.models import UserSession
"""

# name: (unsafe body, protected body). Each body is one module of routes and
# helpers; the guard must flag the unsafe one and pass the protected one.
BYPASSES = {
    "tuple-helper": ("""
        def _payload():
            if request.mimetype == "multipart/form-data":
                return request.form.to_dict(flat=True), []
            return request.get_json() or {}, []

        @bp.route("/start", methods=["POST"])
        def start():
            data, files = _payload()
            tid = str(data.get("thread_id") or "")
            return load_user_sessions("u").get(tid)
    """, """
        def _payload():
            return request.get_json() or {}, []

        @bp.route("/start", methods=["POST"])
        def start():
            data, files = _payload()
            tid = str(data.get("thread_id") or "")
            authorized_thread_scope("u", tid, require_write=True)
            return load_user_sessions("u").get(tid)
    """),
    "single-helper": ("""
        def _body():
            return request.get_json(silent=True) or {}

        @bp.route("/x", methods=["POST"])
        def x():
            data = _body()
            return load_user_sessions("u").get(data.get("session_id"))
    """, """
        def _body():
            return request.get_json(silent=True) or {}

        @bp.route("/x", methods=["POST"])
        def x():
            data = _body()
            authorized_thread_scope("u", data.get("session_id"))
            return load_user_sessions("u")
    """),
    "annotated": ("""
        @bp.route("/x", methods=["POST"])
        def x():
            data: dict = request.get_json()
            return load_user_sessions("u").get(data["thread_id"])
    """, """
        @bp.route("/x", methods=["POST"])
        def x():
            data: dict = request.get_json()
            authorized_thread_scope("u", data["thread_id"])
            return load_user_sessions("u")
    """),
    "walrus": ("""
        @bp.route("/x")
        def x():
            if (tid := request.args.get("thread_id")):
                return load_user_sessions("u").get(tid)
    """, """
        @bp.route("/x")
        def x():
            if (tid := request.args.get("thread_id")):
                authorized_thread_scope("u", tid)
                return load_user_sessions("u")
    """),
    "nested-dict": ("""
        @bp.route("/x", methods=["POST"])
        def x():
            data = request.get_json() or {}
            return load_user_sessions("u").get(data.get("context", {}).get("thread_id"))
    """, """
        @bp.route("/x", methods=["POST"])
        def x():
            data = request.get_json() or {}
            ctx = data.get("context") or {}
            authorized_thread_scope("u", ctx.get("thread_id"))
            return load_user_sessions("u")
    """),
    "keyword-helper": ("""
        def _act(user, *, body):
            return load_user_sessions(user).get(body.get("thread_id"))

        @bp.route("/x", methods=["POST"])
        def x():
            return _act("u", body=request.get_json() or {})
    """, """
        def _act(user, *, body):
            authorized_thread_scope(user, body.get("thread_id"))
            return load_user_sessions(user)

        @bp.route("/x", methods=["POST"])
        def x():
            return _act("u", body=request.get_json() or {})
    """),
    "view-args": ("""
        @bp.route("/x")
        def x():
            return load_user_sessions("u").get(request.view_args["thread_id"])
    """, """
        @bp.route("/x")
        def x():
            tid = request.view_args["thread_id"]
            authorized_thread_scope("u", tid)
            return load_user_sessions("u")
    """),
    "project-id-key": ("""
        @bp.route("/x")
        def x():
            return load_user_sessions("u").get(request.args.get("project_id"))
    """, """
        @bp.route("/x")
        def x():
            pid = request.args.get("project_id")
            authorized_thread_scope("u", pid)
            return load_user_sessions("u")
    """),
    "get-decorator": ("""
        @bp.get("/x/<thread_id>")
        def x(thread_id):
            return load_user_sessions("u").get(thread_id)
    """, """
        @bp.get("/x/<thread_id>")
        def x(thread_id):
            authorized_thread_scope("u", thread_id)
            return load_user_sessions("u")
    """),
    "dead-branch-seam": ("""
        @bp.route("/x/<thread_id>")
        def x(thread_id):
            if False:
                authorized_thread_scope("u", thread_id)
            return load_user_sessions("u").get(thread_id)
    """, """
        @bp.route("/x/<thread_id>")
        def x(thread_id):
            if True:
                authorized_thread_scope("u", thread_id)
            return load_user_sessions("u").get(thread_id)
    """),
    "nested-def-seam": ("""
        @bp.route("/x/<thread_id>")
        def x(thread_id):
            def _never():
                authorized_thread_scope("u", thread_id)
            return load_user_sessions("u").get(thread_id)
    """, """
        @bp.route("/x/<thread_id>")
        def x(thread_id):
            def _later():
                return thread_id
            authorized_thread_scope("u", thread_id)
            return load_user_sessions("u").get(_later())
    """),
    "seam-on-other-id": ("""
        @bp.route("/x", methods=["POST"])
        def x():
            data = request.get_json() or {}
            authorized_thread_scope("u", "t-something-else")
            return load_user_sessions("u").get(data.get("thread_id"))
    """, """
        @bp.route("/x", methods=["POST"])
        def x():
            data = request.get_json() or {}
            target = str(data.get("thread_id") or "").strip()
            authorized_thread_scope("u", target)
            return load_user_sessions("u").get(target)
    """),
    "orm-read-first": ("""
        @bp.route("/x/<thread_id>")
        def x(thread_id):
            row = UserSession.query.filter_by(session_id=thread_id).first()
            authorized_thread_scope("u", thread_id)
            return row
    """, """
        @bp.route("/x/<thread_id>")
        def x(thread_id):
            authorized_thread_scope("u", thread_id)
            return UserSession.query.filter_by(session_id=thread_id).first()
    """),
    "loading-helper-first": ("""
        def _load(thread_id):
            return load_user_sessions("u").get(thread_id)

        @bp.route("/x/<thread_id>")
        def x(thread_id):
            project = _load(thread_id)
            authorized_thread_scope("u", thread_id)
            return project
    """, """
        def _load(thread_id):
            return load_user_sessions("u").get(thread_id)

        @bp.route("/x/<thread_id>")
        def x(thread_id):
            authorized_thread_scope("u", thread_id)
            return _load(thread_id)
    """),
}


def _planted(body):
    return {**PLANTED_LIB, "app.routes.planted": textwrap.dedent(PLANTED_HEADER) + textwrap.dedent(body)}


def _flagged(body, **kwargs):
    violations, checked, _pre = _violations(
        _index(_planted(body)), ["app.routes.planted"],
        exemptions=kwargs.get("exemptions", {}), ordering_exemptions=kwargs.get("ordering", {}),
    )
    return {fn: why for _m, fn, why, _s in violations}, checked


def test_the_audit_listed_fourteen_bypass_patterns():
    assert len(BYPASSES) == 14


@pytest.mark.parametrize("pattern", sorted(BYPASSES))
def test_guard_flags_the_unsafe_form_of_each_bypass(pattern):
    flagged, _checked = _flagged(BYPASSES[pattern][0])
    assert flagged, f"{pattern}: the unsafe implementation was not detected"


@pytest.mark.parametrize("pattern", sorted(BYPASSES))
def test_guard_passes_the_protected_form_of_each_bypass(pattern):
    flagged, checked = _flagged(BYPASSES[pattern][1])
    assert not flagged, f"{pattern}: the protected implementation was flagged: {flagged}"
    assert any(module == "app.routes.planted" for module, _fn in checked), \
        f"{pattern}: the protected implementation was not scanned at all"


def test_an_id_returning_helper_makes_its_caller_responsible():
    unsafe = """
        def _tid():
            return request.args.get("thread_id") or request.headers.get("X-Session-ID")

        @bp.route("/x")
        def x():
            return load_user_sessions("u").get(_tid())
    """
    flagged, _checked = _flagged(unsafe)
    assert set(flagged) == {"x"}, flagged
    safe = unsafe.replace('            return load_user_sessions("u").get(_tid())',
                          '            tid = _tid()\n            authorized_thread_scope("u", tid)\n'
                          '            return load_user_sessions("u").get(tid)')
    assert _flagged(safe)[0] == {}


def test_an_exemption_silences_only_its_own_function():
    body = BYPASSES["project-id-key"][0] + BYPASSES["get-decorator"][0].replace("def x(", "def y(")
    flagged, _checked = _flagged(body, exemptions={("app.routes.planted", "x"): "test"})
    assert set(flagged) == {"y"}, flagged


# --- Self-test: ordering exemptions are narrow ---------------------------------------

PROBE_ROUTE = """
    from app.routes.sessions import load_user_sessions, canonical_row
    from app.project_scope import authorized_thread_scope

    @bp.route("/x", methods=["POST"])
    def probe():
        data = request.get_json() or {}
        tid = data.get("thread_id")
        existing = canonical_row("u", tid)
        __INSERT__
        if existing is not None:
            authorized_thread_scope("u", tid, require_write=True)
        return load_user_sessions("u")
"""
PROBE_EXEMPTION = {("app.routes.planted", "probe"): {"permits": {"canonical_row": 1}, "reason": "test"}}


def test_ordering_exemption_permits_exactly_the_named_probe():
    flagged, _checked = _flagged(PROBE_ROUTE.replace("__INSERT__", "pass"))
    assert "probe" in flagged, "without the exemption the probe must be flagged"
    flagged, _checked = _flagged(PROBE_ROUTE.replace("__INSERT__", "pass"), ordering=PROBE_EXEMPTION)
    assert flagged == {}, flagged


@pytest.mark.parametrize("insert", [
    'load_user_sessions("u")',
    'canonical_row("u", tid)',
    'UserSession.query.filter_by(session_id=tid).first()',
    'get_llm_client()',
    '_loader(tid)',
])
def test_ordering_exemption_still_catches_any_other_unsafe_operation(insert):
    """Audit finding 2: an exemption names the operations it excuses. An
    unrelated unsafe call, an ORM read, a model call, a loading helper, or a
    second probe inserted before the seam is still a violation."""
    body = PROBE_ROUTE.replace("__INSERT__", insert) + """
    def _loader(tid):
        return load_user_sessions("u").get(tid)
    """
    flagged, _checked = _flagged(body, ordering=PROBE_EXEMPTION)
    assert "probe" in flagged and flagged["probe"].startswith("unsafe before the access seam"), (insert, flagged)


def test_real_ordering_exemptions_reject_an_inserted_unsafe_call():
    """The same holds for the real entries: inserting one extra unsafe call
    before the seam in each exempted function makes the guard fail."""
    modules = _index()
    for (module_name, fname) in ORDERING_EXEMPTIONS:
        source_path = APP_ROOT.parent / (module_name.replace(".", "/") + ".py")
        source = source_path.read_text()
        tree = ast.parse(source)
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == fname)
        first = fn.body[0]
        while isinstance(first, ast.Try):
            first = first.body[0]
        lines = source.splitlines()
        indent = lines[first.lineno - 1][: len(lines[first.lineno - 1]) - len(lines[first.lineno - 1].lstrip())]
        lines.insert(first.lineno - 1, f"{indent}load_scenarios_data('u')")
        mutated = dict(modules)
        mutated[module_name] = _Module(module_name, ast.parse("\n".join(lines)))
        mutated[module_name].imports = modules[module_name].imports
        violations, _checked, _pre = _violations(mutated, [module_name])
        assert (module_name, fname) in {(m, f) for m, f, _w, _s in violations}, \
            f"{module_name}.{fname}: an inserted unsafe call was excused by its ordering exemption"


@pytest.mark.parametrize("mutation", ["remove_seam_call", "rename_seam"])
def test_guard_fails_when_the_seam_call_is_removed(mutation):
    body = BYPASSES["tuple-helper"][1]
    if mutation == "remove_seam_call":
        body = body.replace('            authorized_thread_scope("u", tid, require_write=True)\n', "")
    else:
        body = body.replace("authorized_thread_scope(", "lookup_thread(")
    flagged, _checked = _flagged(body)
    assert "start" in flagged, flagged
