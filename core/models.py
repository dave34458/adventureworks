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

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import ExpressionWrapper, F
from django.utils import timezone

class dboDatabaseLog(models.Model):
    database_log_id = models.AutoField(db_column='DatabaseLogID', primary_key=True)
    post_time = models.DateTimeField(db_column='PostTime')
    database_user = models.CharField(db_column='DatabaseUser', max_length=128)
    event = models.CharField(db_column='Event', max_length=128)
    schema = models.CharField(db_column='Schema', null=True, blank=True, max_length=128)
    object = models.CharField(db_column='Object', null=True, blank=True, max_length=128)
    tsql = models.TextField(db_column='TSQL')
    xml_event = models.TextField(db_column='XmlEvent')

    class Meta:
        db_table = 'dbo_DatabaseLog'

    def __str__(self):
        return f"{self.event} {self.object or ''}".strip()


class dboErrorLog(models.Model):
    error_log_id = models.AutoField(db_column='ErrorLogID', primary_key=True)
    error_time = models.DateTimeField(db_column='ErrorTime', default=timezone.now)
    user_name = models.CharField(db_column='UserName', max_length=128)
    error_number = models.IntegerField(db_column='ErrorNumber')
    error_severity = models.IntegerField(db_column='ErrorSeverity', null=True, blank=True)
    error_state = models.IntegerField(db_column='ErrorState', null=True, blank=True)
    error_procedure = models.CharField(db_column='ErrorProcedure', null=True, blank=True, max_length=126)
    error_line = models.IntegerField(db_column='ErrorLine', null=True, blank=True)
    error_message = models.CharField(db_column='ErrorMessage', max_length=4000)

    class Meta:
        db_table = 'dbo_ErrorLog'

    def __str__(self):
        return (self.error_message or '')[:60]


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


class PersonAddressType(models.Model):
    address_type_id = models.AutoField(db_column='AddressTypeID', primary_key=True)
    name = models.CharField(db_column='Name', unique=True, max_length=50)
    rowguid = models.UUIDField(db_column='rowguid', unique=True, default=uuid.uuid4, editable=False)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Person_AddressType'

    def __str__(self):
        return str(self.name)


class dboAWBuildVersion(models.Model):
    system_information_id = models.AutoField(db_column='SystemInformationID', primary_key=True)
    database_version = models.CharField(db_column='Database Version', max_length=25)
    version_date = models.DateTimeField(db_column='VersionDate')
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'dbo_AWBuildVersion'

    def __str__(self):
        return self.database_version


class ProductionBillOfMaterials(models.Model):
    bill_of_materials_id = models.AutoField(db_column='BillOfMaterialsID', primary_key=True)
    product_assembly = models.ForeignKey('ProductionProduct', models.PROTECT, db_column='ProductAssemblyID', related_name='productionbillofmaterials_product_assembly_set', null=True, blank=True)
    component = models.ForeignKey('ProductionProduct', models.PROTECT, db_column='ComponentID', related_name='productionbillofmaterials_component_set')
    start_date = models.DateTimeField(db_column='StartDate', default=timezone.now)
    end_date = models.DateTimeField(db_column='EndDate', null=True, blank=True)
    unit_measure = models.ForeignKey('ProductionUnitMeasure', models.PROTECT, db_column='UnitMeasureCode')
    bom_level = models.SmallIntegerField(db_column='BOMLevel')
    per_assembly_qty = models.DecimalField(db_column='PerAssemblyQty', max_digits=8, decimal_places=2, default=Decimal('1.00'))
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Production_BillOfMaterials'
        constraints = [
            models.UniqueConstraint(fields=['product_assembly', 'component', 'start_date'], name='uq_production_billofmaterials_product_assembly_id_component_id_start_date'[:100]),
            models.CheckConstraint(condition=(models.Q(end_date__gt=F('start_date')) | models.Q(end_date__isnull=True)), name='CK_BillOfMaterials_EndDate'),
            models.CheckConstraint(condition=~models.Q(product_assembly=F('component')), name='CK_BillOfMaterials_ProductAssemblyID'),
            models.CheckConstraint(condition=((models.Q(product_assembly__isnull=True) & models.Q(bom_level=0) & models.Q(per_assembly_qty=1.00)) | (models.Q(product_assembly__isnull=False) & models.Q(bom_level__gte=1))), name='CK_BillOfMaterials_BOMLevel'),
            models.CheckConstraint(condition=models.Q(per_assembly_qty__gte=1.00), name='CK_BillOfMaterials_PerAssemblyQty'),
        ]

    def __str__(self):
        return f"{self.component} in {self.product_assembly}"


class PersonBusinessEntity(models.Model):
    business_entity_id = models.AutoField(db_column='BusinessEntityID', primary_key=True)
    rowguid = models.UUIDField(db_column='rowguid', unique=True, default=uuid.uuid4, editable=False)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Person_BusinessEntity'

    def __str__(self):
        return f"PersonBusinessEntity {self.pk}"


class PersonBusinessEntityAddress(models.Model):
    id = models.AutoField(primary_key=True)
    business_entity = models.ForeignKey('PersonBusinessEntity', models.PROTECT, db_column='BusinessEntityID')
    address = models.ForeignKey('PersonAddress', models.PROTECT, db_column='AddressID')
    address_type = models.ForeignKey('PersonAddressType', models.PROTECT, db_column='AddressTypeID')
    rowguid = models.UUIDField(db_column='rowguid', unique=True, default=uuid.uuid4, editable=False)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Person_BusinessEntityAddress'
        constraints = [
            models.UniqueConstraint(fields=['business_entity', 'address', 'address_type'], name='uq_person_businessentityaddress_key'),
        ]

    def __str__(self):
        return f"{self.business_entity} / {self.address}"


