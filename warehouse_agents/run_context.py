"""Who and which model the run in progress is for. Set once by Reasoner.run; read by tools that act for the
user (save_memory) or must keep the user's model choice when delegating (investigate_warehouse)."""

import contextvars

CURRENT_USER = contextvars.ContextVar('coinsight_user', default=None)
CURRENT_MODEL = contextvars.ContextVar('coinsight_model', default=None)
