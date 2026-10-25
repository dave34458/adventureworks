"""
AdventureWorks (2025 build) as Django models, generated from Microsoft's instawdb.sql
by gen_models.py. Do not edit by hand; re-run the generator instead.

Design notes:
  * Tables keep their original single-column primary keys.
  * Tables with composite keys get either their identity column or a new `id` as the
    primary key, and the original key columns become a UniqueConstraint.
  * Computed SQL Server columns are GeneratedFields (LineTotal, TotalDue, StockedQty) or
    read-only stored columns (SalesOrderNumber, AccountNumber, hierarchy levels).
  * CHECK constraints that translate to Django are included; ones that use GETDATE()/LIKE
    are listed in a comment on each model.
  * Binary photo/document columns are BinaryFields; hierarchyid values are hex text.
"""
import uuid
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.db.models import ExpressionWrapper, F
from django.utils import timezone


class UserManager(BaseUserManager):
    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("The email address is required.")
        email = self.normalize_email(email).strip().lower()
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_active", True)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields["is_staff"] = True
        extra_fields["is_superuser"] = True
        extra_fields.setdefault("is_active", True)
        return self._create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True, max_length=254)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ()

    class Meta:
        db_table = "auth_user"
        verbose_name = "user"
        verbose_name_plural = "users"

    def __str__(self):
        return self.email

    def clean(self):
        super().clean()
        self.email = self.email.strip().lower()

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def get_short_name(self):
        return self.first_name



class PersonAddress(models.Model):
    address_id = models.AutoField(db_column='AddressID', primary_key=True)
    address_line1 = models.CharField(db_column='AddressLine1', max_length=60)
    address_line2 = models.CharField(db_column='AddressLine2', null=True, blank=True, max_length=60)
    city = models.CharField(db_column='City', max_length=30)
    state_province = models.ForeignKey('PersonStateProvince', models.PROTECT, db_column='StateProvinceID')
    postal_code = models.CharField(db_column='PostalCode', max_length=15)
    spatial_location = models.TextField(db_column='SpatialLocation', null=True, blank=True, editable=False)
    rowguid = models.UUIDField(db_column='rowguid', unique=True, default=uuid.uuid4, editable=False)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Person_Address'
        constraints = [
            models.UniqueConstraint(fields=['address_line1', 'address_line2', 'city', 'state_province', 'postal_code'], name='uq_person_address_address_line1_address_line2_city_state_province_id_postal_code'[:100]),
        ]

    def __str__(self):
        return f"{self.address_line1}, {self.city}"








class PersonBusinessEntity(models.Model):
    business_entity_id = models.AutoField(db_column='BusinessEntityID', primary_key=True)
    rowguid = models.UUIDField(db_column='rowguid', unique=True, default=uuid.uuid4, editable=False)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Person_BusinessEntity'

    def __str__(self):
        return f"PersonBusinessEntity {self.pk}"










class PersonCountryRegion(models.Model):
    country_region_code = models.CharField(db_column='CountryRegionCode', primary_key=True, max_length=3)
    name = models.CharField(db_column='Name', unique=True, max_length=50)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Person_CountryRegion'

    def __str__(self):
        return str(self.name)










class SalesCustomer(models.Model):
    customer_id = models.AutoField(db_column='CustomerID', primary_key=True)
    person = models.ForeignKey('Person', models.PROTECT, db_column='PersonID', null=True, blank=True)
    store = models.ForeignKey('SalesStore', models.PROTECT, db_column='StoreID', null=True, blank=True)
    territory = models.ForeignKey('SalesTerritory', models.PROTECT, db_column='TerritoryID', null=True, blank=True)
    account_number = models.CharField(db_column='AccountNumber', unique=True, editable=False, max_length=10)
    rowguid = models.UUIDField(db_column='rowguid', unique=True, default=uuid.uuid4, editable=False)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Sales_Customer'

    def __str__(self):
        if self.person_id:
            return str(self.person)
        if self.store_id:
            return str(self.store)
        return f"Customer {self.pk}"






