class PersonBusinessEntityContact(models.Model):
    id = models.AutoField(primary_key=True)
    business_entity = models.ForeignKey('PersonBusinessEntity', models.PROTECT, db_column='BusinessEntityID')
    person = models.ForeignKey('Person', models.PROTECT, db_column='PersonID')
    contact_type = models.ForeignKey('PersonContactType', models.PROTECT, db_column='ContactTypeID')
    rowguid = models.UUIDField(db_column='rowguid', unique=True, default=uuid.uuid4, editable=False)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Person_BusinessEntityContact'
        constraints = [
            models.UniqueConstraint(fields=['business_entity', 'person', 'contact_type'], name='uq_person_businessentitycontact_key'),
        ]

    def __str__(self):
        return f"{self.business_entity} / {self.person}"


class PersonContactType(models.Model):
    contact_type_id = models.AutoField(db_column='ContactTypeID', primary_key=True)
    name = models.CharField(db_column='Name', unique=True, max_length=50)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Person_ContactType'

    def __str__(self):
        return str(self.name)


class SalesCountryRegionCurrency(models.Model):
    id = models.AutoField(primary_key=True)
    country_region = models.ForeignKey('PersonCountryRegion', models.PROTECT, db_column='CountryRegionCode')
    currency = models.ForeignKey('SalesCurrency', models.PROTECT, db_column='CurrencyCode')
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Sales_CountryRegionCurrency'
        constraints = [
            models.UniqueConstraint(fields=['country_region', 'currency'], name='uq_sales_countryregioncurrency_key'),
        ]

    def __str__(self):
        return f"{self.country_region} / {self.currency}"


class PersonCountryRegion(models.Model):
    country_region_code = models.CharField(db_column='CountryRegionCode', primary_key=True, max_length=3)
    name = models.CharField(db_column='Name', unique=True, max_length=50)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Person_CountryRegion'

    def __str__(self):
        return str(self.name)


class SalesCreditCard(models.Model):
    credit_card_id = models.AutoField(db_column='CreditCardID', primary_key=True)
    card_type = models.CharField(db_column='CardType', max_length=50)
    card_number = models.CharField(db_column='CardNumber', unique=True, max_length=25)
    exp_month = models.PositiveSmallIntegerField(db_column='ExpMonth')
    exp_year = models.SmallIntegerField(db_column='ExpYear')
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Sales_CreditCard'

    def __str__(self):
        return f"{self.card_type} ****{self.card_number[-4:]}"


class ProductionCulture(models.Model):
    culture_id = models.CharField(db_column='CultureID', primary_key=True, max_length=6)
    name = models.CharField(db_column='Name', unique=True, max_length=50)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Production_Culture'

    def __str__(self):
        return str(self.name)


class SalesCurrency(models.Model):
    currency_code = models.CharField(db_column='CurrencyCode', primary_key=True, max_length=3)
    name = models.CharField(db_column='Name', unique=True, max_length=50)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Sales_Currency'

    def __str__(self):
        return str(self.name)


class SalesCurrencyRate(models.Model):
    currency_rate_id = models.AutoField(db_column='CurrencyRateID', primary_key=True)
    currency_rate_date = models.DateTimeField(db_column='CurrencyRateDate')
    from_currency = models.ForeignKey('SalesCurrency', models.PROTECT, db_column='FromCurrencyCode', related_name='salescurrencyrate_from_currency_set')
    to_currency = models.ForeignKey('SalesCurrency', models.PROTECT, db_column='ToCurrencyCode', related_name='salescurrencyrate_to_currency_set')
    average_rate = models.DecimalField(db_column='AverageRate', max_digits=19, decimal_places=4)
    end_of_day_rate = models.DecimalField(db_column='EndOfDayRate', max_digits=19, decimal_places=4)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Sales_CurrencyRate'
        constraints = [
            models.UniqueConstraint(fields=['currency_rate_date', 'from_currency', 'to_currency'], name='uq_sales_currencyrate_currency_rate_date_from_currency_code_to_currency_code'[:100]),
        ]

    def __str__(self):
        return f"SalesCurrencyRate {self.pk}"


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


class HumanResourcesDepartment(models.Model):
    department_id = models.AutoField(db_column='DepartmentID', primary_key=True)
    name = models.CharField(db_column='Name', unique=True, max_length=50)
    group_name = models.CharField(db_column='GroupName', max_length=50)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'HumanResources_Department'

    def __str__(self):
        return str(self.name)


class ProductionDocument(models.Model):
    document_node = models.CharField(db_column='DocumentNode', primary_key=True, max_length=255)
    document_level = models.SmallIntegerField(db_column='DocumentLevel', null=True, blank=True, editable=False)
    title = models.CharField(db_column='Title', max_length=50)
    owner = models.ForeignKey('HumanResourcesEmployee', models.PROTECT, db_column='Owner')
    folder_flag = models.BooleanField(db_column='FolderFlag', default=False)
    file_name = models.CharField(db_column='FileName', max_length=400)
    file_extension = models.CharField(db_column='FileExtension', max_length=8)
    revision = models.CharField(db_column='Revision', max_length=5)
    change_number = models.IntegerField(db_column='ChangeNumber', default=0)
    status = models.PositiveSmallIntegerField(db_column='Status')
    document_summary = models.TextField(db_column='DocumentSummary', null=True, blank=True)
    document = models.BinaryField(db_column='Document', null=True, blank=True, editable=False)
    rowguid = models.UUIDField(db_column='rowguid', unique=True, default=uuid.uuid4, editable=False)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Production_Document'
        constraints = [
            models.CheckConstraint(condition=(models.Q(status__gte=1) & models.Q(status__lte=3)), name='CK_Document_Status'),
        ]

    def __str__(self):
        return self.title


class PersonEmailAddress(models.Model):
    business_entity = models.ForeignKey('Person', models.PROTECT, db_column='BusinessEntityID')
    email_address_id = models.AutoField(db_column='EmailAddressID', primary_key=True)
    email_address = models.CharField(db_column='EmailAddress', null=True, blank=True, max_length=50)
    rowguid = models.UUIDField(db_column='rowguid', default=uuid.uuid4, editable=False)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Person_EmailAddress'

    def __str__(self):
        return self.email_address or ""


