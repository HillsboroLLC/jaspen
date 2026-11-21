"""Apply one request's changes to a project that moved on since it was read.

A request reads a project, changes part of it and saves. If someone else
saved the same project in between, writing the request's whole copy back
would revert their work. Instead the store compares three versions:

* ``original``: what this request read;
* ``desired``: what this request wants to save;
* ``current``: what is stored now.

Only what this request changed (``desired`` against ``original``) is applied
to ``current``. Changes to different parts of the project are both kept. A
part that both writers changed, to different values, is the same object
edited twice: the save is refused (``ConflictingChange``) and never resolved
by overwriting either writer.

Lists whose items all carry a unique ``id`` (scorecard snapshots, comments)
are merged by identity: each item with its own earlier and stored versions,
whatever its position. Other lists are merged only in the two shapes a
project grows by: items added at the end (chat history, appended entries) or
at the front (newest first), item by item, and never pairing two items that
carry different ids. Any other overlapping list change is a conflict.

This is the session-payload counterpart of ``scenarios_store``'s snapshot
delta for scenario data. It changes how a save is combined with newer data,
never what a request saves.
"""

import copy

_MISSING = object()

# Bookkeeping that moves on every write. A difference here is not an edit to
# an object, so it never makes a conflict; the request's own value is kept.
BOOKKEEPING_KEYS = frozenset({
    'timestamp',
    'updated_at',
    'revision',
    'base_revision',
    'last_edited_by_user_id',
    'hidden_for_user_ids',
})


class ConflictingChange(Exception):
    """Both writers changed the same part of the project differently."""

    def __init__(self, paths):
        self.paths = list(paths)
        super().__init__(', '.join(self.paths[:5]) or 'conflict')


def apply_request_changes(original, desired, current, *, own_paths=()):
    """Return ``current`` with this request's changes applied.

    ``own_paths`` are parts of the project this same request already saved
    earlier: a later save in the request may change them again (the request's
    latest value wins, as it always has). Raises ConflictingChange when a part
    this request changed was also changed, differently, by someone else.
    """
    conflicts = []
    merged = _merge(original, desired, current, '', conflicts)
    foreign = [path for path in conflicts if not _is_own(path, own_paths)]
    if foreign:
        raise ConflictingChange(foreign)
    if conflicts:
        merged = _prefer_own(merged, desired, conflicts)
    return merged


def changed_paths(original, desired, path=''):
    """The parts of a project a save changed, as paths ('/a/b')."""
    if original == desired:
        return set()
    if isinstance(original, dict) and isinstance(desired, dict):
        out = set()
        for key in set(original) | set(desired):
            if key in BOOKKEEPING_KEYS:
                continue
            out |= changed_paths(original.get(key, _MISSING), desired.get(key, _MISSING), f'{path}/{key}')
        return out
    return {path or '/'}


def _is_own(path, own_paths):
    for own in own_paths:
        if path == own or path.startswith(own + '/') or own.startswith(path + '/') or own == '/':
            return True
    return False


def _prefer_own(merged, desired, paths):
    """Set each own-conflicting path to this request's latest value."""
    for path in paths:
        keys = [k for k in path.split('/') if k]
        if not keys:
            return copy.deepcopy(desired)
        source, target = desired, merged
        for key in keys[:-1]:
            if isinstance(source, list):
                key = int(key)
            source = source[key]
            target = target[key]
        last = keys[-1]
        if isinstance(source, list):
            last = int(last)
        if isinstance(source, dict) and last not in source:
            target.pop(last, None)
        else:
            target[last] = copy.deepcopy(source[last])
    return merged


def _merge(original, desired, current, path, conflicts, key=None):
    if desired == original:
        return copy.deepcopy(current)
    if current == original or current == desired:
        return copy.deepcopy(desired)
    if key in BOOKKEEPING_KEYS:
        return copy.deepcopy(desired)
    if _all(dict, original, desired, current):
        return _merge_dict(original, desired, current, path, conflicts)
    if _all(list, original, desired, current):
        return _merge_list(original, desired, current, path, conflicts)
    conflicts.append(path or '/')
    return copy.deepcopy(current)


def _merge_dict(original, desired, current, path, conflicts):
    merged = {}
    for key in list(current.keys()) + [k for k in desired.keys() if k not in current]:
        o = original.get(key, _MISSING)
        d = desired.get(key, _MISSING)
        c = current.get(key, _MISSING)
        child = f'{path}/{key}'
        if d is _MISSING and o is _MISSING:
            merged[key] = copy.deepcopy(c)
            continue
        if _same(d, o):
            if c is not _MISSING:
                merged[key] = copy.deepcopy(c)
            continue
        if _same(c, o) or _same(c, d):
            if d is not _MISSING:
                merged[key] = copy.deepcopy(d)
            continue
        if key in BOOKKEEPING_KEYS:
            if d is not _MISSING:
                merged[key] = copy.deepcopy(d)
            continue
        if _MISSING in (o, d, c):
            # One side removed what the other changed.
            conflicts.append(child)
            if c is not _MISSING:
                merged[key] = copy.deepcopy(c)
            continue
        merged[key] = _merge(o, d, c, child, conflicts, key=key)
    return merged


