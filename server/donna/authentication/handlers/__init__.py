"""
Per-provider OAuth login handlers.

v1 ships only Google login. Add HubSpot / Microsoft / GitHub etc. by
dropping a new ``<provider>.py`` module and registering it in
``AuthService.HANDLERS``.
"""
