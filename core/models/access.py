from django.db import models


class TabAccess(models.Model):
    """Holds one permission per nav tab. It has no database table (managed = False):
    it exists only so Django creates the permissions below."""

    class Meta:
        managed = False
        default_permissions = ()
        permissions = [
            ("access_sales", "Can open the Sales report tab"),
            ("access_customers", "Can open the Customer profile tab"),
            ("access_costs", "Can open the Cost report tab"),
            ("access_finance", "Can open the Revenue and loss tab"),
        ]