class HumanResourcesEmployee(models.Model):
    business_entity = models.OneToOneField('Person', models.PROTECT, db_column='BusinessEntityID', primary_key=True)
    national_id_number = models.CharField(db_column='NationalIDNumber', unique=True, max_length=15)
    login_id = models.CharField(db_column='LoginID', unique=True, max_length=256)
    organization_node = models.CharField(db_column='OrganizationNode', null=True, blank=True, max_length=255)
    organization_level = models.SmallIntegerField(db_column='OrganizationLevel', null=True, blank=True, editable=False)
    job_title = models.CharField(db_column='JobTitle', max_length=50)
    birth_date = models.DateField(db_column='BirthDate')
    marital_status = models.CharField(db_column='MaritalStatus', max_length=1)
    gender = models.CharField(db_column='Gender', max_length=1)
    hire_date = models.DateField(db_column='HireDate')
    salaried_flag = models.BooleanField(db_column='SalariedFlag', default=True)
    vacation_hours = models.SmallIntegerField(db_column='VacationHours', default=0)
    sick_leave_hours = models.SmallIntegerField(db_column='SickLeaveHours', default=0)
    current_flag = models.BooleanField(db_column='CurrentFlag', default=True)
    rowguid = models.UUIDField(db_column='rowguid', unique=True, default=uuid.uuid4, editable=False)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'HumanResources_Employee'
        constraints = [
            models.CheckConstraint(condition=models.Q(marital_status__in=['M', 'S', 'm', 's']), name='CK_Employee_MaritalStatus'),
            models.CheckConstraint(condition=models.Q(gender__in=['M', 'F', 'm', 'f']), name='CK_Employee_Gender'),
            models.CheckConstraint(condition=(models.Q(vacation_hours__gte=-40) & models.Q(vacation_hours__lte=240)), name='CK_Employee_VacationHours'),
            models.CheckConstraint(condition=(models.Q(sick_leave_hours__gte=0) & models.Q(sick_leave_hours__lte=120)), name='CK_Employee_SickLeaveHours'),
        ]
    # CHECK not translated (CK_Employee_BirthDate): [BirthDate] BETWEEN '1930-01-01' AND DATEADD(YEAR, -18, GETDATE())
    # CHECK not translated (CK_Employee_HireDate): [HireDate] BETWEEN '1996-07-01' AND DATEADD(DAY, 1, GETDATE())

    def __str__(self):
        return str(self.business_entity)


class HumanResourcesEmployeeDepartmentHistory(models.Model):
    id = models.AutoField(primary_key=True)
    business_entity = models.ForeignKey('HumanResourcesEmployee', models.PROTECT, db_column='BusinessEntityID')
    department = models.ForeignKey('HumanResourcesDepartment', models.PROTECT, db_column='DepartmentID')
    shift = models.ForeignKey('HumanResourcesShift', models.PROTECT, db_column='ShiftID')
    start_date = models.DateField(db_column='StartDate')
    end_date = models.DateField(db_column='EndDate', null=True, blank=True)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'HumanResources_EmployeeDepartmentHistory'
        constraints = [
            models.UniqueConstraint(fields=['business_entity', 'start_date', 'department', 'shift'], name='uq_humanresources_employeedepartmenthistory_key'),
            models.CheckConstraint(condition=(models.Q(end_date__gte=F('start_date')) | models.Q(end_date__isnull=True)), name='CK_EmployeeDepartmentHistory_EndDate'),
        ]

    def __str__(self):
        return f"{self.business_entity} / {self.department}"


class HumanResourcesEmployeePayHistory(models.Model):
    id = models.AutoField(primary_key=True)
    business_entity = models.ForeignKey('HumanResourcesEmployee', models.PROTECT, db_column='BusinessEntityID')
    rate_change_date = models.DateTimeField(db_column='RateChangeDate')
    rate = models.DecimalField(db_column='Rate', max_digits=19, decimal_places=4)
    pay_frequency = models.PositiveSmallIntegerField(db_column='PayFrequency')
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'HumanResources_EmployeePayHistory'
        constraints = [
            models.UniqueConstraint(fields=['business_entity', 'rate_change_date'], name='uq_humanresources_employeepayhistory_key'),
            models.CheckConstraint(condition=models.Q(pay_frequency__in=[1, 2]), name='CK_EmployeePayHistory_PayFrequency'),
            models.CheckConstraint(condition=(models.Q(rate__gte=6.50) & models.Q(rate__lte=200.00)), name='CK_EmployeePayHistory_Rate'),
        ]

    def __str__(self):
        return str(self.business_entity)


class ProductionIllustration(models.Model):
    illustration_id = models.AutoField(db_column='IllustrationID', primary_key=True)
    diagram = models.TextField(db_column='Diagram', null=True, blank=True)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Production_Illustration'

    def __str__(self):
        return f"Illustration {self.pk}"


class HumanResourcesJobCandidate(models.Model):
    job_candidate_id = models.AutoField(db_column='JobCandidateID', primary_key=True)
    business_entity = models.ForeignKey('HumanResourcesEmployee', models.PROTECT, db_column='BusinessEntityID', null=True, blank=True)
    resume = models.TextField(db_column='Resume', null=True, blank=True)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'HumanResources_JobCandidate'

    def __str__(self):
        return f"Candidate {self.pk}"


class ProductionLocation(models.Model):
    location_id = models.AutoField(db_column='LocationID', primary_key=True)
    name = models.CharField(db_column='Name', unique=True, max_length=50)
    cost_rate = models.DecimalField(db_column='CostRate', max_digits=10, decimal_places=4, default=Decimal('0.00'))
    availability = models.DecimalField(db_column='Availability', max_digits=8, decimal_places=2, default=Decimal('0.00'))
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Production_Location'
        constraints = [
            models.CheckConstraint(condition=models.Q(cost_rate__gte=0.00), name='CK_Location_CostRate'),
            models.CheckConstraint(condition=models.Q(availability__gte=0.00), name='CK_Location_Availability'),
        ]

    def __str__(self):
        return str(self.name)


class PersonPassword(models.Model):
    business_entity = models.OneToOneField('Person', models.PROTECT, db_column='BusinessEntityID', primary_key=True)
    password_hash = models.CharField(db_column='PasswordHash', max_length=128)
    password_salt = models.CharField(db_column='PasswordSalt', max_length=10)
    rowguid = models.UUIDField(db_column='rowguid', default=uuid.uuid4, editable=False)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Person_Password'

    def __str__(self):
        return f"Password record {self.pk}"


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