class Person(models.Model):
    business_entity = models.OneToOneField('PersonBusinessEntity', models.PROTECT, db_column='BusinessEntityID', primary_key=True)
    person_type = models.CharField(db_column='PersonType', max_length=2)
    name_style = models.BooleanField(db_column='NameStyle', default=False)
    title = models.CharField(db_column='Title', null=True, blank=True, max_length=8)
    first_name = models.CharField(db_column='FirstName', max_length=50)
    middle_name = models.CharField(db_column='MiddleName', null=True, blank=True, max_length=50)
    last_name = models.CharField(db_column='LastName', max_length=50)
    suffix = models.CharField(db_column='Suffix', null=True, blank=True, max_length=10)
    email_promotion = models.IntegerField(db_column='EmailPromotion', default=0)
    additional_contact_info = models.TextField(db_column='AdditionalContactInfo', null=True, blank=True)
    demographics = models.TextField(db_column='Demographics', null=True, blank=True)
    rowguid = models.UUIDField(db_column='rowguid', unique=True, default=uuid.uuid4, editable=False)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Person_Person'
        constraints = [
            models.CheckConstraint(condition=(models.Q(email_promotion__gte=0) & models.Q(email_promotion__lte=2)), name='CK_Person_EmailPromotion'),
            models.CheckConstraint(condition=(models.Q(person_type__isnull=True) | models.Q(person_type__in=['SC', 'VC', 'IN', 'EM', 'SP', 'GC', 'sc', 'vc', 'in', 'em', 'sp', 'gc'])), name='CK_Person_PersonType'),
        ]

    def __str__(self):
        return f"{self.first_name} {self.last_name}"








class ProductionProduct(models.Model):
    product_id = models.AutoField(db_column='ProductID', primary_key=True)
    name = models.CharField(db_column='Name', unique=True, max_length=50)
    product_number = models.CharField(db_column='ProductNumber', unique=True, max_length=25)
    make_flag = models.BooleanField(db_column='MakeFlag', default=True)
    finished_goods_flag = models.BooleanField(db_column='FinishedGoodsFlag', default=True)
    color = models.CharField(db_column='Color', null=True, blank=True, max_length=15)
    safety_stock_level = models.SmallIntegerField(db_column='SafetyStockLevel')
    reorder_point = models.SmallIntegerField(db_column='ReorderPoint')
    standard_cost = models.DecimalField(db_column='StandardCost', max_digits=19, decimal_places=4)
    list_price = models.DecimalField(db_column='ListPrice', max_digits=19, decimal_places=4)
    size = models.CharField(db_column='Size', null=True, blank=True, max_length=5)
    weight = models.DecimalField(db_column='Weight', null=True, blank=True, max_digits=8, decimal_places=2)
    days_to_manufacture = models.IntegerField(db_column='DaysToManufacture')
    product_line = models.CharField(db_column='ProductLine', null=True, blank=True, max_length=2)
    class_field = models.CharField(db_column='Class', null=True, blank=True, max_length=2)
    style = models.CharField(db_column='Style', null=True, blank=True, max_length=2)
    product_subcategory = models.ForeignKey('ProductionProductSubcategory', models.PROTECT, db_column='ProductSubcategoryID', null=True, blank=True)
    sell_start_date = models.DateTimeField(db_column='SellStartDate')
    sell_end_date = models.DateTimeField(db_column='SellEndDate', null=True, blank=True)
    discontinued_date = models.DateTimeField(db_column='DiscontinuedDate', null=True, blank=True)
    rowguid = models.UUIDField(db_column='rowguid', unique=True, default=uuid.uuid4, editable=False)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Production_Product'
        constraints = [
            models.CheckConstraint(condition=models.Q(safety_stock_level__gt=0), name='CK_Product_SafetyStockLevel'),
            models.CheckConstraint(condition=models.Q(reorder_point__gt=0), name='CK_Product_ReorderPoint'),
            models.CheckConstraint(condition=models.Q(standard_cost__gte=0.00), name='CK_Product_StandardCost'),
            models.CheckConstraint(condition=models.Q(list_price__gte=0.00), name='CK_Product_ListPrice'),
            models.CheckConstraint(condition=models.Q(weight__gt=0.00), name='CK_Product_Weight'),
            models.CheckConstraint(condition=models.Q(days_to_manufacture__gte=0), name='CK_Product_DaysToManufacture'),
            models.CheckConstraint(condition=(models.Q(product_line__in=['S', 'T', 'M', 'R', 's', 't', 'm', 'r']) | models.Q(product_line__isnull=True)), name='CK_Product_ProductLine'),
            models.CheckConstraint(condition=(models.Q(class_field__in=['L', 'M', 'H', 'l', 'm', 'h']) | models.Q(class_field__isnull=True)), name='CK_Product_Class'),
            models.CheckConstraint(condition=(models.Q(style__in=['W', 'M', 'U', 'w', 'm', 'u']) | models.Q(style__isnull=True)), name='CK_Product_Style'),
            models.CheckConstraint(condition=(models.Q(sell_end_date__gte=F('sell_start_date')) | models.Q(sell_end_date__isnull=True)), name='CK_Product_SellEndDate'),
        ]

    def __str__(self):
        return self.name


