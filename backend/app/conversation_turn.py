"""One lifecycle for a conversation turn.

A turn is the unit a customer experiences: they send a message and Jaspen
replies. Every turn, on every route (start, continue, regenerate), streamed or
not, moves through the same steps:

    reserve -> generate -> settle -> save -> (persist balance)

    on failure before settlement -> release

Before this module each route carried its own copy of those steps, twice (one
streamed, one not): six copies of the code that decides what a customer is
charged and what is saved. ``ConversationTurn`` is now the only place that
holds a turn's financial and persistence state.

What this module owns
---------------------
* The turn's state: what was reserved, whether it was settled, what was
  charged, the balance left.
* The ORDER rules that make a turn safe: settle at most once, never release
  after settlement, save through one seam.

What it deliberately does not own
---------------------------------
* Money. Balances, prices and reservations belong to the billing authority
  behind ``TurnBilling``. This module never reads or writes a balance.
* Storage. Projects are written by the store behind ``TurnStore``, which also
  enforces organization ownership and write permission.
* Words. The AI's reply is passed through untouched (Constitution, Article
  17A). Nothing here inspects or rewrites it.

The two ports are the integration boundary. Today they are bound to the
legacy credit functions and to ``save_user_sessions``. The authoritative
ledger (billing Phase 12) replaces the ``TurnBilling`` binding and nothing
else: the routes, the lifecycle and the tests in
``tests/journeys/test_conversation_turn_lifecycle.py`` stay as they are.

Behaviour is unchanged from the six copies this replaced. In particular the
charging gaps recorded as strict-xfail probes in that test file (a dropped
stream keeps its reservation; a JSON turn is charged before it is saved) are
still present. Each is now a change in ONE place, and each needs its own
approval because it alters live charging.

One thing was deliberately corrected: a turn writes only its own project
(see ``ConversationTurn.save``). The copies wrote back every project the
route had loaded, which reverted work saved elsewhere during generation.
"""

from dataclasses import dataclass
from typing import Any, Callable, Optional


@dataclass(frozen=True)
class TurnBilling:
    """The financial authority a turn talks to. It owns all balances.

    ``reserve(user, model_type, token_hint)`` -> dict with ``ok``,
        ``reserved`` and, when refused, ``payload`` for the customer.
    ``price(usage, model_type, user)`` -> credits owed for delivered usage.
    ``settle(user, reserved_credits, actual_credits)`` -> dict with ``ok``,
        ``charged``, ``remaining`` and, when refused, ``payload``.
    ``release(user, reserved_credits)`` gives an unused reservation back.
    ``persist_balance(user_id, remaining)`` makes the settled balance durable.
    ``insufficient_payload(user, required)`` -> the customer-facing refusal.
    """

    reserve: Callable[..., dict]
    price: Callable[..., int]
    settle: Callable[..., dict]
    release: Callable[..., Any]
    persist_balance: Callable[..., Any]
    insufficient_payload: Callable[..., dict]


@dataclass(frozen=True)
class TurnStore:
    """Where a turn's project is written. ``save(user_id, sessions) -> bool``."""

    save: Callable[..., bool]


class TurnLifecycleError(RuntimeError):
    """A turn was driven out of order. Always a programming error."""


class ConversationTurn:
    """Financial and persistence state for exactly one conversation turn.

    ``session`` is the one project this turn belongs to and the only one it
    ever writes. ``sessions`` is the set the route loaded; it is kept current
    for the route's own reads and is never written back (see ``save``).
    """

    def __init__(self, *, user, user_id, thread_id, session, sessions,
                 model_type, billing: TurnBilling, store: TurnStore,
                 session_key: Optional[str] = None):
        self.user = user
        self.user_id = user_id
        self.thread_id = thread_id
        self.session_key = session_key or thread_id
        self.session = session
        self.sessions = sessions
        self.model_type = model_type
        self._billing = billing
        self._store = store

        self.reserved_credits = 0
        self.credits_charged = 0
        self.remaining = None
        self._reserved = False
        self._settled = False
        self._released = False

    # -- state ----------------------------------------------------------

    @property
    def settled(self) -> bool:
        """True once settlement was attempted, whether or not it succeeded."""
        return self._settled

    # -- money ----------------------------------------------------------

    def reserve(self, *, token_hint=None) -> Optional[dict]:
        """Reserve credits before generating.

        Returns ``None`` when the turn may proceed, or the customer-facing
        refusal when the balance cannot cover it.
        """
        if self._reserved:
            raise TurnLifecycleError("a turn reserves once")
        reservation = self._billing.reserve(
            self.user, self.model_type, token_hint=token_hint,
        )
        if not reservation["ok"]:
            return reservation["payload"]
        self._reserved = True
        self.reserved_credits = int(reservation["reserved"] or 0)
        return None

    def settle(self, usage) -> Optional[dict]:
        """Convert the reservation into the charge for what was delivered.

        Returns ``None`` on success, or the customer-facing refusal when the
        actual cost exceeds what the balance can cover.
        """
        if self._settled:
            raise TurnLifecycleError("a turn settles once")
        actual = self._billing.price(usage, self.model_type, self.user)
        settlement = self._billing.settle(
            self.user,
            reserved_credits=self.reserved_credits,
            actual_credits=actual,
        )
        self._settled = True
        if not settlement["ok"]:
            return settlement["payload"] or self._billing.insufficient_payload(self.user, actual)
        self.remaining = settlement["remaining"]
        self.credits_charged = settlement["charged"]
        return None

    def release_unsettled(self) -> bool:
        """Give the reservation back if the turn never reached settlement.

        Safe to call from any failure path, any number of times. After
        settlement it does nothing: a settled charge is undone by reversal,
        which is a different, separately approved operation.
        """
        if self._settled or self._released or not self._reserved:
            return False
        self._released = True
        self._billing.release(self.user, self.reserved_credits)
        return True

    def persist_balance(self) -> None:
        """Make the settled balance durable."""
        if not self._settled:
            raise TurnLifecycleError("nothing settled to persist")
        self._billing.persist_balance(self.user_id, self.remaining)

    # -- storage --------------------------------------------------------

    def save(self) -> bool:
        """The single place a turn writes, and it writes ONE project.

        A turn can take many seconds. The route loaded its projects before
        generation began, so every project other than this turn's is by now a
        stale copy: another tab, the sidebar assistant or a colleague may have
        saved to it since. Handing those copies back to the store would revert
        that work, so only this turn's project is sent.

        The store still resolves the organization's canonical row for it and
        enforces read access, write access and any declared revision, exactly
        as before; narrowing what is sent removes writes, it adds none.
        """
        self.sessions[self.session_key] = self.session
        return bool(self._store.save(self.user_id, {self.session_key: self.session}))
