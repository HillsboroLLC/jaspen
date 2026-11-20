"""Prompt-version evidence for AI operations (P5b, gap AI-5).

Evidence only. Nothing here builds, edits, orders or sends a prompt.

Each AI operation records which prompt configuration produced it, so a
scorecard, plan or reply can be traced to the prompt code that was live.
A *prompt family* names the static material one kind of operation is built
from: the functions that hold the prompt text and decide which sections are
assembled, and the prompt constants. An entry is a name in the family's
module, or ``"module:name"`` for a symbol in another module. Every
module-level constant those symbols reference (in their own module, or
imported from ``app.*``) is included automatically and transitively, whatever
its name, so a schema block, a weights table or an enum set cannot escape.
The family's version is ``"<family>:<first 16 hex of SHA-256>"`` over that
material, listed symbols first, then the constants by module and name.

- Deterministic: the same deployed code gives the same version, on every
  worker and every restart. Never random, never a timestamp.
- Static parts only: per-turn context (project data, history, memory) is
  not hashed. Each symbol is hashed by its source text (a function from its
  first decorator to its end, a constant by every module-level statement that
  assigns it), never by a runtime ``repr``, so an unordered constant such as a
  ``set`` hashes the same on every worker. A comment or formatting edit in
  that source also changes the version (deliberate: it over-reports, never
  under-reports, for what is hashed).
- Coverage is enforced by test: every app function a family symbol calls is
  either in the family or on a reviewed list of non-prompt helpers.
- Computed once per process and cached (``warm_prompt_versions`` at app
  start), so it describes the code the process loaded, not a later file on
  disk.
- Failure-safe: if a version cannot be computed it is ``None`` and the
  operation simply carries no version. Evidence never fails an operation.
"""

from __future__ import annotations

import ast
import functools
import hashlib
import importlib.util
import logging

logger = logging.getLogger(__name__)

PROMPT_VERSION_KEY = 'prompt_version'
# Earlier versions of a retried idempotent operation, oldest first. Only
# written when a retry ran under a different prompt version than the attempt
# before it, so a version is never replaced silently.
PROMPT_VERSION_HISTORY_KEY = 'prompt_version_history'

_DIGEST_CHARS = 16

_AI_AGENT = 'app.routes.ai_agent'
_STRATEGY = 'app.routes.strategy'

# family -> (module, ordered symbols holding its static prompt material)
PROMPT_FAMILIES = {
    # The conversation turn: system prompt prefix, every section builder the
    # reply generators assemble, the tool definitions the model is given,
    # the decision-capture pass that runs inside the same turn, and the two
    # renderers in other modules whose framing text the sections include.
    'conversation': (_AI_AGENT, (
        '_SYSTEM_PROMPT_PREFIX',
        '_build_agent_system_prompt',
        '_original_intake_prompt_suffix',
        '_context_summary_prompt_suffix',
        '_intake_context_prompt_suffix',
        '_view_context_prompt_suffix',
        '_connector_context_prompt_suffix',
        '_jira_portfolio_prompt_suffix',
        '_cross_session_memory_prompt_suffix',
        '_organizational_memory_prompt_suffix',
        '_batch_promotion_prompt_suffix',
        '_scenario_modeling_prompt_suffix',
        '_monitoring_prompt_suffix',
        '_readiness_phase_prompt_suffix',
        '_decision_kit_prompt_suffix',
        '_scorecard_content_prompt_suffix',
        '_wbs_content_prompt_suffix',
        '_decision_facts_prompt_suffix',
        '_anthropic_tool_definitions',
        '_CAPTURE_SYSTEM_PROMPT',
        '_capture_pass_tool',
        '_rfp_subtype_question_needed',
        'app.jira_portfolio:ai_prompt_text',
        'app.jira_portfolio:ai_prompt_payload',
        'app.memory_context:render_memory_prompt',
    )),
    'scorecard': (_STRATEGY, (
        '_generate_jaspen_scorecard',
        '_scorecard_objective_guidance',
    )),
    'scorecard_batch': (_STRATEGY, (
        '_generate_batch_scorecards',
        '_generate_jaspen_scorecard',
        '_scorecard_objective_guidance',
    )),
    'execution_plan': (_STRATEGY, ('_generate_ai_wbs_suggestion', '_infer_wbs_planning_mode')),
    'scorecard_assistant': (_STRATEGY, ('scorecard_assistant', '_scorecard_objective_guidance')),
    'execution_assistant': (_STRATEGY, ('execution_assistant',)),
    'analysis_chat': (_STRATEGY, ('chat_with_analysis',)),
    'portfolio_analysis': (_STRATEGY, ('portfolio_scores_agent',)),
    'batch_ranking': (_AI_AGENT, ('_rank_batch_ideas_with_ai', '_batch_ranking_prompt_payload')),
    'batch_clarification': (_AI_AGENT, ('_reevaluate_batch_idea_with_ai', '_batch_ranking_prompt_payload')),
    'decision_kit_classification': (_AI_AGENT, ('_classify_decision_kit',)),
    'context_summarization': (_AI_AGENT, ('_summarize_conversation_segment',)),
    'user_memory_extraction': (_AI_AGENT, ('_MEMORY_EXTRACT_PROMPT', 'extract_and_update_user_memory')),
    'data_insight_text': (_AI_AGENT, ('_llm_data_insight_text',)),
    'knowledge_refresh': (_AI_AGENT, ('refresh_knowledge_signals',)),
    'connector_idea_generation': ('app.routes.connectors', ('generate_ideas_from_connector',)),
    'insights_analysis': ('app.routes.insights', ('_llm_analysis',)),
    'report_generation': ('app.routes.reports', ('_llm_report_markdown',)),
    'feedback_digest': ('app.feedback_digest', ('_anthropic_digest_text',)),
    'public_intake_chat': ('app.routes._public_intake_chat', (
        '_PUBLIC_SYSTEM_PROMPT',
        '_public_readiness_prompt_suffix',
        '_stream_ai_reply',
    )),
}


