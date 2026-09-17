"""Date arithmetic policy, stated once so both implementations can be held to it.

The reminder half of this studio makes a different claim from the document
half. The document half claims arithmetic correctness; this claims DATE
correctness, and it is provable in the same way -- by computing every date
twice, by two implementations that share no code, and refusing to render if
they disagree by a single day.

The policy, so that redates.py can be written against it rather than against
this file's code:

  * Every date entering the engine is an ISO calendar date, YYYY-MM-DD. No
    locale parsing, no "15/08/2026" ambiguity, no natural language.
  * A due date is derived: reference date + credit days. It is never typed
    unless the supplier declares it directly, and when they do, the derivation
    is still shown so the two can be compared.
  * Credit days are counted in CALENDAR days, not working days. Working days
    require a holiday calendar the tool does not have and will not guess.
  * Days overdue = as_of - due_date, in calendar days, and may be negative.
    Negative means not yet due, and the tool says so rather than printing a
    minus sign.
  * `as_of` is always an explicit input. The engine never calls date.today().
    A reminder must be reproducible: the same JSON must produce the same
    document next year, or nobody can check the one you sent last year.
  * An ageing bucket is derived from days overdue against declared boundaries,
    and the boundary that placed it is printed alongside it -- the same move
    as printing the place-of-supply provision rather than just the state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

# The standard receivables ageing boundaries. These are a reporting
# convention, not a claim about anybody's business, which is why the tool is
# willing to supply them when they are not declared. They are printed on the
# document either way, so a reader can see which convention was used.
DEFAULT_BUCKETS: tuple[int, ...] = (30, 60, 90)

# Days counted in a year for simple interest. Declared here rather than
# inlined, because it is a convention a contract may disagree with, and a
# reader of the document is entitled to see which one was used.
DAY_COUNT_BASIS = 365


class DateError(ValueError):
    """A value that should be a calendar date is not one."""


@dataclass(frozen=True)
class DateFact:
    """One computed date or day count, and the derivation that produced it.

    The money equivalent is compute.Fact. Kept separate because a day count
    formatted as rupees would be nonsense, and the fact table prints both.
    """

    key: str
    value: str
    formula: str

    def __str__(self) -> str:
        return f"{self.key} = {self.value}  [{self.formula}]"


def to_date(value, *, field: str) -> date:
    """Parse user input into a calendar date. ISO only, and nothing else.

    A date is refused rather than guessed at for the same reason a GST rate
    is: 03/04/2026 is two different days in two different countries, and a
    reminder that names the wrong due date is worse than no reminder.
    """
    if isinstance(value, date):
        return value
    if value in (None, ""):
        raise DateError(f"{field}: is required (YYYY-MM-DD)")
    if not isinstance(value, str):
        raise DateError(
            f"{field}: expected a date as a YYYY-MM-DD string, got "
            f"{type(value).__name__}"
        )
    text = value.strip()
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise DateError(
            f"{field}: {value!r} is not a date in YYYY-MM-DD form. Dates are "
            f"accepted in ISO form only -- 03/04/2026 means two different days "
            f"in two different countries and this tool will not choose one"
        ) from None


def to_optional_date(value, *, field: str) -> date | None:
    if value in (None, ""):
        return None
    return to_date(value, field=field)


def to_days(value, *, field: str) -> int:
    """Parse a whole number of calendar days. Floats and negatives refused."""
    if isinstance(value, bool):
        raise DateError(f"{field}: expected a whole number of days, got a boolean")
    if isinstance(value, int):
        days = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise DateError(f"{field}: is empty")
        try:
            days = int(text)
        except ValueError:
            raise DateError(
                f"{field}: {value!r} is not a whole number of days"
            ) from None
    else:
        raise DateError(
            f"{field}: expected a whole number of days, got "
            f"{type(value).__name__}"
        )
    if days < 0:
        raise DateError(f"{field}: cannot be negative, got {days}")
    return days


def add_days(start: date, days: int) -> date:
    """Calendar days, not working days. The tool has no holiday calendar."""
    return start + timedelta(days=days)


def days_between(start: date, end: date) -> int:
    """end - start, in calendar days. Negative when end precedes start."""
    return (end - start).days


def derive_due_date(reference_date: date, credit_days: int) -> date:
    """The due date the credit terms produce."""
    return add_days(reference_date, credit_days)


def bucket_of(days_overdue: int, buckets: tuple[int, ...]) -> tuple[str, str]:
    """Place a day count in an ageing bucket, with the boundary that placed it.

    Returns (label, why). The `why` is printed next to the label so a reader
    can check the placement instead of trusting it.
    """
    if days_overdue <= 0:
        return "Not yet due", (
            f"the due date has not passed as at the stated date"
            if days_overdue == 0 else
            f"due in {-days_overdue} day{_s(-days_overdue)}"
        )

    previous = 0
    for boundary in buckets:
        if days_overdue <= boundary:
            return (f"{previous + 1}-{boundary} days",
                    f"{days_overdue} day{_s(days_overdue)} overdue falls at or "
                    f"below the {boundary}-day boundary")
        previous = boundary

    last = buckets[-1] if buckets else 0
    return (f"Over {last} days",
            f"{days_overdue} day{_s(days_overdue)} overdue is past the "
            f"{last}-day boundary, the last one declared")


def parse_buckets(value, *, field: str) -> tuple[int, ...]:
    """Ageing boundaries, ascending and distinct, or the standard convention."""
    if value in (None, ""):
        return DEFAULT_BUCKETS
    if not isinstance(value, (list, tuple)):
        raise DateError(f"{field}: expected a list of day counts")
    boundaries = tuple(
        to_days(v, field=f"{field}[{i}]") for i, v in enumerate(value)
    )
    if not boundaries:
        raise DateError(f"{field}: at least one boundary is required")
    if any(b <= 0 for b in boundaries):
        raise DateError(f"{field}: every boundary must be greater than zero")
    if list(boundaries) != sorted(set(boundaries)):
        raise DateError(
            f"{field}: boundaries must ascend and not repeat, got {list(boundaries)}"
        )
    return boundaries


def format_date(value: date) -> str:
    """The one date format that reaches a rendered page."""
    return value.strftime("%d %b %Y")


def _s(n: int) -> str:
    return "" if n == 1 else "s"
