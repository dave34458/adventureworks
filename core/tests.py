from datetime import date, datetime
from decimal import Decimal

from django.apps import apps
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.roles import TABLES
from core.models import (
    Person,
    PersonAddress,
    PersonBusinessEntity,
    PersonCountryRegion,
    PersonStateProvince,
    ProductionProduct,
    ProductionProductCategory,
    ProductionProductCostHistory,
    ProductionProductSubcategory,
    ProductionScrapReason,
    ProductionWorkOrder,
    PurchasingPurchaseOrderDetail,
    PurchasingPurchaseOrderHeader,
    PurchasingVendor,
    SalesCustomer,
    SalesOrderDetail,
    SalesOrderHeader,
    SalesStore,
    SalesTerritory,
)
from reporting.services import shown


User = get_user_model()


class TableColumnTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            email="column-admin@example.com", password="column-admin")

        us = PersonCountryRegion.objects.create(
            country_region_code="US", name="United States")
        canada = PersonCountryRegion.objects.create(
            country_region_code="CA", name="Canada")
        west = SalesTerritory.objects.create(
            name="Northwest", country_region=us, group="North America")
        canada_west = SalesTerritory.objects.create(
            name="Canada West", country_region=canada, group="North America")
        wa = PersonStateProvince.objects.create(
            state_province_code="WA", country_region=us, name="Washington",
            territory=west)
        bc = PersonStateProvince.objects.create(
            state_province_code="BC", country_region=canada, name="British Columbia",
            territory=canada_west)
        address = PersonAddress.objects.create(
            address_line1="1 Main", city="Springfield", state_province=wa,
            postal_code="11111")
        PersonAddress.objects.create(
            address_line1="2 Main", city="Springfield", state_province=bc,
            postal_code="22222")

        category = ProductionProductCategory.objects.create(name="Bikes")
        subcategory = ProductionProductSubcategory.objects.create(
            product_category=category, name="Road Bikes")
        product = ProductionProduct.objects.create(
            name="Test Bike", product_number="TB-1", safety_stock_level=1,
            reorder_point=1, standard_cost=Decimal("50"), list_price=Decimal("100"),
            days_to_manufacture=1, product_subcategory=subcategory,
            sell_start_date=datetime(2022, 1, 1),
        )

        store = SalesStore.objects.create(
            business_entity=PersonBusinessEntity.objects.create(),
            name="Active Store",
            demographics=("<BusinessType>BS</BusinessType><SquareFeet>1000</SquareFeet>"
                          "<NumberEmployees>10</NumberEmployees>"),
        )
        customer = SalesCustomer.objects.create(
            store=store, territory=west, account_number="AW00000001")
        person = Person.objects.create(
            business_entity=PersonBusinessEntity.objects.create(),
            person_type="EM", first_name="Ada", last_name="Lovelace",
        )

        header = SalesOrderHeader.objects.create(
            order_date=datetime(2024, 1, 1), due_date=datetime(2024, 1, 5),
            ship_date=datetime(2024, 1, 2), customer=customer, territory=west,
            bill_to_address=address, ship_to_address=address,
            sales_order_number="SO1", purchase_order_number="PO1",
            account_number="AW00000001", credit_card_approval_code="CC",
            sub_total=Decimal("10"), tax_amt=Decimal("1"), freight=Decimal("1"),
            total_due=Decimal("12"), comment="Test order",
        )
        SalesOrderDetail.objects.create(
            sales_order=header, carrier_tracking_number="TRACK",
            order_qty=1, product=product, unit_price=Decimal("10"),
            unit_price_discount=Decimal("0"), line_total=Decimal("10"),
        )

        vendor = PurchasingVendor.objects.create(
            business_entity=PersonBusinessEntity.objects.create(),
            account_number="VEN1", name="Vendor One", credit_rating=1,
            purchasing_web_service_url="https://example.com",
        )
        purchase_order = PurchasingPurchaseOrderHeader.objects.create(
            vendor=vendor, order_date=datetime(2024, 2, 1),
            ship_date=datetime(2024, 2, 2), sub_total=Decimal("10"),
            tax_amt=Decimal("1"), freight=Decimal("1"), total_due=Decimal("12"),
        )
        PurchasingPurchaseOrderDetail.objects.create(
            purchase_order=purchase_order, due_date=datetime(2024, 2, 3),
            order_qty=1, product=product, unit_price=Decimal("10"),
            line_total=Decimal("10"), received_qty=Decimal("1"),
            rejected_qty=Decimal("0"), stocked_qty=Decimal("1"),
        )

        reason = ProductionScrapReason.objects.create(name="Bad part")
        ProductionWorkOrder.objects.create(
            product=product, order_qty=1, stocked_qty=1, scrapped_qty=1,
            start_date=datetime(2024, 3, 1), end_date=datetime(2024, 3, 2),
            due_date=datetime(2024, 3, 3), scrap_reason=reason,
        )
        ProductionProductCostHistory.objects.create(
            product=product, start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 12, 31), standard_cost=Decimal("50"),
        )

        cls.rows = {
            "SalesOrderHeader": header,
            "SalesOrderDetail": SalesOrderDetail.objects.get(),
            "SalesTerritory": west,
            "SalesCustomer": customer,
            "Person": person,
            "PersonBusinessEntity": PersonBusinessEntity.objects.first(),
            "PersonAddress": address,
            "SalesStore": store,
            "PersonStateProvince": wa,
            "PersonCountryRegion": us,
            "ProductionProduct": product,
            "ProductionProductSubcategory": subcategory,
            "ProductionProductCategory": category,
            "PurchasingPurchaseOrderHeader": purchase_order,
            "PurchasingPurchaseOrderDetail": PurchasingPurchaseOrderDetail.objects.get(),
            "PurchasingVendor": vendor,
            "ProductionWorkOrder": ProductionWorkOrder.objects.get(),
            "ProductionProductCostHistory": ProductionProductCostHistory.objects.get(),
            "ProductionScrapReason": reason,
        }

    def setUp(self):
        self.client.force_login(self.admin)

    @staticmethod
    def all_models():
        for tab, names in TABLES.items():
            for name in names:
                yield tab, apps.get_model("core", name)

    def edit_url(self, tab, model):
        return reverse("table_edit", args=[tab, model.__name__, self.rows[model.__name__].pk])

    def form_data(self, obj, form):
        data = {}
        for name in form.fields:
            field = obj._meta.get_field(name)
            value = getattr(obj, field.attname)
            if value is None:
                data[name] = ""
            elif isinstance(value, bool):
                data[name] = "True" if value else "False"
            elif isinstance(value, datetime):
                data[name] = value.isoformat(sep=" ")
            elif isinstance(value, date):
                data[name] = value.isoformat()
            else:
                data[name] = str(value)
        return data

    def test_every_table_detail_shows_every_column(self):
        for tab, model in self.all_models():
            obj = self.rows[model.__name__]
            response = self.client.get(
                reverse("table_detail", args=[tab, model.__name__, obj.pk]))
            self.assertEqual(response.status_code, 200, model.__name__)
            fields = shown(model)
            self.assertEqual(len(response.context["fields"]), len(fields), model.__name__)
            body = response.content.decode()
            for field in fields:
                self.assertIn(field.verbose_name, body, f"{model.__name__}.{field.name}")

    def test_every_editable_column_is_in_the_edit_form(self):
        for tab, model in self.all_models():
            response = self.client.get(self.edit_url(tab, model))
            self.assertEqual(response.status_code, 200, model.__name__)
            form = response.context["form"]
            expected = {
                f.name for f in model._meta.fields
                if f.editable and not f.primary_key and f.name != "modified_date"
            }
            self.assertEqual(set(form.fields), expected, model.__name__)

    def test_every_editable_column_can_be_saved(self):
        for tab, model in self.all_models():
            obj = self.rows[model.__name__]
            response = self.client.get(self.edit_url(tab, model))
            form = response.context["form"]
            response = self.client.post(self.edit_url(tab, model), self.form_data(obj, form))
            if response.status_code != 302:
                errors = response.context["form"].errors if response.context else None
                self.fail(f"{model.__name__} edit failed: {errors}")

    def test_every_column_can_be_searched_and_sorted(self):
        for tab, model in self.all_models():
            obj = self.rows[model.__name__]
            url = reverse("table_list", args=[tab, model.__name__])
            for field in model._meta.fields:
                if field.get_internal_type() == "BinaryField":
                    continue
                value = getattr(obj, field.attname)
                if value is None:
                    query = "x"
                elif isinstance(value, bool):
                    query = "True" if value else "False"
                elif isinstance(value, datetime):
                    query = value.isoformat(sep=" ")
                elif isinstance(value, date):
                    query = value.isoformat()
                else:
                    query = str(value)
                response = self.client.get(url, {"col": field.name, "q": query})
                self.assertEqual(
                    response.status_code, 200, f"{model.__name__}.{field.name} search")
                response = self.client.get(url, {"sort": field.name})
                self.assertEqual(
                    response.status_code, 200, f"{model.__name__}.{field.name} sort")