def _split(module_name, entry):
    if ':' in entry:
        other, name = entry.split(':', 1)
        return other, name
    return module_name, entry


class _Module:
    """One module's source and its top-level definitions, read once."""

    def __init__(self, name, source):
        self.name = name
        self.source = source
        self.tree = ast.parse(source)
        self.defs = {}       # functions and classes
        self.assigns = {}    # constant name -> [module-level statements]
        self.imports = {}    # local name -> (module, name), app.* only
        for node in self.tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self.defs[node.name] = node
            elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        self.assigns.setdefault(target.id, []).append(node)
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ImportFrom):
                base = resolve_import(name, node)
                if base and (base == 'app' or base.startswith('app.')):
                    for alias in node.names:
                        self.imports.setdefault(alias.asname or alias.name, (base, alias.name))

    def segment(self, node):
        first = min([node.lineno] + [item.lineno for item in getattr(node, 'decorator_list', [])])
        lines = self.source.splitlines(keepends=True)
        return ''.join(lines[first - 1:node.end_lineno])

    def material(self, name):
        if name in self.defs:
            return self.segment(self.defs[name])
        if name in self.assigns:
            return ''.join(self.segment(node) for node in self.assigns[name])
        raise KeyError(f'{self.name}:{name} is not a top-level definition')


def resolve_import(module_name, node):
    """The absolute module an ``ImportFrom`` in ``module_name`` reads from."""
    base = node.module or ''
    if node.level:
        package = module_name.split('.')
        if not _is_package(module_name):
            package = package[:-1]  # a plain module's package is its parent
        if node.level > 1:
            package = package[:len(package) - (node.level - 1)]
        base = '.'.join(package + ([base] if base else []))
    return base


def _spec(name):
    try:
        return importlib.util.find_spec(name)
    except (ImportError, AttributeError, ValueError):
        return None


def _is_module(name):
    return _spec(name) is not None


def _is_package(name):
    spec = _spec(name)
    return bool(spec and spec.submodule_search_locations)


def _module_source(module_name):
    spec = importlib.util.find_spec(module_name)
    if spec is None or not spec.origin:
        raise ModuleNotFoundError(module_name)
    with open(spec.origin, encoding='utf-8') as handle:
        return handle.read()


@functools.lru_cache(maxsize=None)
def _parsed_module(module_name):
    """A module's source, parsed once per process (it is read-only here)."""
    return _Module(module_name, _module_source(module_name))


def referenced_names(node):
    return [item.id for item in ast.walk(node) if isinstance(item, ast.Name)]


