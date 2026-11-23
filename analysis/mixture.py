"""Exact interval verdicts for a mixture of two frozen evidence items.

At a real ratio ``t`` the mixed joint frequency of every disposition row is
``(1 - t) * left + t * right``, so each mixed frequency is a linear polynomial
in ``t`` with rational coefficients.  The completion probability and the
conditional review expectation of the mixed branching process are therefore
piecewise rational in ``t``.  Both threshold rules are decided exactly for
every real ``t`` in the closed window by reducing them to sign checks of
rational polynomials on closed rational intervals.
"""
from fractions import Fraction

from intake.outcomes import Disposition, WorkClass


# ---------------------------------------------------------------------------
# Polynomials with rational coefficients, stored as ascending power tuples.
# ---------------------------------------------------------------------------

def _trim(poly):
    poly = tuple(poly)
    while poly and poly[-1] == 0:
        poly = poly[:-1]
    return poly


def _add(a, b):
    size = max(len(a), len(b))
    coeffs = [Fraction(0)] * size
    for index, coeff in enumerate(a):
        coeffs[index] += coeff
    for index, coeff in enumerate(b):
        coeffs[index] += coeff
    return _trim(coeffs)


def _neg(a):
    return tuple(-coeff for coeff in a)


def _sub(a, b):
    return _add(a, _neg(b))


def _scale(a, factor):
    if factor == 0:
        return ()
    return _trim(tuple(factor * coeff for coeff in a))


def _mul(a, b):
    if not a or not b:
        return ()
    coeffs = [Fraction(0)] * (len(a) + len(b) - 1)
    for i, ca in enumerate(a):
        for j, cb in enumerate(b):
            coeffs[i + j] += ca * cb
    return _trim(coeffs)


def _eval(poly, point):
    result = Fraction(0)
    for coeff in reversed(poly):
        result = result * point + coeff
    return result


def _derivative(poly):
    return tuple(Fraction(power) * poly[power] for power in range(1, len(poly)))


def _poly_divmod(dividend, divisor):
    rest = list(dividend)
    lead = divisor[-1]
    quotient = [Fraction(0)] * max(0, len(rest) - len(divisor) + 1)
    while rest and len(rest) >= len(divisor):
        coeff = rest[-1] / lead
        shift = len(rest) - len(divisor)
        quotient[shift] = coeff
        for index, dcoeff in enumerate(divisor):
            rest[shift + index] -= coeff * dcoeff
        while rest and rest[-1] == 0:
            rest.pop()
    return _trim(quotient), _trim(rest)


def _monic(poly):
    if not poly:
        return poly
    lead = poly[-1]
    return tuple(coeff / lead for coeff in poly)


def _poly_gcd(a, b):
    while b:
        a, b = b, _poly_divmod(a, b)[1]
    return _monic(a)


def _squarefree(poly):
    """Divide out repeated factors so every real root becomes simple."""
    derivative = _derivative(poly)
    if not derivative:
        return poly
    return _poly_divmod(poly, _poly_gcd(poly, derivative))[0]


def _sturm_sequence(poly):
    sequence = [poly]
    derivative = _derivative(poly)
    if derivative:
        sequence.append(derivative)
        while True:
            remainder = _neg(_poly_divmod(sequence[-2], sequence[-1])[1])
            if not remainder:
                return sequence
            sequence.append(remainder)
    return sequence


def _sign_variations(sequence, point):
    signs = []
    for poly in sequence:
        value = _eval(poly, point)
        if value > 0:
            signs.append(1)
        elif value < 0:
            signs.append(-1)
    return sum(1 for first, second in zip(signs, signs[1:]) if first != second)


def _roots_in_open(poly, sequence, low, high):
    """Number of distinct real roots of a squarefree polynomial in (low, high)."""
    count = _sign_variations(sequence, low) - _sign_variations(sequence, high)
    if _eval(poly, high) == 0:
        count -= 1
    return count


def _bisect_roots(poly, sequence, low, high, lo, hi, count, out):
    if count == 1 and lo > low and hi < high:
        out.append((lo, hi))
        return
    mid = (lo + hi) / 2
    if _eval(poly, mid) == 0:
        left = _roots_in_open(poly, sequence, lo, mid)
        right = _roots_in_open(poly, sequence, mid, hi)
        if left:
            _bisect_roots(poly, sequence, low, high, lo, mid, left, out)
        out.append((mid, mid))
        if right:
            _bisect_roots(poly, sequence, low, high, mid, hi, right, out)
        return
    left = _roots_in_open(poly, sequence, lo, mid)
    right = count - left
    if left:
        _bisect_roots(poly, sequence, low, high, lo, mid, left, out)
    if right:
        _bisect_roots(poly, sequence, low, high, mid, hi, right, out)


def _isolate_roots(poly, sequence, low, high):
    """Disjoint rational intervals around each distinct root in (low, high)."""
    count = _roots_in_open(poly, sequence, low, high)
    intervals = []
    if count:
        _bisect_roots(poly, sequence, low, high, low, high, count, intervals)
    return intervals


def _tighten_root(poly, sequence, lo, hi):
    """One bisection step on a single-root interval with non-root endpoints."""
    mid = (lo + hi) / 2
    if _eval(poly, mid) == 0:
        return mid, mid
    if _roots_in_open(poly, sequence, lo, mid) == 1:
        return lo, mid
    return mid, hi