class ProductionProductCategory(models.Model):
    product_category_id = models.AutoField(db_column='ProductCategoryID', primary_key=True)
    name = models.CharField(db_column='Name', unique=True, max_length=50)
    rowguid = models.UUIDField(db_column='rowguid', unique=True, default=uuid.uuid4, editable=False)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Production_ProductCategory'

    def __str__(self):
        return str(self.name)


class ProductionProductCostHistory(models.Model):
    id = models.AutoField(primary_key=True)
    product = models.ForeignKey('ProductionProduct', models.PROTECT, db_column='ProductID')
    start_date = models.DateTimeField(db_column='StartDate')
    end_date = models.DateTimeField(db_column='EndDate', null=True, blank=True)
    standard_cost = models.DecimalField(db_column='StandardCost', max_digits=19, decimal_places=4)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Production_ProductCostHistory'
        constraints = [
            models.UniqueConstraint(fields=['product', 'start_date'], name='uq_production_productcosthistory_key'),
            models.CheckConstraint(condition=(models.Q(end_date__gte=F('start_date')) | models.Q(end_date__isnull=True)), name='CK_ProductCostHistory_EndDate'),
            models.CheckConstraint(condition=models.Q(standard_cost__gte=0.00), name='CK_ProductCostHistory_StandardCost'),
        ]

    def __str__(self):
        return str(self.product)






















class ProductionProductSubcategory(models.Model):
    product_subcategory_id = models.AutoField(db_column='ProductSubcategoryID', primary_key=True)
    product_category = models.ForeignKey('ProductionProductCategory', models.PROTECT, db_column='ProductCategoryID')
    name = models.CharField(db_column='Name', unique=True, max_length=50)
    rowguid = models.UUIDField(db_column='rowguid', unique=True, default=uuid.uuid4, editable=False)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Production_ProductSubcategory'

    def __str__(self):
        return str(self.name)




class PurchasingPurchaseOrderDetail(models.Model):
    purchase_order = models.ForeignKey('PurchasingPurchaseOrderHeader', models.PROTECT, db_column='PurchaseOrderID')
    purchase_order_detail_id = models.AutoField(db_column='PurchaseOrderDetailID', primary_key=True)
    due_date = models.DateTimeField(db_column='DueDate')
    order_qty = models.SmallIntegerField(db_column='OrderQty')
    product = models.ForeignKey('ProductionProduct', models.PROTECT, db_column='ProductID')
    unit_price = models.DecimalField(db_column='UnitPrice', max_digits=19, decimal_places=4)
    line_total = models.GeneratedField(expression=ExpressionWrapper(F('order_qty') * F('unit_price'), output_field=models.DecimalField(max_digits=19, decimal_places=4)), output_field=models.DecimalField(max_digits=19, decimal_places=4), db_persist=True, db_column='LineTotal')
    received_qty = models.DecimalField(db_column='ReceivedQty', max_digits=8, decimal_places=2)
    rejected_qty = models.DecimalField(db_column='RejectedQty', max_digits=8, decimal_places=2)
    stocked_qty = models.GeneratedField(expression=ExpressionWrapper(F('received_qty') - F('rejected_qty'), output_field=models.DecimalField(max_digits=9, decimal_places=2)), output_field=models.DecimalField(max_digits=9, decimal_places=2), db_persist=True, db_column='StockedQty')
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Purchasing_PurchaseOrderDetail'
        constraints = [
            models.CheckConstraint(condition=models.Q(order_qty__gt=0), name='CK_PurchaseOrderDetail_OrderQty'),
            models.CheckConstraint(condition=models.Q(unit_price__gte=0.00), name='CK_PurchaseOrderDetail_UnitPrice'),
            models.CheckConstraint(condition=models.Q(received_qty__gte=0.00), name='CK_PurchaseOrderDetail_ReceivedQty'),
            models.CheckConstraint(condition=models.Q(rejected_qty__gte=0.00), name='CK_PurchaseOrderDetail_RejectedQty'),
        ]

    def __str__(self):
        return f"PurchasingPurchaseOrderDetail {self.pk}"


