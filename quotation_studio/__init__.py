"""Tool 03 -- Quotation, Proposal & Payment-Reminder Studio.

Claim: arithmetic and field correctness, which is provable. For reminders the
same claim extends to the calendar: due dates, day counts and ageing are
derived and computed twice, never typed.

Not claimed: that any rate, classification or registration status is correct,
that a sum chased is actually owed, or that it is undisputed. Those are the
supplier's declarations; this tool never suggests them.
"""

from .pipeline import (  # noqa: F401
    ReminderResult, Result, remind, remind_file, run, run_file,
)

__all__ = [
    "run", "run_file", "Result",
    "remind", "remind_file", "ReminderResult",
]
__version__ = "0.1.0"
