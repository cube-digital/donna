"""
Auth-flow signals — decouple views from email dispatch.

Views emit signals; ``receivers.py`` listens and sends mail via Django's
``send_mail``. This lets us swap the email backend (console → SMTP →
provider X) without touching views, and makes it easy to fan out (e.g.,
in-app notification + email) later.
"""
from django.dispatch import Signal


# Sent by ``ResetPasswordView`` after the token is persisted.
# Receivers send the recovery link by email.
reset_password_recover = Signal()       # kwargs: instance, reset_password_token

# Sent by ``ResetPasswordConfirmView`` after the password is reset.
# Receivers can send a "your password was changed" confirmation email.
reset_password_confirm = Signal()       # kwargs: user

# Sent by ``EmailVerifyRequestView`` after the token is persisted.
# Receivers send the verification link by email.
email_verify_request = Signal()         # kwargs: instance, verification_token
