"""How finished a set of things is, expressed the same way everywhere.

Task statistics, milestone progress and a task's checklist all answer the same
question about different rows, and all three had their own copy of the
arithmetic. Three copies is three chances for one of them to round differently
— and two percentages rendered side by side that disagree in the fourth
decimal place read as a bug in whichever the reader trusts less.
"""

# Four decimal places is a hundredth of a percent: enough to render any bar or
# figure, and short of the digits a ratio of two integers trails behind it.
COMPLETION_RATE_PRECISION = 4


def completion_rate(done: int, total: int) -> float:
    """The finished fraction of ``total``, 0.0 when there is nothing to finish.

    An empty set is 0% complete rather than unknown: a client that has to
    decide what a null means here will decide differently in each place it
    renders one.
    """
    if not total:
        return 0.0
    return round(done / total, COMPLETION_RATE_PRECISION)
