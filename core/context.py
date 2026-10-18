from django.urls import reverse

from .tabs import LABELS


def nav(request):
    """Adds the nav tabs the signed-in user may open (a tab appears only with its access_ permission)."""
    user = request.user
    if not user.is_authenticated:
        return {}
    tabs = [(slug, label, reverse("dashboard", args=[slug]))
            for slug, label in LABELS.items() if user.has_perm(f"core.access_{slug}")]
    match = request.resolver_match
    return {"nav": tabs, "tab": match.kwargs.get("tab") if match else None}