def _merge_list(original, desired, current, path, conflicts):
    # Items that carry their own id are matched by identity first, so an
    # insertion, a removal or a rebuilt list never pairs two different items.
    o_ids, d_ids, c_ids = _ids(original), _ids(desired), _ids(current)
    if o_ids is not None and d_ids is not None and c_ids is not None:
        keyed = _merge_by_id(original, desired, current, (o_ids, d_ids, c_ids), path)
        if keyed is None:
            conflicts.append(path or '/')
            return copy.deepcopy(current)
        return keyed
    n = len(original)
    # Items added at the end by either writer (or both).
    if len(desired) >= n and len(current) >= n:
        head = _merge_items(original, desired[:n], current[:n], path)
        if head is not None:
            return head + _combine_new(current[n:], desired[n:])
    # Items added at the front by either writer (newest first).
    if len(desired) >= n and len(current) >= n:
        d_new, c_new = len(desired) - n, len(current) - n
        tail = _merge_items(original, desired[d_new:], current[c_new:], path)
        if tail is not None:
            return _combine_new(desired[:d_new], current[:c_new]) + tail
    conflicts.append(path or '/')
    return copy.deepcopy(current)


def _item_id(item):
    if not isinstance(item, dict):
        return None
    value = item.get('id')
    if value is None or isinstance(value, (dict, list)) or str(value) == '':
        return None
    return str(value)


def _ids(items):
    """Every item's id, or None unless every item has a unique id."""
    ids = [_item_id(item) for item in items]
    if any(i is None for i in ids) or len(set(ids)) != len(ids):
        return None
    return ids


def _merge_by_id(original, desired, current, ids, path):
    """Merge identified items item by item; None when two writers changed the
    same item differently, or one removed an item the other changed."""
    o_ids, d_ids, c_ids = ids
    o_map = dict(zip(o_ids, original))
    d_map = dict(zip(d_ids, desired))
    c_map = dict(zip(c_ids, current))
    merged_items = {}
    for item_id in dict.fromkeys(c_ids + d_ids + o_ids):
        o = o_map.get(item_id, _MISSING)
        d = d_map.get(item_id, _MISSING)
        c = c_map.get(item_id, _MISSING)
        if _same(d, o):
            if c is not _MISSING:
                merged_items[item_id] = copy.deepcopy(c)
            continue
        if _same(c, o) or _same(c, d):
            if d is not _MISSING:
                merged_items[item_id] = copy.deepcopy(d)
            continue
        if _MISSING in (o, d, c):
            return None
        item_conflicts = []
        merged = _merge(o, d, c, f'{path}/{item_id}', item_conflicts)
        if item_conflicts:
            return None
        merged_items[item_id] = merged
    return [merged_items[i] for i in _merged_order(o_ids, d_ids, c_ids) if i in merged_items]


def _merged_order(o_ids, d_ids, c_ids):
    """Stored order, unless this request reordered the items it read; items
    this request added keep their place next to the item before them."""
    o_set, c_set = set(o_ids), set(c_ids)
    kept = [i for i in o_ids if i in d_ids]
    d_kept = [i for i in d_ids if i in o_set]
    if d_kept != kept:
        order = [i for i in d_ids if i in o_set or i in c_set]
        order += [i for i in c_ids if i not in order]
    else:
        order = list(c_ids)
    for index, item_id in enumerate(d_ids):
        if item_id in o_set or item_id in order:
            continue
        before = next((d_ids[j] for j in range(index - 1, -1, -1) if d_ids[j] in order), None)
        if before is None:
            order.insert(0, item_id)
            continue
        at = order.index(before) + 1
        # After items the other writer added there meanwhile, as appends were
        # always combined (theirs first, then this request's).
        while at < len(order) and order[at] in c_set and order[at] not in o_set:
            at += 1
        order.insert(at, item_id)
    return order


def _merge_items(original, desired, current, path):
    """Merge equal-length item lists item by item; None if any item conflicts."""
    out = []
    for index, (o, d, c) in enumerate(zip(original, desired, current)):
        # Never pair two different items: same position, different ids.
        if len({i for i in map(_item_id, (o, d, c)) if i is not None}) > 1:
            return None
        item_conflicts = []
        merged = _merge(o, d, c, f'{path}/{index}', item_conflicts)
        if item_conflicts:
            return None
        out.append(merged)
    return out


def _combine_new(first, second):
    """New items from both writers, without repeating identical additions."""
    first = copy.deepcopy(list(first))
    if not first:
        return copy.deepcopy(list(second))
    if not second or list(second) == first:
        return first
    return first + copy.deepcopy(list(second))


def _same(a, b):
    if a is _MISSING or b is _MISSING:
        return a is b
    return a == b


def _all(kind, *values):
    return all(isinstance(value, kind) for value in values)
