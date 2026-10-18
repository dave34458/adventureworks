from django import forms
from django.forms.utils import flatatt
from django.utils.html import format_html


class SearchSelect(forms.Select):
    """A foreign-key box that fetches records on demand: the page carries one label (the
    current value), not the whole table, and a matching query returns 20 rows at most.
    TableEdit sets .queryset (for the label) and .url (the autocomplete view) per field."""

    class Media:
        js = ["core/autocomplete.js"]

    queryset = None
    url = ""

    def render(self, name, value, attrs=None, renderer=None):
        value = "" if value in (None, "") else str(value)
        obj = self.queryset.filter(pk=value).first() if value and self.queryset is not None else None
        attrs = self.build_attrs(self.attrs, attrs)
        attrs.pop("required", None)  # the visible box holds text, the hidden one the value
        return format_html(
            '<span class="ac"><input type="text"{} value="{}" data-url="{}" autocomplete="off"'
            ' placeholder="search..."><input type="hidden" name="{}" value="{}"></span>',
            flatatt(attrs), str(obj) if obj is not None else value, self.url, name, value,
        )
