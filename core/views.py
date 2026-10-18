from django.contrib.auth.mixins import PermissionRequiredMixin
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.generic import TemplateView

from .tabs import LABELS, TAB_MODULES, TABS, visible_tables


def home(request):
    """Send the user to the first tab they may open, or explain that they have none."""
    for slug in LABELS:
        if request.user.has_perm(f"core.access_{slug}"):
            return redirect("dashboard", slug)
    return render(request, "core/no_access.html")


class Dashboard(PermissionRequiredMixin, TemplateView):
    """One dashboard page per tab (bare for now). Its data comes from core/tabs/<tab>.py."""
    template_name = "core/dashboard.html"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.tab = kwargs["tab"]
        if self.tab not in TABS:
            raise Http404

    def get_permission_required(self):
        return [f"core.access_{self.tab}"]

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        ctx.update(TAB_MODULES[self.tab].context(self.request))
        ctx.update(tab=self.tab, title=LABELS[self.tab], tab_label=LABELS[self.tab],
                   tables=visible_tables(self.request.user, self.tab))
        return ctx
