from decimal import Decimal

from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.response import Response

from apps.core.api import PermissionedView, validated
from apps.core.permissions import AnyOf
from apps.scheduling.api import UserBrief

from . import services
from .models import Batch, Item, Purchase, StockMovement, Supplier
from apps.core.concurrency import bump_version, guarded_edit


class ItemSerializer(serializers.ModelSerializer):
    on_hand = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True, default=None)
    usable = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True, default=None)
    is_low = serializers.SerializerMethodField()

    class Meta:
        model = Item
        fields = ["id", "code", "name", "generic_name", "brand_name", "category", "dosage_form", "strength", "unit",
                  "route", "therapeutic_category", "controlled_class", "allergy_groups", "warnings", "default_supplier",
                  "reorder_level", "selling_price", "is_active", "on_hand", "usable", "is_low", "pack_unit",
                  "units_per_pack", "row_version"]

    def get_is_low(self, obj):
        usable = getattr(obj, "usable", None)
        return usable is not None and usable <= obj.reorder_level


class ItemInput(serializers.Serializer):
    code = serializers.CharField(max_length=30)
    name = serializers.CharField(max_length=150)
    generic_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    brand_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    category = serializers.ChoiceField(choices=Item.Category.choices)
    dosage_form = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    strength = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    unit = serializers.CharField(max_length=20, default="unit")
    route = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    therapeutic_category = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")
    controlled_class = serializers.ChoiceField(choices=Item.Controlled.choices, required=False, allow_blank=True, default="")
    allergy_groups = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    warnings = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    default_supplier = serializers.PrimaryKeyRelatedField(queryset=Supplier.objects.all(), required=False,
                                                          allow_null=True, default=None)
    reorder_level = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=0, default=0)
    selling_price = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0, default=0)
    is_active = serializers.BooleanField(default=True)
    pack_unit = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")
    units_per_pack = serializers.DecimalField(max_digits=10, decimal_places=3, min_value=Decimal("0.001"),
                                              required=False, allow_null=True, default=None)


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = ["id", "name", "contact_person", "phone", "email", "address", "tin", "is_active", "row_version"]


class BatchSerializer(serializers.ModelSerializer):
    on_hand = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    item_name = serializers.CharField(source="item.__str__", read_only=True)
    item_code = serializers.CharField(source="item.code", read_only=True)
    unit = serializers.CharField(source="item.unit", read_only=True)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True, default="")

    class Meta:
        model = Batch
        fields = ["id", "item", "item_code", "item_name", "unit", "batch_number", "expiry_date", "unit_cost",
                  "supplier_name", "on_hand", "created_at"]


class MovementSerializer(serializers.ModelSerializer):
    created_by = UserBrief(read_only=True)
    batch_number = serializers.CharField(source="batch.batch_number", read_only=True)
    item_name = serializers.CharField(source="item.__str__", read_only=True)

    class Meta:
        model = StockMovement
        fields = ["id", "item", "item_name", "batch", "batch_number", "kind", "quantity", "reason", "reference_type",
                  "reference_id", "is_override", "created_by", "created_at"]


class PurchaseSerializer(serializers.ModelSerializer):
    supplier = SupplierSerializer(read_only=True)
    received_by = UserBrief(read_only=True)
    line_count = serializers.IntegerField(source="movements.count", read_only=True)

    class Meta:
        model = Purchase
        fields = ["id", "supplier", "supplier_invoice_no", "purchase_date", "notes", "total_cost", "received_by",
                  "line_count", "created_at"]


# Dental staff choose the materials a procedure used, so they may search the item list.
INVENTORY_READ = AnyOf(("inventory.view", "pharmacy.view", "prescriptions.create", "medicines.manage",
                        "dental.procedure.record", "dental.catalog.manage"))


class ItemListCreateView(PermissionedView):
    required_permissions = {"GET": INVENTORY_READ, "POST": AnyOf(("inventory.manage", "medicines.manage"))}

    def get(self, request):
        qs = Item.objects.all()
        if q := request.query_params.get("q", "").strip():
            qs = qs.filter(Q(name__icontains=q) | Q(generic_name__icontains=q) | Q(brand_name__icontains=q)
                           | Q(code__iexact=q))
        if cat := request.query_params.get("category"):
            qs = qs.filter(category=cat)
        active = self.param_bool("active")
        if active is not None:
            qs = qs.filter(is_active=active)
        qs = services.items_with_stock(qs).order_by("name")
        if self.param_bool("low"):
            qs = [i for i in qs if i.usable <= i.reorder_level]
            return Response(ItemSerializer(qs, many=True).data)
        return self.paginate(qs, ItemSerializer)

    def post(self, request):
        item = services.save_item(self.ctx(), validated(ItemInput, request.data))
        return Response(ItemSerializer(services.items_with_stock(Item.objects.filter(pk=item.pk)).get()).data,
                        status=status.HTTP_201_CREATED)


