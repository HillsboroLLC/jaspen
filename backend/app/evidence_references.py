# backend/app/evidence_references.py
#
# Evidence references: the record of WHICH input supported a judgment.
#
# Until this existed, scoring retained only a channel ("conversation") and the
# model's own reasoning. That let Jaspen say "this rests on thin evidence" but
# never "here is the evidence, and here is where it came from", which is the
# question "how much of your direction is backed by evidence?" invites. A
# percentage nobody can drill into is a claim, not an audit trail.
#
# THE RULE THAT MAKES THIS PROVENANCE RATHER THAN A BETTER LABEL
#
# A model may PROPOSE that a passage supported its judgment. Nothing here
# trusts that proposal. Every reference is verified against the actual source
# text before it is stored, and an excerpt that cannot be located is discarded
# rather than recorded. So a stored reference means: this text demonstrably
# exists in the input, at these offsets, and the scoring pass named it.
#
# That distinction is the whole point. An unverified quote is exactly the
# fluent, confident, unsupported artifact the product exists to expose, and
# storing one under the word "evidence" would be worse than storing nothing.
#
# WHAT IS STORED, AND WHY IT IS A SNAPSHOT RATHER THAN A POINTER
#
# Every reference carries `excerpt`: the verbatim text Jaspen actually
# evaluated, taken from the SOURCE and not from the model's restatement of it.
# A pointer alone is not enough, because sources change. A NetSuite figure read
# in August may differ in October, and a Decision Record that says "see NetSuite
# field X" would then silently describe a decision nobody made. The record must
# preserve what was seen at the time it was seen.
#
# THREE PATHS, ONE SHAPE
#
# The schema is common across all three from the start, so adding attachment
# and connector capture later cannot force a migration of what conversation
# capture already wrote:
#
#   conversation   message index, role, and character offsets into that message
#   attachment     attachment id, filename, and a location inside it
#   connector      system, object, record, field, and retrieval time
#
# Only conversation capture is implemented here. The other two builders exist
# and are typed, so the shape is settled, but they are not yet called from
# scoring. See ATTACHMENT and CONNECTOR notes on each.

import re
import uuid
from datetime import datetime

CONVERSATION = "conversation"
ATTACHMENT = "attachment"
CONNECTOR = "connector"

EVIDENCE_KINDS = (CONVERSATION, ATTACHMENT, CONNECTOR)

# Below this, an "excerpt" is too short to identify anything. Three or four
# characters will match somewhere in almost any conversation, which would
# produce references that verify successfully and mean nothing.
MIN_EXCERPT_CHARS = 12

# Above this, the model is quoting a wall of text rather than the passage it
# used, which makes the reference useless to a reader trying to see the basis.
MAX_EXCERPT_CHARS = 600

# How many references one criterion may carry. A judgment resting on more than
# a handful of passages is not being evidenced, it is being justified.
MAX_REFERENCES_PER_CRITERION = 5


def _now():
    return datetime.utcnow().isoformat()


def _reference_id():
    return f"ev_{uuid.uuid4().hex[:12]}"


def _text(value):
    return str(value or "").strip()


def _normalize_for_match(text):
    """Collapse whitespace and case, and return an index map back to the source.

    Models reformat what they quote: they re-wrap lines, straighten quotes, and
    change spacing. Matching the raw strings would reject correct references for
    cosmetic reasons, which would quietly push the system back toward having no
    provenance at all.

    Returns (normalized, index_map) where index_map[i] is the offset in the
    original string that produced normalized[i]. The map is what lets a match
    found in normalized space be reported as real offsets into the source, so
    the stored excerpt is the SOURCE's wording and not the model's.
    """
    normalized = []
    index_map = []
    previous_was_space = False
    for index, char in enumerate(text):
        if char.isspace():
            if previous_was_space or not normalized:
                continue
            normalized.append(" ")
            index_map.append(index)
            previous_was_space = True
            continue
        normalized.append(char.lower())
        index_map.append(index)
        previous_was_space = False

    # A trailing collapsed space would let a match run past the real content.
    while normalized and normalized[-1] == " ":
        normalized.pop()
        index_map.pop()

    return "".join(normalized), index_map


def locate_excerpt(excerpt, source):
    """Find `excerpt` inside `source`, tolerating reformatting.

    Returns (start, end, verbatim) with offsets into the ORIGINAL source and
    the source's own wording, or None when the passage is not present.

    Returning None is the important case: it means the model quoted something
    that is not in the input, and the caller must discard the reference rather
    than record an unverifiable one.
    """
    excerpt = _text(excerpt)
    source = str(source or "")
    if not excerpt or not source:
        return None
    if not (MIN_EXCERPT_CHARS <= len(excerpt) <= MAX_EXCERPT_CHARS):
        return None

    normalized_source, index_map = _normalize_for_match(source)
    normalized_excerpt, _ = _normalize_for_match(excerpt)
    if not normalized_excerpt:
        return None

    position = normalized_source.find(normalized_excerpt)
    if position == -1:
        return None

    start = index_map[position]
    # The map records where each normalized character began, so the end offset
    # is one past the final matched character in the source.
    end = index_map[position + len(normalized_excerpt) - 1] + 1
    return start, end, source[start:end]