class PurchasingPurchaseOrderHeader(models.Model):
    purchase_order_id = models.AutoField(db_column='PurchaseOrderID', primary_key=True)
    revision_number = models.PositiveSmallIntegerField(db_column='RevisionNumber', default=0)
    status = models.PositiveSmallIntegerField(db_column='Status', default=1)
    vendor = models.ForeignKey('PurchasingVendor', models.PROTECT, db_column='VendorID')
    order_date = models.DateTimeField(db_column='OrderDate', default=timezone.now)
    ship_date = models.DateTimeField(db_column='ShipDate', null=True, blank=True)
    sub_total = models.DecimalField(db_column='SubTotal', max_digits=19, decimal_places=4, default=Decimal('0.00'))
    tax_amt = models.DecimalField(db_column='TaxAmt', max_digits=19, decimal_places=4, default=Decimal('0.00'))
    freight = models.DecimalField(db_column='Freight', max_digits=19, decimal_places=4, default=Decimal('0.00'))
    total_due = models.GeneratedField(expression=ExpressionWrapper(F('sub_total') + F('tax_amt') + F('freight'), output_field=models.DecimalField(max_digits=19, decimal_places=4)), output_field=models.DecimalField(max_digits=19, decimal_places=4), db_persist=True, db_column='TotalDue')
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Purchasing_PurchaseOrderHeader'
        constraints = [
            models.CheckConstraint(condition=(models.Q(status__gte=1) & models.Q(status__lte=4)), name='CK_PurchaseOrderHeader_Status'),
            models.CheckConstraint(condition=(models.Q(ship_date__gte=F('order_date')) | models.Q(ship_date__isnull=True)), name='CK_PurchaseOrderHeader_ShipDate'),
            models.CheckConstraint(condition=models.Q(sub_total__gte=0.00), name='CK_PurchaseOrderHeader_SubTotal'),
            models.CheckConstraint(condition=models.Q(tax_amt__gte=0.00), name='CK_PurchaseOrderHeader_TaxAmt'),
            models.CheckConstraint(condition=models.Q(freight__gte=0.00), name='CK_PurchaseOrderHeader_Freight'),
        ]

    def __str__(self):
        return f"PO{self.pk}"


class SalesOrderDetail(models.Model):
    sales_order = models.ForeignKey('SalesOrderHeader', models.PROTECT, db_column='SalesOrderID')
    sales_order_detail_id = models.AutoField(db_column='SalesOrderDetailID', primary_key=True)
    carrier_tracking_number = models.CharField(db_column='CarrierTrackingNumber', null=True, blank=True, max_length=25)
    order_qty = models.SmallIntegerField(db_column='OrderQty')
    product = models.ForeignKey('ProductionProduct', models.PROTECT, db_column='ProductID')
    unit_price = models.DecimalField(db_column='UnitPrice', max_digits=19, decimal_places=4)
    unit_price_discount = models.DecimalField(db_column='UnitPriceDiscount', max_digits=19, decimal_places=4, default=Decimal('0.0'))
    line_total = models.GeneratedField(expression=ExpressionWrapper(F('unit_price') * (1 - F('unit_price_discount')) * F('order_qty'), output_field=models.DecimalField(max_digits=38, decimal_places=6)), output_field=models.DecimalField(max_digits=38, decimal_places=6), db_persist=True, db_column='LineTotal')
    rowguid = models.UUIDField(db_column='rowguid', unique=True, default=uuid.uuid4, editable=False)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Sales_SalesOrderDetail'
        constraints = [
            models.CheckConstraint(condition=models.Q(order_qty__gt=0), name='CK_SalesOrderDetail_OrderQty'),
            models.CheckConstraint(condition=models.Q(unit_price__gte=0.00), name='CK_SalesOrderDetail_UnitPrice'),
            models.CheckConstraint(condition=models.Q(unit_price_discount__gte=0.00), name='CK_SalesOrderDetail_UnitPriceDiscount'),
        ]


    def __str__(self):
        return f"SalesOrderDetail {self.pk}"