class SalesPersonCreditCard(models.Model):
    id = models.AutoField(primary_key=True)
    business_entity = models.ForeignKey('Person', models.PROTECT, db_column='BusinessEntityID')
    credit_card = models.ForeignKey('SalesCreditCard', models.PROTECT, db_column='CreditCardID')
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Sales_PersonCreditCard'
        constraints = [
            models.UniqueConstraint(fields=['business_entity', 'credit_card'], name='uq_sales_personcreditcard_key'),
        ]

    def __str__(self):
        return f"{self.business_entity} / {self.credit_card}"


class PersonPhone(models.Model):
    id = models.AutoField(primary_key=True)
    business_entity = models.ForeignKey('Person', models.PROTECT, db_column='BusinessEntityID')
    phone_number = models.CharField(db_column='PhoneNumber', max_length=25)
    phone_number_type = models.ForeignKey('PersonPhoneNumberType', models.PROTECT, db_column='PhoneNumberTypeID')
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Person_PersonPhone'
        constraints = [
            models.UniqueConstraint(fields=['business_entity', 'phone_number', 'phone_number_type'], name='uq_person_personphone_key'),
        ]

    def __str__(self):
        return self.phone_number


class PersonPhoneNumberType(models.Model):
    phone_number_type_id = models.AutoField(db_column='PhoneNumberTypeID', primary_key=True)
    name = models.CharField(db_column='Name', max_length=50)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Person_PhoneNumberType'

    def __str__(self):
        return str(self.name)


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
    size_unit_measure = models.ForeignKey('ProductionUnitMeasure', models.PROTECT, db_column='SizeUnitMeasureCode', related_name='productionproduct_size_unit_measure_set', null=True, blank=True)
    weight_unit_measure = models.ForeignKey('ProductionUnitMeasure', models.PROTECT, db_column='WeightUnitMeasureCode', related_name='productionproduct_weight_unit_measure_set', null=True, blank=True)
    weight = models.DecimalField(db_column='Weight', null=True, blank=True, max_digits=8, decimal_places=2)
    days_to_manufacture = models.IntegerField(db_column='DaysToManufacture')
    product_line = models.CharField(db_column='ProductLine', null=True, blank=True, max_length=2)
    class_field = models.CharField(db_column='Class', null=True, blank=True, max_length=2)
    style = models.CharField(db_column='Style', null=True, blank=True, max_length=2)
    product_subcategory = models.ForeignKey('ProductionProductSubcategory', models.PROTECT, db_column='ProductSubcategoryID', null=True, blank=True)
    product_model = models.ForeignKey('ProductionProductModel', models.PROTECT, db_column='ProductModelID', null=True, blank=True)
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


class ProductionProductDescription(models.Model):
    product_description_id = models.AutoField(db_column='ProductDescriptionID', primary_key=True)
    description = models.CharField(db_column='Description', max_length=400)
    rowguid = models.UUIDField(db_column='rowguid', unique=True, default=uuid.uuid4, editable=False)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Production_ProductDescription'

    def __str__(self):
        return self.description[:60]


class ProductionProductDocument(models.Model):
    id = models.AutoField(primary_key=True)
    product = models.ForeignKey('ProductionProduct', models.PROTECT, db_column='ProductID')
    document_node = models.ForeignKey('ProductionDocument', models.PROTECT, db_column='DocumentNode')
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Production_ProductDocument'
        constraints = [
            models.UniqueConstraint(fields=['product', 'document_node'], name='uq_production_productdocument_key'),
        ]

    def __str__(self):
        return f"{self.product} / {self.document_node}"


class ProductionProductInventory(models.Model):
    id = models.AutoField(primary_key=True)
    product = models.ForeignKey('ProductionProduct', models.PROTECT, db_column='ProductID')
    location = models.ForeignKey('ProductionLocation', models.PROTECT, db_column='LocationID')
    shelf = models.CharField(db_column='Shelf', max_length=10)
    bin = models.PositiveSmallIntegerField(db_column='Bin')
    quantity = models.SmallIntegerField(db_column='Quantity', default=0)
    rowguid = models.UUIDField(db_column='rowguid', default=uuid.uuid4, editable=False)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Production_ProductInventory'
        constraints = [
            models.UniqueConstraint(fields=['product', 'location'], name='uq_production_productinventory_key'),
            models.CheckConstraint(condition=(models.Q(bin__gte=0) & models.Q(bin__lte=100)), name='CK_ProductInventory_Bin'),
        ]
    # CHECK not translated (CK_ProductInventory_Shelf): ([Shelf] LIKE '[A-Za-z]') OR ([Shelf] = 'N/A')

    def __str__(self):
        return f"{self.product} / {self.location}"


class ProductionProductListPriceHistory(models.Model):
    id = models.AutoField(primary_key=True)
    product = models.ForeignKey('ProductionProduct', models.PROTECT, db_column='ProductID')
    start_date = models.DateTimeField(db_column='StartDate')
    end_date = models.DateTimeField(db_column='EndDate', null=True, blank=True)
    list_price = models.DecimalField(db_column='ListPrice', max_digits=19, decimal_places=4)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Production_ProductListPriceHistory'
        constraints = [
            models.UniqueConstraint(fields=['product', 'start_date'], name='uq_production_productlistpricehistory_key'),
            models.CheckConstraint(condition=(models.Q(end_date__gte=F('start_date')) | models.Q(end_date__isnull=True)), name='CK_ProductListPriceHistory_EndDate'),
            models.CheckConstraint(condition=models.Q(list_price__gt=0.00), name='CK_ProductListPriceHistory_ListPrice'),
        ]

    def __str__(self):
        return str(self.product)


class ProductionProductModel(models.Model):
    product_model_id = models.AutoField(db_column='ProductModelID', primary_key=True)
    name = models.CharField(db_column='Name', unique=True, max_length=50)
    catalog_description = models.TextField(db_column='CatalogDescription', null=True, blank=True)
    instructions = models.TextField(db_column='Instructions', null=True, blank=True)
    rowguid = models.UUIDField(db_column='rowguid', unique=True, default=uuid.uuid4, editable=False)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Production_ProductModel'

    def __str__(self):
        return str(self.name)