def _as_turns(source):
    """Accept either a chat history or the raw text the model was shown.

    Scoring is handed a description string rather than a transcript (see
    routes/strategy.py _generate_jaspen_scorecard), and that string is the only
    thing the model could have quoted from. Verifying against anything wider
    would let a reference cite text the scoring pass never saw, which is a
    quieter version of not verifying at all.
    """
    if isinstance(source, list):
        return source
    text = _text(source)
    return [{"role": "user", "content": text}] if text else []


def conversation_reference(excerpt, source, *, criterion=None):
    """A verified reference to a passage in the input, or None.

    Only user-authored turns are searchable. Assistant text is Jaspen's own
    output, and letting a judgment cite Jaspen back to itself would create a
    loop that looks like corroboration while adding no evidence at all. This
    mirrors the same rule the readiness engine applies when scoring input.
    """
    turns = _as_turns(source)
    for index, message in enumerate(turns):
        if not isinstance(message, dict):
            continue
        if str(message.get("role") or "").strip().lower() != "user":
            continue
        located = locate_excerpt(excerpt, message.get("content"))
        if not located:
            continue
        start, end, verbatim = located
        return {
            "id": _reference_id(),
            "kind": CONVERSATION,
            "criterion": criterion,
            "captured_at": _now(),
            # The SOURCE's wording, not the model's restatement of it.
            "excerpt": verbatim,
            "locator": {
                "message_index": index,
                "role": "user",
                "start": start,
                "end": end,
            },
        }
    return None


def attachment_reference(excerpt, *, attachment_id, filename,
                         location=None, criterion=None):
    """A reference into an uploaded document.

    ATTACHMENT: not yet called from scoring. Extracted attachment text is
    available (see routes/ai_agent.py _extract_word_attachment_text and
    _extract_data_attachment_text), so verification can use locate_excerpt
    against that text exactly as the conversation path does. `location` is the
    human-meaningful position inside the file: a page for a document, a sheet
    and cell for a spreadsheet. It is deliberately open-ended because those
    differ per format and pinning a shape now would be guessing.
    """
    excerpt = _text(excerpt)
    if not excerpt or not attachment_id:
        return None
    return {
        "id": _reference_id(),
        "kind": ATTACHMENT,
        "criterion": criterion,
        "captured_at": _now(),
        "excerpt": excerpt,
        "locator": {
            "attachment_id": str(attachment_id),
            "filename": _text(filename) or None,
            "location": location or None,
        },
    }


def connector_reference(observed_value, *, system, object_name=None,
                        record_id=None, field=None, retrieved_at=None,
                        criterion=None):
    """A reference to a value read from a connected system.

    CONNECTOR: not yet called from scoring. This is the path where the snapshot
    rule matters most. A connector value is the only evidence that can change
    after the decision was made, so `excerpt` holds the value as observed and
    `retrieved_at` records when it was true. A reference that only pointed at
    the field would let a Decision Record silently re-describe itself every
    time the underlying system moved, which would make the record worse than
    useless: it would look authoritative while no longer describing the
    decision anyone actually took.
    """
    observed = _text(observed_value)
    if not observed or not system:
        return None
    return {
        "id": _reference_id(),
        "kind": CONNECTOR,
        "criterion": criterion,
        "captured_at": _now(),
        "excerpt": observed,
        "locator": {
            "system": _text(system).lower(),
            "object": _text(object_name) or None,
            "record_id": _text(record_id) or None,
            "field": _text(field) or None,
            # When the value was true, which is not the same as when the
            # decision was scored, and is what makes staleness detectable.
            "retrieved_at": retrieved_at or _now(),
        },
    }


def verify_claimed_evidence(claimed, source, *, criterion=None):
    """Turn a model's claimed excerpts into verified references.

    `claimed` is whatever the scoring pass returned for one criterion: a list
    of strings, or of objects carrying an "excerpt". Anything that cannot be
    located in a user turn is dropped silently, because a rejected claim is not
    an error the user needs to see, it is simply the absence of evidence, and
    the confidence grade already reports that.

    Duplicate passages collapse: a criterion citing the same sentence twice has
    one piece of evidence, not two, and counting it twice would overstate how
    grounded the judgment is.
    """
    if not claimed:
        return []
    if isinstance(claimed, (str, dict)):
        claimed = [claimed]
    if not isinstance(claimed, list):
        return []

    references = []
    seen_spans = set()
    for item in claimed:
        if isinstance(item, dict):
            excerpt = item.get("excerpt") or item.get("text") or item.get("quote")
        else:
            excerpt = item
        reference = conversation_reference(excerpt, source, criterion=criterion)
        if not reference:
            continue
        locator = reference["locator"]
        span = (locator["message_index"], locator["start"], locator["end"])
        if span in seen_spans:
            continue
        seen_spans.add(span)
        references.append(reference)
        if len(references) >= MAX_REFERENCES_PER_CRITERION:
            break
    return references


def attach_evidence_references(dimensions, source):
    """Verify and attach references for every dimension that claimed evidence.

    Mutates `dimensions` in place and returns the count of verified references,
    so a caller can log how much of what the model claimed actually held up.

    The claimed field is removed once processed. Leaving it would put an
    unverified model assertion next to a verified record under similar names,
    and something downstream would eventually read the wrong one.
    """
    if not isinstance(dimensions, dict):
        return 0

    verified_total = 0
    for key, dim in dimensions.items():
        if not isinstance(dim, dict):
            continue
        claimed = dim.pop("evidence", None)
        references = verify_claimed_evidence(claimed, source, criterion=key)
        if references:
            dim["evidence_references"] = references
            verified_total += len(references)
    return verified_total