class ItemDetailView(PermissionedView):
    required_permissions = {"GET": INVENTORY_READ, "PATCH": AnyOf(("inventory.manage", "medicines.manage"))}

    def get(self, request, pk):
        item = get_object_or_404(services.items_with_stock(), pk=pk)
        body = ItemSerializer(item).data
        body["batches"] = BatchSerializer(services.batches_with_stock(item).filter(on_hand__gt=0), many=True).data
        return Response(body)

    def patch(self, request, pk):
        data = validated(ItemInput, request.data, partial=True)
        data.pop("code", None)  # codes are permanent identifiers
        with guarded_edit(Item, pk, request, object_type="item", label="item") as item:
            services.save_item(self.ctx(), data, item)
        return Response(ItemSerializer(services.items_with_stock(Item.objects.filter(pk=pk)).get()).data)


class SupplierListCreateView(PermissionedView):
    required_permissions = {"GET": ("inventory.view",), "POST": ("inventory.manage",)}

    def get(self, request):
        return Response(SupplierSerializer(Supplier.objects.order_by("name"), many=True).data)

    def post(self, request):
        s = SupplierSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        supplier = services.save_supplier(self.ctx(), dict(s.validated_data))
        return Response(SupplierSerializer(supplier).data, status=status.HTTP_201_CREATED)


class SupplierDetailView(PermissionedView):
    required_permissions = {"PATCH": ("inventory.manage",)}

    def patch(self, request, pk):
        with guarded_edit(Supplier, pk, request, object_type="supplier", label="supplier") as supplier:
            s = SupplierSerializer(supplier, data=request.data, partial=True)
            s.is_valid(raise_exception=True)
            saved = services.save_supplier(self.ctx(), dict(s.validated_data), supplier)
        return Response(SupplierSerializer(saved).data)


class PurchaseLineInput(serializers.Serializer):
    item_id = serializers.UUIDField()
    batch_number = serializers.CharField(max_length=50)
    expiry_date = serializers.DateField(required=False, allow_null=True)
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=Decimal("0.001"))
    unit_cost = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0, default=0)


class PurchaseInput(serializers.Serializer):
    supplier_id = serializers.UUIDField()
    purchase_date = serializers.DateField()
    supplier_invoice_no = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    notes = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    lines = PurchaseLineInput(many=True)


class PurchaseListCreateView(PermissionedView):
    required_permissions = {"GET": ("inventory.view",), "POST": ("inventory.manage",)}

    def get(self, request):
        qs = Purchase.objects.select_related("supplier", "received_by").order_by("-purchase_date", "-created_at")
        return self.paginate(qs, PurchaseSerializer)

    def post(self, request):
        data = validated(PurchaseInput, request.data)
        supplier = get_object_or_404(Supplier, pk=data["supplier_id"], is_active=True)
        items = {i.pk: i for i in Item.objects.filter(pk__in=[l["item_id"] for l in data["lines"]])}
        lines = []
        for line in data["lines"]:
            if line["item_id"] not in items:
                return Response({"error": {"code": "validation_error", "message": "Unknown item in lines."}}, status=400)
            lines.append({**line, "item": items[line["item_id"]]})
        purchase = services.receive_purchase(self.ctx(), supplier=supplier, purchase_date=data["purchase_date"],
                                             lines=lines, supplier_invoice_no=data["supplier_invoice_no"],
                                             notes=data["notes"])
        return Response(PurchaseSerializer(purchase).data, status=status.HTTP_201_CREATED)


class AdjustmentInput(serializers.Serializer):
    batch_id = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3)
    kind = serializers.ChoiceField(choices=[StockMovement.Kind.ADJUSTMENT, StockMovement.Kind.EXPIRED])
    reason = serializers.CharField(max_length=255)


class MovementListCreateView(PermissionedView):
    required_permissions = {"GET": ("inventory.view",), "POST": ("inventory.adjust",)}

    def get(self, request):
        qs = StockMovement.objects.select_related("item", "batch", "created_by")
        if item := self.param_uuid("item"):
            qs = qs.filter(item_id=item)
        if kind := request.query_params.get("kind"):
            qs = qs.filter(kind=kind)
        return self.paginate(qs.order_by("-created_at"), MovementSerializer)

    def post(self, request):
        data = validated(AdjustmentInput, request.data)
        batch = get_object_or_404(Batch.objects.select_related("item"), pk=data["batch_id"])
        movement = services.adjust_stock(self.ctx(), batch=batch, quantity=data["quantity"], kind=data["kind"],
                                         reason=data["reason"])
        return Response(MovementSerializer(movement).data, status=status.HTTP_201_CREATED)


class StockAlertsView(PermissionedView):
    required_permissions = {"GET": AnyOf(("inventory.view", "pharmacy.view"))}

    def get(self, request):
        days = int(request.query_params.get("days", 90))
        return Response({
            "low_stock": ItemSerializer(services.low_stock_items(), many=True).data,
            "expiring": BatchSerializer(services.expiring_batches(days), many=True).data,
            "expiry_window_days": days,
        })
