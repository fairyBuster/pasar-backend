"""Post-processing hook that guarantees a usable response schema per endpoint.

A large part of this API is written as function based views returning plain
``Response({...})`` dicts, so drf-spectacular derives no response schema for
them. On top of that, ``OpenApiResponse(examples=[...])`` without
``response=...`` is silently reduced to a bare description: drf-spectacular
drops the examples entirely once the response object is empty.

This hook closes the gaps after generation, in order of fidelity:

1. An example without a schema gets a schema derived from that example.
2. A schema without an example gets an example generated from that schema.
3. Neither -> documented as a free-form JSON object with an empty example.

Missing operation summaries are derived from the auto-generated ``operationId``
(e.g. ``attendance_logs_claim_bonus_create`` -> "Create Attendance Logs Claim
Bonus"). An explicit ``@extend_schema(summary=...)`` still wins.
"""
import re

HTTP_METHODS = ('get', 'post', 'put', 'patch', 'delete', 'head', 'options')
NO_BODY_STATUSES = ('204', '205', '304')

VERB_BY_ACTION = {
    'list': 'List',
    'retrieve': 'Get',
    'create': 'Create',
    'update': 'Update',
    'partial_update': 'Partial Update',
    'destroy': 'Delete',
}

ACRONYMS = {
    'api': 'API', 'id': 'ID', 'jwt': 'JWT', 'otp': 'OTP', 'pin': 'PIN',
    'qr': 'QR', 'usd': 'USD', 'va': 'VA', 'ph': 'PH',
}

STRING_SAMPLES = (
    ('email', 'user@example.com'),
    ('phone', '081234567890'),
    ('username', 'user123'),
    ('password', 'Secret123!'),
    ('token', 'eyJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoxfQ.signature'),
    ('transaction_id', 'TRX-20260101120000-A1B2C3'),
    ('trx_id', 'TRX-20260101120000-A1B2C3'),
    ('callback', 'https://example.com/callback'),
    ('url', 'https://example.com'),
    ('address', 'Jl. Contoh No. 1'),
    ('currency', 'IDR'),
    ('bank', 'BCA'),
    ('account', '1234567890'),
    ('code', 'ABC123'),
    ('pin', '123456'),
    ('otp', '123456'),
    ('name', 'Example'),
    ('status', 'success'),
    ('message', 'Request completed successfully'),
    ('note', 'Catatan contoh'),
    ('description', 'Contoh deskripsi'),
)

MONEY_HINTS = ('amount', 'balance', 'price', 'total', 'fee', 'rate', 'profit', 'min', 'max')

_ISO_DATE_TIME = re.compile(r'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}')
_ISO_DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')

MAX_DEPTH = 6


# ---------------------------------------------------------------------------
# schema helpers
# ---------------------------------------------------------------------------
def _resolve(schema, schemas, depth=0):
    """Follow a local $ref a bounded number of times."""
    while isinstance(schema, dict) and schema.get('$ref') and depth < 4:
        schema = schemas.get(schema['$ref'].rsplit('/', 1)[-1], {})
        depth += 1
    return schema if isinstance(schema, dict) else {}


def _is_unmodeled(schema, schemas):
    """True when the schema carries no usable structure."""
    resolved = _resolve(schema, schemas)
    if not resolved:
        return True
    if resolved.get('properties'):
        return False
    if any(key in resolved for key in ('oneOf', 'anyOf', 'allOf', 'enum', 'items')):
        return False
    return resolved.get('type') in (None, 'object')


def _string_sample(name, schema):
    fmt = schema.get('format')
    if fmt == 'date-time':
        return '2026-01-01T00:00:00Z'
    if fmt == 'date':
        return '2026-01-01'
    if fmt == 'time':
        return '00:00:00'
    if fmt == 'uuid':
        return '3fa85f64-5717-4562-b3fc-2c963f66afa6'
    if fmt == 'email':
        return 'user@example.com'
    if fmt in ('uri', 'url'):
        return 'https://example.com'
    for hint, sample in STRING_SAMPLES:
        if hint in name:
            return sample
    return 'string'


def _number_sample(name):
    if any(hint in name for hint in MONEY_HINTS):
        return 100000
    if name.endswith('_id') or name == 'id':
        return 1
    if name.endswith('count') or name.startswith('total_'):
        return 1
    return 0


