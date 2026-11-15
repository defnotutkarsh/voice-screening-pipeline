"""Adapters translate one voice platform's post-call payload into the record
shape the rest of the code understands. See base.py for that shape."""
from .base import CALL_RECORD_FIELDS, Adapter
from .generic import GenericAdapter

__all__ = ["Adapter", "CALL_RECORD_FIELDS", "GenericAdapter"]