def _separate_roots(poly, sequence, intervals):
    """Tighten isolation intervals until consecutive ones leave a real gap."""
    intervals = [list(interval) for interval in intervals]
    for index in range(len(intervals) - 1):
        while intervals[index][1] >= intervals[index + 1][0]:
            intervals[index] = list(_tighten_root(poly, sequence, *intervals[index]))
            intervals[index + 1] = list(_tighten_root(poly, sequence, *intervals[index + 1]))
    return [tuple(interval) for interval in intervals]


def _nonnegative_on_interval(poly, low, high):
    """Exact check: poly(t) >= 0 for every real t in [low, high]."""
    poly = _trim(poly)
    if _eval(poly, low) < 0 or _eval(poly, high) < 0:
        return False
    if low == high or len(poly) <= 1:
        return True
    squarefree = _squarefree(poly)
    sequence = _sturm_sequence(squarefree)
    intervals = _separate_roots(squarefree, sequence, _isolate_roots(squarefree, sequence, low, high))
    # Each gap between consecutive root intervals is root free, so the
    # polynomial keeps one sign there; sample its rational midpoint.
    starts = [low] + [upper for _, upper in intervals]
    stops = [lower for lower, _ in intervals] + [high]
    return all(_eval(poly, (start + stop) / 2) >= 0 for start, stop in zip(starts, stops))


# ---------------------------------------------------------------------------
# The mixed branching model at ratio t.
# ---------------------------------------------------------------------------

_ORDINARY_ROWS = (
    Disposition(0, 0, True), Disposition(0, 0, False),
    Disposition(0, 1, True), Disposition(0, 1, False),
    Disposition(1, 0, True), Disposition(1, 0, False),
    Disposition(2, 0, True), Disposition(2, 0, False),
)
_SPECIAL_ROWS = (
    Disposition(0, 0, True), Disposition(0, 0, False),
    Disposition(0, 1, True), Disposition(0, 1, False),
)


def _frequencies(rows, work_class):
    return {
        row.disposition: row.frequency
        for row in rows
        if row.work_class is work_class
    }


def _linear(left, right):
    """The mixed frequency (1 - t) * left + t * right as a polynomial in t."""
    return _trim((left, right - left))


def build_mixture_model(left_rows, right_rows):
    """Linear polynomials for every joint row of the two work classes."""
    left_ordinary = _frequencies(left_rows, WorkClass.ORDINARY)
    right_ordinary = _frequencies(right_rows, WorkClass.ORDINARY)
    left_special = _frequencies(left_rows, WorkClass.SPECIAL)
    right_special = _frequencies(right_rows, WorkClass.SPECIAL)
    zero = Fraction(0)
    ordinary = tuple(
        _linear(left_ordinary.get(key, zero), right_ordinary.get(key, zero))
        for key in _ORDINARY_ROWS
    )
    special = tuple(
        _linear(left_special.get(key, zero), right_special.get(key, zero))
        for key in _SPECIAL_ROWS
    )
    return ordinary, special


def mixture_interval_passes(model, low, high, completion_min, review_max):
    """Decide whether every real ratio in [low, high] meets both thresholds.

    ``model`` comes from :func:`build_mixture_model`; the bounds and
    thresholds are exact ``Fraction`` values.  The completion probability
    must reach ``completion_min`` and the conditional review expectation of
    completed batches must not exceed ``review_max`` at every point.
    """
    (a, b, c, d, e, f, g, h), (i, j, k, l) = model
    zero = _add(_add(a, b), _add(c, d))
    two = _add(g, h)
    # Completion: q(t) = min(1, zero/two) for zero > 0, else 0 (or 1 when the
    # two-child frequency vanishes).  For 0 < c <= 1 the rule q(t) >= c is
    # equivalent to the linear conditions zero(t) > 0 and zero(t) >= c*two(t).
    if completion_min > 1:
        return False
    if _eval(zero, low) <= 0 or _eval(zero, high) <= 0:
        return False
    margin = _sub(zero, _scale(two, completion_min))
    if _eval(margin, low) < 0 or _eval(margin, high) < 0:
        return False
    # Review: with q(t) > 0 everywhere, R(t) <= review_max is equivalent to
    # W(t) <= review_max * (1 - mean(t)), where W is the per-item review
    # contribution and mean the conditioned ordinary offspring mean.  A zero
    # contribution at the critical mean counts as zero, a positive one as
    # infinite; both fall out of the same inequality.
    drift = _sub(zero, two)
    close = _add(i, j)
    flagged = _add(i, k)
    rolled = _add(_mul(_add(a, c), close), _mul(_add(c, d), flagged))
    # Where zero >= two the completion probability is one:
    steady = _sub(
        _mul(_sub(_scale(drift, review_max), _add(_add(a, c), _add(e, g))), close),
        _mul(_add(c, d), flagged),
    )
    # Where zero < two the completion probability is zero/two:
    shifting = _sub(
        _sub(
            _mul(_sub(_scale(_neg(drift), review_max), e), _mul(_mul(zero, two), close)),
            _mul(rolled, _mul(two, two)),
        ),
        _mul(_mul(g, _mul(zero, zero)), close),
    )
    cuts = [low, high]
    if len(drift) == 2:
        knot = -drift[0] / drift[1]
        if low < knot < high:
            cuts = [low, knot, high]
    for start, stop in zip(cuts, cuts[1:]):
        probe = start if start == stop else (start + stop) / 2
        poly = steady if _eval(drift, probe) >= 0 else shifting
        if not _nonnegative_on_interval(poly, start, stop):
            return False
    return True
