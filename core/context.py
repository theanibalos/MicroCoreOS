import contextvars

# Core Context variables for causality and identity tracking
# These are neutral to both Tools and Plugins.
current_event_id_var = contextvars.ContextVar("current_event_id", default=None)
current_identity_var = contextvars.ContextVar("current_identity", default="Unknown")