class ProductionProductModelIllustration(models.Model):
    id = models.AutoField(primary_key=True)
    product_model = models.ForeignKey('ProductionProductModel', models.PROTECT, db_column='ProductModelID')
    illustration = models.ForeignKey('ProductionIllustration', models.PROTECT, db_column='IllustrationID')
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Production_ProductModelIllustration'
        constraints = [
            models.UniqueConstraint(fields=['product_model', 'illustration'], name='uq_production_productmodelillustration_key'),
        ]

    def __str__(self):
        return f"{self.product_model} / {self.illustration}"


class ProductionProductModelProductDescriptionCulture(models.Model):
    id = models.AutoField(primary_key=True)
    product_model = models.ForeignKey('ProductionProductModel', models.PROTECT, db_column='ProductModelID')
    product_description = models.ForeignKey('ProductionProductDescription', models.PROTECT, db_column='ProductDescriptionID')
    culture = models.ForeignKey('ProductionCulture', models.PROTECT, db_column='CultureID')
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Production_ProductModelProductDescriptionCulture'
        constraints = [
            models.UniqueConstraint(fields=['product_model', 'product_description', 'culture'], name='uq_production_productmodelproductdescriptionculture_key'),
        ]

    def __str__(self):
        return f"{self.product_model} / {self.product_description}"


class ProductionProductPhoto(models.Model):
    product_photo_id = models.AutoField(db_column='ProductPhotoID', primary_key=True)
    thumb_nail_photo = models.BinaryField(db_column='ThumbNailPhoto', null=True, blank=True, editable=False)
    thumbnail_photo_file_name = models.CharField(db_column='ThumbnailPhotoFileName', null=True, blank=True, max_length=50)
    large_photo = models.BinaryField(db_column='LargePhoto', null=True, blank=True, editable=False)
    large_photo_file_name = models.CharField(db_column='LargePhotoFileName', null=True, blank=True, max_length=50)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Production_ProductPhoto'

    def __str__(self):
        return self.thumbnail_photo_file_name or f"Photo {self.pk}"


class ProductionProductProductPhoto(models.Model):
    id = models.AutoField(primary_key=True)
    product = models.ForeignKey('ProductionProduct', models.PROTECT, db_column='ProductID')
    product_photo = models.ForeignKey('ProductionProductPhoto', models.PROTECT, db_column='ProductPhotoID')
    primary = models.BooleanField(db_column='Primary', default=False)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Production_ProductProductPhoto'
        constraints = [
            models.UniqueConstraint(fields=['product', 'product_photo'], name='uq_production_productproductphoto_key'),
        ]

    def __str__(self):
        return f"{self.product} / {self.product_photo}"


class ProductionProductReview(models.Model):
    product_review_id = models.AutoField(db_column='ProductReviewID', primary_key=True)
    product = models.ForeignKey('ProductionProduct', models.PROTECT, db_column='ProductID')
    reviewer_name = models.CharField(db_column='ReviewerName', max_length=50)
    review_date = models.DateTimeField(db_column='ReviewDate', default=timezone.now)
    email_address = models.CharField(db_column='EmailAddress', max_length=50)
    rating = models.IntegerField(db_column='Rating')
    comments = models.CharField(db_column='Comments', null=True, blank=True, max_length=3850)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Production_ProductReview'
        constraints = [
            models.CheckConstraint(condition=(models.Q(rating__gte=1) & models.Q(rating__lte=5)), name='CK_ProductReview_Rating'),
        ]

    def __str__(self):
        return f"{self.product} ({self.rating}/5)"


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


class PurchasingProductVendor(models.Model):
    id = models.AutoField(primary_key=True)
    product = models.ForeignKey('ProductionProduct', models.PROTECT, db_column='ProductID')
    business_entity = models.ForeignKey('PurchasingVendor', models.PROTECT, db_column='BusinessEntityID')
    average_lead_time = models.IntegerField(db_column='AverageLeadTime')
    standard_price = models.DecimalField(db_column='StandardPrice', max_digits=19, decimal_places=4)
    last_receipt_cost = models.DecimalField(db_column='LastReceiptCost', null=True, blank=True, max_digits=19, decimal_places=4)
    last_receipt_date = models.DateTimeField(db_column='LastReceiptDate', null=True, blank=True)
    min_order_qty = models.IntegerField(db_column='MinOrderQty')
    max_order_qty = models.IntegerField(db_column='MaxOrderQty')
    on_order_qty = models.IntegerField(db_column='OnOrderQty', null=True, blank=True)
    unit_measure = models.ForeignKey('ProductionUnitMeasure', models.PROTECT, db_column='UnitMeasureCode')
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Purchasing_ProductVendor'
        constraints = [
            models.UniqueConstraint(fields=['product', 'business_entity'], name='uq_purchasing_productvendor_key'),
            models.CheckConstraint(condition=models.Q(average_lead_time__gte=1), name='CK_ProductVendor_AverageLeadTime'),
            models.CheckConstraint(condition=models.Q(standard_price__gt=0.00), name='CK_ProductVendor_StandardPrice'),
            models.CheckConstraint(condition=models.Q(last_receipt_cost__gt=0.00), name='CK_ProductVendor_LastReceiptCost'),
            models.CheckConstraint(condition=models.Q(min_order_qty__gte=1), name='CK_ProductVendor_MinOrderQty'),
            models.CheckConstraint(condition=models.Q(max_order_qty__gte=1), name='CK_ProductVendor_MaxOrderQty'),
            models.CheckConstraint(condition=models.Q(on_order_qty__gte=0), name='CK_ProductVendor_OnOrderQty'),
        ]

    def __str__(self):
        return f"{self.product} / {self.business_entity}"


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
    employee = models.ForeignKey('HumanResourcesEmployee', models.PROTECT, db_column='EmployeeID')
    vendor = models.ForeignKey('PurchasingVendor', models.PROTECT, db_column='VendorID')
    ship_method = models.ForeignKey('PurchasingShipMethod', models.PROTECT, db_column='ShipMethodID')
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
    special_offer = models.ForeignKey('SalesSpecialOffer', models.PROTECT, db_column='SpecialOfferID')
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

    def clean(self):
        # SQL Server has a composite FK (SpecialOfferID, ProductID) -> SpecialOfferProduct.
        # Django cannot declare that, so enforce it here.
        if self.special_offer_id and self.product_id and not SalesSpecialOfferProduct.objects.filter(
            special_offer_id=self.special_offer_id, product_id=self.product_id
        ).exists():
            raise ValidationError('This product is not part of the chosen special offer.')

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
    sales_person = models.ForeignKey('SalesPerson', models.PROTECT, db_column='SalesPersonID', null=True, blank=True)
    territory = models.ForeignKey('SalesTerritory', models.PROTECT, db_column='TerritoryID', null=True, blank=True)
    bill_to_address = models.ForeignKey('PersonAddress', models.PROTECT, db_column='BillToAddressID', related_name='salesorderheader_bill_to_address_set')
    ship_to_address = models.ForeignKey('PersonAddress', models.PROTECT, db_column='ShipToAddressID', related_name='salesorderheader_ship_to_address_set')
    ship_method = models.ForeignKey('PurchasingShipMethod', models.PROTECT, db_column='ShipMethodID')
    credit_card = models.ForeignKey('SalesCreditCard', models.PROTECT, db_column='CreditCardID', null=True, blank=True)
    credit_card_approval_code = models.CharField(db_column='CreditCardApprovalCode', null=True, blank=True, max_length=15)
    currency_rate = models.ForeignKey('SalesCurrencyRate', models.PROTECT, db_column='CurrencyRateID', null=True, blank=True)
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