class SalesOrderHeader(models.Model):
    sales_order_id = models.AutoField(db_column='SalesOrderID', primary_key=True)
    revision_number = models.PositiveSmallIntegerField(db_column='RevisionNumber', default=0)
    order_date = models.DateTimeField(db_column='OrderDate', default=timezone.now)
    due_date = models.DateTimeField(db_column='DueDate')
    ship_date = models.DateTimeField(db_column='ShipDate', null=True, blank=True)
    status = models.PositiveSmallIntegerField(db_column='Status', default=1)
    online_order_flag = models.BooleanField(db_column='OnlineOrderFlag', default=True)
    sales_order_number = models.CharField(db_column='SalesOrderNumber', unique=True, editable=False, max_length=25)
    purchase_order_number = models.CharField(db_column='PurchaseOrderNumber', null=True, blank=True, max_length=25)
    account_number = models.CharField(db_column='AccountNumber', null=True, blank=True, max_length=15)
    customer = models.ForeignKey('SalesCustomer', models.PROTECT, db_column='CustomerID')
    territory = models.ForeignKey('SalesTerritory', models.PROTECT, db_column='TerritoryID', null=True, blank=True)
    bill_to_address = models.ForeignKey('PersonAddress', models.PROTECT, db_column='BillToAddressID', related_name='salesorderheader_bill_to_address_set')
    ship_to_address = models.ForeignKey('PersonAddress', models.PROTECT, db_column='ShipToAddressID', related_name='salesorderheader_ship_to_address_set')
    credit_card_approval_code = models.CharField(db_column='CreditCardApprovalCode', null=True, blank=True, max_length=15)
    sub_total = models.DecimalField(db_column='SubTotal', max_digits=19, decimal_places=4, default=Decimal('0.00'))
    tax_amt = models.DecimalField(db_column='TaxAmt', max_digits=19, decimal_places=4, default=Decimal('0.00'))
    freight = models.DecimalField(db_column='Freight', max_digits=19, decimal_places=4, default=Decimal('0.00'))
    total_due = models.GeneratedField(expression=ExpressionWrapper(F('sub_total') + F('tax_amt') + F('freight'), output_field=models.DecimalField(max_digits=19, decimal_places=4)), output_field=models.DecimalField(max_digits=19, decimal_places=4), db_persist=True, db_column='TotalDue')
    comment = models.CharField(db_column='Comment', null=True, blank=True, max_length=128)
    rowguid = models.UUIDField(db_column='rowguid', unique=True, default=uuid.uuid4, editable=False)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Sales_SalesOrderHeader'
        constraints = [
            models.CheckConstraint(condition=(models.Q(status__gte=0) & models.Q(status__lte=8)), name='CK_SalesOrderHeader_Status'),
            models.CheckConstraint(condition=models.Q(due_date__gte=F('order_date')), name='CK_SalesOrderHeader_DueDate'),
            models.CheckConstraint(condition=(models.Q(ship_date__gte=F('order_date')) | models.Q(ship_date__isnull=True)), name='CK_SalesOrderHeader_ShipDate'),
            models.CheckConstraint(condition=models.Q(sub_total__gte=0.00), name='CK_SalesOrderHeader_SubTotal'),
            models.CheckConstraint(condition=models.Q(tax_amt__gte=0.00), name='CK_SalesOrderHeader_TaxAmt'),
            models.CheckConstraint(condition=models.Q(freight__gte=0.00), name='CK_SalesOrderHeader_Freight'),
        ]

    def __str__(self):
        return self.sales_order_number or f"SO{self.pk}"












