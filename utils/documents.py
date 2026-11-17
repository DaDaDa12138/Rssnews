"""Postgres-backed replacements for the small slice of the mongoengine API this code base
was written against.

The personal edition keeps every document in Postgres. Rather than rewrite all 600 call
sites, the models in apps/*/models.py now subclass LegacyDocument, which supplies the
mongoengine conveniences the call sites rely on:

    Model.objects(**lookups)        -> Model.objects.filter(**lookups)
    Model.objects.read_preference() -> no-op, returns the queryset
    qs.no_cache()                   -> no-op
    qs.update(set__field=value)     -> qs.update(field=value)
    qs.update(inc__field=1)         -> qs.update(field=F("field") + 1)
    qs.update(unset__field=1)       -> qs.update(field=None)
    doc.reload()                    -> doc.refresh_from_db()
    doc.save(safe=True, cascade=True, validate=False) -> doc.save()

Lookups mongoengine spelled differently are translated too: field__ne=value ->
exclude(field=value), field__exists=True -> field__isnull=False. The operator sits at the
end of the lookup (score__ne), which is the opposite of Django's own lookups, so both
LegacyQuerySet.filter() and LegacyQuerySet.exclude() rewrite them before Django parses
them.

There is deliberately no translation for field__len. Django reads an unknown JSON lookup
as a key transform, so highlights__len__gt=0 quietly becomes highlights -> 'len' > 0 and
matches nothing. Call sites that need "the JSON array is not empty" write
.exclude(field=[]).

utils/documents.py
"""

from django.db import DatabaseError, IntegrityError, models
from django.db.models import F

# The names mongoengine raised, mapped onto the Django exceptions that replaced them.
# NotUniqueError is what a duplicate key looked like; Django raises IntegrityError for the
# same condition, so the alias keeps every existing 'except NotUniqueError' working.
NotUniqueError = IntegrityError
OperationError = DatabaseError


UPDATE_OPERATORS = ("set", "inc", "unset", "push", "pull", "add_to_set", "pop")
LOOKUP_ALIASES = {
    "ne": "exclude",
    "nin": "exclude",
    "exists": "isnull",
}


def translate_update(**kwargs):
    """Turn a mongoengine update document into Django update kwargs."""
    translated = {}
    for key, value in kwargs.items():
        operator = None
        field = key
        if "__" in key:
            head, rest = key.split("__", 1)
            if head in UPDATE_OPERATORS:
                operator = head
                field = rest

        if operator in (None, "set"):
            translated[field] = value
        elif operator == "inc":
            translated[field] = F(field) + value
        elif operator == "unset":
            translated[field] = None
        else:
            raise NotImplementedError(
                "LegacyDocument does not support the %r update operator; rewrite the call site "
                "in apps/ (utils/documents.py)" % operator
            )
    return translated


def split_lookups(kwargs):
    """Separate plain lookups from the ones mongoengine spelled with field__ne / field__exists.

    mongoengine put the operator after the field (score__ne), so the operator is the last
    segment of the lookup, not the first. Nested paths keep working because rpartition only
    peels off the final segment (story__id__ne -> field "story__id", operator "ne").
    """
    plain = {}
    legacy = {}
    for key, value in kwargs.items():
        field, _, operator = key.rpartition("__")
        if field and operator in LOOKUP_ALIASES:
            legacy[key] = value
        else:
            plain[key] = value
    return plain, legacy


def reject_raw_lookup(kwargs):
    """The Mongo $where escape hatch has no Django equivalent, so fail loudly and early."""
    if "__raw__" in kwargs:
        raise NotImplementedError(
            "The __raw__ lookup has no Django equivalent; rewrite the call site in apps/ "
            "(utils/documents.py)"
        )


def translate_exclusions(excluded):
    """Build a Q object for the lookups Django cannot express as a filter kwarg."""
    from django.db.models import Q

    query = Q()
    for key, value in excluded.items():
        field, _, operator = key.rpartition("__")
        if operator == "ne":
            query &= ~Q(**{field: value})
        elif operator == "nin":
            query &= ~Q(**{field + "__in": value})
        elif operator == "exists":
            query &= Q(**{field + "__isnull": not value})
    return query


class LegacyQuerySet(models.QuerySet):
    """A Django queryset that also answers the mongoengine-only helpers."""

    def read_preference(self, *args, **kwargs):
        return self

    def no_cache(self):
        return self

    def limit(self, count):
        # mongoengine's .limit(n) is a slice in Django, but Mongo allowed .order_by() after
        # it, so the slice is kept pending and only applied when the rows are fetched.
        return self._legacy_limits(0, count)

    def skip(self, count):
        # mongoengine's .skip(n) starts the slice later, pending like .limit(n).
        return self._legacy_limits(count, None)

    def _legacy_limits(self, start, stop):
        clone = self._chain()
        clone._legacy_slice = (start, stop)
        return clone

    def _fetch_all(self):
        pending = getattr(self, '_legacy_slice', None)
        if pending is not None:
            self._legacy_slice = None
            start, stop = pending
            self.query.set_limits(start, stop)
        return super()._fetch_all()

    def hint(self, *args, **kwargs):
        # Query hints are a Mongo planner detail; Postgres plans on its own.
        return self

    def filter(self, *args, **kwargs):
        # Call sites write filter(score__ne=0), which Django would reject, so the legacy
        # lookups are peeled off and applied as a negation.
        reject_raw_lookup(kwargs)
        plain, legacy = split_lookups(kwargs)
        queryset = super().filter(*args, **plain)
        if legacy:
            queryset = queryset.filter(translate_exclusions(legacy))
        return queryset

    def exclude(self, *args, **kwargs):
        # exclude(score__ne=0) means "keep rows where score is 0", the inverse of filter().
        reject_raw_lookup(kwargs)
        plain, legacy = split_lookups(kwargs)
        queryset = super().exclude(*args, **plain)
        for key, value in legacy.items():
            field, _, operator = key.rpartition("__")
            if operator == "ne":
                queryset = queryset.exclude(**{field: value})
            elif operator == "exists":
                queryset = queryset.exclude(**{field + "__isnull": not value})
        return queryset

    def update(self, **kwargs):
        return super().update(**translate_update(**kwargs))

    def delete(self):
        return super().delete()


class LegacyManager(models.Manager.from_queryset(LegacyQuerySet)):
    """Model.objects(...) is mongoengine's spelling of Model.objects.filter(...)."""

    def __call__(self, *args, **kwargs):
        return self.get_queryset().filter(*args, **kwargs)


class LegacyDocument(models.Model):
    """Base class for the documents that used to live in Mongo."""

    objects = LegacyManager()

    # Documents that were mongoengine DynamicDocument (or strict=False) tolerate fields this
    # model does not declare, so keep ignoring them instead of raising TypeError.
    legacy_ignore_unknown_fields = False

    class Meta:
        abstract = True

    def __init__(self, *args, **kwargs):
        if self.legacy_ignore_unknown_fields:
            known = {field.name for field in self._meta.fields}
            known.update({field.attname for field in self._meta.fields})
            known.update({"pk", "id"})
            for key in list(kwargs):
                if key not in known and not key.startswith("_"):
                    kwargs.pop(key)
        super().__init__(*args, **kwargs)

    def save(self, *args, **kwargs):
        for ignored in ("safe", "cascade", "validate", "clean_check", "write_concern", "force_insert"):
            kwargs.pop(ignored, None)
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        return super().delete()

    def reload(self):
        self.refresh_from_db()
        return self

    def to_mongo(self):
        raise NotImplementedError("utils/documents.py: documents now live in Postgres")
