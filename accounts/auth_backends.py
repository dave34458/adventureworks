from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class EmailBackend(ModelBackend):
    """Authenticate with the account email address."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        user_model = get_user_model()
        email = username or kwargs.get("email")
        if email is None or password is None:
            return None

        user = user_model.objects.filter(email__iexact=email.strip()).first()
        if user is None:
            user_model().set_password(password)
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
