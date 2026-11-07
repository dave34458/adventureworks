from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("reporting", "0005_report_filters")]

    operations = [
        migrations.AlterModelOptions(
            name="tabaccess",
            options={
                "managed": False,
                "default_permissions": (),
                "permissions": [
                    ("access_sales", "Can open the Sales tab"),
                    ("access_customer_profile", "Can open the Customer profile tab"),
                    ("access_revenue_and_loss", "Can open the Revenue and loss tab"),
                    ("access_cost", "Can open the Cost tab"),
                    ("manage_department_users", "Can manage users in the department"),
                ],
            },
        ),
    ]