def _example_from_schema(schema, schemas, name='', depth=0, seen=frozenset()):
    """Build a plausible example value from a JSON schema."""
    if depth > MAX_DEPTH or not isinstance(schema, dict):
        return None
    if 'example' in schema:
        return schema['example']
    if 'default' in schema:
        return schema['default']

    ref = schema.get('$ref')
    if ref:
        ref_name = ref.rsplit('/', 1)[-1]
        if ref_name in seen:
            return None
        seen = seen | {ref_name}
        schema = schemas.get(ref_name, {})

    if schema.get('enum'):
        return schema['enum'][0]
    for key in ('oneOf', 'anyOf'):
        if schema.get(key):
            return _example_from_schema(schema[key][0], schemas, name, depth + 1, seen)
    if 'allOf' in schema:
        merged = {}
        for sub in schema['allOf']:
            value = _example_from_schema(sub, schemas, name, depth + 1, seen)
            if isinstance(value, dict):
                merged.update(value)
        return merged or None

    schema_type = schema.get('type')
    if schema_type == 'object' or 'properties' in schema:
        result = {}
        for prop_name, prop_schema in (schema.get('properties') or {}).items():
            value = _example_from_schema(prop_schema, schemas, prop_name, depth + 1, seen)
            result[prop_name] = value if value is not None else None
        if not result and isinstance(schema.get('additionalProperties'), dict):
            result['key'] = _example_from_schema(
                schema['additionalProperties'], schemas, 'value', depth + 1, seen
            )
        return result
    if schema_type == 'array':
        item = _example_from_schema(schema.get('items') or {}, schemas, name, depth + 1, seen)
        return [item] if item is not None else []
    if schema_type == 'string':
        return _string_sample(name, schema)
    if schema_type == 'integer':
        return int(_number_sample(name))
    if schema_type == 'number':
        return float(_number_sample(name))
    if schema_type == 'boolean':
        return True
    if schema_type == 'null':
        return None
    return None


def _schema_from_value(value):
    """Derive a JSON schema from a concrete example payload."""
    if isinstance(value, bool):
        return {'type': 'boolean', 'example': value}
    if isinstance(value, int):
        return {'type': 'integer', 'example': value}
    if isinstance(value, float):
        return {'type': 'number', 'example': value}
    if isinstance(value, str):
        schema = {'type': 'string'}
        if _ISO_DATE_TIME.match(value):
            schema['format'] = 'date-time'
        elif _ISO_DATE.match(value):
            schema['format'] = 'date'
        elif '@' in value and '.' in value and ' ' not in value:
            schema['format'] = 'email'
        elif value.startswith(('http://', 'https://')):
            schema['format'] = 'uri'
        schema['example'] = value
        return schema
    if isinstance(value, dict):
        properties = {key: _schema_from_value(item) for key, item in value.items()}
        if not properties:
            return {'type': 'object', 'additionalProperties': True, 'example': value}
        return {'type': 'object', 'properties': properties, 'example': value}
    if isinstance(value, list):
        if value:
            return {'type': 'array', 'items': _schema_from_value(value[0]), 'example': value}
        return {'type': 'array', 'items': {}, 'example': value}
    return {'type': 'string', 'nullable': True}


# ---------------------------------------------------------------------------
# summary helpers
# ---------------------------------------------------------------------------
def _humanize(token):
    words = [word for word in re.split(r'[-_]', token) if word]
    return ' '.join(ACRONYMS.get(word.lower(), word.capitalize()) for word in words)


def _summary_from_operation_id(operation_id, method, path):
    if operation_id:
        tokens = operation_id.split('_')
        action = None
        if len(tokens) >= 2 and tokens[-2:] == ['partial', 'update']:
            action, tokens = 'partial_update', tokens[:-2]
        elif len(tokens) >= 2 and tokens[-1] in VERB_BY_ACTION:
            action, tokens = tokens[-1], tokens[:-1]
        # Keep the module prefix: "List Attendance Logs" reads better than
        # the ambiguous "List Logs".
        noun = ' '.join(_humanize(token) for token in tokens)
        if noun:
            verb = VERB_BY_ACTION.get(action)
            return f'{verb} {noun}' if verb else noun
    return f'{method.upper()} {path}'


# ---------------------------------------------------------------------------
# hook
# ---------------------------------------------------------------------------
def ensure_schema_and_examples(result, generator, request, public):
    """Entry point referenced from ``SPECTACULAR_SETTINGS['POSTPROCESSING_HOOKS']``."""
    schemas = ((result.get('components') or {}).get('schemas') or {})

    for path, item in (result.get('paths') or {}).items():
        for method, operation in item.items():
            if method not in HTTP_METHODS:
                continue

            if not operation.get('summary'):
                operation['summary'] = _summary_from_operation_id(
                    operation.get('operationId'), method, path
                )

            responses = operation.setdefault('responses', {})
            for status, response in responses.items():
                content = response.get('content')
                if not content:
                    if status in NO_BODY_STATUSES or method == 'delete':
                        continue
                    content = response['content'] = {'application/json': {}}
                for media in content.values():
                    _fill_media(media, schemas)

    return result


def _fill_media(media, schemas):
    example = media.get('example')
    examples = media.get('examples') or {}
    if example is None and examples:
        first = next(iter(examples.values()), {})
        example = first.get('value') if isinstance(first, dict) else first

    if example is not None:
        if _is_unmodeled(media.get('schema'), schemas):
            media['schema'] = _schema_from_value(example)
        if 'example' not in media and 'examples' not in media:
            media['example'] = example
        return

    if not _is_unmodeled(media.get('schema'), schemas):
        generated = _example_from_schema(media['schema'], schemas)
        if generated is not None:
            media['example'] = generated
        return

    media['schema'] = {'type': 'object', 'additionalProperties': True}
    media['example'] = {}