class SalesOrderHeaderSalesReason(models.Model):
    id = models.AutoField(primary_key=True)
    sales_order = models.ForeignKey('SalesOrderHeader', models.PROTECT, db_column='SalesOrderID')
    sales_reason = models.ForeignKey('SalesReason', models.PROTECT, db_column='SalesReasonID')
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Sales_SalesOrderHeaderSalesReason'
        constraints = [
            models.UniqueConstraint(fields=['sales_order', 'sales_reason'], name='uq_sales_salesorderheadersalesreason_key'),
        ]

    def __str__(self):
        return f"{self.sales_order} / {self.sales_reason}"


class SalesPerson(models.Model):
    business_entity = models.OneToOneField('HumanResourcesEmployee', models.PROTECT, db_column='BusinessEntityID', primary_key=True)
    territory = models.ForeignKey('SalesTerritory', models.PROTECT, db_column='TerritoryID', null=True, blank=True)
    sales_quota = models.DecimalField(db_column='SalesQuota', null=True, blank=True, max_digits=19, decimal_places=4)
    bonus = models.DecimalField(db_column='Bonus', max_digits=19, decimal_places=4, default=Decimal('0.00'))
    commission_pct = models.DecimalField(db_column='CommissionPct', max_digits=10, decimal_places=4, default=Decimal('0.00'))
    sales_ytd = models.DecimalField(db_column='SalesYTD', max_digits=19, decimal_places=4, default=Decimal('0.00'))
    sales_last_year = models.DecimalField(db_column='SalesLastYear', max_digits=19, decimal_places=4, default=Decimal('0.00'))
    rowguid = models.UUIDField(db_column='rowguid', unique=True, default=uuid.uuid4, editable=False)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Sales_SalesPerson'
        constraints = [
            models.CheckConstraint(condition=models.Q(sales_quota__gt=0.00), name='CK_SalesPerson_SalesQuota'),
            models.CheckConstraint(condition=models.Q(bonus__gte=0.00), name='CK_SalesPerson_Bonus'),
            models.CheckConstraint(condition=models.Q(commission_pct__gte=0.00), name='CK_SalesPerson_CommissionPct'),
            models.CheckConstraint(condition=models.Q(sales_ytd__gte=0.00), name='CK_SalesPerson_SalesYTD'),
            models.CheckConstraint(condition=models.Q(sales_last_year__gte=0.00), name='CK_SalesPerson_SalesLastYear'),
        ]

    def __str__(self):
        return str(self.business_entity)


class SalesPersonQuotaHistory(models.Model):
    id = models.AutoField(primary_key=True)
    business_entity = models.ForeignKey('SalesPerson', models.PROTECT, db_column='BusinessEntityID')
    quota_date = models.DateTimeField(db_column='QuotaDate')
    sales_quota = models.DecimalField(db_column='SalesQuota', max_digits=19, decimal_places=4)
    rowguid = models.UUIDField(db_column='rowguid', unique=True, default=uuid.uuid4, editable=False)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Sales_SalesPersonQuotaHistory'
        constraints = [
            models.UniqueConstraint(fields=['business_entity', 'quota_date'], name='uq_sales_salespersonquotahistory_key'),
            models.CheckConstraint(condition=models.Q(sales_quota__gt=0.00), name='CK_SalesPersonQuotaHistory_SalesQuota'),
        ]

    def __str__(self):
        return str(self.business_entity)


class SalesReason(models.Model):
    sales_reason_id = models.AutoField(db_column='SalesReasonID', primary_key=True)
    name = models.CharField(db_column='Name', max_length=50)
    reason_type = models.CharField(db_column='ReasonType', max_length=50)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Sales_SalesReason'

    def __str__(self):
        return str(self.name)


class SalesTaxRate(models.Model):
    sales_tax_rate_id = models.AutoField(db_column='SalesTaxRateID', primary_key=True)
    state_province = models.ForeignKey('PersonStateProvince', models.PROTECT, db_column='StateProvinceID')
    tax_type = models.PositiveSmallIntegerField(db_column='TaxType')
    tax_rate = models.DecimalField(db_column='TaxRate', max_digits=10, decimal_places=4, default=Decimal('0.00'))
    name = models.CharField(db_column='Name', max_length=50)
    rowguid = models.UUIDField(db_column='rowguid', unique=True, default=uuid.uuid4, editable=False)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Sales_SalesTaxRate'
        constraints = [
            models.UniqueConstraint(fields=['state_province', 'tax_type'], name='uq_sales_salestaxrate_state_province_id_tax_type'[:100]),
            models.CheckConstraint(condition=(models.Q(tax_type__gte=1) & models.Q(tax_type__lte=3)), name='CK_SalesTaxRate_TaxType'),
        ]

    def __str__(self):
        return str(self.name)


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