class SalesTerritory(models.Model):
    territory_id = models.AutoField(db_column='TerritoryID', primary_key=True)
    name = models.CharField(db_column='Name', unique=True, max_length=50)
    country_region = models.ForeignKey('PersonCountryRegion', models.PROTECT, db_column='CountryRegionCode')
    group = models.CharField(db_column='Group', max_length=50)
    sales_ytd = models.DecimalField(db_column='SalesYTD', max_digits=19, decimal_places=4, default=Decimal('0.00'))
    sales_last_year = models.DecimalField(db_column='SalesLastYear', max_digits=19, decimal_places=4, default=Decimal('0.00'))
    cost_ytd = models.DecimalField(db_column='CostYTD', max_digits=19, decimal_places=4, default=Decimal('0.00'))
    cost_last_year = models.DecimalField(db_column='CostLastYear', max_digits=19, decimal_places=4, default=Decimal('0.00'))
    rowguid = models.UUIDField(db_column='rowguid', unique=True, default=uuid.uuid4, editable=False)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Sales_SalesTerritory'
        constraints = [
            models.CheckConstraint(condition=models.Q(sales_ytd__gte=0.00), name='CK_SalesTerritory_SalesYTD'),
            models.CheckConstraint(condition=models.Q(sales_last_year__gte=0.00), name='CK_SalesTerritory_SalesLastYear'),
            models.CheckConstraint(condition=models.Q(cost_ytd__gte=0.00), name='CK_SalesTerritory_CostYTD'),
            models.CheckConstraint(condition=models.Q(cost_last_year__gte=0.00), name='CK_SalesTerritory_CostLastYear'),
        ]

    def __str__(self):
        return str(self.name)




class ProductionScrapReason(models.Model):
    scrap_reason_id = models.AutoField(db_column='ScrapReasonID', primary_key=True)
    name = models.CharField(db_column='Name', unique=True, max_length=50)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Production_ScrapReason'

    def __str__(self):
        return str(self.name)












class PersonStateProvince(models.Model):
    state_province_id = models.AutoField(db_column='StateProvinceID', primary_key=True)
    state_province_code = models.CharField(db_column='StateProvinceCode', max_length=3)
    country_region = models.ForeignKey('PersonCountryRegion', models.PROTECT, db_column='CountryRegionCode')
    is_only_state_province_flag = models.BooleanField(db_column='IsOnlyStateProvinceFlag', default=True)
    name = models.CharField(db_column='Name', unique=True, max_length=50)
    territory = models.ForeignKey('SalesTerritory', models.PROTECT, db_column='TerritoryID')
    rowguid = models.UUIDField(db_column='rowguid', unique=True, default=uuid.uuid4, editable=False)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Person_StateProvince'
        constraints = [
            models.UniqueConstraint(fields=['state_province_code', 'country_region'], name='uq_person_stateprovince_state_province_code_country_region_code'[:100]),
        ]

    def __str__(self):
        return str(self.name)


class SalesStore(models.Model):
    business_entity = models.OneToOneField('PersonBusinessEntity', models.PROTECT, db_column='BusinessEntityID', primary_key=True)
    name = models.CharField(db_column='Name', max_length=50)
    demographics = models.TextField(db_column='Demographics', null=True, blank=True)
    rowguid = models.UUIDField(db_column='rowguid', unique=True, default=uuid.uuid4, editable=False)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Sales_Store'

    def __str__(self):
        return self.name








class PurchasingVendor(models.Model):
    business_entity = models.OneToOneField('PersonBusinessEntity', models.PROTECT, db_column='BusinessEntityID', primary_key=True)
    account_number = models.CharField(db_column='AccountNumber', unique=True, max_length=15)
    name = models.CharField(db_column='Name', max_length=50)
    credit_rating = models.PositiveSmallIntegerField(db_column='CreditRating')
    preferred_vendor_status = models.BooleanField(db_column='PreferredVendorStatus', default=True)
    active_flag = models.BooleanField(db_column='ActiveFlag', default=True)
    purchasing_web_service_url = models.CharField(db_column='PurchasingWebServiceURL', null=True, blank=True, max_length=1024)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Purchasing_Vendor'
        constraints = [
            models.CheckConstraint(condition=(models.Q(credit_rating__gte=1) & models.Q(credit_rating__lte=5)), name='CK_Vendor_CreditRating'),
        ]

    def __str__(self):
        return self.name


