"""Deterministic byte encoding of mixture handover manifests.

A manifest binds the ordered V1 identities of the two parent evidence items
to the exact closed ratio window.  Its id is the SHA-256 digest of the
canonical body, mirroring the V1 evidence codec.
"""
from fractions import Fraction
from hashlib import sha256
import json

from intake.record_checks import valid_name


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')


def _body(left_id, right_id, low, high):
    return {
        'version': 1,
        'left': left_id,
        'right': right_id,
        'low': str(low),
        'high': str(high),
    }


def compute_mix_id(left_id, right_id, low, high):
    return sha256(_canonical(_body(left_id, right_id, low, high))).hexdigest()


def encode_mix_manifest(left_id, right_id, low, high) -> bytes:
    body = _body(left_id, right_id, low, high)
    return _canonical({'id': compute_mix_id(left_id, right_id, low, high), 'body': body})


def _parse_bound(value):
    if not isinstance(value, str):
        raise ValueError('mixture bounds must use rational strings')
    bound = Fraction(value)
    if not 0 <= bound <= 1:
        raise ValueError('mixture bounds must lie inside [0, 1]')
    return bound


def decode_mix_manifest(payload: bytes):
    """Return (mix_id, left_id, right_id, low, high) for a canonical manifest."""
    if type(payload) is not bytes or not payload:
        raise ValueError('expected a nonempty manifest byte string')
    try:
        envelope = json.loads(payload)
        body = envelope['body']
        if type(body['version']) is not int or body['version'] != 1:
            raise ValueError('unsupported manifest version')
        left_id, right_id = body['left'], body['right']
        if not valid_name(left_id) or not valid_name(right_id):
            raise ValueError('invalid parent identities')
        low, high = _parse_bound(body['low']), _parse_bound(body['high'])
        if low > high:
            raise ValueError('mixture bounds must satisfy low <= high')
        mix_id = compute_mix_id(left_id, right_id, low, high)
        if envelope['id'] != mix_id:
            raise ValueError('manifest identity does not match its body')
        if encode_mix_manifest(left_id, right_id, low, high) != payload:
            raise ValueError('manifest is not in its canonical encoding')
        return mix_id, left_id, right_id, low, high
    except (KeyError, TypeError, ValueError, ZeroDivisionError, RecursionError) as exc:
        raise ValueError(f'invalid manifest: {exc}') from exc
