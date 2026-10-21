"""Dependency-light action schemas shared by serving and offline fine-tuning."""

SCHEMAS = {
    'service_health': {'type': 'object', 'properties': {}, 'additionalProperties': False},
    'model_health': {
        'type': 'object',
        'properties': {'cutoff': {'type': 'string'}},
        'additionalProperties': False,
    },
    'warehouse_coverage': {
        'type': 'object',
        'properties': {
            'symbol': {'type': 'string', 'enum': ['BTC', 'ETH', 'SOL']},
            'hours': {'type': 'integer', 'minimum': 1, 'maximum': 168},
        },
        'additionalProperties': False,
    },
    'search_runbooks': {
        'type': 'object',
        'properties': {
            'query': {'type': 'string', 'minLength': 1, 'maxLength': 2000},
            'top_k': {'type': 'integer', 'minimum': 1, 'maximum': 5},
        },
        'required': ['query'],
        'additionalProperties': False,
    },
}