class SalesTerritoryHistory(models.Model):
    id = models.AutoField(primary_key=True)
    business_entity = models.ForeignKey('SalesPerson', models.PROTECT, db_column='BusinessEntityID')
    territory = models.ForeignKey('SalesTerritory', models.PROTECT, db_column='TerritoryID')
    start_date = models.DateTimeField(db_column='StartDate')
    end_date = models.DateTimeField(db_column='EndDate', null=True, blank=True)
    rowguid = models.UUIDField(db_column='rowguid', unique=True, default=uuid.uuid4, editable=False)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Sales_SalesTerritoryHistory'
        constraints = [
            models.UniqueConstraint(fields=['business_entity', 'start_date', 'territory'], name='uq_sales_salesterritoryhistory_key'),
            models.CheckConstraint(condition=(models.Q(end_date__gte=F('start_date')) | models.Q(end_date__isnull=True)), name='CK_SalesTerritoryHistory_EndDate'),
        ]

    def __str__(self):
        return f"{self.business_entity} / {self.territory}"


class ProductionScrapReason(models.Model):
    scrap_reason_id = models.AutoField(db_column='ScrapReasonID', primary_key=True)
    name = models.CharField(db_column='Name', unique=True, max_length=50)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Production_ScrapReason'

    def __str__(self):
        return str(self.name)


class HumanResourcesShift(models.Model):
    shift_id = models.AutoField(db_column='ShiftID', primary_key=True)
    name = models.CharField(db_column='Name', unique=True, max_length=50)
    start_time = models.TimeField(db_column='StartTime')
    end_time = models.TimeField(db_column='EndTime')
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'HumanResources_Shift'
        constraints = [
            models.UniqueConstraint(fields=['start_time', 'end_time'], name='uq_humanresources_shift_start_time_end_time'[:100]),
        ]

    def __str__(self):
        return str(self.name)


class PurchasingShipMethod(models.Model):
    ship_method_id = models.AutoField(db_column='ShipMethodID', primary_key=True)
    name = models.CharField(db_column='Name', unique=True, max_length=50)
    ship_base = models.DecimalField(db_column='ShipBase', max_digits=19, decimal_places=4, default=Decimal('0.00'))
    ship_rate = models.DecimalField(db_column='ShipRate', max_digits=19, decimal_places=4, default=Decimal('0.00'))
    rowguid = models.UUIDField(db_column='rowguid', unique=True, default=uuid.uuid4, editable=False)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Purchasing_ShipMethod'
        constraints = [
            models.CheckConstraint(condition=models.Q(ship_base__gt=0.00), name='CK_ShipMethod_ShipBase'),
            models.CheckConstraint(condition=models.Q(ship_rate__gt=0.00), name='CK_ShipMethod_ShipRate'),
        ]

    def __str__(self):
        return str(self.name)


class SalesShoppingCartItem(models.Model):
    shopping_cart_item_id = models.AutoField(db_column='ShoppingCartItemID', primary_key=True)
    shopping_cart_id = models.CharField(db_column='ShoppingCartID', max_length=50)
    quantity = models.IntegerField(db_column='Quantity', default=1)
    product = models.ForeignKey('ProductionProduct', models.PROTECT, db_column='ProductID')
    date_created = models.DateTimeField(db_column='DateCreated', default=timezone.now)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Sales_ShoppingCartItem'
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity__gte=1), name='CK_ShoppingCartItem_Quantity'),
        ]

    def __str__(self):
        return f"Cart {self.shopping_cart_id} item {self.pk}"


class SalesSpecialOffer(models.Model):
    special_offer_id = models.AutoField(db_column='SpecialOfferID', primary_key=True)
    description = models.CharField(db_column='Description', max_length=255)
    discount_pct = models.DecimalField(db_column='DiscountPct', max_digits=10, decimal_places=4, default=Decimal('0.00'))
    type = models.CharField(db_column='Type', max_length=50)
    category = models.CharField(db_column='Category', max_length=50)
    start_date = models.DateTimeField(db_column='StartDate')
    end_date = models.DateTimeField(db_column='EndDate')
    min_qty = models.IntegerField(db_column='MinQty', default=0)
    max_qty = models.IntegerField(db_column='MaxQty', null=True, blank=True)
    rowguid = models.UUIDField(db_column='rowguid', unique=True, default=uuid.uuid4, editable=False)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Sales_SpecialOffer'
        constraints = [
            models.CheckConstraint(condition=models.Q(end_date__gte=F('start_date')), name='CK_SpecialOffer_EndDate'),
            models.CheckConstraint(condition=models.Q(discount_pct__gte=0.00), name='CK_SpecialOffer_DiscountPct'),
            models.CheckConstraint(condition=models.Q(min_qty__gte=0), name='CK_SpecialOffer_MinQty'),
        ]

    def __str__(self):
        return self.description


class SalesSpecialOfferProduct(models.Model):
    id = models.AutoField(primary_key=True)
    special_offer = models.ForeignKey('SalesSpecialOffer', models.PROTECT, db_column='SpecialOfferID')
    product = models.ForeignKey('ProductionProduct', models.PROTECT, db_column='ProductID')
    rowguid = models.UUIDField(db_column='rowguid', unique=True, default=uuid.uuid4, editable=False)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Sales_SpecialOfferProduct'
        constraints = [
            models.UniqueConstraint(fields=['special_offer', 'product'], name='uq_sales_specialofferproduct_key'),
        ]

    def __str__(self):
        return f"{self.special_offer} / {self.product}"


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
    sales_person = models.ForeignKey('SalesPerson', models.PROTECT, db_column='SalesPersonID', null=True, blank=True)
    demographics = models.TextField(db_column='Demographics', null=True, blank=True)
    rowguid = models.UUIDField(db_column='rowguid', unique=True, default=uuid.uuid4, editable=False)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Sales_Store'

    def __str__(self):
        return self.name