def family_material(family, sources=None):
    """``[(module:name, source text)]`` hashed for ``family``.

    ``sources`` maps a module name to replacement source text (tests use it to
    show that a source edit changes the version)."""
    sources = dict(sources or {})
    modules = {}

    def module(name):
        if name not in modules:
            modules[name] = _Module(name, sources[name]) if name in sources else _parsed_module(name)
        return modules[name]

    home, entries = PROMPT_FAMILIES[family]
    listed = [_split(home, entry) for entry in entries]
    material = [(f'{mod}:{name}', module(mod).material(name)) for mod, name in listed]

    constants = {}
    todo = list(listed)
    seen = set()
    while todo:
        mod, name = todo.pop()
        if (mod, name) in seen:
            continue
        seen.add((mod, name))
        source = module(mod)
        nodes = [source.defs[name]] if name in source.defs else source.assigns.get(name, [])
        for node in nodes:
            for ref in referenced_names(node):
                target = None
                if ref in source.assigns:
                    target = (mod, ref)
                elif ref in source.imports and ref not in source.defs:
                    other_mod, other_name = source.imports[ref]
                    try:
                        if other_name in module(other_mod).assigns:
                            target = (other_mod, other_name)
                    except (ModuleNotFoundError, OSError):
                        target = None
                if target and target not in listed and target not in constants:
                    constants[target] = module(target[0]).material(target[1])
                    todo.append(target)
    material.extend((f'{mod}:{name}', constants[(mod, name)]) for mod, name in sorted(constants))
    return material


def referenced_helpers(family):
    """``{listed symbol: sorted app callables/modules it references}`` that are
    not themselves in the family. Constants are not listed: they are hashed
    automatically. The coverage guard test classifies every entry."""
    home, entries = PROMPT_FAMILIES[family]
    listed = {_split(home, entry) for entry in entries}
    modules = {}

    def module(name):
        if name not in modules:
            modules[name] = _parsed_module(name)
        return modules[name]

    result = {}
    for mod, name in sorted(listed):
        source = module(mod)
        if name not in source.defs:
            continue
        found = set()
        for ref in referenced_names(source.defs[name]):
            if ref in source.assigns:
                continue
            if ref in source.defs:
                target = (mod, ref)
            elif ref in source.imports:
                other_mod, other_name = source.imports[ref]
                if _is_module(f'{other_mod}.{other_name}'):
                    target = (f'{other_mod}.{other_name}', '*')  # an imported module
                else:
                    try:
                        if other_name in module(other_mod).assigns:
                            continue  # a constant: hashed automatically
                    except (ModuleNotFoundError, OSError):
                        pass
                    target = (other_mod, other_name)
            else:
                continue
            if target not in listed:
                found.add(f'{target[0]}:{target[1]}')
        result[f'{mod}:{name}'] = sorted(found)
    return result


def compute_prompt_version(family, sources=None):
    """The version of ``family`` from its source now (uncached)."""
    digest = hashlib.sha256()
    for key, text in family_material(family, sources):
        digest.update(key.encode('utf-8'))
        digest.update(b'\0')
        digest.update(text.encode('utf-8'))
        digest.update(b'\0')
    return f'{family}:{digest.hexdigest()[:_DIGEST_CHARS]}'


@functools.lru_cache(maxsize=None)
def _cached_prompt_version(family):
    return compute_prompt_version(family)


def prompt_version(family):
    """The cached version of ``family``; ``None`` when there is no family or
    it cannot be computed. Never raises."""
    if not family:
        return None
    try:
        return _cached_prompt_version(str(family))
    except Exception:
        logger.warning('prompt version unavailable for family %r', family, exc_info=True)
        return None


def warm_prompt_versions():
    """Compute every family once, while the loaded code and its source agree."""
    return {family: prompt_version(family) for family in PROMPT_FAMILIES}


def restamp_prompt_version(metadata, version):
    """Return ``metadata`` with ``version`` as its prompt version. A different
    earlier version is kept in the history, never dropped."""
    metadata = dict(metadata or {})
    if not version:
        return metadata
    previous = metadata.get(PROMPT_VERSION_KEY)
    if previous and previous != version:
        metadata[PROMPT_VERSION_HISTORY_KEY] = [
            *list(metadata.get(PROMPT_VERSION_HISTORY_KEY) or []), previous,
        ]
    metadata[PROMPT_VERSION_KEY] = version
    return metadata
