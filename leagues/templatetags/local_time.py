"""Render saved UTC/ISO timestamps in the project's local timezone."""

from django import template
from django.template.defaultfilters import date as date_filter
from django.utils import timezone
from django.utils.dateparse import parse_datetime

register = template.Library()


@register.filter
def local_dt(value, fmt="M j, Y, g:i A T"):
    dt = parse_datetime(value) if isinstance(value, str) else value
    if dt is None:
        return value
    if timezone.is_aware(dt):
        dt = timezone.localtime(dt)
    return date_filter(dt, fmt)