class ProductionWorkOrder(models.Model):
    work_order_id = models.AutoField(db_column='WorkOrderID', primary_key=True)
    product = models.ForeignKey('ProductionProduct', models.PROTECT, db_column='ProductID')
    order_qty = models.IntegerField(db_column='OrderQty')
    stocked_qty = models.GeneratedField(expression=ExpressionWrapper(F('order_qty') - F('scrapped_qty'), output_field=models.IntegerField()), output_field=models.IntegerField(), db_persist=True, db_column='StockedQty')
    scrapped_qty = models.SmallIntegerField(db_column='ScrappedQty')
    start_date = models.DateTimeField(db_column='StartDate')
    end_date = models.DateTimeField(db_column='EndDate', null=True, blank=True)
    due_date = models.DateTimeField(db_column='DueDate')
    scrap_reason = models.ForeignKey('ProductionScrapReason', models.PROTECT, db_column='ScrapReasonID', null=True, blank=True)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Production_WorkOrder'
        constraints = [
            models.CheckConstraint(condition=models.Q(order_qty__gt=0), name='CK_WorkOrder_OrderQty'),
            models.CheckConstraint(condition=models.Q(scrapped_qty__gte=0), name='CK_WorkOrder_ScrappedQty'),
            models.CheckConstraint(condition=(models.Q(end_date__gte=F('start_date')) | models.Q(end_date__isnull=True)), name='CK_WorkOrder_EndDate'),
        ]

    def __str__(self):
        return f"WO{self.pk}"




# ---------------------------------------------------------------------------
# Hand-written (not generated): one permission per nav tab.

class TabAccess(models.Model):
    """Holds one permission per nav tab. It has no database table (managed = False):
    it exists only so Django creates the permissions below."""

    class Meta:
        managed = False
        default_permissions = ()
        permissions = [
            ("access_sales", "Can open the Sales tab"),
            ("access_customer_profile", "Can open the Customer profile tab"),
            ("access_revenue_and_loss", "Can open the Revenue and loss tab"),
            ("access_cost", "Can open the Cost tab"),
        ]


# ---------------------------------------------------------------------------
# Hand-written (not generated): privacy notice version and audit trail.

PRIVACY_NOTICE_VERSION = "1.0"


class AuditLog(models.Model):
    """One row per edit or deletion made through the table pages: who changed which
    record, when, and the old and new values. Written by the shared edit and delete
    views; visible read-only at /manage/ and retained for twelve months per the
    privacy notice."""

    ACTIONS = [("create", "create"), ("update", "update"), ("delete", "delete")]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                             on_delete=models.SET_NULL, related_name="audit_log")
    username = models.CharField(max_length=150)  # snapshot: the record survives user deletion
    action = models.CharField(max_length=8, choices=ACTIONS)
    model = models.CharField(max_length=100)
    object_pk = models.CharField(max_length=64)
    object_repr = models.CharField(max_length=255)
    changes = models.JSONField(default=dict, blank=True)  # {field: [old, new]}, or the row on delete
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["model", "object_pk"]), models.Index(fields=["created_at"])]
        verbose_name = "audit record"
        verbose_name_plural = "audit records"

    def __str__(self):
        return f"{self.username} {self.action} {self.model} {self.object_pk}"


# ---------------------------------------------------------------------------
# Hand-written (not generated): saved report snapshots.
#
# One table holds one saved report per module/range. All KPI and panel data lives in
# `payload`. The report views read the saved row instead of running the aggregate SQL,
# which keeps saved pages fast. A range with no snapshot falls back to the live query.


class Report(models.Model):
    """One saved report row. `module` selects the panel; all KPI and panel data lives
    in `payload`."""

    MODULES = [
        ("sales", "Sales"),
        ("customer-profile", "Customer profile"),
        ("revenue-and-loss", "Revenue and loss"),
        ("cost", "Cost"),
    ]

    module = models.CharField(max_length=32, choices=MODULES)
    title = models.CharField(max_length=120, default="")
    range_start = models.DateField()
    range_end = models.DateField()
    compare_start = models.DateField(null=True, blank=True)
    compare_end = models.DateField(null=True, blank=True)
    source_through = models.DateField()
    window_label = models.CharField(max_length=120)
    prev_label = models.CharField(max_length=120)
    period = models.CharField(max_length=120)
    custom = models.BooleanField(default=False)
    payload = models.JSONField(default=dict, encoder=DjangoJSONEncoder)
    schema_version = models.PositiveSmallIntegerField(default=2)

    generated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name="reports")
    generated_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-range_end", "-generated_at"]
        constraints = [
            models.UniqueConstraint(fields=["module", "range_start", "range_end"],
                                    name="uq_report_module_range"),
        ]

    def __str__(self):
        return f"{self.get_module_display()} {self.range_start} \u2013 {self.range_end}"