class ProductionTransactionHistory(models.Model):
    transaction_id = models.AutoField(db_column='TransactionID', primary_key=True)
    product = models.ForeignKey('ProductionProduct', models.PROTECT, db_column='ProductID')
    reference_order_id = models.IntegerField(db_column='ReferenceOrderID')
    reference_order_line_id = models.IntegerField(db_column='ReferenceOrderLineID', default=0)
    transaction_date = models.DateTimeField(db_column='TransactionDate', default=timezone.now)
    transaction_type = models.CharField(db_column='TransactionType', max_length=1)
    quantity = models.IntegerField(db_column='Quantity')
    actual_cost = models.DecimalField(db_column='ActualCost', max_digits=19, decimal_places=4)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Production_TransactionHistory'
        constraints = [
            models.CheckConstraint(condition=models.Q(transaction_type__in=['W', 'S', 'P', 'w', 's', 'p']), name='CK_TransactionHistory_TransactionType'),
        ]

    def __str__(self):
        return f"{self.product} {self.transaction_date:%Y-%m-%d}"


class ProductionTransactionHistoryArchive(models.Model):
    transaction_id = models.IntegerField(db_column='TransactionID', primary_key=True)
    product_id = models.IntegerField(db_column='ProductID')
    reference_order_id = models.IntegerField(db_column='ReferenceOrderID')
    reference_order_line_id = models.IntegerField(db_column='ReferenceOrderLineID', default=0)
    transaction_date = models.DateTimeField(db_column='TransactionDate', default=timezone.now)
    transaction_type = models.CharField(db_column='TransactionType', max_length=1)
    quantity = models.IntegerField(db_column='Quantity')
    actual_cost = models.DecimalField(db_column='ActualCost', max_digits=19, decimal_places=4)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Production_TransactionHistoryArchive'
        constraints = [
            models.CheckConstraint(condition=models.Q(transaction_type__in=['W', 'S', 'P', 'w', 's', 'p']), name='CK_TransactionHistoryArchive_TransactionType'),
        ]

    def __str__(self):
        return f"Archive transaction {self.pk}"


class ProductionUnitMeasure(models.Model):
    unit_measure_code = models.CharField(db_column='UnitMeasureCode', primary_key=True, max_length=3)
    name = models.CharField(db_column='Name', unique=True, max_length=50)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Production_UnitMeasure'

    def __str__(self):
        return str(self.name)


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


class ProductionWorkOrderRouting(models.Model):
    id = models.AutoField(primary_key=True)
    work_order = models.ForeignKey('ProductionWorkOrder', models.PROTECT, db_column='WorkOrderID')
    product_id = models.IntegerField(db_column='ProductID')
    operation_sequence = models.SmallIntegerField(db_column='OperationSequence')
    location = models.ForeignKey('ProductionLocation', models.PROTECT, db_column='LocationID')
    scheduled_start_date = models.DateTimeField(db_column='ScheduledStartDate')
    scheduled_end_date = models.DateTimeField(db_column='ScheduledEndDate')
    actual_start_date = models.DateTimeField(db_column='ActualStartDate', null=True, blank=True)
    actual_end_date = models.DateTimeField(db_column='ActualEndDate', null=True, blank=True)
    actual_resource_hrs = models.DecimalField(db_column='ActualResourceHrs', null=True, blank=True, max_digits=9, decimal_places=4)
    planned_cost = models.DecimalField(db_column='PlannedCost', max_digits=19, decimal_places=4)
    actual_cost = models.DecimalField(db_column='ActualCost', null=True, blank=True, max_digits=19, decimal_places=4)
    modified_date = models.DateTimeField(db_column='ModifiedDate', default=timezone.now)

    class Meta:
        db_table = 'Production_WorkOrderRouting'
        constraints = [
            models.UniqueConstraint(fields=['work_order', 'product_id', 'operation_sequence'], name='uq_production_workorderrouting_key'),
            models.CheckConstraint(condition=models.Q(scheduled_end_date__gte=F('scheduled_start_date')), name='CK_WorkOrderRouting_ScheduledEndDate'),
            models.CheckConstraint(condition=(models.Q(actual_end_date__gte=F('actual_start_date')) | models.Q(actual_end_date__isnull=True) | models.Q(actual_start_date__isnull=True)), name='CK_WorkOrderRouting_ActualEndDate'),
            models.CheckConstraint(condition=models.Q(actual_resource_hrs__gte=0.0000), name='CK_WorkOrderRouting_ActualResourceHrs'),
            models.CheckConstraint(condition=models.Q(planned_cost__gt=0.00), name='CK_WorkOrderRouting_PlannedCost'),
            models.CheckConstraint(condition=models.Q(actual_cost__gt=0.00), name='CK_WorkOrderRouting_ActualCost'),
        ]

    def __str__(self):
        return f"{self.work_order} / {self.location}"


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
# Hand-written (not generated): data privacy governance.

PRIVACY_NOTICE_VERSION = "1.0"


class PrivacyAcknowledgment(models.Model):
    """One row per user holding the latest recorded acknowledgment of the privacy
    notice. Written on every successful login, so the row always shows the notice
    version the user accepted and when. This is the audit evidence for consent."""

    user = models.OneToOneField("auth.User", on_delete=models.CASCADE, related_name="privacy_acknowledgment")
    version = models.CharField(max_length=10)
    acknowledged_at = models.DateTimeField()

    class Meta:
        verbose_name = "privacy acknowledgment"
        verbose_name_plural = "privacy acknowledgments"

    def __str__(self):
        return f"{self.user} acknowledged v{self.version}"


class AuditLog(models.Model):
    """One row per edit or deletion made through the table pages: who changed which
    record, when, and the old and new values. Written by the shared edit and delete
    views; visible read-only at /manage/ and retained for twelve months per the
    privacy notice."""

    ACTIONS = [("create", "create"), ("update", "update"), ("delete", "delete")]

    user = models.ForeignKey("auth.User", null=True, blank=True, on_delete=models.SET_NULL,
                             related_name="audit_log")
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
